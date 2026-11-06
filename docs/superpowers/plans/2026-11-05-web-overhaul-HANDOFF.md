# Web overhaul - ledger and handoff for the next session (updated 2026-11-06)

First written 2026-11-05 after value book Part 6 merged; **updated 2026-11-06 after web overhaul Part 4 merged**.
A fresh session (Sonnet is fine as the orchestrator) can carry on from this file without the conversation that
produced it. Every status line below was checked against the code on `main` (`6347dd9`, equal to `origin/main`;
the only untracked file is `data/value_filing_reads.json`, a runtime file), against `git log` and the Part 4
plan's Progress log, not copied from a plan. Finished items are ticked and moved to **Archive (done)** at the foot
of this file, so the top is only what is still open. Read the top to the Archive heading.

## 0. Headline

- **Web overhaul Parts 1-4 are done, merged and pushed**, and so are the value book's four web sections (F-I).
  Part 4 (cleanup, honesty and the value gaps) landed on `main` by fast-forward on 2026-11-05 (no merge commit;
  its range is `20fcd7e..a7fddc9`), and two unrelated fixes followed it on `main` the same evening (`544e32e`,
  `6347dd9`: the rolling drawdown window, the hero change per range, the spreads card health). All seven daemons
  were restarted at 23:57:24, after the last commit (23:56:58), so the live stack runs Part 4.
- **Pages on the payslip system: 11 of 17 routes** (Home, Trades x2, Portfolio, Activity, Position, More, What
  Claude knows, three ledger sub-routes); every route now has a title and the console has a not-found and an
  error page. **Not recomposed: Stock, Research, Universe, News x2, How it works.**
- **Part 5 (the stock page) is next, and its plan is written**:
  `docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md` (not committed; its A0 step commits it). The
  backend half and the whole web half were prototyped on a scratch copy of `main` (section 6 below has the gate).
- **The order is unchanged**: Part 5 stock page, Part 6 Research/Universe/search, Part 7 News/More/How it works,
  Part 8 value record (gated), order control on its own track. The six operator questions keep their defaults
  (5.3); Part 4 did not change any of them.

## 1. Where things stand

| Part | Plan | State | Landed on `main` | What shipped (verified in code) |
|---|---|---|---|---|
| 1, 1b, market-picture web, 2, 3, 3b, value F-I | see Archive A.1 | **Done, pushed** | `ab7339c` ... `6045d2f` | Archive A.1 |
| **4 - Cleanup, honesty, value gaps** | `plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md` | **Done, pushed, restarted** | fast-forward to `a7fddc9` (2026-11-05, 20:00); pushed with `6347dd9` | Archive A.2 |
| (not a numbered part) drawdown window, hero range change, spreads card health | commits only | **On main, pushed** | `544e32e`, `6347dd9` (2026-11-05) | `src/execution/circuit_breakers.py` rolling 3-session window; `AccountValueSeries.change*`; `features/home/hero.ts` |
| **5 - The stock page (NEXT)** | `plans/2026-11-06-web-overhaul-5-stock-page.md` | **Plan written, not started, not committed** | - | 4 sections, 11 tasks (section 5) |
| 6 - Research, Universe, search | none | Not started | - | |
| 7 - News, More, How it works | none | Not started | - | |
| 8 - The value record (gated) | none | Not started | - | |
| Order control (own track) | none, no spec | Not started | - | History still says "A working order is cancelled in IBKR for now" |

**Verified today (2026-11-06):**

- `main` = `origin/main` = `6347dd9`; worktrees `.claude/worktrees/value-book-6` (ca14c40) and
  `.claude/worktrees/web-overhaul-4` (a7fddc9) still exist; every `feat/*` and `fix/*` branch listed in operator
  to-do 3 is merged into `main` (`git branch --merged main`).
- `python -m pytest -q` from the main checkout: **5675 passed, 1 skipped** (Part 4 ended at 5669 + 1; the two
  later fixes added 6). `ruff check .` clean; `mypy src` **361 files**, clean.
