# Web overhaul - ledger and handoff for the next session (updated 2026-11-07, after Part 6)

First written 2026-11-05 after value book Part 6 merged; updated 2026-11-06 after web overhaul Parts 4 and 5 merged,
and **again on 2026-11-07 after Part 6 merged and was pushed**. A fresh session (Sonnet is fine as the orchestrator)
can carry on from this file without the conversation that produced it. Every status line below was checked against
the code on `main` (`02236ec`, equal to `origin/main`; the only untracked file is `data/value_filing_reads.json`, a
runtime file), against `git log`, `ps` and the Part 6 plan's Progress log, not copied from a plan. Finished items are
ticked and moved to **Archive (done)** at the foot of this file, so the top is only what is still open. Read the top
to the Archive heading.

## 0. Headline

- **Web overhaul Parts 1-6 are done, merged and pushed**, and so are the value book's four web sections (F-I).
  Part 6 (Research, Universe and search) landed on `main` by fast-forward on 2026-11-07 (no merge commit; the plan
  commit `affa316` on `main`, then `725f26b..3ebd3a8`, 20 commits from `feat/web-overhaul-6`), then one docs commit on
  `main` (`02236ec`, the plan's merge and push rows). 21 commits `d3d1e28..02236ec`; **no file under `src/`,
  `scripts/`, `tests/` or `config/` changed**.
- **Restart: not needed for the daemons, and not done.** All seven daemons still run from 2026-11-06 19:59:14 (Part 5's
  restart); Part 6 changed no Python, so they run the same Python as `main`. `next dev` (20:01:37) is a dev server
  that recompiles on change, so it already serves Part 6's web code. The plan's Restart row is blank; fill it as "not
  needed (web only; `next dev` recompiled)" or with the `ps` time of the next `./ibkr restart`. (Part 6's to-do 2 asked
  for a restart "so the stack runs one commit": harmless, optional.)
