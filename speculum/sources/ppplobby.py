"""Lobbying on the Paycheck Protection Program, 2020-21: a one-time read of every quarterly lobbying report (LD-2)
filed for 2020 and 2021, before Speculum's record begins.

A report counts when one of its lobbying activities says "Paycheck Protection Program", or says "PPP" (or "paycheck
protection") together with words about loans (loan, lender, SBA, small business, forgiveness): "PPP" alone also means
public-private partnership, and other bills are named "Paycheck Protection Act" (union dues, firefighters' pay).
A report about PPP that also mentions a fee is marked, because the lenders' processing fees were set by these rules.
A report says what an organization lobbied on, not which side it took. Kept: per organization, its sector, whether it
files its own reports, the quarters, and up to eight of the reports themselves; per quarter, how many reports were read
and how many mention the program. Saved to data/records/ppp_lobbying.json."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from pathlib import Path

from ..lobbysectors import sector as sector_of
from .lobbyspend import BASE, PERIODS, name_key

log = logging.getLogger(__name__)

QUARTERS = [(y, q) for y in (2020, 2021) for q in (1, 2, 3, 4)]
_PPP = re.compile(r"paycheck\s+protection\s+program", re.I)
# Other bills are called "Paycheck Protection Act" (union dues, firefighters' pay): those words alone never count.
_PPP_ABBR = re.compile(r"\bPPP\b|paycheck\s+protection(?!\s+(?:act|program))", re.I)
_LOANISH = re.compile(r"\b(loans?|lenders?|lending|SBA|small business(es)?|forgiv\w*)\b", re.I)
_FEE = re.compile(r"\bfees?\b", re.I)


def mentions_ppp(text: str | None) -> bool:
    t = text or ""
    return bool(_PPP.search(t) or (_PPP_ABBR.search(t) and _LOANISH.search(t)))


def scan(filings, orgs: dict, label: str) -> tuple[int, int]:
    """Add one quarter's filings to `orgs`; returns (reports read, reports mentioning PPP)."""
    n = hits = 0
    for f in filings:
        n += 1
        acts = [a for a in f.get("lobbying_activities") or [] if mentions_ppp(a.get("description"))]
        if not acts:
            continue
        hits += 1
        reg, cli = f.get("registrant") or {}, f.get("client") or {}
        own = bool(cli.get("client_self_select"))
        k = name_key(cli.get("name"))
        if not k:
            continue
        o = orgs.setdefault(k, {"name": cli.get("name"), "sector": None, "own": False, "quarters": [], "reports": [],
                                "n_reports": 0, "fee": 0, "registrants": []})
        o["sector"] = o["sector"] or sector_of(cli.get("general_description") or (reg.get("description") if own else ""),
                                               cli.get("name"), bool(cli.get("client_government_entity")))
        o["own"] = o["own"] or own
        if label not in o["quarters"]:
            o["quarters"].append(label)
        o["n_reports"] += 1
        o["fee"] += any(_FEE.search(a.get("description") or "") for a in acts)
        if len(o["reports"]) < 8 and f.get("filing_uuid"):
            o["reports"].append({"quarter": label, "uuid": f["filing_uuid"]})
        rn = reg.get("name")
        if rn and rn not in o["registrants"] and len(o["registrants"]) < 6:
            o["registrants"].append(rn)
    return n, hits


def merge(orgs: dict, more: dict) -> None:
    for k, o in more.items():
        if k not in orgs:
            orgs[k] = o
            continue
        m = orgs[k]
        m["own"] = m["own"] or o["own"]
        m["sector"] = m["sector"] or o["sector"]
        m["quarters"] += [q for q in o["quarters"] if q not in m["quarters"]]
        m["n_reports"] += o["n_reports"]
        m["fee"] += o["fee"]
        m["reports"] = (m["reports"] + o["reports"])[:8]
        m["registrants"] += [r for r in o["registrants"] if r not in m["registrants"]][: max(0, 6 - len(m["registrants"]))]


def fetch(path: Path, fetch, key: str | None, budget_min: float = 280) -> dict:
    """Pages through each quarter (about 1,000 pages of 25 reports each); resumable: a quarter already complete in
    `path` is kept."""
    fetch.min_interval["lda.gov"] = 0.55 if key else 4.2
    headers = {"Authorization": f"Token {key}"} if key else None
    have = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    orgs, quarters = have.get("orgs_by_key", {}), have.get("quarters", {})
    t0 = time.monotonic()
    for y, q in QUARTERS:
        label = f"{y}-Q{q}"
        if (quarters.get(label) or {}).get("complete"):
            continue
        page, n, hits, complete, qorgs = 1, 0, 0, False, {}
        while True:
            if (time.monotonic() - t0) / 60 > budget_min:
                log.warning("PPP lobbying %s: stopped at page %d for time; run again to finish", label, page)
                break
            data = fetch.get_json("lda", f"ppp_{y}_q{q}_p{page:04d}.json", f"{BASE}/filings/",
                                  params={"filing_year": y, "filing_period": PERIODS[q], "page": page, "page_size": 25},
                                  headers=headers)
            a, b = scan(data.get("results", []), qorgs, label)
            n, hits = n + a, hits + b
            if not data.get("next"):
                complete = True
                break
            page += 1
        if complete:
            merge(orgs, qorgs)
            quarters[label] = {"reports": n, "ppp_reports": hits, "complete": True}
            log.info("PPP lobbying %s: %d reports, %d mention the program", label, n, hits)
        else:
            break                                   # a partial quarter is dropped whole; the next run starts it again
    done = {k for k, v in quarters.items() if v.get("complete")}
    out = {"source": f"{BASE}/filings/", "rule": __doc__.split("\n\n")[1].strip(), "built": date.today().isoformat(),
           "quarters": quarters, "complete": len(done) == len(QUARTERS),
           "orgs_by_key": orgs}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
