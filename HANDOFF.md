# Handoff: where Speculum stands (November 6, 2026)

Read this first in a new session. It records what is built, how it runs, the rules the project keeps, and what comes next.

## What Speculum is

A public, nonpartisan record of Congress at speculum.vote: how every member votes, where their campaign money comes from, and who lobbies them, built only from public filings and updated nightly. The record began on Day Zero, November 3, 2026. Public launch is planned for November 11–12, 2026 (flip `data/site.json` `"public"` to `"launch"`).

## Rules the project keeps

- Show the pattern, never a verdict. Fixed rules, the same for every member and party; every figure links to its source; the Method page publishes every rule. Findings are fixed measures chosen in advance, never selected for what they show.
- Real data only. When a figure can't be checked, say so rather than estimate.
- Never ask for, paste or handle API keys or passwords in chat. Keys live only in GitHub secrets, which the owner sets.
- Never force-push.
- Commit to `main`; the deploy runs on push. (The old session also mirrored `main` to a `tide` branch.)
- Subtle lore (Malleus Cordis / Vesperhold) stays subtle. The one open reference is The Glass (`glass.html`, linked from the auditor's seal and the footer): the Catedral's mirror framing four panes of plain facts from the record, and a closed door teasing Malleus Cordis, with a note that the game casts no real person as anything and nothing in the record is drawn from it.

## How it runs

- Nightly: `.github/workflows/nightly.yml` runs `python -m speculum snapshot`, commits `data/snapshots/<date>/` (only the files that changed; see Snapshots below), archives raw API responses to a GitHub release (`raw-<date>`), builds and deploys. A Cloudflare Worker in `scheduler/` starts it at 10:20, 13:50 and 17:20 UTC; the gate lets only the first full run of the day through.
- Deploy: `scripts/deploy.sh` publishes two Cloudflare Pages projects. `speculum-public` is speculum.vote, still the holding page with the early-access sign-up. `speculum-preview` is the full site at early.speculum.vote, behind Cloudflare Access (an email allow-list, policy "Approved readers"); its pages.dev addresses redirect there.
- Nightly time limits (November 9): drafting 45 minutes, revision 30, source check 45, Said & Done 10, so a slow AI night still commits and deploys. The drafter's `--limit` counts attempts, not successes; a chain whose draft fails is recorded in `data/chains/draft_failures.json` and skipped for 7 days; no new draft starts after 30 minutes. (On November 9 the drafting step ran for over 90 minutes, where it usually takes 6 to 8.)
- Guard (November 9): `python -m speculum guard` runs after every build, before the deploy (`speculum/guard.py`). It fails when a data file shrank by more than a quarter since the night before, members or roll calls in the same Congress went down, a main page is missing, empty or shows unfilled template text, member pages are missing, or the Cloudflare limits are near. Then the deploy is skipped and the last good site stays up; the night's data is already committed. An expected drop (a new Congress, the lobbying years moving on) goes in `data/guard.json`: `{"allow": {"lobbying.json": "2027-04-05"}}`, allowed through that date.
- Alerts (November 9): a failed or timed-out nightly run opens a "Nightly run failed" issue (or comments on the open one), a failed code deploy a "Site deploy failed" issue; the next success closes it (`scripts/alert.sh`). GitHub emails the repository's watchers, so the owner must be watching speculum-vote/speculum.
- Source check: `check.yml` uses the Anthropic API to verify every claim in The Dependents against its sources. Readers' disputes go to the KV store `speculum-disputes`.
- Early access: sign-ups are stored in KV `speculum-signups`, never in the repository. The owner's list is at speculum.vote/signups. Approve and Remove edit the Access policy through `functions/api/approve.js`; Invite opens a draft in the Speculum Gmail account, which sends as hello@speculum.vote.
- Secrets (GitHub): CONGRESS_API_KEY, FEC_API_KEY, LDA_API_KEY, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, ANTHROPIC_API_KEY, SPECULUM_DISPATCH_TOKEN (fine-grained token, owner speculum-vote, Actions read/write), SPECULUM_ADMIN_PASSWORD (signups page), CLOUDFLARE_ACCESS_TOKEN (Access policies only).
- Email: hello@ and corrections@ forward through Cloudflare Email Routing to the Speculum Gmail account, which sends as hello@speculum.vote. Instagram: @speculum.vote.

## Snapshots

- A data file is stored only on a night its content changed. Each night's `meta.json` has a `files` index: for every file, the night whose copy stood that night, its SHA-256 and size. Reads follow the index, so a night that stored nothing for a source (unchanged, or the fetch failed) shows the copy that stood.
- After a full run on the newest night, copies no longer standing leave the working tree (`prune` in `speculum/snapshot.py`). They stay in git history, and the raw filings behind them stay in that night's raw release. `meta.json` and `tide.json` stay on every night; Day Zero keeps every file as the baseline.
- `python -m speculum restore <date>` rebuilds any night's files from git history and checks each against the index (a shallow clone needs `git fetch --unshallow` first).
- `lobbying.json` and `spend.json` are written as compact JSON. GitHub refuses files over 100 MB, and the run prints a warning when any file passes 80 MB. Gzip is written with a fixed header, so unchanged data gives unchanged bytes. Big files stay uncompressed on purpose: git stores a plain night as a small delta, while a gzipped one would be stored whole.
- The checkout holds about 180 MB of snapshots (Day Zero plus one standing copy of each file) and grows by a few KB a night, plus the size of whatever changed.
- A back-dated rerun (`--date` earlier than the newest night) never prunes. It keeps that night's saved edition of The Tide when the night before is in git history only.
- A night whose edition of The Tide failed to build keeps its own files, and the night before's, until it has one. The site build then makes the edition from them. A rerun whose copy turns out the same as the night before's drops its copy and updates the index.

## The site's sections

Home (`index.html`), The Tide (nightly editions with a dated timeline), Findings (fixed measures), The Chamber (`chamber.html`, every member), The Money (campaign sources, lobbying contributions and spending by issue area, shared funders), Bills (who lobbied each bill, by sector, from LD-2 descriptions; sector rules in `speculum/lobbysectors.py`), Said & Done (`saiddone.html`, below), Interests, The Dependents (decisions traced to outcomes, by theme), Day Zero, Method, About, Corrections, Join the readers (`join.html`).

The Dependents has five themes, each a rule in `RULES` (`speculum/chains.py`):
- Foreign arms sales (`chain.html`): Senate votes on Arms Export Control Act disapprovals; money from SIPRI Top 100 companies (`data/sectors.json`).
- Regulations overturned (`chain_rule.html`, added November 6): every roll call in either chamber on a Congressional Review Act disapproval; one chain per resolution across both chambers. Money around each chamber's last vote comes from organizations whose LD-2 reports name the resolution (LD-203, through the vote date). The drafter has its own brief (`SYSTEM_RULE` in `speculum/interpret.py`): the rule, what it required, and the agency's own benefit and cost estimates side by side. It drafts resolutions that became law first, oldest first. 48 resolutions; at 3 drafts a night (`--limit 3` in `nightly.yml`), research takes about 16 nights, and each chain goes public once its record passes the source check. The Dependents' measures are fetched first in the nightly bill-details step, so every resolution's final status (became law or not) is known.
- Budget reconciliation, Ending national emergencies and War powers (added November 6): same page (`chain_rule.html`) and money method as regulations. Each rule has a `page` block that sets its heading, subject, record fields and closing note. Each has its own drafter brief (`BRIEFS` in `speculum/interpret.py`). Selected by statutory title wording: "to provide for reconciliation pursuant to" (2 bills: H.R. 1, S. 2); "terminating the national emergency declared" (7, all Senate so far); "removal of United States Armed Forces from hostilities" (18, Senate so far). House votes on these appear as House bill titles arrive.
- Research path for the newer themes (November 8): drafts state one fact per outcome with the source's own passage ("quote", "locator"); records name each field's sources ("field_sources") and are checked field by field (`record_fields` in `speculum/chains.py`); a chain publishes once its core fields pass (the theme's main field and "status"); benefit and cost estimates show only as a pair. The checker sends long sources as their opening plus every passage containing the claim's figures or quotes (`passages` in `speculum/verify.py`). Failed draft claims are revised once from the checker's note (`chains --revise`, before the check in `nightly.yml`), never adding facts; old whole records are split into fields on revision. The nightly check limit is 80 claims. Arms-sale records keep the whole-record check.
- The first six regulation drafts (November 7-8) all came back "partly supported": dense claims with one wrong detail each, Federal Register rules cut off at 200,000 characters, and Congress.gov unreadable to the checker. The changes above answer each.
- 75 chains await research across the four newer themes. At 3 drafts a night that is about 25 nights; raising `--limit` on the chains step in `nightly.yml` speeds it up at more API cost.

Said & Done (added November 8, `speculum/saiddone.py`): sets one kind of filing against another by a fixed rule. The first measure, "Both sides of the vote": for a bill, the organizations that named it on their own LD-2 reports (said) and the members they or their PAC funded on each side of its final vote (done, LD-203, 2025–2026, before or after the vote; lobbyists' own contributions and lobbying firms left out). The deciding vote is the last roll call in each chamber on the measure itself (`DECISION`); simple resolutions are left out. A bill qualifies once 5 organizations that lobbied it funded its voters (119 bills on November 8).
- Readers' rounds: bills open one at a time. H.R. 1 opened first (most lobbied; 629 of 683 funders funded both sides, recounted independently). Each round runs 7 days over the 6 most-lobbied qualifying bills not yet open; verified reader-checkers vote on early.speculum.vote. State is `data/saiddone.json`; `python -m speculum saiddone` (nightly, before the commit) counts a closed round from the private sign-up store, opens the winner (tie: more organizations lobbied, then list order; no votes: nothing opens) and starts the next round. Only totals are kept; the votes are deleted after counting.
- The ballot is `functions/api/ballot.js`. A voter must be signed in through Access on early.speculum.vote (the function checks the Access token's signature against the team's certificates and the app's audience tag, read with CF_ACCESS_TOKEN, which `deploy.sh` now also sets on the preview project) and be approved on their sign-up record. One vote per reader per round, changeable until the round closes (end of the closing day, Eastern). On speculum.vote the page lists the shortlist and links to Join the readers.
- The owner votes only if their own email is approved on the sign-up list.
- Not yet: links to the LD-2 reports that name the bill (the snapshot keeps only counts per organization); more measures (a member's cosponsorship against their vote; Congress's own deadlines against its record).

## Launch and rollback

Before switching (the day before or that morning):
- The day's nightly run has finished green (GitHub Actions, "Nightly snapshot"). Do not switch while a nightly run is still going: it deploys at its end, and a switch pushed between its build and its deploy would be overwritten until the next push.
- Approve your own email on speculum.vote/signups, then vote on early.speculum.vote/saiddone.html, change the vote once, and check it shows as yours.
- `data/lameduck.json`: move any newly called race from `uncalled` to `members` with its source; update the "as of" date. A push to any top-level `data/*.json` file now deploys.
- If the date moved, change the date on Instagram slide 9 before posting.

Switch: set `"public": "launch"` in `data/site.json` and commit to main (the GitHub web editor is fine). "Deploy site" runs; the first full upload of about 10,000 files takes a few minutes.

Check within 15 minutes, on a phone and a computer:
- speculum.vote shows the full home page, not the holding page; open The Chamber, one member, one bill, Said & Done, The Money, Method.
- Join the readers: send a test sign-up, see it at speculum.vote/signups, remove it.
- early.speculum.vote still asks for sign-in; speculum.vote/robots.txt says Allow.
- The next morning, after the nightly run, speculum.vote is still the full site.

Roll back: set `"public": "holding"` and commit. The deploy puts the holding page back, and every other address on speculum.vote then shows it too; early.speculum.vote and the sign-up list are untouched. For an immediate rollback, Cloudflare dashboard → Workers & Pages → speculum-public → Deployments → the last holding deployment → Rollback; set `site.json` back as well, or the next deploy relaunches.

## Next, in order

1. Launch on November 11–12 by the checklist below. The phone and desktop check of the public build was done on November 9 (no page overflows at 390 px; every internal link resolves; fixes committed). Join the readers (`join.html`) is the sign-up's home after launch.
2. Donations: undecided. Options are a Stripe payment link now with HCB fiscal sponsorship later, or HCB only. Planned funding rules: refuse money from parties, campaigns, PACs, lobbying registrants and their clients; cap each donor at about $1,000 a year; publish donor names above a small amount and monthly costs on a Funding page.
3. Requested by early readers: CSV downloads on every table and a Data page; a weekly trend report from The Tide (PDF and CSV); later, an in-browser report writer.
4. Households and capital: official series (Federal Reserve wealth shares, BEA/BLS labor share and corporate profits, real wages, housing cost burden, health coverage, life expectancy) side by side, with markers for laws the lobbying sectors worked on. Use neutral naming.
5. Later: Remove should also revoke the reader's Access session; a sector view of lobbyists who held government posts; a vetted member network (invitation tree, influence over process only, never over findings).

## Known limits and notes

- Bill titles come from Congress.gov, up to 600 a night (`speculum/sources/billinfo.py`).
- One lobbying filer is set aside, with its filings, in `data/lobbying_set_aside.json`.
- Lobbying spending matches in-house and firm reports by organization name, so totals run about 3% above independent counts (stated on the Method page).
- GitHub's own cron is unreliable; the Cloudflare scheduler is the main trigger.
- Cloudflare Pages allows 20,000 files per deployment and 25 MiB per file. The full site is about 10,100 files (mostly member, bill and interest pages) and its largest file is `ledgers.json` at 4 MB. Watch the count as bill and interest pages grow.
- LD-203 years: the current Congress's, except that through March 31 of a new Congress's first year the closing Congress's two years are still read (its year-end reports are due January 30; `_years` in `speculum/sources/lda.py`). The first night the years move on, the closing Congress's last copy is kept as `data/records/lobbying-<congress>.json` (about 76 MB for the 119th; git stores it as the same blob as the snapshot copy). Dependents chains read their own Congress's record, so their money figures do not change once it closes; member pages move to the new Congress.
- Still open: FEC committee totals on member pages and in arms-sale chains are campaign-cycle totals, so after the switch to the 2028 cycle the arms chains' PAC column would show 2027-28 money beside 2025-26 votes. The money verdicts use LD-203 only, but the PAC column should be frozen the same way (a finance record per Congress).
- Bills list and lobbied-bill ranking break ties by bill number, so the order a file lists bills in never changes a page.
- Adding a Dependents theme: a rule in `RULES` (title test from the statute, subject parser, area, `page` block, `why` with verified sources) and a drafter brief in `BRIEFS`.
