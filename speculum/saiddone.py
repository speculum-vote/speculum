"""Said & Done: what a group says it works on, beside what it does.

The first measure, "Both sides of the vote": for a bill that came to a final vote, the organizations that named
it on their own lobbying reports (what they said they worked on), and the members they funded on each side of
that vote (what they did). It states a pattern, never a motive: lobbying reports do not say which side an
organization took.

Rules (published on the page and on the Method page), the same for every bill:
- Lobbied: an organization named the bill on a quarterly lobbying report (LD-2) and files its own reports, so
  its registrant is the organization itself. Lobbying firms are left out, since a firm works for many clients
  (the same rule as the Bills pages).
- The vote: in each chamber, the last roll call that decided the measure itself (passage, adoption, agreeing
  to a conference report or the other chamber's amendment, or passage over a veto). Votes on rules, motions,
  amendments and cloture are not the decision. Simple House and Senate resolutions are left out.
- Funded: federal campaign contributions (LD-203) the organization reported, by it or its PAC, to a member who
  cast a yea or a nay on that vote; every contribution reported since 2025, before or after the vote.
  Contributions a lobbyist reports as their own ("Self", or the lobbyist's own name) are not counted.
- Both sides: an organization funded at least one member who voted yes and at least one who voted no.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import lobbysectors as S
from .bills import collect, norm
from .findings import YES, NO, billname

DECISION = re.compile(
    r"^(On Passage( of the Bill)?"
    r"|On Motion to Suspend the Rules and (Pass|Agree|Concur)"
    r"|On Motion to Concur in the (House|Senate) Amendments?"
    r"|On Agreeing to the Conference Report|On the Conference Report"
    r"|On Agreeing to the (Concurrent )?Resolution(, as Amended)?"
    r"|On the (Joint|Concurrent) Resolution|On the Resolution"
    r"|On the Motion to Concur"
    r"|Passage, Objections of the President|On Overriding the Veto|On Passage, Objections)", re.I)

LD2_URL = "https://lda.gov/filings/public/filing/{}/print"
MIN_FUNDERS = 5          # a bill qualifies once this many organizations that lobbied it funded its voters
SELF = {"self", "", "same", "myself"}


def simple_resolution(bill: str) -> bool:
    return norm(bill).startswith(("HRES", "SRES"))


def decisions(rolls: list[dict]) -> list[dict]:
    """The last deciding roll call in each chamber, House first."""
    out = {}
    for v in sorted(rolls, key=lambda v: ((v.get("date") or ""), int(v["number"]) if str(v.get("number", "")).isdigit() else 0)):
        if DECISION.match((v.get("question") or "").strip()):
            out[v["chamber"]] = v
    return [out[c] for c in ("house", "senate") if c in out]


def _personal(r: dict) -> bool:
    """A contribution a lobbyist reports as their own."""
    con = (r.get("contributor") or "").strip()
    if con.lower() in SELF:
        return True
    rb = r.get("reported_by") or ""
    if " (" in rb and rb.endswith(")"):
        lob = re.sub(r"[^a-z]", "", rb[:rb.index(" (")].lower())
        return bool(lob) and re.sub(r"[^a-z]", "", con.lower()) == lob
    return False


def org_giving(lobbying: dict) -> dict[str, dict[str, list[dict]]]:
    """registrant id -> member -> the contributions counted (organization or PAC, never a lobbyist's own)."""
    out: dict = defaultdict(lambda: defaultdict(list))
    for bio, rows in (lobbying.get("by_member") or {}).items():
        for r in rows:
            if (r.get("type") or "").upper() != "FECA" or not r.get("amount") or not r.get("registrant_id") or _personal(r):
                continue
            out[str(r["registrant_id"])][bio].append(r)
    return out


def measure(key: tuple[int, str], lobbied_entry: dict, rolls: list[dict], positions: dict, giving: dict,
            party: dict) -> dict | None:
    """Both sides of the vote for one bill, or None when it has no deciding roll call."""
    dec = decisions(rolls)
    if not dec:
        return None
    side: dict[str, str] = {}                      # member -> "Y" / "N" on their chamber's deciding vote
    votes = []
    for v in dec:
        pos = positions.get(v["id"]) or {}
        y = n = 0
        for bio, p in pos.items():
            s = "Y" if p in YES else "N" if p in NO else None
            if s:
                side[bio] = s
                y += s == "Y"
                n += s == "N"
        votes.append({"id": v["id"], "chamber": v["chamber"], "date": (v.get("date") or "")[:10], "question": v.get("question"),
                      "result": v.get("result"), "url": v.get("url"), "yes": y, "no": n})
    orgs, lobbied_own = [], 0
    files = lobbied_entry.get("files") or {}
    for okey, o in lobbied_entry["orgs"].items():
        rid = o[2]
        if not rid:
            continue
        lobbied_own += 1
        g = giving.get(str(rid)) or {}
        to = {"Y": defaultdict(float), "N": defaultdict(float)}
        filings: dict[str, str] = {}                 # LD-203 report -> its period, for the reader to check
        for bio, rows in g.items():
            s = side.get(bio)
            if not s:
                continue
            for r in rows:
                to[s][bio] += float(r["amount"])
                if r.get("url"):
                    filings.setdefault(r["url"], r.get("period") or "")
        if not to["Y"] and not to["N"]:
            continue

        def part(s):
            pc = defaultdict(int)
            for b in to[s]:
                pc[party.get(b) or "I"] += 1
            return {"members": len(to[s]), "amount": round(sum(to[s].values()), 2),
                    "party": {p: pc[p] for p in ("D", "R", "I") if pc.get(p)}}
        orgs.append({"name": o[0], "sector": o[1], "sector_name": S.NAMES.get(o[1], o[1]), "registrant": str(rid),
                     "both": bool(to["Y"]) and bool(to["N"]), "yes": part("Y"), "no": part("N"),
                     "filings": [{"url": u, "period": p} for u, p in sorted(filings.items(), key=lambda kv: kv[0])][:8],
                     "n_filings": len(filings),
                     # Said: the LD-2 reports that name the bill (filed by the organization or a firm it hired), oldest first.
                     "said": [{"url": LD2_URL.format(u), "quarter": q} for q, u in sorted(set(files.get(okey) or []))][:8],
                     "n_said": len(set(files.get(okey) or []))})
    orgs.sort(key=lambda x: (not x["both"], -(x["yes"]["amount"] + x["no"]["amount"]), (x["name"] or "").lower()))
    both = [o for o in orgs if o["both"]]
    total = lambda rows, s: round(sum(o[s]["amount"] for o in rows), 2)
    cg, b = key
    return {
        "congress": cg, "bill": b, "label": billname(b), "slug": f"{cg}-{b.lower()}",
        "votes": votes, "n_lobbied": len(lobbied_entry["orgs"]), "n_lobbied_own": lobbied_own, "quarters": lobbied_entry.get("quarters", []),
        "n_funders": len(orgs), "n_both": len(both),
        "n_yes_only": sum(1 for o in orgs if o["yes"]["members"] and not o["no"]["members"]),
        "n_no_only": sum(1 for o in orgs if o["no"]["members"] and not o["yes"]["members"]),
        "money": {"yes": total(orgs, "yes"), "no": total(orgs, "no")},
        "money_both": {"yes": total(both, "yes"), "no": total(both, "no")},
        "orgs": orgs,
    }


def build(spend: dict | None, votes: dict, members: list[dict], lobbying: dict, info: dict | None) -> dict:
    """Every bill that qualifies, measured, most-lobbied first."""
    lobbied = collect(spend, info)
    bills_info = (info or {}).get("bills", {})
    party = {m["bioguide"]: m["party"] for m in members}
    for k, p in (votes.get("people") or {}).items():
        party.setdefault(k, (p or {}).get("party"))
    by_bill = defaultdict(list)
    for v in votes.get("votes") or []:
        if v.get("bill") and v.get("type") != "Quorum" and not simple_resolution(v["bill"]):
            by_bill[(int(v.get("congress") or 0), norm(v["bill"]))].append(v)
    giving = org_giving(lobbying)
    positions = votes.get("positions") or {}
    out = []
    for key, rolls in by_bill.items():
        e = lobbied.get(key)
        if not e:
            continue
        m = measure(key, e, rolls, positions, giving, party)
        if not m or m["n_funders"] < MIN_FUNDERS:
            continue
        meta = bills_info.get(f"{key[0]}-{key[1]}") or {}
        m["title"] = next((v.get("title") for v in rolls if v.get("title")), None) or meta.get("title")
        m["info"] = meta
        out.append(m)
    out.sort(key=lambda m: (-m["n_lobbied"], m["congress"], m["bill"]))
    return {"bills": out, "by_slug": {m["slug"]: m for m in out}, "min_funders": MIN_FUNDERS,
            "years": lobbying.get("years_label")}


# Readers' rounds (retired November 16, 2026): verified reader-checkers voted each week on which bill opened next;
# H.R. 1 and H.R. 8800 opened that way. Every qualifying bill is now shown. The code is in git history.
