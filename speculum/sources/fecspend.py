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
