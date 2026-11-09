"""Checks run after the build and before the deploy. If any fails, the deploy does not run and the last good
site stays up; the night's data is already committed, so nothing is lost.

Two kinds of check:
- The night's data against the night before: a data file that shrank by more than a quarter, fewer members
  than the night before, or fewer roll calls in the same Congress. A source that answered with half its
  records would otherwise publish half a record.
- The built site: the main pages are there and not empty, one page per member, nothing a template failed
  to fill in, and the Cloudflare Pages limits (20,000 files, 25 MiB a file).

A drop that is expected (a new Congress, the lobbying years moving on) is allowed through `data/guard.json`:
{"allow": {"<file name>": "<last day allowed, YYYY-MM-DD>"}}.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import snapshot as snap_mod

SHRINK = 0.75                 # a data file below this share of the night before's size fails
MIN_MEMBERS = 520             # 535 seats less vacancies; fewer means the roster fetch broke
MAX_FILES = 19_500            # Cloudflare Pages allows 20,000
MAX_BYTES = 25 * 1024 * 1024  # and 25 MiB a file
PAGES = {"index.html": 4_000, "chamber.html": 50_000, "findings.html": 5_000, "money.html": 5_000,
         "bills.html": 20_000, "method.html": 10_000, "saiddone.html": 3_000, "lameduck.html": 3_000,
         "tide.html": 2_000, "dependents.html": 3_000, "join.html": 1_000, "about.html": 1_000}
JUNK = re.compile(r"Traceback \(most recent|\{\{|\{%|\bundefined\b|\bNaN\b")


def _allowed(data_root: Path, today: str) -> set[str]:
    p = data_root / "guard.json"
    try:
        allow = (json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}).get("allow") or {}
    except ValueError:
        return set()
    return {name for name, until in allow.items() if str(until) >= today}


def check_data(snapshots_root: Path) -> list[str]:
    root = Path(snapshots_root)
    cur = snap_mod.latest(root)
    if cur is None:
        return ["no snapshot"]
    prev = snap_mod.previous(root, cur.date)
    problems = []
    members = cur.read("members.json", []) or []
    if len(members) < MIN_MEMBERS:
        problems.append(f"members.json: {len(members)} members (at least {MIN_MEMBERS} expected)")
    if prev is None:
        return problems
    allowed = _allowed(root.parent, cur.date)
    now, before = cur.index(), (prev._meta().get("files") or prev.index())
    for name, e in now.items():
        b = (before.get(name) or {}).get("bytes")
        if b and name not in allowed and e["bytes"] < SHRINK * b:
            problems.append(f"{name}: {e['bytes']:,} bytes, down from {b:,} the night before ({e['bytes'] / b:.0%})")
    pm = prev.read("members.json", []) or []
    if "members.json" not in allowed and len(members) < len(pm) - 5:
        problems.append(f"members.json: {len(members)} members, down from {len(pm)}")
    if "votes.json.gz" not in allowed:
        def per_congress(s):
            out = {}
            for v in (s.read("votes.json.gz", {}) or {}).get("votes") or []:
                out[v.get("congress")] = out.get(v.get("congress"), 0) + 1
            return out
        a, b = per_congress(cur), per_congress(prev)
        for c, n in b.items():
            if c in a and a[c] < n:
                problems.append(f"votes.json.gz: {a[c]} roll calls in the {c}th Congress, down from {n}")
    return problems


def check_site(out: Path, members: int | None = None) -> list[str]:
    out = Path(out)
    problems = []
    files = [p for p in out.rglob("*") if p.is_file()]
    for site in ("preview", "public"):
        d = out / site
        n = sum(1 for p in files if d in p.parents)
        if n > MAX_FILES:
            problems.append(f"{site}: {n:,} files (Cloudflare Pages allows 20,000)")
    for p in files:
        if p.stat().st_size > MAX_BYTES:
            problems.append(f"{p.relative_to(out)}: {p.stat().st_size:,} bytes (over 25 MiB)")
    launched = (out / "public" / "chamber.html").exists()
    for site in ("preview", "public") if launched else ("preview",):
        for page, least in PAGES.items():
            p = out / site / page
            if not p.exists():
                problems.append(f"{site}/{page} is missing")
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if len(text) < least:
                problems.append(f"{site}/{page}: {len(text):,} bytes (at least {least:,} expected)")
            body = re.sub(r"<script.*?</script>|<style.*?</style>", "", text, flags=re.S)
            m = JUNK.search(body)
            if m:
                problems.append(f"{site}/{page}: unfilled template or error text near {body[max(0, m.start() - 40):m.end() + 40]!r}")
        if members is not None:
            n = len(list((out / site / "member").glob("*.html")))
            if n < members:
                problems.append(f"{site}: {n} member pages for {members} members")
    if not (out / "public" / "index.html").exists():
        problems.append("public/index.html is missing")
    return problems
