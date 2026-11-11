"""Lobbying on the Paycheck Protection Program, 2020-21: a one-time read of every quarterly lobbying report (LD-2)
filed for 2020 and 2021, before Speculum's record begins.

A report counts when one of its lobbying activities says "Paycheck Protection Program", or says "PPP" (or "paycheck
protection") together with words about loans (loan, lender, SBA, small business, forgiveness): "PPP" alone also means
public-private partnership, and other bills are named "Paycheck Protection Act" (union dues, firefighters' pay).
The name of the law "Paycheck Protection Program and Health Care Enhancement Act" (H.R. 266, April 2020) does not count
by itself: it also funded hospitals and testing, and many filers list it among the COVID-19 laws they lobbied on.
Those reports are counted per quarter but no organization is listed for them. A report about PPP that mentions a fee
within 300 characters of the program is marked, because the lenders' processing fees were set by these rules.
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
from urllib.parse import quote

from ..lobbysectors import sector as sector_of
from .lobbyspend import BASE, PERIODS, REGISTRATIONS, _amount, name_key

log = logging.getLogger(__name__)

QUARTERS = [(y, q) for y in (2020, 2021) for q in (1, 2, 3, 4)]
RULE_VERSION = 2     # 2: H.R. 266's name alone does not count; fee within 300 characters; matched words kept;
                     #    amendments counted once; every organization's 2020-21 lobbying amounts kept
_PPP = re.compile(r"paycheck\s+protection\s+program", re.I)
# Other bills are called "Paycheck Protection Act" (union dues, firefighters' pay): those words alone never count.
_PPP_ABBR = re.compile(r"\bPPP\b|paycheck\s+protection(?!\s+(?:act|program))", re.I)
_LOANISH = re.compile(r"\b(loans?|lenders?|lending|SBA|small business(es)?|forgiv\w*)\b", re.I)
_FEE = re.compile(r"\bfees?\b", re.I)
_LAW = re.compile(r"paycheck\s+protection\s+program\s+and\s+health\s*care\s+enhancement\s+act", re.I)


def _strip(text: str | None) -> str:
    return _LAW.sub(lambda m: " " * len(m.group(0)), text or "")      # same length, so positions still line up


def mentions_ppp(text: str | None) -> bool:
    t = _strip(text)
    return bool(_PPP.search(t) or (_PPP_ABBR.search(t) and _LOANISH.search(t)))


def law_only(text: str | None) -> bool:
    """Names H.R. 266 and nothing else about the program."""
    return bool(_LAW.search(text or "")) and not mentions_ppp(text)


def fee_window(text: str | None, width: int = 140) -> str:
    """The words around the first fee mentioned near the program."""
    t = re.sub(r"\s+", " ", text or "")
    st = _strip(t)
    spots = [m.start() for m in list(_PPP.finditer(st)) + list(_PPP_ABBR.finditer(st))]
    for f in _FEE.finditer(st):
        if any(abs(f.start() - p) <= 300 for p in spots):
            a, b = max(0, f.start() - width), min(len(t), f.end() + width)
            return ("…" if a else "") + t[a:b].strip() + ("…" if b < len(t) else "")
    return ""


def fee_near(text: str | None, reach: int = 300) -> bool:
    t = _strip(text)
    spots = [m.start() for m in list(_PPP.finditer(t)) + list(_PPP_ABBR.finditer(t))]
    return any(abs(f.start() - p) <= reach for f in _FEE.finditer(t) for p in spots)


def scan(filings, orgs: dict, label: str, state: dict | None = None) -> tuple[int, int, int]:
    """Add one quarter's filings to `orgs`; returns (reports read, reports mentioning PPP, reports naming only H.R. 266).
    A report amended in the same quarter is counted once (by registrant and client). `state` carries, across a quarter's
    pages, which reports were seen and the latest version's lobbying amount for every report."""
    state = {} if state is None else state
    seen, law_seen, latest = state.setdefault("seen", set()), state.setdefault("law", set()), state.setdefault("spend", {})
    n = hits = law = 0
    for f in filings:
        n += 1
        reg, cli = f.get("registrant") or {}, f.get("client") or {}
        pair = (reg.get("id"), cli.get("id"))
        own = bool(cli.get("client_self_select"))
        if pair[0] and pair[1] and (f.get("filing_type") or "") not in REGISTRATIONS:
            dt = f.get("dt_posted") or ""
            if pair not in latest or dt > latest[pair][0]:
                latest[pair] = (dt, name_key(cli.get("name")), cli.get("name"), own,
                                _amount(f.get("expenses")) if own else _amount(f.get("income")),
                                name_key(reg.get("name")), reg.get("name"), cli.get("state"), reg.get("state"))
        descs = [a.get("description") for a in f.get("lobbying_activities") or []]
        acts = [d for d in descs if mentions_ppp(d)]
        if not acts:
            if any(law_only(d) for d in descs) and pair not in law_seen:
                law_seen.add(pair)
                law += 1
            continue
        if pair in seen:
            continue
        seen.add(pair)
        hits += 1
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
        fees = [d for d in acts if fee_near(d)]
        o["fee"] += bool(fees)
        if fees and not o.get("fee_said"):
            o["fee_said"] = fee_window(fees[0])
            o["fee_report"] = {"quarter": label, "uuid": f.get("filing_uuid")}
        if len(o["reports"]) < 8 and f.get("filing_uuid"):
            r = {"quarter": label, "uuid": f["filing_uuid"]}
            if len(o["reports"]) < 2:
                w = _windows(acts[0], 110)
                r["said"] = w[0] if w else None
            o["reports"].append(r)
        rn = reg.get("name")
        if rn and rn not in o["registrants"] and len(o["registrants"]) < 6:
            o["registrants"].append(rn)
    return n, hits, law


