"""The drafter: asks Claude to research a chain's mechanism and outcome links.

It runs only when ANTHROPIC_API_KEY is set, only for chains that have no research yet, and it writes
drafts, never approvals. Its output lands in data/chains/drafts/<chain id>.json for a reviewer to read,
correct and merge into data/chains/research.json. Nothing it writes reaches a reader as fact until a
person approves the chain in data/chains/reviews.json.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import requests

log = logging.getLogger("speculum.interpret")

API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("SPECULUM_MODEL", "claude-sonnet-5-5")

SYSTEM = """You research consequence chains for Speculum, a nonpartisan record of the US Congress.
A chain follows one recorded decision to what happened to people afterwards. You draft two kinds of link:

mechanism: exactly what the decision changed (for an arms sale: items, value, recipient, named contractors,
the notification number) from the bill text, DSCA, State Department or CRS.

outcomes: what happened to civilians afterwards, each with one evidence grade:
  documented  an official or authoritative investigative record ties weapons or actions of this kind from
              this decision's recipient to specific harm (UN panels and commissions, US government reports,
              court orders, forensic investigations that identified US-made munitions at strike sites)
  estimated   authoritative aggregate figures for the conflict (UN OCHA, UN agencies, IPC, peer-reviewed)
  associated  credible reporting of a pattern without direct linkage

Rules you never break:
- Only state what a source you opened says. Give figures with the date they apply to.
- Prefer primary documents (UN, US government, courts, SIPRI). Use news only for original forensic work.
- Record the subject government's response or a credible dispute beside each outcome when one exists.
- Record harm a decision prevented as faithfully as harm it caused.
- Never characterise anyone's intent, and never call a person or a government good or evil.
- If nothing credible ties the decision to harm, say so; that is a valid finding.
- Write as a record, in the third person: never "I", "we" or "my".

Answer with one JSON object and nothing else:
{"mechanism": {"items": "...", "value": "...", "contractors": ["..."], "notification": "...",
               "proceeded": "...", "sources": [{"title": "...", "url": "...", "publisher": "...", "date": "..."}]},
 "outcomes": [{"country": "...", "grade": "documented|estimated|associated", "claim": "...",
               "source": {"title": "...", "url": "...", "publisher": "...", "date": "..."}, "counterpoint": "..."}],
 "notes": "anything uncertain or contested"}"""


SYSTEM_RULE = """You research consequence chains for Speculum, a nonpartisan record of the US Congress.
A chain follows one recorded decision to what happened to people afterwards. This decision is a joint resolution
under the Congressional Review Act to overturn a federal agency's rule. You draft two kinds of link:

mechanism: exactly what the rule did and what the resolution changed, from the Federal Register, the agency's
own regulatory impact analysis or economic analysis, govinfo.gov, the Congressional Research Service, GAO or
the Congressional Budget Office:
  rule        the rule's name and Federal Register citation, its publication and effective dates
  required    what it required or changed, and of whom
  benefits    the agency's own estimate of the rule's benefits, with figures, units and the period they cover
  costs       the agency's own estimate of the rule's costs, from the same analysis
  agency_reasons   the agency's stated purpose
  sponsor_reasons  the stated reasons of the resolution's sponsors and supporters, from their own statements
  status      what happened: whether the resolution became law (and its Public Law number) or failed, and
              therefore whether the rule is void or still in force

outcomes: what happened to people afterwards, or what official analysis expects, each with one evidence grade:
  documented  an official record of what actually followed (agency data, GAO, inspector general, court records)
  estimated   an official or peer-reviewed estimate: the agency's regulatory impact analysis, CBO, or a
              peer-reviewed study. A forecast made before the vote is an estimate, never a documented outcome.
  associated  credible reporting or analysis of a pattern without direct evidence for the specific claim

Rules you never break:
- Only state what a source you opened says. Give figures with the date and period they apply to.
- Give the agency's estimated costs as faithfully as its estimated benefits, from the same analysis, and record
  any official dispute of those estimates (a CBO, GAO or court finding) beside them.
- Record harm the rule's removal prevented, or burden it lifted, as faithfully as harm it allowed.
- Prefer primary documents. Use news only for original reporting of what followed.
- Never characterise anyone's intent, and never call a person, party, company or agency good or evil.
- If nothing credible records what followed, say so; that is a valid finding.

Every item you write is checked, on its own, by an independent checker who opens only the sources that item
cites, reads them strictly and publishes nothing that adds a figure, date, attribution or degree of certainty
its sources do not state. Write so that each item can pass:
- One fact per outcome: one figure, or figures stated together in one sentence or table row of one source.
  Split anything else into separate outcomes. Each outcome carries "quote", the exact sentence (or table row)
  from its source that states it, and "locator", where in the source it is (section, heading or page).
