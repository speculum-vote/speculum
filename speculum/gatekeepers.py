"""The gatekeepers: what an industry gives the members of the committee that oversees it, against
what it gives every other member of the same chamber.

Most bills that are lobbied never reach a vote; committees decide which bills move. This compares,
for each pairing of an industry with the committee that writes its laws:

  share of seats     committee members / members of the chamber
  share of money     the industry's gifts to committee members / its gifts to the whole chamber
  per member         average gift to a committee member against the average to everyone else
  other money        the same comparison for gifts from every other sector: the control. A committee
                     whose members simply draw more money from everyone shows up here too.

Money: federal campaign contributions reported on LD-203 by organizations that lobby (cleaned as on
member pages). An organization's sector is read from its own description of its business (the rule
on the Bills page), taken across quarters; where it named no bill, from its registration's own
description. Lobbying firms serve many industries, so their gifts count only as "other money".
Committee seats: unitedstates/congress-legislators, current membership.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from .lobbysectors import sector as sector_of

FINANCE = {"banks", "finance", "investment", "insurance"}

# (industry, its sectors, [(chamber, committee codes, committee label)])
PAIRS = [
    ("Banks, finance and insurance", FINANCE,
     [("house", {"HSBA"}, "Financial Services"), ("senate", {"SSBK"}, "Banking, Housing, and Urban Affairs")]),
    ("Health and pharmaceuticals", {"health"},
     [("house", {"HSIF", "HSWM"}, "Energy and Commerce, or Ways and Means"),
      ("senate", {"SSFI", "SSHR"}, "Finance, or Health, Education, Labor, and Pensions")]),
    ("Agriculture and food", {"agriculture"},
     [("house", {"HSAG"}, "Agriculture"), ("senate", {"SSAF"}, "Agriculture, Nutrition, and Forestry")]),
    ("Defense and aerospace", {"defense"},
     [("house", {"HSAS"}, "Armed Services"), ("senate", {"SSAS"}, "Armed Services")]),
    ("Energy, utilities and mining", {"energy"},
     [("house", {"HSIF"}, "Energy and Commerce"), ("senate", {"SSEG"}, "Energy and Natural Resources")]),
    ("Technology, telecom and media", {"tech"},
     [("house", {"HSIF"}, "Energy and Commerce"), ("senate", {"SSCM"}, "Commerce, Science, and Transportation")]),
    ("Transportation", {"transport"},
     [("house", {"HSPW"}, "Transportation and Infrastructure"), ("senate", {"SSCM"}, "Commerce, Science, and Transportation")]),
    ("Labor unions", {"labor"},
     [("house", {"HSED"}, "Education and Workforce"), ("senate", {"SSHR"}, "Health, Education, Labor, and Pensions")]),
]
CHAMBER = {"house": "House", "senate": "Senate"}
TOP = 10


def registrant_sectors(spend: dict | None, registrants: dict) -> dict[str, str]:
    """LD-203 registrant id -> sector. From the organizations that file for themselves (majority across
    quarters), else from the registration's own description. Lobbying firms come out "professional"."""
    votes: dict[str, Counter] = defaultdict(Counter)
    for q in ((spend or {}).get("quarters") or {}).values():
        for name, sec, rid in (q.get("orgs") or {}).values():
            if rid:
                votes[str(rid)][sec] += 1
    out = {r: c.most_common(1)[0][0] for r, c in votes.items()}
    for rid, reg in (registrants or {}).items():
        if rid not in out:
            out[rid] = sector_of(reg.get("description"), reg.get("name"))
    return out


def _avg(xs):
    return sum(xs) / len(xs) if xs else 0.0


def build(members: list[dict], lobbying: dict, spend: dict | None, committees: dict | None) -> dict | None:
    seats = {b: {s["code"] for s in v} for b, v in ((committees or {}).get("seats") or {}).items()}
    if not seats or not lobbying.get("by_member"):
        return None
    sec = registrant_sectors(spend, lobbying.get("registrants") or {})
    money: dict[str, Counter] = defaultdict(Counter)
    total = known = 0.0
    for bio, gifts in lobbying["by_member"].items():
        for g in gifts:
            a = float(g.get("amount") or 0)
            s = sec.get(str(g.get("registrant_id")), "other")
            money[bio][s] += a
            total += a
            known += a if s not in ("other", "professional", "trade") else 0
    titles = {}
    for b, v in ((committees or {}).get("seats") or {}).items():
        for s in v:
            if s.get("title"):
                titles[(b, s["code"])] = s["title"]
    by_chamber = defaultdict(list)
    for m in members:
        by_chamber[m.get("chamber")].append(m)
    groups = []
    for industry, secs, rows in PAIRS:
        out = []
        for chamber, codes, label in rows:
            mem = by_chamber.get(chamber) or []
            if not mem:
                continue
            ind = lambda m: sum(money[m["bioguide"]][s] for s in secs)
            oth = lambda m: sum(v for s, v in money[m["bioguide"]].items() if s not in secs)
            on = [m for m in mem if seats.get(m["bioguide"], set()) & codes]
            off = [m for m in mem if not (seats.get(m["bioguide"], set()) & codes)]
            all_ind = sum(map(ind, mem))
            if not on or not off or not all_ind:
                continue
            a1, a0 = _avg([ind(m) for m in on]), _avg([ind(m) for m in off])
            o1, o0 = _avg([oth(m) for m in on]), _avg([oth(m) for m in off])
            top = sorted(on, key=lambda m: -ind(m))[:TOP]
            out.append({
                "chamber": chamber, "chamber_name": CHAMBER[chamber], "committee": label, "codes": sorted(codes),
                "n_on": len(on), "n_all": len(mem), "seat_share": len(on) / len(mem),
                "money_on": sum(map(ind, on)), "money_all": all_ind, "money_share": sum(map(ind, on)) / all_ind,
                "avg_on": a1, "avg_off": a0, "ratio": a1 / a0 if a0 else None,
                "other_ratio": o1 / o0 if o0 else None,
                "top": [{"bioguide": m["bioguide"], "name": m["name"], "party": m.get("party"),
                         "amount": ind(m), "title": next((titles[(m["bioguide"], c)] for c in sorted(codes)
                                                            if (m["bioguide"], c) in titles), None)} for m in top],
            })
        if out:
            groups.append({"industry": industry, "rows": out})
    lead = next((r for g in groups for r in g["rows"] if r["codes"] == ["HSBA"]), None)
    return {"groups": groups, "years": lobbying.get("years_label"), "total": total,
            "known_share": known / total if total else 0, "lead": lead}
