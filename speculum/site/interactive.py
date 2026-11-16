"""The files behind the site's interactive parts. Everything is computed at build time and served as static JSON:
nothing is sent anywhere when a reader searches, filters or picks their members, and nothing is tracked.

- search.json: one row per member, bill, case, organization, page.
- committees.json: committee codes and names, for the filters on member tables.
- explore/<sector>.json and explore.json: each industry's contributions to members (LD-203), for the explorer.
- mine.json: a short summary of every member for the Your members page.
"""
from __future__ import annotations

import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from ..bills import billname

PARTY = {"D": "Democrat", "R": "Republican", "I": "Independent", "L": "Libertarian"}


def fold(s: str) -> str:
    """Lower case, no accents, letters and digits only: what search compares."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


# ---------- committees, for filters and for where money concentrates ----------

def committee_index(committees: dict) -> dict[str, dict]:
    """code -> {n: short name, c: 'h'|'s'|'j', p: parent code or None}."""
    out = {}
    for seats in ((committees or {}).get("seats") or {}).values():
        for s in seats:
            code, name = s["code"], s.get("name") or s["code"]
            if code in out:
                continue
            ch = {"H": "h", "S": "s", "J": "j"}.get(code[:1], "j")
            parent = code[:4] if len(code) > 4 else None
            short = re.sub(r"^(House|Senate|Joint) Committee on (the )?", "", name)
            short = re.sub(r": (the )?", ": ", short)
            short = re.sub(r"^(House|Senate) (Select|Permanent Select|Special) Committee on ", r"\2 Committee on ", short)
            out[code] = {"n": short, "c": ch, "p": parent}
    return out


def member_seats(committees: dict) -> dict[str, list[str]]:
    return {b: sorted({s["code"] for s in v}) for b, v in ((committees or {}).get("seats") or {}).items()}


def concentration(amounts: dict[str, float], seats: dict[str, list[str]], cindex: dict, *,
                  min_members: int = 4, top: int = 5) -> list[dict]:
    """Where one giver's money concentrates: for each committee, the average a sitting member on it received
    against the average for every other sitting member. Only committees where the giver funded at least
    `min_members` members. Ranked by that ratio."""
    sitting = set(seats)
    if not sitting:
        return []
    on: dict[str, list[str]] = defaultdict(list)
    for b, codes in seats.items():
        for c in codes:
            on[c].append(b)
    total = sum(a for b, a in amounts.items() if b in sitting)
    out = []
    for code, bs in on.items():
        n_on = len(bs)
        n_off = len(sitting) - n_on
        if n_on < 10 or n_off <= 0:
            continue
        g_on = sum(amounts.get(b, 0) for b in bs)
        funded = sum(1 for b in bs if amounts.get(b, 0) > 0)
        if funded < min_members:
            continue
        avg_on, avg_off = g_on / n_on, (total - g_on) / n_off
        if avg_off <= 0:
            continue
        ce = cindex.get(code, {})
        out.append({"code": code, "name": {"h": "House ", "s": "Senate ", "j": "Joint "}.get(ce.get("c"), "") + ce.get("n", code), "seats": n_on, "funded": funded,
                    "to": g_on, "avg_on": avg_on, "avg_off": avg_off, "ratio": avg_on / avg_off})
    out.sort(key=lambda x: (-x["ratio"], -x["to"]))
    return out[:top]


# ---------- search ----------

def search_index(members, seat_fn, bills, cases, interest_rows, pages) -> list[list]:
    """[type, name, subtitle, url, extra words] per entry; the page scores matches itself."""
    out = []
    for m in members:
        out.append(["Member", m["name"], f"{'Senator' if m['chamber'] == 'senate' else 'Representative'}, {seat_fn(m)} · {PARTY.get(m['party'], m['party'])}", f"member/{m['bioguide']}.html",
                    fold(" ".join(filter(None, [m.get("sort_name"), m.get("state"), m.get("state_name")])))])
    for c in cases:
        names = " ".join(x.get("name", "") for x in ((c.get("contracts") or {}).get("companies") or []))
        dek = c.get("dek") or ""
        if len(dek) > 140:
            dek = dek[:138].rsplit(" ", 1)[0] + "…"
        out.append(["Case", c["title"], dek, f"case/{c['slug']}.html",
                    fold(" ".join(filter(None, [c.get("dek"), c.get("why"), names, " ".join(c.get("bills") or [])]))) if c else ""])
    for b in bills:
        out.append(["Bill", f"{b.get('label') or ''} {b.get('title') or ''}".strip(), f"{b.get('n_orgs') or ''} organizations lobbied on it".strip(),
                    f"bill/{b['slug']}.html", fold((b.get("label") or "").replace(".", "").replace(" ", ""))])
    for e in interest_rows:
        kind = "Organization" if e["kind"] == "registrant" else e["type"]
        out.append([kind, e["name"], f"{'Reported giving' if e['kind'] == 'registrant' else 'Gave'} ${_short(e['total'])} to {e['members']} member{'s' if e['members'] != 1 else ''}",
                    f"interest/{e['slug']}.html", ""])
    for p in pages:
        out.append(["Page", p[0], p[1], p[2], fold(p[3] if len(p) > 3 else "")])
    return out


def _short(x: float) -> str:
    x = float(x or 0)
    if x >= 1e9:
        return f"{x / 1e9:.1f}B"
    if x >= 1e6:
        return f"{x / 1e6:.1f}M"
    if x >= 1e3:
        return f"{x / 1e3:.0f}K"
    return f"{x:,.0f}"


# ---------- industry explorer ----------

def explore(lobbying: dict, sectors_of: dict[str, str], sector_names: dict[str, str], seats, cindex, members) -> tuple[list, dict]:
    """explore.json (the list of industries) and, per industry, its members and givers."""
    sitting = {m["bioguide"] for m in members}
    reg = lobbying.get("registrants") or {}
    per: dict[str, dict] = defaultdict(lambda: {"members": defaultdict(float), "givers": defaultdict(float), "n": defaultdict(int)})
    for bio, rows in (lobbying.get("by_member") or {}).items():
        if bio not in sitting:
            continue
        for r in rows:
            rid = str(r.get("registrant_id") or "")
            if not rid:
                continue
            sec = sectors_of.get(rid) or "other"
            a = float(r.get("amount") or 0)
            P = per[sec]
            P["members"][bio] += a
            P["givers"][rid] += a
            P["n"][bio] += 1
    listing, files = [], {}
    for sec, P in per.items():
        total = sum(P["members"].values())
        if total <= 0:
            continue
        conc = concentration(dict(P["members"]), seats, cindex, min_members=5, top=8)
        files[sec] = {"key": sec, "name": sector_names.get(sec, sec.title()), "total": total,
                      "members": sorted(([b, round(a, 2), P["n"][b]] for b, a in P["members"].items()), key=lambda x: -x[1]),
                      "givers": sorted(([rid, (reg.get(rid) or {}).get("name") or rid, round(a, 2)] for rid, a in P["givers"].items()), key=lambda x: -x[2])[:60],
                      "n_givers": len(P["givers"]), "concentration": conc}
        listing.append({"key": sec, "name": files[sec]["name"], "total": total, "members": len(P["members"]), "givers": len(P["givers"])})
    listing.sort(key=lambda x: -x["total"])
    return listing, files


# ---------- your members ----------

def mine(members, ledgers, lobbying, vlist, positions, cases, sectors_of, sector_names, seat_fn, leaving: dict, cindex, seats,
         titles: dict | None = None) -> dict:
    """A short summary per member: money, votes, standing in the chamber, recent and case votes."""
    reg = lobbying.get("registrants") or {}
    case_bills = defaultdict(list)            # (congress, label) -> case
    for c in cases:
        for b in c.get("bills") or []:
            label = b if isinstance(b, str) else (b.get("label") or b.get("bill") or "")
            cg = c.get("congress") if isinstance(b, str) else (b.get("congress") or c.get("congress"))
            case_bills[(cg, _label_key(label))].append(c)
    case_votes = [(v, case_bills[(v.get("congress"), _label_key(v.get("bill") or ""))]) for v in vlist
                  if case_bills.get((v.get("congress"), _label_key(v.get("bill") or "")))]
    out = {}
    for m in members:
        bio = m["bioguide"]
        L = ledgers.get(bio) or {}
        lob = lobbying.get("by_member", {}).get(bio, [])
        givers, secs = Counter(), Counter()
        for r in lob:
            rid = str(r.get("registrant_id") or "")
            a = float(r.get("amount") or 0)
            if rid:
                givers[rid] += a
                secs[sectors_of.get(rid) or "other"] += a
        recent = []
        for v in vlist:
            p = positions.get(v["id"], {}).get(bio)
            if p is None:
                continue
            b = str(v.get("bill") or "")
            t = (titles or {}).get(f"{v.get('congress')}-{_label_key(b)}") if b and not b.startswith("PN") else None
            if t and len(t) > 90:
                t = t[:88].rsplit(" ", 1)[0] + "…"
            what = v.get("title") or ((billname(_label_key(b)) + (" " + t if t else "") + ": " if b and not b.startswith("PN") else "") + (v.get("question") or ""))
            recent.append([v["id"], (v.get("date") or "")[:10], v.get("bill") or "", what[:160],
                           v.get("question") or "", p, v.get("result") or "", v.get("url") or ""])
            if len(recent) >= 8:
                break
        cv = []
        for v, cs in case_votes:
            p = positions.get(v["id"], {}).get(bio)
            if p is None:
                continue
            for c in cs:
                cv.append([c["slug"], c["title"], (v.get("date") or "")[:10], v.get("question") or "", p, v.get("url") or ""])
        F = L.get("funding") or {}
        pct, med = L.get("pct") or {}, L.get("chamber_median") or {}
        out[bio] = {
            "n": m["name"], "p": m["party"], "seat": seat_fn(m), "ch": m["chamber"][0], "x": 1 if bio in leaving else 0,
            "raised": F.get("total"), "cycle": (L.get("finance") or {}).get("cycle_label"), "small": (F.get("parts") or {}).get("small"), "pac": (F.get("parts") or {}).get("pac"),
            "lob": L.get("lobbyist_total") or 0, "unity": L.get("unity"), "att": L.get("attendance"),
            "pct": {k: (round(v) if v is not None else None) for k, v in pct.items()},
            "med": {k: v for k, v in med.items()},
            "givers": [[rid, (reg.get(rid) or {}).get("name") or rid, round(a)] for rid, a in givers.most_common(5)],
            "sectors": [[s, sector_names.get(s, s.title()), round(a)] for s, a in secs.most_common(4)],
            "cmte": [c for c in seats.get(bio, []) if len(c) == 4],
            "recent": recent, "cases": cv,
        }
    return out


def _label_key(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def write(prev: Path, name: str, obj) -> None:
    p = prev / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str), encoding="utf-8")