- A counterpoint must come from the outcome's own source; a response from elsewhere is its own outcome.
- Each record field cites only the sources that state it, in "field_sources" (positions in "sources", from 0),
  and says nothing those sources do not. Keep fields short; leave a field out rather than guess.
- Copy figures, units, dates and periods exactly as the source gives them (for example "full-fuel-cycle"
  savings stay full-fuel-cycle; a range stays a range).
- Congress.gov cannot be opened by the checker. For a law's number, text or date cite govinfo.gov (Public
  Law and Statutes at Large), for votes the Clerk of the House or Senate.gov.
- Write as a record, in the third person: never "I", "we" or "my". Not "I found no estimate" but "The rule
  gives no dollar estimate of its benefits."

Answer with one JSON object and nothing else:
{"mechanism": {"rule": "...", "agency": "...", "federal_register": "...", "published": "YYYY-MM-DD", "effective": "YYYY-MM-DD",
               "required": "...", "benefits": "...", "costs": "...", "agency_reasons": "...", "sponsor_reasons": "...",
               "status": "...", "sources": [{"title": "...", "url": "...", "publisher": "...", "date": "..."}],
               "field_sources": {"rule": [0], "required": [0], "benefits": [1], "costs": [1], "status": [2]}},
 "outcomes": [{"grade": "documented|estimated|associated", "claim": "...", "date": "YYYY-MM-DD", "quote": "...", "locator": "...",
               "source": {"title": "...", "url": "...", "publisher": "...", "date": "..."}, "counterpoint": "..."}],
 "notes": "anything uncertain or contested"}"""


_COMMON = """
Evidence grades for outcomes:
  documented  an official record of what actually followed (government data, GAO, inspectors general, courts,
              UN bodies, forensic or investigative records that identify what happened and to whom)
  estimated   an official or peer-reviewed estimate (CBO, an agency's own analysis, UN agencies, peer-reviewed
              studies). A forecast made before the vote is an estimate, never a documented outcome.
  associated  credible reporting or analysis of a pattern without direct evidence for the specific claim

Rules you never break:
- Only state what a source you opened says. Give figures with the date and period they apply to.
- Give estimated costs as faithfully as estimated benefits, from the same analysis, and record any official
  dispute of an estimate beside it.
- Record harm a decision prevented, or burden it lifted, as faithfully as harm it caused or allowed.
- Give the stated reasons of both sides in their own terms, from their own statements.
- Prefer primary documents. Use news only for original reporting of what followed.
- Never characterise anyone's intent, and never call a person, party, company, country or agency good or evil.
- If nothing credible records what followed, say so; that is a valid finding.

Every item you write is checked, on its own, by an independent checker who opens only the sources that item
cites, reads them strictly and publishes nothing that adds a figure, date, attribution or degree of certainty
its sources do not state. Write so that each item can pass:
- One fact per outcome: one figure, or figures stated together in one sentence or table row of one source.
  Split anything else into separate outcomes. Each outcome carries "quote", the exact sentence (or table row)
  from its source that states it, and "locator", where in the source it is (section, heading or page).
- A counterpoint must come from the outcome's own source; a response from elsewhere is its own outcome.
- Each record field cites only the sources that state it, in "field_sources" (positions in "sources", from 0),
  and says nothing those sources do not. Keep fields short; leave a field out rather than guess.
- Copy figures, units, dates and periods exactly as the source gives them (for example "full-fuel-cycle"
  savings stay full-fuel-cycle; a range stays a range).
- Congress.gov cannot be opened by the checker. For a law's number, text or date cite govinfo.gov (Public
  Law and Statutes at Large), for votes the Clerk of the House or Senate.gov.
- Write as a record, in the third person: never "I", "we" or "my". Not "I found no estimate" but "The rule
  gives no dollar estimate of its benefits."

Answer with one JSON object and nothing else:
{"mechanism": {MECHANISM, "status": "...", "sources": [{"title": "...", "url": "...", "publisher": "...", "date": "..."}],
               "field_sources": {"<field>": [0, 1], "status": [2]}},
 "outcomes": [{"grade": "documented|estimated|associated", "claim": "...", "date": "YYYY-MM-DD", "quote": "...", "locator": "...",
               "source": {"title": "...", "url": "...", "publisher": "...", "date": "..."}, "counterpoint": "..."}],
 "notes": "anything uncertain or contested"}"""

_HEAD = """You research consequence chains for Speculum, a nonpartisan record of the US Congress.
A chain follows one recorded decision to what happened to people afterwards. """

BRIEFS = {
    "reconciliation": _HEAD + """This decision is a budget reconciliation bill. You draft:

