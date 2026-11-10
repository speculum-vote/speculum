"""Organizations that lobbied in 2020-21 and took PPP loans: the SBA's loan-level data matched to lobbying reports.

Matching: a loan counts when the borrower's name, with case, punctuation and legal endings set aside (the rule used
everywhere on the site), equals the name of a client or lobbying firm on a 2020 or 2021 lobbying report, and the
borrower's state is one the reports give for it. Loans to sole proprietors, self-employed individuals and independent
contractors are left out, so no person is named. A matched name is not proof the borrower is the same organization;
each match links to its SBA record and its lobbying reports for checking.

Context, stated on the page: borrowers "primarily engaged in political or lobbying activities" were ineligible (13 CFR
120.110(r)); from December 27, 2020, trade associations and other 501(c)(6) organizations could borrow if lobbying was
no more than 15% of their receipts and activities and their lobbying cost no more than $1 million in the most recent tax
year, measured as reported under the Lobbying Disclosure Act. This file states what each organization reported; it
does not decide whether a loan met the rules. Saved to data/records/ppp_borrowers.json."""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from .lobbyspend import name_key
from .ppp import DATASET, RELEASE, _date, _num, stream_rows

log = logging.getLogger(__name__)

PEOPLE = {"sole proprietorship", "self-employed individuals", "independent contractors"}


def targets(lobbying: dict) -> dict[str, dict]:
    """name key -> {kind, name, states, lobbying by year}: every 2020-21 client and lobbying firm with a state."""
    out = {}
    for k, e in (lobbying.get("firms_by_key") or {}).items():
        if e.get("states"):
            out[k] = {"kind": "firm", "name": e["name"], "states": e["states"],
                      "lobbying": {y: {"firm_income": e.get(y, 0.0)} for y in ("2020", "2021")}}
    for k, e in (lobbying.get("spend_by_key") or {}).items():
        if not e.get("states"):
            continue
        t = out.setdefault(k, {"kind": "client", "name": e["name"], "states": [], "lobbying": {}})
        if t["kind"] == "firm":
            t["kind"] = "firm and client"
        t["states"] = sorted(set(t["states"]) | set(e["states"]))
        for y in ("2020", "2021"):
            t["lobbying"].setdefault(y, {}).update(e.get(y) or {})
    return out


def match(rows, tg: dict[str, dict]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    seen = set()
    for r in rows:
        if (r.get("BusinessType") or "").strip().lower() in PEOPLE:
            continue
        k = name_key(r.get("BorrowerName"))
        t = tg.get(k)
        if not t or (r.get("BorrowerState") or "").strip() not in t["states"]:
            continue
        ln = (r.get("LoanNumber") or "").strip()
        if ln in seen:
            continue
        seen.add(ln)
        approved = _num(r.get("CurrentApprovalAmount")) or _num(r.get("InitialApprovalAmount"))
        when = _date(r.get("DateApproved"))
        e = found.setdefault(k, {**t, "loans": []})
        e["loans"].append({
            "loan": ln, "borrower": " ".join((r.get("BorrowerName") or "").split()),
            "city": (r.get("BorrowerCity") or "").strip().title(), "state": (r.get("BorrowerState") or "").strip(),
            "approved": when.isoformat() if when else None, "amount": round(approved - _num(r.get("UndisbursedAmount")), 2),
            "forgiven": round(_num(r.get("ForgivenessAmount")), 2),
            "draw": "second" if (r.get("ProcessingMethod") or "").strip().upper() == "PPS" else "first",
            "type": (r.get("BusinessType") or "").strip(), "naics": (r.get("NAICSCode") or "").strip(),
            "jobs": int(_num(r.get("JobsReported"))), "lender": " ".join((r.get("OriginatingLender") or "").split())})
    return found


def fetch(lobbying_path: Path, path: Path) -> dict:
    lob = json.loads(lobbying_path.read_text(encoding="utf-8"))
    if not lob.get("complete") or not lob.get("spend_by_key"):
        raise ValueError("data/records/ppp_lobbying.json is not complete or has no 2020-21 amounts; run ppplobby first")
    tg = targets(lob)
    log.info("PPP borrowers: matching against %d lobbying clients and firms", len(tg))
    found = match(stream_rows(), tg)
    out = {"source": DATASET, "release": RELEASE, "rule": __doc__.split("\n\n")[1].strip(), "built": date.today().isoformat(),
           "n_targets": len(tg), "matches": found}
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("PPP borrowers: %d organizations, %d loans, $%.1fM", len(found), sum(len(e["loans"]) for e in found.values()),
             sum(l["amount"] for e in found.values() for l in e["loans"]) / 1e6)
    return out
