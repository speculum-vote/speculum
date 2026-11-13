"""Re-read, report by report, every lobbying report our data says names one bill: for checking a bill's lobbying
by hand before anything about it goes public.

The report list comes from the newest snapshot's spend.json (`bill_filings`, every quarter). Each report is fetched
again from the Senate's lobbying disclosure API, and every place its activity descriptions name the bill is kept with
the words around it, the issue code, the registrant and client, and the amount as filed. Saved to
data/records/bill_check.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .lobbyspend import BASE

_PREFIX = {"HR": r"H\.?\s*R\.?", "S": r"S\.?", "HRES": r"H\.?\s*Res\.?", "SRES": r"S\.?\s*Res\.?",
           "HJRES": r"H\.?\s*J\.?\s*Res\.?", "SJRES": r"S\.?\s*J\.?\s*Res\.?"}


def pattern(label: str) -> re.Pattern:
    m = re.fullmatch(r"([A-Z]+)(\d+)", label.upper().replace(" ", "").replace(".", ""))
    if not m or m.group(1) not in _PREFIX:
        raise ValueError(f"bill label not understood: {label}")
    return re.compile(rf"(?<![A-Za-z]){_PREFIX[m.group(1)]}\s*(?:No\.?\s*)?#?\s*{m.group(2)}(?!\d)", re.I)


def report_list(spend: dict, label: str) -> dict[str, list[tuple[str, str]]]:
    """Per organization key, the (quarter, report id) pairs our data counts for the bill."""
    out: dict[str, list[tuple[str, str]]] = {}
    for q, v in sorted((spend.get("quarters") or {}).items()):
        for k, ids in ((v.get("bill_filings") or {}).get(label) or {}).items():
            out.setdefault(k, []).extend((q, u) for u in ids)
    return out


def reread(out: Path, fetch, key: str | None, spend: dict, label: str) -> dict:
    fetch.min_interval["lda.gov"] = 0.55 if key else 4.2
    headers = {"Authorization": f"Token {key}"} if key else None
    pat = pattern(label)
    reports = []
    for org, pairs in report_list(spend, label).items():
        for q, u in pairs:
            f = fetch.get_json("lda", f"billcheck_{u}.json", f"{BASE}/filings/{u}/", headers=headers)
            cli, reg = f.get("client") or {}, f.get("registrant") or {}
            hits = []
            for a in f.get("lobbying_activities") or []:
                d = re.sub(r"\s+", " ", a.get("description") or "")
                for m in pat.finditer(d):
                    hits.append({"issue": a.get("general_issue_code"),
                                 "words": d[max(0, m.start() - 220):m.end() + 220]})
            reports.append({"org_key": org, "quarter": q, "uuid": u, "type": f.get("filing_type"),
                            "year": f.get("filing_year"), "period": f.get("filing_period"),
                            "registrant": reg.get("name"), "client": cli.get("name"),
                            "own": cli.get("client_self_select"), "income": f.get("income"),
                            "expenses": f.get("expenses"), "posted": f.get("dt_posted"), "hits": hits})
    res = {"bill": label, "reports": reports,
           "_summary": {"reports": len(reports), "with_mention": sum(1 for r in reports if r["hits"]),
                        "orgs": len({r["org_key"] for r in reports})}}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return res