mechanism: what the bill changed, from the enacted text, Congress.gov, the Congressional Budget Office, the Joint
Committee on Taxation and the Congressional Research Service:
  summary          its major provisions: taxes, spending programs, eligibility rules, the debt limit
  budget_effect    CBO's (and JCT's) estimate of its effect on deficits, with the period it covers
  distribution     CBO's estimate of its effects on households by income
  sponsor_reasons  supporters' stated reasons; opponent_reasons: opponents' stated objections
  status           whether it became law (and its Public Law number) or failed

outcomes: what happened to people afterwards, or what official analysis expects (for example coverage, benefits,
taxes paid, prices or jobs), by group affected.""".replace("{MECHANISM}", ""),
    "emergencies": _HEAD + """This decision is a joint resolution to end a national emergency under the National
Emergencies Act. You draft:

mechanism: what the emergency did, from the Federal Register, the executive order or proclamation, CRS, CBO,
the US International Trade Commission or the agencies carrying it out:
  declared           when and by what order it was declared, and what it imposed or allowed (for tariffs: the
                     rates, the goods and countries covered, and changes since)
  estimates          official estimates of its effects (revenue, prices, trade volumes), with periods
  executive_reasons  the stated basis for the emergency; sponsor_reasons: the resolution's sponsors' stated reasons
  status             whether the resolution passed either chamber or became law, and whether the emergency continues

outcomes: what happened to people afterwards (prices paid, jobs, businesses, trading partners' responses), or
what official analysis expects.""",
    "war-powers": _HEAD + """This decision is a resolution or bill directing the removal of United States Armed Forces
from hostilities under the War Powers Resolution. You draft:

mechanism: the hostilities, from the President's War Powers reports, the Department of Defense, CRS and official
statements:
  hostilities        what operations, where, since when and at what scale, and what Congress had or had not authorized
  executive_reasons  the administration's stated legal basis; sponsor_reasons: the resolution's sponsors' stated reasons
  status             what happened to the resolution, and whether the hostilities continued

outcomes: what happened to people afterwards: civilian and military casualties, displacement, damage, costs, each
from UN bodies, official records or forensic investigations, with any official dispute beside it.""",
}
for _k in BRIEFS:
    _MECH = {"reconciliation": '"summary": "...", "budget_effect": "...", "distribution": "...", "sponsor_reasons": "...", "opponent_reasons": "..."',
             "emergencies": '"declared": "...", "estimates": "...", "executive_reasons": "...", "sponsor_reasons": "..."',
             "war-powers": '"hostilities": "...", "executive_reasons": "...", "sponsor_reasons": "..."'}[_k]
    BRIEFS[_k] = BRIEFS[_k] + _COMMON.replace("{MECHANISM", "{" + _MECH)


def _prompt_rule(chain: dict) -> str:
    votes = "; ".join(f"{(v.get('chamber') or '').title()} {v['date']}: {v['question']}, {v['result']} ({v['yeas']}-{v['nays']})"
                      for v in chain["votes"])
    return (f"Decision: {chain['title']} ({chain['bill']}, {chain['congress']}th Congress). "
            + (f"Agency: {chain.get('agency')}. Rule: {chain.get('rule_title')}. " if chain.get("agency") else
               f"{(chain.get('page') or {}).get('subject_label', 'Subject')}: {chain.get('subject') or 'not named'}. ")
            + f"Recorded votes: {votes}. "
            f"Latest action: {chain.get('latest_action_text') or 'unknown'}. Draft the mechanism and outcome links.")


def _prompt(chain: dict) -> str:
    v = chain["votes"][-1]
    return (f"Decision: {chain['title']} ({chain['bill']}, {chain['congress']}th Congress). "
            f"Last recorded Senate vote {v['date']}: {v['question']}, {v['result']} ({v['yeas']}-{v['nays']}). "
            f"Recipient: {chain.get('country')}. Rule: {chain['rule_name']}. Draft the mechanism and outcome links.")


def draft(chain: dict, key: str, max_searches: int = 8) -> dict:
    theme = chain.get("rule") or "arms-sales"
    system = SYSTEM if theme == "arms-sales" else SYSTEM_RULE if theme == "rules-overturned" else BRIEFS[theme]
    resp = requests.post(API, timeout=600, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, json={
        "model": MODEL, "max_tokens": 8000, "system": system,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}],
        "messages": [{"role": "user", "content": _prompt(chain) if theme == "arms-sales" else _prompt_rule(chain)}]})
    resp.raise_for_status()
    body = resp.json()
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("drafter returned no JSON")
    out = json.loads(m.group(0))
    out["_drafted"] = {"by": body.get("model", MODEL), "on": date.today().isoformat(), "status": "draft",
                       "usage": body.get("usage")}
    return out


def check() -> str:
    """One small live request with one web search, to prove the key, model and tool all work."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    resp = requests.post(API, timeout=120, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, json={
        "model": MODEL, "max_tokens": 300,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
        "messages": [{"role": "user", "content": "Search once for the DSCA major arms sales page and reply with its URL only."}]})
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:500]}")
    body = resp.json()
    used = sum(1 for b in body.get("content", []) if b.get("type") == "server_tool_use")
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text").strip()
    return f"model={body.get('model')} searches={used} usage={body.get('usage')} reply={text[:200]!r}"


