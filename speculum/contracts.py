"""A case about federal contracts: who won them, what the winners (and the bidders who lost) reported on their own
lobbying reports, who else lobbied on the program, which of the lobbyists came from the agency or the committees,
and whose campaigns the companies' PACs and lobbyists funded.

`freeze` turns the by-hand re-reads of the Senate lobbying database (records/topic_check.json, from
`speculum topiccheck`, and records/issue_search.json, from `speculum issuesearch`) into one frozen record per case,
data/records/case_<slug>.json, so later checks cannot change a published page. `compute` adds the campaign money
from the current snapshot.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

Q = {"first_quarter": 1, "second_quarter": 2, "third_quarter": 3, "fourth_quarter": 4}
PRINT = "https://lda.gov/filings/public/filing/{}/print/"


def _q(r: dict) -> str | None:
    n = Q.get(r.get("period") or "")
    return f"{r['year']}-Q{n}" if n and r.get("year") else None


def company_lobbying(rows: list[dict], client: str, topic: str) -> dict:
    """One company's lobbying, quarter by quarter, from every report naming it as client. A quarter's amount is the
    company's own report when it files one (an organization's own figure already includes what it pays outside
    firms); otherwise the sum of the firms' reports. The latest amendment of each report counts. Also: which reports
    name the topic in their own words, and the first quarter one did."""
    crx, trx = re.compile(client, re.I), re.compile(topic, re.I)
    latest: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: r.get("posted") or ""):
        if not crx.search(r.get("client") or "") or not _q(r):
            continue
        latest[(_q(r), r.get("registrant"), bool(r.get("own")))] = r
    by_q: dict[str, list[dict]] = defaultdict(list)
    for (q, _, _), r in latest.items():
        by_q[q].append(r)
    quarters, total, named, first = [], 0.0, [], None
    for q in sorted(by_q):
        rs = by_q[q]
        own = [r for r in rs if r.get("own")]
        amt = sum(float(r.get("expenses") or 0) for r in own) if own else sum(float(r.get("income") or 0) for r in rs)
        total += amt
        hit = [r for r in rs if any(trx.search(a.get("words") or "") for a in r.get("matches") or [])]
        if hit and first is None:
            first = q
        for r in hit:
            w = next(a["words"] for a in r["matches"] if trx.search(a.get("words") or ""))
            m = trx.search(w)
            a0 = max(0, m.start() - 160)
            if a0:
                a0 = w.find(" ", a0) + 1 or a0          # start on a whole word
            named.append({"quarter": q, "url": PRINT.format(r["uuid"]), "by": r.get("registrant"), "own": bool(r.get("own")),
                          "words": ("…" if a0 else "") + w[a0:m.end() + 200].strip()})
        quarters.append({"quarter": q, "amount": amt, "how": "own" if own else "firms"})
    return {"total": total, "quarters": quarters, "first_named": first, "named": named, "n_named": len(named),
            "own_filer": any(r.get("own") for r in latest.values()),
            "firms": sorted({r.get("registrant") for r in latest.values() if not r.get("own")} - {None})}


_STRIP = re.compile(r"\b(INC|LLC|CORP|CORPORATION|CO|COMPANY|THE|AND AFFILIATES|AFFILIATES|D B A|LTD|L P|LP|USA|US)\b")


def org_key(name: str, aliases: dict[str, str]) -> str:
    n = (name or "").upper()
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", _STRIP.sub(" ", n)).strip()
    return aliases.get(n, n)


def freeze(topic_rows: dict[str, list[dict]], search: dict, cfg: dict) -> dict:
    """The frozen record for one contracts case. `cfg` is the case's `contracts` block."""
    topic = cfg.get("topic") or r"air traffic|\bBNATCS\b|\bFENS\b|FAA network"
    allrows = [r for rows in topic_rows.values() for r in rows]
    seen, rows = set(), []
    for r in allrows:
        if r.get("uuid") not in seen:
            seen.add(r.get("uuid"))
            rows.append(r)
    companies = []
    for c in cfg.get("companies") or []:
        lob = company_lobbying(rows, c["client"], topic) if c.get("client") else None
        companies.append({**{k: v for k, v in c.items() if k != "client"}, "lobbying": lob})
    aliases = {k.upper(): v.upper() for k, v in (cfg.get("aliases") or {}).items()}
    reps = [r for r in search.get("reports") or [] if r.get("matches")]
    orgs: dict[str, dict] = {}
    for r in reps:
        k = org_key(r.get("client"), aliases)
        o = orgs.setdefault(k, {"names": Counter(), "quarters": set(), "reports": 0})
        o["names"][r.get("client")] += 1
        if _q(r):
            o["quarters"].add(_q(r))
        o["reports"] += 1
    org_list = sorted(({"name": o["names"].most_common(1)[0][0], "quarters": len(o["quarters"]), "reports": o["reports"]}
                       for o in orgs.values()), key=lambda o: (-o["quarters"], o["name"]))
    prx = re.compile(cfg.get("posts") or r"$^", re.I)
    people: dict[str, dict] = {}
    for r in reps:
        for a in r["matches"]:
            for l in a.get("lobbyists") or []:
                if l.get("former") and prx.search(l["former"]):
                    p = people.setdefault(l["name"].upper(), {"name": l["name"], "posts": Counter(), "for": set()})
                    p["posts"][l["former"].strip()] += 1
                    p["for"].add(r.get("client"))
    n_lobbyists = len({l["name"].upper() for r in reps for a in r["matches"] for l in a.get("lobbyists") or []})
    former = sorted(({"name": p["name"].title(), "post": p["posts"].most_common(1)[0][0], "for": sorted(p["for"])}
                     for p in people.values()), key=lambda p: p["name"].split()[-1])
    return {"phrases": search.get("_phrases"), "years": search.get("_years"), "n_reports": len(reps),
            "companies": companies, "orgs": org_list, "n_lobbyists": n_lobbyists, "former": former}


