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


def load(data_root: Path) -> list[dict]:
    d = Path(data_root) / "cases"
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.exists() else []


def compute(case: dict, spend: dict | None, votes: dict, members: list[dict], lobbying: dict) -> dict:
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
    rolls = [v for v in votes.get("votes") or [] if int(v.get("congress") or 0) == cg and v.get("bill")
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
    return {**{k: case[k] for k in ("slug", "title", "dek", "congress", "bills", "vehicle")}, "facts": facts,
            "not_yet": case.get("not_yet"), "orgs": orgs, "groups": groups, "n_orgs": len(orgs), "reports": merged["reports"],
            "measure": m, "former": former, "n_former": len(merged["former"])}