def draft_missing(chains: list[dict], drafts_dir: Path, limit: int = 3) -> list[str]:
    """Draft research for up to `limit` chains that have neither reviewed research nor a draft."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        log.info("no ANTHROPIC_API_KEY; skipping the drafter")
        return []
    drafts_dir.mkdir(parents=True, exist_ok=True)
    done = []
    # Resolutions that became law first (their rules are void, so what followed is a matter of record), oldest
    # first, since older decisions have the longest record; a fixed order, the same every night.
    for ch in sorted(chains, key=lambda c: (not c.get("enacted"), c.get("date") or "")):
        if len(done) >= limit:
            break
        path = drafts_dir / f"{ch['id']}.json"
        if ch.get("mechanism") or path.exists():
            continue
        try:
            path.write_text(json.dumps(draft(ch, key), indent=1, ensure_ascii=False), encoding="utf-8")
            done.append(ch["id"])
            log.info("drafted %s", ch["id"])
        except Exception:
            log.exception("drafting %s failed", ch["id"])
    return done


# ---------------------------------------------------------------------------------------------------
# Revision. A drafted claim the source check did not pass goes back once, with the checker's note and the
# passages it quoted, to be narrowed or corrected to what its own sources state. Nothing new may be added:
# no new facts, figures or sources. A claim that fails again stays off the site. Reviewed research
# (data/chains/research.json) is never touched here.

FAILED = {"partly_supported", "not_supported", "grade_too_strong"}
_NARRATES = re.compile(r"\b(?:I (?:found|could|did|was|located|searched|saw|checked|am|have|cannot|can't|identified|read|confirmed|note)"
                       r"|my (?:search|review|research)|we (?:found|could not|did not find))\b", re.I)
VOICE = ("Style: the item narrates the research in the first person (for example 'I found no estimate'). Restate it "
         "as a record in the third person (for example 'The rule gives no dollar estimate'), changing no fact.")


def narrates(item) -> bool:
    """Whether research speaks as 'I' or 'we' outside quotation marks (quoted statements are left alone)."""
    text = item if isinstance(item, str) else " ".join(str(item.get(k) or "") for k in ("claim", "counterpoint", "text", "note"))
    return bool(_NARRATES.search(re.sub(r"[\"\u201c][^\"\u201d]*[\"\u201d]", " ", text)))


def _with_voice(check: dict | None) -> dict:
    c = dict(check or {"result": "supported", "note": ""})
    c["note"] = ((c.get("note") or "") + " " + VOICE).strip()
    return c

REVISER = """You correct one item of research for Speculum, a nonpartisan record of the US Congress, after an
independent checker read its sources. You are given the item, the checker's verdict and note, and passages the
checker quoted from the sources.

Return the item corrected so that its own sources support every word of it:
- Remove or correct exactly what the note says the sources do not state. Keep what the note confirms.
- Never add a fact, figure, date, source or degree of certainty. You may only narrow, correct or remove.
- If the note says a source could not be read, remove what rests only on that source.
- If the note says the evidence grade is too strong, lower it.
- Keep "quote" (an exact passage from the source that states the item) and "locator" if they are right; correct
  them from the checker's quoted passages if they are not.
- If nothing supported remains, answer {"drop": true}.

Answer with one JSON object and nothing else: the corrected item in the same shape it came in, or {"drop": true}."""

SPLITTER = REVISER + """

