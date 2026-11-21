"""What members' leadership PACs spend their money on, from the FEC: for research before anything goes public.

A leadership PAC is a committee a member of Congress sponsors (FEC designation "D"), separate from their campaign.
For every leadership PAC whose sponsor is a current member, this fetches the committee's two-year totals and every
itemized disbursement (Schedule B) in the 2025-26 period, as filed. Saved to data/records/leadpac_spend.json.gz.
"""
from __future__ import annotations

import gzip
import json
import logging
import time
from pathlib import Path

from .fec import BASE

log = logging.getLogger("speculum")

KEEP = ("committee_id", "recipient_name", "recipient_city", "recipient_state", "disbursement_amount", "disbursement_date",
        "disbursement_description", "disbursement_purpose_category", "memo_code", "memo_text", "entity_type",
        "recipient_committee_id", "line_number", "transaction_id", "image_number", "pdf_url", "amendment_indicator")


def _get(fetch, key, name, path, **params):
    return fetch.get_json("fec", name, f"{BASE}{path}", params={"api_key": key, **params})


def leadership_pacs(fetch, key, members: list[dict], cycle: int) -> list[dict]:
    sponsor = {cid: m["bioguide"] for m in members for cid in (m.get("fec_ids") or [])}
    out, page = [], 1
    while True:
        data = _get(fetch, key, f"leadpacs_{cycle}_p{page}.json", "/committees/", designation="D", cycle=cycle,
                    per_page=100, page=page)
        for c in data.get("results", []):
            bios = sorted({sponsor[s] for s in (c.get("sponsor_candidate_ids") or []) if s in sponsor})
            if bios:
                out.append({"committee_id": c["committee_id"], "name": c.get("name"), "sponsors": bios,
                            "sponsor_candidate_ids": c.get("sponsor_candidate_ids"), "treasurer": c.get("treasurer_name")})
        pages = (data.get("pagination") or {}).get("pages") or 1
        if page >= pages:
            break
        page += 1
    return out


def fetch_spend(out: Path, fetch, key: str, members: list[dict], cycle: int = 2026, deadline: float | None = None) -> dict:
    pacs = leadership_pacs(fetch, key, members, cycle)
    log.info("leadership PACs sponsored by current members: %d", len(pacs))
    done = 0
    for p in pacs:
        if deadline and time.time() > deadline:
            log.warning("deadline reached after %d PACs", done)
            break
        t = _get(fetch, key, f"lp_totals_{p['committee_id']}_{cycle}.json", f"/committee/{p['committee_id']}/totals/",
                 cycle=cycle, per_page=5)
        p["totals"] = (t.get("results") or [None])[0]
        rows, params, n = [], {"committee_id": p["committee_id"], "two_year_transaction_period": cycle,
                               "per_page": 100, "sort": "-disbursement_date"}, 0
        while True:
            data = _get(fetch, key, f"lp_sb_{p['committee_id']}_p{n}.json", "/schedules/schedule_b/", **params)
            res = data.get("results") or []
            rows += [{k: r.get(k) for k in KEEP} for r in res]
            last = (data.get("pagination") or {}).get("last_indexes")
            if not res or not last or len(res) < 100:
                break
            params = {**params, **last}
            n += 1
        p["disbursements"] = rows
        p["complete"] = True
        done += 1
    res = {"cycle": cycle, "pacs": pacs, "_summary": {"pacs": len(pacs), "fetched": done,
                                                       "rows": sum(len(p.get("disbursements") or []) for p in pacs)}}
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    return res


