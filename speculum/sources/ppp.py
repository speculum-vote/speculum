"""The Paycheck Protection Program (2020-21): what the SBA paid lenders to make the loans, estimated loan by loan.

Source: the SBA's loan-level PPP data (data.sba.gov, dataset "PPP FOIA"), every disbursed loan with its lender and
amount. The SBA paid each lender a processing fee per loan; borrowers could not be charged. What the SBA actually paid
each lender is not published, so the fee is estimated from the SBA's own schedule (Procedural Notices 5000-20036 and
its 2021 update):
- loans approved before December 27, 2020: 5% up to $350,000; 3% above $350,000 and below $2 million; 1% from $2 million;
- loans approved from December 27, 2020 (first and second draw): up to $50,000, 50% of the loan or $2,500, whichever is
  less; 5% up to $350,000; 3% above $350,000 and below $2 million; 1% from $2 million (first draw only; second-draw
  loans were capped at $2 million).
The fee is on the amount disbursed (approved amount less any undisbursed amount); a loan with nothing disbursed earns none.
Only the per-lender totals are kept (data/records/ppp_lenders.json); no borrower is named."""
from __future__ import annotations

import csv
import io
import json
import logging
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

BASE = "https://data.sba.gov/sites/default/files/distribution/SBA-OCA-2022-07-001/"
RELEASE = "240930"
FILES = [f"public_150k_plus_{RELEASE}.csv"] + [f"public_up_to_150k_{i}_{RELEASE}.csv" for i in range(1, 13)]
DATASET = "https://data.sba.gov/dataset/ppp-foia"
NEW_SCHEDULE = date(2020, 12, 27)


def fee(disbursed: float, approved_on: date | None) -> float:
    if disbursed <= 0:
        return 0.0
    if approved_on is not None and approved_on >= NEW_SCHEDULE and disbursed <= 50_000:
        return min(0.5 * disbursed, 2_500.0)
    if disbursed <= 350_000:
        return 0.05 * disbursed
    if disbursed < 2_000_000:
        return 0.03 * disbursed
    return 0.01 * disbursed


def _date(s: str) -> date | None:
    s = (s or "").strip()
    try:
        if "/" in s:
            m, d, y = s.split("/")[:3]
            return date(int(y[:4]), int(m), int(d))
        return date.fromisoformat(s[:10])
    except (ValueError, IndexError):
        return None


def _num(s) -> float:
    try:
        return float(str(s or "0").replace(",", "").replace("$", "") or 0)
    except ValueError:
        return 0.0


BANDS = [(50_000, "up to $50K"), (150_000, "$50K–150K"), (350_000, "$150K–350K"), (2_000_000, "$350K–2M"), (float("inf"), "$2M and up")]


def aggregate(rows) -> dict:
    """rows: dicts with the SBA's column names. Returns per-lender totals and program totals."""
    lenders: dict = defaultdict(lambda: {"loans": 0, "amount": 0.0, "fees": 0.0, "forgiven": 0.0, "second": 0, "small": 0})
    tot = {"loans": 0, "amount": 0.0, "fees": 0.0, "forgiven": 0.0, "first": 0, "second": 0, "skipped": 0}
    bands = {b: {"loans": 0, "amount": 0.0, "fees": 0.0} for _, b in BANDS}
    seen = set()
    for r in rows:
        ln = (r.get("LoanNumber") or "").strip()
        ln = int(ln) if ln.isdigit() else ln          # integers keep 11 million of them small in memory
        if ln and ln in seen:
            continue
        seen.add(ln)
        approved = _num(r.get("CurrentApprovalAmount")) or _num(r.get("InitialApprovalAmount"))
        disbursed = approved - _num(r.get("UndisbursedAmount"))
        if disbursed <= 0:
            tot["skipped"] += 1
            continue
        when = _date(r.get("DateApproved"))
        f = fee(disbursed, when)
        name = " ".join((r.get("OriginatingLender") or "Not stated").split())
        key = name.upper().rstrip(".,")                 # one lender, whatever office made the loan
        L = lenders[key]
        L.setdefault("names", Counter())[name] += 1
        L.setdefault("states", Counter())[(r.get("OriginatingLenderState") or "").strip()] += 1
        L["loans"] += 1
        L["amount"] += disbursed
        L["fees"] += f
        L["forgiven"] += _num(r.get("ForgivenessAmount"))
        second = (r.get("ProcessingMethod") or "").strip().upper() == "PPS"
        L["second"] += second
        L["small"] += disbursed <= 50_000
        tot["loans"] += 1
        tot["amount"] += disbursed
        tot["fees"] += f
        tot["forgiven"] += _num(r.get("ForgivenessAmount"))
        tot["second" if second else "first"] += 1
        band = next(b for lim, b in BANDS if disbursed <= lim)
        bands[band]["loans"] += 1
        bands[band]["amount"] += disbursed
        bands[band]["fees"] += f
    ranked = sorted(lenders.items(), key=lambda kv: -kv[1]["fees"])
    fees_sorted = [v["fees"] for _, v in ranked]
    out_l = [{"name": v["names"].most_common(1)[0][0], "state": v["states"].most_common(1)[0][0], "n_states": len(v["states"]),
              **{x: (round(v[x], 2) if isinstance(v[x], float) else v[x]) for x in v if x not in ("names", "states")}}
             for k, v in ranked]
    return {
        "totals": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in tot.items()},
        "n_lenders": len(lenders),
        "top_shares": {str(n): round(sum(fees_sorted[:n]) / tot["fees"], 4) if tot["fees"] else None for n in (10, 100)},
        "bands": [{"band": b, **{x: round(y, 2) if isinstance(y, float) else y for x, y in bands[b].items()}} for _, b in BANDS],
        "lenders": out_l[:500],
    }


def fetch(path: Path, get=None) -> dict:
    """Stream every file, aggregate, save. About 11 million rows; only totals are kept."""
    import requests

    def rows():
        for name in FILES:
            url = BASE + name
            log.info("PPP: reading %s", url)
            with requests.get(url, stream=True, timeout=(30, 600), headers={"User-Agent": "speculum.vote (public record of Congress)"}) as r:
                r.raise_for_status()
                lines = (line.decode("utf-8", errors="replace") for line in r.iter_lines())
                n = 0
                for row in csv.DictReader(lines):
                    n += 1
                    yield row
                log.info("PPP: %s rows from %s", f"{n:,}", name)
    data = aggregate(rows())
    if data["totals"]["loans"] < 10_000_000:
        raise ValueError(f"only {data['totals']['loans']:,} loans read; expected about 11 million")
    data.update({"source": DATASET, "release": RELEASE, "files": [BASE + f for f in FILES], "built": date.today().isoformat()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    t = data["totals"]
    log.info("PPP: %s loans, $%.1fB disbursed, $%.1fB in estimated lender fees, %s lenders",
             f"{t['loans']:,}", t["amount"] / 1e9, t["fees"] / 1e9, f"{data['n_lenders']:,}")
    return data
