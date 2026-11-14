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


AVIATION = r"air traffic|Federal Aviation|\bFAA\b|NextGen|BNATCS|airspace|radar|voice switch|aviation"


def topic_reread(out: Path, fetch, key: str | None, names: list[str], years, words: str = AVIATION) -> dict:
    """Every report for each named client in the given years, read in full: the amount as filed, and each activity
    whose description matches `words` or that lists a matching agency, with its words and the agencies lobbied.
    Saved to data/records/topic_check.json."""
    from urllib.parse import quote
    from .ppplobby import name_key
    fetch.min_interval["lda.gov"] = 0.55 if key else 4.2
    headers = {"Authorization": f"Token {key}"} if key else None
    pat = re.compile(words, re.I)
    res = {"_words": words, "_years": list(years)}
    for name in names:
        rows, seen = [], set()
        for y in years:
            page = 1
            while True:
                data = fetch.get_json("lda", f"topic_{name_key(name)}_{y}_p{page}.json",
                                      f"{BASE}/filings/?client_name={quote(name)}&filing_year={y}&page={page}&page_size=25",
                                      headers=headers)
                for f in data.get("results", []):
                    if f.get("filing_uuid") in seen:
                        continue
                    seen.add(f.get("filing_uuid"))
                    cli, reg = f.get("client") or {}, f.get("registrant") or {}
                    acts = []
                    for a in f.get("lobbying_activities") or []:
                        d = re.sub(r"\s+", " ", a.get("description") or "")
                        ents = [e.get("name") for e in a.get("government_entities") or [] if e.get("name")]
                        if pat.search(d) or any(pat.search(e) for e in ents):
                            acts.append({"issue": a.get("general_issue_code"), "words": d[:900], "entities": ents})
                    rows.append({"year": f.get("filing_year"), "period": f.get("filing_period"), "type": f.get("filing_type"),
                                 "registrant": reg.get("name"), "client": cli.get("name"), "own": cli.get("client_self_select"),
                                 "income": f.get("income"), "expenses": f.get("expenses"), "posted": f.get("dt_posted"),
                                 "uuid": f.get("filing_uuid"), "matches": acts})
                if not data.get("next"):
                    break
                page += 1
        res[name] = sorted(rows, key=lambda r: (r["year"] or 0, r["period"] or "", r["posted"] or ""))
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return res


def issue_search(out: Path, fetch, key: str | None, phrases: list[str], years) -> dict:
    """Every report whose specific lobbying issues contain one of `phrases`, in the given years, found with the
    Senate API's own text filter and then checked against the text again. For each report: the amount as filed, the
    matching activities with their words and agencies, and every lobbyist on those activities with any former
    government post they disclosed. Saved to data/records/issue_search.json."""
    from urllib.parse import quote
    fetch.min_interval["lda.gov"] = 0.55 if key else 4.2
    headers = {"Authorization": f"Token {key}"} if key else None
    pat = re.compile("|".join(re.escape(p) for p in phrases), re.I)
    seen, reports, off = set(), [], 0
    for phrase in phrases:
        for y in years:
            page = 1
            while True:
                data = fetch.get_json("lda", f"issue_{re.sub(r'[^a-z0-9]+', '_', phrase.lower())}_{y}_p{page}.json",
                                      f"{BASE}/filings/?filing_specific_lobbying_issues={quote(phrase)}&filing_year={y}"
                                      f"&page={page}&page_size=25", headers=headers)
                results = data.get("results", [])
                for f in results:
                    u = f.get("filing_uuid")
                    if u in seen:
                        continue
                    seen.add(u)
                    cli, reg = f.get("client") or {}, f.get("registrant") or {}
                    acts = []
                    for a in f.get("lobbying_activities") or []:
                        d = re.sub(r"\s+", " ", a.get("description") or "")
                        if not pat.search(d):
                            continue
                        lob = [{"name": " ".join(x for x in ((l.get("lobbyist") or {}).get("first_name"),
                                                             (l.get("lobbyist") or {}).get("last_name")) if x),
                                "former": l.get("covered_position") or "", "new": l.get("new")}
                               for l in a.get("lobbyists") or []]
                        acts.append({"issue": a.get("general_issue_code"), "words": d[:1200],
                                     "entities": [e.get("name") for e in a.get("government_entities") or [] if e.get("name")],
                                     "lobbyists": lob})
                    if not acts:
                        off += 1
                    reports.append({"year": f.get("filing_year"), "period": f.get("filing_period"), "type": f.get("filing_type"),
                                    "registrant": reg.get("name"), "registrant_id": reg.get("id"), "client": cli.get("name"),
                                    "client_id": cli.get("id"), "own": cli.get("client_self_select"),
                                    "income": f.get("income"), "expenses": f.get("expenses"), "posted": f.get("dt_posted"),
                                    "uuid": u, "matches": acts})
                # The filter must be working: if most of a page does not contain the phrase, stop rather than read everything.
                if page == 1 and results and sum(1 for r in reports[-len(results):] if not r["matches"]) > len(results) / 2:
                    raise RuntimeError(f"text filter not applied for {phrase!r}: stopping")
                if not data.get("next"):
                    break
                page += 1
    res = {"_phrases": phrases, "_years": list(years), "_without_match": off, "reports": reports}
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return res
