"""ZIP code to congressional district, from the Census Bureau's relationship file between the 119th Congress's
districts and 2020 ZIP Code Tabulation Areas (ZCTAs).

ZCTAs are the Census Bureau's areas built from ZIP codes: most ZIP codes have one, but post-office-box-only ZIPs and
some others do not, and a ZCTA can straddle districts. For each ZCTA the file gives every district it overlaps and the
share of its land in each, so the reader is shown every district a ZIP touches, largest first.

The 119th Congress's districts are the ones the sitting members represent until January 3, 2027; for the 120th
Congress (new maps in several states), switch CONGRESS and the URL when the Census Bureau's file is used.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

CONGRESS = 119
URL = f"https://www2.census.gov/geo/docs/maps-data/data/rel2020/cd-sld/tab20_cd{CONGRESS}20_zcta520_natl.txt"
FIPS = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
        "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
        "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
        "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
        "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
        "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY", "72": "PR"}


def parse(text: str) -> dict:
    """{zcta: [[state, district, share of the ZCTA's land], ...]}, largest share first. District 0 is at large;
    DC's and Puerto Rico's delegate seats come as 98 and are kept as 0."""
    rows = csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter="|")
    cd_col = next((c for c in rows.fieldnames or [] if c.startswith("GEOID_CD")), None)
    if not cd_col or "GEOID_ZCTA5_20" not in (rows.fieldnames or []):
        raise ValueError(f"unexpected columns: {rows.fieldnames}")
    parts: dict[str, dict] = {}
    for r in rows:
        z, cd = (r.get("GEOID_ZCTA5_20") or "").strip(), (r.get(cd_col) or "").strip()
        if len(z) != 5 or len(cd) != 4 or cd[:2] not in FIPS or cd[2:] == "ZZ":
            continue
        d = int(cd[2:]) if cd[2:].isdigit() else None
        if d is None:
            continue
        d = 0 if d in (0, 98) else d
        land = float(r.get("AREALAND_PART") or 0)
        key = (FIPS[cd[:2]], d)
        parts.setdefault(z, {})
        parts[z][key] = parts[z].get(key, 0.0) + land
    out = {}
    for z, by in parts.items():
        total = sum(by.values())
        out[z] = sorted(([s, d, round(a / total, 3) if total else round(1 / len(by), 3)] for (s, d), a in by.items()),
                        key=lambda x: (-x[2], x[0], x[1]))
    return out


def fetch(path: Path, get=None) -> dict:
    """Download, parse and save the file; returns {zcta: [...]}."""
    import requests
    get = get or (lambda u: requests.get(u, timeout=120, headers={"User-Agent": "speculum.vote (public record of Congress)"}))
    r = get(URL)
    r.raise_for_status()
    data = parse(r.text)
    if len(data) < 30_000:
        raise ValueError(f"only {len(data)} ZIP code areas; expected about 33,000")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"congress": CONGRESS, "source": URL, "zcta": data}, separators=(",", ":"), sort_keys=True),
                    encoding="utf-8")
    log.info("ZIP code areas: %d, from %s", len(data), URL)
    return data