- **Pages on the payslip system: 14 of 17 routes** (Home, Trades x2, Portfolio, Activity, Position, More, What Claude
  knows, three ledger sub-routes, Stock, and now Research and Universe). **Not recomposed: News x2, How it works**
  (and More's theme, target-mode and credits controls inside an otherwise-done page).
- **Part 7 (News, More and How it works) is DONE, merged and pushed 2026-11-12** (`main` a491d59, 14 commits
  from `7eb2ae8`; plan `docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md`; vitest 1625 in 153
  files). News and a name's news page are on the payslip, How it works is seven static cards (`features/explain/`,
  `components/explain/` deleted), More names the value book, the six Open Decisions are RESOLVED in `DESIGN.md`, the
  rail's Search is an outlined field. The Opus review's three Important findings were false or incomplete sentences
  on How it works (a console halt does not stop spreads; Claude's size cut; the capital-release chain), fixed in
  `c55379d`; the operator then ruled the "Four books" card to "Three books in one account" (`a491d59`). **Part 8
  (the value record) is next, gated on a month of paper record.** Open: none for Part 7.
- **The order is unchanged**: Part 8 value record (gated), order control on its own
  track. The six operator questions keep their defaults (5.3); Part 6 changed none of them.

## 1. Where things stand

| Part | Plan | State | Landed on `main` | What shipped (verified in code) |
|---|---|---|---|---|
| 1, 1b, market-picture web, 2, 3, 3b, value F-I | see Archive A.1 | **Done, pushed** | `ab7339c` ... `6045d2f` | Archive A.1 |
| 4 - Cleanup, honesty, value gaps | `plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md` | **Done, pushed, restarted** | fast-forward to `a7fddc9` (2026-11-05) | Archive A.2 |
| (not a numbered part) drawdown window, hero range change, spreads card health | commits only | **Done, pushed** | `544e32e`, `6347dd9` (2026-11-05) | Archive A.2 |
| **5 - The stock page** | `plans/2026-11-06-web-overhaul-5-stock-page.md` | **Done, pushed, restarted** | fast-forward to `b408cf0` (2026-11-06), merge row `d3d1e28` | Archive A.5 |
| **6 - Research, Universe, search** | `plans/2026-11-06-web-overhaul-6-research-universe-search.md` | **Done, pushed; restart not needed (web only)** | plan `affa316`, fast-forward to `3ebd3a8` (2026-11-07), rows `02236ec` | Archive A.6 |
| **7 - News, More, How it works (NEXT)** | `plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md` | **Plan written, not started, not committed** | - | 5 sections (A carried, B News, C How it works, D More and Open Decisions, E finish), 11 tasks |
| 8 - The value record (gated) | none | Not started | - | |
| Order control (own track) | none, no spec | Not started | - | History still says "A working order is cancelled in IBKR for now" |

**Verified today (2026-11-07):**

- `main` = `origin/main` = `02236ec` (`git status -sb`: `## main...origin/main`). Worktrees still on disk:
  `.claude/worktrees/value-book-6` (`ca14c40`), `.claude/worktrees/web-overhaul-4` (`a7fddc9`),
  `.claude/worktrees/web-overhaul-5` (`b408cf0`), `.claude/worktrees/web-overhaul-6` (`3ebd3a8`). Every `feat/*` and
  `fix/*` branch listed in operator to-do 3 is merged into `main` (`git branch --merged main`),
  `feat/web-overhaul-6` included; `fix/refresh-invalidation-loop` is **not** merged and is not this overhaul's.
- `python -m pytest -q` from the main checkout: **5767 passed, 1 skipped** (equal to Part 5; Part 6 changed no Python). `ruff check .` clean; `mypy src` **361 files**, clean.
- `cd web && npx vitest run`: **1623 tests in 157 files** (Part 6's fix pass ended at 1623; Part 5 at 1562);
  `npx tsc --noEmit` and `npm run lint` clean.
- da-vinci `design_md_check.py web/DESIGN.md` exits 0 (marker `updated=2026-11-07`, Part 6 Task 15); `lint.py` over
  `web/app web/components web/features` still finds one non-test hit, the legacy em dash (an `&mdash;` entity) at
  `components/explain/SourceRefs.tsx:21` (Part 7's page).
- Daemons (`ps`): approval_service, monitor, api, research_worker, spreads, news, value all started
  2026-11-06 19:59:14 (IB Gateway 19:59:10); `next dev` 20:01:37 (the headline says why that is current).
- `df -h .`: 22 GiB free at 95%.

## 2. What the overhaul intended, and how much is done

### 2.1 Pages (open rows only; done pages are in Archive A.3)

| Surface | Route | State | What is missing |
|---|---|---|---|
| News | `/news`, `/news/[symbol]` | **NOT DONE; Part 7** | `components/news/NewsFeed.tsx` has no page title, old chips (`rounded-sm px-3 py-1`, under 44 px) and a 28-wide `font-mono` symbol input; `NewsTicker.tsx` a `font-mono text-lg` title, bare inline story links and a legacy brief button (`BriefRequest`, a `submitCommand("news_brief")` site that stays) |
| How it works | `/explain` | **NOT DONE and stale; Part 7 (Q1)** | 8-tab shell (`components/explain/ExplainShell.tsx`, `px-8 py-6`, `font-mono text-2xl` "System Explanation"), 1,532 lines with tests, static copy only (no API read); says nothing of spreads, the value book, regime sizing, capital release, the news thread or the roll redesign; carries the last non-test em dash (`SourceRefs.tsx:21`) |
| More | `/more` | **PARTIAL; Part 7** | links and titles are on the payslip; the theme, target-mode and credits controls are legacy (Part 6 Task 15 finding (f)); no value mention (L6) |
| Order control | (History) | **NOT DONE; own track** | F1 |
| Recommendations | `/recommendations` | **CUT (Q5 default)** | API route and Telegram card stay |

### 2.2 Cross-cutting intent (open rows only)

| Intent | State | Evidence |
|---|---|---|
| `DESIGN.md` Open Decisions | **OPEN; Part 7 (Q6)** | product name, favicon, icons, sheet exit, the decide controls' look, the disabled quiet button (`web/DESIGN.md` "Open Decisions") |

## 3. Remaining work, itemised

IDs are stable from the first version of this file; closed ones are in Archive A.4.

### 3.1 Legacy surfaces still to be recomposed (L)

| ID | Item | Size (code today) | Part |
|---|---|---|---|
| L4 | News feed and News ticker (`NewsCard` content and `BriefRequest`'s command stay) | `components/news` 496 lines with tests; `app/news` 29 | 7 |
| L5 | How it works (Q1) | `components/explain` 1,532 lines with tests | 7 |
| L6 | More: a value mention, and the legacy theme, target-mode and credits controls (titles landed in Part 4, the Search row in Part 6) | `app/more/page.tsx` 91 | 7 |

### 3.2 Gaps on existing surfaces (V)

| ID | Gap | Part |
|---|---|---|
| V7 (rest) | Top opportunities: stop always null (left until a policy sets one); "Sell a put" shows on a scan's `passed` stage, not a re-gate (H4, left). The card's `claude_note` landed in Part 6 | left |
| V9 | A value sale with unknown realised P&L is left out of the month sum with no "incomplete" flag | 8 |

### 3.3 Shell and design-system debt (S)

| ID | Item | Part |
|---|---|---|
| S4 | `DESIGN.md` Open Decisions (Q6) | 7 |
| S5 | `DESIGN.md` Surfaces paragraphs for News (rewrite) and How it works (new), More (rewrite) (Stock, Research, Universe: done) | 7 |

### 3.4 Deferred minors still open (M)

- **Part 1:** a holiday or early close reads "Delayed" on the hero (accepted); the sheet's 180ms exit and the
  decide controls' look (S4).
- **Part 2:** the smart default can open on an empty Proposals during an in-flight Approve; `activity_days` loads
  every approval snapshot per `/pnl/day`; `positionHref` keeps `paper` (correct: only a paper spread has a page).
- **Part 3:** `/ledger/executions` covers days+1 calendar days; a name card's open P&L under a type chip sums the
  visible legs only; with `source: none` and open spreads, Positions shows only the spreads card; da-vinci-finish
  tests assert class names; `SpreadFills` shows the raw `mode`.
- **Part 4:**
  - Home's `PositionsCard` says "No portfolio snapshot has been captured yet." under the Value chip with an empty book;
  - review-accepted costs: a book switched off after selling whose value.db later cannot be read hides the
    "Value book unavailable" flag (ruling 7); the mixed phone banner reads "2 proposals need you" while Open goes
    to Trades (ruling 15); an enabled book with no value.db reads "could not be read"; the value drain reads "Not
    checking" during a night run longer than 300 s;
  - stale comments in the protected `AutonomyControl`, `HaltControl`, `DecideControls` (they name deleted files);
  - History links omit today and All; `PayView` fetches the unfiltered month once before the floor is known;
    `strategyWord` passes labels other than the two wheel strategies through raw;
  - finish observed, not fixed: the strategy switcher wraps "Value" to a second row at 390 px and "All" in the
    range chips at 320 px (operator, to-do 5); the protected receipt reads "accepted, waiting for the trading
    service" above the value note (S4); "See the value file" is READY-only on Top opportunities (ratified,
    operator); the "Value book" chip-group label sits 4 px under the chips; the disabled next-day arrow draws a filled
    circle (Open Decision, Q6);
  - review nits: `DecideControls.test.tsx` titles use an em dash, `boundaries.test.tsx`'s `once` assertion.
- **Part 5 (from its Progress log's Task 11, review and fix-pass rows; verified in the code on `main`):**
  - `_one_line` in `src/api/routers/value.py` can drop a whole last word and leave a trailing comma before the
    ellipsis (cosmetic);
  - a held name whose value file is not-applicable or missing draws no Stop or Half sale on the chart though a plan
    exists (edge case);
  - the tranche sentence and the Sentiment sample counts lack `.tabular`; long pane labels at 320 px sit over
    candles; the statements' scroll hint is `md:hidden`, so a long quarterly table can overflow unannounced between
    768 and 1023 px;
  - at one year (~2.8 px per bar at 1440 px) a hollow up candle and a filled down candle read alike: the real fix is
    range chips or zoom (Part 5 ruling 13 deferred them): **operator call** (to-do 6);
  - the Sentiment row for a source with no score reads "n/a" then "n/a samples" (each true, redundant); fully hatched
    statement columns are loud when most of a column is unknown; the stock 404 sentence has no Research link besides
    the back link (ruling 15).
- **Part 6 (new, from its Task 15 row's "Findings NOT fixed" and the review row; the Opus reviewer judged none
  needed before merge; verified in the code on `main`):**
  - (a) the rail's Search row (`components/shell/Rail.tsx`) shares the active row's pressed-sage fill, so with
    Research active two rows look alike (weight and `aria-current` tell them apart): a **proposal for the operator**
    (draw Search as an outlined field instead; ruling 9 and DESIGN.md name the pressed-sage row) (5.4 Q4);
  - (b) Sectors prints "IV rank 71.2 (7)" with a bare count ("(1 name)" for one): a **copy proposal**, "(7 with
    history)"; the form is DESIGN.md's and Part 6 ruling 12's (5.4 Q4);
  - (c) Universe's two-column grid leaves a ~100 px gap under the short Indexes card (rows align; two independent
    columns would break the phone DOM order): accepted;
  - (d) Universe rows wrap Remove inconsistently on a phone (beside the name for two facts, own line for three; both
    44 px): accepted;
  - (e) the palette's hint text truncates on a phone, and an exact ticker typed and Entered inside the first answer's
    wait does nothing (it now shows "Searching tickers."): hints are secondary, accepted;
  - (f) More's legacy theme, target-mode and credits controls: **Part 7** (L6).

### 3.5 Features never built (F)

| ID | Item | Call |
|---|---|---|
| F1 | **Order control**: cancel a working order from Trades, History (a `cancel_order` kind, a drain handler, `ConfirmAction` + the LIVE second confirmation, a receipt) | Own track, spec first (superpowers:brainstorming) |
| F2 | Ladder next-lot zone per held name, "room left under the regime budget", governing regime per held name | Defer until a month of regime-sizing record |
| F4 | `/recommendations` | Cut (Q5) |
| F5 | Web surface for the value book's go-live evidence | Part 8 |

## 4. Recommendations (open items only)

| ID | Call | What, and why |
|---|---|---|
| L4, S5 News | **BUILD ON (Part 7)** | News on the payslip with the Stock/Research frame: a page title, the Market card leading, the group chips and the symbol filter at 44 px, the calendar as a card of rows; the ticker page with a title, the brief request as a secondary button (its `news_brief` command, `CommandReceipt` and poll unchanged), Recent stories as rows with 44 px links and a Stock page link. `NewsCard` content stays; `VerdictPill`'s `text-gain`/`text-loss` on a forecast becomes ink (ruling 7: a forecast is not money) |
| L5, S5 How it works | **REBUILD SMALL (Part 7, Q1 default)** | One page of static plain-English sections in `features/explain/`, each linking to the console page that shows it; `components/explain/` (1,532 lines with tests, stale) deleted |
| L6 | **BUILD (Part 7)** | More: one "Value book" row, and the theme, target-mode and credits controls restyled in place |
| S4 | **CLOSE (Part 7, Q6 defaults)** | Record each decision in `DESIGN.md`; the only code it needs is a favicon (`web/app/icon.svg`, a text mark) and the disabled quiet button's rule in `components/ui/Button.tsx` |
| Part 6 Task 15 (a), (b) | **ASK (5.4 Q4)** | The rail's Search row as an outlined field; "(7 with history)" on Sectors. Each one small patch if taken |
| V9, F5 | **DEFER (Part 8)** | Unchanged |
| F1 | **BUILD, own track** | Unchanged |
| F2 | **DEFER** | Unchanged |

## 5. Proposed parts from here

Every part is one plan of the Part 4/5/6 shape (Execution model with Model and Effort columns, Progress log,
Roadmap, Rulings, Global Constraints, Review Focus, File structure, sections with entry checks, tasks with gates,
whole-branch review). "Part N" means **web overhaul Part N**.

| Part | Scope | Items | Depends on | Size |
|---|---|---|---|---|
| **7 - News, More and How it works (DONE 2026-11-12)** | News feed and ticker on the payslip; How it works rebuilt small (Q1); More's value row and legacy controls; DESIGN.md Open Decisions closed (Q6); the Part 6 proposals the operator takes (5.4 Q4) | L4, L5, L6, S4, S5, Part 6 (a)/(b) | Part 6 (done), the 5.4 answers | 5 sections (A carried, B News, C How it works, D More and Open Decisions, E finish), ~12 tasks (outline in 5.4) |
| **8 - The value record (gated)** | `GET /value/record` over `value_db.py`, an Activity view: baseline vs Claude, horizon returns, clamp frequency, breaker state, drawdown vs SPY; the `MonthPay` realised-complete flag | F5, V9 | a month of paper record with the book on (Q4) | 2 sections + finish, ~6 tasks |
| **Order control (own track)** | Spec, then plan: `cancel_order` kind, drain handler, Cancel behind `ConfirmAction` + LIVE second confirmation, receipt, History copy | F1 | spec | spec, then ~7 tasks |

### 5.1 Rulings (standing; the operator may overturn any)

1. **Numbering**: the old Part 4 became Parts 4-7; order control has no number.
2. **No fold of `components/` into `features/`.** New code goes in `features/`; `components/` keeps `ui`, `shell`,
   the protected `options` controls, `value` and the survivors (written into `web/CLAUDE.md` and
   `ARCHITECTURE.md`). Living legacy components are restyled **in place** (Part 5 did this for `components/stock`
   and `components/checks`, Part 6 for `components/home`, `components/search` and `components/universe`; Part 7 does
   it for `components/news`). A legacy surface replaced whole (Part 7's `components/explain/`) is deleted.
3. **`components/value/` stays**; the command-site grep stays: `grep -rln "submitCommand\|confirmCommand"
   web/features` prints `features/more/TargetCard.tsx`, `features/stock-value/AnalyseButton.tsx` and their tests.
   (Universe's command sites are `submitUniverseCommand` in `components/universe/`, and News's is
   `components/news/BriefRequest.tsx`; both outside that grep, and they stay where they are.)
4. **The value book gets no top-level nav destination, no Trades tab and no new page** until Part 8 (Q3 default).
5. **The calendar keeps its second request** for the value split.
6. **No new token, colour, font, radius or elevation** in any part; a da-vinci proposal for one waits for the
   operator.
7. **Green and red are for signed money only** (DESIGN.md Colors). Part 5 applied it to candles, the check
   ribbon, headline tone and the sentiment change; Part 6 to the watchlist's and the sectors' day change (a price
   move: signed, not coloured); Part 7 to the news verdict pill (a forecast) and any other legacy surface it
   recomposes.

### 5.2 What each part must not do

- Part 7: add a command site, change a protected file, a Rules Engine path, a gate, sizing or the value book's
  logic; add an API route or field (News and the ticker page read what is already served). Part 8: add a write.

### 5.3 Questions for the operator (defaults shown; plan writers assume them; Parts 4-6 changed none)

1. **How it works (`/explain`)**: rebuild small, rebuild in full, or cut? *Default: rebuild small (Part 7).* (Part 7
   asks it again, made concrete, as 5.4 Q1.)
2. **Order control**: build it after Part 7, or leave it? *Default: spec in parallel; build after Part 7.*
3. **A "Value" destination** (own nav item and page) or the current spread across Home, Stock, Research and a record view in Activity? *Default: no new destination.*
4. **When should the value record view (Part 8) be built**: now, or after the paper sleeve has run a month with `value.book.enabled`? *Default: after.* (The book has been enabled in paper since at least 2026-11-05.)
5. **Confirm cutting the `/recommendations` page.** *Default: cut.*
6. **Close the `DESIGN.md` Open Decisions.** *Defaults: keep "IBKR Income" with a text wordmark and a simple favicon; keep lucide icons; keep the immediate sheet close; leave the legacy bordered decide controls inside sheets as the recorded exception; a disabled quiet button stays transparent and only dims.* (Part 7 asks it again as 5.4 Q2.)

### 5.4 Part 7 outline and scope questions (written 2026-11-07 by the Part 7 plan writer; answered by the operator 2026-11-07, all five as recommended; now the plan's rulings 2-6)

**Outline** (the plan is written after the answers; every section prototyped on a scratch copy of `main`, patches
pinned by SHA-256, a Sonnet orchestrator with one Sonnet subagent per section):

| Section | Tasks | Effort | What |
|---|---|---|---|
| A0 | setup | - | plan + HANDOFF commit on `main`, worktree `web-overhaul-7`, helper, hashes |
| A, Carried | 1-2 | medium | (1) the Part 6 proposals taken under Q4 (rail Search row; Sectors copy); (2) the Part 5 stock minors in the web only: `.tabular` on the tranche sentence and the Sentiment counts, the statements' scroll hint shown below `lg` (not `md`), one "n/a" instead of "n/a samples" |
| B, News | 3-5 | high | (3) `features/news/NewsPage.tsx`: the frame, the Market card first, the group chips and a 44 px symbol field, the feed states in words; (4) the calendar as a card of rows, `NewsCard` and `VerdictPill` restyled in place (the verdict in ink, ruling 7); (5) `features/news/NewsTickerPage.tsx`: title, next earnings, the brief request as a secondary button (command unchanged), Recent stories as rows with 44 px links, a link to `/stock/SYM` |
| C, How it works | 6-7 | high | (6) `features/explain/ExplainPage.tsx`, one page of static sections per Q1 (each sentence checked against `CLAUDE.md` and the code; a test pins the headings, the links and no em dash); (7) delete `components/explain/` and its tests, update the search page hint and the More row's sub |
| D, More and Open Decisions | 8-9 | medium (8), high (9) | (8) More: a "Value book" row and the theme, target-mode and credits controls restyled in place; (9) Q6: the disabled quiet `Button` rule (+ tests over History's, Spreads' and Activity's arrows), `web/app/icon.svg`, `DESIGN.md` Open Decisions closed with Decision Log entries |
| E, Finish | 10-11 + review | medium (10, docs), high (11, fresh da-vinci reviewer), opus high review, sonnet high fix pass | DESIGN.md Surfaces (News, How it works, More), STATUS, ARCHITECTURE, `web/CLAUDE.md`; captures at 320/390/1440 light and dark against a synthetic API (`mock7`, `capture7`), `main`'s scroll measured |

**Questions** (each with the writer's recommendation; the operator's answers become rulings):

1. **How it works scope (Q1 made concrete).** (a) rebuild small: one page, about seven short sections (the day's
   cycle from scan to send-time re-gate; who decides what: the Rules Engine, Claude and its two written exceptions,
   you; the four books: wheel, spreads, value, news; safety: paper and live, halt, autonomy, breakers; what each page
   is for, with links), static copy in the web, no API; (b) rebuild in full (the eight panels brought up to date;
   about three times the work, and it ages with every change); (c) cut: redirect `/explain` to `/more` and drop the
   row. *Recommended: (a).*
2. **Open Decisions (Q6 made concrete).** Take all six defaults: "IBKR Income" as a text wordmark plus a text-mark
   favicon (`app/icon.svg`, ink on paper, no new colour); lucide icons; the immediate sheet close; the legacy
   bordered decide controls inside sheets as the recorded exception (protected files untouched); a disabled quiet
   button stays transparent and only dims (changes the shared `components/ui/Button.tsx` rule: History's, Spreads'
   and Activity's end-of-range arrows). *Recommended: all six as defaulted.*
3. **The ticker news page.** Keep `/news/[symbol]` (the brief request, the latest brief and the story clusters live
   only there) restyled, with a link to the stock page; or fold it into the stock page's News section and redirect.
   *Recommended: keep and cross-link (no API change; the fold would need the stock page to carry a command site).*
4. **Part 6's two proposals.** (a) draw the rail's Search row as an outlined field so it never looks like the active
   row; (b) Sectors' "IV rank 71.2 (7)" reads "(7 with history)". *Recommended: take both (two small patches in
   Section A); say no to either and it is dropped.*
5. **The Part 5 stock minors in Section A (web only).** Include the three cheap ones above, or leave them. *Recommended:
   include.* (`_one_line`'s trailing comma, a Python change, stays deferred either way.)

**Increments to write the plan:** about four (1: header, Progress log, rulings, constraints, A0 and Section A; 2:
Section B; 3: Sections C and D; 4: Section E, the full gate on the final tree and cleanup), five if the How it works
copy runs long.

## 6. Binding rules for any plan writer

- **Core invariant.** The Rules Engine is the only path to an order; nothing the web or Claude produces gates,
  sizes or prices anything. The two written exceptions in `CLAUDE.md` (the CSP contract cut; the value verdict)
  are untouched and the web only displays them, with Claude's words labelled as Claude's and never on a button.
  Text written by a model that may not be Claude (the research summary backend can be Ollama or OpenAI) is
  labelled by its model, not as Claude's.
- **Web fence.** The API reads the trading database read-only and writes exactly one table, `app_commands`,
  through `src/api/commands.py` (research.db's per-user watchlist rows are research-side, not the trading DB).
  Every web action on the trading side is an intent drained by `approval_service` (or, for the six `value_*` kinds,
  by the value process). `tests/test_web_fence.py`, `test_eval_skills.py`, `test_regime_fence.py`,
  `test_news_fence.py`, `test_spreads_fence.py`, `test_value_fence.py` and `test_wheel_spreads_isolation.py` stay
  green and are never weakened.
- **Value fence.** The API imports from `src.value` only `scorecard` and `schemas`; only `src/api/value_db.py`
  opens value.db (`mode=ro`, plain SQL). A rule the API needs from `src.value` is mirrored in `src/api/` with a test
  that holds it equal to the original (Part 5's `_size_pct`). `src/reporting/` imports nothing from `src.claude`
  or `src.value`.
- **Protected files:** `web/components/options/{DecideControls,ConfirmAction,CommandReceipt,HaltControl,AutonomyControl,RollModeControl}.tsx`,
  `web/lib/commands.ts`, `web/lib/receipt.ts`: `git diff --stat main -- <paths>` prints nothing at every section exit.
  A test file beside a protected component (Part 6's save-side cases) is not protected.
- **da-vinci.** Every UI task invokes the `da-vinci` skill first (and says so in every subagent prompt, with the
  concrete spec so it has little to decide); the finish runs `critique` + `audit` + `polish` at 320/390/1440 px,
  light and dark, by a **fresh reviewer agent** against a synthetic API in the scratchpad (never the live API).
  `web/DESIGN.md` is the visual authority (tokens only, lime only on the primary act, unknown is a hatched `n/a`,
  no state by colour alone, no shadow except the sheet and confirm dialog, charts never animate in, 44 px phone
  targets, zero em dashes and none of "seamless/robust/unlock/elevate" in UI copy). New surfaces get a Surfaces
  paragraph and a Decision Log entry; `design_md_check.py web/DESIGN.md` exits 0 and the marker date is bumped.
- **Look at the page the way the shell scrolls it (Part 5 lesson).** The shell scrolls `main`, not the document, so
  a `fullPage` capture shows one viewport and `document.documentElement.scrollWidth` never reports a sideways
  scroll. A capture harness scrolls `main` in chunks and measures `main.scrollWidth - main.clientWidth`; Part 5's
  sideways scroll at 320 px was caught only that way. A page-level grid with no column template is sized by its
  widest child: use `grid-cols-1` (or a `minmax(0,1fr)` template).
- **Never build inside `web/`.** The operator's `next dev` shares `web/.next`. Builds run in a scratch copy in the
  session scratchpad (the `mktemp` + `rm -rf "$(dirname ...)"` form is refused by the sandbox; remove the
  `node_modules` symlink first, then the copy, by literal path). The Google-font fetch in `next build` fails
  transiently ("Cannot read properties of null (reading '1')" in `next/font/google`): retry up to three times
  before calling the build red. The route table lists **18 routes plus `/_not-found`** (Part 5's plan said "19
  routes plus `/_not-found`", counting `/_not-found` in the 19).
- **Gates.** After every web task `cd web && npx vitest run && npx tsc --noEmit && npm run lint`; after Python
  `python -m pytest -q && ruff check . && mypy src` from the worktree root. After any API contract change regenerate
  offline: `IBKR_CONFIG_USE_EXAMPLES=1 python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json`
  then `cd web && npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts`; `tests/test_openapi_current.py`
  stays green. A field the API always sends but declares with a default becomes a **required** key in
  `api-types.ts`, so typed web fixtures need it (Part 4 Task 2, Part 5 Task 2). **Baselines (2026-11-07, after
  Part 6):** pytest 5767 + 1 skipped, vitest 1623 in 157 files, mypy 361 files (recompute from `git log`; counts go
  stale). `tests/test_scan_timeout.py` is a known flake: re-run it alone.
- **Execution model (token-light, operator-mandated, effort updated 2026-11-06).** Work in a worktree
  `.claude/worktrees/web-overhaul-N` on `feat/web-overhaul-N` (symlink `.venv` and `web/node_modules`, run
  `init_db()` with `IBKR_CONFIG_USE_EXAMPLES=1`). The main session is a **Sonnet orchestrator**; it runs each
  section's entry checks itself, spawns **one Sonnet subagent per section** with the effort the plan's Execution
  model table gives (**medium for mechanical edits, high or xhigh for tricky UI or shared state; low only where it
  genuinely does the job**: operator, 2026-11-06), verifies the report itself (`git log main..HEAD`, `git status`,
  gate counts, the protected-file diff, the command-site grep) and **stops and asks before the next section**.
  After the last code section: one Opus whole-branch review (high), then one Sonnet fix pass (high); ask before
  merge or push.
- **Plan specificity (operator, 2026-11-06; Part 5 proved it).** Plans are executed by Sonnet with no design
  decisions of their own: every change is a `git apply` patch embedded in the plan, pinned by SHA-256 and extracted
  by a helper that also repairs blank context lines, so the apply check itself is the entry check that re-verifies
  every edited line; complete test code; exact commands with expected output; exact paths and a gate per task;
  concrete layouts, tokens and copy for visual work, existing components by exact import path. Prototype the whole
  part on a code-only scratch copy of `main`, confirm each new test fails against the old code, and say in the plan
  what was and was not run. Small visual details may be left to da-vinci where it is better placed, with every
  change recorded as a ruling.
- **Progress log.** The plan carries one; after every task tick its boxes and fill its row (status, commit, gate,
  date, every ruling with its cost-if-wrong) in the same commit; **add rows for the merge, the push and the
  restart, and fill the restart row when the restart happens** (Part 4 had no row; Part 5's row was written before
  the restart and still says "owed").
- **Doc-update table (`CLAUDE.md`).** New file/module: `ARCHITECTURE.md` folder guide; new config key: the
  committed example + `ARCHITECTURE.md` + `SETUP.md`; feature built/deferred: `STATUS.md`; UI surface:
  `web/DESIGN.md`, `web/CLAUDE.md`, `docs/web/api.md` for any route or field, `docs/web/commands.md` for any kind.
- **Gotchas.** Never import `scripts.run_*` (py_compile instead); never copy `research.db`; worktree sessions cannot
  edit private `config/*.yaml`; daemons do not hot-reload (`./ibkr restart`, trading service before the API); never
  add an `AGENTS.md`; `df -h .` as an entry check (22 GiB free at 95% on 2026-11-07); pin `now` in tests that compare
  fixture times; in a test file import `@/lib/test-query` before `@/lib/api` and `@/lib/commands`; the repo is not
  prettier-formatted (hand-indent, never `prettier --write` a whole file); BSD `sed` treats `\t` as `t`; da-vinci `lint.py` refuses a path that does not exist
  yet, so a section gate lists only folders that exist at that point (Part 6 G5).

## 7. Briefs and to-dos

### 7.1 Brief for the Part 7 plan writer (done 2026-11-11: the plan is written; kept for the record)

A plan-writer agent wrote the outline and questions in 5.4 on 2026-11-07 and stopped (the operator is near the weekly
usage limit, so it works in increments and stops after each). Resume it with the operator's answers to 5.4 Q1-Q5 and
"continue"; it writes `docs/superpowers/plans/2026-11-07-web-overhaul-7-<slug>.md` in about four increments, each
adding finished, prototyped sections. If that agent is gone, spawn one `general-purpose` agent (`model: opus`) with:
"You are the plan writer for web overhaul Part 7 (News, More and How it works). Read CLAUDE.md, web/CLAUDE.md,
web/DESIGN.md, this HANDOFF in full (sections 3-6 bind you; 5.4 is your outline and holds the operator's answers), the
Part 5 and Part 6 plans and their Progress logs (reproduce Part 6's format: patches embedded and extracted by the
helper, pinned by SHA-256, entry checks that `git apply --check` every patch, complete test code, a red check per task,
a gate per task, effort per section, a Sonnet orchestrator with one Sonnet subagent per section, rows for the merge,
push and restart). Prototype the whole part on a code-only scratch copy of main (git archive; symlink .venv and
web/node_modules), run pytest, vitest, tsc, lint, ruff, mypy and a scratch build, render it against a synthetic API and
measure `main`'s scroll (not the document's), generate the patches from a per-task git history, delete the copy. Do
not commit. Work in increments and stop after each."

### 7.2 Brief for the Part 7 orchestrator (after the plan is written)

Open a fresh session (Sonnet, high) in the main checkout and give it:

```
Execute docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md with superpowers:executing-plans, as its
"Execution model" says: you are the orchestrator; run each section's entry checks yourself, spawn one Sonnet
subagent per section at the effort the table gives (pass effort on every spawn), verify its report yourself, and
stop and ask me before the next section. Every UI subagent invokes the da-vinci skill first. Never build or run
next dev inside web/. Keep the plan's Progress log current in the same commit as each task, including the Merge,
Push and Restart rows (fill the Restart row when it happens, or write "not needed" for a web-only part). Ask before
merging or pushing.
```

### 7.3 Operator to-dos

1. **Approve running Part 7** (7.2). Read its rulings 13-25 (the News frame and labels, How it works' seven cards and
   their words, More's Value book row, the Open Decisions' code) and overturn any before the section that builds it.
2. Part 6's Restart row is blank: Part 6 changed no Python, so the daemons need no restart and `next dev` already
   serves it. Write "not needed" in the row with the next docs commit, or `./ibkr restart` and record the `ps` time.
3. Look once at Research and the search palette (⌘K, or the Search row on More) on a phone in dark mode (Part 6
   to-do 3).
4. Housekeeping: `git worktree remove .claude/worktrees/value-book-6`, `.claude/worktrees/web-overhaul-4`,
   `.claude/worktrees/web-overhaul-5` and `.claude/worktrees/web-overhaul-6`, then `git branch -d` the merged branches
   (`feat/value-book-1` to `-6`, `feat/web-home-followups`, `feat/web-overhaul-2` to `-6`, `feat/contract-cache`,
   `feat/news-thread`, `feat/spreads-claude-picker`, `fix/breaker-ack-auto-roll`, `fix/qualify-partial-chunks`,
   `fix/spreads-gex-map-spot-wait`, `perf/claude-token-slim`). `fix/refresh-invalidation-loop` is not merged: decide
   separately.
5. Disk: `df -h .` shows 22 GiB free at 95%; check before each long run.
6. Look once at Home on a phone in dark mode with a value proposal waiting (Part 4 ruling 15's row and banner);
   overturn it if you would rather decide from "Needs you" directly. Decide whether the strategy switcher may
   shorten "Credit spreads" so "Value" stops wrapping at 390 px (Part 4 finish, item a).
7. Look once at `/stock/<a Ready name>` on a phone in dark mode (Part 5 to-do 3), and decide whether the stock chart
   should get range chips (1M, 3M, 6M, 1Y) so candles stay legible (Part 5 Task 11 (a), ruling 13): a later task.
8. Value book live checks still owed from value book Part 6 (paper): a Telegram tap on a value card reaches the value
   process and the next RTH cycle sends; the trim card's button; the first digest night; the watchdog's value line;
   a stale card answers "out of date" (`SETUP.md` section 19, step 14).
9. Leave `next dev` running; no plan builds inside `web/`.

---

## Archive (done)

Ticked items moved here from the sections above. Nothing below is open.

### A.1 Parts and pieces done before Part 4

| Part | Plan / source | Merge | What shipped |
|---|---|---|---|
| [x] 1 - Foundation, shell, Home | `plans/2026-10-13-web-overhaul-1-foundation-home.md` | `ab7339c` (2026-10-14) | Payslip tokens/fonts/theme; ten `components/ui/` primitives; the shell; strategy switcher; `features/home/`; `GET /portfolio/value`, `/pnl/month`, `/spreads/positions`; redirects; `web/DESIGN.md` ratified |
| [x] 1b - Home follow-ups | `plans/2026-10-15-web-home-followups.md` | `bb34b58` (2026-10-15) | Done today, realised calendar, positions search + row links, position pages, settable income target |
| [x] market picture web | `plans/2026-10-20-market-picture.md` Tasks 22-23 | `ee87286`, `353cdd8` | What Claude knows, Market card, name notes, Held back or trimmed |
| [x] 2 - Trades | `plans/2026-10-19-web-overhaul-2-trades.md` | `4872a77` (2026-10-19) | `/trades` views, approval detail, roll on the position page, `approvals.decided_by`, `GET /spreads/picks` |
| [x] 3 - Portfolio, Activity | `plans/2026-10-23-web-overhaul-3-portfolio-activity.md` | `378970d` (2026-10-28) | `/portfolio`, `/activity`, `GET /pnl/sizing`, `/ledger/executions`, `/spreads/orders` |
| [x] 3b - post-Part-3 pass | commits `e2bf506`, `1dad9dc` | direct on main | Account donut, name cards, day stepper, Select, DatePicker, RefreshButton |
| [x] Value F-I | `plans/2026-10-29-value-book-6-web-telegram.md` Tasks 16-19 | `2d55bd7`, `dda50c1`, `f3622ca`, `1efcddc`, fixes `6045d2f` | Home Value card + decide flow; stock-page value block; Research Top opportunities; the `value` kind across Home |

### A.2 Part 4 - what shipped (verified in code and `git log`, 2026-11-06)

Plan `plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md`; 25 commits `20fcd7e..a7fddc9`, fast-forwarded
to `main`, pushed, restarted 2026-11-05 23:57. Gate at the review fix pass: vitest 1529 in 149 files, tsc and lint
clean, pytest 5669 + 1 skipped (Task 4), ruff and mypy (361 files) clean, G1 (protected files) empty, G2 the four
command-site files, `design_md_check` exit 0, scratch build green (18 routes plus `/_not-found`).

- [x] **A (Tasks 1-2)** `07cb80a` capital-release close words in `src/reporting/day.py` + guard test (V1);
  `3ff7463` value drain heartbeat (`value_drain_heartbeat` in `system_settings`, `GET /value/book`
  `drain_healthy`/`drain_last_seen`) (V2 backend). Early merge declined; merged with the rest.
- [x] **B (Tasks 3-4)** `5c7b88c` `GET /nav` removed (D3); `5972f63` `truncated` on `GET /spreads/orders`.
- [x] **C (Tasks 5-7)** `b42c0d9` `DecideControls.test.tsx` (14 ported, mutation-checked); `363bf07` 12 roll cases on
  `RollCard.test.tsx`, `DrainWarning` to `components/shell/`; `228b1ce` sixteen unmounted files + nine tests deleted
  (D1, D2).
- [x] **D (Tasks 8-10)** `62a71b7` `ValueDrainNote` (V2 web); `18f7feb` value taps in Needs you and the phone banner
  (`features/home/ValueWaiting.tsx`, V3, ruling 15: a row that jumps to the Value card, not a second Review);
  `16b6e89` the Value chip and card on Portfolio, the Value chip on At IBKR, `bookWord("value")`, the unavailable
  flag only when the book is off and never wrote (V4, V5, V8).
- [x] **E (Tasks 11-13)** `f022dc0` History says "could not be loaded" and the 200 cap; `ea9f8f4` Back to Trades keeps
  view, day and strategy, the Spreads day in `?day=`; `bd33441` Pay's strategy words, the `?month=` floor, the ledger
  stock gain n/a, capped spread fills, History and Fills cross-links (M honesty minors, F3).
- [x] **F (Tasks 14-15)** `03ba252` a title on every route (sibling `layout.tsx` for client pages, `app/titles.test.ts`)
  (S2); `2706c2b` `app/not-found.tsx`, `app/error.tsx` (S3; no `loading.tsx`, no `global-error.tsx`).
- [x] **G (Tasks 16-17)** `478d936` docs (every "until Part 4" line, STATUS, ARCHITECTURE, `web/CLAUDE.md`,
  `docs/web/architecture.md`, SETUP troubleshooting row) (D6); `562e5c4` the da-vinci finish by a fresh reviewer
  with ~170 captures including the F-I dark set (V10), fixing the Value card's contradiction with Needs you and the
  stacked fill-price column.
- [x] **Review + fix pass** `a7fddc9`: Needs you no longer says "Nothing needs you" beside an unknown book; Not traded
  asks for 201; `tradesReturnQuery` rejects inherited names.
- [x] **After Part 4, on `main`** (not a numbered part): `544e32e`, `6347dd9` (2026-11-05) the rolling 3-session
  drawdown window (`src/execution/circuit_breakers.py`), the hero change per range (`AccountValueSeries.change*`,
  `features/home/hero.ts`), the spreads card health.
- Rulings that changed the HANDOFF's plan: the value book was already on (Section A first); V1 needed no agreement
  work elsewhere and does not name the funding request; the heartbeat lives in the trading DB, not value.db; V4 is
  smaller (the ledger's trades are options only); D1 was sixteen files; the error page has one action.

### A.3 Pages done (from 2.1)

[x] Home `/` · [x] Trades `/trades`, `/trades/[approvalId]` (cancel is F1) · [x] Portfolio `/portfolio` (value
holdings since Part 4) · [x] Activity `/activity` (Value chip on At IBKR since Part 4) · [x] Position · [x] More
(titles since Part 4) · [x] What Claude knows · [x] Ledger sub-routes · [x] titles on every route, not-found and
error pages (Part 4) · [x] **Stock `/stock/[symbol]` (Part 5)** · [x] **Research `/research` and Universe
`/research/universe` (Part 6)** · [x] Native mobile app: cut earlier (`STATUS.md` "P5 - Mobile").

### A.4 Items closed (from sections 2.2, 3 and 4 of earlier versions)

- [x] Payslip design system; shell; safety friction held; old URLs redirect (Parts 1-3).
- [x] D1 unmounted legacy deleted, D2 tests ported, D3 `GET /nav` removed, D6 stale docs rewritten (Part 4).
- [x] D4 fold of `components/` into `features/`: cut (ruling 2). D5 other unused routes: left.
- [x] V1 capital-release words, V2 value drain health, V3 value taps in Needs you, V4 the ledger's `value` book,
  V5 value holdings on Portfolio, V8 the unavailable flag, V10 F-I reviewer and dark captures (Part 4).
- [x] S2 page titles, S3 not-found and error pages (Part 4).
- [x] Part 2 minors: In flight / Not traded unknown-is-not-none, `BackToTrades` params, Spreads day in the URL,
  "Next onto today" (already cleared the day; now pinned). Part 3 minors: spread-fills `truncated`, `?month=`
  clamp, raw `cash_secured_put`, a ledger trade's null stock gain, the Trades History and Activity Fills
  cross-links (F3) (Part 4).
- [x] Operator to-do "do not enable the book until Part 4 merges": moot (the book was already on; Part 4 merged and
  the stack restarted 2026-11-05 23:57).
- [x] The Part 4 plan-writer brief: done; the plan was written, executed and merged.
- [x] **Closed by Part 5 (2026-11-06):** L2 (the stock page recomposed), V6 (the value levels on the chart, the size
  tier and the tranche plan in the API and the value block), V7 backend (`ValueTopItem.claude_note`), S5 Stock (the
  Stock Surfaces paragraph and Decision Log entry in `web/DESIGN.md`), and the Part 4 finish minor "Generate summary"
  36 px (now the secondary `Button`, 44 px; Task 9).
- [x] **Part 6 scope questions (5.4):** answered by the operator 2026-11-06, each as recommended; the Part 6 plan
  is written (`plans/2026-11-06-web-overhaul-6-research-universe-search.md`) and the Part 6 plan-writer brief is done.
- [x] **Part 5 briefs and to-dos:** the Part 5 plan-writer brief and orchestrator brief (old 7.1, 7.2) are done; the
  operator approved running Part 5 (old to-do 1); `./ibkr restart` after Part 5 (old to-do 2) happened 2026-11-06
  19:59:14.

- [x] **Closed by Part 6 (2026-11-07):** L1 (Research), L3 (Universe), S1 (global search in the shell), V7 card
  (`claude_note` on Top opportunities, labelled Claude's), S5 Research and Universe, the Part 4 save-side gap and
  `decodeURIComponent` nit, the Part 4 finish's sub-44 px Research targets, the Part 5 value-block remount (operator
  5.4 #3 of the old HANDOFF) and the Part 5 position-page grid and headline link (Task 11 (b)); the Part 6 orchestrator
  brief; the old to-do "approve running Part 6".
- [x] **Part 6 scope questions** (asked and answered 2026-11-06, each as recommended): global search finds tickers
  plus the console's own pages from a fixed list in the web; keep both watchlists, Research's titled "Your watchlist"
  with a line pointing to Universe; hold the stock page's value block until `GET /value/{symbol}` answers.

### A.5 Part 5 - what shipped (verified in code, `git log` and `ps`, 2026-11-06)

Plan `plans/2026-11-06-web-overhaul-5-stock-page.md`; 14 commits `7981584..b408cf0` (the plan commit on `main`, then
twelve on `feat/web-overhaul-5` and the log row), fast-forwarded to `main` and pushed with the merge-row commit
`d3d1e28`; all seven daemons restarted 2026-11-06 19:59:14, `next dev` 20:01:37. Gate at the review fix pass: vitest
1562 in 152 files, tsc and lint clean, pytest 5767 + 1 skipped, ruff and mypy (361 files) clean, G1 (protected files)
empty, G2 the four command-site files, `design_md_check` exit 0, G5 (da-vinci lint) no finding, scratch build green
(18 routes plus `/_not-found`).

- [x] **A (Tasks 1-2)** `0a9ed58` `size_pct` and `tranches` on each `ValueListOut`, `tranches_done`, `tranches`,
  `tranche_min_sessions`, `last_tranche_on` on `ValuePlanOut`, `claude_note` on `ValueTopItem` (CLI reads only,
  one line, at most 200 characters); `_size_pct` mirrors `src.value.sizing.tier_pct` under a parity test (V6, V7
  backend). `3323cb1` the contract regenerated.
- [x] **B (Tasks 3-6)** `7bcb301` `features/stock/stock.ts` (`valueLeads`, `valueLines`, `nameLine`); `f90f66a`
  `PriceChart` in ink (up hollow, down filled) with the value levels as dashed price lines; `390ef33` the page frame
  (`features/stock/StockPage`, `StockSection`; `SectionShell` deleted; the Stock Surfaces paragraph); `c296632` the
  size tier and tranche sentences in `SizeBlock`.
- [x] **C (Tasks 7-9)** `7e3c5ab` Checks in words and ink; `416fe2d` Technicals, Sentiment, News and the statements
  restyled in place; `d74ad70` "Model summary", labelled by its model, "Generate summary" a secondary button.
- [x] **D (Tasks 10-11)** `19da4d9` docs (STATUS, ARCHITECTURE, `web/CLAUDE.md`, `docs/web/api.md`); `c845334` the
  da-vinci finish by a fresh reviewer: both grid columns `grid-cols-1` (the page scrolled sideways at 320/390 px when
  the statements were open), the statements' phone scroll hint, the News headline link 44 px on a phone with
  "(opens in a new tab)".
- [x] **Review + fix pass** (Opus: 0 Critical, 1 Important, 7 Minor) `e42c122`: the candle series'
  `autoscaleInfoProvider` keeps every value level on the canvas (Important); the second tranche's wait says at least
  ten sessions; a size-tier test where the name cap binds (64 cases); STATUS's range. `b408cf0`, `d3d1e28` the
  Progress log's fix-pass hash and merge row. Four Minors and Task 11's unfixed findings are in 3.4.
- Rulings that changed the plan: none beyond the fixes above (each Progress log row says "none" or records a
  class-level da-vinci note). The plan's G4 expectation "19 routes plus `/_not-found`" is 18 plus `/_not-found`.
### A.6 Part 6 - what shipped (verified in code, `git log` and `ps`, 2026-11-07)

Plan `plans/2026-11-06-web-overhaul-6-research-universe-search.md`; the plan commit `affa316` on `main`, then 19
commits `725f26b..3ebd3a8` on `feat/web-overhaul-6` (15 task commits, three `docs(plan)` hash-fill commits and the
review fix pass; the plan's merge row says "20 commits", counting `affa316`), fast-forwarded to `main` and pushed with the rows commit
`02236ec` (2026-11-07). Web and docs only: no file under `src/`, `scripts/`, `tests/` or `config/` changed, so no
daemon restart is needed (the plan's Restart row is blank; operator to-do 2). Gate at the review fix pass: vitest
1623 in 157 files (Part 5 ended at 1562), tsc and lint clean, G1 (protected files) empty, G2 the four command-site
files, G3 `design_md_check` exit 0 (marker `updated=2026-11-07`), G5 no non-test da-vinci finding (the
`SourceRefs.tsx:21` em dash is Part 7's), G6 the four fence suites 55 passed, G7 `web/app/layout.tsx:55` the one
`<CommandPalette />` mount, scratch build green (18 routes plus `/_not-found`). Re-run on `main` 2026-11-07: vitest
1623 in 157 files, tsc and lint clean, pytest 5767 + 1 skipped, ruff and mypy (361 files) clean.

- [x] **A (Tasks 1-4)** `725f26b` `lib/segment.ts` `decodeSegment` in five `generateMetadata` layouts; `61f503a` the
  save-side tests for a pending decide or roll command (red check by mutation of the protected save calls, restored,
  ruling 16); `496127f` the stock page's value block mounts once (held until the value read answers); `8104abd` the
  position page's `grid-cols-1` column and 44 px phone headline links.
- [x] **B (Tasks 5-7)** `76a3093` `features/search/pages.ts` and `lib/search.ts` (`openSearch`,
  `OPEN_SEARCH_EVENT`); `ad30440` `components/search/CommandPalette.tsx` rewritten in place as a combobox (pages
  first, then tickers); `b613c9b` the palette mounted once in `app/layout.tsx`, a Search row in the rail and on More,
  Research's Search button opens it.
- [x] **C (Tasks 8-11)** `b1f29b3` "Your watchlist" as a card of rows (day change signed, never coloured; a line
  pointing to Universe); `bdbb71d` the sectors as one card of rows; `76db0fa` `features/research/ResearchPage.tsx`
  (Top opportunities first); `3ae07f2` Claude's one-line note on each opportunity, labelled as Claude's.
- [x] **D (Tasks 12-13)** `388944f` `features/universe/UniversePage.tsx`, one card per list saying what it is for
  (the commands, the would-own confirmation and its consequence text unchanged; `sectors` file-only); `299f54d` the
  add field and the override badge restyled.
- [x] **E (Tasks 14-15)** `273fd97` docs (STATUS, ARCHITECTURE, `web/CLAUDE.md`, `docs/web/*`); `f19b96f` the
  da-vinci finish by a fresh reviewer (18 captures, `hscroll` on `main` 0 everywhere): Your watchlist's phone row as
  one link with Remove on its own 44 px row, "Searching tickers." while the first answer is pending, "Tickers could
  not be searched right now." on a failed Follow search.
- [x] **Review + fix pass** (Opus: 0 Critical, 2 Important, 7 Minor, all fixed) `3ebd3a8`: the palette's Tab trap
  counts only focusables with a box (I-1); the Indexes and Watchlist lines no longer overclaim (I-2, "Being here
  selects no trade"; only Would own allows a put); a late older ticker answer no longer clears a newer one; Enter
  during IME composition; a "-" sector mover reads n/a; OverrideBadge hatches an unknown time; the position page body
  decodes its segment. `000143f`, `45d8781`, `0c74eeb` hash fills; `02236ec` the merge and push rows.
- Rulings that changed the plan: none overturned (rulings 1-20 stood). Logged deviations, each with no cost: G5
  (`lint.py`) was run over existing folders only until `features/search` and `features/universe` existed; Task 6's
  commit was amended once to carry its own plan edits; hash fills rode in trailing docs commits. Task 15's unfixed
  P3 findings (a)-(f) are in 3.4.
