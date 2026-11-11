"""Cases: one decision followed through the record from start to finish, with the same rules for every case.

A case is a small file in data/cases/ that names the bills or resolutions and lists dated facts, each with its
source (or the roll call that is the source). Everything else on a case page is computed from the record every
night, as elsewhere on the site:
- who named the measure on quarterly lobbying reports (LD-2), by sector, with the reports;
- of those that file their own reports, whom they funded among the members who voted (LD-203, as Said & Done);
- lobbyists on those reports who list a past post at a financial regulator or on a banking committee, and whom
  they lobbied for.
A lobbying report does not say which side an organization took, so the page never sorts organizations by side."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from . import lobbysectors as S
from .bills import collect, norm
from .saiddone import measure, org_giving, simple_resolution


# PPP lenders matched to today's lobbying filers by core name (legal endings and words like "Bank, N.A.", "Holdings",
# "Financial", "Bancorp" set aside), plus a bank whose parent company files under another name, listed here.
_FORMS = re.compile(r"\b(THE|INC|INCORPORATED|LLC|L L C|LLP|LP|CORP|CORPORATION|CO|COMPANY|LTD|PLC|NATIONAL ASSOCIATION|N A|NA|"
                    r"A DIVISION OF|HOLDINGS?|GROUP|FINANCIAL|SERVICES|BANCORPORATION|BANCORP|DBA .*)\b")
PARENTS = {"KEYBANK": "KEYCORP", "MANUFACTURERS AND TRADERS TRUST": "M AND T", "HUNTINGTON NATIONAL": "HUNTINGTON BANCSHARES"}


def core_name(n: str | None) -> str:
    s = (n or "").upper().replace("&", " AND ")
    s = re.sub(r"\(.*?\)", " ", s).replace(".", "").replace("'", "")
    s = " ".join(_FORMS.sub(" ", re.sub(r"[^A-Z0-9 ]", " ", s)).split())
    s = re.sub(r"\s+AND$", "", s)
    s = re.sub(r"\s+BANK$", "", s)
    return PARENTS.get(s, s)


def ppp_today(lenders: list[dict], spend: dict | None, lobbying: dict, members: list[dict]) -> list[dict]:
    """For each lender: whether it (or its parent) files its own lobbying reports in 2025-26, what it reported spending,
    how many bills it named, and what it gave sitting members (LD-203), by party."""
    regs: dict = {}
    clients: dict = defaultdict(set)
    for q, v in (spend or {}).get("quarters", {}).items():
        for rid, r in (v.get("registrants") or {}).items():
            if r.get("own"):
                e = regs.setdefault(core_name(r["name"]), {"names": set(), "spend": 0.0, "rids": set()})
                e["names"].add(r["name"])
                e["spend"] += sum((r.get("issues") or {}).values())
                e["rids"].add(str(rid))
        for k, o in (v.get("orgs") or {}).items():
            clients[core_name(o[0])].add(k)
    named = defaultdict(set)
    for (cg, b), e in collect(spend, None).items():
        for k in e["orgs"]:
            named[k].add(b)
    giving = org_giving(lobbying)
    party = {m["bioguide"]: m["party"] for m in members}
    out = []
    for L in lenders:
        c = core_name(L["name"])
        R = regs.get(c)
        bills_named = set().union(*(named[k] for k in clients.get(c, ()))) if clients.get(c) else set()
        g = defaultdict(float)
        for rid in (R or {}).get("rids", ()):
            for bio, rows in (giving.get(rid) or {}).items():
                for row in rows:
                    g[party.get(bio) or "I"] += float(row["amount"])
        out.append({"name": L["name"], "fees": L["fees"], "rate": L.get("rate"), "own": bool(R),
                    "as": sorted(R["names"]) if R else [], "spend": round(R["spend"], 2) if R else 0.0,
                    "bills": len(bills_named), "gave": {p: round(x, 2) for p, x in g.items() if x},
                    "gave_total": round(sum(g.values()), 2)})
    return out


LDA_FILING = "https://lda.gov/filings/public/filing/{}/print/"
# Words that name the fees the SBA paid lenders (or agents), as opposed to other fees in a long list of issues.
LENDER_FEE = re.compile(r"loans?\W+processing\W+fees?|lenders?'?\W+(processing\W+)?fees?|agents?'?\W+fees?|\bPPP\W+(loan\W+)?fees?|"
                        r"fees?\W+(paid\W+)?to\W+(the\W+)?(originating\W+)?(lender|bank|agent)s?", re.I)


def ppp_history(lob: dict, lenders: list[dict]) -> dict | None:
    """Who lobbied on the program while it ran (data/records/ppp_lobbying.json, read once): organizations merged by
    core name, by sector; those whose reports mention fees; and which of the 25 lenders paid the most lobbied on it."""
    if not lob or not lob.get("complete"):
        return None
    merged: dict[str, dict] = {}
    for k, o in (lob.get("orgs_by_key") or {}).items():
        c = core_name(o["name"]) or k
        m = merged.setdefault(c, {"name": o["name"], "sector": o.get("sector") or "other", "own": False, "quarters": set(),
                                  "reports": [], "n_reports": 0, "fee": 0, "registrants": [], "said": None})
        m["own"] = m["own"] or o.get("own")
        m["quarters"] |= set(o.get("quarters") or [])
        m["n_reports"] += o.get("n_reports", 0)
        m["fee"] += o.get("fee", 0)
        if o.get("fee_said") and not m.get("fee_said"):
            m["fee_said"], m["fee_report"] = o["fee_said"], o.get("fee_report")
        for r in o.get("reports") or []:
            if len(m["reports"]) < 4 and r["quarter"] not in {x["quarter"] for x in m["reports"]}:   # one link per quarter
                m["reports"].append({"quarter": r["quarter"], "url": LDA_FILING.format(r["uuid"])})
            m["said"] = m["said"] or r.get("said")
        m["registrants"] += [x for x in o.get("registrants") or [] if x not in m["registrants"]]
    orgs = []
    for c, m in merged.items():
        m["quarters"] = sorted(m["quarters"])
        m["reports"].sort(key=lambda r: r["quarter"])
        m["sector_name"] = S.NAMES.get(m["sector"], m["sector"])
        m["firms"] = [] if m["own"] else m["registrants"][:3]
        orgs.append(m)
    orgs.sort(key=lambda m: (-m["n_reports"], m["name"]))
    by_sector = defaultdict(int)
    for m in orgs:
        by_sector[m["sector"]] += 1
    sectors = [{"key": k, "name": S.NAMES.get(k, k), "group": S.GROUPS.get(k, ""), "n": n}
               for k, n in sorted(by_sector.items(), key=lambda kv: -kv[1])]
    spend = lob.get("spend_by_key") or {}
    spend_core = defaultdict(lambda: {"2020": 0.0, "2021": 0.0})
    for k, e in spend.items():
        for y in ("2020", "2021"):
            spend_core[core_name(e.get("name") or k)][y] += (e.get(y) or {}).get("own", 0.0)
    lenders_out = []
    for L in lenders:
        c = core_name(L["name"])
        m = merged.get(c)
        lenders_out.append({"name": L["name"], "fees": L["fees"], "lobbied": bool(m), "own": bool(m and m["own"]),
                            "bank": bool(re.search(r"BANK\b|\bTRUST\b", L["name"].upper())),
                            "n_reports": m["n_reports"] if m else 0, "quarters": m["quarters"] if m else [],
                            "reports": m["reports"] if m else [], "firms": m["firms"] if m else [],
                            "spent": {y: round(v, 2) for y, v in spend_core[c].items()} if c in spend_core else None})
    q = lob.get("quarters") or {}
    return {"orgs": orgs, "n_orgs": len(orgs), "n_reports": sum(v.get("ppp_reports", 0) for v in q.values()),
            "n_read": sum(v.get("reports", 0) for v in q.values()),
            "law_only": sum(v.get("law_only_reports", 0) for v in q.values()) if any("law_only_reports" in v for v in q.values()) else None,
            "quarters": [{"label": k, **v} for k, v in sorted(q.items())], "sectors": sectors,
            "fee_orgs": sorted([m for m in orgs if m.get("fee_said") and LENDER_FEE.search(m["fee_said"])],
                               key=lambda m: m["name"]),
            "n_fee_any": sum(1 for m in orgs if m["fee"]),
            "lenders": lenders_out, "rule": lob.get("rule"), "rule_version": lob.get("rule_version")}


SBA_LOAN = "https://data.sba.gov/dataset/ppp-foia"
BIG_LOBBY, FEW_JOBS = 250_000, 20


def ppp_borrowers(d: dict) -> dict | None:
    """Organizations on 2020-21 lobbying reports that took PPP loans (data/records/ppp_borrowers.json), after two
    checks: a client named as "X (on behalf of Y)" is dropped, and so is a match where the organization reported more
    than $250,000 a year in its own lobbying but the borrower is a small company (fewer than 20 jobs, a corporation or
    LLC outside the membership-organization industry codes, 813): a gas station that shares a name with an oil company.
    Trade associations with small staffs and large lobbying budgets are kept."""
    if not d or not d.get("matches"):
        return None
    keep, dropped = [], []
    for k, e in d["matches"].items():
        own = max((e["lobbying"].get(y) or {}).get("own", 0.0) for y in ("2020", "2021"))
        jobs = max(l.get("jobs") or 0 for l in e["loans"])
        company = all(l.get("type", "").startswith(("Corporation", "Subchapter S", "Limited  Liability Company", "Limited Liability Company"))
                      and not str(l.get("naics", "")).startswith("813") for l in e["loans"])
        if "BEHALF OF" in e["name"].upper() or (e["kind"] != "firm" and own > BIG_LOBBY and jobs < FEW_JOBS and company):
            dropped.append(e["name"])
            continue
        L = e["loans"]
        lob = {y: round(sum((e["lobbying"].get(y) or {}).values()), 2) for y in ("2020", "2021")}
        types = {l["type"] for l in L}
        keep.append({"name": e["name"], "kind": e["kind"], "loans": sorted(L, key=lambda l: l["approved"] or ""),
                     "amount": round(sum(l["amount"] for l in L), 2), "forgiven": round(sum(l["forgiven"] for l in L), 2),
                     "c6": any(t.startswith("501(c)6") for t in types),
                     "own": {y: (e["lobbying"].get(y) or {}).get("own", 0.0) for y in ("2020", "2021")},
                     "firm_income": {y: (e["lobbying"].get(y) or {}).get("firm_income", 0.0) for y in ("2020", "2021")},
                     "lobbying": lob})
    keep.sort(key=lambda x: -x["amount"])
    # Firms registered to lobby for others whose SBA industry code is legal (5411), consulting (5416) or public
    # relations and advertising (5418) services: a hospital that once registered for a client is not a lobbying firm.
    code = lambda x, pre: any(str(l.get("naics", "")).startswith(pre) for l in x["loans"])
    firms = [x for x in keep if "firm" in x["kind"] and code(x, ("5411", "5416", "5418"))]
    law = [x for x in firms if code(x, "5411")]
    lobby = sorted([x for x in firms if not code(x, "5411")], key=lambda x: -(x["firm_income"]["2020"] or x["firm_income"]["2021"]))
    c6 = sorted([x for x in keep if x["c6"]], key=lambda x: -max(x["own"].values()))
    over = [x for x in c6 if any(v > 1_000_000 for v in x["own"].values())]
    return {"n": len(keep), "n_loans": sum(len(x["loans"]) for x in keep), "amount": sum(x["amount"] for x in keep),
            "forgiven": sum(x["forgiven"] for x in keep), "top": keep[:15], "n_firms": len(firms),
            "law": law[:10], "n_law": len(law), "law_amount": sum(x["amount"] for x in law),
            "lobby": lobby[:20], "n_lobby": len(lobby), "lobby_amount": sum(x["amount"] for x in lobby),
            "lobby_forgiven": sum(x["forgiven"] for x in lobby),
            "lobby_early": sum(1 for x in lobby[:20] if (x["loans"][0]["approved"] or "")[:7] in ("2020-04", "2020-05")), "c6": c6[:15], "n_c6": len(c6),
            "c6_amount": sum(x["amount"] for x in c6), "c6_over": over, "dropped": sorted(dropped),
            "release": d.get("release"), "source": d.get("source") or SBA_LOAN}


def load(data_root: Path) -> list[dict]:
    d = Path(data_root) / "cases"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.exists() else []


def compute(case: dict, spend: dict | None, votes: dict, members: list[dict], lobbying: dict, data_root: Path | None = None) -> dict:
    cg = int(case["congress"])
    lobbied = collect(spend, None)
    merged = {"orgs": {}, "files": defaultdict(list), "former": {}, "former_for": defaultdict(set), "reports": 0}
    for b in case["bills"]:
        e = lobbied.get((cg, b))
        if not e:
            continue
        merged["reports"] += e["reports"]
        for k, o in e["orgs"].items():
            if k not in merged["orgs"] or (o[2] and not merged["orgs"][k][2]):
                merged["orgs"][k] = o
        for k, fs in e["files"].items():
            merged["files"][k].extend(fs)
        merged["former"].update(e["former"])
        for lid, ks in e.get("former_for", {}).items():
            merged["former_for"][lid] |= set(ks)
    party = {m["bioguide"]: m["party"] for m in members}
    for k, p in (votes.get("people") or {}).items():
        party.setdefault(k, (p or {}).get("party"))
    rolls = [v for v in votes.get("votes") or [] if case.get("vehicle") and int(v.get("congress") or 0) == cg and v.get("bill")
             and norm(v["bill"]) == case["vehicle"] and v.get("type") != "Quorum" and not simple_resolution(v["bill"])]
    m = measure((cg, case["vehicle"]), merged, rolls, votes.get("positions") or {}, org_giving(lobbying), party) if rolls else None
    funded = {o["name"]: o for o in (m or {}).get("orgs", [])}
    orgs = []
    for k, o in merged["orgs"].items():
        files = sorted(set(merged["files"].get(k) or []))
        orgs.append({"name": o[0], "sector": o[1], "sector_name": S.NAMES.get(o[1], o[1]), "group": S.GROUPS.get(o[1], "Not described"),
                     "own": bool(o[2]), "reports": [{"quarter": q, "url": f"https://lda.gov/filings/public/filing/{u}/print"} for q, u in files][:8],
                     "n_reports": len(files), "funding": funded.get(o[0])})
    orgs.sort(key=lambda o: (S.GROUP_ORDER.index(o["group"]) if o["group"] in S.GROUP_ORDER else 99, -o["n_reports"], o["name"]))
    groups = [{"name": g, "n": sum(1 for o in orgs if o["group"] == g),
               "funders": sum(1 for o in orgs if o["group"] == g and o["funding"])} for g in S.GROUP_ORDER if any(o["group"] == g for o in orgs)]
    rx = re.compile(case.get("regulators") or r"$^", re.I)
    former = sorted(({"name": p[0], "post": p[1], "for": sorted({merged["orgs"][k][0] for k in merged["former_for"].get(lid, ()) if k in merged["orgs"]})}
                     for lid, p in merged["former"].items() if rx.search(p[1] if len(p) > 1 else "")), key=lambda x: x["name"])
    vote_by_id = {v["id"]: v for v in (m or {}).get("votes", [])}
    facts = [{**f, "roll": vote_by_id.get(f.get("vote"))} for f in case.get("facts") or []]
    extra = {}
    if case.get("dataset") == "ppp":                    # SBA loan data, per lender (speculum/sources/ppp.py)
        p = Path(data_root or ".") / "records" / "ppp_lenders.json"
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            t = d["totals"]
            for L in d["lenders"]:
                L["rate"] = round(L["fees"] / L["amount"], 4) if L["amount"] else None
                L["name"] = re.sub(r",?\s+a division of\s*$", "", L["name"], flags=re.I)   # cut short in the SBA's file
            extra["ppp"] = {**d, "lenders": d["lenders"][:25], "fee_rate": round(t["fees"] / t["amount"], 4),
                            "forgiven_share": round(t["forgiven"] / t["amount"], 4)}
            extra["ppp"]["today"] = ppp_today(d["lenders"][:25], spend, lobbying, members)
            extra["ppp"]["years"] = lobbying.get("years_label")
            hp = Path(data_root or ".") / "records" / "ppp_lobbying.json"
            if hp.exists():
                extra["ppp"]["history"] = ppp_history(json.loads(hp.read_text(encoding="utf-8")), d["lenders"][:25])
            bp = Path(data_root or ".") / "records" / "ppp_borrowers.json"
            if bp.exists():
                extra["ppp"]["borrowers"] = ppp_borrowers(json.loads(bp.read_text(encoding="utf-8")))
                extra["ppp"]["borrowers_public"] = bool(case.get("borrowers_public"))
                extra["ppp"]["borrower_notes"] = case.get("borrower_notes") or []
    return {**{k: case.get(k) for k in ("slug", "title", "dek", "congress", "bills", "vehicle")}, "facts": facts, **extra,
            "not_yet": case.get("not_yet"), "orgs": orgs, "groups": groups, "n_orgs": len(orgs), "reports": merged["reports"],
            "measure": m, "former": former, "n_former": len(merged["former"])}