def fold_spend(spend: dict, latest: dict, year: int, firms: dict | None = None) -> None:
    """Each organization's reported lobbying for the year, all issues: what it reported spending on its own reports
    ("own") and what lobbying firms reported being paid for it ("firms"), by name. Both are kept; they overlap when
    an organization's own report includes what it paid its firms. `firms`: each lobbying firm's income, all clients."""
    firms = {} if firms is None else firms
    for dt, k, name, own, amt, rk, rname, cst, rst in latest.values():
        if not k or not amt:
            continue
        e = spend.setdefault(k, {"name": name})
        if cst and cst not in e.setdefault("states", []):
            e["states"].append(cst)
        y = e.setdefault(str(year), {"own": 0.0, "firms": 0.0})
        y["own" if own else "firms"] += amt
        if not own and rk:                     # a lobbying firm: what it was paid, all clients
            f = firms.setdefault(rk, {"name": rname})
            if rst and rst not in f.setdefault("states", []):
                f["states"].append(rst)
            f[str(year)] = f.get(str(year), 0.0) + amt


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
        if o.get("fee_said") and not m.get("fee_said"):
            m["fee_said"], m["fee_report"] = o["fee_said"], o.get("fee_report")
        m["reports"] = (m["reports"] + o["reports"])[:8]
        m["registrants"] += [r for r in o["registrants"] if r not in m["registrants"]][: max(0, 6 - len(m["registrants"]))]