def giving(lobbying: dict, committees: dict, panel_codes: set[str], members: list[dict], floor: float = 50_000) -> dict:
    """Per registrant: what its PAC and lobbyists gave to sitting members (LD-203), how much went to members of the
    given panels, and how that compares per member with everyone else. `baseline` is the same ratio across every
    registrant that gave at least `floor`."""
    seats = (committees or {}).get("seats") or {}
    panel = {b for b, v in seats.items() if any(x["code"] in panel_codes for x in v)}
    sitting = set(seats)
    party = {m["bioguide"]: m.get("party") for m in members}
    g, o, n, by_party = defaultdict(float), defaultdict(float), defaultdict(set), defaultdict(Counter)
    for b, rows in (lobbying.get("by_member") or {}).items():
        if b not in sitting:
            continue
        for r in rows:
            rid, a = str(r.get("registrant_id")), float(r.get("amount") or 0)
            (g if b in panel else o)[rid] += a
            n[rid].add(b)
            by_party[rid][party.get(b) or "?"] += a
    P, N = len(panel), len(sitting)

    def ratio(rid):
        po = o[rid] / (N - P) if N > P else 0
        return (g[rid] / P) / po if P and po else None

    base = sorted(r for rid in set(g) | set(o) if g[rid] + o[rid] >= floor and (r := ratio(rid)) is not None)
    out = {}
    for rid in set(g) | set(o):
        tot = g[rid] + o[rid]
        r = ratio(rid)
        out[rid] = {"total": tot, "members": len(n[rid]), "to_panel": g[rid], "panel_members": len(n[rid] & panel),
                    "ratio": r, "percentile": round(100 * sum(v < r for v in base) / len(base)) if r is not None and base and tot >= floor else None,
                    "party": dict(by_party[rid])}
    return {"by_registrant": out, "panel_seats": P, "seats": N, "n_base": len(base),
            "median": statistics.median(base) if base else None}


def compute(case: dict, record: dict, lobbying: dict, committees: dict, members: list[dict]) -> dict:
    cfg = case.get("contracts") or {}
    G = giving(lobbying, committees, set(cfg.get("panels") or []), members)
    names = {k: v.get("name") for k, v in (lobbying.get("registrants") or {}).items()}
    companies = []
    for c in record["companies"]:
        gv = G["by_registrant"].get(str(c.get("registrant_id"))) if c.get("registrant_id") else None
        companies.append({**c, "giving": gv})
    context = [{"name": names.get(str(rid), str(rid)), **G["by_registrant"][str(rid)]}
               for rid in cfg.get("context_givers") or [] if str(rid) in G["by_registrant"]]
    return {**record, "companies": companies, "context_givers": context, "panel_seats": G["panel_seats"], "seats": G["seats"],
            "n_base": G["n_base"], "median": G["median"], "panels": cfg.get("panel_names"), "years": lobbying.get("years_label")}
