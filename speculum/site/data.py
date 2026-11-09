"""The Data page: the record's main tables as CSV files, rebuilt every night with the site.

Each file holds what the site shows, at full precision, with one header row. Amounts are dollars; shares are
fractions from 0 to 1; dates are YYYY-MM-DD. The votes of every member on every roll call are gzipped
(about 380,000 rows)."""
from __future__ import annotations

import csv
import gzip
import io
from pathlib import Path

from .. import ledger as ledger_mod


def _write(path: Path, header: list[str], rows, gz: bool = False) -> dict:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    n = 0
    for r in rows:
        w.writerow(["" if x is None else x for x in r])
        n += 1
    body = buf.getvalue().encode("utf-8")
    path.write_bytes(gzip.compress(body, mtime=0) if gz else body)
    return {"file": path.name, "rows": n, "bytes": path.stat().st_size, "columns": header}


def write(out: Path, members, chamber_rows, votes, interests, bills, said_opened, leaving_rows) -> list[dict]:
    d = out / "data"
    d.mkdir(exist_ok=True)
    by_id = {m["bioguide"]: m for m in members}
    files = []

    cr = {r["bioguide"]: r for r in chamber_rows}
    files.append({**_write(d / "members.csv",
        ["bioguide", "name", "party", "caucus", "chamber", "state", "district", "campaign_receipts", "small_donor_share",
         "pac_share", "lobbyist_contributions", "party_unity", "attendance"],
        ([m["bioguide"], m["name"], m["party"], ledger_mod.caucus_party(m), m["chamber"], m["state"],
          "" if m["chamber"] == "senate" else int(m.get("district") or 0),
          cr[m["bioguide"]]["raised"], cr[m["bioguide"]]["small"], cr[m["bioguide"]]["pac"], cr[m["bioguide"]]["lobby"],
          cr[m["bioguide"]]["unity"], cr[m["bioguide"]]["attend"]]
         for m in sorted(members, key=lambda m: m.get("sort_name") or m["name"]))),
        "title": "Members", "about": "Every sitting member with the figures on The Chamber: campaign receipts this cycle "
        "(FEC), the small-donor and PAC shares of them, contributions reported by lobbyists and their organizations "
        "(LD-203), party unity and attendance on roll calls. Party unity and attendance count independents with the party "
        "they caucus with."})

    positions = votes.get("positions", {})
    vlist = sorted(votes.get("votes", []), key=lambda v: (v.get("date") or "", v["id"]))

    def counts(v):
        c = {"Y": 0, "N": 0, "P": 0, "NV": 0}
        for p in (positions.get(v["id"]) or {}).values():
            s = ledger_mod.side(p)
            c[s if s else ("P" if p == "Present" else "NV")] += 1
        return c
    files.append({**_write(d / "rollcalls.csv",
        ["id", "chamber", "congress", "session", "number", "date", "question", "result", "bill", "yea", "nay", "present",
         "not_voting", "source"],
        ([v["id"], v["chamber"], v.get("congress"), v.get("session"), v.get("number"), (v.get("date") or "")[:10],
          v.get("question"), v.get("result"), v.get("bill"), *counts(v).values(), v.get("url")] for v in vlist)),
        "title": "Roll calls", "about": "Every recorded vote in the House and Senate since January 3, 2025, with its totals "
        "and a link to the official record."})
    files.append({**_write(d / "votes.csv.gz",
        ["rollcall_id", "bioguide", "name", "party", "position"],
        ([v["id"], b, (by_id.get(b) or {}).get("name") or ((votes.get("people") or {}).get(b) or {}).get("name"),
          (by_id.get(b) or {}).get("party") or ((votes.get("people") or {}).get(b) or {}).get("party"), p]
         for v in vlist for b, p in sorted((positions.get(v["id"]) or {}).items())), gz=True),
        "title": "Every vote of every member (gzipped)", "about": "One row per member per roll call: how they voted "
        "(Yea, Nay, Aye, No, Present or Not Voting). Former members are included under the party recorded at the vote."})

    files.append({**_write(d / "interests.csv",
        ["slug", "name", "kind", "type", "given_to_members", "members", "share_to_democrats", "share_to_republicans",
         "share_to_independents"],
        ([e["slug"], e["name"], e["kind"], e["type"], round(e["total"], 2), e["members"], round(e["split"].get("D", 0), 4),
          round(e["split"].get("R", 0), 4), round(e["split"].get("I", 0), 4)] for e in interests)),
        "title": "Interests", "about": "Committees (FEC) and lobbying organizations (LD-203) that fund sitting members, with "
        "what they gave and how it splits by party. Committee figures come from the largest itemized gifts collected for "
        "each member, so they are a floor."})

    files.append({**_write(d / "bills.csv",
        ["congress", "bill", "title", "organizations", "lobbying_reports", "business_share", "quarters", "page"],
        ([x["congress"], x["label"], x.get("title"), x["n_orgs"], x["reports"], x.get("business_share"),
          " ".join(x.get("quarters") or []), f"bill/{x['slug']}.html"] for x in bills)),
        "title": "Lobbied bills", "about": "Every bill named on quarterly lobbying reports (LD-2) since 2025, with how many "
        "organizations named it, in how many reports, and the share of those organizations that are businesses."})
    files.append({**_write(d / "bill_organizations.csv",
        ["congress", "bill", "organization", "sector", "files_own_reports"],
        ([x["congress"], x["label"], o["name"], o["sector"], "yes" if o.get("own") else "no"] for x in bills for o in x.get("orgs") or [])),
        "title": "Who lobbied each bill", "about": "One row per bill and organization named on its lobbying reports, with "
        "the organization's sector."})

    files.append({**_write(d / "said_done.csv",
        ["bill", "organization", "sector", "both_sides", "yes_members_funded", "yes_amount", "no_members_funded",
         "no_amount", "lobbying_reports_naming_the_bill", "contribution_reports"],
        ([m["label"], o["name"], o["sector_name"], "yes" if o["both"] else "no", o["yes"]["members"], o["yes"]["amount"],
          o["no"]["members"], o["no"]["amount"], o.get("n_said", 0), o["n_filings"]] for m in said_opened for o in m["orgs"])),
        "title": "Said & Done", "about": "For each bill the readers have opened: every organization that lobbied it and "
        "funded members who voted on it, with whom it funded on each side of the final vote."})

    files.append({**_write(d / "leaving.csv",
        ["bioguide", "name", "chamber", "state", "reason", "detail", "party_unity_before", "party_unity_after",
         "attendance_before", "attendance_after", "source"],
        ([r["bioguide"], r["member"]["name"], r["member"]["chamber"], r["member"]["state"], r["reason_label"], r.get("detail"),
          r["unity_before"], r["unity_after"], r["attend_before"], r["attend_after"], (r.get("source") or {}).get("url")]
         for r in leaving_rows)),
        "title": "Members leaving in January", "about": "Members not returning to their chamber, why, and their party "
        "unity and attendance before and after Election Day (shown once they have cast enough votes since)."})
    return files