This item is a whole record that was checked at once. Return it as a record whose fields are checked one by
one: the same fields, corrected as above, plus "sources" (the same list, unchanged) and "field_sources",
which gives for each field the positions (from 0) of the sources that state it. Leave out any field the note
says the sources do not support."""


def _revise_call(key: str, system: str, item: dict, check: dict) -> dict:
    msg = (f"Item (JSON):\n{json.dumps(item, ensure_ascii=False, indent=1)}\n\n"
           f"Checker's verdict: {check.get('result')}\nChecker's note: {check.get('note') or '(none)'}\n"
           f"Passages the checker quoted:\n" + "\n".join(f"- {q}" for q in check.get("quotes") or []) )
    resp = requests.post(API, timeout=600, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, json={
        "model": MODEL, "max_tokens": 6000, "system": system, "messages": [{"role": "user", "content": msg}]})
    resp.raise_for_status()
    text = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text")
    start = text.find("{")
    if start < 0:
        raise ValueError("reviser returned no JSON")
    out, _ = json.JSONDecoder().raw_decode(text[start:])
    return out


def revise_failed(drafts_dir: Path, checks: dict, limit: int = 20, key: str | None = None, call=None) -> list[str]:
    """Revise, once each, drafted claims the source check did not pass. `call` is for tests."""
    from .chains import claim_fp, record_fields
    key = key or os.environ.get("ANTHROPIC_API_KEY")
    if not key and call is None:
        log.info("no ANTHROPIC_API_KEY; skipping revisions")
        return []
    call = call or (lambda system, item, check: _revise_call(key, system, item, check))
    done = []
    for path in sorted(Path(drafts_dir).glob("*.json")) if Path(drafts_dir).exists() else []:
        d = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        # Outcomes
        kept = []
        for o in d.get("outcomes") or []:
            c = checks.get(claim_fp(o))
            failed = bool(c and c.get("result") in FAILED and not o.get("_revised"))
            voice = narrates(o) and not o.get("_voiced")
            if len(done) < limit and (failed or voice):
                if voice:
                    c = _with_voice(c if failed else None)
                try:
                    new = call(REVISER, {k: v for k, v in o.items() if not k.startswith("_")}, c)
                except Exception as exc:
                    log.warning("revising an outcome of %s failed: %s", path.stem, exc)
                    kept.append(o)
                    continue
                done.append(f"{path.stem}: outcome")
                changed = True
                if new.get("drop"):
                    continue
                kept.append({**new, **({"_revised": 1} if failed or o.get("_revised") else {}), **({"_voiced": 1} if voice or o.get("_voiced") else {})})
            else:
                kept.append(o)
        d["outcomes"] = kept
        mx = d.get("mechanism")
        if mx:
            fields = record_fields(mx)
            if not fields:                                    # an old whole record: split it into checked fields
                c = checks.get(claim_fp(mx))
                if len(done) < limit and c and c.get("result") in FAILED and not mx.get("_revised"):
                    try:
                        new = call(SPLITTER, {k: v for k, v in mx.items() if not k.startswith("_")}, c)
                        if new.get("drop"):
                            d["mechanism"] = None
                        else:
                            new.setdefault("sources", mx.get("sources") or [])
                            d["mechanism"] = {**new, "_revised": 1}
                        done.append(f"{path.stem}: record")
                        changed = True
                    except Exception as exc:
                        log.warning("revising the record of %s failed: %s", path.stem, exc)
            else:
                revised = set(mx.get("_revised_fields") or [])
                voiced = set(mx.get("_voiced_fields") or [])
                for k, f in fields.items():
                    c = checks.get(f["fp"])
                    failed = bool(c and c.get("result") in FAILED and k not in revised)
                    voice = narrates(f["item"].get("text") or "") and k not in voiced
                    if len(done) >= limit or not (failed or voice):
                        continue
                    if voice:
                        c = _with_voice(c if failed else None)
                    try:
                        new = call(REVISER, f["item"], c)
                    except Exception as exc:
                        log.warning("revising %s of %s failed: %s", k, path.stem, exc)
                        continue
                    keys = list(f["item"].get("record", {})) if k == "header" else [k]
                    if new.get("drop"):
                        for kk in keys:
                            mx.pop(kk, None)
                    elif k == "header" and isinstance(new.get("record"), dict):
                        for kk in keys:
                            mx.pop(kk, None)
                        mx.update({kk: vv for kk, vv in new["record"].items() if kk in ("rule", "agency", "federal_register", "published", "effective")})
                    elif isinstance(new.get("text"), str):
                        mx[k] = new["text"]
                    if failed:
                        revised.add(k)
                        mx["_revised_fields"] = sorted(revised)
                    if voice:
                        voiced.add(k)
                        mx["_voiced_fields"] = sorted(voiced)
                    done.append(f"{path.stem}: {k}")
                    changed = True
        if changed:
            path.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
            log.info("revised %s", path.stem)
    return done