def fetch(path: Path, fetch, key: str | None, budget_min: float = 280, fresh: bool = False) -> dict:
    """Pages through each quarter (about 1,000 pages of 25 reports each); resumable: a quarter already complete in
    `path` is kept."""
    fetch.min_interval["lda.gov"] = 0.55 if key else 4.2
    headers = {"Authorization": f"Token {key}"} if key else None
    have = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if fresh or have.get("rule_version") != RULE_VERSION:
        have = {}
    orgs, quarters, spend = have.get("orgs_by_key", {}), have.get("quarters", {}), have.get("spend_by_key", {})
    firms = have.get("firms_by_key", {})
    t0 = time.monotonic()
    for y, q in QUARTERS:
        label = f"{y}-Q{q}"
        if (quarters.get(label) or {}).get("complete"):
            continue
        page, n, hits, law, complete, qorgs, state = 1, 0, 0, 0, False, {}, {}
        while True:
            if (time.monotonic() - t0) / 60 > budget_min:
                log.warning("PPP lobbying %s: stopped at page %d for time; run again to finish", label, page)
                break
            data = fetch.get_json("lda", f"ppp_{y}_q{q}_p{page:04d}.json", f"{BASE}/filings/",
                                  params={"filing_year": y, "filing_period": PERIODS[q], "page": page, "page_size": 25},
                                  headers=headers)
            a, b, c = scan(data.get("results", []), qorgs, label, state)
            n, hits, law = n + a, hits + b, law + c
            if not data.get("next"):
                complete = True
                break
            page += 1
        if complete:
            merge(orgs, qorgs)
            fold_spend(spend, state.get("spend", {}), y, firms)
            quarters[label] = {"reports": n, "ppp_reports": hits, "law_only_reports": law, "complete": True}
            log.info("PPP lobbying %s: %d reports, %d mention the program", label, n, hits)
        else:
            break                                   # a partial quarter is dropped whole; the next run starts it again
    done = {k for k, v in quarters.items() if v.get("complete")}
    out = {"source": f"{BASE}/filings/", "rule": __doc__.split("\n\n")[1].strip(), "built": date.today().isoformat(),
           "rule_version": RULE_VERSION, "quarters": quarters, "complete": len(done) == len(QUARTERS),
           "orgs_by_key": orgs, "spend_by_key": spend, "firms_by_key": firms}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def _windows(text: str, width: int = 160) -> list[str]:
    t = re.sub(r"\s+", " ", text or "")
    st = _strip(t)
    out = []
    for m in list(_PPP.finditer(st)) + list(_PPP_ABBR.finditer(st)):
        a, b = max(0, m.start() - width), min(len(t), m.end() + width)
        w = t[a:b]
        if not any(w in o or o in w for o in out):
            out.append(w)
    return out[:2]


def spot(path: Path, out: Path, fetch, key: str | None, n: int = 40, seed: int = 2020, names: list[str] = ()) -> dict:
    """Re-read a sample of the matched reports and keep the words that matched, for checking by hand: a fixed-seed
    random sample of organizations plus any named ones. Saved to data/records/ppp_spot.json."""
    import random
    fetch.min_interval["lda.gov"] = 0.55 if key else 4.2
    headers = {"Authorization": f"Token {key}"} if key else None
    orgs = json.loads(path.read_text(encoding="utf-8"))["orgs_by_key"]
    keys = sorted(orgs)
    pick = random.Random(seed).sample(keys, min(n, len(keys))) + [k for k in names if k in orgs]
    rows = []
    for k in dict.fromkeys(pick):
        r = orgs[k]["reports"][0]
        f = fetch.get_json("lda", f"ppp_spot_{r['uuid']}.json", f"{BASE}/filings/{r['uuid']}/", headers=headers)
        cli = f.get("client") or {}
        acts = [a for a in f.get("lobbying_activities") or [] if mentions_ppp(a.get("description"))]
        rows.append({"key": k, "quarter": r["quarter"], "uuid": r["uuid"], "client": cli.get("name"),
                     "description": cli.get("general_description"), "sector": orgs[k]["sector"],
                     "matched": [w for a in acts for w in _windows(a.get("description"))][:3], "still_matches": bool(acts)})
    res = {"seed": seed, "n": len(rows), "rows": rows}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return res


def client_filings(out: Path, fetch, key: str | None, names: list[str], years=(2019, 2020, 2021)) -> dict:
    """Every report naming each client, by year, with the amounts as filed: for checking a figure by hand.
    Saved to data/records/ppp_check.json."""
    fetch.min_interval["lda.gov"] = 0.55 if key else 4.2
    headers = {"Authorization": f"Token {key}"} if key else None
    res = {}
    for name in names:
        rows = []
        for y in years:
            page = 1
            while True:
                data = fetch.get_json("lda", f"check_{name_key(name)}_{y}_p{page}.json",
                                      f"{BASE}/filings/?client_name={quote(name)}&filing_year={y}&page={page}&page_size=25",
                                      headers=headers)
                for f in data.get("results", []):
                    cli, reg = f.get("client") or {}, f.get("registrant") or {}
                    rows.append({"year": f.get("filing_year"), "period": f.get("filing_period"), "type": f.get("filing_type"),
                                 "registrant": reg.get("name"), "client": cli.get("name"), "own": cli.get("client_self_select"),
                                 "income": f.get("income"), "expenses": f.get("expenses"), "posted": f.get("dt_posted"),
                                 "uuid": f.get("filing_uuid")})
                if not data.get("next"):
                    break
                page += 1
        res[name] = sorted(rows, key=lambda r: (r["year"] or 0, r["period"] or "", r["posted"] or ""))
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return res