def committee_check(out: Path, fetch, key: str, committee_ids: list[str]) -> dict:
    """Every cycle's totals and receipts by contribution size for a few committees, as the FEC reports them:
    for checking a committee's history by hand. Saved to data/records/fec_committee_check.json."""
    res = {}
    for cid in committee_ids:
        info = _get(fetch, key, f"cc_info_{cid}.json", f"/committee/{cid}/")
        totals = _get(fetch, key, f"cc_totals_{cid}.json", f"/committee/{cid}/totals/", per_page=20, sort="-cycle")
        cycles = [t.get("cycle") for t in totals.get("results") or []]
        sizes = {}
        for c in cycles:
            s = _get(fetch, key, f"cc_size_{cid}_{c}.json", "/schedules/schedule_a/by_size/", committee_id=cid, cycle=c, per_page=20)
            sizes[str(c)] = s.get("results") or []
        res[cid] = {"info": (info.get("results") or [None])[0], "totals": totals.get("results") or [], "by_size": sizes}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return res


IE_KEEP = ("committee_id", "expenditure_amount", "expenditure_date", "dissemination_date", "support_oppose_indicator",
           "candidate_id", "candidate_name", "candidate_office", "candidate_office_state", "candidate_party",
           "payee_name", "expenditure_description", "category_code_full", "memo_code", "memo_text", "is_notice",
           "filing_form", "report_type", "report_year", "transaction_id", "image_number", "file_number",
           "amendment_indicator", "previous_file_number", "original_sub_id", "sub_id", "pdf_url", "filing_date",
           "most_recent", "back_reference_transaction_id")
TOTAL_KEEP = ("committee_id", "cycle", "coverage_start_date", "coverage_end_date", "last_report_type_full", "receipts",
              "disbursements", "operating_expenditures", "independent_expenditures", "fed_candidate_committee_contributions",
              "contributions_ie_and_party_expenditures_made_percent")


def ie_fetch(out: Path, fetch, key: str, members: list[dict], cycles=(2024, 2026), batch: int = 20) -> dict:
    """Every independent expenditure (Schedule E, from periodic reports and 24- and 48-hour notices) by current members'
    leadership PACs, and each PAC's latest two-year totals, as filed. Saved to data/records/leadpac_ie.json.gz.
    Notices repeat in the next periodic report: the reader dedupes, this keeps every row as filed."""
    pacs = leadership_pacs(fetch, key, members, max(cycles))
    ids = [p["committee_id"] for p in pacs]
    groups = [ids[i:i + batch] for i in range(0, len(ids), batch)]
    res = {"pacs": pacs, "ie": {}, "totals": {}}
    for cycle in cycles:
        rows, tots = [], []
        for g, chunk in enumerate(groups):
            t = _get(fetch, key, f"ie_tot_{cycle}_g{g}.json", "/totals/pac-party/", committee_id=chunk, cycle=cycle,
                     per_page=100)
            tots += [{k: r.get(k) for k in TOTAL_KEEP} for r in t.get("results") or []]
            params, n = {"committee_id": chunk, "cycle": cycle, "per_page": 100, "sort": "-expenditure_date"}, 0
            while True:
                try:
                    data = _get(fetch, key, f"ie_se_{cycle}_g{g}_p{n}.json", "/schedules/schedule_e/", **params)
                except Exception as exc:  # keep going; the gap is recorded and reported
                    body = getattr(getattr(exc, "response", None), "text", "")[:500]
                    log.error("schedule_e failed for group %d cycle %s page %d: %s %s", g, cycle, n, exc.__class__.__name__, body.replace(key, "***"))
                    res.setdefault("errors", []).append({"cycle": cycle, "group": chunk, "page": n, "error": body.replace(key, "***") or exc.__class__.__name__})  # never str(exc): it holds the URL
                    break
                got = data.get("results") or []
                rows += [{k: r.get(k) for k in IE_KEEP} for r in got]
                last = (data.get("pagination") or {}).get("last_indexes")
                if not got or not last or len(got) < 100:
                    break
                params = {**params, **last}
                n += 1
        res["ie"][str(cycle)] = rows
        res["totals"][str(cycle)] = tots
        log.info("cycle %s: %d IE rows, %d totals", cycle, len(rows), len(tots))
    res["_summary"] = {"pacs": len(pacs), **{f"ie_{c}": len(res["ie"][str(c)]) for c in cycles}}
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    return res
