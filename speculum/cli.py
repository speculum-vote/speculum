"""Command line: `python -m speculum snapshot` then `python -m speculum build`."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .archive import RawArchive
from .http import Fetcher
from .snapshot import DAY_ZERO, Snapshot

log = logging.getLogger("speculum")
ROOT = Path(os.environ.get("SPECULUM_DATA", "data"))


def today_et() -> str:
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def cmd_snapshot(args) -> int:
    from .sources import congress, fec, lda, legislators, senate

    run_date = args.date or today_et()
    keys = {"congress": os.environ.get("CONGRESS_API_KEY"), "fec": os.environ.get("FEC_API_KEY"),
            "lda": os.environ.get("LDA_API_KEY")}
    missing = [k for k in ("congress", "fec") if not keys[k]]
    if missing:
        log.error("missing API keys: %s (set CONGRESS_API_KEY and FEC_API_KEY)", ", ".join(missing))
        return 2

    archive = RawArchive(ROOT / "raw", run_date)
    fetch = Fetcher(archive, min_interval={
        "api.congress.gov": 0.8,      # 5,000 requests/hour per key
        "api.open.fec.gov": 3.7,      # 1,000 requests/hour per key
        "lda.gov": 1.0,
        "www.senate.gov": 0.5,
        "unitedstates.github.io": 0.2,
    })
    snap = Snapshot(ROOT / "snapshots", run_date)
    errors: dict[str, str] = {}

    members = legislators.fetch_members(fetch)
    snap.write("members.json", members)
    log.info("members: %d", len(members))
    try:
        from .sources import committees
        snap.write("committees.json", committees.fetch_committees(fetch))
    except Exception as exc:  # a control, not a source of record: never sink the night over it
        log.exception("committees failed")
        errors["committees"] = f"{type(exc).__name__}: {exc}"

    def step(name, fn):
        if args.only and name not in args.only:
            return None
        try:
            return fn()
        except Exception as exc:  # one failing source must not sink the night's snapshot
            log.exception("%s failed", name)
            errors[name] = f"{type(exc).__name__}: {exc}"
            return None

    # Time budget: GitHub stops a job after 6 hours. Finance is the slowest source (FEC allows
    # 1,000 requests an hour), so it runs last and stops early to leave time to commit.
    import time
    deadline = time.monotonic() + 60 * float(os.environ.get("SPECULUM_BUDGET_MINUTES", "290"))
    votes = step("votes", lambda: _votes(fetch, keys, members, snap, errors))
    lobbying = step("lobbying", lambda: lda.fetch_lobbying(fetch, keys["lda"], members, run_date))
    if lobbying is not None:
        # The night the years read move on to a new Congress, keep the closing Congress's last copy as its
        # finished record: chains about that Congress's votes keep reading it (data/records/lobbying-<congress>.json).
        before = _latest(snap, "lobbying.json")
        done = lda.closed_record(before, lobbying)
        if done:
            rec = ROOT / "records" / f"lobbying-{done}.json"
            if not rec.exists():
                rec.parent.mkdir(parents=True, exist_ok=True)
                rec.write_text(json.dumps(before, separators=(",", ":"), sort_keys=True, ensure_ascii=False), encoding="utf-8")
                log.info("kept the %sth Congress's lobbyist contributions as its finished record: %s", done, rec)
        snap.write("lobbying.json", lobbying)

    def _spend():
        from .sources import lobbyspend
        bf = ROOT / "records" / "ld2_backfill.json"   # one-time: fields added after older quarters were fetched
        return lobbyspend.fetch_spend(fetch, keys["lda"], run_date, previous=_latest(snap, "spend.json"),
                                      deadline=deadline - 150 * 60,   # leave advocacy and finance time
                                      backfill=json.loads(bf.read_text(encoding="utf-8")) if bf.exists() else None)
    spend = step("spend", _spend)
    if spend is not None:
        snap.write("spend.json", spend)
    def _billinfo():
        from .sources import billinfo
        from . import bills as bills_mod
        from . import chains as chains_mod
        votes_now = snap.read("votes.json.gz") or _latest(snap, "votes.json.gz")
        # The Dependents' measures first (their final status decides what a chain can say), then the bill pages' own.
        wanted = list(dict.fromkeys(chains_mod.measures(votes_now) + bills_mod.wanted(spend or _latest(snap, "spend.json"), votes_now)))
        return billinfo.fetch_bill_info(fetch, keys["congress"], wanted, run_date, previous=_latest(snap, "billinfo.json"),
                                        deadline=deadline - 140 * 60)
    info = step("billinfo", _billinfo)
    if info is not None:
        snap.write("billinfo.json", info)
    def _advocacy():
        from .sources import advocacy
        from .chains import load_json
        cfg = load_json(ROOT / "advocacy.json", {})
        return advocacy.fetch_advocacy(fetch, keys["fec"], cfg, run_date, previous=_latest(snap, "advocacy.json"),
                                       deadline=deadline - 60 * 60)   # leave finance at least an hour
    adv = step("advocacy", _advocacy)
    if adv is not None:
        snap.write("advocacy.json", adv)
    finance = step("finance", lambda: fec.fetch_finance(fetch, keys["fec"], members, run_date,
                                                         previous=_latest(snap, "finance.json"),
                                                         top_n=args.top_committees, deadline=deadline))
    partial = None
    if finance is not None:
        partial = finance.pop("_partial", None)
        snap.write("finance.json", finance)

    votes = votes or snap.read("votes.json.gz", {"votes": []})
    finance = finance or snap.read("finance.json", {})
    lobbying = lobbying or snap.read("lobbying.json", {"by_member": {}})
    coverage = sorted(f["coverage_end"] for f in finance.values() if f.get("coverage_end"))
    vote_dates = sorted(v["date"] for v in votes.get("votes", []) if v.get("date"))
    files = sum(1 for _ in archive.manifest.open()) if archive.manifest.exists() else 0
    meta = {
        "date": run_date,
        "day_zero": DAY_ZERO,
        "note": "Day Zero baseline" if run_date == DAY_ZERO else "",
        "counts": {
            "members": len(members),
            "house": sum(1 for m in members if m["chamber"] == "house"),
            "senate": sum(1 for m in members if m["chamber"] == "senate"),
            "votes": len(votes.get("votes", [])),
            "finance": len(finance),
            "lobbying_items": sum(len(v) for v in lobbying.get("by_member", {}).values()),
            "lobbying_unmatched": len(lobbying.get("unmatched_honorees", [])),
        },
        "fec_through": coverage[-1] if coverage else None,
        "votes_through": vote_dates[-1][:10] if vote_dates else None,
        "raw_files": files,
        "calls": fetch.calls,
        "errors": errors,
        "finance_partial": partial,
    }
    if args.only:
        # A partial rerun fills in sources for a night already saved: keep what that night recorded
        # about the sources this run did not touch.
        prior = snap.read("meta.json", {}) or {}
        skipped = [k for k in ("votes", "finance", "lobbying", "spend", "billinfo", "advocacy") if k not in args.only]
        meta["errors"] = {**{k: v for k, v in (prior.get("errors") or {}).items()
                             if any(k == s or k.startswith(s + "_") for s in skipped)}, **errors}
        if "finance" not in args.only:
            meta["finance_partial"] = prior.get("finance_partial")
        meta["raw_files"] += prior.get("raw_files") or 0
        meta["calls"] += prior.get("calls") or 0
        meta["note"] = prior.get("note", meta["note"])
    meta["files"] = snap.index()   # which night's copy of each file stands tonight, with its SHA-256
    snap.write("meta.json", meta)
    try:
        from . import tide
        from .snapshot import all_dates
        earlier = [d for d in all_dates(ROOT / "snapshots") if d < run_date]
        prev = Snapshot(ROOT / "snapshots", earlier[-1]) if earlier else None
        gone = [n for n in tide.NEEDS if prev and prev.standing(n) is None]
        if gone and (snap.dir / "tide.json").exists():
            # A back-dated rerun: the night before is in git history only, and an edition built without it
            # would call everything new. Keep the edition already saved for this night.
            log.warning("kept %s's saved edition of The Tide: %s for %s is in git history only", run_date, ", ".join(gone), prev.date)
        else:
            snap.write("tide.json", tide.build_edition(snap, prev))
    except Exception:
        log.exception("tide edition failed")
    from .snapshot import all_dates as _dates, prune
    if _dates(ROOT / "snapshots")[-1] == run_date:   # a back-dated rerun never removes anything
        removed = prune(ROOT / "snapshots")
        if removed:
            log.info("older copies left for git history: %s", ", ".join(f"{p.parent.name}/{p.name}" for p in removed))
    stored = sorted(n for n, e in meta["files"].items() if e["night"] == run_date)
    log.info("files stored for %s (the rest are unchanged and stand from earlier nights): %s", run_date, ", ".join(stored) or "none")
    log.info("snapshot %s done: %s", run_date, json.dumps(meta["counts"]))
    if errors:
        log.warning("sources with errors: %s", ", ".join(errors))
    return 0


def _votes(fetch, keys, members, snap, errors):
    from .sources import congress, senate

    previous = _latest(snap, "votes.json.gz")
    empty = {"votes": [], "positions": {}}

    def chamber(name, fn):
        # Each chamber stands alone: a refusal from one site must not throw away the other's votes.
        try:
            return fn()
        except Exception as exc:
            log.exception("%s votes failed", name)
            errors[f"votes_{name}"] = f"{type(exc).__name__}: {exc}"
            keep = [v for v in (previous or {}).get("votes", []) if v.get("chamber") == name]
            return {"votes": keep, "positions": {v["id"]: previous["positions"].get(v["id"], {}) for v in keep}} if keep else empty

    house = chamber("house", lambda: congress.fetch_house_votes(fetch, keys["congress"], previous))
    sen = chamber("senate", lambda: senate.fetch_senate_votes(fetch, members, previous))
    merged = {"votes": house["votes"] + sen["votes"], "positions": {**house["positions"], **sen["positions"]},
              "people": sen.get("people") or (previous or {}).get("people", {})}
    # A back-dated run (e.g. stamping Day Zero after the fact) keeps only roll calls held by that date.
    if snap.date < today_et():
        keep = [v for v in merged["votes"] if (v.get("date") or "")[:10] <= snap.date]
        ids = {v["id"] for v in keep}
        merged = {"votes": keep, "positions": {k: p for k, p in merged["positions"].items() if k in ids}, "people": merged.get("people", {})}
    snap.write("votes.json.gz", merged)
    return merged


def _latest(snap: Snapshot, name: str):
    """This run's file if a rerun already wrote it, else the copy that stood the night before.
    Lets each night fetch only what changed."""
    from .snapshot import read_newest
    return snap.read(name) or read_newest(snap.root, name, snap.date)


def cmd_build(args) -> int:
    from .site.build import build

    result = build(ROOT / "snapshots", Path(args.out))
    log.info("built site: %s", result)
    return 0


def cmd_chains(args) -> int:
    from . import chains, interpret
    from .snapshot import latest

    snap = latest(ROOT / "snapshots")
    if snap is None:
        log.error("no snapshot yet")
        return 1
    from .sources.lda import clean
    from .sources.fec import clean_finance
    from .sources.senate import clean_votes
    out = chains.for_site(snap.read("members.json", []), clean_finance(snap.read("finance.json", {}), snap.read("members.json", [])), clean(snap.read("lobbying.json", {}), snap.read("members.json", [])),
                          clean_votes(snap.read("votes.json.gz", {"votes": [], "positions": {}})), ROOT,
                          spend=snap.read("spend.json"), bill_info=snap.read("billinfo.json"))
    log.info("chains: %d (%d with reviewed research)", len(out), sum(1 for c in out if c["research_by"] == "research"))
    if args.check:
        log.info("drafter check: %s", interpret.check())
        return 0
    if args.draft:
        done = interpret.draft_missing(out, ROOT / "chains" / "drafts", limit=args.limit)
        log.info("drafted: %s", ", ".join(done) or "none")
    if args.revise:
        checks = chains.load_json(ROOT / "chains" / "checks.json", {}).get("checks", {})
        done = interpret.revise_failed(ROOT / "chains" / "drafts", checks, limit=args.limit)
        log.info("revised after the source check: %d (%s)", len(done), "; ".join(done) or "none")
    return 0


def cmd_approve(args) -> int:
    """Record a person's approval of one chain, tied to the research as it stands now."""
    import json
    from . import chains
    from .snapshot import latest
    from .sources.lda import clean
    from .sources.fec import clean_finance
    from .sources.senate import clean_votes

    snap = latest(ROOT / "snapshots")
    if snap is None:
        log.error("no snapshot yet")
        return 1
    members = snap.read("members.json", [])
    out = chains.for_site(members, clean_finance(snap.read("finance.json", {}), members), clean(snap.read("lobbying.json", {}), members),
                          clean_votes(snap.read("votes.json.gz", {"votes": [], "positions": {}})), ROOT,
                          spend=snap.read("spend.json"), bill_info=snap.read("billinfo.json"))
    want = args.chain.lower().replace(".", "").replace(" ", "")
    hits = [c for c in out if c["id"] == want or c["id"].endswith("-" + want)]
    if len(hits) != 1:
        log.error("no single chain matches %r; chains: %s", args.chain, ", ".join(c["id"] for c in out))
        return 1
    ch = hits[0]
    path = ROOT / "chains" / "reviews.json"
    reviews = chains.load_json(path, {})
    entry = {k: v for k, v in (reviews.get(ch["id"]) or {}).items() if k not in ("approved_by", "date", "note", "research")}
    if not args.revoke:
        entry.update({"approved_by": args.by, "date": today_et(), "research": ch["fingerprint"]})
        if args.note:
            entry["note"] = args.note
    reviews[ch["id"]] = entry
    path.write_text(json.dumps(reviews, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("%s %s", "revoked" if args.revoke else f"approved by {args.by}:", ch["id"])
    return 0


def cmd_verify(args) -> int:
    """Read readers' disputes, then check new, changed and disputed claims against their sources."""
    from . import verify
    if not args.no_disputes:
        verify.ingest_disputes(ROOT)
    verify.run(ROOT, limit=args.limit)
    return 0


def said_done_data(snap) -> dict:
    """Both sides of the vote, measured for every qualifying bill in a snapshot (speculum/saiddone.py)."""
    from . import saiddone
    from .sources.lda import clean
    from .sources.senate import clean_votes
    members = snap.read("members.json", [])
    return saiddone.build(snap.read("spend.json"), clean_votes(snap.read("votes.json.gz", {"votes": [], "positions": {}})),
                          members, clean(snap.read("lobbying.json", {"by_member": {}}), members), snap.read("billinfo.json"))


def cmd_ppplobby(args) -> int:
    """One-time read of 2020-21 lobbying reports for the PPP case (data/records/ppp_lobbying.json); resumable."""
    from .http import Fetcher
    from .sources import ppplobby
    run_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    fetch = Fetcher(RawArchive(ROOT / "raw", run_date), min_interval={"lda.gov": 0.55})
    out = ppplobby.fetch(ROOT / "records" / "ppp_lobbying.json", fetch, os.environ.get("LDA_API_KEY"), budget_min=args.minutes)
    log.info("PPP lobbying: %d of %d quarters complete, %d organizations", sum(1 for q in out["quarters"].values() if q.get("complete")),
             len(ppplobby.QUARTERS), len(out["orgs_by_key"]))
    return 0


def cmd_pppspot(args) -> int:
    """Re-read a sample of the 2020-21 PPP matches and save the matched words for checking by hand."""
    from .http import Fetcher
    from .sources import ppplobby
    run_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    fetch = Fetcher(RawArchive(ROOT / "raw", run_date), min_interval={"lda.gov": 0.55})
    res = ppplobby.spot(ROOT / "records" / "ppp_lobbying.json", ROOT / "records" / "ppp_spot.json", fetch,
                        os.environ.get("LDA_API_KEY"), n=args.n, names=[x.strip() for x in (args.names or "").split("|") if x.strip()])
    log.info("PPP spot check: %d reports, %d still match", res["n"], sum(1 for r in res["rows"] if r["still_matches"]))
    return 0


def cmd_pppcheck(args) -> int:
    """Every 2019-21 report naming each client, with amounts as filed (data/records/ppp_check.json)."""
    from .http import Fetcher
    from .sources import ppplobby
    run_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    fetch = Fetcher(RawArchive(ROOT / "raw", run_date), min_interval={"lda.gov": 0.55})
    res = ppplobby.client_filings(ROOT / "records" / "ppp_check.json", fetch, os.environ.get("LDA_API_KEY"),
                                  [x.strip() for x in (args.names or "").split("|") if x.strip()])
    log.info("PPP check: %s", {k: len(v) for k, v in res.items()})
    return 0


def cmd_pppfees(args) -> int:
    """Re-read in full every 2020-21 report of the named clients for fees near the program (data/records/ppp_fees.json)."""
    from .http import Fetcher
    from .sources import ppplobby
    run_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    fetch = Fetcher(RawArchive(ROOT / "raw", run_date), min_interval={"lda.gov": 0.55})
    names = [x.strip() for x in (args.names or "").split("|") if x.strip()]
    if not names:
        lob = json.loads((ROOT / "records" / "ppp_lobbying.json").read_text(encoding="utf-8"))
        names = sorted(v["name"] for v in lob["orgs_by_key"].values() if v.get("fee"))
    res = ppplobby.fee_reread(ROOT / "records" / "ppp_fees.json", fetch, os.environ.get("LDA_API_KEY"), names)
    log.info("PPP fees: %d clients, %d reports, %d fee mentions", len(res), sum(v["reports_read"] for v in res.values()),
             sum(len(v["fee_mentions"]) for v in res.values()))
    return 0


def cmd_pppborrowers(args) -> int:
    """Match the SBA's PPP loans to 2020-21 lobbying clients and firms (data/records/ppp_borrowers.json)."""
    from .sources import pppborrowers
    pppborrowers.fetch(ROOT / "records" / "ppp_lobbying.json", ROOT / "records" / "ppp_borrowers.json")
    return 0


def cmd_ppp(args) -> int:
    """Fetch the SBA's PPP loan data and save per-lender totals with estimated processing fees (data/records)."""
    from .sources import ppp
    path = ROOT / "records" / "ppp_lenders.json"
    if args.if_missing and path.exists():
        log.info("PPP file already there: %s", path)
        return 0
    ppp.fetch(path)
    return 0


def cmd_zcta(args) -> int:
    """Fetch the Census Bureau's ZIP code area to congressional district file into data/records (for Find your members)."""
    from .sources import zcta
    path = ROOT / "records" / f"zcta_cd{zcta.CONGRESS}.json"
    if args.if_missing and path.exists():
        log.info("ZIP code file already there: %s", path)
        return 0
    zcta.fetch(path)
    return 0


def cmd_guard(args) -> int:
    """Check the night's data and the built site before deploying; a failure stops the deploy."""
    from . import guard
    from .snapshot import latest
    snap = latest(ROOT / "snapshots")
    problems = guard.check_data(ROOT / "snapshots") if not args.site_only else []
    problems += guard.check_site(Path(args.out), len(snap.read("members.json", []) or []) if snap else None)
    for p in problems:
        print(f"::error::guard: {p}")
    if problems:
        log.error("guard: %d problem(s); not deploying. The last good site stays up. Expected drops go in data/guard.json.", len(problems))
        return 1
    log.info("guard: data and site look right")
    return 0


def cmd_saiddone(args) -> int:
    """Bring the readers' rounds up to date: count a closed round, open its winner, start the next round."""
    from . import saiddone
    from .snapshot import latest
    snap = latest(ROOT / "snapshots")
    if snap is None:
        log.error("no snapshot yet")
        return 1
    sd = said_done_data(snap)
    path = ROOT / "saiddone.json"
    state = saiddone.load_state(path)
    today = args.date or today_et()
    rnd = state.get("round")
    tally = saiddone.kv_tally
    if rnd and today > rnd["closes"] and not (os.environ.get("CLOUDFLARE_API_TOKEN") and os.environ.get("CLOUDFLARE_ACCOUNT_ID")):
        log.warning("round %s has closed but there are no Cloudflare credentials to count it; left open until they are set", rnd["id"])
        return 0
    new = saiddone.advance(state, sd, today, tally)
    saiddone.save_state(path, new)
    r = new.get("round") or {}
    log.info("said & done: open %s; round %s closes %s over %s", [o["slug"] for o in new["opened"]], r.get("id"), r.get("closes"), r.get("candidates"))
    return 0


def cmd_restore(args) -> int:
    """Rebuild a past night's files from git history, checked against that night's SHA-256 index."""
    from .snapshot import restore
    out = Path(args.out or f"restored/{args.date}")
    result = restore(ROOT / "snapshots", args.date, out)
    for name, status in result.items():
        log.info("%-18s %s", name, status)
    missing = [n for n, s in result.items() if not s.startswith("ok")]
    if missing:
        log.error("not found: %s (a shallow clone lacks history: run `git fetch --unshallow`)", ", ".join(missing))
        return 1
    log.info("restored %s into %s", args.date, out)
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="speculum")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="fetch every source and write today's snapshot")
    s.add_argument("--date", help="override the snapshot date (YYYY-MM-DD)")
    s.add_argument("--only", nargs="*", choices=["votes", "finance", "lobbying", "spend", "billinfo", "advocacy"])
    s.add_argument("--top-committees", type=int, default=50, help="committee givers kept per member (pages show the top 10)")
    b = sub.add_parser("build", help="render the site from the latest snapshot")
    b.add_argument("--out", default="dist")
    c = sub.add_parser("chains", help="build consequence chains; with --draft, ask the AI drafter for missing research")
    c.add_argument("--draft", action="store_true")
    c.add_argument("--revise", action="store_true", help="revise, once each, drafted claims the source check did not pass")
    c.add_argument("--check", action="store_true", help="one small live request to prove the API key works")
    c.add_argument("--limit", type=int, default=3, help="most chains to draft in one run")
    a = sub.add_parser("approve", help="record a person's approval of one chain's current research")
    a.add_argument("chain", help="chain id or bill, e.g. sjres32")
    a.add_argument("--by", default="the editor", help="name shown on the page")
    a.add_argument("--note", help="optional note shown with the approval")
    a.add_argument("--revoke", action="store_true", help="withdraw the approval")
    v = sub.add_parser("verify", help="check new, changed and disputed claims against their sources")
    v.add_argument("--limit", type=int, default=40, help="most claims to check in one run")
    v.add_argument("--no-disputes", action="store_true", help="skip reading new disputes from Cloudflare")
    r = sub.add_parser("restore", help="rebuild a past night's files from git history, checked by SHA-256")
    r.add_argument("date", help="the night, YYYY-MM-DD")
    r.add_argument("--out", help="folder to write into (default restored/<date>)")
    pl = sub.add_parser("ppplobby", help="one-time read of 2020-21 lobbying reports on the PPP")
    pl.add_argument("--minutes", type=float, default=280)
    ps = sub.add_parser("pppspot", help="re-read a sample of the 2020-21 PPP matches for checking by hand")
    ps.add_argument("--n", type=int, default=40)
    ps.add_argument("--names", help="organization keys to add, separated by |")
    sub.add_parser("pppborrowers", help="match PPP loans to 2020-21 lobbying clients and firms")
    pf = sub.add_parser("pppfees", help="re-read every 2020-21 report of the clients that mention fees near PPP")
    pf.add_argument("--names", help="client names, separated by |; default: every client flagged")
    pk = sub.add_parser("pppcheck", help="every 2019-21 report naming each client, with amounts as filed")
    pk.add_argument("--names", help="client names, separated by |")
    pp = sub.add_parser("ppp", help="fetch the SBA's PPP loan data into per-lender totals")
    pp.add_argument("--if-missing", action="store_true")
    z = sub.add_parser("zcta", help="fetch the ZIP code area to congressional district file")
    z.add_argument("--if-missing", action="store_true")
    g = sub.add_parser("guard", help="check the night's data and the built site before deploying")
    g.add_argument("--out", default="dist")
    g.add_argument("--site-only", action="store_true", help="check only the built site")
    sd = sub.add_parser("saiddone", help="Said & Done: count a closed readers' round and start the next")
    sd.add_argument("--date", help="today, YYYY-MM-DD (default: today in Eastern time)")
    args = p.parse_args(argv)
    return {"snapshot": cmd_snapshot, "build": cmd_build, "chains": cmd_chains, "approve": cmd_approve,
            "verify": cmd_verify, "restore": cmd_restore, "saiddone": cmd_saiddone, "guard": cmd_guard, "zcta": cmd_zcta, "ppp": cmd_ppp, "ppplobby": cmd_ppplobby, "pppspot": cmd_pppspot, "pppborrowers": cmd_pppborrowers, "pppcheck": cmd_pppcheck, "pppfees": cmd_pppfees}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
