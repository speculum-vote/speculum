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
            extra["ppp"] = {**d, "lenders": d["lenders"][:25], "fee_rate": round(t["fees"] / t["amount"], 4),
                            "forgiven_share": round(t["forgiven"] / t["amount"], 4)}
            extra["ppp"]["today"] = ppp_today(d["lenders"][:25], spend, lobbying, members)
            extra["ppp"]["years"] = lobbying.get("years_label")
    return {**{k: case.get(k) for k in ("slug", "title", "dek", "congress", "bills", "vehicle")}, "facts": facts, **extra,
            "not_yet": case.get("not_yet"), "orgs": orgs, "groups": groups, "n_orgs": len(orgs), "reports": merged["reports"],
            "measure": m, "former": former, "n_former": len(merged["former"])}