- `cd web && npx vitest run`: **1531 tests in 149 files** (Part 4 ended at 1529; `544e32e` added 2 hero tests).
- da-vinci `design_md_check.py web/DESIGN.md` exits 0 (`status=ratified updated=2026-11-05`); `lint.py` over
  `web/app web/components web/features` finds one non-test hit, the legacy em dash at
  `components/explain/SourceRefs.tsx:21` (Part 7's page).
- Daemons (`ps`): approval_service, monitor, api, research_worker, spreads, news, value all started
  2026-11-05 23:57:24; `next dev` (pid started Oct 30) still serves `web/`.
- The private `config/value.yaml` has `book.enabled: true` (line 263), as Part 4 ruling 1 found; the capital-release
  words (V1) and the value drain heartbeat (V2) it needed are now live.
- **Gap in the record:** Part 4's Progress log ends at the review fix pass; it has no row for the fast-forward to
  `main`, the push or the 23:57 restart. Recorded here instead (cost: none).

## 2. What the overhaul intended, and how much is done

### 2.1 Pages (open rows only; done pages are in Archive A.3)

| Surface | Route | State | What is missing |
|---|---|---|---|
| Stock | `/stock/[symbol]` | **PARTIAL; Part 5** | Legacy frame (`px-8 py-6`, `font-mono` title, `SectionShell`); value levels not on the chart (V6); no size tier or tranche plan (G3) |
| Research | `/research` | **PARTIAL; Part 6** | Top opportunities is on the payslip; the frame (`font-mono text-2xl`, `px-8 py-6`, bordered search button), `WatchlistTable`, `SectorGrid`, `CommandPalette` are not |
| Universe | `/research/universe` | **NOT DONE; Part 6** | `components/universe` (974 lines, legacy) |
| News | `/news`, `/news/[symbol]` | **NOT DONE; Part 7** | `components/news/NewsFeed.tsx` has no page title, old chips and inputs |
| How it works | `/explain` | **NOT DONE and stale; Part 7 (Q1)** | 8-tab shell, 1,491 lines, says nothing of spreads, the value book, regime sizing, capital release, the news thread or the roll redesign |
| Order control | (History) | **NOT DONE; own track** | F1 |
| Recommendations | `/recommendations` | **CUT (Q5 default)** | API route and Telegram card stay |

### 2.2 Cross-cutting intent (open rows only)

| Intent | State | Evidence |
|---|---|---|
| Global search | **NOT DONE; Part 6** | `CommandPalette` is mounted only on `/research` |
| `DESIGN.md` Open Decisions | **OPEN; Part 7 (Q6)** | product name, favicon, icons, sheet exit, the decide controls' look, the disabled quiet button |
| A save-side test for pending commands | **OPEN (found by Part 4)** | no test pins that a pending `DecideControls`/`RollProposal` command is *saved* to localStorage (only restore and clear are pinned) |

## 3. Remaining work, itemised

IDs are stable from the first version of this file; closed ones are in Archive A.4.

### 3.1 Legacy surfaces still to be recomposed (L)

| ID | Item | Size (code today) | Part |
|---|---|---|---|
| L1 | Research landing frame, `WatchlistTable`, `SectorGrid`/`SectorCard`, `CommandPalette` | `app/research/page.tsx` 46, `components/home` 578, `components/search` 267 lines | 6 |
| L2 | Stock page: frame, header, chart, section shells, Checks, Technicals, Statements, Sentiment, News, summary | `app/stock/[symbol]/page.tsx` 115, `components/stock` ~1,030, `components/checks` 518 | **5 (planned)** |
| L3 | Universe page and its three components (edit flows and `ConfirmAction` consequence text stay) | `components/universe` 974 | 6 |
| L4 | News feed and News ticker (`NewsCard` content stays) | `components/news` 449 | 7 |
| L5 | How it works (Q1) | `components/explain` 1,491 | 7 |
| L6 | More: a value mention only (titles landed in Part 4) | `app/more/page.tsx` 81 | 7 |

### 3.2 Gaps on existing surfaces (V)

| ID | Gap | Part |
|---|---|---|
| V6 | Stock page: fair value, entry ceiling, half sale and stop on the chart; tranche plan and size tier in the API and the value block; "what changed since last time" has no field (stays deferred, value book ruling G5) | **5 (planned)** |
| V7 | Top opportunities: the Claude one-line note (`ValueTopItem.claude_note`: backend in Part 5, card in Part 6); stop always null (left until a policy sets one); "Sell a put" shows on a scan's `passed` stage, not a re-gate (H4, left) | 5 backend, 6 card |
| V9 | A value sale with unknown realised P&L is left out of the month sum with no "incomplete" flag | 8 |

### 3.3 Shell and design-system debt (S)

| ID | Item | Part |
|---|---|---|
| S1 | Global search: mount the command palette in the shell (⌘K everywhere, a search entry in the Rail and on More for phones) | 6 |
| S4 | `DESIGN.md` Open Decisions (Q6) | 7 |
| S5 | `DESIGN.md` Surfaces paragraphs for Stock (Part 5 writes it), Universe (6), News and How it works (7) | 5-7 |

### 3.4 Deferred minors still open (M)

- **Part 1:** a holiday or early close reads "Delayed" on the hero (accepted); the sheet's 180ms exit and the
  decide controls' look (S4).
- **Part 2:** the smart default can open on an empty Proposals during an in-flight Approve; `activity_days` loads
  every approval snapshot per `/pnl/day`; `positionHref` keeps `paper` (correct: only a paper spread has a page).
- **Part 3:** `/ledger/executions` covers days+1 calendar days; a name card's open P&L under a type chip sums the
  visible legs only; with `source: none` and open spreads, Positions shows only the spreads card; da-vinci-finish
  tests assert class names; `SpreadFills` shows the raw `mode`.
- **Part 4 (new, from its Progress log, STATUS "Deferred" and the finish/review rows):**
  - no test pins that a pending `DecideControls` or `RollProposal` command is saved to storage (Tasks 5, 6);
  - Home's `PositionsCard` says "No portfolio snapshot has been captured yet." under the Value chip with an empty book;
  - review-accepted costs: a book switched off after selling whose value.db later cannot be read hides the
    "Value book unavailable" flag (ruling 7); the mixed phone banner reads "2 proposals need you" while Open goes
    to Trades (ruling 15); an enabled book with no value.db reads "could not be read"; the value drain reads "Not
    checking" during a night run longer than 300 s;
  - stale comments in the protected `AutonomyControl`, `HaltControl`, `DecideControls` (they name deleted files);
  - History links omit today and All; `PayView` fetches the unfiltered month once before the floor is known;
    `strategyWord` passes labels other than the two wheel strategies through raw;
  - finish (Task 17) observed, not fixed: the strategy switcher wraps "Value" to a second row at 390 px and "All"
    in the range chips at 320 px (a copy or radius decision, operator); the protected receipt reads "accepted,
    waiting for the trading service" above the value note (S4); "See the value file" is READY-only on Top
    opportunities (ratified, operator); sub-44 px targets on Research ("Search a ticker" 36 px, the watchlist input
    30 px: Part 6) and the stock page ("Generate summary" 36 px: **fixed by the Part 5 plan**, Task 9); the "Value
    book" chip-group label sits 4 px under the chips; the disabled next-day arrow draws a filled circle (Open
    Decision);
  - review nits: `DecideControls.test.tsx` titles use an em dash, `boundaries.test.tsx`'s `once` assertion, the
    unguarded `decodeURIComponent` in the `generateMetadata` layouts (a malformed `%` in a URL would throw in the
    title, not the page).

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
| L2, V6, V7 backend, S5 Stock | **BUILD (Part 5, planned)** | As the plan: keep the candles (`PriceChart`) but in ink, add the value levels as dashed price lines, every section a card, the value block first for a priced or held name, state words instead of green/red on non-money |
| L1, L3, S1, V7 card | **BUILD ON (Part 6)** | Research on the payslip with Top opportunities leading and `claude_note` shown (labelled Claude's, never on a button); Watchlist rows; Sectors as cards like the Market card; Universe restyle only (`sectors` stays file-only); the palette in the shell |
| L4, L5, L6, S4 | **BUILD ON / REBUILD SMALL (Part 7)** | As before (Q1 default: one small "How it works" page with `SourceRefs`; cut the 8-tab shell) |
| Part 4 save-side gap | **ADD (one task, any part)** | One `DecideControls` and one `RollProposal` case that asserts a pending command and an open live step are written to localStorage; cheap, closes a real blind spot |
| Part 4 review nit (decodeURIComponent) | **ADD (Part 6, one line each)** | Guard the four `generateMetadata` layouts with a try/catch that falls back to the raw segment |
| V9, F5 | **DEFER (Part 8)** | Unchanged |
| F1 | **BUILD, own track** | Unchanged |
| F2 | **DEFER** | Unchanged |

## 5. Proposed parts from here

Every part is one plan of the Part 4/5 shape (Execution model with Model and Effort columns, Progress log,
Roadmap, Rulings, Global Constraints, Review Focus, File structure, sections with entry checks, tasks with gates,
whole-branch review). "Part N" means **web overhaul Part N**.

| Part | Scope | Items | Depends on | Size |
|---|---|---|---|---|
| **5 - The stock page (NEXT, plan written)** | A backend (`size_pct`, `tranches`, the plan's tranche fields, `claude_note`) and the contract; B the page frame, chart with the value levels, size and tranche words; C the sections restyled in place; D docs, a fresh da-vinci reviewer, Opus review, Sonnet fix pass | L2, V6, V7 (backend), S5 (Stock) | Part 4 (done) | 4 sections, 11 tasks |
| **6 - Research, Universe and search** | Research page on the payslip with Top opportunities leading and its `claude_note`; Watchlist rows; Sectors cards; Universe restyle; the palette in the shell; the `generateMetadata` guard; the save-side tests | L1, L3, S1, V7 (card), two Part 4 minors | Part 5 | 2-3 sections + finish, ~8 tasks |
| **7 - News, More and How it works** | News feed and ticker on the payslip; How it works rebuilt small (Q1) or cut; More's value mention; DESIGN.md Open Decisions closed (Q6) | L4, L5, L6, S4, S5 | Part 6, Q1, Q6 | 2 sections + finish, ~8 tasks |
| **8 - The value record (gated)** | `GET /value/record` over `value_db.py`, an Activity view: baseline vs Claude, horizon returns, clamp frequency, breaker state, drawdown vs SPY; the `MonthPay` realised-complete flag | F5, V9 | a month of paper record with the book on (Q4) | 2 sections + finish, ~6 tasks |
| **Order control (own track)** | Spec, then plan: `cancel_order` kind, drain handler, Cancel behind `ConfirmAction` + LIVE second confirmation, receipt, History copy | F1 | spec | spec, then ~7 tasks |

### 5.1 Rulings (standing; the operator may overturn any)

1. **Numbering**: the old Part 4 became Parts 4-7; order control has no number.
2. **No fold of `components/` into `features/`.** New code goes in `features/`; `components/` keeps `ui`, `shell`,
   the protected `options` controls, `value` and the survivors (now written into `web/CLAUDE.md` and
   `ARCHITECTURE.md`). Living legacy components are restyled **in place** (Part 5 does this for `components/stock`
   and `components/checks`).
3. **`components/value/` stays**; the command-site grep stays: `grep -rln "submitCommand\|confirmCommand"
   web/features` prints `features/more/TargetCard.tsx`, `features/stock-value/AnalyseButton.tsx` and their tests.
4. **The value book gets no top-level nav destination, no Trades tab and no new page** until Part 8 (Q3 default).
5. **The calendar keeps its second request** for the value split.
6. **No new token, colour, font, radius or elevation** in any part; a da-vinci proposal for one waits for the
   operator.
7. **Green and red are for signed money only** (DESIGN.md Colors). Part 5 applies it to candles, the check
   ribbon, headline tone and the sentiment change; later parts apply it the same way to any legacy surface they
   recompose.

### 5.2 What each part must not do

- Parts 5-7: add a command site, change a protected file, a Rules Engine path, a gate, sizing or the value book's
  logic. Part 5's API change is read-side (`src/api/` only). Part 8: add a write.

### 5.3 Questions for the operator (defaults shown; plan writers assume them; Part 4 changed none)

1. **How it works (`/explain`)**: rebuild small, rebuild in full, or cut? *Default: rebuild small (Part 7).*
2. **Order control**: build it before the Research/Stock parts, after Part 7, or leave it? *Default: spec in parallel; build after Part 6.*
3. **A "Value" destination** (own nav item and page) or the current spread across Home, Stock, Research and a record view in Activity? *Default: no new destination.*
4. **When should the value record view (Part 8) be built**: now, or after the paper sleeve has run a month with `value.book.enabled`? *Default: after.* (The book has been enabled in paper since at least 2026-11-05.)
5. **Confirm cutting the `/recommendations` page.** *Default: cut.*
6. **Close the `DESIGN.md` Open Decisions.** *Defaults: keep "IBKR Income" with a text wordmark and a simple favicon; keep lucide icons; keep the immediate sheet close; leave the legacy bordered decide controls inside sheets as the recorded exception; a disabled quiet button stays transparent and only dims.*

## 6. Binding rules for any plan writer

- **Core invariant.** The Rules Engine is the only path to an order; nothing the web or Claude produces gates,
  sizes or prices anything. The two written exceptions in `CLAUDE.md` (the CSP contract cut; the value verdict)
  are untouched and the web only displays them, with Claude's words labelled as Claude's and never on a button.
  Text written by a model that may not be Claude (the research summary backend can be Ollama or OpenAI) is
  labelled by its model, not as Claude's.
- **Web fence.** The API reads the trading database read-only and writes exactly one table, `app_commands`,
  through `src/api/commands.py`. Every web action is an intent drained by `approval_service` (or, for the six
  `value_*` kinds, by the value process). `tests/test_web_fence.py`, `test_eval_skills.py`, `test_regime_fence.py`,
  `test_news_fence.py`, `test_spreads_fence.py`, `test_value_fence.py` and `test_wheel_spreads_isolation.py` stay
  green and are never weakened.
- **Value fence.** The API imports from `src.value` only `scorecard` and `schemas`; only `src/api/value_db.py`
  opens value.db (`mode=ro`, plain SQL). A rule the API needs from `src.value` (Part 5: the size tier) is mirrored
  in `src/api/` with a test that holds it equal to the original. `src/reporting/` imports nothing from `src.claude`
  or `src.value`.
- **Protected files:** `web/components/options/{DecideControls,ConfirmAction,CommandReceipt,HaltControl,AutonomyControl,RollModeControl}.tsx`,
  `web/lib/commands.ts`, `web/lib/receipt.ts`: `git diff --stat main -- <paths>` prints nothing at every section exit.
- **da-vinci.** Every UI task invokes the `da-vinci` skill first (and says so in every subagent prompt, with the
  concrete spec so it has little to decide); the finish runs `critique` + `audit` + `polish` at 320/390/1440 px,
  light and dark, by a **fresh reviewer agent** against a synthetic API in the scratchpad (never the live API).
  `web/DESIGN.md` is the visual authority (tokens only, lime only on the primary act, unknown is a hatched `n/a`,
  no state by colour alone, no shadow except the sheet and confirm dialog, charts never animate in, 44 px phone
  targets, zero em dashes and none of "seamless/robust/unlock/elevate" in UI copy). New surfaces get a Surfaces
  paragraph and a Decision Log entry; `design_md_check.py web/DESIGN.md` exits 0 and the marker date is bumped.
- **Never build inside `web/`.** The operator's `next dev` shares `web/.next`. Builds run in a scratch copy in the
  session scratchpad (the `mktemp` + `rm -rf "$(dirname ...)"` form is refused by the sandbox; remove the
  `node_modules` symlink first, then the copy, by literal path). The Google-font fetch in `next build` fails
  transiently ("Cannot read properties of null (reading '1')" in `next/font/google`): retry up to three times
  before calling the build red.
- **Gates.** After every web task `cd web && npx vitest run && npx tsc --noEmit && npm run lint`; after Python
  `python -m pytest -q && ruff check . && mypy src` from the worktree root. After any API contract change regenerate
  offline: `IBKR_CONFIG_USE_EXAMPLES=1 python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json`
  then `cd web && npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts`; `tests/test_openapi_current.py`
  stays green. A field the API always sends but declares with a default becomes a **required** key in
  `api-types.ts`, so typed web fixtures need it (Part 4 Task 2, Part 5 Task 2). **Baselines (2026-11-06):** pytest
  5675 + 1 skipped, vitest 1531 in 149 files, mypy 361 files (recompute from `git log`; counts go stale).
  `tests/test_scan_timeout.py` is a known flake: re-run it alone.
- **Execution model (token-light, operator-mandated, effort updated 2026-11-06).** Work in a worktree
  `.claude/worktrees/web-overhaul-N` on `feat/web-overhaul-N` (symlink `.venv` and `web/node_modules`, run
  `init_db()` with `IBKR_CONFIG_USE_EXAMPLES=1`). The main session is a **Sonnet orchestrator**; it runs each
  section's entry checks itself, spawns **one Sonnet subagent per section** with the effort the plan's Execution
  model table gives (**medium for mechanical edits, high or xhigh for tricky UI or shared state; low only where it
  genuinely does the job**: operator, 2026-11-06), verifies the report itself (`git log main..HEAD`, `git status`,
  gate counts, the protected-file diff, the command-site grep) and **stops and asks before the next section**.
  After the last code section: one Opus whole-branch review (high), then one Sonnet fix pass (high); ask before
  merge or push.
- **Plan specificity (operator, 2026-11-06).** Plans are executed by Sonnet: give the code in full (Part 5 ships
  every change as a `git apply` patch embedded in the plan, extracted by a helper that also repairs blank context
  lines, so the apply check itself is the entry check that re-verifies every edited line), exact commands with
  expected output, exact paths and a gate per task. Small visual details may be left to da-vinci where it is
  better placed to decide, with the concrete layout, tokens and copy given.
- **Progress log.** The plan carries one; after every task tick its boxes and fill its row (status, commit, gate,
  date, every ruling with its cost-if-wrong) in the same commit; **add a row for the merge, the push and the
  restart** (Part 4 forgot). A new session resumes from the log and `git log`, never from memory.
- **Doc-update table (`CLAUDE.md`).** New file/module: `ARCHITECTURE.md` folder guide; new config key: the
  committed example + `ARCHITECTURE.md` + `SETUP.md`; feature built/deferred: `STATUS.md`; UI surface:
  `web/DESIGN.md`, `web/CLAUDE.md`, `docs/web/api.md` for any route or field, `docs/web/commands.md` for any kind.
- **Gotchas.** Never import `scripts.run_*` (py_compile instead); never copy `research.db`; worktree sessions cannot
  edit private `config/*.yaml`; daemons do not hot-reload (`./ibkr restart`, trading service before the API); never
  add an `AGENTS.md`; `df -h .` as an entry check (22 GiB free at 95% on 2026-11-06); pin `now` in tests that compare
  fixture times; in a test file import `@/lib/test-query` before `@/lib/api` and `@/lib/commands`; the repo is not
  prettier-formatted (hand-indent, never `prettier --write` a whole file); BSD `sed` treats `\t` as `t`.

## 7. Briefs and to-dos

### 7.1 Brief for the Part 5 orchestrator (do this next)

Open a fresh session (Sonnet, high) in the main checkout and give it:

```
Execute docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md with superpowers:executing-plans, as its
"Execution model" says: you are the orchestrator; run each section's entry checks yourself, spawn one Sonnet
subagent per section at the effort the table gives (pass effort on every spawn), verify its report yourself, and
stop and ask me before the next section. Every UI subagent invokes the da-vinci skill first. Never build or run
next dev inside web/. Keep the plan's Progress log current in the same commit as each task, including a row for
the merge, push and restart. Ask before merging or pushing.
```

### 7.2 Brief for the Part 6 plan writer (after Part 5 merges)

Spawn one `general-purpose` agent (`model: opus`, background) with: "You are the plan writer for web overhaul
Part 6 (Research, Universe and search). Read CLAUDE.md, web/CLAUDE.md, web/DESIGN.md, this HANDOFF in full
(sections 3-6 bind you), the Part 5 plan and its Progress log (reproduce its format: patches embedded and
extracted by the helper, entry checks that `git apply --check` every patch, a gate per task, effort per section),
STATUS.md's Part 5 and Part 4 Built sections, docs/web/api.md. Scope: L1, L3, S1, V7 card (`claude_note`, labelled
Claude's), the `generateMetadata` guard and the save-side tests (section 4). Prototype the whole part on a
code-only scratch copy of main (git archive; symlink .venv and web/node_modules), run pytest, vitest, tsc, lint,
ruff, mypy and a scratch build, generate the patches from a per-task git history, delete the copy. Hand back
numbered questions only for genuine operator calls. Output docs/superpowers/plans/<date>-web-overhaul-6-research-
universe-search.md, not committed; then update this HANDOFF the same way it was updated for Part 5."

### 7.3 Operator to-dos

1. **Approve running Part 5** (7.1). Its plan asks nothing of you up front; read its rulings 6-9 (ink candles,
   "Model summary", the back link, the value block's place) and overturn any you dislike before Section B.
2. After Part 5 merges: `./ibkr restart` (the API serves the new value fields; `next dev` picks up the web).
3. Answer Q1-Q6 (5.3) before Part 7; none blocks Parts 5 or 6.
4. Housekeeping: `git worktree remove .claude/worktrees/value-book-6` and `.claude/worktrees/web-overhaul-4`, then
   `git branch -d` the merged branches (`feat/value-book-1` to `-6`, `feat/web-home-followups`, `feat/web-overhaul-2`,
   `-3`, `-4`, `feat/contract-cache`, `feat/news-thread`, `feat/spreads-claude-picker`, `fix/breaker-ack-auto-roll`,
   `fix/qualify-partial-chunks`, `fix/spreads-gex-map-spot-wait`, `perf/claude-token-slim`).
5. Disk: `df -h .` shows 22 GiB free at 95%; check before each long run.
6. Look once at Home on a phone in dark mode with a value proposal waiting (Part 4 ruling 15's row and banner);
   overturn it if you would rather decide from "Needs you" directly. Decide whether the strategy switcher may
   shorten "Credit spreads" so "Value" stops wrapping at 390 px (Part 4 finish, item a).
7. Value book live checks still owed from Part 6 (paper): a Telegram tap on a value card reaches the value process
   and the next RTH cycle sends; the trim card's button; the first digest night; the watchdog's value line; a stale
   card answers "out of date" (`SETUP.md` section 19, step 14).
8. Leave `next dev` running; no plan builds inside `web/`.

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
command-site files, `design_md_check` exit 0, scratch build green (19 routes plus `/_not-found`).

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
- Rulings that changed the HANDOFF's plan: the value book was already on (Section A first); V1 needed no agreement
  work elsewhere and does not name the funding request; the heartbeat lives in the trading DB, not value.db; V4 is
  smaller (the ledger's trades are options only); D1 was sixteen files; the error page has one action.

### A.3 Pages done (from 2.1)

[x] Home `/` · [x] Trades `/trades`, `/trades/[approvalId]` (cancel is F1) · [x] Portfolio `/portfolio` (value
holdings since Part 4) · [x] Activity `/activity` (Value chip on At IBKR since Part 4) · [x] Position · [x] More
(titles since Part 4) · [x] What Claude knows · [x] Ledger sub-routes · [x] titles on every route, not-found and
error pages (Part 4) · [x] Native mobile app: cut earlier (`STATUS.md` "P5 - Mobile").

### A.4 Items closed (from sections 2.2, 3 and 4 of the first version)

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
- [x] The Part 4 plan-writer brief (old 7.1): done; the plan was written, executed and merged.
