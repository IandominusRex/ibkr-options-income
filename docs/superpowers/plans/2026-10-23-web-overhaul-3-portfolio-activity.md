# Web Overhaul, Part 3: Portfolio and Activity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (native execution, or one subagent per section on the labelled model with a stop between sections, the operator's token-light method). The plan is split into four sections; every section opens with **entry checks** that must all pass before its first task starts. Each section carries a **model label** so an orchestrator that delegates a section knows which model to spawn. **Every task that touches UI starts by invoking the `da-vinci` skill** (operator, 2026-10-19), and so does any subagent given one of those tasks (say so in its prompt). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recompose `/portfolio` and `/activity` on the payslip design system for how the account
actually runs, and put the market-picture build where the operator audits the money.

- **Portfolio** reads what you hold, name by name: the account in figure lines, then three views
  kept in the URL (Positions grouped by ticker with Home's row anatomy and the news service's
  "Weak health" and "Event" words; Campaigns, the wheel threads, with their money labelled
  before commissions; the expiry Calendar with an event word where a verified date falls before
  an expiry).
- **Activity** reads what the money did, in four views kept in the URL: **Pay** (one month at a
  time as a stub, then the record since the system began, the equity curve and the legs with
  their CSV), **Ledger** (the broker-truth ledger's overview, its drill-down pages restyled),
  **Fills and orders** (the system's orders, the system's fills including the credit-spread
  book, and IBKR's own executions, side by side and never merged) and **System** (the
  score-vs-outcome evidence, restyled, and the **sizing record**: what the regime limits, the
  scale-in ladder and Claude's size cut held back, and what that would have earned — the review
  the live-cutover gate asks for).

**Architecture:** Three backend tasks, all read-only. Task 1 adds `GET /pnl/sizing`, a thin route
over `src/claude/eval/sizing_counterfactual.py::summarize`, read behind the eval fence exactly as
`GET /pnl/system` reads the score report. Task 2 makes orders carry the sizing action that shaped
them and makes fills name their contract. Task 3 adds `GET /ledger/executions` (the ledger's
real executions, newest first) and `GET /spreads/orders` (the spreads book's filled orders,
through `src/api/spreads_db.py`). Nothing is written, nothing in the trading path changes, and
no schema changes. The web side adds `web/features/portfolio/` and `web/features/activity/` and
one shared hook (`lib/useViewParam.ts`); the payslip primitives from Part 1 and Home's rows,
`FigureLines`, `useClaudeContext` and `NameFlags` from Part 1 and the market-picture build are
reused as they stand. Components that keep their job (the P&L tables and charts, the ledger
tables, `OrdersTable`, `FillsTable`, `RefreshControl`) are restyled **in place under their
existing tests**; components whose composition changes are new, and the legacy panels they
replace stay unmounted until Part 4 deletes them. `RefreshControl` is still the only write on
these pages (the `refresh` command, unchanged); the ledger drill-down pages keep the intents they
already send.

**Tech Stack:** Next.js 15 App Router, React 19, Tailwind CSS v4, @tanstack/react-query,
lucide-react, Recharts (the existing curves), Vitest + Testing Library; FastAPI, SQLAlchemy (the
ORM over the trading DB; plain SQL over a `mode=ro` SQLite engine for the spreads file),
Pydantic, pytest.

**Spec:** `web/DESIGN.md` (ratified 2026-10-14; § Surfaces → Portfolio and Activity, § Components;
the authority for every visual value), the roadmap in
`docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md` § "Roadmap (this plan is Part 2 of
5)", Part 3, as revised by the operator on 2026-10-19, and, for the market-picture additions,
`docs/superpowers/specs/2026-10-20-market-picture-design.md` §10 (the counterfactual record) and
§11 with `docs/superpowers/plans/2026-10-20-market-picture.md` (built and merged 2026-10-22; its
web follow-up of 2026-10-23 is the base this plan starts from). The Portfolio and Activity
surface contracts are written into `web/DESIGN.md` in Task 4 before any Part 3 UI code.

## Execution model

| Section | Tasks | Model | Why this model |
|---|---|---|---|
| **A — The API** | 1–3 | **sonnet** (effort xhigh) | Three read-only routes. Task 1 reads behind the eval fence, Task 2 changes two response shapes that two web surfaces already read, and Task 3 opens the ledger tables and the spreads file, so the fence tests run in every task. Every line of code and every test is given and was run against `main` at c692a1b (2026-10-28 re-verification), so the section is transcription plus the gates, not design. |
| **B — Portfolio** | 4–7 | **sonnet** (effort xhigh) | New components in `web/features/portfolio/` against interfaces that Parts 1 and 2 and Section A pinned; the two small restyles carry full replacement code under their existing tests. |
| **C — Activity** | 8–14 | **sonnet** (effort xhigh) | New views plus restyles in place. Every restyle is given as exact replacements and has an existing test suite that must pass unmodified: that is the proof the restyle changed no behaviour. |
| **D — Docs and finish** | 15 | **sonnet** (effort xhigh), then an **opus** whole-branch review | The doc sweep and the da-vinci finish are checklists; the whole-branch review at the end (superpowers:requesting-code-review) is a review, not implementation, and runs on the most capable model (the operator's token-light method). |

**How a section runs (native):**

1. Run that section's **entry checks** (below each section heading), in order.
2. **Any check fails → stop.** Report what failed with its output, and do not start the section's
   first task. A failure that belongs to the previous section is fixed there (reopen its last
   task, record the ruling) before re-running the checks.
3. **All checks pass →** record a row for them in the Progress log ("Section X entry", gate
   result, date) and start the first task. No operator confirmation is needed between green
   sections.
4. An orchestrator delegating instead of running natively spawns one subagent per section on
   the labelled model and effort (sonnet, xhigh), hands it this plan plus `web/DESIGN.md`, tells it
   to invoke `da-vinci` before any UI code, and runs the next section's entry checks itself before
   spawning the next.

**How to apply a step (for the implementer).** Every code block is the exact text to write. A
"create" or "replace `<file>` with" step is the whole file. An "append inside `describe(...)`" step
goes before that `describe`'s closing `});` (the last line of the file in every case here). An
"add after `<name>`" step goes after the end of that function or class. A "replace the lines" step
names old text that occurs exactly once in the file today: if it does not, stop and report rather
than guess. Copy blocks byte for byte. Do not reformat them by hand; the formatter steps do that.

**Commit counts.** Each task is one commit (Task 1's also carries the plan's Progress log). A review
fix pass adds one commit; record it in the Progress log and add one to every later entry check's
count.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **Plan written** | done | (plan file only) | n/a | 2026-10-23 | Operator asked for Part 3 in the style of Parts 1 and 2 with the market-picture additions where relevant, and to make the calls itself rather than ask. Every call is a ruling below, with the evidence it rests on; the operator may overturn any of them. Tasks numbered 1–15. |
| **Plan re-verified** | done | (plan file only) | Tasks 1–14 replayed from this text onto a scratch worktree of `main` at c692a1b: pytest 4963 → 4993 (+30), vitest 1242 passed (135 files), tsc, eslint, ruff, mypy, fences, `test_openapi_current` and the da-vinci lint (non-test files) clean; `next build` green | 2026-10-28 | Operator asked for the plan to be checked against the system as it now stands and made executable by a Sonnet subagent at xhigh. (1) The plan file and the market-picture web work were committed together in 353cdd8, so A1 now expects a clean tree. (2) **f4af002 (2026-10-27) made `partial` final** (the executors cancel the rest at the fill timeout): `/options/orders?state=working` is queued and submitted only. Task 2's replacement `list_orders` re-added `partial` and would have undone that fix silently (no existing test seeds a partial order). Fixed in the task's code, and a ninth test, `test_a_partial_order_is_history_not_working`, pins it (it fails against the old text). Counts updated (+9, total +30). (3) Every section is now labelled sonnet at xhigh; the whole-branch review stays on opus. (4) A "how to apply a step" paragraph was added, the flaky `tests/test_scan_timeout.py` is named in A2 so a lone intermittent failure there does not stop the run, and Task 15's root `CLAUDE.md` and restart instructions now name exact anchors (`./ibkr restart` restarts the whole supervised stack; there is no API-only restart). (5) f4af002's USD-only account value needs no plan change: Pay's month stub already says "needs the month's opening account value" when the API's `month_start_value` is null (every month before November 2026 with a percent target), and the equity curve already leaves gaps for a null net liquidation. |
| **Section A entry** | done | (none) | A1-A5 pass (run by the orchestrator); baseline pytest 4962 passed + 1 skipped (4963 collected), ruff clean, mypy clean (297 files); vitest 1027 passed (108 files), tsc clean, eslint clean | 2026-10-28 | Work is in the worktree `.claude/worktrees/web-overhaul-3` (branch `feat/web-overhaul-3`, based on main c692a1b); the plan file there carries the operator's uncommitted 2026-10-28 re-verification edits and Task 1's commit includes them. A1 says "`git branch --show-current` prints `main`": here the branch is `feat/web-overhaul-3` by design (a worktree), so Task 1 Step 1's `git switch -c` was not needed. |
| **Task 1: `GET /pnl/sizing`** | done | 463d742 `feat(api): GET /pnl/sizing - the sizing record's totals, read behind the eval fence` (hash filled in by Task 2's commit; a commit cannot name itself) | pytest 4972 passed + 1 skipped (baseline 4962 + 10 new); the 10 new tests, `test_web_fence.py`, `test_eval_skills.py`, `test_regime_fence.py` pass (48 passed); `test_openapi_current` passes; ruff clean, mypy clean (297 files); vitest 1027 passed (108 files), tsc clean, eslint clean | 2026-10-28 | (1) Step 1 (branch) not run: already on `feat/web-overhaul-3` in a worktree (see the entry row). (2) Step 7's regeneration used `IBKR_CONFIG_USE_EXAMPLES=1` in front of the `python -c` (the private config is not read). (3) `web/lib/api-types.ts` regeneration changed one line the task did not write: the `GET /options/orders` `state` description reads "(queued/submitted)" instead of "(queued/submitted/partial)". `docs/web/openapi.json` already carried the new text from f4af002 (2026-10-27); only the generated TypeScript comment had been left stale. Harmless, and the regenerated file is the one `test_openapi_current` pins. (4) The task's Step 8 lists only `npx tsc --noEmit` on the web side; vitest and eslint were run as well (the orchestrator's per-task gate) and are unchanged from the baseline. |
| **Task 2: orders carry their sizing; fills name their contract** | done | 606aa70 `feat(api): orders carry the sizing that shaped them; fills name their contract` (hash filled in by Task 3's commit) | pytest 4981 passed + 1 skipped (Task 1's 4972 + 9 new); vitest 1027 passed (108 files, unchanged); tsc, eslint, ruff, mypy (297 files) clean; `test_openapi_current` passes after regeneration | 2026-10-28 | (1) Step 2 as predicted: 8 of the 9 new tests failed before the change and `test_a_partial_order_is_history_not_working` passed on the old route and still passes on the new one (`_WORKING` is still `{"queued", "submitted"}`, comment unchanged). (2) Step 6's first command includes `test_openapi_current`, which fails until the contract is regenerated (it ran before the regeneration, as the step is ordered): 67 passed and that one failed, then it passed after the regeneration. (3) In `types.ts` the plan gives the five new `FillSummary` fields as one inline-code list in prose; they are written one field per line, like the rest of the file. (4) The pasted test block had one blank line before `test_a_partial_order_is_history_not_working`; `ruff format` made it two, the only change the formatter made to the task's text besides line wrapping. (5) The `api-types.ts` and `openapi.json` diffs drop only the old docstring lines, the old `maximum: 90` on `days` and the old FillSummary docstring, all replaced by this task's text. |
| **Task 3: `GET /ledger/executions` and `GET /spreads/orders`** | done | ae79b47 `feat(api): GET /ledger/executions and GET /spreads/orders - the audit lists` (hash filled in by Task 4's commit; a commit cannot name itself; `git log --oneline c692a1b..HEAD` showed three Section A commits) | pytest 4992 passed + 1 skipped (Task 2's 4981 + 11 new: 5 ledger, 6 spreads); `test_web_fence`, `test_spreads_fence`, `test_wheel_spreads_isolation` pass with the new tests (64 passed); the five fence files (`test_web_fence`, `test_eval_skills`, `test_regime_fence`, `test_news_fence`, `test_spreads_fence`) pass (60 passed); `test_openapi_current` passes; vitest 1027 passed (108 files, unchanged); tsc, eslint, ruff, mypy (297 files) clean; the B3 loop over `web/lib/api-types.ts` prints nothing | 2026-10-28 | (1) Step 3 as predicted: all 11 new tests failed on 404 bodies before the change (the two `require_owner` cases answered 404 where 401 is expected). (2) The pasted ledger tests were appended after `test_nav_has_a_ledger_section` with the `datetime` import placed above `pathlib` (isort order); ruff's check needed no `--fix`. (3) Route and model imports were added exactly as the task says (`LedgerExecutionRowOut` and `LedgerExecutionsResponse` sit after `LedgerExecutionOut`, and `ruff check` accepts the order). (4) The contract regeneration removes no existing line from `openapi.json` or `api-types.ts`: it only adds the two ledger schemas, the two spreads schemas and the two paths. (5) No documentation file was touched in Section A on purpose: the plan puts the ARCHITECTURE.md / STATUS.md / SETUP.md / CLAUDE.md / `docs/web/api.md` sweep in Task 15, so the CLAUDE.md doc-update reminder fired after each `src/api` edit and is satisfied there. |
| **Section B entry** | done | (none) | B1-B5 pass (run by the orchestrator); re-run by the orchestrator after Section A: pytest 4992 passed + 1 skipped, ruff clean, mypy clean (297 files); vitest 1027 passed (108 files), tsc clean, eslint clean | 2026-10-28 | (no rulings) |
| **Task 4: contracts, the Account card, `useViewParam`, two restyles** | done | 44541a8 `feat(web): Portfolio and Activity contracts, the Account card, useViewParam` (hash filled in by Task 5's commit; a commit cannot name itself) | vitest 1040 passed (110 files: baseline 1027 + 4 `useViewParam` + 9 `SummaryCard`); tsc clean; eslint clean; the targeted run (`lib features/portfolio components/portfolio`) passed 20 files / 158 tests, with the 6 existing `RefreshControl` tests and the other legacy portfolio tests unmodified; `design_md_check.py web/DESIGN.md` exit 0; da-vinci `lint.py` exit 0 on `web/features/portfolio`, `web/lib/useViewParam.ts`, `DegradedNotice.tsx`, `RefreshControl.tsx` | 2026-10-28 | (1) Step 1: da-vinci loaded (sync check `OK 16`, `web/DESIGN.md` status `ratified`); no new colour, font, radius, elevation or token was needed, so nothing is proposed. (2) The code blocks (both test files, `useViewParam.ts`, `SummaryCard.tsx`) were extracted from this plan with `sed` by line range and not retyped; the DESIGN.md block was diffed against the plan's text (identical). (3) Step 5: the two implementation files were moved aside for the run, so both test files failed with "Failed to resolve import" as expected, then put back. (4) Steps 8 and 9 applied as `Edit`s of exactly the quoted old text (the `DegradedNotice` return and the "an elevated surface and plain text" wording, which wraps over two comment lines; the `RefreshControl` import and `return (...)`). (5) The existing `RefreshControl` test prints two React "not wrapped in act(...)" stderr warnings; it printed the same two on the file before the restyle (checked), so they are not new. (6) Section B entry B1-B5 were not re-run by the implementer: the orchestrator ran them and the row above records that. |
| **Task 5: Positions, name cards over Home's rows** | done | 144e11d `feat(web): Portfolio Positions - name cards over Home's rows, totals that never hide an n/a` (hash filled in by Task 6's commit; a commit cannot name itself) | vitest 1073 passed (113 files: Task 4's 1040 + 5 `PositionRowItem` + 14 `positions` + 14 `PositionsView`); the 20 existing `PositionsCard` tests passed unmodified after the row extraction; tsc clean; eslint clean; da-vinci `lint.py` exit 0 on `web/features/portfolio`, `PositionRowItem.tsx`, `PositionsCard.tsx` | 2026-10-28 | (1) Code blocks extracted from the plan by line range, not retyped (test files, `PositionRowItem.tsx`, `positions.ts`, `PositionsView.tsx`). (2) Step 3: all three new test files failed with "Failed to resolve import" before the implementations existed. (3) Step 4's `visible.map` replacement was done by line range after asserting the first and last lines of the old block (`{visible.map((r) => {` ... `})}`, the only child of the `<ul>`); the old row markup is in `PositionRowItem` unchanged apart from the two additions the plan gives (`flags` and `detail`). The new import `PositionRowItem` sits above the `./positions` import; the plan does not say where. (4) The import list in `PositionsCard.tsx` matched the plan's instructions exactly: `tsc` and `next lint` named no missed import. |
| **Task 6: Campaigns and Calendar** | done | 8de60eb `feat(web): Portfolio Campaigns and Calendar - threads before commissions, event words on expiries` (hash filled in by Task 7's commit; a commit cannot name itself) | vitest 1104 passed (117 files: Task 5's 1073 + 4 `campaigns` + 8 `CampaignsView` + 4 `calendar` + 12 `CalendarView` + 3 `eventBefore`); every existing `market` test passed unmodified (20 in the file: 17 existing + 3 appended); tsc clean; eslint clean; da-vinci `lint.py` exit 0 on `web/features/portfolio`, `web/components/ui/field.ts`, `web/features/market/market.ts` | 2026-10-28 | (1) Code blocks extracted from the plan by line range, not retyped. (2) Step 3: the four new test files failed with "Failed to resolve import" and the three appended `eventBefore` tests failed with "eventBefore is not a function" before the implementations existed. (3) `market.test.tsx`: the `eventBefore` describe was appended after one blank line, and `eventBefore` was added to the `./market` import in alphabetical position (`actionTitle, eventBefore, limitSentence, ...`); the plan does not say where in the import. (4) `eventBefore` was appended to `market.ts` after `nameFlags` (the last function in the file) with one blank line between. |
| **Task 7: the Portfolio page at `/portfolio`** | done | 34deff2 `feat(web): the Portfolio page - Account card, Positions, Campaigns, Calendar in the URL` (hash filled in by Task 8's commit, the first of Section C; `git log --oneline main..HEAD` showed seven commits at the end of Section B) | vitest 1108 passed (118 files: Task 6's 1104 + 4 `PortfolioPage`); tsc clean; eslint clean; da-vinci `lint.py` exit 0 on `web/features/portfolio` and `web/app/portfolio`. Section B exit: pytest 4992 passed + 1 skipped (unchanged from Section A, the section adds no Python; no `tests/test_scan_timeout.py` flake this run), ruff clean, mypy clean (297 files); `git diff --stat main --` over the six protected components and `lib/commands.ts`, `lib/receipt.ts` prints nothing; `grep -rn "submitCommand\|confirmCommand" web/features` prints only `features/more/TargetCard.tsx` and `features/more/TargetCard.test.tsx`; the nine legacy `components/portfolio/*.test.tsx` files, `PortfolioShell.tsx`, `SummaryPanel.tsx` and `PositionsPanel.tsx` are byte-identical to `main` and the full vitest run is green; `PortfolioShell` is no longer imported anywhere (three comments still name it) | 2026-10-28 | (1) The test file, `views.ts`, `PortfolioPage.tsx` and `app/portfolio/page.tsx` were extracted from the plan by line range, not retyped. (2) Step 3: the test failed with "Failed to resolve import ./PortfolioPage" before the implementation existed. (3) Step 5's `npx vitest run` is the whole suite, so the legacy portfolio tests ran unmodified in the same pass. (4) No browser pass was done in this section (not asked for; the page-level visual check is Section D's da-vinci finish), so the page has been exercised by its tests and type-checked but not looked at in a rendered viewport. |
| **Section C entry** | done | (none) | C1-C5 pass (run by the orchestrator); re-run by the orchestrator after Section B: pytest 4992 passed + 1 skipped, ruff clean, mypy clean (297 files); vitest 1108 passed (118 files), tsc clean, eslint clean; scratch-copy `next build` green (`/portfolio` built) | 2026-10-28 | (no rulings) |
| **Task 8: Pay, a month at a time, and the totals** | done | 4042a02 `feat(web): Activity Pay - a month at a time as a stub, then the totals since the start` (hash filled in by Task 9's commit; a commit cannot name itself) | vitest 1139 passed (123 files: Section B's 1108 + 31 new: 6 `month`, 4 `useMonthParam`, 5 `MonthStepper`, 5 `useLegFilters`, 11 `PayView`); tsc clean; eslint clean; the existing `SummaryPanel`, `BreakdownTable`, `Money`, `EquityChart`, `RefreshControl` and legacy portfolio tests pass unmodified (targeted run `features/activity components/pnl components/portfolio`: 18 files / 150 tests); da-vinci `lint.py` exit 0 on `web/features/activity`, `SummaryPanel.tsx`, `BreakdownTable.tsx`, `Money.tsx` | 2026-10-28 | (1) Step 1: da-vinci loaded (sync check `OK 16`, `web/DESIGN.md` status `ratified`); the task composes existing parts only (`Card`, `Stub`, `Meter`, `StatusWord`, `SegmentedControl`, `Button`), so no new colour, font, radius, elevation or token was needed and none is proposed. (2) Every code block (five test files, `month.ts`, `useMonthParam.ts`, `MonthStepper.tsx`, `useLegFilters.ts`, `useEquity.ts`, `PayMonth.tsx`, `PayView.tsx`, the `BreakdownTable.tsx` replacement and the `SegmentedControl` snippet) was extracted from a pristine copy of this plan by fence line number with a helper kept outside the repo, not retyped. (3) Step 3: all five new test files failed with "Failed to resolve import" before the implementations existed. (4) Step 7: both `Money` label spans carried the identical old class string and both were replaced (`replace_all`). (5) Step 9: the `<fieldset>` block (lines 56 to 73 of `SummaryPanel.tsx`) was replaced by script after asserting its first and last lines and that `<fieldset` occurs once; the `SegmentedControl` import sits directly after the `EmptyState` import, as told; the heading, list and button class edits each matched exactly once. The existing 422 book-choice test passed unmodified against the `SegmentedControl` (role `group`, label "Book", two `aria-pressed` buttons). (6) The `RefreshControl` test prints its two React act warnings and `EquityChart` its zero-width chart warnings in jsdom, exactly as before this task (not new). (7) No browser pass was done (the page is not mounted until Task 14); `PayView` is exercised by its tests only. |
| **Task 9: Pay, the filters, the equity curve and the legs** | done | ef081a7 `feat(web): Activity Pay - one set of filters over the totals, the curve and the legs` (hash filled in by Task 10's commit; a commit cannot name itself) | vitest 1147 passed (123 files: Task 8's 1139 + 8 new `PayView`, 19 in the file); tsc clean; eslint clean; the targeted run (`features/activity components/pnl`) passed 9 files / 84 tests, with every existing `LedgerTable` (`LegRow`, `CampaignRow`, `LedgerTable`), `EquityChart`, `SummaryPanel` and `SystemPanel` test unmodified; da-vinci `lint.py` over `web/features/activity web/components/pnl` finds nothing in any non-test source file (exit 1 only for the two em dashes in the legacy test titles at `SystemPanel.test.tsx:20` and `:82`, which the step expects and which are not copy) | 2026-10-28 | (1) Step 1: da-vinci already loaded in this session; the task composes existing parts (`Card`, `FIELD`, `FIELD_LABEL`, `StatusWord`, the hairline row recipe), so no new colour, font, radius, elevation or token was needed and none is proposed. (2) Step 2: the `leg`, `campaign` and `ledgerBody` helpers went in directly below `equity` and the `"/pnl/ledger"` entry of `serve` was replaced, both by script with an exactly-once assertion; the eight new tests were appended before the closing `});` of the describe. Code blocks were extracted from a pristine copy of the plan by fence line, not retyped (one first attempt used the wrong fence line, the helper refused it and wrote nothing). (3) Step 3: the eight new tests failed (no Symbol field, no filter sentence, no curve, no legs, no campaign threads); the eleven from Task 8 still passed. (4) Steps 4 and 5: `LedgerFilters`, `LegRow` and `CampaignRow` were replaced by the plan's whole-file blocks; `CampaignRow`'s thread button label, `data-testid`s and leg count text are the old ones, so the existing tests pass unmodified. (5) Step 6: the five `EquityChart` edits (four classes and the comment) each matched exactly once; the file still has five other em dashes in code comments, which the lint does not read as copy and the plan does not ask to change. (6) Step 11: the lint exit 1 is the two legacy test titles above, not source; the plan's expected result names exactly this case. (7) No browser pass (the page mounts in Task 14). |
| **Task 10: Ledger, the overview in the figure face, without a sub-navigation** | done | 71b75cf `feat(web): the ledger overview in the figure face, with no sub-navigation` (hash filled in by Task 11's commit; a commit cannot name itself) | vitest 1157 passed (126 files: Task 9's 1147 + 10 new: 2 `Tile`, 3 `OutcomePill`, 1 `BackToLedger`, 4 appended to `LedgerOverview`); tsc clean; eslint clean; the targeted run (`components/ledger`) passed 7 files / 28 tests, with the existing `LedgerOverview` (5), `TickerView`, `TradesView` and `ImportView` tests unmodified; da-vinci `lint.py` exit 0 on `web/components/ledger` | 2026-10-28 | (1) Step 1: da-vinci already loaded in this session; the task composes existing parts (`Card`, `StatusWord`, the perforated figure-line recipe, the existing `--chart-line` token), so no new colour, font, radius, elevation or token was needed and none is proposed. (2) Code blocks (the three new test files, the four appended `LedgerOverview` tests, `Tile.tsx`, `OutcomePill.tsx`, `BackToLedger.tsx`, `LedgerShell.tsx`, `TickerTable.tsx`, `LedgerOverview.tsx`) were extracted from a pristine copy of the plan by fence line, not retyped. (3) Step 3: not every new test failed before the change, and the plan's expectation names only the missing modules and the overview's old behaviour. Failing: `Tile` (2, no `TileList`), `BackToLedger` (file did not resolve), and 2 of the 4 appended overview tests (the sub-navigation and the missing links and source sentence). Already passing on the old code: all 3 `OutcomePill` tests and the other 2 appended overview tests (upcoming expiries, could not load). They pin behaviour the restyle has to keep, so they are kept as written and pass after it too. (4) Step 4: the `Charts.tsx` stroke (`var(--color-gain)` to `var(--chart-line)`) matched once, on the `PnlCurve` line only; `MonthlyBars` keeps `var(--color-gain)` as the plan says nothing else changes. (5) Step 7: `TickerView`'s tile container was swapped by script (the opening `<div className="grid grid-cols-2 ...">` and the `</div>` directly before `<p className="text-xs text-muted">`), with the import changed to `Tile, TileList`; `TickerView` still renders `LedgerNav` until Task 11, as the plan says. (6) The old `LedgerOverview.test.tsx` still mocks `usePathname` for the `LedgerNav` that the overview no longer renders; left as is (existing tests unmodified). (7) No browser pass (the Ledger view mounts in Task 14). |
| **Task 11: Ledger, the trades, ticker and import pages** | done | 08b92b6 `feat(web): the ledger's trades, ticker and import pages - sheet, fields, back link` (hash filled in by Task 12's commit; a commit cannot name itself) | vitest 1165 passed (126 files: Task 10's 1157 + 8 new: 4 `TradesView`, 2 `TickerView`, 2 `ImportView`); tsc clean; eslint clean; the targeted run (`components/ledger`) passed 7 files / 36 tests, with every existing `TradesView`, `TickerView`, `ImportView` and `LedgerOverview` test unmodified (save notes, filters into the request, CSV link, upload, oversize, PDF, review-and-refresh and no-history cases); da-vinci `lint.py` exit 0 on `web/components/ledger` and `web/app/ledger`; `LedgerNav.tsx` is imported nowhere now and is byte-identical to `main` | 2026-10-28 | (1) Step 1: da-vinci already loaded in this session; the task composes existing parts (`Sheet`, `Card`, `Button`, `FIELD`, `FIELD_LABEL`, the figure-line recipe), so no new colour, font, radius, elevation or token was needed and none is proposed. (2) All code blocks (the three test appends and the eight whole-file replacements: `TradesTable`, `TradesView`, `TradePanel`, `TickerView`, `ImportView` and the three ledger pages) were extracted from a pristine copy of the plan by fence line, not retyped; `within` was added to `TradesView.test.tsx`'s `@testing-library/react` import (alphabetical, after `waitFor`) as the plan says. (3) Step 3: 6 of the 8 new tests failed (no back link on the three views, no keyboard `tabindex` on a row, no `Trade` dialog); the other 2 already passed on the old code and pin behaviour the restyle keeps: "has neither the back link nor the heading when pinned to a ticker" and "says a feed that is failing, in words". (4) Step 6: `TradePanel` becomes a `Sheet`; its form state, resync rule and `ledger_annotate` flow are the plan's block, which the plan states is the old code unchanged, and its existing save-notes test passes unmodified. The `submitCommand` calls in `TradePanel` and `ImportView` are under `components/ledger`, not `web/features`, so the fence grep is unaffected. (5) The old `usePathname` mocks in the three existing test files are left as they are (existing tests unmodified). (6) No browser pass (the Ledger view mounts in Task 14, and the three routes are reached from it). |
| **Task 12: Fills and orders, three lists each naming its source** | done | a106cd0 `feat(web): Activity Fills and orders - the system's orders and fills, IBKR's executions, apart` (hash filled in by Task 13's commit; a commit cannot name itself) | vitest 1202 passed (131 files: Task 11's 1165 + 37 new: 3 `whenET` in `time.test.ts`, 6 `fills`, 7 `FillsTable`, 5 appended to `OrdersTable`, 6 `ExecutionsList`, 5 `SpreadFills`, 5 `FillsView`); tsc clean; eslint clean; the targeted run (`features components/options`) passed 67 files / 752 tests, with the five existing `OrdersTable` tests (empty Working state, n/a for a null fill price, state label, no roll button, rejected detail) unmodified; da-vinci `lint.py` exit 0 on `web/features/activity`, `OrdersTable.tsx`, `FillsTable.tsx` | 2026-10-28 | (1) Step 1: da-vinci already loaded in this session; the task composes existing parts (`Card`, `StatusWord`, `SegmentedControl`, the hairline row recipe, the figure face), so no new colour, font, radius, elevation or token was needed and none is proposed. (2) All code blocks (the test files, the two appends, `whenET`, `types.ts`, `fills.ts`, the two whole-file restyles, `ExecutionsList`, `SpreadFills`, `FillsView`) were extracted from a pristine copy of the plan by fence line, not retyped. `whenET` was added to `time.test.ts`'s import after `todayInNewYork`, and its describe appended after the existing one with one blank line. (3) `OrdersTable.test.tsx` ends with `});` and no trailing newline (the plan says the describe's closing `});` is the last line of the file); the five tests were inserted before that line by script and the file still ends without a newline, so the diff is only the added lines. The appended tests use `as any` for the `apiFetch` mock exactly as the plan writes them, and `next lint` accepts them. (4) Step 3: `whenET` (3), `FillsTable` (6 of 7) and all five new `OrdersTable` cases failed on the old code, and the four new modules' test files failed to resolve their imports; `FillsTable`'s seventh case ("says it could not load") already passed on the old table, which also printed "Could not load fills". It pins behaviour the restyle keeps. (5) `components/options/OrdersTable.tsx` and `FillsTable.tsx` are not imported by any mounted page yet (Task 14 mounts `FillsView`); the web CLAUDE.md `components/options` entry says they were unmounted until Part 3, and this task mounts them only through `FillsView`. (6) No browser pass (the view mounts in Task 14). |
| **Task 13: System, the sizing record over the score against outcome** | done | cc799d6 `feat(web): Activity System - the sizing record over the score against outcome` (hash filled in by Task 14's commit; a commit cannot name itself) | vitest 1235 passed (134 files: Task 12's 1202 + 33 new: 15 `sizing`, 12 `SizingRecord`, 4 `SystemView`, 2 appended to `SystemPanel`); tsc clean; eslint clean; the targeted run (`features/activity components/pnl`) passed 16 files / 139 tests, with the ten existing `SystemPanel` tests (the notes in order, no control that could change a weight, the small-sample label, buckets and correlations with n/a, the agreement block) unmodified; da-vinci `lint.py` over `web/features/activity web/components/pnl` finds nothing in any non-test source file (exit 1 only for the same two legacy test-title em dashes at `SystemPanel.test.tsx:20` and `:82`, which the step expects) | 2026-10-28 | (1) Step 1: da-vinci already loaded in this session; the task composes existing parts (`Card`, `FIELD`, `FIELD_LABEL`, the stub face), so no new colour, font, radius, elevation or token was needed and none is proposed. The sizing marks use no gain or loss colour on purpose (a positive number is what the action cost), as the plan's component comment says. (2) All code blocks (the three new test files, the two `SystemPanel` test appends, `sizing.ts`, `SizingRecord.tsx`, the three whole-file restyles and `SystemView.tsx`) were extracted from a pristine copy of the plan by fence line, not retyped. `WindowControls` was added to `SystemPanel.test.tsx`'s `./SystemPanel` import as the plan says; the two tests were appended before the describe's closing `});`. (3) Step 3: the two `SystemPanel` cases failed (the date controls still rendered with `windowControls={false}`; `WindowControls` was undefined) and the three new test files failed to resolve their imports. (4) Step 6: `SystemPanel`'s `since` and `until` inputs keep `data-role="window-control"` and their `aria-label`s, so the existing "only controls on the surface" test passes unmodified; `SystemPanel` is no longer wrapped by `PnlShell` (unmounted, ruling 12). (5) `SizingRecord` reads `GET /pnl/sizing` and the existing `GET /claude/context` through `useClaudeContext`; nothing under `features/activity` sends a command (the fence grep is checked at the section end). (6) No browser pass (the view mounts in Task 14). |
| **Task 14: the Activity page at `/activity`, and `/ledger` joins it** | done | 2246d00 `feat(web): the Activity page - Pay, Ledger, Fills and orders, System; /ledger redirects into it` (hash filled in by Section D's first commit; `git log --oneline main..HEAD` shows fourteen commits at the end of Section C) | vitest 1242 passed (135 files: Task 13's 1235 + 7 `ActivityPage`; the `next.config` and More changes edit existing tests in place, as the plan says); tsc clean; eslint clean; da-vinci `lint.py` exit 0 on `web/features/activity`, `web/app/activity`, `web/app/more`; `design_md_check.py web/DESIGN.md` exit 0; scratch-copy production build green, listing `/activity`, `/portfolio`, `/ledger/trades`, `/ledger/import` and `/ledger/ticker/[symbol]` and no `/ledger`. Section C exit: pytest 4992 passed + 1 skipped (unchanged, the section adds no Python; no `tests/test_scan_timeout.py` flake this run), ruff clean, mypy clean (297 files); `git diff --stat main --` over the six protected components and `lib/commands.ts`, `lib/receipt.ts` prints nothing; `grep -rn "submitCommand\|confirmCommand" web/features` prints only `features/more/TargetCard.tsx` and `features/more/TargetCard.test.tsx`; the legacy files of ruling 12 (`components/portfolio/{PortfolioShell,SummaryPanel,PositionsPanel,PositionGroup,StockLegRow,OptionLegRow,CampaignsPanel,CampaignThread,CalendarPanel}.tsx`, `components/pnl/PnlShell.tsx`, `components/ledger/LedgerNav.tsx`) are byte-identical to `main`; of them only `PortfolioShell.test.tsx` still imports one (`PortfolioShell`), `PnlShell` and `LedgerNav` are imported nowhere | 2026-10-28 | (1) Step 1: da-vinci already loaded in this session; the task is the page frame only (title, the four view chips, the view), composed from `SegmentedControl`, so no new colour, font, radius, elevation or token was needed and none is proposed. (2) The test file, `views.ts`, `ActivityPage.tsx` and `app/activity/page.tsx` were extracted from a pristine copy of the plan by fence line, not retyped. The `/ledger` redirect sits after the `/pnl` entry in `next.config.ts` and its assertion after the `/pnl` assertion in `next.config.test.ts` (the plan names the redirect's place, not the assertion's). The More test's title and Ledger assertion were changed as quoted (the assertion was on line 48); the Ledger row's `href` changed and its label and sub-line did not, and `Import a statement` keeps `/ledger/import`. (3) Step 3: `ActivityPage.test.tsx` failed to resolve `./ActivityPage`; the `/ledger` redirect assertion failed (`map["/ledger"]` undefined); the More Ledger-link case failed on the old `/ledger` href. The other seven tests in those two files passed throughout. (4) `web/app/ledger/page.tsx` was removed with `git rm`. (5) Step 5: the scratch-copy build was run as the plan's snippet writes it, with `TMPDIR` exported to the scratchpad path first; macOS `mktemp -d` still created the directory under `/var/folders/.../T` and not under `TMPDIR`, so the copy lived outside both the repo and the scratchpad. It was never inside `web/`, `web/.next` was not touched, and the copy was deleted afterwards (its `node_modules` symlink removed first, so nothing in `node_modules` was affected). The build log is in the scratchpad (`t14_build.log`). (6) Section C exit: the plan counts "seven more commits"; the branch has fourteen beyond c692a1b, none of them a review fix pass. (7) No browser pass was done in this section (not asked for; the page-level visual check at 1440px and 390px, both themes, is Section D's da-vinci finish), so `/activity` and the three restyled `/ledger/*` routes have been exercised by their tests and a production build only, not looked at in a rendered viewport. (8) The next section's first commit should fill in this row's hash (and Section D's entry check C-count). |
| **Section D entry** | done | (none) | D1-D4 pass (run by the orchestrator); re-run by the orchestrator after Section C: pytest 4992 passed + 1 skipped, ruff clean, mypy clean (297 files); vitest 1242 passed (135 files), tsc clean, eslint clean; scratch-copy `next build` green (`/activity`, `/portfolio`, `/ledger/trades`, `/ledger/import`, `/ledger/ticker/[symbol]`, no `/ledger`); protected-file diff empty; `submitCommand` grep prints only `TargetCard` | 2026-10-28 | (no rulings) |
| **Task 15: docs, the da-vinci finish, the full gate** | done (Steps 1-6; Step 7, the whole-branch review and the finishing step, is the orchestrator's) | c828a54 `fix(web): da-vinci finish of Portfolio and Activity` (also carries the Task 14 hash fill-in and the Section D entry row), 4c79c6f `docs: web overhaul Part 3 - Portfolio, Activity, the sizing record, the audit lists`, and the Progress-log commit `docs(plan): web overhaul Part 3 Progress log` (a commit cannot name itself) | pytest 4992 passed + 1 skipped (unchanged: no Python changed in Section D; 229 s, no `test_scan_timeout` flake), ruff clean, mypy clean (297 files); vitest 1257 passed (136 files: Task 14's 1242 + 15 finish tests), tsc clean, eslint clean; da-vinci `lint.py` over `web/features web/components/{pnl,ledger,portfolio,options,ui}` exits 1 with 22 `EM_DASH` lines, all in eight legacy test files (`ApprovalCard`, `ApprovalsList`, `AssessedRow`, `AutonomyControl`, `CommandReceipt`, `HaltControl`, `ShortsTable`, `SystemPanel` `.test.tsx`, none of those lines edited on this branch; `SystemPanel.test.tsx` lines 20 and 82 are the two the plan already names), and no finding in any non-test source file or in any file this branch added; `design_md_check.py web/DESIGN.md` exit 0; `grep -rn "submitCommand\|confirmCommand" web/features` prints only `features/more/TargetCard.tsx` and its test; `git diff --stat main --` over the six protected components and `lib/commands.ts`, `lib/receipt.ts` prints nothing; scratch-copy production build green, listing `/activity`, `/portfolio`, `/ledger/trades`, `/ledger/import` and `/ledger/ticker/[symbol]` and no `/ledger` (log `scratchpad/d/final_build.log`). Screenshots: about 200 PNGs in the session scratchpad (`.../scratchpad/d/shots/`, never in the repo): every listed route at 1440px and 390px in light and dark (the first pass `*-1440-light|dark`, `*-390-light|dark`, the open states `*-open-*`, `*-legopen-*`, `*-sheet-*`), then 320px for `/portfolio` (all three views) and every Activity view, and a final set (`end-*`, `fin-*`) of the finished code. | 2026-10-28 | (1) Step 1: the mock API is the plan's text, extracted by line range and unmodified, run on 8799; the scratch `next dev` ran on 3100 from a copy of `web/` under the scratchpad (`dev-copy/web`, `node_modules` symlinked), not `mktemp`, so nothing was ever built or served inside `web/`. The operator's dev server on 3000 was never touched. (2) Step 2 viewing tool: the Playwright MCP could navigate, resize, click and read the console, but `browser_take_screenshot` refuses paths outside the repo root and its `.playwright-mcp`, so screenshots were written with `page.screenshot({ path })` through `browser_run_code_unsafe` straight into the scratchpad. The tool's own console and snapshot logs went to its long-standing, git-ignored `.playwright-mcp/` in the main checkout (its default output directory; nothing in the worktree). `main` is the scroll container (the root row is `h-dvh overflow-hidden`), so each capture enlarged the viewport to the content's height to show the whole page. Every image was opened and looked at. (3) The mock has no ledger trade, ticker history or import-history rows (`/ledger/trades` is empty and `/ledger/tickers/NVDA` and `/ledger/imports` answer 404), so "open a trade: the sheet", the ticker page and the import history could not show their real states from the mock alone. They were checked with `page.route()` overlays (synthetic trades, one ticker, two import runs) on top of the unchanged mock. The Orders list showing a filled order under "Working" is the mock ignoring `?state=`, not the app. (4) Console: the only errors on any route, viewport or theme were `/favicon.ico` 404 (DESIGN.md: no favicon exists) and 404s from routes the mock lacks (`/api/ledger/tickers/NVDA`, `/api/ledger/imports`); no React, hydration or unhandled-exception message, before or after the fixes. (5) Step 3 ran in-thread by the implementer (ruling 16), not as a fresh finish-reviewer subagent: da-vinci `critique` (single context, design review written before the lint and DOM evidence, rendered at 1440 and 390), `audit` (accessibility by DOM scan: no nameless control, no duplicate id, one `h1` and ordered headings per page, focus ring a 2px ink outline, phone targets 44px through the chips' hit area, so only the stub-line exception reads 24px; responsive by `scrollWidth` at 320, 390 and 1440; theming by both themes on every route) and `polish`. Critique, in brief: the payslip system is applied coherently; the register pages answer one question per card; unknowns are hatched `n/a`; no new colour, font, radius, elevation or token was needed, so none is proposed. (6) Finish findings and fixes (each with a test written red first, in the same commit; no existing test edited, only tests appended): **P1** the System view, Pay with a leg thread open and the ledger's overview, trades, ticker and import pages clipped on a phone (a page-level `grid` with no column template is sized by its widest table: `main` was 449px wide on System, 591px on Pay and 1091px on `/ledger/trades` at a 390px viewport), against ruling 15; the six view roots and the P&L summary's breakdown grid are now `grid-cols-1`, so a table scrolls inside its card. **P2** a table that scrolls on a phone said nothing, so the import history's Counts column and the score tables' last columns were cut off unannounced; the legs, the P&L breakdowns, the three score-evidence tables and the import history now carry "Scroll sideways to see every column." as the ledger's tables already did. **P2** the ledger's two charts overflowed their `h-64` figure by the caption's height, so the cumulative curve's axis labels ran into the sentence below it; each figure is now a flex column and the chart takes the room under its caption. **P2** the monthly premium chart named its two bars by colour alone; a legend names them. **P3** a ledger bucket table with no rows showed only its headings (now "None yet."); the sizing record's "to expiry" and "exit rules" marks wrapped onto two lines on a phone (now `shrink-0`). Observed and not fixed (copy and design that the plan does not ask this finish to change): Pay's by-strategy table shows the raw label `cash_secured_put` (the API's label, pinned by the legacy tests), a ledger trade's null stock gain reads blank where `n/a` is meant, the page `<title>` is "IBKR Income" on every route (app-wide), and the month stepper's disabled arrows draw as a filled circle, which the Decision Log now adds to the existing open "disabled quiet button" decision. (7) Step 4: every edit anchored on text that occurs exactly once and was checked by grep after it landed; `design_md_check.py` exit 0 with `updated=2026-10-28` and `status=ratified`. The Decision Log entry is dated 2026-10-28. `docs/web/api.md` also corrects `GET /options/orders`'s introduction, which still named a `partial` order as working (the params line had been fixed in f4af002). `web/CLAUDE.md` has no `ledger/` component entry on `main`, so one was added beside the app-level `ledger/` entry. **`README.md` is unchanged**: no Telegram command and no top-level directory was added (its one `/ledger` sentence is still true, since `/ledger` redirects to the overview). (8) `web/.next` exists in this worktree as `web/.next/cache/eslint` only (the lint cache `next lint` writes, created at 13:39 before Section D, git-ignored); `next build` and `next dev` never ran inside `web/`. All scratch copies (dev, build) were removed symlink first. |

*(Rows are added as each task lands; a ruling is any deviation from the task text, and why.)*

## Roadmap (this plan is Part 3 of 5)

- **Part 1 — Foundation, shell and Home.** Done (merged ab7339c), plus the Home follow-ups
  (merged bb34b58).
- **Part 2 — Trades.** Done (merged 4872a77).
- **Part 3 — Portfolio and Activity.** This plan.
- **Part 4 — Research, News, More and cleanup.** As planned in Parts 1 and 2, plus: delete what
  this part leaves unmounted (ruling 12 lists every file) after porting any test that is the only
  coverage of something still live.
- **Part 5 — Order control.** Unchanged: cancelling a working order from Trades → History needs
  its own spec and reviewed plan. Until it ships, History says in words that a working order is
  cancelled in IBKR. Fills and orders (Task 12) says the same in one sentence under Working.

## Rulings made up front (the operator may overturn any of them)

The evidence behind rulings 9 to 11 (read from the live databases on 2026-10-23, read-only):
`orders` holds 83 filled, 63 cancelled, 7 rejected and 5 partial rows (all paper); `fills` holds
92 rows (2026-06-24 to 2026-10-22); `broker_executions` (superseded rows excluded) holds 108
system executions from the live feed (2026-10-06 to 2026-10-22), 34 manual ones (27 Flex, 7 live)
and 4 credit-spread ones, all on 2026-10-08, plus 6 order-level statement rows; `spread_orders`
holds 2 rows, both on 2026-10-15; `sizing_actions` holds 7 rows (5 `scale_in_zone`, 2
`loss_exit_cooldown`). For credit spreads the system's record and the ledger's do not cover the
same days. That is what an audit page is for, and why neither list stands in for the other.

1. **Portfolio is where you read what you hold; Home stays the glance.** Three views in the URL
   (`?view=positions|campaigns|calendar`, default Positions; a junk value is Positions). There is
   no strategy switcher: Positions carries Home's type chips (All, CSPs, CCs, Credit spreads,
   Shares) itself, Campaigns has its own status chips, and a campaign is a symbol's thread, not a
   strategy. Above the views, the account in figure lines (`GET /portfolio/summary`), the
   freshness in words, a **Delayed** word when the snapshot is older than 30 minutes or degraded
   (the same `FRESH_FOR_MINUTES` as Home), the API's degraded note verbatim, and Refresh.
2. **Positions are grouped by name, with Home's row anatomy.** One card per underlying: the
   ticker, its flag words, the name's open P&L, the shares line (with the premium-adjusted cost
   basis when there is one), then one row per option leg built by `buildPositionRows` (the same
   rows, status words and "Roll alert" word Home shows, each opening the contract's page), with a
   detail line (delta and its source, mark, value). Credit spreads are one more card, "SPY credit
   spreads", from `GET /spreads/positions`. **A name's open P&L is the sum only when every leg's
   P&L is known; otherwise it is `n/a`**, never the sum of the known legs and never `$0`.
3. **Campaigns keep the server-side filters** (`status`, `symbol` in the request, so a filter is a
   real refetch). Money in a thread is **before commissions** and says so in words (the API
   states it); an assigned thread shows its adjusted cost basis and realised stock P&L; a leg
   whose candidate was pruned is "Leg unavailable", never dropped.
4. **Calendar** keeps the horizon (14, 30, 45, 90, 180 days) in the request. A short option whose
   name has a **verified event date** (the news service's dossier; Python checked the date against
   the cited news) between today and the expiry gets the word "Event <date> before expiry".
   Only the date is shown: the event's title is Claude's, and the calendar needs no prose.
5. **The market picture, where it matters (four additions).** (a) The "Weak health" and "Event"
   words on each name in Positions (`NameFlags`, built 2026-10-23). (b) The event word on the
   Calendar (ruling 4). (c) **An order says what shaped its size**: `OrderSummary.sizing` lists the
   `sizing_actions` rows linked to it, and the Orders list shows them in words ("Claude's cut ·
   Sent 1 of 3 contracts") so the auditor sees why 1 contract went out when the scan said 3. (d)
   **System gains the sizing record** (`GET /pnl/sizing`). **Not built, with reasons:** the ladder's
   next-lot zone per held name (not served per held name; the scan computes it per candidate, and
   serving it needs trading-side code), a "room left under the regime budget" card (a new
   computation on the trading side; it needs its own spec), and a governing regime per held name
   (the regime sizes entries, not holdings). Each is listed in `STATUS.md` in Task 15.
6. **Activity is one page, four views in the URL** (`?view=pay|ledger|fills|system`, default Pay;
   a junk value is Pay). There is no strategy switcher: P&L and the ledger already carry their
   own filters (book, strategy, symbol, outcome, dates), and the broker ledger spans both books.
7. **Pay is a month at a time.** `?month=YYYY-MM` (a junk value or a future month opens the
   current month; the stepper stops at the month the system began), previous, next and "This
   month" in New York months. The month is a stub (the same `payStubLines` Home uses, always
   open here), then three more cards: the record since the system began (the restyled P&L
   summary, with its mixed-book choice), the equity curve (restyled), and **Legs** (the filters,
   the campaign threads and the CSV export, restyled). A month with nothing opened or closed says
   so in a sentence under the stub of genuine zeros.
8. **The legs table lives under Pay** (the operator's P&L page, kept whole). The Ledger view is
   the broker-truth ledger, a different list: what IBKR says happened, from the trade ledger.
9. **Ledger is the ledger's overview embedded in Activity.** `/ledger` redirects (307) to
   `/activity?view=ledger`; `/ledger/trades`, `/ledger/ticker/:symbol` and `/ledger/import` keep
   their routes, are restyled in the figure face, and replace the ledger's own sub-navigation
   with a back link to Activity → Ledger. The rail still marks Activity current on them.
10. **Fills and orders is three lists with named sources, never merged.** **Orders**: the system's
    own `orders` (Working, All, Rejected, over a window), each with the sizing words (ruling 5c).
    Working is queued and submitted only: a `partial` order is final since 2026-10-27 (the rest
    was cancelled at the fill timeout), so it shows under All with the "Partial" flag word.
    **Fills**: the system's own `fills` with the contract named (they carried only a candidate
    id), plus the credit-spread book's filled orders from `GET /spreads/orders`, which is
    "unavailable" when the file cannot be read, never "none". **At IBKR**: the ledger's real
    executions (`GET /ledger/executions`), newest first, tagged by book (System, Spreads, Manual).
    The page does not reconcile the lists; seeing both is the audit. Under Working, one sentence
    says a working order is cancelled in IBKR for now (Part 5).
11. **System keeps the score-vs-outcome evidence exactly as it is** (the read-only sentences first,
    no control that could change a weight) and gains the sizing record above it: one line per
    kind of action with the rows counted, the rows valued so far, the contracts withheld, and the
    two marks ("to expiry" and "exit rules") in words that say a positive number is what the
    action **cost**. Rows not yet valued are counted and not valued. The record shows Claude's cut
    as applied or recorded-only from `GET /claude/context`'s existing cut mode. Nothing on the
    page can change a limit, a size or a weight.
12. **Legacy files left unmounted stay put for Part 4**, because deleting a component means
    porting its tests first: `components/portfolio/{PortfolioShell,SummaryPanel,PositionsPanel,
    PositionGroup,StockLegRow,OptionLegRow,CampaignsPanel,CampaignThread,CalendarPanel}.tsx`
    (with their tests), `components/pnl/PnlShell.tsx` (no test) and
    `components/ledger/LedgerNav.tsx` (no test of its own). None of them is restyled.
    `components/portfolio/FreshnessLabel.tsx` stays mounted and unchanged; `Money`,
    `DegradedNotice` and `RefreshControl` are restyled in place under their tests.
13. **Protected files are byte-identical to `main`:** `web/components/options/{DecideControls,
    ConfirmAction,CommandReceipt,HaltControl,AutonomyControl,RollModeControl}.tsx` and
    `web/lib/{commands,receipt}.ts`. The existing `RefreshControl` and `ImportView` tests pass
    unmodified (new cases are only appended): the restyle of the two flows that send commands
    changes markup only.
14. **Times.** Trade and fill times on the new lists are New York time, labelled ("2:31 PM ET"),
    as on Trades. The Pay month is a New York month. The restyled P&L and ledger tables keep the
    dates they already show (the ledger's trade dates are already US/Eastern dates; the P&L
    tables show dates, not clock times).
15. **Phones.** New lists are rows, not tables. The restyled wide tables (the ledger's trades and
    tickers tables, the legs) scroll inside their own container, never the page; a table that
    scrolls says "Scroll sideways" in a caption on a phone. No element reaches past the viewport.
16. **The finish review runs in-thread** unless the operator allows a subagent; disclose which.

## Global Constraints

- Every colour comes from a semantic token; never a raw palette class (`bg-white`, `bg-gray-800`)
  or a hex literal in a component. Charts read tokens from CSS custom properties at mount.
- Fonts: Hanken Grotesk for everything; Red Hat Mono (`font-mono`) for stub, ledger and price
  figures. Apply `.tabular` to every numeric column.
- Lime (`bg-primary`) only on primary actions, the pending-count badge, the pay meter and the
  "Expires today" status word. Nothing on Portfolio or Activity is lime except the pay meter on
  the Pay view's stub and an "Expires today" word on a position row.
- Unknown values render `n/a` with the `.hatch` texture and `text-unknown`, never `$0`, `0%` or a
  blank. A genuine zero renders `$0`.
- No state by colour alone: signed money carries `+`/`−`, flags carry a word, selected carries an
  ink fill (never lime or green).
- Charts never animate their data in. Only touched things move (chevron 180ms, sheet 240ms in,
  press scale 0.98), all removed under `prefers-reduced-motion`.
- No shadow anywhere except the review sheet and the confirm dialog.
- Zero em dashes in UI copy; banned words: "seamless", "robust", "unlock", "elevate".
- Claude's text is always labelled as Claude's ("Claude's cut", "Claude's reason") and never sits
  on a button. A sizing action's reason is shown as "Claude's reason:" when its kind is
  `claude_cut` or `claude_cut_unapplied`, and as "Rule:" (its codes spelled out) for every other
  kind.
- Safety friction unchanged: every order intent goes through `DecideControls` → `ConfirmAction`;
  the second LIVE confirmation stays. These pages add no order intent.
- `grep -rn "submitCommand\|confirmCommand" web/features` prints only `features/more/TargetCard.tsx`
  and its test (on `main` before Part 2): the new features reach commands only through
  `components/portfolio/RefreshControl` and the `components/ledger` flows, never directly.
- Old URLs keep working: `/pnl` → `/activity` (already), `/ledger` → `/activity?view=ledger` (new,
  307). `/ledger/trades`, `/ledger/ticker/:symbol`, `/ledger/import`, `/portfolio` and
  `/activity` keep their paths.
- Backend: the API writes nothing new (still exactly one table, `app_commands`); no schema
  change; nothing under `src/api/` imports `src.spreads`; `data/spreads.db` is opened only by
  `src/api/spreads_db.py`; `src/ledger/` stays the only writer of the ledger tables (the
  executions route only reads); `GET /pnl/sizing` calls `summarize` and recomputes nothing; no
  engine, execution, strategy or sizing code changes or imports anything new.
- Quality gate after every task: `cd web && npx vitest run && npx tsc --noEmit && npm run lint`;
  for backend tasks also `python -m pytest -q && ruff check . && mypy src` from the repo root, after
  `ruff format` on the Python files the task creates or extends (they are formatted on `main`, so
  the diff is only the task's own lines).
- Never run `next build` inside `web/` (the operator's `next dev` shares `web/.next`): build in a
  scratch copy (command in Section C's entry checks).
- da-vinci never changes the design system (colour, font, radius, elevation, a new token)
  without the operator; a new token is proposed in the Progress log and waits.

## Review Focus

1. **A name's total is never a partial sum.** One leg with an unknown mark makes the name's open
   P&L `n/a`; a genuine `$0` stays `$0`; the shares row counts as the card shows it, the
   premium-adjusted figure when there is one → Task 5 `rowsPnl` tests (5) and PositionsView tests
   "shows n/a for a name's total when one leg is unknown, never the sum of the rest" and "keeps a
   genuine zero as $0".
2. **An old or degraded snapshot says so, and an empty one says why.** The `eod` rung with
   `degraded` shows "Delayed", the age and the API's note verbatim on Portfolio; `source: none`
   says "No portfolio snapshot has been captured yet." in Positions and Calendar and never "No
   open positions" → Task 4 SummaryCard tests, Task 5 and Task 6 view tests.
3. **Unreadable is not none.** An unreadable spreads book on Portfolio says "Credit spreads are
   unavailable right now" and does not list zero spreads; the spread-fills section on Fills says
   the same → Task 5 test "says an unreadable spreads book is unavailable, not empty", Task 12
   `SpreadFills` tests "says the book is unavailable, not empty, when the file cannot be read" and
   "says unavailable when the request fails".
4. **Months.** `?month=2026-13`, `?month=abc` and a future month open the current month; the
   stepper never offers a month after this one nor one before the system began; a month with
   nothing opened or closed shows genuine zeros and says so → Task 8 `month.test.ts` and PayView
   tests.
5. **The three fill lists can disagree, and the page lets them.** Fills with none recorded by the
   system says so while At IBKR lists executions; At IBKR with none says where they come from
   and that a statement import or the Flex query fills them; the page never merges rows →
   Task 12 tests.
6. **The sizing record is honest about what it has not valued.** Unresolved rows count and are
   not valued; a `pushed_out` line carries no money; a valued row without an entry IV is left out
   of "exit rules" and said so; an empty record says "No sizing actions on record yet." and shows
   no zeros; a positive number is worded as what the action **cost** → Task 1 tests, Task 13
   tests.
7. **The legs list narrows with the best/worst jump and exports what it shows.** Choosing a leg in
   the record sets the Legs symbol filter, the list narrows, and the CSV link carries the same
   query string → Task 9 tests.
8. **Refresh is untouched in behaviour.** Restyling `RefreshControl` changes classes only: its
   existing test passes unmodified (a `broker_unavailable` answer is still a plain answer, not
   red chrome) → Task 4 Step 10 (the existing `RefreshControl` tests run unmodified).
9. **`/ledger` still reaches the ledger.** The redirect points at `/activity?view=ledger` (Next
   forwards the query string it is given) and the three drill-down routes keep their pages →
   Task 14 `next.config.test.ts` and the scratch-copy build, which lists them.

---

## File structure

```
src/
  api/models/pnl.py                 MODIFY  SizingGroupOut, SizingRecordResponse
  api/routers/pnl.py                MODIFY  GET /pnl/sizing (+ _sizing_groups)
  api/models/options.py             MODIFY  OrderSizingOut; OrderSummary.sizing; FillSummary contract fields
  api/routers/options.py            MODIFY  list_orders (days, sizing), list_fills (contract, days <= 365)
  api/models/ledger.py              MODIFY  LedgerExecutionRowOut, LedgerExecutionsResponse
  api/routers/ledger.py             MODIFY  GET /ledger/executions
  api/spreads_db.py                 MODIFY  try_read_spread_order_rows
  api/models/spreads.py             MODIFY  SpreadOrderOut, SpreadOrdersResponse
  api/routers/spreads.py            MODIFY  GET /spreads/orders
tests/test_api_pnl_sizing.py        CREATE  (10 tests)
tests/test_api_orders.py            MODIFY  +9
tests/test_api_ledger.py            MODIFY  +5
tests/test_api_spread_orders.py     CREATE  (6 tests)
docs/web/openapi.json               MODIFY  regenerated (Tasks 1-3)
web/
  lib/api-types.ts                  MODIFY  regenerated, offline (Tasks 1-3)
  lib/useViewParam.ts               CREATE  (+ test)
  next.config.ts, next.config.test.ts  MODIFY  /ledger -> /activity?view=ledger
  components/ui/field.ts            CREATE  FIELD, FIELD_LABEL (the `field` component's classes)
  components/options/types.ts       MODIFY  OrderSummary.sizing, FillSummary contract fields
  components/options/OrdersTable.tsx, FillsTable.tsx   MODIFY  restyle, window, sizing words
                                            (+ FillsTable.test.tsx CREATE)
  components/portfolio/RefreshControl.tsx, DegradedNotice.tsx, Money.tsx   MODIFY  classes only
  components/pnl/SummaryPanel.tsx, BreakdownTable.tsx, EquityChart.tsx, CampaignRow.tsx,
    LegRow.tsx, LedgerFilters.tsx, SystemPanel.tsx, ScoreBucketTable.tsx,
    CorrelationTable.tsx            MODIFY  restyle in place, same text and test ids
  components/ledger/BackToLedger.tsx, LedgerShell.tsx   CREATE (+ BackToLedger.test.tsx)
  components/ledger/Tile.tsx, OutcomePill.tsx, Charts.tsx, TickerTable.tsx, LedgerOverview.tsx,
    TradesTable.tsx, TradesView.tsx, TradePanel.tsx (now a Sheet), TickerView.tsx,
    ImportView.tsx                  MODIFY  restyle in place; LedgerNav.tsx unmounted
  features/home/PositionRowItem.tsx CREATE  Home's row, shared (+ test); PositionsCard.tsx MODIFY
  features/market/market.ts         MODIFY  eventBefore
  features/trades/time.ts           MODIFY  whenET
  features/portfolio/               CREATE  format.ts, views.ts, SummaryCard.tsx, positions.ts,
                                            PositionsView.tsx, campaigns.ts, CampaignsView.tsx,
                                            calendar.ts, CalendarView.tsx, PortfolioPage.tsx
                                            (+ tests)
  features/activity/                CREATE  types.ts, month.ts, useMonthParam.ts, MonthStepper.tsx,
                                            useLegFilters.ts, useEquity.ts, PayMonth.tsx, Curve.tsx,
                                            Legs.tsx, PayView.tsx, fills.ts, ExecutionsList.tsx,
                                            SpreadFills.tsx, FillsView.tsx, sizing.ts,
                                            SizingRecord.tsx, SystemView.tsx, views.ts,
                                            ActivityPage.tsx (+ tests)
  app/portfolio/page.tsx            MODIFY  <Suspense><PortfolioPage/></Suspense>
  app/activity/page.tsx             MODIFY  <Suspense><ActivityPage/></Suspense>
  app/ledger/page.tsx               DELETE  (next.config redirect owns /ledger)
  app/ledger/trades/page.tsx, import/page.tsx, ticker/[symbol]/page.tsx   MODIFY  LedgerShell frame
  app/more/page.tsx, app/more/page.test.tsx   MODIFY  the Ledger row opens Activity → Ledger
  DESIGN.md, CLAUDE.md              MODIFY
ARCHITECTURE.md, STATUS.md, SETUP.md, CLAUDE.md, docs/web/api.md   MODIFY (Task 15)
```

---

## Section A — The API (Tasks 1–3) · model: sonnet (effort xhigh)

Three read-only routes and two enriched shapes. Nothing here touches the web app except the
regenerated `api-types.ts` and one hand-written type file that gains optional fields.

**Entry checks (the baseline; run from the repo root on `main` before Task 1 Step 1):**

- [ ] **A1. Clean starting point, on the commits this plan was verified against.**
  `git status --short` shows nothing (optionally `web/design-preview.html`, untracked);
  `git branch --show-current` prints `main`. The plan file itself is tracked (it was committed
  with the market-picture web work in 353cdd8). Each of these prints at least one line:

  ```bash
  git ls-files web/features/market/NameFlags.tsx web/features/claude-context/useClaudeContext.ts
  git merge-base --is-ancestor c692a1b HEAD && echo "c692a1b is in main"
  grep -n '_WORKING = {"queued", "submitted"}' src/api/routers/options.py
  ```

  The first is the 2026-10-23 web follow-up of the market-picture build (the Market card,
  `NameNotes`, `NameFlags`, `HeldBack`, `GET /claude/sizing`, `useClaudeContext`) that this plan
  builds on; the second is the commit the plan was last replayed against (2026-10-28); the third
  is f4af002's rule that a `partial` order is final, which Task 2 keeps. If any prints nothing,
  **stop** and report: `main` has moved in a way this plan has not been checked against.
- [ ] **A2. Baseline is green.** All of these pass; record the pytest and vitest counts in the
  Progress log row, because every later gate compares against them (on 2026-10-28: pytest 4963,
  vitest 1027; your counts may be higher if `main` moved):

  ```bash
  python -m pytest -q && ruff check . && mypy src
  cd web && npx vitest run && npx tsc --noEmit && npm run lint && cd ..
  ```

  A red baseline is not this plan's to fix: stop and report it. One known exception:
  `tests/test_scan_timeout.py` is flaky (one of its cases fails intermittently with a
  `TimeoutError`, a different one each run; logged 2026-10-27). If that file is the only failure,
  re-run it alone (`python -m pytest tests/test_scan_timeout.py -q`); if it passes, note "scan
  timeout flake" in the Progress log and continue. The same rule applies at every later gate.
- [ ] **A3. The spec is valid.** `python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md`
  exits 0.
- [ ] **A4. The pieces Section A builds on exist.** Each command prints at least one line:

  ```bash
  grep -n "def summarize" src/claude/eval/sizing_counterfactual.py
  grep -n "def pnl_system" src/api/routers/pnl.py
  grep -n "def list_orders\|def list_fills\|def _order_underlying_strategy_strike" src/api/routers/options.py
  grep -n "class SizingActionRow" src/storage/models.py
  grep -n "class BrokerExecutionRow" src/storage/models.py
  grep -n "def try_read_spread_rows_opened\|def spreads_read_session" src/api/spreads_db.py
  grep -n "class SpreadOrderRow" src/spreads/store.py
  grep -n "^LedgerBookName" src/common/schemas.py
  ```

- [ ] **A5. Nothing already named what Section A adds.** This prints nothing:

  ```bash
  grep -rn "SizingGroupOut\|SizingRecordResponse\|OrderSizingOut\|LedgerExecutionRowOut\|SpreadOrderOut" src tests web/lib
  ```

**Section exit:** three commits on `feat/web-overhaul-3`; Tasks 1–3 ticked in the Progress log;
`docs/web/openapi.json` and `web/lib/api-types.ts` regenerated and current.

---

### Task 1: `GET /pnl/sizing` — what the limits and Claude's cuts held back, and what that earned

**Files:**
- Modify: `src/api/models/pnl.py`, `src/api/routers/pnl.py`
- Create: `tests/test_api_pnl_sizing.py`
- Modify: `docs/web/openapi.json`, `web/lib/api-types.ts` (both regenerated)
- Modify: this plan file (its Progress log rows; it is already tracked)

**Interfaces:**
- Consumes: `summarize(since: date) -> dict[str, dict[str, float]]` from
  `src/claude/eval/sizing_counterfactual.py` (keys `<kind>:<split>` or `claude_overrides`; a
  `cc_breakout_floor:pushed_out` entry carries `count` only), `Envelope`, `OwnerUser`.
- Produces: `GET /pnl/sizing?since=YYYY-MM-DD` → `SizingRecordResponse{as_of, since, groups:
  SizingGroupOut[]}`; `SizingGroupOut{key, kind, split, count, contracts_withheld?, resolved?,
  exact?, pnl_expiry?, pnl_rules?, rules_missing?, applied?, unapplied?}`. Task 13 reads it.

- [x] **Step 1: Branch and worktree**

Run from the repo root:

```bash
git switch -c feat/web-overhaul-3
```

If executing in a separate worktree (superpowers:using-git-worktrees), symlink the main `.venv`
and `web/node_modules` into it and run `python -c "from src.storage.db import init_db; init_db()"`
(a fresh worktree otherwise fails four monitor tests with "no such table: fills").

- [x] **Step 2: Write the failing tests** — create `tests/test_api_pnl_sizing.py`:

```python
"""GET /pnl/sizing - the sizing record's totals (web overhaul Part 3, Task 1).

A thin renderer over src/claude/eval/sizing_counterfactual.py::summarize, read behind the eval
fence exactly as GET /pnl/system reads the score report: nothing is recomputed here, and the
route offers nothing that could change a limit, a size or a weight.
"""

from __future__ import annotations

from datetime import date, datetime

from src.claude.eval.sizing_counterfactual import summarize
from src.storage.models import OrderRow, SizingActionRow
from tests.conftest import OWNER

DAY = date(2026, 10, 20)


def _row(
    sym: str,
    kind: str,
    *,
    sent: int,
    wanted: int = 2,
    day: date = DAY,
    resolved: bool = False,
    expiry_pnl: float = 0.0,
    rules_pnl: float | None = 0.0,
    exact: float | None = None,
    reason: str = "stopped",
) -> SizingActionRow:
    return SizingActionRow(
        created_at=datetime(2026, 10, 20, 15, 0),
        candidate_id=f"c-{sym}-{kind}",
        record_key=f"csp:{sym}:{kind}:{day}",
        underlying=sym,
        strategy="cash_secured_put",
        right="P",
        strike=35.0,
        expiry=date(2026, 11, 13),
        premium=2.0,
        kind=kind,
        regime="stressed",
        deterministic_contracts=wanted,
        sent_contracts=sent,
        reason=reason,
        action_day=day,
        resolved_at=datetime(2026, 11, 14) if resolved else None,
        shadow_pnl_expiry=expiry_pnl if resolved else None,
        shadow_pnl_rules=rules_pnl if resolved else None,
        realized_pnl_per_contract=exact,
    )


def test_requires_owner(client) -> None:
    assert client.get("/pnl/sizing").status_code == 401


def test_an_empty_record_is_an_empty_list_not_an_error(client, api_db) -> None:
    r = client.get("/pnl/sizing", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["groups"] == [] and r.json()["since"] is None


def test_a_group_counts_every_row_and_values_only_the_resolved(client, api_db) -> None:
    with api_db() as s:
        s.add_all(
            [
                _row("ASTS", "scale_in_zone", sent=0, resolved=True, expiry_pnl=120.0, rules_pnl=80.0),
                _row("NVDA", "scale_in_zone", sent=0),
            ]
        )
    (g,) = client.get("/pnl/sizing", headers=OWNER).json()["groups"]
    assert (g["key"], g["kind"], g["split"]) == (
        "scale_in_zone:never_sent",
        "scale_in_zone",
        "never_sent",
    )
    assert (g["count"], g["contracts_withheld"], g["resolved"], g["exact"]) == (2, 4, 1, 0)
    assert (g["pnl_expiry"], g["pnl_rules"], g["rules_missing"]) == (120.0, 80.0, 0)
    assert g["applied"] is None and g["unapplied"] is None


def test_a_row_that_traded_smaller_is_its_own_group_and_may_lack_a_rules_mark(
    client, api_db
) -> None:
    with api_db() as s:
        s.add(
            _row(
                "AMD",
                "loss_exit_cooldown",
                sent=1,
                resolved=True,
                expiry_pnl=-30.0,
                rules_pnl=None,
                exact=-15.0,
            )
        )
    (g,) = client.get("/pnl/sizing", headers=OWNER).json()["groups"]
    assert g["key"] == "loss_exit_cooldown:sent_smaller"
    assert (g["contracts_withheld"], g["exact"], g["rules_missing"]) == (1, 1, 1)
    assert (g["pnl_expiry"], g["pnl_rules"]) == (-30.0, 0.0)


def test_claudes_cuts_are_one_overrides_line_with_applied_and_unapplied_counts(
    client, api_db
) -> None:
    with api_db() as s:
        s.add_all(
            [
                _row("NVDA", "claude_cut", sent=1, wanted=3),
                _row("TSLA", "claude_cut_unapplied", sent=3, wanted=3, reason="Claude suggested 1"),
            ]
        )
    (g,) = client.get("/pnl/sizing", headers=OWNER).json()["groups"]
    assert (g["key"], g["kind"], g["split"]) == ("claude_overrides", "claude_cut", "overrides")
    assert (g["count"], g["applied"], g["unapplied"], g["contracts_withheld"]) == (2, 1, 1, 4)


def test_a_breakout_row_a_covered_call_replaced_is_counted_and_never_valued(client, api_db) -> None:
    with api_db() as s:
        s.add(
            OrderRow(
                candidate_id="cc1",
                state="filled",
                filled_qty=1.0,
                created_at=datetime(2026, 10, 20, 15, 0),
                snapshot={"underlying": "NVDA", "strategy": "covered_call"},
            )
        )
        s.add(_row("NVDA", "cc_breakout_floor", sent=0))
    (g,) = client.get("/pnl/sizing", headers=OWNER).json()["groups"]
    assert (g["key"], g["split"], g["count"]) == ("cc_breakout_floor:pushed_out", "pushed_out", 1)
    for field in ("contracts_withheld", "resolved", "exact", "pnl_expiry", "pnl_rules", "rules_missing"):
        assert g[field] is None, field


def test_since_leaves_out_older_actions_and_is_echoed_back(client, api_db) -> None:
    with api_db() as s:
        s.add_all(
            [
                _row("OLD", "scale_in_zone", sent=0, day=date(2026, 10, 1)),
                _row("NEW", "scale_in_zone", sent=0),
            ]
        )
    body = client.get("/pnl/sizing?since=2026-10-15", headers=OWNER).json()
    assert body["since"] == "2026-10-15"
    assert [g["count"] for g in body["groups"]] == [1]
    assert client.get("/pnl/sizing?since=not-a-date", headers=OWNER).status_code == 422


def test_groups_come_back_in_a_stable_order(client, api_db) -> None:
    with api_db() as s:
        s.add_all(
            [
                _row("A", "scale_in_zone", sent=0),
                _row("B", "loss_exit_cooldown", sent=0),
            ]
        )
    keys = [g["key"] for g in client.get("/pnl/sizing", headers=OWNER).json()["groups"]]
    assert keys == ["loss_exit_cooldown:never_sent", "scale_in_zone:never_sent"]


def test_the_route_does_not_recompute_the_summary(client, api_db, monkeypatch) -> None:
    """If the record is wrong, it is fixed in sizing_counterfactual.py, not in a router."""
    calls: list[date] = []

    def spy(since: date):
        calls.append(since)
        return summarize(since)

    monkeypatch.setattr("src.api.routers.pnl.summarize_sizing", spy)
    client.get("/pnl/sizing", headers=OWNER)
    assert calls == [date.min]


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/pnl/sizing", headers=OWNER).status_code == 403
```

- [x] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_api_pnl_sizing.py -q`
Expected: FAIL (every route test answers 404; the spy test fails on the missing attribute).

- [x] **Step 4: Add the models** — in `src/api/models/pnl.py`, directly after
  `SystemPerformanceResponse`:

```python
class SizingGroupOut(BaseModel):
    """One line of the sizing record: a kind of action and what it withheld, as
    ``src/claude/eval/sizing_counterfactual.py::summarize`` reports it (key ``<kind>:<split>``,
    or ``claude_overrides`` for Claude's cuts, whose ``kind`` is ``claude_cut``).

    A positive P&L is what the withheld contracts would have **earned**: the action cost that
    much (for ``regime_floor_lot`` the valued contracts are the lots the floor let through, so
    positive means letting them through paid). Rows not yet valued count in ``count`` and not
    in ``resolved``. A ``pushed_out`` line is counted and never valued, so its figures are None.
    """

    key: str
    kind: str
    split: str  # sent_smaller | never_sent | pushed_out | overrides
    count: int
    contracts_withheld: int | None = None
    resolved: int | None = None
    exact: int | None = None  # of the resolved, valued at the traded contract's realised P&L
    pnl_expiry: float | None = None
    pnl_rules: float | None = None
    rules_missing: int | None = None  # valued rows with no entry IV, left out of pnl_rules
    applied: int | None = None  # overrides only
    unapplied: int | None = None  # overrides only


class SizingRecordResponse(Envelope):
    """The sizing record, read by a human (the live-cutover gate's step 4). Display only."""

    since: date | None = None
    groups: list[SizingGroupOut]
```

- [x] **Step 5: Add the route** — in `src/api/routers/pnl.py`: add `SizingGroupOut` and
  `SizingRecordResponse` to the `src.api.models.pnl` import list (alphabetical), add
  `from src.claude.eval.sizing_counterfactual import summarize as summarize_sizing` beside the
  other `src.claude.eval` imports, and add after `pnl_system`:

```python
def _sizing_groups(summary: dict[str, dict[str, float]]) -> list[SizingGroupOut]:
    """`summarize`'s dict as ordered lines. A line without `pnl_expiry` is counted, not valued."""
    groups: list[SizingGroupOut] = []
    for key in sorted(summary):
        b = summary[key]
        if key == "claude_overrides":
            kind, split = "claude_cut", "overrides"
        else:
            kind, _, split = key.partition(":")
        valued = "pnl_expiry" in b
        groups.append(
            SizingGroupOut(
                key=key,
                kind=kind,
                split=split,
                count=int(b["count"]),
                contracts_withheld=int(b["contracts_withheld"]) if valued else None,
                resolved=int(b["resolved"]) if valued else None,
                exact=int(b["exact"]) if valued else None,
                pnl_expiry=round(b["pnl_expiry"], 2) if valued else None,
                pnl_rules=round(b["pnl_rules"], 2) if valued else None,
                rules_missing=int(b["rules_missing"]) if valued else None,
                applied=int(b["applied"]) if "applied" in b else None,
                unapplied=int(b["unapplied"]) if "unapplied" in b else None,
            )
        )
    return groups


@router.get("/sizing", response_model=SizingRecordResponse)
def pnl_sizing(
    user: OwnerUser,  # noqa: ARG001
    since: date | None = None,
) -> SizingRecordResponse:
    """What the regime limits, the scale-in ladder, the leveraged-ETF ceiling, the floor lots and
    Claude's size cut held back, and what that would have earned (web overhaul Part 3, Task 1).

    Reads behind the `src/claude/eval/` fence, like `/pnl/system`: this is the human reader
    `CLAUDE.md` says everything `eval/` produces is for. It calls `summarize` and returns what it
    gets, grouped and ordered; no figure is recomputed here, and nothing on the route can change a
    limit, a size or a weight. `since` is the first action day counted (default: every action on
    record). Rows not yet valued count and are not valued.
    """
    return SizingRecordResponse(
        as_of=datetime.now(UTC),
        since=since,
        groups=_sizing_groups(summarize_sizing(since or date.min)),
    )
```

- [x] **Step 6: Run the tests, then the fences**

Run: `python -m pytest tests/test_api_pnl_sizing.py tests/test_web_fence.py tests/test_eval_skills.py tests/test_regime_fence.py -q`
Expected: PASS (10 new tests; every fence test unchanged).

- [x] **Step 7: Regenerate the contract**

```bash
python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json
(cd web && npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts)
python -m pytest tests/test_openapi_current.py -q
```

Expected: PASS; `git diff --stat` shows `docs/web/openapi.json` and `web/lib/api-types.ts` changed
by the two new schemas and the new path only.

- [x] **Step 8: Format and the gate**

Run: `ruff format src/api/models/pnl.py src/api/routers/pnl.py tests/test_api_pnl_sizing.py`. These files
are formatted on `main`, so this changes only what this task wrote. Then
`python -m pytest -q && ruff check . && mypy src && cd web && npx tsc --noEmit && cd ..`
Expected: pytest = baseline + 10; everything else clean (the scan-timeout flake rule in A2 applies).

- [x] **Step 9: Commit** (with the Section A entry row and the Task 1 row of the Progress log filled in)

```bash
git add src/api/models/pnl.py src/api/routers/pnl.py tests/test_api_pnl_sizing.py \
  docs/web/openapi.json web/lib/api-types.ts docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(api): GET /pnl/sizing - the sizing record's totals, read behind the eval fence"
```

---

### Task 2: Orders say what shaped their size, and fills name their contract

**Files:**
- Modify: `src/api/models/options.py`, `src/api/routers/options.py`
- Modify: `tests/test_api_orders.py` (+9 tests)
- Modify: `web/components/options/types.ts` (hand-written mirrors)
- Modify: `docs/web/openapi.json`, `web/lib/api-types.ts` (both regenerated)

**Interfaces:**
- Consumes: `SizingActionRow.order_id` (set at send time by `regime.actions.link_order`),
  `OrderRow.snapshot`, `CandidateRow`, `FillRow`.
- Produces: `OrderSizingOut{kind, deterministic_contracts, sent_contracts, reason}`;
  `OrderSummary.sizing: OrderSizingOut[]` (empty when no action touched the order);
  `FillSummary.underlying | strategy | right | strike | expiry` (each `None` when neither the
  order's snapshot nor its candidate is on record, never `""` or `0`); `GET /options/orders` gains
  `days` (1 to 365); `GET /options/fills` takes `days` up to 365.
- Keeps: `state=working` is `queued` and `submitted` only. Since f4af002 (2026-10-27) a `partial`
  order is final (the executors cancel the rest at the fill timeout), so it is history, listed
  under `all` and `partial`, never `working`. The replacement code below keeps that line and its
  comment exactly; do not "restore" `partial` to `_WORKING`.

- [x] **Step 1: Write the failing tests** — append to `tests/test_api_orders.py` (the module's
  `client` fixture seeds orders 1 to 3 (`c1` NVDA submitted, `c2` AAPL filled with one fill, `c3`
  MSFT queued)). Add `SizingActionRow` to the `src.storage.models` import:

```python
def _sizing(order_id: int, kind: str, *, wanted: int, sent: int, reason: str = "") -> SizingActionRow:
    return SizingActionRow(
        created_at=datetime.now(UTC).replace(tzinfo=None),
        candidate_id="c2",
        record_key=f"c2-{kind}",
        underlying="AAPL",
        strategy="cash_secured_put",
        right="P",
        strike=185.0,
        expiry=_EXPIRY,
        premium=3.10,
        kind=kind,
        regime="stressed",
        deterministic_contracts=wanted,
        sent_contracts=sent,
        reason=reason,
        action_day=date.today(),
        order_id=order_id,
    )


def test_an_order_carries_the_sizing_action_that_shaped_it(client) -> None:
    with session_scope() as s:
        s.add(_sizing(2, "claude_cut", wanted=3, sent=1, reason="Claude suggested 1"))
    by_cid = {o["candidate_id"]: o for o in client.get("/options/orders?state=all", headers=AUTH).json()["orders"]}
    assert by_cid["c2"]["sizing"] == [
        {
            "kind": "claude_cut",
            "deterministic_contracts": 3,
            "sent_contracts": 1,
            "reason": "Claude suggested 1",
        }
    ]


def test_an_order_no_action_touched_has_an_empty_sizing_list(client) -> None:
    by_cid = {o["candidate_id"]: o for o in client.get("/options/orders?state=all", headers=AUTH).json()["orders"]}
    assert by_cid["c1"]["sizing"] == []


def test_two_actions_on_one_order_both_come_back_oldest_first(client) -> None:
    with session_scope() as s:
        s.add(_sizing(2, "regime_budget", wanted=3, sent=2))
        s.add(_sizing(2, "claude_cut", wanted=2, sent=1))
    by_cid = {o["candidate_id"]: o for o in client.get("/options/orders?state=all", headers=AUTH).json()["orders"]}
    assert [a["kind"] for a in by_cid["c2"]["sizing"]] == ["regime_budget", "claude_cut"]


def test_orders_can_be_windowed_by_days(client) -> None:
    with session_scope() as s:
        s.add(
            OrderRow(
                candidate_id="old",
                state="filled",
                filled_qty=1.0,
                is_live=False,
                snapshot=_snap(underlying="OLD"),
                created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30),
            )
        )
    week = {o["candidate_id"] for o in client.get("/options/orders?state=all&days=7", headers=AUTH).json()["orders"]}
    quarter = {o["candidate_id"] for o in client.get("/options/orders?state=all&days=90", headers=AUTH).json()["orders"]}
    assert "old" not in week and "old" in quarter
    assert client.get("/options/orders?days=0", headers=AUTH).status_code == 422
    assert client.get("/options/orders?days=366", headers=AUTH).status_code == 422


def test_a_fill_names_its_contract(client) -> None:
    (fill,) = client.get("/options/fills?days=7", headers=AUTH).json()["fills"]
    assert (fill["underlying"], fill["strategy"], fill["right"], fill["strike"]) == (
        "AAPL",
        "cash_secured_put",
        "P",
        185.0,
    )
    assert fill["expiry"] == _EXPIRY.isoformat()


def test_a_fill_falls_back_to_its_candidate_when_the_order_has_no_snapshot(client) -> None:
    with session_scope() as s:
        order = OrderRow(
            candidate_id="c1", state="filled", filled_qty=1.0, is_live=False, snapshot=None
        )
        s.add(order)
        s.flush()
        s.add(
            FillRow(
                order_id=order.id,
                candidate_id="c1",
                action="SELL",
                filled_qty=1.0,
                avg_price=3.25,
                is_live=False,
                filled_at=datetime.now(UTC),
            )
        )
    fills = client.get("/options/fills?days=7", headers=AUTH).json()["fills"]
    nvda = next(f for f in fills if f["candidate_id"] == "c1")
    assert (nvda["underlying"], nvda["strike"], nvda["right"]) == ("NVDA", 190.0, "P")


def test_a_fill_with_no_order_and_no_candidate_has_an_unknown_contract_not_a_zero(client) -> None:
    with session_scope() as s:
        s.add(
            FillRow(
                order_id=999,
                candidate_id="ghost",
                action="SELL",
                filled_qty=1.0,
                avg_price=1.0,
                is_live=False,
                filled_at=datetime.now(UTC),
            )
        )
    ghost = next(f for f in client.get("/options/fills?days=7", headers=AUTH).json()["fills"] if f["candidate_id"] == "ghost")
    for field in ("underlying", "strategy", "right", "strike", "expiry"):
        assert ghost[field] is None, field


def test_fills_reach_back_a_year_and_no_further(client) -> None:
    assert client.get("/options/fills?days=365", headers=AUTH).status_code == 200
    assert client.get("/options/fills?days=366", headers=AUTH).status_code == 422

def test_a_partial_order_is_history_not_working(client) -> None:
    """`partial` is final (the executors cancel the rest at the fill timeout, 2026-10-27): the
    rewritten route must keep it out of `working`, as the route it replaces did."""
    with session_scope() as s:
        s.add(
            OrderRow(
                candidate_id="half",
                state="partial",
                filled_qty=1.0,
                is_live=False,
                snapshot=_snap(underlying="HALF"),
            )
        )
    working = {o["candidate_id"] for o in client.get("/options/orders", headers=AUTH).json()["orders"]}
    every = {o["candidate_id"] for o in client.get("/options/orders?state=all", headers=AUTH).json()["orders"]}
    assert "half" not in working and "half" in every
```

- [x] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_api_orders.py -q`
Expected: 8 of the 9 new tests FAIL (no `sizing`, no contract fields, `days` ignored on orders,
and `/options/fills?days=365` answers 422 because the route caps `days` at 90 today).
`test_a_partial_order_is_history_not_working` already passes on `main` and must still pass after
Step 4: it guards f4af002's rule (a `partial` order is final, never `working`) that the
replacement route has to keep.

- [x] **Step 3: Models** — in `src/api/models/options.py`:

  Replace `class FillSummary(Envelope)` (the whole class) with:

```python
class FillSummary(Envelope):
    """One fill against an order. Defined here (ahead of Task 2.3's orders/fills section)
    because ``ApprovalDetail`` below references it for the approval-to-fill lineage.

    The contract fields (web overhaul Part 3) come from the order's frozen snapshot, then its
    candidate; each is ``None`` when neither is on record, never ``""`` or ``0``."""

    id: int
    order_id: int
    candidate_id: str
    action: str
    filled_qty: float
    avg_price: float
    commission: float | None = None
    is_live: bool
    filled_at: datetime
    underlying: str | None = None
    strategy: str | None = None
    right: Literal["C", "P"] | None = None
    strike: float | None = None
    expiry: date | None = None
```

  Directly above `class OrderSummary(Envelope)` add:

```python
class OrderSizingOut(BaseModel):
    """One sizing action linked to an order (``sizing_actions.order_id``): what the rules alone
    would have sent, what was sent, and the reason as it was recorded (web overhaul Part 3)."""

    kind: str
    deterministic_contracts: int
    sent_contracts: int
    reason: str = ""
```

  and add this field as the last line of `OrderSummary`:

```python
    sizing: list[OrderSizingOut] = Field(default_factory=list)
```

- [x] **Step 4: Routes** — in `src/api/routers/options.py` add `OrderSizingOut` to the
  `src.api.models.options` import list (alphabetical); the routes import the storage models
  lazily inside their bodies, as the originals do, so nothing else changes at module level. Then
  replace `list_orders` and `list_fills` (everything from `@router.get("/orders"` through the end
  of `list_fills`, leaving `_order_underlying_strategy_strike` above it as it is) with:

```python
def _contract_of(
    snap: dict[str, Any] | None, cand: Any | None
) -> tuple[str | None, str | None, Literal["C", "P"] | None, float | None, Any]:
    """Underlying / strategy / right / strike / expiry from the order's snapshot, then its
    candidate. Unknown stays ``None``: a fill must never claim a strike of 0."""
    snap = snap or {}

    def pick(key: str) -> Any:
        v = snap.get(key)
        return v if v is not None else (getattr(cand, key, None) if cand is not None else None)

    right = pick("right")
    return (
        pick("underlying") or None,
        pick("strategy") or None,
        _right_lit(right) if right else None,
        pick("strike"),
        pick("expiry"),
    )


@router.get("/orders", response_model=OrderListResponse)
def list_orders(
    _user: OwnerUser,
    db: TradingDb,
    state: Literal[
        "working", "all", "queued", "submitted", "filled", "partial", "cancelled", "rejected"
    ] = Query(
        default="working",
        description="`working` (queued/submitted), `all`, or a specific state.",
    ),
    days: int | None = Query(
        default=None, ge=1, le=365, description="Only orders created in the last N days."
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> OrderListResponse:
    """Working orders by default. ``state=all`` returns everything.

    An unknown state value is rejected with 422 (not a silent empty list). Each order carries
    the sizing actions linked to it (``sizing``), so an auditor can see why 1 contract went out
    when the scan said 3.
    """
    from src.storage.models import CandidateRow, OrderRow, SizingActionRow

    now = datetime.now(UTC)
    _WORKING = {"queued", "submitted"}  # `partial` is final: the executors cancel the rest

    stmt = select(OrderRow)
    if state == "working":
        stmt = stmt.where(OrderRow.state.in_(_WORKING))
    elif state != "all":
        # A specific state: validate by the literal above, then filter directly.
        stmt = stmt.where(OrderRow.state == state)
    if days is not None:
        stmt = stmt.where(OrderRow.created_at >= now - timedelta(days=days))
    stmt = stmt.order_by(OrderRow.created_at.desc()).limit(limit)

    orders = db.execute(stmt).scalars().all()
    if not orders:
        return OrderListResponse(as_of=now, orders=[])

    candidate_ids = {o.candidate_id for o in orders}
    cand_map: dict[str, Any] = {}
    if candidate_ids:
        cands = (
            db.execute(select(CandidateRow).where(CandidateRow.candidate_id.in_(candidate_ids)))
            .scalars()
            .all()
        )
        cand_map = {c.candidate_id: c for c in cands}

    sizing: dict[int, list[OrderSizingOut]] = {}
    for a in db.execute(
        select(SizingActionRow)
        .where(SizingActionRow.order_id.in_([o.id for o in orders]))
        .order_by(SizingActionRow.id)
    ).scalars():
        if a.order_id is None:
            continue
        sizing.setdefault(a.order_id, []).append(
            OrderSizingOut(
                kind=a.kind,
                deterministic_contracts=a.deterministic_contracts,
                sent_contracts=a.sent_contracts,
                reason=a.reason or "",
            )
        )

    out: list[OrderSummary] = []
    for o in orders:
        cand = cand_map.get(o.candidate_id)
        underlying, strategy, strike, expiry = _order_underlying_strategy_strike(o.snapshot, cand)
        # avg_fill_price is null for an unfilled order, never 0.0. The row's column
        # is nullable; a fabricated zero would read as real to an operator.
        avg_fill = o.avg_fill_price if o.avg_fill_price is not None else None
        out.append(
            OrderSummary(
                as_of=now,
                id=o.id,
                candidate_id=o.candidate_id,
                approval_id=o.approval_id,
                underlying=underlying,
                strategy=strategy,
                strike=strike,
                expiry=expiry,
                state=o.state,  # type: ignore[arg-type]
                limit_price=o.limit_price,
                filled_qty=o.filled_qty if o.filled_qty is not None else 0.0,
                avg_fill_price=avg_fill,
                is_live=bool(o.is_live),
                detail=o.detail,
                created_at=as_utc_opt(o.created_at) or now,
                updated_at=as_utc_opt(o.updated_at) or now,
                sizing=sizing.get(o.id, []),
            )
        )
    return OrderListResponse(as_of=now, orders=out)


@router.get("/fills", response_model=FillListResponse)
def list_fills(
    _user: OwnerUser,
    db: TradingDb,
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=500),
) -> FillListResponse:
    """Recent fills within the last ``days`` days, each naming its contract (from the order's
    frozen snapshot, then its candidate; unknown stays null)."""
    from src.storage.models import CandidateRow, FillRow, OrderRow

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    rows = (
        db.execute(
            select(FillRow)
            .where(FillRow.filled_at >= cutoff)
            .order_by(FillRow.filled_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    order_map = {
        o.id: o
        for o in db.execute(select(OrderRow).where(OrderRow.id.in_({r.order_id for r in rows})))
        .scalars()
        .all()
    }
    cand_map = {
        c.candidate_id: c
        for c in db.execute(
            select(CandidateRow).where(CandidateRow.candidate_id.in_({r.candidate_id for r in rows}))
        )
        .scalars()
        .all()
    }
    fills: list[FillSummary] = []
    for r in rows:
        order = order_map.get(r.order_id)
        underlying, strategy, right, strike, expiry = _contract_of(
            order.snapshot if order is not None else None, cand_map.get(r.candidate_id)
        )
        fills.append(
            FillSummary(
                as_of=now,
                id=r.id,
                order_id=r.order_id,
                candidate_id=r.candidate_id,
                action=r.action,
                filled_qty=r.filled_qty,
                avg_price=r.avg_price,
                commission=r.commission,
                is_live=bool(r.is_live),
                filled_at=as_utc_opt(r.filled_at) or now,
                underlying=underlying,
                strategy=strategy,
                right=right,
                strike=strike,
                expiry=expiry,
            )
        )
    return FillListResponse(as_of=now, fills=fills)
```

- [x] **Step 5: Hand-written mirrors** — in `web/components/options/types.ts`, add to `OrderSummary`
  the line `sizing?: OrderSizing[];` after `updated_at: string;`, add to `FillSummary` the lines
  `underlying?: string | null; strategy?: string | null; right?: "C" | "P" | null; strike?: number | null; expiry?: string | null;`
  after `filled_at: string;`, and add above `OrderSummary`:

```ts
/** A sizing action linked to an order (src/api/models/options.py OrderSizingOut). */
export type OrderSizing = {
  kind: string;
  deterministic_contracts: number;
  sent_contracts: number;
  reason: string;
};
```

- [x] **Step 6: Run the tests, then regenerate the contract**

```bash
python -m pytest tests/test_api_orders.py tests/test_api_approvals.py tests/test_openapi_current.py -q
python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json
(cd web && npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts)
python -m pytest tests/test_openapi_current.py -q
```

Expected: PASS (every existing orders, fills and approval-detail test unchanged, plus the 9 new
ones); the contract diff adds `OrderSizingOut`, the `sizing` and contract fields, and the
`days` parameter.

- [x] **Step 7: Format and the gate**

Run: `ruff format src/api/models/options.py src/api/routers/options.py tests/test_api_orders.py`, then
`python -m pytest -q && ruff check . && mypy src && cd web && npx vitest run && npx tsc --noEmit && npm run lint && cd ..`
Expected: pytest = Task 1's count + 9; vitest unchanged; everything else clean.

- [x] **Step 8: Commit**

```bash
git add src/api/models/options.py src/api/routers/options.py tests/test_api_orders.py \
  web/components/options/types.ts docs/web/openapi.json web/lib/api-types.ts
git commit -m "feat(api): orders carry the sizing that shaped them; fills name their contract"
```

---

### Task 3: IBKR's executions and the spreads book's filled orders

**Files:**
- Modify: `src/api/models/ledger.py`, `src/api/routers/ledger.py`
- Modify: `src/api/spreads_db.py`, `src/api/models/spreads.py`, `src/api/routers/spreads.py`
- Modify: `tests/test_api_ledger.py` (+5); Create: `tests/test_api_spread_orders.py`
- Modify: `docs/web/openapi.json`, `web/lib/api-types.ts` (both regenerated)

**Interfaces:**
- Consumes: `BrokerExecutionRow` (`source_kind == "exec"`, `superseded_by is None`, `trade_date`
  in US/Eastern), `LedgerBookName`, `spreads_read_session()`, `_columns_of`/`_stamp` helpers in
  `spreads_db.py`.
- Produces:
  - `GET /ledger/executions?days=30&book=&symbol=&limit=200` →
    `LedgerExecutionsResponse{as_of, days, limit, truncated, executions: LedgerExecutionRowOut[]}`
    (`LedgerExecutionRowOut{id, source, exec_id, trade_time (UTC), trade_date, underlying,
    sec_type, right, strike, expiry, multiplier, currency, quantity (signed: bought +, sold −),
    price, proceeds, commission, codes, book, ib_order_id, perm_id}`).
  - `try_read_spread_order_rows(session, *, start: datetime, limit: int) -> list[dict] | None`
    (newest first, each row joined to its position for `mode`, `side`, `expiry`, strikes).
  - `GET /spreads/orders?days=30&limit=200` → `SpreadOrdersResponse{as_of, available,
    underlying, orders: SpreadOrderOut[]}`.

- [x] **Step 1: Write the failing ledger tests** — append to `tests/test_api_ledger.py`. Add
  `from datetime import UTC, date, datetime` to its imports. The `seeded` CSV fixture only loads
  order-level statement rows, which is the exclusion case:

```python
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)


def _exec(n: int, **over):
    from src.storage.models import BrokerExecutionRow

    base = dict(
        dedupe_key=f"live-{n}",
        source_kind="exec",
        source="live",
        exec_id=f"0000{n}",
        perm_id=900 + n,
        ib_order_id=10 + n,
        account="DU1",
        trade_time=datetime(2026, 10, 20, 14, 31, 7),
        trade_date=date(2026, 10, 20),
        contract_ident="NVDA 20261120 165 P",
        underlying="NVDA",
        sec_type="OPT",
        right="P",
        strike=165.0,
        expiry=date(2026, 11, 20),
        multiplier=100.0,
        currency="USD",
        quantity=-1.0,
        price=2.35,
        proceeds=235.0,
        commission=-1.3,
        codes="O",
        book="system",
    )
    base.update(over)
    return BrokerExecutionRow(**base)


@pytest.fixture()
def frozen_ledger_now(monkeypatch):
    import src.api.routers.ledger as routes

    monkeypatch.setattr(routes, "_now", lambda: NOW)


def test_executions_require_owner(client) -> None:
    assert client.get("/ledger/executions").status_code == 401


def test_executions_list_real_fills_newest_first_with_their_contract(
    client, api_db, frozen_ledger_now
) -> None:
    with api_db() as s:
        s.add_all(
            [
                _exec(1, trade_time=datetime(2026, 10, 19, 14, 0), trade_date=date(2026, 10, 19)),
                _exec(2, quantity=1.0, price=1.1, proceeds=-110.0, codes="C"),
            ]
        )
    body = client.get("/ledger/executions", headers=OWNER).json()
    assert [e["exec_id"] for e in body["executions"]] == ["00002", "00001"]
    first = body["executions"][0]
    assert (first["underlying"], first["right"], first["strike"], first["expiry"]) == (
        "NVDA",
        "P",
        165.0,
        "2026-11-20",
    )
    assert (first["quantity"], first["price"], first["commission"], first["book"]) == (1.0, 1.1, -1.3, "system")
    assert first["trade_time"].endswith(("Z", "+00:00"))
    assert (body["days"], body["limit"], body["truncated"]) == (30, 200, False)


def test_executions_leave_out_statement_rows_superseded_twins_and_old_days(
    client, api_db, frozen_ledger_now
) -> None:
    with api_db() as s:
        s.add_all(
            [
                _exec(1),
                _exec(2, source_kind="order"),
                _exec(3, superseded_by=1),
                _exec(4, trade_date=date(2026, 8, 1), trade_time=datetime(2026, 8, 1, 14, 0)),
            ]
        )
    ids = [e["exec_id"] for e in client.get("/ledger/executions", headers=OWNER).json()["executions"]]
    assert ids == ["00001"]
    wide = client.get("/ledger/executions?days=120", headers=OWNER).json()["executions"]
    assert {e["exec_id"] for e in wide} == {"00001", "00004"}


def test_executions_filter_by_book_and_symbol(client, api_db, frozen_ledger_now) -> None:
    with api_db() as s:
        s.add_all(
            [
                _exec(1),
                _exec(2, book="spreads", underlying="SPY", contract_ident="SPY 20261022 763 P"),
                _exec(3, book="manual", underlying="AAPL", contract_ident="AAPL 20261120 185 P"),
            ]
        )
    spreads = client.get("/ledger/executions?book=spreads", headers=OWNER).json()["executions"]
    assert [e["underlying"] for e in spreads] == ["SPY"]
    aapl = client.get("/ledger/executions?symbol=aapl", headers=OWNER).json()["executions"]
    assert [e["book"] for e in aapl] == ["manual"]
    assert client.get("/ledger/executions?book=bogus", headers=OWNER).status_code == 422


def test_executions_say_when_the_list_was_cut_short(client, api_db, frozen_ledger_now) -> None:
    with api_db() as s:
        s.add_all([_exec(n) for n in range(1, 5)])
    body = client.get("/ledger/executions?limit=3", headers=OWNER).json()
    assert len(body["executions"]) == 3 and body["truncated"] is True
    assert client.get("/ledger/executions?limit=0", headers=OWNER).status_code == 422
    assert client.get("/ledger/executions?days=366", headers=OWNER).status_code == 422
```

- [x] **Step 2: Write the failing spreads tests** — create `tests/test_api_spread_orders.py`:

```python
"""GET /spreads/orders - the spreads book's filled orders (web overhaul Part 3, Task 3).

Read-only over data/spreads.db through src/api/spreads_db.py (the API may not import
src.spreads). The tests may import the spreads models to build a real schema.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.conftest import OWNER

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)


@pytest.fixture()
def spreads_file(tmp_path, monkeypatch):
    import src.api.routers.spreads as routes
    import src.api.spreads_db as sdb

    path = tmp_path / "spreads.db"
    monkeypatch.setattr(sdb, "_resolve_path", lambda: str(path))
    monkeypatch.setattr(routes, "_now", lambda: NOW)
    sdb.reset_engine()
    yield path
    sdb.reset_engine()


def _make_db(path, *, orders=(), positions=(), with_orders_table: bool = True) -> None:
    from src.spreads.store import SpreadOrderRow, SpreadPositionRow, SpreadsBase

    eng = create_engine(f"sqlite:///{path}")
    if with_orders_table:
        SpreadsBase.metadata.create_all(eng)
    else:
        SpreadPositionRow.__table__.create(eng)
    with Session(eng) as s:
        for p in positions:
            s.add(SpreadPositionRow(**p))
        for o in orders:
            s.add(SpreadOrderRow(**o))
        s.commit()
    eng.dispose()


def _position(**over) -> dict:
    base = dict(
        spread_id="20261015-P762-757-101726",
        mode="paper",
        side="put",
        expiry=date(2026, 10, 15),
        short_strike=762.0,
        long_strike=757.0,
        width=5.0,
        contracts_opened=2,
        contracts=0,
        entry_credit=0.25,
        entry_commission=2.6,
        opened_at=datetime(2026, 10, 15, 13, 46),
        status="closed",
    )
    base.update(over)
    return base


def _order(kind: str, at: datetime, **over) -> dict:
    base = dict(
        spread_id="20261015-P762-757-101726",
        kind=kind,
        order_ref=f"ref-{kind}",
        ib_order_id=11,
        perm_id=4001,
        filled_qty=2,
        price=0.25 if kind == "open" else 0.05,
        commission=2.6,
        reason=None if kind == "open" else "profit_take",
        created_at=at,
    )
    base.update(over)
    return base


def test_requires_owner(client, spreads_file) -> None:
    assert client.get("/spreads/orders").status_code == 401


def test_no_file_is_unavailable_not_an_error(client, spreads_file) -> None:
    body = client.get("/spreads/orders", headers=OWNER).json()
    assert body["available"] is False and body["orders"] == []
    assert isinstance(body["underlying"], str)


def test_orders_come_back_newest_first_with_their_spread(client, spreads_file) -> None:
    _make_db(
        spreads_file,
        positions=[_position()],
        orders=[
            _order("open", datetime(2026, 10, 15, 13, 46, 24)),
            _order("close", datetime(2026, 10, 15, 14, 33, 50)),
        ],
    )
    body = client.get("/spreads/orders", headers=OWNER).json()
    assert body["available"] is True
    assert [o["kind"] for o in body["orders"]] == ["close", "open"]
    close = body["orders"][0]
    assert (close["mode"], close["side"], close["short_strike"], close["long_strike"]) == (
        "paper",
        "put",
        762.0,
        757.0,
    )
    assert (close["filled_qty"], close["price"], close["commission"], close["reason"]) == (
        2,
        0.05,
        2.6,
        "profit_take",
    )
    assert close["expiry"] == "2026-10-15"
    # Stored naive UTC leaves the API with an offset, so a browser never reads it as local time.
    assert close["created_at"].endswith(("Z", "+00:00"))


def test_an_order_whose_spread_is_missing_still_lists_with_unknown_strikes(client, spreads_file) -> None:
    _make_db(spreads_file, orders=[_order("open", datetime(2026, 10, 15, 13, 46))])
    (o,) = client.get("/spreads/orders", headers=OWNER).json()["orders"]
    for field in ("mode", "side", "expiry", "short_strike", "long_strike"):
        assert o[field] is None, field


def test_days_leaves_out_older_orders_and_limit_caps_the_list(client, spreads_file) -> None:
    _make_db(
        spreads_file,
        positions=[_position()],
        orders=[
            _order("open", datetime(2026, 9, 1, 13, 46)),
            _order("open", datetime(2026, 10, 15, 13, 46), order_ref="a"),
            _order("close", datetime(2026, 10, 15, 14, 33), order_ref="b"),
        ],
    )
    assert len(client.get("/spreads/orders?days=7", headers=OWNER).json()["orders"]) == 2
    assert len(client.get("/spreads/orders?days=60", headers=OWNER).json()["orders"]) == 3
    assert len(client.get("/spreads/orders?days=60&limit=1", headers=OWNER).json()["orders"]) == 1
    assert client.get("/spreads/orders?days=0", headers=OWNER).status_code == 422


def test_an_older_file_without_the_orders_table_is_available_with_no_orders(client, spreads_file) -> None:
    _make_db(spreads_file, positions=[_position()], with_orders_table=False)
    body = client.get("/spreads/orders", headers=OWNER).json()
    assert body["available"] is True and body["orders"] == []
```

- [x] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_api_ledger.py tests/test_api_spread_orders.py -q`
Expected: FAIL (both new routes answer 404).

- [x] **Step 4: Ledger models** — append to `src/api/models/ledger.py` (the file already imports
  `date`, `datetime`, `BaseModel` and `Envelope`):

```python
class LedgerExecutionRowOut(BaseModel):
    """One real IBKR execution (web overhaul Part 3): quantity is signed (bought +, sold −),
    ``trade_time`` is UTC, ``trade_date`` the US/Eastern day. ``right`` is ``C`` or ``P`` for an
    option and None for shares."""

    id: int
    source: str  # live | flex | csv
    exec_id: str | None
    trade_time: datetime
    trade_date: date
    underlying: str
    sec_type: str
    right: str | None
    strike: float | None
    expiry: date | None
    multiplier: float
    currency: str
    quantity: float
    price: float
    proceeds: float
    commission: float
    codes: str
    book: str  # system | manual | spreads
    ib_order_id: int | None
    perm_id: int | None


class LedgerExecutionsResponse(Envelope):
    days: int
    limit: int
    truncated: bool  # more executions exist in the window than were returned
    executions: list[LedgerExecutionRowOut]
```

- [x] **Step 5: Ledger route** — in `src/api/routers/ledger.py`: change the datetime import to
  `from datetime import UTC, date, datetime, timedelta`, the fastapi import to
  `from fastapi import APIRouter, HTTPException, Query`, add `LedgerExecutionRowOut` and
  `LedgerExecutionsResponse` to the `src.api.models.ledger` import list, add
  `from src.api.models.common import as_utc` directly after `from src.api.deps import OwnerUser, TradingDb`
  (the import sort puts it before the `models.ledger` block), and add after
  `get_trade` (before `/trades.csv` is fine, anywhere among the routes):

```python
@router.get("/executions", response_model=LedgerExecutionsResponse)
def get_executions(
    db: TradingDb,
    _user: OwnerUser,
    days: int = Query(default=30, ge=1, le=365),
    book: LedgerBookName | None = None,
    symbol: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> LedgerExecutionsResponse:
    """IBKR's own executions, newest first: the ledger rows that are real fills (``exec``, not an
    order-level statement row) and are not superseded by a twin from a higher-priority feed.
    ``days`` counts US/Eastern trade days back from today; ``truncated`` says the window held
    more than ``limit``. Read-only, like every ledger route (web overhaul Part 3)."""
    now = _now()
    since = (now.astimezone(_ET) - timedelta(days=days)).date()
    stmt = select(BrokerExecutionRow).where(
        BrokerExecutionRow.source_kind == "exec",
        BrokerExecutionRow.superseded_by.is_(None),
        BrokerExecutionRow.trade_date >= since,
    )
    if book is not None:
        stmt = stmt.where(BrokerExecutionRow.book == book)
    if symbol:
        stmt = stmt.where(BrokerExecutionRow.underlying == symbol.upper())
    rows = (
        db.execute(
            stmt.order_by(BrokerExecutionRow.trade_time.desc(), BrokerExecutionRow.id.desc()).limit(
                limit + 1
            )
        )
        .scalars()
        .all()
    )
    return LedgerExecutionsResponse(
        as_of=now,
        days=days,
        limit=limit,
        truncated=len(rows) > limit,
        executions=[
            LedgerExecutionRowOut(
                id=r.id,
                source=r.source,
                exec_id=r.exec_id,
                trade_time=as_utc(r.trade_time),
                trade_date=r.trade_date,
                underlying=r.underlying,
                sec_type=r.sec_type,
                right=r.right,
                strike=r.strike,
                expiry=r.expiry,
                multiplier=r.multiplier,
                currency=r.currency,
                quantity=r.quantity,
                price=r.price,
                proceeds=r.proceeds,
                commission=r.commission,
                codes=r.codes,
                book=r.book,
                ib_order_id=r.ib_order_id,
                perm_id=r.perm_id,
            )
            for r in rows[:limit]
        ],
    )
```

  `LedgerBookName` is already imported in this module (it is used by `_filters`).

- [x] **Step 6: Spreads reader** — append to `src/api/spreads_db.py`:

```python
def try_read_spread_order_rows(
    session: Session, *, start: datetime, limit: int
) -> list[dict[str, Any]] | None:
    """spread_orders rows created at or after *start* (naive UTC, as stored), newest first, each
    joined to its position for `mode`, `side`, `expiry` and the strikes (None when the position
    row is missing), or None when the read failed (an older file without the table)."""
    sql = text(
        "SELECT o.id, o.spread_id, o.kind, o.ib_order_id, o.perm_id, o.filled_qty, o.price, "
        "o.commission, o.reason, o.created_at, p.mode, p.side, p.expiry, p.short_strike, "
        "p.long_strike FROM spread_orders o LEFT JOIN spread_positions p "
        "ON p.spread_id = o.spread_id WHERE o.created_at >= :start "
        "ORDER BY o.created_at DESC, o.id DESC LIMIT :limit"
    ).columns(created_at=DateTime, expiry=Date)
    try:
        result = session.execute(sql, {"start": _stamp(start), "limit": limit})
    except Exception as exc:  # noqa: BLE001 - the caller decides what unreadable means
        log.debug("api spreads_db: order read failed: %s", exc)
        session.rollback()
        return None
    return [dict(r._mapping) for r in result]
```

- [x] **Step 7: Spreads models and route** — append to `src/api/models/spreads.py`:

```python
class SpreadOrderOut(BaseModel):
    """One filled order of the credit-spreads book (``spread_orders``: only filled orders are
    recorded), joined to its spread. The spread's fields are None when its position row is
    missing."""

    spread_id: str
    kind: Literal["open", "close"]
    ib_order_id: int | None
    perm_id: int | None
    filled_qty: int
    price: float | None  # per share; None when no price was recorded
    commission: float
    reason: str | None  # why a close was sent (profit take, stop, expiry...)
    created_at: datetime
    mode: str | None
    side: Literal["put", "call"] | None
    expiry: date | None
    short_strike: float | None
    long_strike: float | None


class SpreadOrdersResponse(Envelope):
    available: bool  # False when data/spreads.db does not exist or cannot be read
    underlying: str
    orders: list[SpreadOrderOut] = Field(default_factory=list)
```

  In `src/api/routers/spreads.py`: add `SpreadOrderOut` and `SpreadOrdersResponse` to the
  `src.api.models.spreads` import list, `try_read_spread_order_rows` to the `src.api.spreads_db`
  import list, and append the route:

```python
@router.get("/orders", response_model=SpreadOrdersResponse)
def spread_orders(
    user: OwnerUser,  # noqa: ARG001
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(200, ge=1, le=500),
) -> SpreadOrdersResponse:
    """The book's filled orders, newest first (web overhaul Part 3). An older file without the
    table answers ``available: true`` with no orders, as `/spreads/picks` does for the picker;
    only a missing or unreadable file is ``available: false``."""
    now = _now()
    underlying = get_config().spreads.underlying
    with spreads_read_session() as s:
        if s is None:
            return SpreadOrdersResponse(as_of=now, available=False, underlying=underlying)
        rows = try_read_spread_order_rows(
            s, start=(now - timedelta(days=days)).replace(tzinfo=None), limit=limit
        )
    orders = [
        SpreadOrderOut(
            spread_id=r["spread_id"],
            kind=r["kind"],
            ib_order_id=r["ib_order_id"],
            perm_id=r["perm_id"],
            filled_qty=r["filled_qty"],
            price=r["price"],
            commission=r["commission"],
            reason=r["reason"],
            created_at=as_utc(r["created_at"]),
            mode=r["mode"],
            side=r["side"],
            expiry=r["expiry"],
            short_strike=r["short_strike"],
            long_strike=r["long_strike"],
        )
        for r in (rows or [])
    ]
    return SpreadOrdersResponse(as_of=now, available=True, underlying=underlying, orders=orders)
```

- [x] **Step 8: Run the tests, the fences, then regenerate the contract**

```bash
python -m pytest tests/test_api_ledger.py tests/test_api_spread_orders.py tests/test_web_fence.py \
  tests/test_spreads_fence.py tests/test_wheel_spreads_isolation.py -q
python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json
(cd web && npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts)
python -m pytest tests/test_openapi_current.py -q
```

Expected: PASS (5 + 6 new tests; every fence test unchanged, including
`test_only_spreads_db_opens_the_spreads_file_in_the_api` and
`test_only_the_ledger_package_writes_the_ledger_tables`).

- [x] **Step 9: Format and the gate**

Run: `ruff format src/api/models/ledger.py src/api/routers/ledger.py src/api/spreads_db.py src/api/models/spreads.py src/api/routers/spreads.py tests/test_api_ledger.py tests/test_api_spread_orders.py`,
then `python -m pytest -q && ruff check . && mypy src && cd web && npx vitest run && npx tsc --noEmit && npm run lint && cd ..`
Expected: pytest = Task 2's count + 11; everything else clean.

- [x] **Step 10: Commit**

```bash
git add src/api/models/ledger.py src/api/routers/ledger.py src/api/spreads_db.py \
  src/api/models/spreads.py src/api/routers/spreads.py tests/test_api_ledger.py \
  tests/test_api_spread_orders.py docs/web/openapi.json web/lib/api-types.ts
git commit -m "feat(api): GET /ledger/executions and GET /spreads/orders - the audit lists"
```

---

## Section B — Portfolio (Tasks 4–7) · model: sonnet (effort xhigh)

The Portfolio surface contract goes into `web/DESIGN.md` first (with Activity's), then the
Account card, Positions, Campaigns, Calendar and the page. Every new component is a client
component under `web/features/portfolio/`; the two restyles (`DegradedNotice`, `RefreshControl`)
change classes only.

**Entry checks (run before Task 4):**

- [ ] **B1. Section A landed.** `git log --oneline main..HEAD` shows three commits (plus any
  review fix passes recorded in the Progress log); Tasks 1–3 are ticked.
- [ ] **B2. Gates green.** `python -m pytest -q && ruff check . && mypy src` and
  `cd web && npx vitest run && npx tsc --noEmit && npm run lint`.
- [ ] **B3. The contract carries the new shapes.** This prints nothing:

  ```bash
  for n in SizingRecordResponse SizingGroupOut OrderSizingOut LedgerExecutionsResponse \
    LedgerExecutionRowOut SpreadOrdersResponse SpreadOrderOut; do
    grep -q "$n" web/lib/api-types.ts || echo "MISSING $n"; done
  ```

- [ ] **B4. The pieces Section B builds on exist.** Each command prints at least one line:

  ```bash
  grep -n "export function FigureLines" web/features/claude-context/FigureLines.tsx
  grep -n "export function NameFlags" web/features/market/NameFlags.tsx
  grep -n "export function useClaudeContext" web/features/claude-context/useClaudeContext.ts
  grep -n "export function buildPositionRows\|export function matchesQuery\|export function optionStatus" web/features/home/positions.ts
  grep -n "export function todayInNewYork\|export function shiftDay" web/features/trades/time.ts
  grep -n "visible.map" web/features/home/PositionsCard.tsx
  ```

- [ ] **B5. Nothing in features sends a command itself.** `grep -rn "submitCommand\|confirmCommand" web/features`
  prints only `web/features/more/TargetCard.tsx` and `web/features/more/TargetCard.test.tsx`.

**Section exit:** four commits; `/portfolio` is the new page; the legacy shell is unmounted and
its tests still pass.

---

### Task 4: The Portfolio and Activity contracts, the Account card, and two small restyles

**Files:**
- Modify: `web/DESIGN.md` (the Portfolio and Activity surface entries)
- Create: `web/lib/useViewParam.ts`, `web/lib/useViewParam.test.tsx`
- Create: `web/features/portfolio/SummaryCard.tsx`, `web/features/portfolio/SummaryCard.test.tsx`
- Modify: `web/components/portfolio/DegradedNotice.tsx`, `web/components/portfolio/RefreshControl.tsx` (classes only)

**Interfaces:**
- Consumes: `Card`, `Button`, `StatusWord`, `FigureLines`/`FigureRow`, `FreshnessLabel`,
  `DegradedNotice`, `FRESH_FOR_MINUTES` (`features/home/positions.ts`), `formatMoneyCell`,
  `isStale`, `PortfolioSummaryResponse`/`AccountBlock`/`ExposureBlock`/`SourcedFloat`
  (`components/portfolio/types.ts`).
- Produces: `useViewParam<T extends string>(views: readonly T[], fallback: T): [T, (v: T) => void]`
  (Tasks 7 and 14); `SummaryCard()` (Task 7), reading `GET /portfolio/summary` under the query key
  `["portfolio", "summary"]`.

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: Operate surface, the
  payslip world, no new colour, font, radius, elevation or token; the Account card is a white
  card with two blocks of figure lines under a perforation; Delayed is the flag word.

- [x] **Step 2: Write the two surface contracts into `web/DESIGN.md`.** Replace these lines:

```markdown
### Portfolio
Operate. Positions, Campaigns, Expiry calendar. Position rows as on Home; "Propose a roll" moves
onto the short-option rows.

### Activity
Operate. Pay (P&L summary and equity curve), Ledger, Fills and orders, System (score-vs-outcome).
Ledger and stubs use the figure face.
```

with:

```markdown
### Portfolio
Operate. Dials as the project default. Built in web overhaul Part 3
(docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md).
- **THESIS:** what you hold, name by name, and how old that reading is. Home is the glance; this
  page is the register. Refuses the brokerage positions grid: a name is a card with its shares,
  its contracts as the rows Home shows, and one total that never hides a figure we do not have.
- **OWN-WORLD:** the payslip. Sage paper, white cards, rows without table chrome, the account in
  figure lines under a perforation. Lime only on an "Expires today" word. A figure we do not have
  is a hatched n/a, and a total over a missing figure is n/a, not the rest added up.
- **STORY:** how fresh is this reading and what is the account (the Account card); what do I hold
  (Positions); how did each wheel go (Campaigns); what expires when, and what happens then
  (Calendar).
- **FIRST VIEWPORT:** the title with Refresh at its right; the Account card (the age of the
  reading in words, a Delayed word when it is older than 30 minutes or degraded, the API's note
  verbatim, then the account and the exposure as two blocks of figure lines, side by side from
  640px); the view chips (Positions, Campaigns, Calendar); then the view. A phone is one column in
  that order.
- **FORM:** one page; the view lives in the URL (`?view=campaigns`). Positions: a search field,
  the type chips (All, CSPs, CCs, Credit spreads, Shares) with counts, then one card per name,
  two columns from 1024px: the ticker bold with its flag words ("Weak health", "Event <date>")
  and the name's open P&L at the right, then Home's rows (shares, then each option contract, each
  a link to the contract's page) with a muted figure line beneath each option (delta and where it
  came from, the mark, the value). Credit spreads are one more card. Campaigns: Status chips
  (All, Open, Closed), a labelled Symbol field, then one card per thread: the symbol, a status
  word, the net premium labelled "before commissions", the legs behind a disclosure; an assigned
  thread adds its adjusted cost basis and realised stock P&L. Calendar: horizon chips (14 to 180
  days), then one card per expiry day (the date and the days left), each contract a row with its
  moneyness and what happens at expiry in a sentence.
- **FINISH:** unreviewed and undocumented is unfinished.
- **Market picture (2026-10-23):** each name carries the same "Weak health" and near "Event
  <date>" words it has on Home. A short option whose name has a verified event date before its
  expiry carries "Event <date> before expiry" on the Calendar. The date is Python's (checked
  against the cited news); the event's title is Claude's and is not shown here.

### Activity
Operate. Dials as the project default. Built in web overhaul Part 3. Ledger and stub figures use
the figure face.
- **THESIS:** what the money did, and whether the records agree. Pay answers what the account
  earned; Ledger what IBKR says happened; Fills and orders what the system sent, what it recorded
  as filled and what IBKR executed, in three lists that are never merged; System how the scoring
  and the size limits have done. Refuses a single merged feed: the sources can disagree, and
  seeing that is the audit.
- **OWN-WORLD:** the payslip, read as a ledger. Stubs for months, hairline rows in the figure
  face for lists, no table chrome on phones, a labelled source on every list ("The system's
  record", "At IBKR"), words for states. Lime only on the pay meter. Nothing here is an action
  except the filters, the month stepper, the CSV links and the statement import (its own page).
- **STORY:** what did I earn this month and since the start (Pay); what does the broker ledger say
  (Ledger); what was sent, what filled, what IBKR executed (Fills and orders); how have the score
  and the size limits paid (System).
- **FIRST VIEWPORT:** the title and the view chips (Pay, Ledger, Fills and orders, System). Pay:
  the month stepper (previous, the month, next, "This month"), the month's stub open (premium
  collected, bought back, commissions, net so far, the pay meter when a target is set), then the
  record since the system began, the equity curve and the legs.
- **FORM:** one page; the view in `?view=`, the Pay month in `?month=YYYY-MM`. Ledger: the ledger's
  overview (tiles as figure lines, the two charts, the tables by strategy, book and ticker, upcoming
  expiries) with links to its Trades and Import pages; those pages and a ticker's page keep their
  own routes under `/ledger/` and say how to get back. Fills and orders: three chips (Orders,
  Fills, At IBKR) and a window (7, 30, 90 days, a year), each list headed by its source. System:
  the sizing record first (one line per kind of action: rows, valued so far, contracts withheld, and
  two marks, worded so that a positive number is what the action cost), then the score-vs-outcome
  evidence with its read-only sentences first.
- **FINISH:** unreviewed and undocumented is unfinished.
- **Market and sizing (2026-10-23):** an order in the Orders list says what shaped its size
  ("Claude's cut · Sent 1 of 3 contracts"). System opens with the sizing record, the review the
  live-cutover gate asks for. Claude's cut is labelled as Claude's wherever its reason shows.
```

- [x] **Step 3: Check the design file**

Run: `python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md`
Expected: exit 0.

- [x] **Step 4: Write the failing tests**

Create `web/lib/useViewParam.test.tsx`:

```tsx
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/portfolio",
}));

import { useViewParam } from "./useViewParam";

const VIEWS = ["positions", "campaigns", "calendar"] as const;

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
});

describe("useViewParam", () => {
  it("reads ?view=", () => {
    nav.params = new URLSearchParams("view=calendar");
    const { result } = renderHook(() => useViewParam(VIEWS, "positions"));
    expect(result.current[0]).toBe("calendar");
  });
  it("falls back when there is no view or the view is not one of the page's", () => {
    expect(renderHook(() => useViewParam(VIEWS, "positions")).result.current[0]).toBe("positions");
    nav.params = new URLSearchParams("view=foo");
    expect(renderHook(() => useViewParam(VIEWS, "positions")).result.current[0]).toBe("positions");
    nav.params = new URLSearchParams("view=");
    expect(renderHook(() => useViewParam(VIEWS, "positions")).result.current[0]).toBe("positions");
  });
  it("writes the view into the URL and keeps the other parameters", () => {
    nav.params = new URLSearchParams("month=2026-09");
    const { result } = renderHook(() => useViewParam(VIEWS, "positions"));
    act(() => result.current[1]("calendar"));
    expect(nav.replace).toHaveBeenCalledWith("/portfolio?month=2026-09&view=calendar", { scroll: false });
  });
  it("replaces a view that is already there", () => {
    nav.params = new URLSearchParams("view=positions&x=1");
    const { result } = renderHook(() => useViewParam(VIEWS, "positions"));
    act(() => result.current[1]("campaigns"));
    expect(nav.replace).toHaveBeenCalledWith("/portfolio?view=campaigns&x=1", { scroll: false });
  });
});
```

Create `web/features/portfolio/SummaryCard.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { SummaryCard } from "./SummaryCard";

const now = () => new Date().toISOString();
const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
const sourced = (value: number | null, stale = false) => ({ value, source: "ibkr", as_of: now(), stale });
const account = (over: Record<string, unknown> = {}) => ({
  as_of: now(),
  net_liquidation: sourced(125_000),
  total_cash: sourced(40_000),
  buying_power: sourced(80_000),
  maintenance_margin: sourced(12_000),
  excess_liquidity: sourced(68_000),
  ...over,
});
const exposure = (over: Record<string, unknown> = {}) => ({
  as_of: now(),
  open_positions: 6,
  open_shorts: 3,
  open_campaigns: 2,
  net_delta_exposure: -150,
  cash_secured_against_puts: 18_000,
  buying_power_utilisation_pct: 22.5,
  shorts_at_assignment_risk: 1,
  ...over,
});
const reading = (over: Record<string, unknown> = {}) => ({
  as_of: now(),
  source: "monitor",
  degraded: false,
  account: account(),
  exposure: exposure(),
  note: null,
  ...over,
});
const serve = (body: unknown) => renderWithQuery(<SummaryCard />, { "/portfolio/summary": body });

describe("SummaryCard", () => {
  it("shows the account and the exposure as figure lines, with no Delayed word on a live reading", async () => {
    serve(reading());
    const acct = await screen.findByRole("group", { name: "Account figures" });
    expect(within(acct).getByText("Net liquidation")).toBeInTheDocument();
    expect(within(acct).getByText("$125,000.00")).toBeInTheDocument();
    const expo = screen.getByRole("group", { name: "Exposure figures" });
    expect(within(expo).getByText("Open shorts")).toBeInTheDocument();
    expect(within(expo).getByText("Shorts at assignment risk")).toBeInTheDocument();
    expect(within(expo).getByText("−150")).toBeInTheDocument(); // a real minus, not a hyphen
    expect(within(expo).getByText("22.5%")).toBeInTheDocument();
    expect(screen.queryByText("Delayed")).toBeNull();
  });

  it("says Delayed, the age and the API's note verbatim when the reading is degraded and old", async () => {
    serve(reading({ source: "eod", degraded: true, as_of: ago(3), note: "Values are from the last end-of-day run." }));
    expect(await screen.findByText("Delayed")).toBeInTheDocument();
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();
    expect(screen.getByTestId("degraded-notice")).toHaveTextContent("Values are from the last end-of-day run.");
  });

  it("says Delayed for an old reading even when nothing marks it degraded, and adds no notice", async () => {
    serve(reading({ as_of: ago(2) }));
    expect(await screen.findByText("Delayed")).toBeInTheDocument();
    expect(screen.queryByTestId("degraded-notice")).toBeNull();
  });

  it("says why there is nothing when no snapshot has been captured, and shows no figures", async () => {
    serve(reading({ source: "none", degraded: true, account: null, exposure: null, note: null }));
    expect(await screen.findByText("No portfolio snapshot has been captured yet.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Account figures" })).toBeNull();
    expect(screen.queryByText("Delayed")).toBeNull();
  });

  it("uses the API's own words for the empty rung when it has some", async () => {
    serve(reading({ source: "none", degraded: true, account: null, exposure: null, note: "The monitor has not run yet." }));
    expect(await screen.findByText("The monitor has not run yet.")).toBeInTheDocument();
  });

  it("renders a figure we do not have as a hatched n/a, never $0", async () => {
    serve(reading({ account: account({ net_liquidation: sourced(null) }) }));
    const acct = await screen.findByRole("group", { name: "Account figures" });
    const na = within(acct).getAllByText("n/a")[0];
    expect(na.closest("dd")).toHaveClass("hatch");
    expect(screen.queryByText("$0")).toBeNull();
  });

  it("says a stale figure is stale, in words", async () => {
    serve(reading({ account: account({ buying_power: sourced(80_000, true) }) }));
    const acct = await screen.findByRole("group", { name: "Account figures" });
    expect(within(acct).getByText("stale")).toBeInTheDocument();
  });

  it("renders an unknown buying-power use as n/a, not 0%", async () => {
    serve(reading({ exposure: exposure({ buying_power_utilisation_pct: null }) }));
    const expo = await screen.findByRole("group", { name: "Exposure figures" });
    expect(within(expo).queryByText("0.0%")).toBeNull();
    expect(within(expo).getByText("n/a")).toBeInTheDocument();
  });

  it("says it could not load, and that it tries again, when the request fails", async () => {
    renderWithQuery(<SummaryCard />, {});
    expect(await screen.findByText("Could not load the account summary.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every 30 seconds.")).toBeInTheDocument();
  });
});
```

- [x] **Step 5: Run them to verify they fail**

Run: `cd web && npx vitest run lib/useViewParam.test.tsx features/portfolio/SummaryCard.test.tsx`
Expected: FAIL (modules not found).

- [x] **Step 6: Implement `web/lib/useViewParam.ts`**

```ts
"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/**
 * A page's view, kept in `?view=` so a reload or a shared link keeps it. No value, or one that is
 * not one of `views`, is `fallback`. Choosing a view writes it into the URL and keeps every other
 * parameter. A page using this must render inside <Suspense> (Next's useSearchParams rule).
 */
export function useViewParam<T extends string>(views: readonly T[], fallback: T): [T, (v: T) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("view");
  const value = (views as readonly string[]).includes(raw ?? "") ? (raw as T) : fallback;

  const set = useCallback(
    (v: T) => {
      const next = new URLSearchParams(params.toString());
      next.set("view", v);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [params, router, pathname],
  );

  return [value, set];
}
```

- [x] **Step 7: Implement `web/features/portfolio/SummaryCard.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { DegradedNotice } from "@/components/portfolio/DegradedNotice";
import { FreshnessLabel } from "@/components/portfolio/FreshnessLabel";
import type {
  AccountBlock,
  ExposureBlock,
  PortfolioSummaryResponse,
  SourcedFloat,
} from "@/components/portfolio/types";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { FigureLines, type FigureRow } from "@/features/claude-context/FigureLines";
import { FRESH_FOR_MINUTES } from "@/features/home/positions";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell, isStale } from "@/lib/money";

const ACCOUNT: { key: keyof Omit<AccountBlock, "as_of">; label: string }[] = [
  { key: "net_liquidation", label: "Net liquidation" },
  { key: "total_cash", label: "Total cash" },
  { key: "buying_power", label: "Buying power" },
  { key: "maintenance_margin", label: "Maintenance margin" },
  { key: "excess_liquidity", label: "Excess liquidity" },
];

function moneyRow(label: string, f: SourcedFloat): FigureRow {
  const unknown = f.value === null || f.value === undefined;
  return {
    label,
    unknown,
    value: unknown ? (
      UNKNOWN
    ) : (
      <>
        {formatMoneyCell(f.value)}
        {f.stale && <span className="ml-1.5 font-sans text-xs font-normal text-muted">stale</span>}
      </>
    ),
  };
}

/** A real minus for a negative figure, as the stub writes signed money. */
function signed(n: number): string {
  const body = Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 1 });
  return n > 0 ? `+${body}` : n < 0 ? `−${body}` : body;
}

function exposureRows(e: ExposureBlock): FigureRow[] {
  const pct = e.buying_power_utilisation_pct;
  const unknownPct = pct === null || pct === undefined;
  return [
    { label: "Open positions", value: String(e.open_positions) },
    { label: "Open shorts", value: String(e.open_shorts) },
    { label: "Open campaigns", value: String(e.open_campaigns) },
    { label: "Shorts at assignment risk", value: String(e.shorts_at_assignment_risk) },
    { label: "Net delta exposure", value: signed(e.net_delta_exposure) },
    { label: "Cash secured against puts", value: formatMoneyCell(e.cash_secured_against_puts) },
    { label: "Buying power used", value: unknownPct ? UNKNOWN : `${pct.toFixed(1)}%`, unknown: unknownPct },
  ];
}

/**
 * The Account card: how old the portfolio reading is, in words, and what it says. Every figure
 * is a Sourced value, so an unknown one is a hatched n/a and a stale one says so. The "Delayed"
 * word and the age follow Home's positions card (older than 30 minutes, or degraded); the API's
 * degraded note is shown verbatim, never paraphrased.
 */
export function SummaryCard() {
  const { data, isError } = useQuery({
    queryKey: ["portfolio", "summary"],
    queryFn: () => apiFetch<PortfolioSummaryResponse>("/portfolio/summary"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  if (isError && !data) {
    return (
      <Card aria-labelledby="account-title">
        <h2 id="account-title" className="text-[1.0625rem] font-bold">
          Account
        </h2>
        <p className="mt-2 text-sm text-muted">Could not load the account summary.</p>
        <p className="mt-1 text-[0.8125rem] text-muted">It tries again every 30 seconds.</p>
      </Card>
    );
  }
  if (!data) {
    return (
      <Card as="div" className="h-[168px]" role="status" aria-busy="true" aria-label="Loading the account summary" />
    );
  }

  const none = data.source === "none";
  const delayed = !none && (data.degraded || isStale(data.as_of, FRESH_FOR_MINUTES));

  return (
    <Card aria-labelledby="account-title">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id="account-title" className="text-[1.0625rem] font-bold">
          Account
        </h2>
        {!none && (
          <span className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-muted">
            {delayed && <StatusWord tone="flag">Delayed</StatusWord>}
            <span>
              Updated <FreshnessLabel asOf={data.as_of} freshForMinutes={FRESH_FOR_MINUTES} />
            </span>
          </span>
        )}
      </div>
      {none ? (
        <p className="mt-2 text-sm">{data.note ?? "No portfolio snapshot has been captured yet."}</p>
      ) : (
        <>
          {data.degraded && data.note && (
            <div className="mt-2.5">
              <DegradedNotice note={data.note} />
            </div>
          )}
          <div className="grid gap-x-8 sm:grid-cols-2">
            {data.account && (
              <FigureLines
                label="Account figures"
                rows={ACCOUNT.map(({ key, label }) => moneyRow(label, data.account![key] as SourcedFloat))}
              />
            )}
            {data.exposure && <FigureLines label="Exposure figures" rows={exposureRows(data.exposure)} />}
          </div>
        </>
      )}
    </Card>
  );
}
```

- [x] **Step 8: Restyle `DegradedNotice`** — in `web/components/portfolio/DegradedNotice.tsx` replace
  the returned element (keep the file's doc comment and the props type) with:

```tsx
export function DegradedNotice({ note }: DegradedNoticeProps) {
  return (
    <div data-testid="degraded-notice" role="note" className="rounded-xl bg-sunk px-3 py-2.5 text-sm text-content">
      {note}
    </div>
  );
}
```

  In the same file's doc comment, change "an elevated surface and plain text" to "a pressed-sage
  block and plain text".

- [x] **Step 9: Restyle `RefreshControl`** — in `web/components/portfolio/RefreshControl.tsx` add
  `import { Button } from "@/components/ui/Button";` after the `CommandReceipt` import, and replace
  the component's returned element (everything from `return (` to the matching `);` before
  `function describeError`) with:

```tsx
  return (
    <div data-testid="refresh-control" className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {/* Secondary, not lime: a refresh reads the broker and writes one snapshot; it decides nothing. */}
      <Button variant="secondary" disabled={inFlight} onClick={onRefresh}>
        Refresh
      </Button>

      {error && (
        <p className="text-[0.8125rem] text-loss" data-testid="command-error" role="alert">
          {error}
        </p>
      )}

      {current && (
        <CommandReceipt
          command={current}
          order={null}
          drainHealthy={drainHealthy}
          plainReasons={["broker_unavailable"]}
        />
      )}
    </div>
  );
```

  Nothing above `return (` changes: the command flow, the invalidation and the controls query are
  the protected behaviour.

- [x] **Step 10: Run the tests, then the gate**

Run: `cd web && npx vitest run lib features/portfolio components/portfolio && npx tsc --noEmit && npm run lint`
Expected: PASS: the 4 + 9 new tests, and every existing `RefreshControl`, `DegradedNotice` and
legacy portfolio test **unmodified** (that is the proof the restyles changed no behaviour).

- [x] **Step 11: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/portfolio web/lib/useViewParam.ts web/components/portfolio/DegradedNotice.tsx web/components/portfolio/RefreshControl.tsx`
Expected: exit 0, or every finding fixed in the code.

- [x] **Step 12: Commit** (with the Progress log row for Task 4 filled in)

```bash
git add web/DESIGN.md web/lib/useViewParam.ts web/lib/useViewParam.test.tsx web/features/portfolio \
  web/components/portfolio/DegradedNotice.tsx web/components/portfolio/RefreshControl.tsx \
  docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): Portfolio and Activity contracts, the Account card, useViewParam"
```

---

### Task 5: Positions — name cards over Home's rows

**Files:**
- Create: `web/features/home/PositionRowItem.tsx`, `web/features/home/PositionRowItem.test.tsx`
- Modify: `web/features/home/PositionsCard.tsx` (uses `PositionRowItem`; behaviour unchanged)
- Create: `web/features/portfolio/positions.ts`, `positions.test.ts`
- Create: `web/features/portfolio/PositionsView.tsx`, `PositionsView.test.tsx`

**Interfaces:**
- Consumes: `buildPositionRows`, `matchesQuery`, `PositionRow`, `FRESH_FOR_MINUTES`
  (`features/home/positions.ts`), `SpreadPosition`/`SpreadPositionsResponse`
  (`features/home/types.ts`), `PositionsResponse`/`PositionGroupData`/`OptionLeg`
  (`components/portfolio/types.ts`), `NameFlags`, `todayInNewYork`, `STRATEGY_LABEL`,
  `SegmentedControl`, `Card`, `StatusWord`, `formatStubValue`, `FreshnessLabel`.
- Produces:
  - `PositionRowItem({ row: PositionRow, flags?: boolean, detail?: ReactNode })` (an `<li>`)
  - `positions.ts`: `PositionsFilter`, `FILTERS`, `FILTER_LABEL`, `EMPTY`, `DetailPart`,
    `legDetail(o: OptionLeg): DetailPart[]`, `rowsPnl(rows: PositionRow[]): number | null`,
    `NameCard`, `buildNameCards(groups, todayIso, alerted?): NameCard[]`,
    `spreadRows(spreads, todayIso, underlying): PositionRow[]`,
    `narrowRows(rows, filter, query): PositionRow[]`, `narrow(cards, filter, query): NameCard[]`,
    `countByFilter(cards, spreads, query): Record<PositionsFilter, number>`
  - `PositionsView()` (Task 7), reading `["portfolio","positions"]`, `["spreads","positions","open"]`
    and `["options","shorts"]`, the keys Home's card reads, so both share one request each.

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: name cards on paper, Home's
  rows exactly, a muted figure line under each option, flags beside the ticker, no lime.

- [x] **Step 2: Write the failing tests**

Create `web/features/home/PositionRowItem.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { PositionRowItem } from "./PositionRowItem";
import type { PositionRow } from "./positions";

const row = (over: Partial<PositionRow> = {}): PositionRow => ({
  key: "AAPL:x",
  kind: "csp",
  underlying: "AAPL",
  href: "/positions/AAPL/2099-11-21_P180",
  title: "AAPL $180 put",
  status: { word: "Out of the money", tone: "neutral" },
  alert: false,
  sub: "Sat, 21 Nov · 30d",
  value: 38,
  valueLabel: "open P&L",
  sortKey: "2099-11-21",
  ...over,
});
const ctx = { "/claude/context": { available: true, dossiers: [{ symbol: "AAPL", health: "weak", events: [] }] } };
const inList = (ui: React.ReactElement) => <ul>{ui}</ul>;

describe("PositionRowItem", () => {
  it("draws the title, the status word, the sub-line and the signed value, and links to the contract", () => {
    renderWithQuery(inList(<PositionRowItem row={row()} />), ctx);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/positions/AAPL/2099-11-21_P180");
    expect(screen.getByText("AAPL $180 put")).toBeInTheDocument();
    expect(screen.getByText("Out of the money")).toBeInTheDocument();
    expect(screen.getByText("+$38.00")).toBeInTheDocument();
  });
  it("is not a link when the contract is not fully known", () => {
    renderWithQuery(inList(<PositionRowItem row={row({ href: null })} />), ctx);
    expect(screen.queryByRole("link")).toBeNull();
  });
  it("shows the name's flags unless asked not to", async () => {
    renderWithQuery(inList(<PositionRowItem row={row()} />), ctx);
    expect(await screen.findByText("Weak health")).toBeInTheDocument();
  });
  it("leaves the flags to the card header when flags is false, and shows a detail line", () => {
    const before = apiFetchMock.mock.calls.length;
    renderWithQuery(inList(<PositionRowItem row={row()} flags={false} detail="delta -0.21" />), ctx);
    expect(screen.getByText("delta -0.21")).toBeInTheDocument();
    // NameFlags is not mounted, so the row never asks for the name's notes.
    expect(apiFetchMock.mock.calls.length).toBe(before);
  });
  it("draws an unknown value as a hatched n/a, never $0", () => {
    renderWithQuery(inList(<PositionRowItem row={row({ value: null })} />), ctx);
    expect(screen.getByText("n/a")).toHaveClass("hatch");
  });
});
```

Create `web/features/portfolio/positions.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { PositionGroupData } from "@/components/portfolio/types";
import type { SpreadPosition } from "@/features/home/types";
import {
  buildNameCards,
  countByFilter,
  legDetail,
  narrow,
  rowsPnl,
  spreadRows,
} from "./positions";

const TODAY = "2026-10-23";
const leg = (over: Record<string, unknown> = {}) => ({
  as_of: "", symbol: "x", right: "P", strike: 180, expiry: "2099-11-21", dte: 30, contracts: 1,
  short: true, delta: -0.21, delta_source: "ibkr", market_price: 1.42, market_value: -142,
  unrealized_pnl: 38, moneyness: "otm", assignment_risk: false, ...over,
});
const stock = (over: Record<string, unknown> = {}) => ({
  as_of: "", shares: 100, avg_cost: 182.4, adjusted_cost_basis: null, market_price: 190,
  market_value: 19000, unrealized_pnl: 760, unrealized_pnl_adjusted: null, ...over,
});
const group = (underlying: string, options: object[], stk: object | null = null) =>
  ({ as_of: "", underlying, stock: stk, options }) as unknown as PositionGroupData;
const spread = (over: Record<string, unknown> = {}) =>
  ({
    as_of: "", spread_id: "s1", mode: "paper", side: "put", expiry: "2099-11-21", short_strike: 763,
    long_strike: 758, width: 5, contracts_opened: 2, contracts: 2, entry_credit: 0.25,
    entry_commission: 2.6, opened_at: "", status: "open", exit_debit: null, exit_commission: null,
    exit_reason: null, closed_at: null, realized_pnl_usd: null, ...over,
  }) as unknown as SpreadPosition;

const pnl = (g: PositionGroupData) => rowsPnl(buildNameCards([g], TODAY)[0].rows);

describe("rowsPnl", () => {
  it("adds the rows up when every one is known", () => {
    expect(pnl(group("AAPL", [leg(), leg({ symbol: "y", right: "C", strike: 200, unrealized_pnl: -12 })]))).toBe(26);
  });
  it("is unknown when any row is unknown, never the sum of the rest", () => {
    expect(pnl(group("AAPL", [leg(), leg({ symbol: "y", unrealized_pnl: null })]))).toBeNull();
  });
  it("keeps a genuine zero", () => {
    expect(pnl(group("AAPL", [leg({ unrealized_pnl: 5 }), leg({ symbol: "y", unrealized_pnl: -5 })]))).toBe(0);
  });
  it("is unknown for no rows", () => {
    expect(rowsPnl([])).toBeNull();
  });
  it("adds the shares row as the card shows it, the premium-adjusted figure when there is one", () => {
    expect(pnl(group("AAPL", [leg()], stock({ unrealized_pnl_adjusted: 900 })))).toBe(938);
    expect(pnl(group("AAPL", [leg()], stock()))).toBe(798);
  });
});

describe("buildNameCards", () => {
  it("orders the names alphabetically and drops a group with nothing to show", () => {
    const cards = buildNameCards([group("KO", [leg()]), group("AAPL", [leg()]), group("EMPTY", [])], TODAY);
    expect(cards.map((c) => c.underlying)).toEqual(["AAPL", "KO"]);
  });
  it("keys each option's figure line by the row's own key", () => {
    const [card] = buildNameCards([group("AAPL", [leg()])], TODAY);
    expect(Object.keys(card.details)).toEqual(["AAPL:x"]);
    expect(card.rows[0].key).toBe("AAPL:x");
  });
  it("flags a roll alert on the contract the monitor raised it on", () => {
    const [card] = buildNameCards([group("AAPL", [leg()])], TODAY, new Set(["x"]));
    expect(card.rows[0].alert).toBe(true);
  });
});

describe("legDetail", () => {
  it("writes delta with its source, the mark and the value", () => {
    expect(legDetail(leg() as never)).toEqual([
      { label: "delta", value: "-0.21 (ibkr)" },
      { label: "mark", value: "$1.42" },
      { label: "value", value: "-$142.00" },
    ]);
  });
  it("leaves an unknown figure null, never 0", () => {
    const parts = legDetail(leg({ delta: null, market_price: null, market_value: null }) as never);
    expect(parts.map((p) => p.value)).toEqual([null, null, null]);
  });
  it("shows a delta without a source", () => {
    expect(legDetail(leg({ delta_source: null }) as never)[0].value).toBe("-0.21");
  });
});

describe("narrow and countByFilter", () => {
  const cards = buildNameCards(
    [
      group("AAPL", [leg(), leg({ symbol: "y", right: "C", strike: 200 })], stock()),
      group("KO", [leg({ symbol: "z", right: "C", strike: 72 })]),
    ],
    TODAY,
  );
  it("keeps only the rows of the chosen type and drops a card left with none", () => {
    expect(narrow(cards, "cc", "").map((c) => [c.underlying, c.rows.length])).toEqual([["AAPL", 1], ["KO", 1]]);
    expect(narrow(cards, "csp", "").map((c) => c.underlying)).toEqual(["AAPL"]);
    expect(narrow(cards, "shares", "").map((c) => c.rows.length)).toEqual([1]);
  });
  it("searches the ticker and the contract's own words", () => {
    expect(narrow(cards, "all", "ko").map((c) => c.underlying)).toEqual(["KO"]);
    expect(narrow(cards, "all", "aapl call").map((c) => c.rows.map((r) => r.title))).toEqual([["AAPL $200 call"]]);
  });
  it("counts what each chip would show with the search applied, spreads included", () => {
    const spreads = spreadRows([spread()], TODAY, "SPY");
    expect(countByFilter(cards, spreads, "")).toEqual({ all: 5, csp: 1, cc: 2, spread: 1, shares: 1 });
    expect(countByFilter(cards, spreads, "aapl")).toEqual({ all: 3, csp: 1, cc: 1, spread: 0, shares: 1 });
  });
});
```

Create `web/features/portfolio/PositionsView.test.tsx`:

```tsx
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { PositionsView } from "./PositionsView";

const now = () => new Date().toISOString();
const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
const leg = (over: Record<string, unknown> = {}) => ({
  as_of: "", symbol: "x", right: "P", strike: 180, expiry: "2099-11-21", dte: 30, contracts: 1,
  short: true, delta: -0.21, delta_source: "ibkr", market_price: 1.42, market_value: -142,
  unrealized_pnl: 38, moneyness: "otm", assignment_risk: false, ...over,
});
const stock = { as_of: "", shares: 100, avg_cost: 182.4, adjusted_cost_basis: null, market_price: 190, market_value: 19000, unrealized_pnl: 760, unrealized_pnl_adjusted: null };
const group = (underlying: string, options: unknown[], stk: unknown = null) => ({ as_of: "", underlying, stock: stk, options });
const positions = (groups: unknown[], over: Record<string, unknown> = {}) => ({ as_of: now(), source: "monitor", degraded: false, groups, ...over });
const spreadsOn = { as_of: "", available: true, underlying: "SPY", mode: "paper", positions: [] };
const common = {
  "/options/shorts": { as_of: "", shorts: [] },
  "/claude/context": { available: false, dossiers: [] },
};
const base = { ...common, "/spreads/positions": spreadsOn };
const aapl = group("AAPL", [leg(), leg({ symbol: "y", right: "C", strike: 200, unrealized_pnl: -12 })], stock);
const ko = group("KO", [leg({ symbol: "z", right: "C", strike: 72, unrealized_pnl: 30 })]);

describe("PositionsView", () => {
  it("groups the contracts under their ticker and totals the name's open P&L", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([aapl]) });
    expect(await screen.findByRole("heading", { name: "AAPL" })).toBeInTheDocument();
    expect(screen.getByText("AAPL $180 put")).toBeInTheDocument();
    expect(screen.getByText("AAPL $200 call")).toBeInTheDocument();
    expect(screen.getByText("AAPL · 100 shares")).toBeInTheDocument();
    expect(screen.getByTestId("name-pnl")).toHaveTextContent("+$786.00");
  });

  it("shows n/a for a name's total when one leg is unknown, never the sum of the rest", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/portfolio/positions": positions([group("AAPL", [leg(), leg({ symbol: "y", unrealized_pnl: null })])]),
    });
    const total = await screen.findByTestId("name-pnl");
    expect(within(total).getByText("n/a")).toHaveClass("hatch");
    expect(total).not.toHaveTextContent("38");
  });

  it("keeps a genuine zero as $0", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/portfolio/positions": positions([group("AAPL", [leg({ unrealized_pnl: 5 }), leg({ symbol: "y", unrealized_pnl: -5 })])]),
    });
    expect(await screen.findByTestId("name-pnl")).toHaveTextContent("$0");
  });

  it("puts the delta, the mark and the value under each contract, n/a where unknown", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/portfolio/positions": positions([group("AAPL", [leg({ delta: null })])]),
    });
    const link = await screen.findByRole("link", { name: /AAPL \$180 put/ });
    expect(link).toHaveTextContent("delta n/a · mark $1.42 · value -$142.00");
  });

  it("opens each contract's page from its row and marks a roll alert in words", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/options/shorts": { as_of: "", shorts: [{ position_symbol: "x", alerts: [{ id: 1 }] }] },
      "/portfolio/positions": positions([group("AAPL", [leg()])]),
    });
    const link = await screen.findByRole("link", { name: /AAPL \$180 put/ });
    expect(link).toHaveAttribute("href", "/positions/AAPL/2099-11-21_P180");
    expect(await screen.findByText("Roll alert")).toBeInTheDocument();
  });

  it("narrows by type and by search, and the chips count what each would show", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([aapl, ko]) });
    expect(await screen.findByRole("button", { name: "All 4" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "CCs 2" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "CCs 2" }));
    expect(screen.queryByText("AAPL $180 put")).toBeNull();
    expect(screen.getByText("KO $72 call")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "All 4" }));
    fireEvent.change(screen.getByLabelText("Search positions"), { target: { value: "ko" } });
    expect(screen.queryByRole("heading", { name: "AAPL" })).toBeNull();
    expect(screen.getByRole("button", { name: "All 1" })).toBeInTheDocument();
  });

  it("says nothing matches a search, in words", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([ko]) });
    await screen.findByText("KO $72 call");
    fireEvent.change(screen.getByLabelText("Search positions"), { target: { value: "zzz" } });
    expect(screen.getByText('No positions match "zzz".')).toBeInTheDocument();
  });

  it("adds a card for the open credit spreads", async () => {
    const spread = {
      as_of: "", spread_id: "s1", mode: "paper", side: "put", expiry: "2099-11-21", short_strike: 763,
      long_strike: 758, width: 5, contracts_opened: 2, contracts: 2, entry_credit: 0.25,
      entry_commission: 2.6, opened_at: "", status: "open", exit_debit: null, exit_commission: null,
      exit_reason: null, closed_at: null, realized_pnl_usd: null,
    };
    renderWithQuery(<PositionsView />, {
      ...base,
      "/spreads/positions": { ...spreadsOn, positions: [spread] },
      "/portfolio/positions": positions([ko]),
    });
    expect(await screen.findByRole("heading", { name: "SPY credit spreads" })).toBeInTheDocument();
    expect(screen.getByText("SPY 763/758 put spread")).toBeInTheDocument();
  });

  it("says an unreadable spreads book is unavailable, not empty", async () => {
    // No "/spreads/positions" answer: the request fails, which is not the same as an empty book.
    renderWithQuery(<PositionsView />, { ...common, "/portfolio/positions": positions([ko]) });
    await screen.findByText("KO $72 call");
    expect(await screen.findByText("Credit spreads are unavailable right now, so they are not listed.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Credit spreads" }));
    expect(screen.getByText("Credit spreads are unavailable right now.")).toBeInTheDocument();
    expect(screen.queryByText("No credit spreads open.")).toBeNull();
  });

  it("says Delayed and the age when the reading is old", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/portfolio/positions": positions([ko], { as_of: ago(3), source: "eod", degraded: true }),
    });
    expect(await screen.findByText("Delayed")).toBeInTheDocument();
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();
  });

  it("tells no snapshot apart from no positions", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([], { source: "none", degraded: true }) });
    expect(await screen.findByText("No portfolio snapshot has been captured yet.")).toBeInTheDocument();
    expect(screen.queryByText("No open positions.")).toBeNull();
  });

  it("says no positions are open when the reading is real and empty", async () => {
    renderWithQuery(<PositionsView />, { ...base, "/portfolio/positions": positions([]) });
    expect(await screen.findByText("No open positions.")).toBeInTheDocument();
  });

  it("puts the name's flags on its card once, not on every row", async () => {
    renderWithQuery(<PositionsView />, {
      ...base,
      "/claude/context": { available: true, dossiers: [{ symbol: "AAPL", health: "weak", events: [] }] },
      "/portfolio/positions": positions([aapl]),
    });
    await screen.findByRole("heading", { name: "AAPL" });
    expect(await screen.findAllByText("Weak health")).toHaveLength(1);
  });

  it("says so in a sentence when positions cannot load", async () => {
    renderWithQuery(<PositionsView />, base);
    expect(await screen.findByText("Positions unavailable right now.")).toBeInTheDocument();
  });
});
```

- [x] **Step 3: Run them to verify they fail**

Run: `cd web && npx vitest run features/home/PositionRowItem.test.tsx features/portfolio`
Expected: FAIL (modules not found).

- [x] **Step 4: Extract the row** — create `web/features/home/PositionRowItem.tsx`:

```tsx
import clsx from "clsx";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { StatusWord } from "@/components/ui/StatusWord";
import { formatStubValue } from "@/components/ui/Stub";
import { NameFlags } from "@/features/market/NameFlags";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import type { PositionRow } from "./positions";

/**
 * One position row, as Home's Positions card and the Portfolio page draw it: the title bold with
 * its status words, a muted sub-line (and an optional figure line beneath it), the value at the
 * right with its label, and a chevron when the whole row opens the contract's page. `flags` puts
 * the name's "Weak health" and "Event" words beside the title; a card that shows them in its own
 * header turns it off.
 */
export function PositionRowItem({
  row: r,
  flags = true,
  detail,
}: {
  row: PositionRow;
  flags?: boolean;
  detail?: ReactNode;
}) {
  const pnl = r.valueLabel === "open P&L";
  const body = (
    <>
      <div className="min-w-0">
        <span className="font-bold">{r.title}</span>
        {r.status && (
          <span className="ml-1.5 align-[1px]">
            <StatusWord tone={r.status.tone}>{r.status.word}</StatusWord>
          </span>
        )}
        {r.alert && (
          <span className="ml-1.5 align-[1px]">
            <StatusWord tone="flag">Roll alert</StatusWord>
          </span>
        )}
        {flags && r.underlying && <NameFlags symbol={r.underlying} />}
        <div className="text-[0.8125rem] text-muted">{r.sub}</div>
        {detail && <div className="tabular font-mono text-xs text-muted">{detail}</div>}
      </div>
      <div className="tabular text-right font-semibold">
        <span
          className={clsx(
            r.value === null && "hatch text-unknown",
            r.value !== null && pnl && r.value < 0 && "text-loss",
            r.value !== null && pnl && r.value > 0 && "text-gain",
          )}
        >
          {r.value === null ? UNKNOWN : pnl ? formatStubValue(r.value, "signed-money") : formatMoneyCell(r.value)}
        </span>
        <div className="text-[0.8125rem] font-normal text-muted">{r.valueLabel}</div>
      </div>
    </>
  );
  return (
    <li className="border-t border-border first:border-t-0">
      {r.href ? (
        // The whole row opens the contract. The chevron says so without a word.
        <Link
          href={r.href}
          className="-mx-2 grid grid-cols-[1fr_auto_16px] items-center gap-x-2.5 rounded-xl px-2 py-[11px] text-sm hover:bg-sunk"
        >
          {body}
          <ChevronRight size={16} aria-hidden="true" className="text-muted" />
        </Link>
      ) : (
        <div className="grid grid-cols-[1fr_auto] gap-x-2.5 py-[11px] text-sm">{body}</div>
      )}
    </li>
  );
}
```

  Then in `web/features/home/PositionsCard.tsx`: **replace** the whole `{visible.map((r) => { ... })}`
  expression (the only child of the `<ul>`, from `{visible.map((r) => {` to its closing `})}`) with

```tsx
          {visible.map((r) => (
            <PositionRowItem key={r.key} row={r} />
          ))}
```

  and fix the imports: add `import { PositionRowItem } from "./PositionRowItem";`; change
  `import { ChevronRight, Search, X } from "lucide-react";` to `import { Search, X } from "lucide-react";`;
  change `import { formatMoneyCell, isStale } from "@/lib/money";` to `import { isStale } from "@/lib/money";`;
  and delete the now-unused `import clsx from "clsx";`, `import Link from "next/link";`,
  `import { NameFlags } from "@/features/market/NameFlags";`,
  `import { formatStubValue } from "@/components/ui/Stub";` and `import { UNKNOWN } from "@/lib/format";`.
  (Run `npx tsc --noEmit` and `npm run lint` after: either names any import this list missed.)

- [x] **Step 5: Implement `web/features/portfolio/positions.ts`**

```ts
import type { OptionLeg, PositionGroupData } from "@/components/portfolio/types";
import { type PositionRow, buildPositionRows, matchesQuery } from "@/features/home/positions";
import type { SpreadPosition } from "@/features/home/types";
import { formatMoneyCell } from "@/lib/money";
import { STRATEGY_LABEL } from "@/lib/strategy";

export type PositionsFilter = "all" | "csp" | "cc" | "spread" | "shares";

export const FILTERS: PositionsFilter[] = ["all", "csp", "cc", "spread", "shares"];
export const FILTER_LABEL: Record<PositionsFilter, string> = { ...STRATEGY_LABEL, shares: "Shares" };
export const EMPTY: Record<PositionsFilter, string> = {
  all: "No open positions.",
  csp: "No cash-secured puts open.",
  cc: "No covered calls open.",
  spread: "No credit spreads open.",
  shares: "No shares held.",
};

export type DetailPart = { label: string; value: string | null };

/** The figures under an option row: delta (and where it came from), the mark and the value. Null is unknown, never 0. */
export function legDetail(o: OptionLeg): DetailPart[] {
  const money = (v: number | null | undefined) => (v === null || v === undefined ? null : formatMoneyCell(v));
  const delta =
    o.delta === null || o.delta === undefined
      ? null
      : `${o.delta.toFixed(2)}${o.delta_source ? ` (${o.delta_source})` : ""}`;
  return [
    { label: "delta", value: delta },
    { label: "mark", value: money(o.market_price) },
    { label: "value", value: money(o.market_value) },
  ];
}

/**
 * A name's open P&L: its rows' own figures added up, but only when every one is known. A missing
 * figure makes the total unknown, never the sum of the rest and never $0; a card with no rows has
 * nothing to add up and is unknown too.
 */
export function rowsPnl(rows: PositionRow[]): number | null {
  const pnl = rows.filter((r) => r.valueLabel === "open P&L");
  if (pnl.length === 0 || pnl.some((r) => r.value === null)) return null;
  return pnl.reduce((sum, r) => sum + (r.value as number), 0);
}

export type NameCard = {
  underlying: string;
  rows: PositionRow[];
  /** The figure line under each option row, by row key. */
  details: Record<string, DetailPart[]>;
};

/** One card per underlying, alphabetical: Home's rows for the name, and each option's figures. */
export function buildNameCards(
  groups: PositionGroupData[],
  todayIso: string,
  alerted: ReadonlySet<string> = new Set(),
): NameCard[] {
  return groups
    .map((g) => ({
      underlying: g.underlying,
      rows: buildPositionRows([g], [], todayIso, "SPY", alerted),
      details: Object.fromEntries(g.options.map((o) => [`${g.underlying}:${o.symbol}`, legDetail(o)])),
    }))
    .filter((c) => c.rows.length > 0)
    .sort((a, b) => a.underlying.localeCompare(b.underlying));
}

export function spreadRows(spreads: SpreadPosition[], todayIso: string, underlying: string): PositionRow[] {
  return buildPositionRows([], spreads, todayIso, underlying);
}

/** The rows the chosen type and the search leave in. */
export function narrowRows(rows: PositionRow[], filter: PositionsFilter, query: string): PositionRow[] {
  return rows.filter((r) => matchesQuery(r, query) && (filter === "all" || r.kind === filter));
}

/** Each card cut to the rows that remain, a card left with none dropped. */
export function narrow(cards: NameCard[], filter: PositionsFilter, query: string): NameCard[] {
  return cards
    .map((c) => ({ ...c, rows: narrowRows(c.rows, filter, query) }))
    .filter((c) => c.rows.length > 0);
}

/** How many rows each chip would show with the search applied. */
export function countByFilter(
  cards: NameCard[],
  spreads: PositionRow[],
  query: string,
): Record<PositionsFilter, number> {
  const all = [...cards.flatMap((c) => c.rows), ...spreads];
  return Object.fromEntries(FILTERS.map((f) => [f, narrowRows(all, f, query).length])) as Record<
    PositionsFilter,
    number
  >;
}
```

- [x] **Step 6: Implement `web/features/portfolio/PositionsView.tsx`**

```tsx
"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import type { ShortListResponse } from "@/components/options/types";
import { FreshnessLabel } from "@/components/portfolio/FreshnessLabel";
import type { PositionsResponse } from "@/components/portfolio/types";
import { Card } from "@/components/ui/Card";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { formatStubValue } from "@/components/ui/Stub";
import { PositionRowItem } from "@/features/home/PositionRowItem";
import { FRESH_FOR_MINUTES } from "@/features/home/positions";
import type { SpreadPositionsResponse } from "@/features/home/types";
import { NameFlags } from "@/features/market/NameFlags";
import { todayInNewYork } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { isStale } from "@/lib/money";
import {
  EMPTY,
  FILTERS,
  FILTER_LABEL,
  type DetailPart,
  type NameCard,
  type PositionsFilter,
  buildNameCards,
  countByFilter,
  narrow,
  narrowRows,
  rowsPnl,
  spreadRows,
} from "./positions";

function Detail({ parts }: { parts: DetailPart[] }): ReactNode {
  return (
    <>
      {parts.map((p, i) => (
        <span key={p.label}>
          {i > 0 && " · "}
          {p.label} {p.value === null ? <span className="hatch text-unknown">{UNKNOWN}</span> : p.value}
        </span>
      ))}
    </>
  );
}

function NameCardView({ card }: { card: NameCard }) {
  const pnl = rowsPnl(card.rows);
  const titleId = `name-${card.underlying}`;
  return (
    <Card as="article" aria-labelledby={titleId}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={titleId} className="inline text-[1.0625rem] font-bold">
            {card.underlying}
          </h3>
          <NameFlags symbol={card.underlying} />
        </div>
        <div data-testid="name-pnl" className="tabular text-right font-mono font-semibold">
          <span
            className={clsx(
              pnl === null && "hatch text-unknown",
              pnl !== null && pnl < 0 && "text-loss",
              pnl !== null && pnl > 0 && "text-gain",
            )}
          >
            {pnl === null ? UNKNOWN : formatStubValue(pnl, "signed-money")}
          </span>
          <div className="font-sans text-[0.8125rem] font-normal text-muted">open P&amp;L</div>
        </div>
      </div>
      <ul className="mt-1">
        {card.rows.map((r) => (
          <PositionRowItem
            key={r.key}
            row={r}
            flags={false}
            detail={card.details[r.key] ? <Detail parts={card.details[r.key]} /> : undefined}
          />
        ))}
      </ul>
    </Card>
  );
}

/**
 * Positions, name by name: Home's rows under each ticker with the figures a register needs. The
 * data is the three requests Home's card makes, under the same query keys, so a visit to both asks
 * once. A name's total is the sum of what its rows show, or n/a; an unreadable spreads book is
 * said, never shown as none.
 */
export function PositionsView() {
  const [filter, setFilter] = useState<PositionsFilter>("all");
  const [query, setQuery] = useState("");
  const searchId = useId();

  const positions = useQuery({
    queryKey: ["portfolio", "positions"],
    queryFn: () => apiFetch<PositionsResponse>("/portfolio/positions"),
    refetchInterval: 60_000,
  });
  const spreads = useQuery({
    queryKey: ["spreads", "positions", "open"],
    queryFn: () => apiFetch<SpreadPositionsResponse>("/spreads/positions?status=open"),
    refetchInterval: 60_000,
  });
  const shorts = useQuery({
    queryKey: ["options", "shorts"],
    queryFn: () => apiFetch<ShortListResponse>("/options/shorts"),
    refetchInterval: 60_000,
  });

  const today = todayInNewYork();
  const alerted = new Set(
    (shorts.data?.shorts ?? []).filter((s) => s.alerts.length > 0).map((s) => s.position_symbol),
  );
  // Unknown is never none: an unreadable spreads book is not an empty one.
  const spreadsKnown = spreads.data?.available === true;
  const spreadsOut = spreads.isError || spreads.data?.available === false;
  const allCards = positions.data ? buildNameCards(positions.data.groups, today, alerted) : [];
  const allSpreads = spreadsKnown ? spreadRows(spreads.data!.positions, today, spreads.data!.underlying) : [];
  const cards = narrow(allCards, filter, query);
  const spreadList = narrowRows(allSpreads, filter, query);
  const counts = countByFilter(allCards, allSpreads, query);
  const options = FILTERS.map((f) => ({
    value: f,
    label: FILTER_LABEL[f],
    count: !positions.data || (f === "spread" && !spreadsKnown) ? null : counts[f],
  }));
  const searching = query.trim() !== "";

  let message: string | null = null;
  if (positions.isError && !positions.data) message = "Positions unavailable right now.";
  else if (positions.data && cards.length === 0 && spreadList.length === 0) {
    if (searching) message = `No positions match "${query.trim()}".`;
    else if (filter === "spread" && spreadsOut) message = "Credit spreads are unavailable right now.";
    else if (filter === "spread" && spreads.isPending) message = "Loading credit spreads.";
    else if (positions.data.source === "none" && filter !== "spread")
      message = "No portfolio snapshot has been captured yet.";
    else message = EMPTY[filter];
  }
  const loading = !positions.data && !positions.isError;
  const delayed =
    positions.data !== undefined &&
    positions.data.source !== "none" &&
    (positions.data.degraded || isStale(positions.data.as_of, FRESH_FOR_MINUTES));

  return (
    <div className="grid gap-3">
      <form role="search" onSubmit={(e) => e.preventDefault()} className="relative">
        <label htmlFor={searchId} className="sr-only">
          Search positions
        </label>
        <Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          id={searchId}
          type="text"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a ticker, like AMZN"
          // 16px: below that, iOS zooms the page when the field takes focus.
          className="min-h-11 w-full rounded-xl border border-control bg-surface pl-9 pr-11 text-base placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        />
        {searching && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => setQuery("")}
            className="absolute right-0 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full text-muted hover:bg-sunk hover:text-content md:right-1 md:h-9 md:w-9"
          >
            <X size={16} aria-hidden="true" />
          </button>
        )}
      </form>
      <SegmentedControl label="Position type" appearance="chips" options={options} value={filter} onChange={setFilter} />
      {delayed && (
        <p className="flex flex-wrap items-center gap-2">
          <StatusWord tone="flag">Delayed</StatusWord>
          <FreshnessLabel asOf={positions.data!.as_of} freshForMinutes={FRESH_FOR_MINUTES} />
        </p>
      )}
      {loading ? (
        <div role="status" aria-busy="true" aria-label="Loading positions" className="space-y-3">
          <div className="h-24 rounded-[18px] bg-surface" />
          <div className="h-24 rounded-[18px] bg-surface" />
        </div>
      ) : message !== null ? (
        <p className="py-3 text-sm text-muted">{message}</p>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {cards.map((c) => (
            <NameCardView key={c.underlying} card={c} />
          ))}
          {spreadList.length > 0 && (
            <Card as="article" aria-labelledby="name-spreads">
              <h3 id="name-spreads" className="text-[1.0625rem] font-bold">
                {spreads.data!.underlying} credit spreads
              </h3>
              <ul className="mt-1">
                {spreadList.map((r) => (
                  <PositionRowItem key={r.key} row={r} flags={false} />
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
      {filter === "all" && spreadsOut && positions.data && (
        <p className="border-t border-border pt-2.5 text-[0.8125rem] text-muted">
          Credit spreads are unavailable right now, so they are not listed.
        </p>
      )}
    </div>
  );
}
```

- [x] **Step 7: Run the tests, then the gate**

Run: `cd web && npx vitest run features/home features/portfolio && npx tsc --noEmit && npm run lint`
Expected: PASS: the 5 + 14 + 14 new tests, and **every existing `PositionsCard` test unmodified**
(the proof the extraction changed no behaviour). A `PositionsCard` test that fails means the row
markup was not moved verbatim: restore it, never edit that test.

- [x] **Step 8: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/portfolio web/features/home/PositionRowItem.tsx web/features/home/PositionsCard.tsx`
Expected: exit 0, or every finding fixed in the code.

- [x] **Step 9: Commit** (with the Progress log row for Task 5 filled in)

```bash
git add web/features/home/PositionRowItem.tsx web/features/home/PositionRowItem.test.tsx \
  web/features/home/PositionsCard.tsx web/features/portfolio/positions.ts \
  web/features/portfolio/positions.test.ts web/features/portfolio/PositionsView.tsx \
  web/features/portfolio/PositionsView.test.tsx docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): Portfolio Positions - name cards over Home's rows, totals that never hide an n/a"
```

---

### Task 6: Campaigns and Calendar

**Files:**
- Create: `web/components/ui/field.ts`
- Create: `web/features/portfolio/format.ts`, `campaigns.ts`, `campaigns.test.ts`,
  `CampaignsView.tsx`, `CampaignsView.test.tsx`, `calendar.ts`, `calendar.test.ts`,
  `CalendarView.tsx`, `CalendarView.test.tsx`
- Modify: `web/features/market/market.ts` (+ `eventBefore`), `web/features/market/market.test.tsx` (+3 tests)

**Interfaces:**
- Consumes: `CampaignsResponse`/`CampaignSummary`/`CampaignLeg`/`CalendarResponse`/`CalendarDay`/
  `CalendarEntry` (`components/portfolio/types.ts`), `optionStatus` and `FRESH_FOR_MINUTES`
  (`features/home/positions.ts`), `useClaudeContext`, `Dossier` (`features/claude-context/`),
  `shortDay` (`features/claude-context/format.ts`), `todayInNewYork` (`features/trades/time.ts`),
  `Card`, `Disclosure`, `SegmentedControl`, `StatusWord`, `formatStubValue`, `FigureLines`.
- Produces:
  - `FIELD`, `FIELD_LABEL` (`components/ui/field.ts`: the `field` component's classes; Tasks 9, 10, 11
    and 12 reuse them)
  - `usd(v)`, `shortDate(iso)`, `weekdayDate(iso)` (`features/portfolio/format.ts`)
  - `legTitle`, `threadSub` (`campaigns.ts`); `HORIZONS`, `DEFAULT_HORIZON`, `daysLeft`,
    `consequenceSentence`, `entryTitle` (`calendar.ts`)
  - `eventBefore(d: Dossier | undefined, today: string, expiry: string): string | null`
    (`features/market/market.ts`)
  - `CampaignsView()`, `CalendarView()` (Task 7). Campaigns reads `["portfolio","campaigns",
    status, symbol]`, Calendar `["portfolio","calendar",horizon]`: the keys `RefreshControl`
    invalidates by the `["portfolio"]` prefix.

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: thread and expiry-day cards on
  paper, the legs behind a disclosure, sentences for consequences, status words not colours.

- [x] **Step 2: Write the failing tests**

Create `web/features/portfolio/campaigns.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { CampaignSummary } from "@/components/portfolio/types";
import { legTitle, threadSub } from "./campaigns";

const leg = (over: Record<string, unknown> = {}) =>
  ({ as_of: "", candidate_id: "a", strategy: "cash_secured_put", right: "P", strike: 180, expiry: "2026-11-20", known: true, ...over }) as never;
const thread = (over: Record<string, unknown> = {}) =>
  ({ as_of: "", campaign_id: "c1", symbol: "NVDA", status: "open", opened_date: "2026-10-01", closed_date: null, legs: [leg(), leg({ candidate_id: "b" })], ...over }) as unknown as CampaignSummary;

describe("legTitle", () => {
  it("names the strategy, the strike and the side", () => {
    expect(legTitle(leg())).toBe("CSP $180 put");
    expect(legTitle(leg({ strategy: "covered_call", right: "C", strike: 72.5 }))).toBe("CC $72.5 call");
    expect(legTitle(leg({ strategy: "roll", right: "P" }))).toBe("Roll $180 put");
  });
  it("says what it does not know instead of guessing", () => {
    expect(legTitle(leg({ strike: null, right: null }))).toBe("CSP strike n/a option");
    expect(legTitle(leg({ strategy: "something_new" }))).toBe("something new $180 put");
  });
});

describe("threadSub", () => {
  it("says when an open thread began, with its leg count", () => {
    expect(threadSub(thread())).toBe("Opened Oct 1, 2026 · 2 legs");
  });
  it("gives a closed thread's span, and a singular leg", () => {
    expect(threadSub(thread({ status: "closed", closed_date: "2026-10-20", legs: [leg()] }))).toBe(
      "Oct 1, 2026 to Oct 20, 2026 · 1 leg",
    );
  });
});
```

Create `web/features/portfolio/CampaignsView.test.tsx`:

```tsx
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { CampaignsView } from "./CampaignsView";

const leg = (id: string, over: Record<string, unknown> = {}) => ({
  as_of: "", candidate_id: id, strategy: "cash_secured_put", right: "P", strike: 180,
  expiry: "2026-11-20", known: true, ...over,
});
const campaign = (over: Record<string, unknown> = {}) => ({
  as_of: "", campaign_id: "c1", symbol: "NVDA", status: "open", opened_date: "2026-10-01",
  closed_date: null, legs: [leg("a"), leg("b")], total_premium_collected: 600, total_debit_paid: 0,
  net_premium: 600, assigned: false, adjusted_cost_basis: null, realized_stock_pnl: null, ...over,
});
const serve = (campaigns: unknown[]) =>
  renderWithQuery(<CampaignsView />, { "/portfolio/campaigns": { as_of: "", campaigns } });
const campaignCalls = () => apiFetchMock.mock.calls.map((c) => c[0]).filter((p) => String(p).startsWith("/portfolio/campaigns"));

describe("CampaignsView", () => {
  it("shows a thread with its status, its dates and its net premium, said to be before commissions", async () => {
    serve([campaign()]);
    expect(await screen.findByRole("heading", { name: "NVDA" })).toBeInTheDocument();
    const card = screen.getByRole("article");
    // "Open" is also a chip above the list, so the status word is read inside the card.
    expect(within(card).getByText("Open")).toBeInTheDocument();
    expect(within(card).getByText("Opened Oct 1, 2026 · 2 legs")).toBeInTheDocument();
    expect(within(card).getByText("+$600.00")).toBeInTheDocument();
    expect(within(card).getByText("net premium, before commissions")).toBeInTheDocument();
  });

  it("gives a closed thread's span and writes a loss with a real minus", async () => {
    serve([campaign({ status: "closed", closed_date: "2026-10-20", net_premium: -120 })]);
    const card = (await screen.findByRole("heading", { name: "NVDA" })).closest("article") as HTMLElement;
    expect(within(card).getByText("Oct 1, 2026 to Oct 20, 2026 · 2 legs")).toBeInTheDocument();
    expect(within(card).getByText("Closed")).toBeInTheDocument();
    expect(within(card).getByText("−$120.00")).toBeInTheDocument();
  });

  it("shows an assigned thread's adjusted cost basis and realised stock P&L, and an unassigned one's neither", async () => {
    serve([
      campaign({ assigned: true, adjusted_cost_basis: 172.4, realized_stock_pnl: 250 }),
      campaign({ campaign_id: "c2", symbol: "AMD" }),
    ]);
    const group = await screen.findByRole("group", { name: "NVDA assigned shares" });
    expect(within(group).getByText("$172.40")).toBeInTheDocument();
    expect(within(group).getByText("+$250.00")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "AMD assigned shares" })).toBeNull();
  });

  it("renders an unknown basis as a hatched n/a, never $0", async () => {
    serve([campaign({ assigned: true, adjusted_cost_basis: null, realized_stock_pnl: null })]);
    const group = await screen.findByRole("group", { name: "NVDA assigned shares" });
    const na = within(group).getAllByText("n/a");
    expect(na).toHaveLength(2);
    expect(na[0].closest("dd")).toHaveClass("hatch");
    expect(screen.queryByText("$0")).toBeNull();
  });

  it("keeps the legs behind a disclosure, and says when a leg's record was pruned", async () => {
    serve([campaign({ legs: [leg("a"), leg("b", { known: false, right: null, strike: null, expiry: null })] })]);
    const known = await screen.findByText("CSP $180 put");
    expect(known).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /2 legs/ }));
    expect(known).toBeVisible();
    expect(screen.getByText("Leg unavailable")).toBeVisible();
    expect(screen.getByText("b")).toBeInTheDocument();
  });

  it("asks the API for the chosen status and symbol, not a client-side filter", async () => {
    serve([campaign()]);
    await screen.findByRole("heading", { name: "NVDA" });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    await waitFor(() => expect(campaignCalls()).toContain("/portfolio/campaigns?status=open"));
    fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "nvda" } });
    await waitFor(() => expect(campaignCalls()).toContain("/portfolio/campaigns?status=open&symbol=NVDA"));
    expect(campaignCalls()).toContain("/portfolio/campaigns");
  });

  it("says nothing matches the filters, in words", async () => {
    serve([]);
    expect(await screen.findByText("No campaigns match the current filters.")).toBeInTheDocument();
  });

  it("says it could not load, and that it tries again", async () => {
    renderWithQuery(<CampaignsView />, {});
    expect(await screen.findByText("Could not load campaigns.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every 30 seconds.")).toBeInTheDocument();
  });
});
```

Create `web/features/portfolio/calendar.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { consequenceSentence, daysLeft, entryTitle, expiryLabel } from "./calendar";

describe("calendar words", () => {
  it("says how long is left", () => {
    expect(daysLeft(0)).toBe("today");
    expect(daysLeft(1)).toBe("1 day left");
    expect(daysLeft(28)).toBe("28 days left");
  });
  it("writes each consequence as a sentence, and keeps unknown a named state", () => {
    expect(consequenceSentence("assigned")).toBe("Assigned: shares change hands");
    expect(consequenceSentence("called_away")).toBe("Called away: shares are sold");
    expect(consequenceSentence("expires_worthless")).toBe("Expires worthless");
    expect(consequenceSentence("unknown")).toBe("Consequence unknown");
  });
  it("titles a contract by its ticker, strike and side", () => {
    expect(entryTitle({ underlying: "AAPL", strike: 180, right: "P" } as never)).toBe("AAPL $180 put");
    expect(entryTitle({ underlying: "KO", strike: 72.5, right: "C" } as never)).toBe("KO $72.5 call");
  });
  it("reads an expiry as written, in the weekday form", () => {
    expect(expiryLabel("2026-11-20")).toBe("Fri, Nov 20");
  });
});
```

Create `web/features/portfolio/CalendarView.test.tsx`:

```tsx
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { shortDay } from "@/features/claude-context/format";
import { shiftDay, todayInNewYork } from "@/features/trades/time";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { expiryLabel } from "./calendar";
import { CalendarView } from "./CalendarView";

const today = todayInNewYork();
const expiry = shiftDay(today, 30);
const ago = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
const entry = (over: Record<string, unknown> = {}) => ({
  as_of: "", symbol: "AAPL  991120P00180000", underlying: "AAPL", right: "P", strike: 180,
  contracts: 1, short: true, moneyness: "otm", consequence: "expires_worthless",
  assignment_risk: false, ...over,
});
const day = (entries: unknown[], over: Record<string, unknown> = {}) => ({ as_of: "", expiry, dte: 30, entries, ...over });
const calendar = (days: unknown[], over: Record<string, unknown> = {}) => ({
  as_of: new Date().toISOString(), source: "monitor", degraded: false, horizon_days: 45, days, ...over,
});
const event = (on: string) => ({ id: "E1", title: "Earnings", on, evidence: "C1", quote: "q" });
const serve = (cal: unknown, dossiers: unknown[] = []) =>
  renderWithQuery(<CalendarView />, {
    "/portfolio/calendar": cal,
    "/claude/context": { available: true, dossiers },
  });

describe("CalendarView", () => {
  it("groups the contracts by expiry day, with the date, the days left and a sentence for each", async () => {
    serve(calendar([day([entry()])]));
    const card = await screen.findByRole("region", { name: `Expiries on ${expiryLabel(expiry)}` });
    expect(within(card).getByText("30 days left")).toBeInTheDocument();
    expect(within(card).getByText("AAPL $180 put")).toBeInTheDocument();
    expect(within(card).getByText("Short · 1 contract")).toBeInTheDocument();
    expect(within(card).getByText("Expires worthless")).toBeInTheDocument();
  });

  it("writes each consequence, and never calls an unknown one worthless", async () => {
    serve(
      calendar([
        day([
          entry({ symbol: "a", consequence: "assigned" }),
          entry({ symbol: "b", consequence: "called_away" }),
          entry({ symbol: "c", consequence: "unknown" }),
        ]),
      ]),
    );
    expect(await screen.findByText("Assigned: shares change hands")).toBeInTheDocument();
    expect(screen.getByText("Called away: shares are sold")).toBeInTheDocument();
    expect(screen.getByText("Consequence unknown")).toBeInTheDocument();
    expect(screen.queryByText("Expires worthless")).toBeNull();
  });

  it("flags an in-the-money short, and says Assignment likely once when the monitor does", async () => {
    serve(
      calendar([
        day([
          entry({ symbol: "a", moneyness: "itm" }),
          entry({ symbol: "b", underlying: "KO", strike: 60, moneyness: "itm", assignment_risk: true }),
        ]),
      ]),
    );
    expect(await screen.findByText("In the money")).toBeInTheDocument();
    expect(screen.getAllByText("Assignment likely")).toHaveLength(1);
  });

  it("says Expires today and still flags assignment risk on the day itself", async () => {
    serve(calendar([day([entry({ moneyness: "itm", assignment_risk: true })], { expiry: today, dte: 0 })]));
    expect(await screen.findByText("Expires today")).toBeInTheDocument();
    expect(screen.getByText("Assignment likely")).toBeInTheDocument();
    expect(screen.getByText("today")).toBeInTheDocument();
  });

  it("says a moneyness it does not have is n/a, not out of the money", async () => {
    serve(calendar([day([entry({ moneyness: null })])]));
    const row = (await screen.findByText("AAPL $180 put")).closest("li") as HTMLElement;
    expect(within(row).getByText("n/a")).toHaveClass("hatch");
    expect(within(row).queryByText("Out of the money")).toBeNull();
  });

  it("marks a short whose name has a verified event before the expiry, by its date", async () => {
    const on = shiftDay(today, 10);
    serve(calendar([day([entry()])]), [{ symbol: "AAPL", health: "ok", events: [event(on)] }]);
    expect(await screen.findByText(`Event ${shortDay(on)} before expiry`)).toBeInTheDocument();
  });

  it("does not mark a long contract, an event after the expiry, or one already past", async () => {
    const soon = shiftDay(today, 10);
    serve(
      calendar([
        day([
          entry({ symbol: "long", short: false }),
          entry({ symbol: "short" }),
          entry({ symbol: "ko", underlying: "KO", strike: 60 }),
        ]),
      ]),
      [
        { symbol: "AAPL", health: "ok", events: [event(soon)] },
        { symbol: "KO", health: "ok", events: [event(shiftDay(expiry, 5)), event(shiftDay(today, -3))] },
      ],
    );
    // The short AAPL's word proves the notes have loaded; it is the only one on the page.
    await screen.findByText(`Event ${shortDay(soon)} before expiry`);
    expect(screen.getAllByText(/before expiry/)).toHaveLength(1);
  });

  it("asks the API for the chosen horizon", async () => {
    serve(calendar([day([entry()])]));
    await screen.findByText("AAPL $180 put");
    fireEvent.click(screen.getByRole("button", { name: "90 days" }));
    await screen.findByText("AAPL $180 put");
    const calls = apiFetchMock.mock.calls.map((c) => c[0]);
    expect(calls).toContain("/portfolio/calendar?horizon_days=45");
    expect(calls).toContain("/portfolio/calendar?horizon_days=90");
  });

  it("says no snapshot has been captured when the source is none", async () => {
    serve(calendar([], { source: "none", degraded: true }));
    expect(await screen.findByText("No portfolio snapshot has been captured yet.")).toBeInTheDocument();
  });

  it("says no option expires inside the horizon when the reading is real and empty", async () => {
    serve(calendar([], { horizon_days: 14 }));
    expect(await screen.findByText("No option expiries within the next 14 days.")).toBeInTheDocument();
  });

  it("says Delayed and the age when the reading is old", async () => {
    serve(calendar([day([entry()])], { as_of: ago(3), source: "eod", degraded: true }));
    expect(await screen.findByText("Delayed")).toBeInTheDocument();
    expect(screen.getByText(/3h ago/)).toBeInTheDocument();
  });

  it("says it could not load, and that it tries again", async () => {
    renderWithQuery(<CalendarView />, {});
    expect(await screen.findByText("Could not load the calendar.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every 30 seconds.")).toBeInTheDocument();
  });
});
```

  Append to the end of `web/features/market/market.test.tsx` (and add `eventBefore` to its
  `./market` import):

```tsx
describe("eventBefore", () => {
  const dossier = (...on: string[]) =>
    ({
      symbol: "AAPL",
      events: on.map((o, i) => ({ id: `E${i}`, title: "t", on: o, evidence: "C1", quote: "q" })),
    }) as never;
  it("is the nearest verified event from today up to and including the expiry", () => {
    expect(eventBefore(dossier("2026-11-10", "2026-10-27"), "2026-10-23", "2026-11-20")).toBe("2026-10-27");
    expect(eventBefore(dossier("2026-11-20"), "2026-10-23", "2026-11-20")).toBe("2026-11-20");
    expect(eventBefore(dossier("2026-10-23"), "2026-10-23", "2026-11-20")).toBe("2026-10-23");
  });
  it("ignores an event already past or after the expiry", () => {
    expect(eventBefore(dossier("2026-10-20", "2026-11-25"), "2026-10-23", "2026-11-20")).toBeNull();
  });
  it("is null with no notes or no events", () => {
    expect(eventBefore(undefined, "2026-10-23", "2026-11-20")).toBeNull();
    expect(eventBefore(dossier(), "2026-10-23", "2026-11-20")).toBeNull();
  });
});
```

- [x] **Step 3: Run them to verify they fail**

Run: `cd web && npx vitest run features/portfolio features/market`
Expected: FAIL (modules and `eventBefore` not found).

- [x] **Step 4: Implement the small files**

`web/components/ui/field.ts`:

```ts
/**
 * The `field` component's classes (web/DESIGN.md Components → Field), shared by every labelled
 * input and select: 16px text so iOS does not zoom, a control-edge border, an ink focus ring.
 */
export const FIELD =
  "min-h-11 rounded-xl border border-control bg-surface px-3 text-base text-content placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export const FIELD_LABEL = "text-xs font-semibold tracking-[0.04em] text-muted";
```

`web/features/portfolio/format.ts`:

```ts
const DATE = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const WEEKDAY = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });

/** "$180", "$72.5": a strike or a basis in dollars, cents only when there are some. */
export const usd = (v: number): string => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

/** "Oct 15, 2026" for a "YYYY-MM-DD" date, read as written so it never shifts with the viewer's zone. */
export const shortDate = (iso: string): string => DATE.format(new Date(`${iso}T00:00:00Z`));

/** "Fri, Nov 20" for a "YYYY-MM-DD" date, read as written. */
export const weekdayDate = (iso: string): string => WEEKDAY.format(new Date(`${iso}T00:00:00Z`));
```

`web/features/portfolio/campaigns.ts`:

```ts
import type { CampaignLeg, CampaignSummary } from "@/components/portfolio/types";
import { shortDate, usd } from "./format";

const KIND: Record<string, string> = { cash_secured_put: "CSP", covered_call: "CC", roll: "Roll" };

/** "CSP $180 put" for a leg; a strike or side the API lacks is said, never guessed. */
export function legTitle(l: CampaignLeg): string {
  const side = l.right === "P" ? "put" : l.right === "C" ? "call" : "option";
  const strike = typeof l.strike === "number" ? usd(l.strike) : "strike n/a";
  return `${KIND[l.strategy] ?? l.strategy.replace(/_/g, " ")} ${strike} ${side}`;
}

/** When the thread began (and ended), with its leg count. */
export function threadSub(c: CampaignSummary): string {
  const n = c.legs.length;
  const legs = `${n} ${n === 1 ? "leg" : "legs"}`;
  return c.closed_date
    ? `${shortDate(c.opened_date)} to ${shortDate(c.closed_date)} · ${legs}`
    : `Opened ${shortDate(c.opened_date)} · ${legs}`;
}
```

`web/features/portfolio/calendar.ts`:

```ts
import type { CalendarEntry } from "@/components/portfolio/types";
import { usd, weekdayDate } from "./format";

export const HORIZONS = [14, 30, 45, 90, 180] as const;
export const DEFAULT_HORIZON = 45; // the API's own default

export const expiryLabel = weekdayDate;

export function daysLeft(dte: number): string {
  return dte <= 0 ? "today" : dte === 1 ? "1 day left" : `${dte} days left`;
}

/**
 * What happens at expiry. `unknown` is a named state, not a default: the API was told never to
 * report an unknown consequence as an expiry worthless, and this never does either.
 */
export function consequenceSentence(c: CalendarEntry["consequence"]): string {
  switch (c) {
    case "assigned":
      return "Assigned: shares change hands";
    case "called_away":
      return "Called away: shares are sold";
    case "expires_worthless":
      return "Expires worthless";
    case "unknown":
      return "Consequence unknown";
  }
}

export function entryTitle(e: Pick<CalendarEntry, "underlying" | "strike" | "right">): string {
  return `${e.underlying} ${usd(e.strike)} ${e.right === "P" ? "put" : "call"}`;
}
```

In `web/features/market/market.ts`, add after `nameFlags`:

```ts
/**
 * The nearest verified event date from today up to and including an expiry, or null. The dates are
 * the ones Python checked against the cited news; an event's title is Claude's and is not read here.
 */
export function eventBefore(d: Dossier | undefined, today: string, expiry: string): string | null {
  const dates = (d?.events ?? []).map((e) => e.on).filter((on) => on >= today && on <= expiry).sort();
  return dates[0] ?? null;
}
```

- [x] **Step 5: Implement `web/features/portfolio/CampaignsView.tsx`**

```tsx
"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import type { CampaignLeg, CampaignSummary, CampaignsResponse } from "@/components/portfolio/types";
import { Card } from "@/components/ui/Card";
import { Disclosure } from "@/components/ui/Disclosure";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { formatStubValue } from "@/components/ui/Stub";
import { FigureLines } from "@/features/claude-context/FigureLines";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import { legTitle, threadSub } from "./campaigns";
import { shortDate } from "./format";

type StatusFilter = "all" | "open" | "closed";
const STATUS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
];

function Leg({ leg }: { leg: CampaignLeg }) {
  const row = "flex items-center justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0";
  if (!leg.known) {
    // The scan's record of this leg was pruned: the leg stays, with its id, and says why it is bare.
    return (
      <li className={row}>
        <span className="text-muted">Leg unavailable</span>
        <span className="font-mono text-xs text-muted">{leg.candidate_id}</span>
      </li>
    );
  }
  return (
    <li className={row}>
      <span className="font-semibold">{legTitle(leg)}</span>
      <span className="text-[0.8125rem] text-muted">
        {leg.expiry ? shortDate(leg.expiry) : <span className="hatch text-unknown">{UNKNOWN}</span>}
      </span>
    </li>
  );
}

function Thread({ c }: { c: CampaignSummary }) {
  const titleId = `campaign-${c.campaign_id}`;
  const net = c.net_premium;
  const basis = c.adjusted_cost_basis;
  const stock = c.realized_stock_pnl;
  return (
    <Card as="article" aria-labelledby={titleId}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={titleId} className="inline text-[1.0625rem] font-bold">
            {c.symbol}
          </h3>
          <span className="ml-1.5 align-[1px]">
            <StatusWord>{c.status === "open" ? "Open" : "Closed"}</StatusWord>
          </span>
          <div className="text-[0.8125rem] text-muted">{threadSub(c)}</div>
        </div>
        <div className="tabular text-right font-mono font-semibold">
          <span className={clsx(net < 0 && "text-loss", net > 0 && "text-gain")}>
            {formatStubValue(net, "signed-money")}
          </span>
          <div className="font-sans text-[0.8125rem] font-normal text-muted">net premium, before commissions</div>
        </div>
      </div>
      {c.assigned && (
        <FigureLines
          label={`${c.symbol} assigned shares`}
          rows={[
            {
              label: "Adjusted cost basis",
              value: basis === null || basis === undefined ? UNKNOWN : formatMoneyCell(basis),
              unknown: basis === null || basis === undefined,
            },
            {
              label: "Realised stock P&L",
              value: stock === null || stock === undefined ? UNKNOWN : formatStubValue(stock, "signed-money"),
              unknown: stock === null || stock === undefined,
            },
          ]}
        />
      )}
      <div className="mt-3">
        <Disclosure summary={<span className="text-sm font-semibold">{c.legs.length} {c.legs.length === 1 ? "leg" : "legs"}</span>}>
          <ul>
            {c.legs.map((l) => (
              <Leg key={l.candidate_id} leg={l} />
            ))}
          </ul>
        </Disclosure>
      </div>
    </Card>
  );
}

/**
 * The wheel threads, one card per symbol. Status and symbol go to the API (a filter is a real
 * refetch, never a client-side narrowing of a list that may be partial). The money is the API's
 * campaign figures, which are before commissions, and the card says so.
 */
export function CampaignsView() {
  const [status, setStatus] = useState<StatusFilter>("all");
  const [symbol, setSymbol] = useState("");
  const symbolId = useId();
  const sym = symbol.trim().toUpperCase();

  const { data, isError } = useQuery({
    queryKey: ["portfolio", "campaigns", status === "all" ? "" : status, sym],
    queryFn: () => {
      const params = new URLSearchParams();
      if (status !== "all") params.set("status", status);
      if (sym) params.set("symbol", sym);
      const qs = params.toString();
      return apiFetch<CampaignsResponse>(`/portfolio/campaigns${qs ? `?${qs}` : ""}`);
    },
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <SegmentedControl label="Status" appearance="chips" options={STATUS} value={status} onChange={setStatus} />
        <div className="grid gap-1">
          <label htmlFor={symbolId} className={FIELD_LABEL}>
            Symbol
          </label>
          <input
            id={symbolId}
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="NVDA"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            className={clsx(FIELD, "w-32")}
          />
        </div>
      </div>
      {isError && !data ? (
        <div className="text-sm text-muted">
          <p>Could not load campaigns.</p>
          <p className="mt-1 text-[0.8125rem]">It tries again every 30 seconds.</p>
        </div>
      ) : !data ? (
        <div role="status" aria-busy="true" aria-label="Loading campaigns" className="h-24 rounded-[18px] bg-surface" />
      ) : data.campaigns.length === 0 ? (
        <p className="py-3 text-sm text-muted">No campaigns match the current filters.</p>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {data.campaigns.map((c) => (
            <Thread key={c.campaign_id} c={c} />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [x] **Step 6: Implement `web/features/portfolio/CalendarView.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { FreshnessLabel } from "@/components/portfolio/FreshnessLabel";
import type { CalendarDay, CalendarEntry, CalendarResponse } from "@/components/portfolio/types";
import { Card } from "@/components/ui/Card";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { shortDay } from "@/features/claude-context/format";
import type { Dossier } from "@/features/claude-context/types";
import { useClaudeContext } from "@/features/claude-context/useClaudeContext";
import { FRESH_FOR_MINUTES, optionStatus } from "@/features/home/positions";
import { eventBefore } from "@/features/market/market";
import { todayInNewYork } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { isStale } from "@/lib/money";
import {
  DEFAULT_HORIZON,
  HORIZONS,
  consequenceSentence,
  daysLeft,
  entryTitle,
  expiryLabel,
} from "./calendar";

function Entry({
  e,
  day,
  today,
  dossier,
}: {
  e: CalendarEntry;
  day: CalendarDay;
  today: string;
  dossier: Dossier | undefined;
}) {
  const status = optionStatus(
    { expiry: day.expiry, dte: day.dte, assignment_risk: e.assignment_risk, moneyness: e.moneyness },
    today,
  );
  // "Expires today" shadows the monitor's flag on the day itself, so the flag is said as well.
  const alsoAssignment = e.assignment_risk && status?.word !== "Assignment likely";
  // Only a short has a reason to care that news is due before it expires.
  const event = e.short ? eventBefore(dossier, today, day.expiry) : null;
  return (
    <li className="border-t border-border py-[11px] first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-sm">
          <span className="font-bold">{entryTitle(e)}</span>
          {status && (
            <span className="ml-1.5 align-[1px]">
              <StatusWord tone={status.tone}>{status.word}</StatusWord>
            </span>
          )}
          {alsoAssignment && (
            <span className="ml-1.5 align-[1px]">
              <StatusWord tone="flag">Assignment likely</StatusWord>
            </span>
          )}
          {event && (
            <span className="ml-1.5 align-[1px]">
              <StatusWord>{`Event ${shortDay(event)} before expiry`}</StatusWord>
            </span>
          )}
          <div className="text-[0.8125rem] text-muted">
            {e.short ? "Short" : "Long"} · {e.contracts} contract{e.contracts === 1 ? "" : "s"}
          </div>
          {e.moneyness === null && (
            <div className="text-[0.8125rem] text-muted">
              Moneyness <span className="hatch text-unknown">{UNKNOWN}</span>
            </div>
          )}
        </div>
        <div className="text-right text-sm">{consequenceSentence(e.consequence)}</div>
      </div>
    </li>
  );
}

/**
 * The expiry calendar: what expires when, and what happens when it does. The horizon goes to the
 * API. A short whose name has a verified event date before its expiry carries that date as a word
 * (the news service's notes, read through the same request the rest of the app shares).
 */
export function CalendarView() {
  const [horizon, setHorizon] = useState<number>(DEFAULT_HORIZON);
  const { data, isError } = useQuery({
    queryKey: ["portfolio", "calendar", horizon],
    queryFn: () => apiFetch<CalendarResponse>(`/portfolio/calendar?horizon_days=${horizon}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const notes = useClaudeContext();
  const today = todayInNewYork();
  const dossierOf = (symbol: string) => notes.data?.dossiers?.find((d) => d.symbol === symbol.toUpperCase());

  const delayed =
    data !== undefined && data.source !== "none" && (data.degraded || isStale(data.as_of, FRESH_FOR_MINUTES));

  return (
    <div className="grid gap-3">
      <SegmentedControl
        label="Horizon"
        appearance="chips"
        options={HORIZONS.map((h) => ({ value: String(h), label: `${h} days` }))}
        value={String(horizon)}
        onChange={(v) => setHorizon(Number(v))}
      />
      {delayed && (
        <p className="flex flex-wrap items-center gap-2">
          <StatusWord tone="flag">Delayed</StatusWord>
          <FreshnessLabel asOf={data!.as_of} freshForMinutes={FRESH_FOR_MINUTES} />
        </p>
      )}
      {isError && !data ? (
        <div className="text-sm text-muted">
          <p>Could not load the calendar.</p>
          <p className="mt-1 text-[0.8125rem]">It tries again every 30 seconds.</p>
        </div>
      ) : !data ? (
        <div role="status" aria-busy="true" aria-label="Loading the calendar" className="h-24 rounded-[18px] bg-surface" />
      ) : data.days.length === 0 ? (
        <p className="py-3 text-sm text-muted">
          {data.source === "none"
            ? "No portfolio snapshot has been captured yet."
            : `No option expiries within the next ${data.horizon_days} days.`}
        </p>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {data.days.map((d) => {
            const label = expiryLabel(d.expiry);
            return (
              <Card as="section" key={d.expiry} aria-label={`Expiries on ${label}`}>
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="text-[1.0625rem] font-bold">{label}</h3>
                  <span className="text-[0.8125rem] text-muted">{daysLeft(d.dte)}</span>
                </div>
                <ul className="mt-1">
                  {d.entries.map((e) => (
                    <Entry key={e.symbol} e={e} day={d} today={today} dossier={dossierOf(e.underlying)} />
                  ))}
                </ul>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [x] **Step 7: Run the tests, then the gate**

Run: `cd web && npx vitest run features/portfolio features/market && npx tsc --noEmit && npm run lint`
Expected: PASS: Campaigns (4 + 8) and Calendar (4 + 12) tests and the 3 `eventBefore` tests; every
existing `market` test unchanged.

- [x] **Step 8: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/portfolio web/components/ui/field.ts web/features/market/market.ts`
Expected: exit 0, or every finding fixed in the code.

- [x] **Step 9: Commit** (with the Progress log row for Task 6 filled in)

```bash
git add web/components/ui/field.ts web/features/portfolio web/features/market/market.ts \
  web/features/market/market.test.tsx docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): Portfolio Campaigns and Calendar - threads before commissions, event words on expiries"
```

---

### Task 7: The Portfolio page at `/portfolio`

**Files:**
- Create: `web/features/portfolio/views.ts`, `web/features/portfolio/PortfolioPage.tsx`,
  `web/features/portfolio/PortfolioPage.test.tsx`
- Modify: `web/app/portfolio/page.tsx`

**Interfaces:**
- Consumes: `useViewParam` (Task 4), `SummaryCard` (Task 4), `PositionsView` (Task 5),
  `CampaignsView`, `CalendarView` (Task 6), `RefreshControl`, `SegmentedControl`.
- Produces: `PortfolioPage()`; `PORTFOLIO_VIEWS`, `VIEW_LABEL`, `PortfolioView` (`views.ts`).

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: the page frame only; the title
  with Refresh at its right, the Account card, the view chips, the view.

- [x] **Step 2: Write the failing tests** — create `web/features/portfolio/PortfolioPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
// test-query registers the @/lib/api mock when it is evaluated, so it must load before anything
// that imports @/lib/api (RefreshControl does through lib/commands).
import { apiFetchMock } from "@/lib/test-query";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/portfolio",
}));

import { PortfolioPage } from "./PortfolioPage";

const now = () => new Date().toISOString();
const sourced = (value: number) => ({ value, source: "ibkr", as_of: now(), stale: false });

function serve() {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === "/portfolio/summary") {
      return {
        as_of: now(), source: "monitor", degraded: false, note: null,
        account: {
          as_of: now(), net_liquidation: sourced(125_000), total_cash: sourced(1), buying_power: sourced(1),
          maintenance_margin: sourced(1), excess_liquidity: sourced(1),
        },
        exposure: {
          as_of: now(), open_positions: 1, open_shorts: 1, open_campaigns: 1, net_delta_exposure: 0,
          cash_secured_against_puts: 0, buying_power_utilisation_pct: 1, shorts_at_assignment_risk: 0,
        },
      };
    }
    if (path === "/portfolio/positions") return { as_of: now(), source: "monitor", degraded: false, groups: [] };
    if (path.startsWith("/spreads/positions")) return { as_of: "", available: true, underlying: "SPY", mode: "paper", positions: [] };
    if (path === "/options/shorts") return { as_of: "", shorts: [] };
    if (path === "/claude/context") return { available: false, dossiers: [] };
    if (path.startsWith("/portfolio/campaigns")) return { as_of: "", campaigns: [] };
    if (path.startsWith("/portfolio/calendar")) {
      return { as_of: now(), source: "monitor", degraded: false, horizon_days: 45, days: [] };
    }
    if (path === "/options/controls") {
      return { as_of: "", autonomy: { level: "full", label: "Full" }, rungs: [], halted: false, mode: "paper", drain_healthy: true, drain_last_seen: null, pending_commands: 0 };
    }
    throw new Error(`no mocked response for ${path}`);
  });
}

const summaryCalls = () => apiFetchMock.mock.calls.filter((c) => c[0] === "/portfolio/summary").length;
const tree = (qc: QueryClient) => (
  <QueryClientProvider client={qc}>
    <PortfolioPage />
  </QueryClientProvider>
);
const mount = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const r = render(tree(qc));
  return { rerenderPage: () => r.rerender(tree(qc)) };
};

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
  serve();
});

describe("PortfolioPage", () => {
  it("opens on Positions with the three view chips, the Account card above them and Refresh in the header", async () => {
    mount();
    expect(screen.getByRole("heading", { level: 1, name: "Portfolio" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(await screen.findByText("No open positions.")).toBeInTheDocument();
    const views = screen.getByRole("group", { name: "View" });
    expect(within(views).getByRole("button", { name: "Positions" })).toHaveAttribute("aria-pressed", "true");
    expect(within(views).getByRole("button", { name: "Campaigns" })).toHaveAttribute("aria-pressed", "false");
    expect(within(views).getByRole("button", { name: "Calendar" })).toHaveAttribute("aria-pressed", "false");
    expect(await screen.findByText("$125,000.00")).toBeInTheDocument();
  });

  it("opens the view the URL asks for, and Positions for one it does not know", async () => {
    nav.params = new URLSearchParams("view=campaigns");
    const page = mount();
    expect(await screen.findByText("No campaigns match the current filters.")).toBeInTheDocument();
    nav.params = new URLSearchParams("view=bogus");
    page.rerenderPage();
    expect(await screen.findByText("No open positions.")).toBeInTheDocument();
  });

  it("writes the chosen view into the URL", async () => {
    mount();
    await screen.findByText("No open positions.");
    fireEvent.click(screen.getByRole("button", { name: "Calendar" }));
    expect(nav.replace).toHaveBeenCalledWith("/portfolio?view=calendar", { scroll: false });
  });

  it("changing the view does not fetch the account summary again", async () => {
    // The mock's call log spans the whole file, so count from where this test starts.
    const before = summaryCalls();
    const page = mount();
    await screen.findByText("$125,000.00");
    expect(summaryCalls() - before).toBe(1);
    nav.params = new URLSearchParams("view=calendar");
    page.rerenderPage();
    expect(await screen.findByText("No option expiries within the next 45 days.")).toBeInTheDocument();
    expect(summaryCalls() - before).toBe(1);
  });
});
```

- [x] **Step 3: Run it to verify it fails**

Run: `cd web && npx vitest run features/portfolio/PortfolioPage.test.tsx`
Expected: FAIL (module not found).

- [x] **Step 4: Implement** — `web/features/portfolio/views.ts`:

```ts
/** The Portfolio page's views (web/DESIGN.md Surfaces → Portfolio). */
export type PortfolioView = "positions" | "campaigns" | "calendar";

export const PORTFOLIO_VIEWS: readonly PortfolioView[] = ["positions", "campaigns", "calendar"];

export const VIEW_LABEL: Record<PortfolioView, string> = {
  positions: "Positions",
  campaigns: "Campaigns",
  calendar: "Calendar",
};
```

`web/features/portfolio/PortfolioPage.tsx`:

```tsx
"use client";

import { RefreshControl } from "@/components/portfolio/RefreshControl";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useViewParam } from "@/lib/useViewParam";
import { CalendarView } from "./CalendarView";
import { CampaignsView } from "./CampaignsView";
import { PositionsView } from "./PositionsView";
import { SummaryCard } from "./SummaryCard";
import { PORTFOLIO_VIEWS, VIEW_LABEL } from "./views";

const SHELL = "mx-auto max-w-[1200px] px-4 py-5 md:px-7 md:py-6";

/**
 * Portfolio: the Account card, then Positions, Campaigns or Calendar, the view kept in the URL.
 * The Account card sits outside the switched view, so changing view never refetches it. Refresh is
 * the page's one write (the `refresh` command), through the unchanged RefreshControl.
 */
export function PortfolioPage() {
  const [view, setView] = useViewParam(PORTFOLIO_VIEWS, "positions");
  const options = PORTFOLIO_VIEWS.map((v) => ({ value: v, label: VIEW_LABEL[v] }));
  return (
    <div className={SHELL}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Portfolio</h1>
        <RefreshControl />
      </div>
      <div className="mt-4">
        <SummaryCard />
      </div>
      <div className="mt-4">
        <SegmentedControl label="View" appearance="chips" options={options} value={view} onChange={setView} />
      </div>
      <div className="mt-5">
        {view === "positions" && <PositionsView />}
        {view === "campaigns" && <CampaignsView />}
        {view === "calendar" && <CalendarView />}
      </div>
    </div>
  );
}
```

Replace `web/app/portfolio/page.tsx` with:

```tsx
import { Suspense } from "react";
import { PortfolioPage } from "@/features/portfolio/PortfolioPage";

// useSearchParams (the view) needs a Suspense boundary under the App Router.
export default function Page() {
  return (
    <Suspense>
      <PortfolioPage />
    </Suspense>
  );
}
```

  `components/portfolio/PortfolioShell.tsx` is now unmounted; it and its legacy panels stay for
  their tests until Part 4 (ruling 12). Do not edit them.

- [x] **Step 5: Run the tests, then the gate**

Run: `cd web && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: PASS: 4 new tests; every legacy portfolio test (`PortfolioShell`, `SummaryPanel`,
`PositionGroup`, `CalendarPanel`, `CampaignThread`, `RefreshControl`) still green and unmodified.

- [x] **Step 6: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/portfolio web/app/portfolio`
Expected: exit 0, or every finding fixed in the code.

- [x] **Step 7: Commit** (with the Progress log row for Task 7 filled in)

```bash
git add web/features/portfolio/views.ts web/features/portfolio/PortfolioPage.tsx \
  web/features/portfolio/PortfolioPage.test.tsx web/app/portfolio/page.tsx \
  docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): the Portfolio page - Account card, Positions, Campaigns, Calendar in the URL"
```

---

## Section C — Activity (Tasks 8–14) · model: sonnet (effort xhigh)

Pay (a month, the totals, the curve, the legs), Ledger, Fills and orders, System, then the page.
Where a legacy component keeps its job it is restyled **in place and its existing tests pass
unmodified**; where the composition changes the component is new. The restyle recipe, applied
everywhere in this section:

- a card is `Card` (white on paper, no border, no shadow); a row inside it is a hairline
  `border-t border-border` with `first:border-t-0`;
- a label above a figure or a column is the `label` type: `text-xs font-semibold tracking-[0.04em]
  text-muted`, never `uppercase` and never below 12px;
- figures are `tabular` and, in lists and ledgers, `font-mono`;
- a state is a `StatusWord` or a sentence, never a coloured dot or pill;
- an input or select uses `FIELD` / `FIELD_LABEL` from `components/ui/field.ts`;
- a table that stays a table sits in `overflow-x-auto`, so only it scrolls on a phone.

**Entry checks (run before Task 8):**

- [ ] **C1. Section B landed.** `git log --oneline main..HEAD` shows seven commits (plus any
  review fix passes recorded in the Progress log); Tasks 1–7 are ticked.
- [ ] **C2. Gates and a production build green.** `python -m pytest -q && ruff check . && mypy src`,
  `cd web && npx vitest run && npx tsc --noEmit && npm run lint`, then the build in a scratch copy
  (never inside `web/`, whose `.next` the operator's dev server shares):

  ```bash
  S="$(mktemp -d)/web" && rsync -a --exclude node_modules --exclude .next web/ "$S/" \
    && ln -s "$PWD/web/node_modules" "$S/node_modules" && (cd "$S" && npm run build)
  ```

- [ ] **C3. The pieces Section C builds on exist.** Each command prints at least one line:

  ```bash
  grep -n "export function payStubLines" web/features/home/PayCard.tsx
  grep -n "export const FIELD" web/components/ui/field.ts
  grep -n "export function useViewParam" web/lib/useViewParam.ts
  grep -n "export function Sheet" web/components/ui/Sheet.tsx
  grep -n "export function SegmentedControl" web/components/ui/SegmentedControl.tsx
  grep -n "export function SummaryCard" web/features/portfolio/SummaryCard.tsx
  ls web/components/pnl/SummaryPanel.tsx web/components/pnl/LedgerFilters.tsx web/components/ledger/LedgerOverview.tsx
  ```

- [ ] **C4. Nothing in features sends a command itself.** `grep -rn "submitCommand\|confirmCommand" web/features`
  prints only `web/features/more/TargetCard.tsx` and `web/features/more/TargetCard.test.tsx`.
- [ ] **C5. The protected files are untouched.** This prints nothing:

  ```bash
  git diff --stat main -- web/components/options/DecideControls.tsx web/components/options/ConfirmAction.tsx \
    web/components/options/CommandReceipt.tsx web/components/options/HaltControl.tsx \
    web/components/options/AutonomyControl.tsx web/components/options/RollModeControl.tsx \
    web/lib/commands.ts web/lib/receipt.ts
  ```

**Section exit:** seven more commits; `/activity` is the new page with four views; `/ledger`
redirects into it and the ledger's own pages say how to get back.

---

### Task 8: Pay — a month at a time, and the totals

**Files:**
- Create: `web/features/activity/month.ts`, `month.test.ts`, `useMonthParam.ts`, `useMonthParam.test.tsx`,
  `MonthStepper.tsx`, `MonthStepper.test.tsx`, `useLegFilters.ts`, `useLegFilters.test.ts`,
  `useEquity.ts`, `PayMonth.tsx`, `PayView.tsx`, `PayView.test.tsx`
- Modify: `web/components/portfolio/Money.tsx` (two label spans), `web/components/pnl/BreakdownTable.tsx`
  (whole file), `web/components/pnl/SummaryPanel.tsx` (three blocks)

**Interfaces:**
- Consumes: `payStubLines` (`features/home/PayCard.tsx`), `MonthPay`/`MonthPayResponse`
  (`features/home/types.ts`), `Stub`, `formatStubValue`, `Meter`, `StatusWord`, `Card`, `Button`,
  `SummaryPanel` (`components/pnl/SummaryPanel.tsx`), `EquityResponse`/`PnlLegData`
  (`components/pnl/types.ts`), `todayInNewYork`.
- Produces:
  - `month.ts`: `currentMonth(today: string): string`, `parseMonth(raw, current): string`,
    `shiftMonth(month, n): string`, `monthLabel(month): string`, `earliestMonth(startsAt): string | null`
  - `useMonthParam(current: string): [string, (m: string) => void]` (`?month=`, removed when it is
    the current month)
  - `MonthStepper({ month, current, floor, onChange })`
  - `useLegFilters()` → `{ filters, setFilters, book, setBook, formKey, viewLeg, qsString }`: the one
    filter state the totals, the curve and the legs share (Task 9)
  - `useEquity(qsString)` (the equity query under the shared key `["pnl","equity",qs]`)
  - `PayMonth({ month, current, floor, onMonth })`, `PayView()` (Task 14 mounts it; Task 9 extends it)

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: the month as a stub, always open
  here; a month stepper of quiet round buttons; totals as a card of figure lines; no new colour.

- [x] **Step 2: Write the failing tests**

Create `web/features/activity/month.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { currentMonth, earliestMonth, monthLabel, parseMonth, shiftMonth } from "./month";

describe("months", () => {
  it("takes the month from a New York day", () => {
    expect(currentMonth("2026-10-23")).toBe("2026-10");
  });
  it("accepts a real month no later than this one", () => {
    expect(parseMonth("2026-09", "2026-10")).toBe("2026-09");
    expect(parseMonth("2026-10", "2026-10")).toBe("2026-10");
  });
  it("falls back to this month for junk, a month that does not exist and a future month", () => {
    for (const raw of [null, undefined, "", "abc", "2026-13", "2026-00", "2026-9", "2026-10-01", "2027-01"]) {
      expect(parseMonth(raw, "2026-10"), String(raw)).toBe("2026-10");
    }
  });
  it("steps across a year boundary in both directions", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-10", 0)).toBe("2026-10");
    expect(shiftMonth("2026-10", -13)).toBe("2025-09");
  });
  it("names a month in words", () => {
    expect(monthLabel("2026-10")).toBe("October 2026");
    expect(monthLabel("2025-01")).toBe("January 2025");
  });
  it("finds the month the system began from the curve's start date", () => {
    expect(earliestMonth("2026-06-24")).toBe("2026-06");
    expect(earliestMonth(null)).toBeNull();
    expect(earliestMonth(undefined)).toBeNull();
    expect(earliestMonth("soon")).toBeNull();
  });
});
```

Create `web/features/activity/useMonthParam.test.tsx`:

```tsx
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/activity",
}));

import { useMonthParam } from "./useMonthParam";

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
});

describe("useMonthParam", () => {
  it("reads ?month=, and is this month for none, junk or a future month", () => {
    nav.params = new URLSearchParams("month=2026-09");
    expect(renderHook(() => useMonthParam("2026-10")).result.current[0]).toBe("2026-09");
    nav.params = new URLSearchParams("month=2027-01");
    expect(renderHook(() => useMonthParam("2026-10")).result.current[0]).toBe("2026-10");
    nav.params = new URLSearchParams();
    expect(renderHook(() => useMonthParam("2026-10")).result.current[0]).toBe("2026-10");
  });
  it("writes a past month and keeps the view", () => {
    nav.params = new URLSearchParams("view=pay");
    const { result } = renderHook(() => useMonthParam("2026-10"));
    act(() => result.current[1]("2026-08"));
    expect(nav.replace).toHaveBeenCalledWith("/activity?view=pay&month=2026-08", { scroll: false });
  });
  it("removes the parameter when the month chosen is this month", () => {
    nav.params = new URLSearchParams("view=pay&month=2026-08");
    const { result } = renderHook(() => useMonthParam("2026-10"));
    act(() => result.current[1]("2026-10"));
    expect(nav.replace).toHaveBeenCalledWith("/activity?view=pay", { scroll: false });
  });
  it("goes to the bare path when nothing else is left", () => {
    nav.params = new URLSearchParams("month=2026-08");
    const { result } = renderHook(() => useMonthParam("2026-10"));
    act(() => result.current[1]("2026-10"));
    expect(nav.replace).toHaveBeenCalledWith("/activity", { scroll: false });
  });
});
```

Create `web/features/activity/MonthStepper.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MonthStepper } from "./MonthStepper";

const stepper = (over: Partial<Parameters<typeof MonthStepper>[0]> = {}) => {
  const onChange = vi.fn();
  render(<MonthStepper month="2026-09" current="2026-10" floor={null} onChange={onChange} {...over} />);
  return onChange;
};

describe("MonthStepper", () => {
  it("names the month and steps back and forward", () => {
    const onChange = stepper();
    expect(screen.getByText("September 2026")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-08");
    fireEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-10");
  });
  it("offers This month only away from this month, and goes there", () => {
    const onChange = stepper();
    fireEvent.click(screen.getByRole("button", { name: "This month" }));
    expect(onChange).toHaveBeenCalledWith("2026-10");
  });
  it("has no This month on this month, and no way forward", () => {
    stepper({ month: "2026-10" });
    expect(screen.queryByRole("button", { name: "This month" })).toBeNull();
    expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
  });
  it("stops going back at the month the system began", () => {
    stepper({ month: "2026-06", floor: "2026-06" });
    expect(screen.getByRole("button", { name: "Previous month" })).toBeDisabled();
  });
  it("lets you go back when the floor is not known", () => {
    stepper({ month: "2020-01", floor: null });
    expect(screen.getByRole("button", { name: "Previous month" })).toBeEnabled();
  });
});
```

Create `web/features/activity/useLegFilters.test.ts`:

```ts
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useLegFilters } from "./useLegFilters";

describe("useLegFilters", () => {
  it("starts on both books with one query string", () => {
    const { result } = renderHook(() => useLegFilters());
    expect(result.current.book).toBe("all");
    expect(result.current.qsString).toBe("book=all");
  });
  it("puts the book into the same filters the other fields use", () => {
    const { result } = renderHook(() => useLegFilters());
    act(() => result.current.setBook("paper"));
    expect(result.current.book).toBe("paper");
    expect(result.current.qsString).toBe("book=paper");
  });
  it("drops empty filters from the query string and keeps the book", () => {
    const { result } = renderHook(() => useLegFilters());
    act(() => result.current.setFilters({ book: "live", outcome: "", since: "2026-09-01", until: "", symbol: "NVDA" }));
    expect(result.current.qsString).toBe("book=live&since=2026-09-01&symbol=NVDA");
  });
  it("adds the book when the filters name none", () => {
    const { result } = renderHook(() => useLegFilters());
    act(() => result.current.setFilters({ symbol: "AMD" }));
    expect(result.current.qsString).toBe("symbol=AMD&book=all");
  });
  it("sets the symbol from a leg and remounts the filter form once", () => {
    const { result } = renderHook(() => useLegFilters());
    const before = result.current.formKey;
    act(() => result.current.viewLeg({ underlying: "NVDA" } as never));
    expect(result.current.filters.symbol).toBe("NVDA");
    expect(result.current.qsString).toBe("symbol=NVDA&book=all");
    expect(result.current.formKey).toBe(before + 1);
  });
});
```

Create `web/features/activity/PayView.test.tsx`:

```tsx
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { todayInNewYork } from "@/features/trades/time";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/activity",
}));

import { currentMonth } from "./month";
import { PayView } from "./PayView";

const now = () => new Date().toISOString();
const pay = (over: Record<string, unknown> = {}) => ({
  month: "2026-09-01", strategy: "all", premium_collected: 2000, bought_back: 400, commissions: 26,
  commissions_complete: true, net: 1574, n_opened: 12, n_closed: 9, month_start_value: 100000,
  target_pct: null, target_mode: "off", target_amount: null, target_base: null, target: null,
  progress_pct: null, days_left: 8, ...over,
});
const monthBody = (over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({
  as_of: now(), book: "paper", pay: pay(over), spreads_available: true, ...extra,
});
const filters = { as_of: now(), symbol: null, strategy: null, outcome: null, since: null, until: null, book: "all" };
const summary = (over: Record<string, unknown> = {}) => ({
  as_of: now(), filters, marks_as_of: now(),
  summary: {
    realized_total: 320, unrealized_total: 115, commissions_complete: true, n_open: 2, n_closed: 4,
    win_rate: 0.75, by_strategy: [], by_symbol: [], best: null, worst: null, ...over,
  },
});
const equity = (startsAt: string | null = "2026-06-24") => ({
  as_of: now(), filters, curve: { points: [], gaps: [], starts_at: startsAt },
});
const serve = (month: unknown = monthBody(), eq: unknown = equity()) =>
  renderWithQuery(<PayView />, {
    "/pnl/month": month,
    "/pnl/summary": summary(),
    "/pnl/equity": eq,
    "/pnl/ledger": { as_of: now(), filters, campaigns: [], marks_as_of: null, n_legs: 0 },
  });
const calls = () => apiFetchMock.mock.calls.map((c) => String(c[0]));

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
});

describe("PayView", () => {
  it("shows this month's stub, open, with the pace sentence and the days left", async () => {
    serve();
    const current = currentMonth(todayInNewYork());
    const stub = await screen.findByRole("group", { name: /pay stub$/ });
    expect(within(stub).getByText("Premium collected")).toBeInTheDocument();
    expect(within(stub).getByText("Net so far")).toBeInTheDocument();
    expect(within(stub).getByText("+$1,574.00")).toBeInTheDocument();
    expect(screen.getByText("No target set · 8 days left")).toBeInTheDocument();
    expect(calls()).toContain(`/pnl/month?month=${current}&strategy=all`);
  });

  it("reads the month from the URL and asks the API for it, with no days left on a past month", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve();
    expect(await screen.findByRole("heading", { name: "September 2026 pay" })).toBeInTheDocument();
    expect(calls()).toContain("/pnl/month?month=2026-09&strategy=all");
    const stub = await screen.findByRole("group", { name: "September 2026 pay stub" });
    expect(within(stub).getByText("Net for the month")).toBeInTheDocument();
    expect(screen.getByText("No target set")).toBeInTheDocument();
    expect(screen.queryByText(/days left/)).toBeNull();
  });

  it("says so when nothing happened in a month, over a stub of genuine zeros", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve(monthBody({ premium_collected: 0, bought_back: 0, commissions: 0, net: 0, n_opened: 0, n_closed: 0 }));
    expect(await screen.findByText("Nothing was opened or closed in September 2026.")).toBeInTheDocument();
    const stub = screen.getByRole("group", { name: "September 2026 pay stub" });
    expect(within(stub).getAllByText("$0").length).toBeGreaterThan(0);
  });

  it("shows the target, the meter and the percent for a past month", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve(monthBody({ target_mode: "fixed", target: 2000, target_amount: 2000, progress_pct: 78.7 }));
    expect(await screen.findByText("79% of target")).toBeInTheDocument();
    expect(screen.getByText("of $2,000.00")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "September 2026 target" })).toHaveAttribute("aria-valuenow", "79");
  });

  it("says the target cannot be worked out without the month's opening value", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve(monthBody({ target_mode: "pct_of_account", target_pct: 2, target: null, progress_pct: null }));
    expect(await screen.findByText(/needs the month's opening account value/)).toBeInTheDocument();
  });

  it("steps to the month before, and back to this month", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    serve();
    await screen.findByRole("heading", { name: "September 2026 pay" });
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/activity?month=2026-08", { scroll: false });
    fireEvent.click(screen.getByRole("button", { name: "This month" }));
    expect(nav.replace).toHaveBeenLastCalledWith("/activity", { scroll: false });
  });

  it("offers no month after this one", async () => {
    serve();
    await screen.findByRole("group", { name: /pay stub$/ });
    expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
  });

  it("stops going back at the month the system began", async () => {
    nav.params = new URLSearchParams("month=2026-06");
    serve(monthBody(), equity("2026-06-24"));
    await screen.findByRole("heading", { name: "June 2026 pay" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Previous month" })).toBeDisabled());
  });

  it("flags that spread income is unavailable, and says the total leaves it out", async () => {
    serve(monthBody({}, { spreads_available: false }));
    expect(await screen.findByText("Spreads unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("Spread income is unavailable because the spreads database could not be read, so this total leaves it out."),
    ).toBeInTheDocument();
  });

  it("says it could not load, and that it tries again", async () => {
    renderWithQuery(<PayView />, { "/pnl/summary": summary(), "/pnl/equity": equity() });
    expect(await screen.findByText("Could not load this month's pay.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every minute.")).toBeInTheDocument();
  });

  it("puts the totals since the system began under the month", async () => {
    serve();
    expect(await screen.findByRole("heading", { name: "Since the system began" })).toBeInTheDocument();
    expect(await screen.findByText("Realized total")).toBeInTheDocument();
  });
});
```

- [x] **Step 3: Run them to verify they fail**

Run: `cd web && npx vitest run features/activity`
Expected: FAIL (modules not found).

- [x] **Step 4: Implement the small modules**

`web/features/activity/month.ts`:

```ts
/** New York months as "YYYY-MM" strings (the Pay view's `?month=`). */
const MONTH = /^(\d{4})-(0[1-9]|1[0-2])$/;
const NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** The month a "YYYY-MM-DD" New York day falls in. */
export const currentMonth = (today: string): string => today.slice(0, 7);

/** A real month no later than this one; anything else (none, junk, a future month) is this month. */
export function parseMonth(raw: string | null | undefined, current: string): string {
  return raw && MONTH.test(raw) && raw <= current ? raw : current;
}

export function shiftMonth(month: string, n: number): string {
  const [y, m] = month.split("-").map(Number);
  const index = y * 12 + (m - 1) + n;
  return `${String(Math.floor(index / 12)).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}`;
}

/** "October 2026". */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return `${NAMES[m - 1]} ${y}`;
}

/** The month the system began, from the curve's start date; null when it is not known. */
export function earliestMonth(startsAt: string | null | undefined): string | null {
  return startsAt && /^\d{4}-\d{2}-\d{2}/.test(startsAt) ? startsAt.slice(0, 7) : null;
}
```

`web/features/activity/useMonthParam.ts`:

```ts
"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import { parseMonth } from "./month";

/**
 * The Pay month, kept in `?month=YYYY-MM`. None, junk or a future month is `current`; choosing the
 * current month removes the parameter, so "This month" is the bare URL. Other parameters (the view)
 * are kept. A page using this must render inside <Suspense> (Next's useSearchParams rule).
 */
export function useMonthParam(current: string): [string, (month: string) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const value = parseMonth(params.get("month"), current);

  const set = useCallback(
    (month: string) => {
      const next = new URLSearchParams(params.toString());
      if (month === current) next.delete("month");
      else next.set("month", month);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, router, pathname, current],
  );

  return [value, set];
}
```

`web/features/activity/MonthStepper.tsx`:

```tsx
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { monthLabel, shiftMonth } from "./month";

/**
 * Previous, the month, This month (away from it) and next. Next stops at the current month, and
 * previous at `floor`, the month the system began, when that is known. A disabled quiet button
 * shows as a filled circle (the Open Decision in web/DESIGN.md), as History's day arrows do.
 */
export function MonthStepper({
  month,
  current,
  floor,
  onChange,
}: {
  month: string;
  current: string;
  floor: string | null;
  onChange: (month: string) => void;
}) {
  return (
    <nav aria-label="Month" className="flex items-center justify-between gap-2">
      <Button
        variant="quiet"
        aria-label="Previous month"
        disabled={floor !== null && month <= floor}
        onClick={() => onChange(shiftMonth(month, -1))}
        className="w-11 !px-0"
      >
        <ChevronLeft size={18} strokeWidth={2.25} aria-hidden="true" />
      </Button>
      <p aria-live="polite" className="text-[1.0625rem] font-bold">
        {monthLabel(month)}
      </p>
      <div className="flex items-center gap-1">
        {month !== current && (
          <Button variant="secondary" onClick={() => onChange(current)}>
            This month
          </Button>
        )}
        <Button
          variant="quiet"
          aria-label="Next month"
          disabled={month >= current}
          onClick={() => onChange(shiftMonth(month, 1))}
          className="w-11 !px-0"
        >
          <ChevronRight size={18} strokeWidth={2.25} aria-hidden="true" />
        </Button>
      </div>
    </nav>
  );
}
```

`web/features/activity/useLegFilters.ts`:

```ts
"use client";

import { useState } from "react";
import type { PnlLegData } from "@/components/pnl/types";

/**
 * The one filter state the totals, the equity curve and the legs list share (the P&L page's
 * rule: a second composition of the query string would let a total disagree with the rows under
 * it). `book` lives inside `filters`, so the book choice the summary offers on a mixed book and the
 * Legs form's own Book field cannot disagree. `viewLeg` sets the symbol from a leg the totals name,
 * and bumps `formKey` so the form remounts with it as its seed rather than syncing in an effect.
 */
export function useLegFilters() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [formKey, setFormKey] = useState(0);
  const book = filters.book || "all";

  const setBook = (next: string) => setFilters((prev) => ({ ...prev, book: next }));
  const viewLeg = (leg: PnlLegData) => {
    setFilters((prev) => ({ ...prev, symbol: leg.underlying }));
    setFormKey((k) => k + 1);
  };

  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "" && v != null)),
  );
  if (!qs.has("book")) qs.set("book", "all");

  return { filters, setFilters, book, setBook, formKey, viewLeg, qsString: qs.toString() };
}
```

`web/features/activity/useEquity.ts`:

```ts
"use client";

import { useQuery } from "@tanstack/react-query";
import type { EquityResponse } from "@/components/pnl/types";
import { apiFetch } from "@/lib/api";

/** The equity curve under the shared filters. One query key, so the Pay month (for the month the
 *  system began) and the curve card ask once. */
export function useEquity(qsString: string) {
  return useQuery({
    queryKey: ["pnl", "equity", qsString],
    queryFn: () => apiFetch<EquityResponse>(`/pnl/equity?${qsString}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
}
```

- [x] **Step 5: Implement `web/features/activity/PayMonth.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { Meter } from "@/components/ui/Meter";
import { StatusWord } from "@/components/ui/StatusWord";
import { Stub, formatStubValue } from "@/components/ui/Stub";
import { payStubLines } from "@/features/home/PayCard";
import type { MonthPay, MonthPayResponse } from "@/features/home/types";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import { MonthStepper } from "./MonthStepper";
import { monthLabel } from "./month";

/** The pace under the meter: against the target and, for this month only, the days left. */
function Pace({ pay, current }: { pay: MonthPay; current: boolean }) {
  const left = current ? ` · ${pay.days_left} ${pay.days_left === 1 ? "day" : "days"} left` : "";
  if (pay.target_mode === "off") return <>No target set{left}</>;
  if (pay.target === null) {
    // The setting is there; the account value at the month's start is not.
    return (
      <>
        Target <span className="hatch">{UNKNOWN}</span> · needs the month&apos;s opening account value{left}
      </>
    );
  }
  if (pay.progress_pct === null) {
    return (
      <>
        <span className="hatch">{UNKNOWN}</span> of target{left}
      </>
    );
  }
  return (
    <>
      {Math.round(Math.max(0, pay.progress_pct))}% of target{left}
    </>
  );
}

/**
 * One New York month as a stub, always open: the same lines as Home's pay card, over any month
 * from the one the system began to this one. The month is the page's (`?month=`); a month nothing
 * was opened or closed in shows its genuine zeros and says so.
 */
export function PayMonth({
  month,
  current,
  floor,
  onMonth,
}: {
  month: string;
  current: string;
  floor: string | null;
  onMonth: (month: string) => void;
}) {
  const label = monthLabel(month);
  const { data, isError } = useQuery({
    queryKey: ["pnl", "month", "all", month],
    queryFn: () => apiFetch<MonthPayResponse>(`/pnl/month?month=${month}&strategy=all`),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });
  const pay = data?.pay;
  const isCurrent = month === current;
  const lines = pay
    ? payStubLines(pay).map((l) => (l.total && !isCurrent ? { ...l, label: "Net for the month" } : l))
    : [];

  return (
    <Card aria-labelledby="pay-title">
      <MonthStepper month={month} current={current} floor={floor} onChange={onMonth} />
      <div className="mt-3 flex flex-wrap items-baseline justify-between gap-x-2.5">
        <h2 id="pay-title" className="whitespace-nowrap text-[1.0625rem] font-bold">
          {label} pay
        </h2>
        {pay && (
          <span className="tabular ml-auto text-right font-mono font-semibold">
            <span className="whitespace-nowrap">{formatStubValue(pay.net, "signed-money")}</span>
            {pay.target !== null && (
              <>
                {" "}
                <span className="whitespace-nowrap font-normal text-muted">of {formatMoneyCell(pay.target)}</span>
              </>
            )}
          </span>
        )}
      </div>
      {isError && !data ? (
        <>
          <p className="mt-2 text-sm text-muted">Could not load this month&apos;s pay.</p>
          <p className="mt-1 text-[0.8125rem] text-muted">It tries again every minute.</p>
        </>
      ) : !pay ? (
        <div role="status" aria-busy="true" aria-label="Loading this month's pay" className="mt-3 h-24 rounded-xl bg-sunk" />
      ) : (
        <>
          <div className="mt-2.5">
            <Meter value={pay.net} max={pay.target} label={`${label} target`} />
          </div>
          <p className="mt-1.5 text-[0.8125rem] text-muted">
            <Pace pay={pay} current={isCurrent} />
          </p>
          <Stub label={`${label} pay stub`} lines={lines} />
          {pay.n_opened === 0 && pay.n_closed === 0 && (
            <p className="mt-2 text-[0.8125rem] text-muted">Nothing was opened or closed in {label}.</p>
          )}
          {data!.spreads_available === false && (
            <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] text-muted">
              <StatusWord tone="flag">Spreads unavailable</StatusWord>
              <span>
                Spread income is unavailable because the spreads database could not be read, so this total leaves it
                out.
              </span>
            </p>
          )}
        </>
      )}
    </Card>
  );
}
```

  `payStubLines` returns `StubLineData[]` whose `total: true` line is "Net so far"; the map above
  renames it for a past month only.

- [x] **Step 6: Implement `web/features/activity/PayView.tsx`** (Task 9 extends it):

```tsx
"use client";

import { SummaryPanel } from "@/components/pnl/SummaryPanel";
import { Card } from "@/components/ui/Card";
import { todayInNewYork } from "@/features/trades/time";
import { PayMonth } from "./PayMonth";
import { currentMonth, earliestMonth } from "./month";
import { useEquity } from "./useEquity";
import { useLegFilters } from "./useLegFilters";
import { useMonthParam } from "./useMonthParam";

/**
 * Pay: a month as a stub, then the totals since the system began. (The equity curve and the legs
 * join it in the next task, under the same filters.)
 */
export function PayView() {
  const current = currentMonth(todayInNewYork());
  const [month, setMonth] = useMonthParam(current);
  const legs = useLegFilters();
  const equity = useEquity(legs.qsString);
  const floor = earliestMonth(equity.data?.curve.starts_at);

  return (
    <div className="grid gap-4">
      <PayMonth month={month} current={current} floor={floor} onMonth={setMonth} />
      <Card aria-labelledby="totals-title">
        <h2 id="totals-title" className="text-[1.0625rem] font-bold">
          Since the system began
        </h2>
        <div className="mt-3">
          <SummaryPanel
            book={legs.book}
            qsString={legs.qsString}
            onBookChange={legs.setBook}
            onSelectLeg={legs.viewLeg}
          />
        </div>
      </Card>
    </div>
  );
}
```

- [x] **Step 7: Restyle `Money`'s two label spans** — in `web/components/portfolio/Money.tsx` change
  both `className="ml-1 text-[10px] uppercase tracking-wide text-muted"` to
  `className="ml-1 text-xs text-muted"` (the kind label and the "gross" label; the text is already
  lowercase, so nothing a test reads changes).

- [x] **Step 8: Restyle `BreakdownTable`** — replace `web/components/pnl/BreakdownTable.tsx` with:

```tsx
"use client";

import { UNKNOWN } from "@/lib/format";
import type { PnlBucketData } from "./types";

/**
 * One breakdown grid, by strategy or by symbol, over the buckets `build_summary` already ordered
 * (realised descending, ties by label). A bucket with nothing closed renders `n/a` in its rate
 * columns, never `0%`: an unknown win rate is not a zero win rate. Scrolls inside its own box on a
 * phone.
 */
export function BreakdownTable({ buckets, label }: { buckets: PnlBucketData[]; label: string }) {
  if (buckets.length === 0) {
    return null;
  }
  const head = "py-1.5 pr-3 text-right font-semibold";
  return (
    <div className="space-y-2" data-testid="breakdown-table">
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">{label}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold tracking-[0.04em] text-muted">
              <th className="py-1.5 pr-3 font-semibold">Label</th>
              <th className={head}>Closed</th>
              <th className={head}>Realized</th>
              <th className={head}>Win rate</th>
              <th className={head}>Mean days held</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.label} className="border-t border-border first:border-t-0">
                <td className="py-2 pr-3 font-mono text-content">{b.label}</td>
                <td className="tabular py-2 pr-3 text-right font-mono text-content">{b.n_closed}</td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  <span className={b.realized < 0 ? "text-loss" : "text-content"}>
                    {b.realized < 0 ? "-" : ""}${Math.abs(b.realized).toFixed(2)}
                  </span>
                </td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  {b.win_rate == null ? (
                    <span className="hatch text-unknown">{UNKNOWN}</span>
                  ) : (
                    `${Math.round(b.win_rate * 100)}%`
                  )}
                </td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  {b.mean_days_held == null ? (
                    <span className="hatch text-unknown">{UNKNOWN}</span>
                  ) : (
                    b.mean_days_held.toFixed(1)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [x] **Step 9: Restyle `SummaryPanel`** (`web/components/pnl/SummaryPanel.tsx`; three edits, no
  text, test id or condition changes):

  1. Add `import { SegmentedControl } from "@/components/ui/SegmentedControl";` after the
     `EmptyState` import, and replace the whole `<fieldset ...> ... </fieldset>` inside the 422
     block (the `fieldset` with `role="group" aria-label="book"` and its two-button `.map`) with:

```tsx
        <SegmentedControl
          label="Book"
          appearance="chips"
          options={[
            { value: "paper", label: "paper book" },
            { value: "live", label: "live book" },
          ]}
          value={book as "paper" | "live"}
          onChange={(b) => onBookChange?.(b)}
        />
```

  2. The best-and-worst heading and list: replace
     `<h3 className="text-xs uppercase tracking-wide text-muted">Best and worst closed legs</h3>` with
     `<h3 className="text-xs font-semibold tracking-[0.04em] text-muted">Best and worst closed legs</h3>`
     and `<ul className="space-y-1 text-xs">` with `<ul className="space-y-1 text-[0.8125rem]">`.
  3. In `BestWorstRow`'s button, replace
     `className="font-mono text-content underline decoration-dotted underline-offset-2 hover:decoration-solid"`
     with
     `className="inline-flex min-h-11 items-center font-mono text-content underline decoration-dotted underline-offset-2 hover:decoration-solid md:min-h-6"`.

- [x] **Step 10: Run the tests, then the gate**

Run: `cd web && npx vitest run features/activity components/pnl components/portfolio && npx tsc --noEmit && npm run lint`
Expected: PASS: the new tests (month 6, useMonthParam 4, MonthStepper 5, useLegFilters 5, PayView 11),
and every existing `SummaryPanel`, `BreakdownTable`, `Money` and legacy portfolio test
**unmodified**.

- [x] **Step 11: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/activity web/components/pnl/SummaryPanel.tsx web/components/pnl/BreakdownTable.tsx web/components/portfolio/Money.tsx`
Expected: exit 0, or every finding fixed in the code.

- [x] **Step 12: Commit** (with the Progress log row for Task 8 filled in)

```bash
git add web/features/activity web/components/portfolio/Money.tsx web/components/pnl/BreakdownTable.tsx \
  web/components/pnl/SummaryPanel.tsx docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): Activity Pay - a month at a time as a stub, then the totals since the start"
```

---

### Task 9: Pay — the filters, the equity curve and the legs

**Files:**
- Create: `web/features/activity/Curve.tsx`, `web/features/activity/Legs.tsx` (`LegsFilters`, `LegsCard`)
- Modify: `web/features/activity/PayView.tsx`, `web/features/activity/PayView.test.tsx` (+8 tests)
- Modify (restyle in place): `web/components/pnl/LedgerFilters.tsx` (whole file),
  `web/components/pnl/CampaignRow.tsx` (whole file), `web/components/pnl/LegRow.tsx` (whole file),
  `web/components/pnl/EquityChart.tsx` (four classes and one comment)

**Interfaces:**
- Consumes: `useLegFilters`, `useEquity` (Task 8), `LedgerResponseData` (`components/pnl/types.ts`),
  `LedgerFilters({ filters, onChange })`, `LedgerTable({ data })`, `EquityChart({ curve })`, `FIELD`,
  `FIELD_LABEL`, `StatusWord`, `Card`.
- Produces: `Curve({ qsString })`, `LegsFilters({ filters, formKey, onFilters })`,
  `LegsCard({ qsString })`; the finished `PayView`.

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: one filter row for the totals,
  the curve and the legs; thread cards with the legs behind a chevron; hairline leg rows in the
  figure face; no lime.

- [x] **Step 2: Write the failing tests** — in `web/features/activity/PayView.test.tsx` replace the
  `serve` helper's `"/pnl/ledger"` entry with `"/pnl/ledger": ledgerBody()` and add these helpers
  below `equity`:

```tsx
const leg = (over: Record<string, unknown> = {}) => ({
  candidate_id: "cand-1", campaign_id: null, symbol: "NVDA 261016 00170000P", underlying: "NVDA",
  strategy: "cash_secured_put", right: "P", strike: 170, expiry: "2026-10-16", contracts: 1,
  opened_at: now(), closed_at: null, credit: 150, debit: 0, commissions: 1, commissions_complete: true,
  net_pnl: null, unrealized_pnl: null, days_held: 5, roc_pct: 0.88, annualized_pct: null,
  outcome: "still_open", is_live: false, ...over,
});
const campaign = (over: Record<string, unknown> = {}) => ({
  campaign_id: "camp-1", symbol: "NVDA", status: "open", opened_date: "2026-09-01", closed_date: null,
  legs: [leg()], option_realized: 0, option_unrealized: 115, stock_realized: null, stock_unrealized: null,
  assigned: false, adjusted_cost_basis: null, total_net: 115, ...over,
});
const ledgerBody = (campaigns: unknown[] = []) => ({
  as_of: now(), filters, campaigns, marks_as_of: null, n_legs: campaigns.length,
});
```

  and append inside `describe("PayView", ...)`:

```tsx
  it("narrows the totals, the curve and the legs by one set of filters, and the CSV carries them", async () => {
    serve();
    fireEvent.change(await screen.findByLabelText("Symbol"), { target: { value: "nvda" } });
    await waitFor(() => {
      expect(calls()).toContain("/pnl/summary?book=all&symbol=NVDA");
      expect(calls()).toContain("/pnl/equity?book=all&symbol=NVDA");
      expect(calls()).toContain("/pnl/ledger?book=all&symbol=NVDA");
    });
    expect(screen.getByTestId("ledger-export-link")).toHaveAttribute("href", "/api/pnl/ledger.csv?book=all&symbol=NVDA");
  });

  it("says the filters apply to everything under them", async () => {
    serve();
    expect(await screen.findByText("These filters apply to the totals, the curve and the legs below.")).toBeInTheDocument();
  });

  it("narrows the legs by the symbol of the best leg the totals name", async () => {
    renderWithQuery(<PayView />, {
      "/pnl/month": monthBody(),
      "/pnl/summary": summary({ best: leg({ candidate_id: "best-1", net_pnl: 149, outcome: "expired_worthless" }) }),
      "/pnl/equity": equity(),
      "/pnl/ledger": ledgerBody(),
    });
    fireEvent.click(await screen.findByRole("button", { name: /view nvda p 170\.00 in the ledger/i }));
    await waitFor(() => expect(calls()).toContain("/pnl/ledger?symbol=NVDA&book=all"));
    expect(screen.getByLabelText("Symbol")).toHaveValue("NVDA");
  });

  it("lists the legs as campaign threads that open to their legs", async () => {
    renderWithQuery(<PayView />, {
      "/pnl/month": monthBody(),
      "/pnl/summary": summary(),
      "/pnl/equity": equity(),
      "/pnl/ledger": ledgerBody([campaign({ legs: [leg(), leg({ candidate_id: "c2", strike: 175 })] })]),
    });
    const thread = await screen.findByRole("button", { name: /NVDA campaign/ });
    expect(thread).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("campaign-leg-count")).toHaveTextContent("2 legs");
    fireEvent.click(thread);
    expect(screen.getAllByTestId("leg-row")).toHaveLength(2);
  });

  it("says there are no trades for the filters, in words", async () => {
    serve();
    expect(await screen.findByText("No trades match the current filters.")).toBeInTheDocument();
  });

  it("says no marks are available rather than showing zeros", async () => {
    serve();
    expect(await screen.findByText("no marks available")).toBeInTheDocument();
  });

  it("draws the equity curve and says when it began", async () => {
    renderWithQuery(<PayView />, {
      "/pnl/month": monthBody(),
      "/pnl/summary": summary(),
      "/pnl/equity": {
        as_of: now(), filters,
        curve: {
          points: [{ entry_date: "2026-09-01", net_liquidation: 250000, unrealized_pnl: 100, cumulative_realized: 0, premium_cashflow: 42 }],
          gaps: [], starts_at: "2026-09-01",
        },
      },
      "/pnl/ledger": ledgerBody(),
    });
    expect(await screen.findByText(/since 1 September 2026/i)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: /legend/i })).toBeInTheDocument();
  });

  it("says it could not load the curve and the legs, and that it tries again", async () => {
    renderWithQuery(<PayView />, { "/pnl/month": monthBody(), "/pnl/summary": summary() });
    expect(await screen.findByText("Could not load the equity curve.")).toBeInTheDocument();
    expect(await screen.findByText("Could not load the ledger.")).toBeInTheDocument();
    expect(screen.getAllByText("It tries again every 30 seconds.").length).toBeGreaterThanOrEqual(2);
  });
```

- [x] **Step 3: Run them to verify they fail**

Run: `cd web && npx vitest run features/activity/PayView.test.tsx`
Expected: FAIL (the 8 new tests: no filters, no curve, no legs).

- [x] **Step 4: Restyle `LedgerFilters`** — replace `web/components/pnl/LedgerFilters.tsx` with the file
  below. Every id, label text, option and the `data-testid` are the old ones; only the layout and
  the field classes change, and the doc comment is kept.

```tsx
"use client";

import clsx from "clsx";
import { useState } from "react";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";

type BookFilter = "all" | "paper" | "live";

/**
 * The filter strip above the ledger. Filters drive the query string, not
 * client-side array filtering, so the CSV export link and the JSON table
 * request the same rows from the backend under the same params — a client-side
 * `.filter()` would let the two drift.
 *
 * The parent owns the query string (the page composes it into the totals, the
 * curve, the legs and the export href); this component reports the next filter
 * set. `filters` is the page's own live filter draft — NOT the backend's echoed
 * response (`LedgerTable`'s separate filter-echo reads that instead), because
 * seeding local state from a request echo would lag one round trip behind. It
 * seeds local state only via `useState`'s lazy initializer, read once — this
 * component stays fast to type in even while a request is in flight. The one
 * case that needs the inputs to change without a keystroke of their own — the
 * summary's "view in ledger" link changing `symbol` externally — works by the
 * parent remounting this component with a fresh `key` instead of a live-sync
 * effect, which would risk clobbering a value the user is mid-typing when a
 * slightly-stale response lands.
 */
export function LedgerFilters({
  filters,
  onChange,
}: {
  filters: Record<string, string> | undefined;
  onChange: (next: Record<string, string>) => void;
}) {
  const [symbol, setSymbol] = useState(filters?.symbol ?? "");
  const [book, setBook] = useState<BookFilter>((filters?.book as BookFilter) || "all");
  const [outcome, setOutcome] = useState(filters?.outcome ?? "");
  const [since, setSince] = useState(filters?.since ?? "");
  const [until, setUntil] = useState(filters?.until ?? "");

  function emit(next: Record<string, string>) {
    onChange(next);
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="ledger-filters">
      <div className="grid gap-1">
        <label htmlFor="ledger-symbol-filter" className={FIELD_LABEL}>
          Symbol
        </label>
        <input
          id="ledger-symbol-filter"
          type="text"
          value={symbol}
          onChange={(e) => {
            setSymbol(e.target.value);
            emit({ book, outcome, since, until, symbol: e.target.value.toUpperCase() });
          }}
          placeholder="NVDA"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          className={clsx(FIELD, "w-full")}
        />
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-book-filter" className={FIELD_LABEL}>
          Book
        </label>
        <select
          id="ledger-book-filter"
          value={book}
          onChange={(e) => {
            const nextBook = e.target.value as BookFilter;
            setBook(nextBook);
            emit({ book: nextBook, outcome, since, until, symbol });
          }}
          className={clsx(FIELD, "w-full")}
        >
          <option value="all">all</option>
          <option value="paper">paper</option>
          <option value="live">live</option>
        </select>
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-outcome-filter" className={FIELD_LABEL}>
          Outcome
        </label>
        <select
          id="ledger-outcome-filter"
          value={outcome}
          onChange={(e) => {
            setOutcome(e.target.value);
            emit({ book, outcome: e.target.value, since, until, symbol });
          }}
          className={clsx(FIELD, "w-full")}
        >
          <option value="">all</option>
          <option value="still_open">still open</option>
          <option value="expired_worthless">expired worthless</option>
          <option value="assigned">assigned</option>
          <option value="closed_early">closed early</option>
        </select>
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-since-filter" className={FIELD_LABEL}>
          Since
        </label>
        <input
          id="ledger-since-filter"
          type="date"
          value={since}
          onChange={(e) => {
            setSince(e.target.value);
            emit({ book, outcome, since: e.target.value, until, symbol });
          }}
          className={clsx(FIELD, "w-full")}
        />
      </div>

      <div className="grid gap-1">
        <label htmlFor="ledger-until-filter" className={FIELD_LABEL}>
          Until
        </label>
        <input
          id="ledger-until-filter"
          type="date"
          value={until}
          onChange={(e) => {
            setUntil(e.target.value);
            emit({ book, outcome, since, until: e.target.value, symbol });
          }}
          className={clsx(FIELD, "w-full")}
        />
      </div>
    </div>
  );
}
```

- [x] **Step 5: Restyle `LegRow` and `CampaignRow`** — replace `web/components/pnl/LegRow.tsx` with:

```tsx
"use client";

import { Money } from "@/components/portfolio/Money";
import type { PnlLegData } from "./types";

/**
 * One leg of a P&L campaign thread — the row an operator reconciles against a
 * broker statement. Every unknown renders `n/a` with texture, never a zero: an
 * open leg has a mark, not a result, so its realised column must not claim
 * `$0.00`. Realised and unrealised are separate columns with distinct headers
 * because they answer different questions ("what did it earn?" vs "what is it
 * worth now?").
 *
 * `commissions_complete: false` renders the gross qualifier — the figure
 * excludes commissions and says so, rather than silently overclaiming "net".
 * Both money columns render through `portfolio/Money`, not a second money
 * component — `complete` carries the gross qualifier itself.
 */
export function LegRow({ leg }: { leg: PnlLegData }) {
  const cell = "py-2 pr-3";
  return (
    <tr data-testid="leg-row" className="border-t border-border text-[0.8125rem] first:border-t-0">
      <td className={`${cell} font-mono text-content`}>{leg.underlying}</td>
      <td className={`${cell} text-muted`}>
        {leg.strategy === "covered_call" ? "CC" : leg.strategy === "roll" ? "roll" : "CSP"} {leg.right}{" "}
        {leg.strike != null ? leg.strike.toFixed(2) : "n/a"}
      </td>
      <td className={`${cell} tabular font-mono text-muted`}>{leg.expiry ?? "n/a"}</td>
      <td className={`${cell} tabular text-right font-mono text-content`}>{leg.contracts}</td>
      <td className={`${cell} tabular text-right font-mono text-muted`}>{leg.days_held}</td>
      {/* Realised — null while open, never $0.00. */}
      <td data-testid="realized" className={`${cell} text-right font-mono`}>
        <Money value={leg.net_pnl} kind="realized" signed complete={leg.commissions_complete} />
      </td>
      {/* Unrealised — filled by the parent from marks; null when no marks exist. */}
      <td data-testid="unrealized" className={`${cell} text-right font-mono`}>
        <Money value={leg.unrealized_pnl} kind="unrealized" signed />
      </td>
      <td className={`${cell} tabular text-muted`}>{leg.outcome.replace(/_/g, " ")}</td>
    </tr>
  );
}
```

  and `web/components/pnl/CampaignRow.tsx` with:

```tsx
"use client";

import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { Money } from "@/components/portfolio/Money";
import { StatusWord } from "@/components/ui/StatusWord";
import { LegRow } from "./LegRow";
import type { CampaignPnlData } from "./types";

const LEG_HEADERS = ["Leg", "Contract", "Expiry", "Qty", "Days", "Realized", "Unrealized", "Outcome"];
const RIGHT = new Set(["Qty", "Days", "Realized", "Unrealized"]);

/**
 * One campaign thread of the P&L ledger: symbol, status, net and leg count
 * collapsed; expanding shows the legs in order through a real
 * `<button aria-expanded>` (each thread owns its own expand/collapse state so
 * opening one never affects another). The legs are rendered only while open.
 *
 * The thread's net renders through `portfolio/Money` (kind "value": it mixes
 * realised and unrealised legs, so neither label would be accurate), with the
 * same null discipline the legs use: an unmarked open leg is not worth zero.
 */
export function CampaignRow({ campaign }: { campaign: CampaignPnlData }) {
  const [isOpen, setIsOpen] = useState(false);
  const legCount = campaign.legs?.length ?? 0;

  return (
    <div className="rounded-[18px] bg-surface" data-testid="campaign-row">
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
        className="flex min-h-11 w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-[18px] px-4 py-3 text-left"
        aria-label={`${campaign.symbol} campaign`}
      >
        <span className="text-[1.0625rem] font-bold">{campaign.symbol}</span>
        <span data-testid="campaign-status">
          <StatusWord>{campaign.status === "open" ? "Open" : "Closed"}</StatusWord>
        </span>
        <span data-testid="campaign-net" className="font-mono">
          <Money value={campaign.total_net} kind="value" signed />
        </span>
        <span className="flex items-center gap-2 text-[0.8125rem] text-muted" data-testid="campaign-leg-count">
          {legCount} {legCount === 1 ? "leg" : "legs"}
          <ChevronDown
            size={16}
            aria-hidden="true"
            className={clsx("transition-transform duration-[180ms] ease-out motion-reduce:transition-none", isOpen && "rotate-180")}
          />
        </span>
      </button>

      {isOpen && (
        <div className="overflow-x-auto border-t border-border px-4 pb-3" data-testid="campaign-legs">
          <table className="w-full">
            <thead>
              <tr className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
                {LEG_HEADERS.map((h) => (
                  <th key={h} className={clsx("py-2 pr-3 font-semibold", RIGHT.has(h) && "text-right")}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(campaign.legs ?? []).map((leg) => (
                <LegRow key={leg.candidate_id} leg={leg} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

  The `campaign-leg-count` test reads `toHaveTextContent("2 legs")`: the chevron is an `svg`
  with no text, so the content is unchanged.

- [x] **Step 6: Restyle `EquityChart`** (`web/components/pnl/EquityChart.tsx`; four class edits and
  one comment edit, the data, the mirrors and every string unchanged): `<div className="h-80 w-full">`
  becomes `<div className="h-64 w-full md:h-80">`; the legend wrapper
  `className="mt-2 flex flex-wrap gap-4"` becomes `className="mt-2 flex flex-wrap gap-x-4 gap-y-1"`
  and each legend item's `className="flex items-center gap-2 text-xs text-muted"` becomes
  `className="flex items-center gap-2 text-[0.8125rem] text-muted"`; the start-date paragraph
  `className="mt-2 text-xs text-muted"` becomes `className="mt-2 text-[0.8125rem] text-muted"`. The JSX
  comment above the series mirrors has an em dash that the da-vinci lint reads as copy: change
  `records its actual props here — one element per series, asserted` to
  `records its actual props here, one element per series, asserted`.

- [x] **Step 7: Implement `web/features/activity/Curve.tsx`**

```tsx
"use client";

import { EquityChart } from "@/components/pnl/EquityChart";
import { Card } from "@/components/ui/Card";
import { useEquity } from "./useEquity";

/** The equity curve under the shared filters. A gap in the journal is a gap in the line. */
export function Curve({ qsString }: { qsString: string }) {
  const { data, isError } = useEquity(qsString);
  return (
    <Card aria-labelledby="curve-title">
      <h2 id="curve-title" className="text-[1.0625rem] font-bold">
        Equity curve
      </h2>
      <div className="mt-3">
        {isError && !data ? (
          <div className="text-sm text-muted">
            <p>Could not load the equity curve.</p>
            <p className="mt-1 text-[0.8125rem]">It tries again every 30 seconds.</p>
          </div>
        ) : !data ? (
          <div role="status" aria-busy="true" aria-label="Loading the equity curve" className="h-40 rounded-xl bg-sunk" />
        ) : (
          <EquityChart curve={data.curve} />
        )}
      </div>
    </Card>
  );
}
```

- [x] **Step 8: Implement `web/features/activity/Legs.tsx`** — the filters and the legs card are two
  exports because the totals and the curve sit between them on the page:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { LedgerFilters } from "@/components/pnl/LedgerFilters";
import { LedgerTable } from "@/components/pnl/LedgerTable";
import type { LedgerResponseData } from "@/components/pnl/types";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";

/**
 * The one row of filters. They narrow the totals, the curve and the legs under them (the page's
 * rule: one composed query string, so a total cannot disagree with the rows). A filter goes to the
 * API, never a client-side narrowing. `formKey` remounts the form when a leg the totals name sets
 * the symbol from outside, instead of syncing the inputs in an effect.
 */
export function LegsFilters({
  filters,
  formKey,
  onFilters,
}: {
  filters: Record<string, string>;
  formKey: number;
  onFilters: (next: Record<string, string>) => void;
}) {
  return (
    <section aria-label="Filters" className="grid gap-2">
      <LedgerFilters key={formKey} filters={filters} onChange={onFilters} />
      <p className="text-[0.8125rem] text-muted">These filters apply to the totals, the curve and the legs below.</p>
    </section>
  );
}

/** Every leg the system opened and closed, in campaign threads, and the CSV export of the same rows. */
export function LegsCard({ qsString }: { qsString: string }) {
  const { data, isError } = useQuery({
    queryKey: ["pnl", "ledger", qsString],
    queryFn: () => apiFetch<LedgerResponseData>(`/pnl/ledger?${qsString}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  return (
    <Card aria-labelledby="legs-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="legs-title" className="text-[1.0625rem] font-bold">
          Legs
        </h2>
        <a
          href={`/api/pnl/ledger.csv?${qsString}`}
          data-testid="ledger-export-link"
          className="inline-flex min-h-11 items-center text-[0.8125rem] font-semibold underline underline-offset-2 md:min-h-8"
        >
          Export CSV
        </a>
      </div>
      <div className="mt-3">
        {isError && !data ? (
          <div className="text-sm text-muted">
            <p>Could not load the ledger.</p>
            <p className="mt-1 text-[0.8125rem]">It tries again every 30 seconds.</p>
          </div>
        ) : !data ? (
          <div role="status" aria-busy="true" aria-label="Loading the ledger" className="h-24 rounded-xl bg-sunk" />
        ) : (
          <LedgerTable data={data} />
        )}
      </div>
    </Card>
  );
}
```

  `LedgerTable` keeps its own words ("no marks available", "No trades match the current filters.",
  the filter echo); none of them changes.

- [x] **Step 9: Extend `PayView`** — replace `web/features/activity/PayView.tsx` with:

```tsx
"use client";

import { SummaryPanel } from "@/components/pnl/SummaryPanel";
import { Card } from "@/components/ui/Card";
import { todayInNewYork } from "@/features/trades/time";
import { Curve } from "./Curve";
import { LegsCard, LegsFilters } from "./Legs";
import { PayMonth } from "./PayMonth";
import { currentMonth, earliestMonth } from "./month";
import { useEquity } from "./useEquity";
import { useLegFilters } from "./useLegFilters";
import { useMonthParam } from "./useMonthParam";

/**
 * Pay: a month as a stub, one row of filters, then what they narrow: the totals since the system
 * began, the equity curve and the legs. The month is the page's (`?month=`); the filters are local
 * and shared by the three cards under them.
 */
export function PayView() {
  const current = currentMonth(todayInNewYork());
  const [month, setMonth] = useMonthParam(current);
  const legs = useLegFilters();
  const equity = useEquity(legs.qsString);
  const floor = earliestMonth(equity.data?.curve.starts_at);

  return (
    <div className="grid gap-4">
      <PayMonth month={month} current={current} floor={floor} onMonth={setMonth} />
      <LegsFilters filters={legs.filters} formKey={legs.formKey} onFilters={legs.setFilters} />
      <Card aria-labelledby="totals-title">
        <h2 id="totals-title" className="text-[1.0625rem] font-bold">
          Since the system began
        </h2>
        <div className="mt-3">
          <SummaryPanel
            book={legs.book}
            qsString={legs.qsString}
            onBookChange={legs.setBook}
            onSelectLeg={legs.viewLeg}
          />
        </div>
      </Card>
      <Curve qsString={legs.qsString} />
      <LegsCard qsString={legs.qsString} />
    </div>
  );
}
```

- [x] **Step 10: Run the tests, then the gate**

Run: `cd web && npx vitest run features/activity components/pnl && npx tsc --noEmit && npm run lint`
Expected: PASS: the 8 new tests and the 11 from Task 8; every existing `LedgerTable.test.tsx`
(`LegRow`, `CampaignRow`, `LedgerTable`), `EquityChart` and `SummaryPanel` test **unmodified**.

- [x] **Step 11: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/activity web/components/pnl`
Expected: exit 0 over every non-test source file (the legacy test titles' em dashes, if any, are
not copy), or every finding fixed in the code.

- [x] **Step 12: Commit** (with the Progress log row for Task 9 filled in)

```bash
git add web/features/activity web/components/pnl/LedgerFilters.tsx web/components/pnl/CampaignRow.tsx \
  web/components/pnl/LegRow.tsx web/components/pnl/EquityChart.tsx docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): Activity Pay - one set of filters over the totals, the curve and the legs"
```

---

### Task 10: Ledger — the overview in the figure face, without a sub-navigation

**Files:**
- Create: `web/components/ledger/BackToLedger.tsx`, `BackToLedger.test.tsx`, `LedgerShell.tsx`,
  `Tile.test.tsx`, `OutcomePill.test.tsx`
- Modify (restyle in place): `web/components/ledger/Tile.tsx` (whole file), `OutcomePill.tsx`
  (whole file), `Charts.tsx` (one line), `TickerTable.tsx` (whole file), `LedgerOverview.tsx`
  (whole file), `TickerView.tsx` (the tile container only)
- Modify: `web/components/ledger/LedgerOverview.test.tsx` (+4 tests)

**Interfaces:**
- Consumes: `Card`, `StatusWord`, the existing `format.ts` helpers (`money`, `pct`, `rate`,
  `signClass`), `LedgerSummary*`/`LedgerTicker` types.
- Produces: `BackToLedger()` (a link to `/activity?view=ledger`, Task 11 and the pages use it),
  `LedgerShell({ children })` (the page frame for the ledger's own routes), `Tile({ id, label, value,
  tone? })` as a figure line and `TileList({ children, testId? })` (a `dl` under a perforation).
  `LedgerOverview()` no longer renders a sub-navigation; Task 14 mounts it as Activity's Ledger view.

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: the ledger's tiles become
  figure lines under a perforation (no KPI-tile grid), states are words, charts keep their data
  and take the ink line.

- [x] **Step 2: Write the failing tests**

Create `web/components/ledger/Tile.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Tile, TileList } from "./Tile";

describe("Tile", () => {
  it("is a labelled figure line with its test id", () => {
    render(
      <TileList testId="list">
        <Tile id="total" label="Total profit" value="$2,575.84" tone="text-gain" />
      </TileList>,
    );
    const line = screen.getByTestId("tile-total");
    expect(line).toHaveTextContent("Total profit");
    expect(line).toHaveTextContent("$2,575.84");
    expect(screen.getByText("$2,575.84")).toHaveClass("text-gain");
    expect(screen.getByTestId("list").tagName).toBe("DL");
  });
  it("draws an unknown figure as a hatched n/a", () => {
    render(
      <TileList>
        <Tile id="contributed" label="Contributed capital" value="n/a" tone="text-unknown" />
      </TileList>,
    );
    expect(screen.getByText("n/a")).toHaveClass("hatch");
  });
});
```

Create `web/components/ledger/OutcomePill.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OutcomePill } from "./OutcomePill";

describe("OutcomePill", () => {
  it("prints the outcome in words", () => {
    render(<OutcomePill outcome="Called away" />);
    expect(screen.getByText("Called away")).toBeInTheDocument();
  });
  it("marks an outcome the operator set, in words for a screen reader", () => {
    render(<OutcomePill outcome="Expired" overridden />);
    expect(screen.getByLabelText("overridden")).toHaveTextContent("*");
  });
  it("marks nothing for a computed outcome", () => {
    render(<OutcomePill outcome="Expired" />);
    expect(screen.queryByLabelText("overridden")).toBeNull();
  });
});
```

Create `web/components/ledger/BackToLedger.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BackToLedger } from "./BackToLedger";

describe("BackToLedger", () => {
  it("leads back to the Ledger view on Activity", () => {
    render(<BackToLedger />);
    expect(screen.getByRole("link", { name: "Back to Activity, Ledger" })).toHaveAttribute(
      "href",
      "/activity?view=ledger",
    );
  });
});
```

  Append inside `describe("LedgerOverview", ...)` in `LedgerOverview.test.tsx`, before its closing `});`:

```tsx
  it("leads to the trades list and the statement import, and has no sub-navigation of its own", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    expect(await screen.findByRole("link", { name: "All trades" })).toHaveAttribute("href", "/ledger/trades");
    expect(screen.getByRole("link", { name: "Import a statement" })).toHaveAttribute("href", "/ledger/import");
    expect(screen.queryByRole("navigation", { name: "Ledger sections" })).toBeNull();
  });

  it("says where its figures come from, and that they can differ from the system's own", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    expect(
      await screen.findByText(/What IBKR reports, from the live feed, the Flex query and statement imports/),
    ).toBeInTheDocument();
    expect(screen.getByText(/It can differ from the system's own record under Pay/)).toBeInTheDocument();
  });

  it("lists upcoming expiries with a link to the ticker and the outcome in words", async () => {
    const upcoming = {
      order_key: "k1", underlying: "NVDA", side: "Sell", lots: 1, strike: 138, right: "P",
      expiry: "2099-11-20", outcome: "Open", outcome_overridden: false,
    };
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary({ upcoming: [upcoming as never] }) },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    const link = await screen.findByRole("link", { name: "NVDA" });
    expect(link).toHaveAttribute("href", "/ledger/ticker/NVDA");
    const row = link.closest("li") as HTMLElement;
    expect(row).toHaveTextContent("Sell 1 x 138P");
    expect(row).toHaveTextContent("Open");
  });

  it("says it could not load the ledger, and shows nothing else, when the summary fails", async () => {
    renderWithQuery(<LedgerOverview />, { "/ledger/tickers": { as_of: ISO, tickers: [] } });
    expect(await screen.findByText("Could not load the ledger.")).toBeInTheDocument();
    expect(screen.queryByTestId("ledger-tiles")).toBeNull();
  });
```

- [x] **Step 3: Run them to verify they fail**

Run: `cd web && npx vitest run components/ledger`
Expected: FAIL (new modules missing; the overview still renders its sub-navigation and has no
links or source sentence).

- [x] **Step 4: Implement the small components**

`web/components/ledger/Tile.tsx`:

```tsx
import type { ReactNode } from "react";

/**
 * The ledger's headline figures as lines under a perforation, in the stub face: the payslip's
 * voice for numbers Python computed, and not a grid of KPI tiles.
 */
export function TileList({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <dl
      data-testid={testId}
      className="tabular mt-3 border-t-2 border-dashed border-perforation pt-2 font-mono text-[0.84375rem] font-medium"
    >
      {children}
    </dl>
  );
}

/** One figure line. A value we do not have ("n/a") is hatched; `tone` carries a sign class. */
export function Tile({ id, label, value, tone }: { id: string; label: string; value: string; tone?: string }) {
  const unknown = value === "n/a";
  return (
    <div data-testid={`tile-${id}`} className="flex min-h-6 items-baseline justify-between gap-3">
      <dt className="min-w-0">{label}</dt>
      <dd className={`text-right ${unknown ? "hatch text-unknown" : (tone ?? "")}`}>{value}</dd>
    </div>
  );
}
```

`web/components/ledger/OutcomePill.tsx`:

```tsx
import { StatusWord } from "@/components/ui/StatusWord";
import type { LedgerOutcome } from "./types";

// The word is the state; no colour carries it (web/DESIGN.md: states are words, never colour alone).
export function OutcomePill({ outcome, overridden = false }: { outcome: LedgerOutcome; overridden?: boolean }) {
  return (
    <StatusWord>
      {outcome}
      {overridden && (
        <span title="Outcome set by you" aria-label="overridden">
          *
        </span>
      )}
    </StatusWord>
  );
}
```

`web/components/ledger/BackToLedger.tsx`:

```tsx
import { ChevronLeft } from "lucide-react";
import Link from "next/link";

/** Where the ledger's own pages lead back to: the Ledger view on Activity. */
export function BackToLedger() {
  return (
    <Link
      href="/activity?view=ledger"
      aria-label="Back to Activity, Ledger"
      className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8"
    >
      <ChevronLeft size={16} aria-hidden="true" />
      Activity · Ledger
    </Link>
  );
}
```

`web/components/ledger/LedgerShell.tsx`:

```tsx
import type { ReactNode } from "react";

/** The page frame of the ledger's own routes (`/ledger/trades`, `/ledger/ticker/:symbol`, `/ledger/import`). */
export function LedgerShell({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1200px] px-4 py-5 md:px-7 md:py-6">{children}</div>;
}
```

In `web/components/ledger/Charts.tsx`, in `PnlCurve` change `stroke="var(--color-gain)"` to
`stroke="var(--chart-line)"` (the ink line every chart in the app uses). Nothing else in the file
changes.

- [x] **Step 5: Restyle `TickerTable`** — replace `web/components/ledger/TickerTable.tsx` with:

```tsx
"use client";

import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { money, pct, rate, signClass } from "./format";
import type { LedgerTicker } from "./types";

type Col = { key: keyof LedgerTicker; label: string };
const COLS: Col[] = [
  { key: "total_realized", label: "Total realised" },
  { key: "option_net_pnl", label: "Options" },
  { key: "stock_realized", label: "Stock" },
  { key: "dividends_net", label: "Dividends" },
  { key: "unrealized", label: "Unrealised" },
  { key: "n_trades", label: "Trades" },
  { key: "win_rate", label: "Win rate" },
  { key: "annualised_return_pct", label: "Annualised" },
  { key: "shares_held", label: "Shares" },
  { key: "wheel_adjusted_basis", label: "Wheel basis" },
];

const NUM = "tabular py-2 pr-4 text-right font-mono";

export function TickerTable({ tickers }: { tickers: LedgerTicker[] }) {
  const [sortKey, setSortKey] = useState<keyof LedgerTicker>("total_realized");
  const [desc, setDesc] = useState(true);
  if (tickers.length === 0) return <p className="text-sm text-muted">No tickers yet. Import a statement to begin.</p>;
  const rows = [...tickers].sort((a, b) => {
    const av = a[sortKey] ?? -Infinity;
    const bv = b[sortKey] ?? -Infinity;
    return (av < bv ? -1 : av > bv ? 1 : 0) * (desc ? -1 : 1);
  });
  function sortBy(k: keyof LedgerTicker) {
    if (k === sortKey) setDesc(!desc);
    else {
      setSortKey(k);
      setDesc(true);
    }
  }
  return (
    <div data-testid="ticker-table">
      <p className="mb-1 text-xs text-muted md:hidden">Scroll sideways to see every column.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
            <tr>
              <th className="py-2 pr-4 font-semibold">Ticker</th>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  className="py-2 pr-4 text-right font-semibold"
                  aria-sort={sortKey === c.key ? (desc ? "descending" : "ascending") : "none"}
                >
                  <button type="button" onClick={() => sortBy(c.key)} className="min-h-11 whitespace-nowrap font-semibold md:min-h-6">
                    {c.label}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.symbol} className="border-t border-border">
                <td className="py-2 pr-4 font-mono font-semibold">
                  <Link href={`/ledger/ticker/${t.symbol}`} className="text-content underline-offset-2 hover:underline">
                    {t.symbol}
                  </Link>
                </td>
                <td className={clsx(NUM, signClass(t.total_realized))}>{money(t.total_realized, t.currency)}</td>
                <td className={NUM}>{money(t.option_net_pnl, t.currency)}</td>
                <td className={NUM}>{money(t.stock_realized, t.currency)}</td>
                <td className={NUM}>{money(t.dividends_net, t.currency)}</td>
                <td className={clsx(NUM, signClass(t.unrealized))}>{money(t.unrealized, t.currency)}</td>
                <td className={NUM}>{t.n_trades}</td>
                <td className={NUM}>{rate(t.win_rate)}</td>
                <td className={NUM}>{pct(t.annualised_return_pct)}</td>
                <td className={NUM}>{t.shares_held}</td>
                <td className={NUM}>{money(t.wheel_adjusted_basis, t.currency)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [x] **Step 6: Restyle `LedgerOverview`** — replace `web/components/ledger/LedgerOverview.tsx` with:

```tsx
"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";
import { MonthlyBars, PnlCurve } from "./Charts";
import { money, rate, signClass } from "./format";
import { OutcomePill } from "./OutcomePill";
import { TickerTable } from "./TickerTable";
import { Tile, TileList } from "./Tile";
import type { LedgerBucket, LedgerSummary, LedgerSummaryResponse, LedgerTickersResponse } from "./types";

const H2 = "text-[1.0625rem] font-bold";
const LINK = "inline-flex min-h-11 items-center font-semibold underline underline-offset-2 md:min-h-8";

function Tiles({ s }: { s: LedgerSummary }) {
  return (
    <TileList testId="ledger-tiles">
      <Tile id="total" label="Total profit" value={money(s.total_realized_usd)} tone={signClass(s.total_realized_usd)} />
      <Tile id="contributed" label="Contributed capital" value={money(s.contributed_usd)} />
      <Tile id="utilised" label="Capital utilised" value={money(s.capital_utilised_usd)} />
      <Tile id="available" label="Available capital" value={money(s.available_usd)} />
      <Tile id="unrealized" label="Unrealised" value={money(s.unrealized_usd)} tone={signClass(s.unrealized_usd)} />
      <Tile id="win-rate" label="Win rate" value={rate(s.win_rate)} />
      <Tile id="month" label="Premium this month" value={money(s.premium_this_month_usd)} />
    </TileList>
  );
}

function Buckets({ title, rows }: { title: string; rows: LedgerBucket[] }) {
  return (
    <Card as="section" aria-label={title} data-testid={`buckets-${title.split(" ")[1]}`}>
      <h2 className={H2}>{title}</h2>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
            <tr>
              <th className="py-1.5 pr-4 font-semibold">Group</th>
              <th className="py-1.5 pr-4 text-right font-semibold">Closed</th>
              <th className="py-1.5 pr-4 text-right font-semibold">Realised</th>
              <th className="py-1.5 pr-4 text-right font-semibold">Win rate</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.label} className="border-t border-border">
                <td className="py-2 pr-4">{b.label}</td>
                <td className="tabular py-2 pr-4 text-right font-mono">{b.n_closed}</td>
                <td className={`tabular py-2 pr-4 text-right font-mono ${signClass(b.realized_usd)}`}>
                  {money(b.realized_usd)}
                </td>
                <td className="tabular py-2 pr-4 text-right font-mono">{rate(b.win_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/**
 * The broker-truth ledger's overview, the Ledger view on Activity: what IBKR reports, built from
 * the live feed, the Flex query and statement imports, with the trades list, the ticker pages and
 * the statement import one link away. It has no sub-navigation of its own: those pages lead back
 * here.
 */
export function LedgerOverview() {
  const summary = useQuery({
    queryKey: ["ledger", "summary"],
    queryFn: () => apiFetch<LedgerSummaryResponse>("/ledger/summary"),
  });
  const tickers = useQuery({
    queryKey: ["ledger", "tickers"],
    queryFn: () => apiFetch<LedgerTickersResponse>("/ledger/tickers"),
  });
  const s = summary.data?.summary;

  return (
    <div className="grid gap-4" data-testid="ledger-overview">
      <div className="grid gap-1">
        <p className="text-[0.8125rem] text-muted">
          What IBKR reports, from the live feed, the Flex query and statement imports. It can differ from the
          system&apos;s own record under Pay.
        </p>
        <p className="flex flex-wrap gap-x-5 text-[0.8125rem]">
          <Link href="/ledger/trades" className={LINK}>
            All trades
          </Link>
          <Link href="/ledger/import" className={LINK}>
            Import a statement
          </Link>
        </p>
      </div>
      {summary.isError && <p className="text-sm text-muted">Could not load the ledger.</p>}
      {!s && !summary.isError && <p className="text-sm text-muted">Loading the ledger</p>}
      {s && (
        <>
          <Card as="section" aria-labelledby="ledger-totals">
            <h2 id="ledger-totals" className={H2}>
              Totals
            </h2>
            <Tiles s={s} />
            {s.orphan_closes > 0 && (
              <p className="mt-3 text-sm text-unknown">
                {s.orphan_closes} closing trades have no opening in the imported history. Import the earlier
                statement to complete them.
              </p>
            )}
            {s.fx_incomplete && (
              <p className="mt-3 text-sm text-unknown">
                Some non-USD figures have no FX rate yet and are left out of USD totals. A Flex pull fills them in.
              </p>
            )}
          </Card>
          <div className="grid items-start gap-4 lg:grid-cols-2">
            <Card as="section" aria-label="Cumulative realised P&L">
              <PnlCurve points={s.curve} />
              <p className="mt-1 text-xs text-muted" data-testid="curve-caption">
                Trading P&amp;L only. The Total profit tile also includes interest and fees.
              </p>
            </Card>
            <Card as="section" aria-label="Premium and realised by month">
              <MonthlyBars months={s.months} />
            </Card>
          </div>
          {(s.by_strategy.length > 0 || s.by_book.length > 0) && (
            <div className="grid items-start gap-4 md:grid-cols-2">
              <Buckets title="By strategy" rows={s.by_strategy} />
              <Buckets title="By book (wheel system, credit spreads, your own trades)" rows={s.by_book} />
            </div>
          )}
        </>
      )}
      <Card as="section" aria-labelledby="ledger-tickers">
        <h2 id="ledger-tickers" className={H2}>
          By ticker
        </h2>
        <div className="mt-2">
          {tickers.isError && <p className="text-sm text-muted">Could not load tickers.</p>}
          {tickers.isLoading && <p className="text-sm text-muted">Loading tickers</p>}
          {tickers.data && <TickerTable tickers={tickers.data.tickers} />}
        </div>
      </Card>
      {s && s.upcoming.length > 0 && (
        <Card as="section" aria-labelledby="ledger-upcoming">
          <h2 id="ledger-upcoming" className={H2}>
            Upcoming expiries
          </h2>
          <ul className="mt-1">
            {s.upcoming.map((t) => (
              <li
                key={t.order_key}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border py-2.5 text-sm first:border-t-0"
              >
                <span className="tabular font-mono text-muted">{t.expiry}</span>
                <Link href={`/ledger/ticker/${t.underlying}`} className="font-mono font-semibold hover:underline">
                  {t.underlying}
                </Link>
                <span className="tabular font-mono">
                  {t.side} {t.lots} x {t.strike}
                  {t.right}
                </span>
                <OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
```

  The `data-testid` values (`ledger-overview`, `ledger-tiles`, `curve-caption`, `buckets-strategy`,
  `buckets-book`) and every sentence the old tests read are the old ones.

- [x] **Step 7: Put `TickerView`'s tiles in a `TileList`** — in `web/components/ledger/TickerView.tsx`
  change `import { Tile } from "./Tile";` to `import { Tile, TileList } from "./Tile";`, and replace
  the tile grid's opening `<div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">`
  with `<TileList>` and its closing `</div>` (the one directly before
  `<p className="text-xs text-muted">` ) with `</TileList>`. The page itself is restyled in the next
  task; this keeps the `Tile` lines valid HTML in the meantime.

- [x] **Step 8: Run the tests, then the gate**

Run: `cd web && npx vitest run components/ledger && npx tsc --noEmit && npm run lint`
Expected: PASS: 2 + 3 + 1 + 4 new tests; every existing `LedgerOverview`, `TickerView`, `TradesView`
and `ImportView` test **unmodified** (they still render `LedgerNav`, which is unmounted from the
overview only; the others lose it in Task 11).

- [x] **Step 9: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/components/ledger`
Expected: exit 0 over every non-test source file, or every finding fixed in the code.

- [x] **Step 10: Commit** (with the Progress log row for Task 10 filled in)

```bash
git add web/components/ledger docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): the ledger overview in the figure face, with no sub-navigation"
```

---

### Task 11: Ledger — the trades, ticker and import pages

**Files:**
- Modify (restyle in place, whole files): `web/components/ledger/TradesTable.tsx`, `TradesView.tsx`,
  `TradePanel.tsx`, `TickerView.tsx`, `ImportView.tsx`
- Modify: `web/app/ledger/trades/page.tsx`, `web/app/ledger/import/page.tsx`,
  `web/app/ledger/ticker/[symbol]/page.tsx` (the page frame)
- Modify: `web/components/ledger/TradesView.test.tsx` (+4), `TickerView.test.tsx` (+2),
  `ImportView.test.tsx` (+2)

**Interfaces:**
- Consumes: `BackToLedger`, `LedgerShell`, `Tile`/`TileList`, `OutcomePill` (Task 10), `FIELD`,
  `FIELD_LABEL`, `Button`, `Card`, `Sheet`.
- Produces: the same exports as today (`TradesTable`, `TradesView({ fixedSymbol? })`,
  `TradePanel({ orderKey, onClose })`, `TickerView({ symbol })`, `ImportView()`), without
  `LedgerNav`. `TradePanel` is a `Sheet` (a right sheet on a desktop, a bottom sheet on a phone)
  instead of a fixed panel with its own shadow.

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: the same data and the same
  flows in the payslip world: the trade detail in the app's sheet, fields in the `field` look,
  tables with hairline rows in the figure face that scroll inside their own box.

- [x] **Step 2: Write the failing tests**

  Append inside `describe("TradesView", ...)` in `TradesView.test.tsx` (the file's helpers `aTrade`,
  `ISO` and its `next/navigation` mock stay; the mock is no longer needed once `LedgerNav` is
  gone, and the test does not care):

```tsx
  it("leads back to the Ledger view, and its page has a heading", async () => {
    renderWithQuery(<TradesView />, { "/ledger/trades": { as_of: ISO, n: 0, trades: [], filters: {} } });
    expect(await screen.findByRole("link", { name: "Back to Activity, Ledger" })).toHaveAttribute("href", "/activity?view=ledger");
    expect(screen.getByRole("heading", { level: 1, name: "Ledger trades" })).toBeInTheDocument();
  });

  it("has neither the back link nor the heading when pinned to a ticker", async () => {
    renderWithQuery(<TradesView fixedSymbol="NVDA" />, { "/ledger/trades": { as_of: ISO, n: 0, trades: [], filters: {} } });
    await screen.findByText("0 trades");
    expect(screen.queryByRole("link", { name: "Back to Activity, Ledger" })).toBeNull();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });

  it("opens a trade from the keyboard as well as the mouse", async () => {
    renderWithQuery(<TradesView />, {
      "/ledger/trades/0123456789abcdef": { as_of: ISO, trade: aTrade(), executions: [] },
      "/ledger/trades": { as_of: ISO, n: 1, trades: [aTrade()], filters: {} },
    });
    const row = (await screen.findByText("NVDA")).closest("tr") as HTMLElement;
    expect(row).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(await screen.findByRole("dialog", { name: "Trade" })).toBeInTheDocument();
  });

  it("shows the trade in the app's sheet and closes it", async () => {
    renderWithQuery(<TradesView />, {
      "/ledger/trades/0123456789abcdef": { as_of: ISO, trade: aTrade(), executions: [] },
      "/ledger/trades": { as_of: ISO, n: 1, trades: [aTrade()], filters: {} },
    });
    fireEvent.click(await screen.findByText("NVDA"));
    const dialog = await screen.findByRole("dialog", { name: "Trade" });
    expect(await within(dialog).findByLabelText("Notes")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
```

  (add `within` to the file's `@testing-library/react` import). Append inside
  `describe("TickerView", ...)` in `TickerView.test.tsx`:

```tsx
  it("leads back to the Ledger view and keeps its figures as lines of one list", async () => {
    renderWithQuery(<TickerView symbol="amzn" />, {
      "/ledger/tickers/AMZN": { as_of: ISO, detail: DETAIL },
      "/ledger/trades": { as_of: ISO, n: 0, trades: [], filters: {} },
    });
    expect(await screen.findByRole("link", { name: "Back to Activity, Ledger" })).toHaveAttribute("href", "/activity?view=ledger");
    expect(screen.getByTestId("tile-broker-cost").closest("dl")).not.toBeNull();
  });

  it("leads back from the no-history state too", async () => {
    apiFetchMock.mockImplementation(async () => { throw new ApiError(404, "No ledger history"); });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><TickerView symbol="ZZZZ" /></QueryClientProvider>);
    expect(await screen.findByText(/No ledger history for ZZZZ/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Activity, Ledger" })).toBeInTheDocument();
  });
```

  Append inside `describe("ImportView", ...)` in `ImportView.test.tsx`:

```tsx
  it("leads back to the Ledger view and has a heading of its own", async () => {
    renderWithQuery(<ImportView />, { "/ledger/imports": IMPORTS });
    expect(await screen.findByRole("link", { name: "Back to Activity, Ledger" })).toHaveAttribute("href", "/activity?view=ledger");
    expect(screen.getByRole("heading", { level: 1, name: "Import a statement" })).toBeInTheDocument();
  });

  it("says a feed that is failing, in words", async () => {
    renderWithQuery(<ImportView />, {
      "/ledger/imports": { ...IMPORTS, flex: { configured: true, last_run: null, last_status: null, last_error: "token expired" } },
    });
    expect(await screen.findByText(/Flex pull: failing: token expired/)).toBeInTheDocument();
  });
```

- [x] **Step 3: Run them to verify they fail**

Run: `cd web && npx vitest run components/ledger/TradesView.test.tsx components/ledger/TickerView.test.tsx components/ledger/ImportView.test.tsx`
Expected: FAIL (the 8 new tests: no back link, no heading, no dialog, no keyboard).

- [x] **Step 4: Restyle `TradesTable`** — replace `web/components/ledger/TradesTable.tsx` with:

```tsx
"use client";

import clsx from "clsx";
import { money, pct, signClass } from "./format";
import { OutcomePill } from "./OutcomePill";
import type { LedgerTrade } from "./types";

const HEADERS = [
  "Sell/Buy", "Put/Call", "Order Date", "Expiry", "Ticker", "Lots", "Strike", "Premium",
  "Outcome", "Stock gain", "DTE", "% Profit", "Net P&L", "Closed", "Book", "Notes",
];
const RIGHT = new Set(["Lots", "Strike", "Premium", "Stock gain", "DTE", "% Profit", "Net P&L"]);
const NUM = "tabular py-2 pr-4 text-right font-mono";

/** The operator's sheet as a table. A row opens the trade from the mouse or the keyboard. */
export function TradesTable({ trades, onSelect }: { trades: LedgerTrade[]; onSelect: (key: string) => void }) {
  if (trades.length === 0) return <p className="text-sm text-muted">No trades match the current filters.</p>;
  return (
    <div data-testid="trades-table">
      <p className="mb-1 text-xs text-muted md:hidden">Scroll sideways to see every column.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
            <tr>
              {HEADERS.map((h) => (
                <th key={h} scope="col" className={clsx("whitespace-nowrap py-2 pr-4 font-semibold", RIGHT.has(h) && "text-right")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr
                key={t.order_key}
                tabIndex={0}
                onClick={() => onSelect(t.order_key)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(t.order_key);
                  }
                }}
                className="cursor-pointer border-t border-border hover:bg-sunk focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
              >
                <td className="py-2 pr-4">{t.side}</td>
                <td className="py-2 pr-4">{t.right === "P" ? "Put" : "Call"}</td>
                <td className="tabular py-2 pr-4 font-mono">{t.order_date}</td>
                <td className="tabular py-2 pr-4 font-mono">{t.expiry}</td>
                <td className="py-2 pr-4 font-mono font-semibold">{t.underlying}</td>
                <td className={NUM}>{t.lots}</td>
                <td className={NUM}>{t.strike}</td>
                <td className={clsx(NUM, signClass(t.premium))}>{money(t.premium, t.currency)}</td>
                <td className="py-2 pr-4">
                  <OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} />
                </td>
                <td className={NUM}>{t.stock_gain === null ? "" : money(t.stock_gain, t.currency)}</td>
                <td className={NUM}>{t.dte}</td>
                <td className={NUM}>{pct(t.pct_profit)}</td>
                <td className={clsx(NUM, signClass(t.net_pnl))}>{money(t.net_pnl, t.currency)}</td>
                <td className="tabular py-2 pr-4 font-mono">{t.close_date ?? ""}</td>
                <td className="py-2 pr-4 text-muted">{t.book}</td>
                <td className="max-w-[16rem] truncate py-2 pr-4 text-muted">{t.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [x] **Step 5: Restyle `TradesView`** — replace `web/components/ledger/TradesView.tsx` with:

```tsx
"use client";

import clsx from "clsx";
import { useId, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { apiFetch } from "@/lib/api";
import { BackToLedger } from "./BackToLedger";
import { TradePanel } from "./TradePanel";
import { TradesTable } from "./TradesTable";
import { OUTCOMES, type LedgerTradesResponse } from "./types";

type Filters = { symbol: string; right: string; outcome: string; book: string; tag: string; since: string; until: string; sort: string };
const EMPTY: Filters = { symbol: "", right: "", outcome: "", book: "", tag: "", since: "", until: "", sort: "-order_date" };

function Field({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="grid gap-1">
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      {children(id)}
    </div>
  );
}

/**
 * The operator's sheet as a filterable table. One composed query string drives both the
 * fetch and the CSV export link, so the export always carries the filters on screen.
 * `fixedSymbol` pins the ticker (the drill-down page) and hides the back link, the heading and the
 * ticker filter.
 */
export function TradesView({ fixedSymbol }: { fixedSymbol?: string }) {
  const [f, setF] = useState<Filters>(EMPTY);
  const [selected, setSelected] = useState<string | null>(null);
  const qs = useMemo(() => {
    const p = new URLSearchParams();
    const symbol = fixedSymbol ?? f.symbol.trim().toUpperCase();
    if (symbol) p.set("symbol", symbol);
    for (const k of ["right", "outcome", "book", "tag", "since", "until"] as const) if (f[k]) p.set(k, f[k]);
    p.set("sort", f.sort);
    return p.toString();
  }, [f, fixedSymbol]);
  const { data, isError } = useQuery({
    queryKey: ["ledger", "trades", qs],
    queryFn: () => apiFetch<LedgerTradesResponse>(`/ledger/trades?${qs}`),
  });
  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setF((prev) => ({ ...prev, [k]: e.target.value }));
  const select = clsx(FIELD, "w-full");

  return (
    <div className="grid gap-4" data-testid="trades-view">
      {!fixedSymbol && (
        <div className="grid gap-1">
          <BackToLedger />
          <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Ledger trades</h1>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {!fixedSymbol && (
          <Field label="Ticker">
            {(id) => <input id={id} value={f.symbol} onChange={set("symbol")} autoComplete="off" autoCapitalize="characters" spellCheck={false} className={select} />}
          </Field>
        )}
        <Field label="Put/Call">
          {(id) => (
            <select id={id} value={f.right} onChange={set("right")} className={select}>
              <option value="">All</option>
              <option value="P">Put</option>
              <option value="C">Call</option>
            </select>
          )}
        </Field>
        <Field label="Outcome">
          {(id) => (
            <select id={id} value={f.outcome} onChange={set("outcome")} className={select}>
              <option value="">All</option>
              {OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Book">
          {(id) => (
            <select id={id} value={f.book} onChange={set("book")} className={select}>
              <option value="">All</option>
              <option value="system">System</option>
              <option value="manual">Manual</option>
              <option value="spreads">Spreads</option>
            </select>
          )}
        </Field>
        <Field label="Tag">{(id) => <input id={id} value={f.tag} onChange={set("tag")} autoComplete="off" className={select} />}</Field>
        <Field label="From">{(id) => <input id={id} type="date" value={f.since} onChange={set("since")} className={select} />}</Field>
        <Field label="To">{(id) => <input id={id} type="date" value={f.until} onChange={set("until")} className={select} />}</Field>
        <Field label="Sort">
          {(id) => (
            <select id={id} value={f.sort} onChange={set("sort")} className={select}>
              <option value="-order_date">Newest first</option>
              <option value="order_date">Oldest first</option>
              <option value="-pct_profit">% Profit high to low</option>
              <option value="-net_pnl">Net P&L high to low</option>
              <option value="net_pnl">Net P&L low to high</option>
              <option value="expiry">Expiry soonest</option>
            </select>
          )}
        </Field>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        {data ? <p className="text-[0.8125rem] text-muted">{data.n} trades</p> : <span />}
        <a
          href={`/api/ledger/trades.csv?${qs}`}
          className="inline-flex min-h-11 items-center text-[0.8125rem] font-semibold underline underline-offset-2 md:min-h-8"
        >
          Export CSV
        </a>
      </div>
      {isError && <p className="text-sm text-muted">Could not load trades.</p>}
      {data && <TradesTable trades={data.trades} onSelect={setSelected} />}
      {selected && <TradePanel key={selected} orderKey={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
```

- [x] **Step 6: Restyle `TradePanel` as a sheet** — replace `web/components/ledger/TradePanel.tsx` with
  the file below. The form state, the resync rule and the `ledger_annotate` flow above `return`
  are the old code, unchanged; the shell is `Sheet`, the fields are `field`s and Save is a
  secondary `Button`.

```tsx
"use client";

import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { Sheet } from "@/components/ui/Sheet";
import { apiFetch } from "@/lib/api";
import { submitCommand, useCommandStatus } from "@/lib/commands";
import { money, pct } from "./format";
import { OutcomePill } from "./OutcomePill";
import { OUTCOMES, type LedgerTradeResponse } from "./types";

export function TradePanel({ orderKey, onClose }: { orderKey: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["ledger", "trade", orderKey],
    queryFn: () => apiFetch<LedgerTradeResponse>(`/ledger/trades/${orderKey}`),
  });
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [override, setOverride] = useState("");
  const [exclude, setExclude] = useState(false);
  const [commandId, setCommandId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const status = useCommandStatus(commandId);

  // Re-sync the form from server data only for a newly selected trade or right after a save
  // was applied, never on a background refetch (that would wipe unsaved edits).
  const syncedKey = useRef<string | null>(null);
  const resync = useRef(false);

  useEffect(() => {
    if (!data) return;
    if (syncedKey.current === orderKey && !resync.current) return;
    syncedKey.current = orderKey;
    resync.current = false;
    setNotes(data.trade.notes);
    setTags(data.trade.tags.join(", "));
    setOverride(data.trade.outcome_overridden ? data.trade.outcome : "");
    setExclude(data.trade.exclude_from_stats);
  }, [data, orderKey]);

  useEffect(() => {
    if (status.data?.status === "applied") resync.current = true;
    if (status.data?.status === "applied") void qc.invalidateQueries({ queryKey: ["ledger"] });
  }, [status.data?.status, qc]);

  async function save() {
    setError(null);
    try {
      const r = await submitCommand("ledger_annotate", {
        order_key: orderKey,
        notes,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        outcome_override: override,
        exclude_from_stats: exclude,
      });
      setCommandId(r.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    }
  }

  const state = status.data?.status;
  const t = data?.trade;
  return (
    <Sheet open onClose={onClose} title="Trade">
      {!data && <p className="text-sm text-muted">Loading</p>}
      {data && t && (
        <div className="grid gap-5">
          <div className="grid gap-2">
            <p className="font-mono text-sm font-semibold">
              {t.side} {t.lots} x {t.underlying} {t.expiry} {t.strike}
              {t.right}
            </p>
            <p>
              <OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} />
            </p>
            <dl className="tabular border-t-2 border-dashed border-perforation pt-2 font-mono text-[0.84375rem] font-medium">
              {[
                ["Premium", money(t.premium, t.currency)],
                ["Net P&L", money(t.net_pnl, t.currency)],
                ["% Profit (sheet)", pct(t.pct_profit)],
                ["Annualised net", pct(t.annualised_net_pct)],
                ["IBKR realised", money(t.ibkr_realized_pnl, t.currency)],
                ...(t.rolled_from ? [["Rolled from", t.rolled_from]] : []),
                ...(t.rolled_to ? [["Rolled to", t.rolled_to]] : []),
              ].map(([label, value]) => (
                <div key={label} className="flex min-h-6 items-baseline justify-between gap-3">
                  <dt className="min-w-0 font-sans font-normal text-muted">{label}</dt>
                  <dd className={clsx("text-right", value === "n/a" && "hatch text-unknown")}>{value}</dd>
                </div>
              ))}
            </dl>
          </div>
          <section className="grid gap-1">
            <h3 className="text-[1.0625rem] font-bold">Executions</h3>
            <ul className="tabular font-mono text-xs text-muted">
              {data.executions.map((e) => (
                <li key={e.id} className="border-t border-border py-1.5 first:border-t-0">
                  {e.trade_time.slice(0, 19).replace("T", " ")} {e.quantity} @ {e.price} {e.codes} ({e.source}
                  {e.superseded_by ? ", superseded" : ""})
                </li>
              ))}
            </ul>
          </section>
          <section className="grid gap-3">
            <label className="grid gap-1 text-sm">
              <span className={FIELD_LABEL}>Notes</span>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className={clsx(FIELD, "w-full py-2")} />
            </label>
            <label className="grid gap-1 text-sm">
              <span className={FIELD_LABEL}>Tags (comma separated)</span>
              <input value={tags} onChange={(e) => setTags(e.target.value)} className={clsx(FIELD, "w-full")} />
            </label>
            <label className="grid gap-1 text-sm">
              <span className={FIELD_LABEL}>Outcome override</span>
              <select value={override} onChange={(e) => setOverride(e.target.value)} className={clsx(FIELD, "w-full")}>
                <option value="">Use computed ({t.computed_outcome})</option>
                {OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-h-11 items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={exclude} onChange={(e) => setExclude(e.target.checked)} className="h-5 w-5" />
              Exclude from win rate and averages (still counted in money totals)
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="secondary" onClick={save}>
                Save
              </Button>
              {state === "pending" && <span className="text-sm text-muted">Saving</span>}
              {state === "applied" && <span className="text-sm text-gain">Saved</span>}
              {state === "failed" && (
                <span className="text-sm text-loss">Not saved: {String(status.data?.result?.reason ?? "error")}</span>
              )}
              {error && <span className="text-sm text-loss">{error}</span>}
            </div>
          </section>
        </div>
      )}
    </Sheet>
  );
}
```

- [x] **Step 7: Restyle `TickerView`** — replace `web/components/ledger/TickerView.tsx` with:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card } from "@/components/ui/Card";
import { ApiError, apiFetch } from "@/lib/api";
import { BackToLedger } from "./BackToLedger";
import { money, pct, rate, signClass } from "./format";
import { Tile, TileList } from "./Tile";
import { TradesView } from "./TradesView";
import type { LedgerTickerResponse } from "./types";

const H2 = "text-[1.0625rem] font-bold";
const TH = "py-1.5 pr-4 font-semibold";

export function TickerView({ symbol }: { symbol: string }) {
  const upper = symbol.toUpperCase();
  const { data, error } = useQuery({
    queryKey: ["ledger", "ticker", upper],
    queryFn: () => apiFetch<LedgerTickerResponse>(`/ledger/tickers/${upper}`),
    retry: false,
  });

  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="grid gap-3">
        <BackToLedger />
        <p className="text-sm text-muted">No ledger history for {upper}.</p>
      </div>
    );
  }
  if (error) {
    return (
      <div className="grid gap-3">
        <BackToLedger />
        <p className="text-sm text-muted">Could not load {upper}.</p>
      </div>
    );
  }
  if (!data) return <p className="text-sm text-muted">Loading {upper}</p>;

  const d = data.detail;
  const t = d.ticker;
  return (
    <div className="grid gap-4" data-testid="ticker-view">
      <div className="grid gap-1">
        <BackToLedger />
        <h1 className="font-mono text-2xl font-extrabold tracking-[-0.015em]">{t.symbol}</h1>
      </div>
      <Card as="section" aria-label={`${t.symbol} figures`}>
        <TileList>
          <Tile id="total" label="Total realised" value={money(t.total_realized, t.currency)} tone={signClass(t.total_realized)} />
          <Tile id="options" label="Options net" value={money(t.option_net_pnl, t.currency)} />
          <Tile id="stock" label="Stock realised" value={money(t.stock_realized, t.currency)} />
          <Tile id="dividends" label="Dividends net" value={money(t.dividends_net, t.currency)} />
          <Tile id="unrealized" label="Unrealised" value={money(t.unrealized, t.currency)} tone={signClass(t.unrealized)} />
          <Tile id="win-rate" label="Win rate" value={rate(t.win_rate)} />
          <Tile id="broker-cost" label="Broker avg cost" value={money(t.broker_avg_cost, t.currency)} />
          <Tile id="wheel-basis" label="Wheel-adjusted basis" value={money(t.wheel_adjusted_basis, t.currency)} />
        </TileList>
        <p className="mt-3 text-xs text-muted">
          {t.n_trades} trades, {t.n_open} open. Annualised return on capital-days {pct(t.annualised_return_pct)}. Shares held {t.shares_held}.
        </p>
      </Card>

      {d.basis_walk.length > 0 && (
        <Card as="section" aria-labelledby="basis-walk">
          <h2 id="basis-walk" className={H2}>
            Cost-basis walk
          </h2>
          <figure className="mt-2 h-56" aria-label="Wheel-adjusted cost basis per share">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.basis_walk}>
                <XAxis dataKey="point_date" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={60} />
                <Tooltip formatter={(v) => money(Number(v), t.currency)} labelFormatter={(_, p) => p?.[0]?.payload?.label ?? ""} />
                <Line type="stepAfter" dataKey="basis_per_share" stroke="var(--chart-line)" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </figure>
          <ol className="tabular mt-2 font-mono text-xs text-muted">
            {d.basis_walk.map((p, i) => (
              <li key={i} className="border-t border-border py-1.5 first:border-t-0">
                {p.point_date} {p.label}: {money(p.basis_per_share, t.currency)}
              </li>
            ))}
          </ol>
        </Card>
      )}

      {d.lots.length > 0 && (
        <Card as="section" aria-labelledby="share-lots">
          <h2 id="share-lots" className={H2}>
            Share lots
          </h2>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-[0.8125rem]">
              <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
                <tr>
                  <th className={TH}>Acquired</th>
                  <th className={TH}>How</th>
                  <th className={`${TH} text-right`}>Qty</th>
                  <th className={`${TH} text-right`}>Remaining</th>
                  <th className={`${TH} text-right`}>Cost/share</th>
                </tr>
              </thead>
              <tbody>
                {d.lots.map((l) => (
                  <tr key={l.lot_key} className="border-t border-border">
                    <td className="tabular py-2 pr-4 font-mono">{l.acquired_date}</td>
                    <td className="py-2 pr-4">{l.source}</td>
                    <td className="tabular py-2 pr-4 text-right font-mono">{l.quantity}</td>
                    <td className="tabular py-2 pr-4 text-right font-mono">{l.remaining}</td>
                    <td className="tabular py-2 pr-4 text-right font-mono">{money(l.cost_per_share, l.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {d.dividends.length > 0 && (
        <Card as="section" aria-labelledby="dividends">
          <h2 id="dividends" className={H2}>
            Dividends and withholding
          </h2>
          <ul className="mt-1 text-sm">
            {d.dividends.map((c, i) => (
              <li key={i} className="tabular flex flex-wrap gap-x-3 border-t border-border py-2 first:border-t-0">
                <span className="font-mono text-muted">{c.event_date}</span>
                <span className={`font-mono ${signClass(c.amount)}`}>{money(c.amount, c.currency)}</span>
                <span className="text-muted">{c.event_type}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <section className="grid gap-2">
        <h2 className={H2}>Every trade</h2>
        <TradesView fixedSymbol={upper} />
      </section>
    </div>
  );
}
```

- [x] **Step 8: Restyle `ImportView`** — replace `web/components/ledger/ImportView.tsx` with the file
  below. The upload flow, the size and type checks, the messages and the corporate-action review
  are the old code, unchanged; only the shell and the controls are new.

```tsx
"use client";

import clsx from "clsx";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";
import { submitCommand, useCommandStatus } from "@/lib/commands";
import { BackToLedger } from "./BackToLedger";
import type { LedgerFeedStatus, LedgerImportsResponse } from "./types";

// Client-side UX hint only; the server enforces ledger.upload_max_bytes (ruling F6).
const MAX_BYTES = 5 * 1024 * 1024;
const H2 = "text-[1.0625rem] font-bold";

// FileReader rather than File.text(): same result, and it exists in every browser and in jsdom.
function readText(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result ?? ""));
    r.onerror = () => reject(r.error);
    r.readAsText(f);
  });
}

function Feed({ label, s }: { label: string; s: LedgerFeedStatus }) {
  let text = "not set up (see SETUP.md, Trade ledger)";
  if (s.configured)
    text = s.last_error
      ? `failing: ${s.last_error}`
      : s.last_run
        ? `last run ${s.last_run.slice(0, 16).replace("T", " ")} UTC${s.last_status ? ` (${s.last_status})` : ""}`
        : "set up, not run yet";
  return (
    <li className="text-sm text-muted">
      {label}: {text}
    </li>
  );
}

export function ImportView() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["ledger", "imports"], queryFn: () => apiFetch<LedgerImportsResponse>("/ledger/imports") });
  const [commandId, setCommandId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const status = useCommandStatus(commandId);

  const [reviewId, setReviewId] = useState<{ command: number; action: number } | null>(null);
  const reviewStatus = useCommandStatus(reviewId?.command ?? null);
  const reviewPending = reviewId !== null && !(reviewStatus.data && reviewStatus.data.status !== "pending");

  useEffect(() => {
    const st = status.data;
    if (!st) return;
    if (st.status === "applied") {
      const counts = (st.result?.counts ?? null) as Record<string, number> | null;
      const part = (key: string, label: string) => `${counts && typeof counts[key] === "number" ? counts[key] : "n/a"} ${label}`;
      setMessage(`Imported: ${part("new", "new")}, ${part("duplicate", "already present")}, ${part("superseded", "merged with broker fills")}.`);
      void qc.invalidateQueries({ queryKey: ["ledger"] });
    } else if (st.status === "failed") {
      setMessage(`Import failed: ${String(st.result?.reason ?? "error")}`);
    }
  }, [status.data, qc]);

  useEffect(() => {
    const st = reviewStatus.data;
    if (!st) return;
    if (st.status === "applied") {
      void qc.invalidateQueries({ queryKey: ["ledger"] });
    } else if (st.status === "failed" || st.status === "expired") {
      setMessage(`Could not mark reviewed: ${String(st.result?.reason ?? st.status)}`);
    }
  }, [reviewStatus.data, qc]);

  async function onFile(f: File | undefined) {
    setMessage(null);
    if (!f) return;
    if (f.name.toLowerCase().endsWith(".pdf")) {
      setMessage("PDF statements are not supported. In Client Portal, open the same statement and choose CSV as the format.");
      return;
    }
    if (f.size > MAX_BYTES) {
      setMessage("That file is over 5 MB. Split the period into two statements.");
      return;
    }
    try {
      const content = await readText(f);
      const r = await submitCommand("ledger_import", { filename: f.name, content });
      setCommandId(r.id);
      setMessage("Importing");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Upload failed");
    }
  }

  async function markReviewed(id: number) {
    setMessage(null);
    try {
      const r = await submitCommand("ledger_ca_reviewed", { corporate_action_id: id });
      setReviewId({ command: r.id, action: id });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not mark reviewed");
    }
  }

  return (
    <div className="grid gap-4" data-testid="import-view">
      <div className="grid gap-1">
        <BackToLedger />
        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Import a statement</h1>
      </div>
      <Card as="section" aria-labelledby="upload-title">
        <h2 id="upload-title" className={H2}>
          Upload an IBKR Activity Statement
        </h2>
        <p className="mt-1 text-[0.8125rem] text-muted">
          Client Portal, Performance and Reports, Statements, Activity, format CSV. Re-uploading the same file changes nothing.
        </p>
        <label className="mt-3 grid gap-2 text-sm text-muted">
          Activity Statement CSV
          <input
            type="file"
            accept=".csv,text/csv"
            aria-label="Activity Statement CSV"
            onChange={(e) => void onFile(e.target.files?.[0])}
            className="block min-h-11 text-sm text-content"
          />
        </label>
        {message && (
          <p className="mt-2 text-sm text-content" role="status">
            {message}
          </p>
        )}
      </Card>

      {data && (
        <>
          <ul className="grid gap-1">
            <Feed label="Flex pull" s={data.flex} />
            <Feed label="Google Sheet mirror" s={data.sheets} />
          </ul>

          {data.corporate_actions.length > 0 && (
            <Card as="section" aria-labelledby="corporate-actions">
              <h2 id="corporate-actions" className={H2}>
                Corporate actions
              </h2>
              <p className="mt-1 text-[0.8125rem] text-muted">
                These are stored but never applied to cost basis automatically. Check each one, then mark it reviewed.
              </p>
              <ul className="mt-2 text-sm">
                {data.corporate_actions.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border py-2 first:border-t-0">
                    <span className="tabular font-mono text-muted">{a.event_date}</span>
                    <span className="text-content">{a.description}</span>
                    {a.reviewed ? (
                      <span className="text-xs text-muted">reviewed</span>
                    ) : (
                      <Button variant="secondary" disabled={reviewPending} onClick={() => void markReviewed(a.id)}>
                        {reviewPending && reviewId?.action === a.id ? "Marking" : "Mark reviewed"}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card as="section" aria-labelledby="import-history">
            <h2 id="import-history" className={H2}>
              Import history
            </h2>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-[0.8125rem]">
                <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
                  <tr>
                    <th className="py-1.5 pr-4 font-semibold">When</th>
                    <th className="py-1.5 pr-4 font-semibold">Source</th>
                    <th className="py-1.5 pr-4 font-semibold">File</th>
                    <th className="py-1.5 pr-4 font-semibold">Result</th>
                    <th className="py-1.5 pr-4 font-semibold">Counts</th>
                  </tr>
                </thead>
                <tbody>
                  {data.runs.map((r) => (
                    <tr key={r.id} className="border-t border-border align-top">
                      <td className="tabular py-2 pr-4 font-mono">{r.started_at.slice(0, 16).replace("T", " ")}</td>
                      <td className="py-2 pr-4">{r.source}</td>
                      <td className="py-2 pr-4">{r.filename}</td>
                      <td className={clsx("py-2 pr-4", r.status === "ok" ? "text-gain" : "text-loss")}>
                        {r.status}
                        {r.reason ? ` (${r.reason})` : ""}
                      </td>
                      <td className="tabular py-2 pr-4 font-mono text-muted">
                        {Object.entries(r.counts).map(([k, v]) => `${k} ${v}`).join(", ")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
```

- [x] **Step 9: Frame the three pages** — replace the three page files:

  `web/app/ledger/trades/page.tsx`:

```tsx
import { LedgerShell } from "@/components/ledger/LedgerShell";
import { TradesView } from "@/components/ledger/TradesView";

export default function LedgerTradesPage() {
  return (
    <LedgerShell>
      <TradesView />
    </LedgerShell>
  );
}
```

  `web/app/ledger/import/page.tsx`:

```tsx
import { ImportView } from "@/components/ledger/ImportView";
import { LedgerShell } from "@/components/ledger/LedgerShell";

export default function LedgerImportPage() {
  return (
    <LedgerShell>
      <ImportView />
    </LedgerShell>
  );
}
```

  `web/app/ledger/ticker/[symbol]/page.tsx`:

```tsx
"use client";

import { use } from "react";
import { LedgerShell } from "@/components/ledger/LedgerShell";
import { TickerView } from "@/components/ledger/TickerView";

export default function LedgerTickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  return (
    <LedgerShell>
      <TickerView symbol={symbol} />
    </LedgerShell>
  );
}
```

- [x] **Step 10: Run the tests, then the gate**

Run: `cd web && npx vitest run components/ledger && npx tsc --noEmit && npm run lint`
Expected: PASS: the 8 new tests, and every existing `TradesView`, `TickerView`, `ImportView` and
`LedgerOverview` test **unmodified** (the save-notes, filters-into-the-request, CSV link, upload,
oversize, PDF, review-and-refresh and no-history cases are the proof the flows are untouched).
`LedgerNav.tsx` is now unmounted and stays for Part 4 (ruling 12).

- [x] **Step 11: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/components/ledger web/app/ledger`
Expected: exit 0 over every non-test source file, or every finding fixed in the code.

- [x] **Step 12: Commit** (with the Progress log row for Task 11 filled in)

```bash
git add web/components/ledger web/app/ledger docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): the ledger's trades, ticker and import pages - sheet, fields, back link"
```

---

### Task 12: Fills and orders — three lists, each naming its source

**Files:**
- Create: `web/features/activity/types.ts`, `fills.ts`, `fills.test.ts`, `ExecutionsList.tsx`,
  `ExecutionsList.test.tsx`, `SpreadFills.tsx`, `SpreadFills.test.tsx`, `FillsView.tsx`,
  `FillsView.test.tsx`
- Modify (restyle in place, whole files): `web/components/options/OrdersTable.tsx`,
  `web/components/options/FillsTable.tsx`
- Create: `web/components/options/FillsTable.test.tsx`
- Modify: `web/components/options/OrdersTable.test.tsx` (+5), `web/features/trades/time.ts`
  (+ `whenET`), `web/features/trades/time.test.ts` (+3)

**Interfaces:**
- Consumes: the regenerated types (`LedgerExecutionRowOut`, `LedgerExecutionsResponse`,
  `SpreadOrderOut`, `SpreadOrdersResponse`), `OrderSummary.sizing` and `FillSummary` contract
  fields (`components/options/types.ts`), `kindWord`/`reasonWords`/`sentSentence`
  (`features/market/market.ts`), `timeET`/`dayLabel`/`newYorkDay` (`features/trades/time.ts`),
  `SegmentedControl`, `StatusWord`, `Card`.
- Produces:
  - `whenET(iso: string): string` ("Thu, Oct 22 · 2:31 PM ET", "time n/a" when unreadable)
  - `fills.ts`: `WINDOWS`, `DEFAULT_WINDOW`, `windowLabel(days)`, `executionTitle(e)`, `bookWord(book)`,
    `sourceWord(source)`, `spreadOrderTitle(o, underlying)`
  - `OrdersTable({ days? })` (the window applies to All and Rejected, never to Working),
    `FillsTable({ days? })` (default 7, so its old path is unchanged), `ExecutionsList({ days })`,
    `SpreadFills({ days })`, `FillsView()` (Task 14 mounts it)

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: rows without table chrome, a
  state word on every order, the figure face for prices and counts, a labelled source on every list,
  unknown as a hatched n/a, a flag word only where something needs attention (a partial fill, Claude's cut).

- [x] **Step 2: Write the failing tests**

Append to `web/features/trades/time.test.ts` (add `whenET` to its import from `./time`):

```ts
describe("whenET", () => {
  it("writes an instant as a New York day and time", () => {
    expect(whenET("2026-10-22T18:31:00Z")).toBe("Thu, Oct 22 · 2:31 PM ET");
  });
  it("uses the New York day, not the UTC one", () => {
    expect(whenET("2026-10-23T02:31:00Z")).toBe("Thu, Oct 22 · 10:31 PM ET");
  });
  it("says when it cannot read the time", () => {
    expect(whenET("nope")).toBe("time n/a");
  });
});
```

Create `web/features/activity/fills.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { bookWord, executionTitle, lastWindow, sourceWord, spreadOrderTitle, windowLabel } from "./fills";

const exec = (over: Record<string, unknown> = {}) =>
  ({ quantity: -1, underlying: "NVDA", sec_type: "OPT", right: "P", strike: 165, expiry: "2026-11-20", ...over }) as never;

describe("executionTitle", () => {
  it("says sold or bought by the sign of the quantity, with the contract", () => {
    expect(executionTitle(exec())).toBe("Sold 1 NVDA $165 put · Nov 20");
    expect(executionTitle(exec({ quantity: 2, right: "C", strike: 72.5 }))).toBe("Bought 2 NVDA $72.5 call · Nov 20");
  });
  it("names shares as shares", () => {
    expect(executionTitle(exec({ sec_type: "STK", right: null, strike: null, expiry: null, quantity: 100 }))).toBe(
      "Bought 100 NVDA shares",
    );
  });
  it("says what it does not know about an option", () => {
    expect(executionTitle(exec({ strike: null, expiry: null }))).toBe("Sold 1 NVDA strike n/a put");
  });
});

describe("words", () => {
  it("names the books and the sources in words", () => {
    expect(bookWord("system")).toBe("System");
    expect(bookWord("spreads")).toBe("Spreads");
    expect(bookWord("manual")).toBe("Manual");
    expect(bookWord("other")).toBe("other");
    expect(sourceWord("live")).toBe("live feed");
    expect(sourceWord("flex")).toBe("Flex query");
    expect(sourceWord("csv")).toBe("statement import");
    expect(sourceWord("odd")).toBe("odd");
  });
  it("labels the windows as chips and as sentences", () => {
    expect(windowLabel(7)).toBe("7 days");
    expect(windowLabel(365)).toBe("A year");
    expect(lastWindow(30)).toBe("the last 30 days");
    expect(lastWindow(365)).toBe("the last year");
  });
  it("titles a spread order by its strikes, or says the strikes are unknown", () => {
    const o = { short_strike: 763, long_strike: 758, side: "put" } as never;
    expect(spreadOrderTitle(o, "SPY")).toBe("SPY 763/758 put spread");
    expect(spreadOrderTitle({ short_strike: null, long_strike: null, side: null } as never, "SPY")).toBe(
      "SPY credit spread, strikes n/a",
    );
  });
});
```

Create `web/components/options/FillsTable.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { FillsTable } from "./FillsTable";

const fill = (over: Record<string, unknown> = {}) => ({
  as_of: "", id: 1, order_id: 2, candidate_id: "c2", action: "SELL", filled_qty: 1, avg_price: 3.1,
  commission: 1.3, is_live: false, filled_at: "2026-10-22T18:31:00Z", underlying: "AAPL",
  strategy: "cash_secured_put", right: "P", strike: 185, expiry: "2026-11-20", ...over,
});
const serve = (fills: unknown[], days?: number) =>
  renderWithQuery(<FillsTable days={days} />, { "/options/fills": { as_of: "", fills } });

describe("FillsTable", () => {
  it("names the contract, the action, the price and when, in New York time", async () => {
    serve([fill()]);
    expect(await screen.findByText("AAPL $185 put")).toBeInTheDocument();
    expect(screen.getByText("SELL 1")).toBeInTheDocument();
    expect(screen.getByText("$3.10")).toBeInTheDocument();
    expect(screen.getByText(/Thu, Oct 22 · 2:31 PM ET/)).toBeInTheDocument();
    expect(screen.getByText(/paper/)).toBeInTheDocument();
  });

  it("says the commission is unknown rather than $0", async () => {
    serve([fill({ commission: null })]);
    await screen.findByText("AAPL $185 put");
    expect(screen.getByText("commission").parentElement).toHaveTextContent("commission n/a");
    expect(screen.queryByText("$0.00")).toBeNull();
  });

  it("says the contract is not on record, with the candidate id, when the order and candidate are gone", async () => {
    serve([fill({ underlying: null, strategy: null, right: null, strike: null, expiry: null, candidate_id: "ghost" })]);
    expect(await screen.findByText("Contract not on record")).toBeInTheDocument();
    expect(screen.getByText("ghost")).toBeInTheDocument();
  });

  it("asks for the window, and keeps the old seven days by default", async () => {
    serve([fill()]);
    await screen.findByText("AAPL $185 put");
    expect(apiFetchMock.mock.calls.map((c) => c[0])).toContain("/options/fills?days=7&limit=500");
  });

  it("says there are none in the window, in words", async () => {
    serve([], 30);
    expect(await screen.findByText("No fills in the last 30 days.")).toBeInTheDocument();
  });

  it("says the list was cut at 500", async () => {
    serve(Array.from({ length: 500 }, (_, i) => fill({ id: i + 1 })));
    expect(await screen.findByText("Showing the latest 500 fills. Choose a shorter window to see every fill in it.")).toBeInTheDocument();
  });

  it("says it could not load", async () => {
    renderWithQuery(<FillsTable />, {});
    expect(await screen.findByText("Could not load fills")).toBeInTheDocument();
  });
});
```

  Append inside `describe("OrdersTable", ...)` in `OrdersTable.test.tsx` (it uses the module's
  `withClient` and `vi.mock("@/lib/api")` helpers):

```tsx
  const order = (over: Record<string, unknown> = {}) => ({
    as_of: "x", id: 1, candidate_id: "c1", approval_id: null, underlying: "NVDA", strategy: "cash_secured_put",
    strike: 190.0, expiry: null, state: "filled", limit_price: 3.25, filled_qty: 1, avg_fill_price: 3.2,
    is_live: false, detail: null, created_at: "2026-10-22T18:31:00Z", updated_at: "x", sizing: [], ...over,
  });
  const serveOrders = async (orders: unknown[]) => {
    const { apiFetch } = await import("@/lib/api");
    (apiFetch as any).mockImplementation(async () => ({ as_of: "x", orders }));
    return apiFetch as any;
  };

  it("says what shaped an order's size, in words, and labels Claude's reason as Claude's", async () => {
    await serveOrders([order({ sizing: [{ kind: "claude_cut", deterministic_contracts: 3, sent_contracts: 1, reason: "Claude suggested 1" }] })]);
    withClient(<OrdersTable />);
    fireEvent.click(await screen.findByRole("button", { name: "All" }));
    expect(await screen.findByText("Claude's cut")).toBeInTheDocument();
    expect(screen.getByText("Sent 1 of 3 contracts.")).toBeInTheDocument();
    expect(screen.getByText(/Claude's reason:/)).toHaveTextContent("Claude's reason: Claude suggested 1");
  });

  it("words a rule's reason codes and does not call them Claude's", async () => {
    await serveOrders([order({ sizing: [{ kind: "regime_budget", deterministic_contracts: 2, sent_contracts: 1, reason: "trimmed (regime_budget)" }] })]);
    withClient(<OrdersTable />);
    fireEvent.click(await screen.findByRole("button", { name: "All" }));
    expect(await screen.findByText(/Rule:/)).toHaveTextContent("the market regime has shrunk the put budget");
    expect(screen.queryByText(/Claude's reason/)).toBeNull();
  });

  it("asks for the window on All and Rejected, never on Working", async () => {
    const api = await serveOrders([]);
    withClient(<OrdersTable days={90} />);
    await screen.findByText(/No working orders/i);
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    await screen.findByText(/No orders\./i);
    const paths = api.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(paths).toContain("/options/orders?state=working&limit=200");
    expect(paths).toContain("/options/orders?state=all&days=90&limit=200");
  });

  it("says a working order is cancelled in IBKR for now", async () => {
    await serveOrders([]);
    withClient(<OrdersTable />);
    expect(await screen.findByText("A working order is cancelled in IBKR for now. The web cannot cancel one yet.")).toBeInTheDocument();
  });

  it("makes a partial fill the one flag word, and says when the list was cut at 200", async () => {
    await serveOrders(Array.from({ length: 200 }, (_, i) => order({ id: i + 1, candidate_id: `c${i}`, state: i === 0 ? "partial" : "filled" })));
    withClient(<OrdersTable />);
    fireEvent.click(await screen.findByRole("button", { name: "All" }));
    expect(await screen.findByText("Partial")).toHaveAttribute("data-tone", "flag");
    expect(screen.getByText("Showing the latest 200 orders. Choose a shorter window to see every order in it.")).toBeInTheDocument();
  });
```

Create `web/features/activity/ExecutionsList.test.tsx`:

```tsx
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { ExecutionsList } from "./ExecutionsList";

const exec = (over: Record<string, unknown> = {}) => ({
  id: 1, source: "live", exec_id: "0000e1", trade_time: "2026-10-22T18:31:07Z", trade_date: "2026-10-22",
  underlying: "NVDA", sec_type: "OPT", right: "P", strike: 165, expiry: "2026-11-20", multiplier: 100,
  currency: "USD", quantity: -1, price: 2.35, proceeds: 235, commission: -1.3, codes: "O", book: "system",
  ib_order_id: 11, perm_id: 900, ...over,
});
const body = (executions: unknown[], over: Record<string, unknown> = {}) => ({
  as_of: "", days: 30, limit: 200, truncated: false, executions, ...over,
});
const serve = (b: unknown, days = 30) => renderWithQuery(<ExecutionsList days={days} />, { "/ledger/executions": b });

describe("ExecutionsList", () => {
  it("lists IBKR's executions with the contract, the book, the source, the price and the commission", async () => {
    serve(body([exec(), exec({ id: 2, quantity: 100, sec_type: "STK", right: null, strike: null, expiry: null, underlying: "AMZN", price: 205.5, book: "manual", source: "flex", commission: 0, exec_id: "x2" })]));
    // "System" and "Manual" are also book chips above the list, so each word is read inside its row.
    const [first, second] = await screen.findAllByRole("listitem");
    expect(within(first).getByText("Sold 1 NVDA $165 put · Nov 20")).toBeInTheDocument();
    expect(within(first).getByText("System")).toBeInTheDocument();
    expect(within(first).getByText(/Thu, Oct 22 · 2:31 PM ET · live feed/)).toBeInTheDocument();
    expect(within(first).getByText("$2.35")).toBeInTheDocument();
    expect(within(first).getByText(/commission \$1\.30/)).toBeInTheDocument();
    expect(within(second).getByText("Bought 100 AMZN shares")).toBeInTheDocument();
    expect(within(second).getByText("Manual")).toBeInTheDocument();
    expect(within(second).getByText(/Flex query/)).toBeInTheDocument();
  });

  it("says no commission was recorded rather than $0", async () => {
    serve(body([exec({ commission: 0 })]));
    expect(await screen.findByText(/commission none recorded/)).toBeInTheDocument();
    expect(screen.queryByText(/commission \$0/)).toBeNull();
  });

  it("asks the API for the window and the chosen book", async () => {
    serve(body([exec()]), 90);
    await screen.findAllByRole("listitem");
    fireEvent.click(screen.getByRole("button", { name: "Spreads" }));
    const calls = () => apiFetchMock.mock.calls.map((c) => String(c[0]));
    await waitFor(() => expect(calls()).toContain("/ledger/executions?days=90&limit=200&book=spreads"));
    expect(calls()).toContain("/ledger/executions?days=90&limit=200");
  });

  it("says the list was cut short", async () => {
    serve(body([exec()], { truncated: true }));
    expect(await screen.findByText("Showing the latest 200. Choose a shorter window to see every execution in it.")).toBeInTheDocument();
  });

  it("says where executions come from when there are none", async () => {
    serve(body([]));
    expect(
      await screen.findByText(
        "No executions at IBKR in the last 30 days. They arrive through the live feed, the Flex query or a statement import.",
      ),
    ).toBeInTheDocument();
  });

  it("says it could not load", async () => {
    renderWithQuery(<ExecutionsList days={30} />, {});
    expect(await screen.findByText("Could not load IBKR's executions.")).toBeInTheDocument();
  });
});
```

Create `web/features/activity/SpreadFills.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { SpreadFills } from "./SpreadFills";

const order = (over: Record<string, unknown> = {}) => ({
  spread_id: "s1", kind: "close", ib_order_id: 11, perm_id: 4001, filled_qty: 2, price: 0.05,
  commission: 2.6, reason: "profit_take", created_at: "2026-10-15T14:33:50Z", mode: "paper", side: "put",
  expiry: "2026-10-15", short_strike: 763, long_strike: 758, ...over,
});
const body = (orders: unknown[], over: Record<string, unknown> = {}) => ({
  as_of: "", available: true, underlying: "SPY", orders, ...over,
});
const serve = (b: unknown) => renderWithQuery(<SpreadFills days={30} />, { "/spreads/orders": b });

describe("SpreadFills", () => {
  it("lists the book's filled orders with the spread, what was done, the reason and the price", async () => {
    serve(body([order()]));
    expect(await screen.findByText("SPY 763/758 put spread")).toBeInTheDocument();
    expect(screen.getByText("Closed")).toBeInTheDocument();
    expect(screen.getByText("paper")).toBeInTheDocument();
    expect(screen.getByText("Reason: profit take")).toBeInTheDocument();
    expect(screen.getByText("$0.05")).toBeInTheDocument();
    expect(screen.getByText(/2 contracts/)).toBeInTheDocument();
  });

  it("says a price it does not have is n/a, and a spread it cannot identify", async () => {
    serve(body([order({ price: null, short_strike: null, long_strike: null, side: null, mode: null })]));
    expect(await screen.findByText("SPY credit spread, strikes n/a")).toBeInTheDocument();
    expect(screen.getByText("n/a")).toHaveClass("hatch");
  });

  it("says the book is unavailable, not empty, when the file cannot be read", async () => {
    serve(body([], { available: false }));
    expect(await screen.findByText("Credit spread fills are unavailable right now.")).toBeInTheDocument();
    expect(screen.queryByText(/No credit spread orders/)).toBeNull();
  });

  it("says unavailable when the request fails", async () => {
    renderWithQuery(<SpreadFills days={30} />, {});
    expect(await screen.findByText("Credit spread fills are unavailable right now.")).toBeInTheDocument();
  });

  it("says there are none in the window when the book is readable and empty", async () => {
    serve(body([]));
    expect(await screen.findByText("No credit spread orders in the last 30 days.")).toBeInTheDocument();
  });
});
```

Create `web/features/activity/FillsView.test.tsx`:

```tsx
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { FillsView } from "./FillsView";

const world = (over: Record<string, unknown> = {}) => ({
  "/options/orders": { as_of: "", orders: [] },
  "/options/fills": { as_of: "", fills: [] },
  "/spreads/orders": { as_of: "", available: true, underlying: "SPY", orders: [] },
  "/ledger/executions": {
    as_of: "", days: 30, limit: 200, truncated: false,
    executions: [{
      id: 1, source: "live", exec_id: "e1", trade_time: "2026-10-22T18:31:07Z", trade_date: "2026-10-22",
      underlying: "NVDA", sec_type: "OPT", right: "P", strike: 165, expiry: "2026-11-20", multiplier: 100,
      currency: "USD", quantity: -1, price: 2.35, proceeds: 235, commission: -1.3, codes: "O", book: "system",
      ib_order_id: 11, perm_id: 900,
    }],
  },
  ...over,
});
const calls = () => apiFetchMock.mock.calls.map((c) => String(c[0]));

describe("FillsView", () => {
  it("opens on the system's orders and says whose record it is", async () => {
    renderWithQuery(<FillsView />, world());
    expect(await screen.findByText(/The system's record: the wheel orders it sent to IBKR/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Orders" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText(/No working orders/i)).toBeInTheDocument();
  });

  it("shows the system's fills and the credit-spread fills under their own headings", async () => {
    renderWithQuery(<FillsView />, world());
    fireEvent.click(await screen.findByRole("button", { name: "Fills" }));
    expect(await screen.findByRole("heading", { name: "Wheel" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Credit spreads" })).toBeInTheDocument();
    expect(await screen.findByText("No fills in the last 30 days.")).toBeInTheDocument();
    expect(await screen.findByText("No credit spread orders in the last 30 days.")).toBeInTheDocument();
  });

  it("keeps IBKR's executions apart, with their own source line, and does not reconcile them", async () => {
    renderWithQuery(<FillsView />, world());
    fireEvent.click(await screen.findByRole("button", { name: "At IBKR" }));
    expect(await screen.findByText("Sold 1 NVDA $165 put · Nov 20")).toBeInTheDocument();
    expect(screen.getByText(/IBKR's record: every execution the ledger holds/)).toBeInTheDocument();
    expect(screen.getByText(/if they disagree, the disagreement is the finding/)).toBeInTheDocument();
    // The system's own fills list is empty in this world, and this view does not pretend otherwise.
    expect(screen.queryByText("No fills in the last 30 days.")).toBeNull();
  });

  it("passes the chosen window to every list", async () => {
    renderWithQuery(<FillsView />, world());
    fireEvent.click(await screen.findByRole("button", { name: "90 days" }));
    fireEvent.click(await screen.findByRole("button", { name: "Fills" }));
    await screen.findByText("No fills in the last 90 days.");
    fireEvent.click(screen.getByRole("button", { name: "At IBKR" }));
    await screen.findByText("Sold 1 NVDA $165 put · Nov 20");
    const seen = calls();
    expect(seen).toContain("/options/fills?days=90&limit=500");
    expect(seen).toContain("/spreads/orders?days=90&limit=200");
    expect(seen).toContain("/ledger/executions?days=90&limit=200");
  });

  it("defaults the window to 30 days", async () => {
    renderWithQuery(<FillsView />, world());
    expect(await screen.findByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
  });
});
```

- [x] **Step 3: Run them to verify they fail**

Run: `cd web && npx vitest run features/trades/time.test.ts features/activity components/options/OrdersTable.test.tsx components/options/FillsTable.test.tsx`
Expected: FAIL (modules and `whenET` missing; the 5 new `OrdersTable` cases fail on the old table).

- [x] **Step 4: Implement `whenET`** — append to `web/features/trades/time.ts`:

```ts
/** "Thu, Oct 22 · 2:31 PM ET": an instant as a New York day and time; "time n/a" when it cannot be read. */
export function whenET(iso: string): string {
  const day = newYorkDay(iso);
  return day === null ? "time n/a" : `${dayLabel(day)} · ${timeET(iso)}`;
}
```

- [x] **Step 5: Implement `web/features/activity/types.ts` and `fills.ts`**

`types.ts`:

```ts
import type { components } from "@/lib/api-types";

type S = components["schemas"];

/** Aliases of the generated contract (docs/web/openapi.json), never hand-copied. */
export type SizingGroup = S["SizingGroupOut"];
export type SizingRecordResponse = S["SizingRecordResponse"];
export type LedgerExecution = S["LedgerExecutionRowOut"];
export type LedgerExecutionsResponse = S["LedgerExecutionsResponse"];
export type SpreadOrder = S["SpreadOrderOut"];
export type SpreadOrdersResponse = S["SpreadOrdersResponse"];
```

`fills.ts`:

```ts
import { shortDay } from "@/features/claude-context/format";
import { usd } from "@/features/portfolio/format";
import type { LedgerExecution, SpreadOrder } from "./types";

/** The look-back windows the lists share (days). */
export const WINDOWS = [7, 30, 90, 365] as const;
export const DEFAULT_WINDOW = 30;

/** A window chip: "7 days", "A year". */
export const windowLabel = (days: number): string => (days === 365 ? "A year" : `${days} days`);

/** A window in a sentence: "the last 30 days", "the last year". */
export const lastWindow = (days: number): string => (days === 365 ? "the last year" : `the last ${days} days`);

/** "Sold 1 NVDA $165 put · Nov 20", from the sign of the quantity; shares are "Bought 100 AMZN shares". */
export function executionTitle(
  e: Pick<LedgerExecution, "quantity" | "underlying" | "sec_type" | "right" | "strike" | "expiry">,
): string {
  const side = e.quantity < 0 ? "Sold" : "Bought";
  const n = Math.abs(e.quantity);
  if (e.sec_type !== "OPT") return `${side} ${n} ${e.underlying} shares`;
  const strike = typeof e.strike === "number" ? usd(e.strike) : "strike n/a";
  const base = `${side} ${n} ${e.underlying} ${strike} ${e.right === "C" ? "call" : "put"}`;
  return e.expiry ? `${base} · ${shortDay(e.expiry)}` : base;
}

const BOOK: Record<string, string> = { system: "System", spreads: "Spreads", manual: "Manual" };
const SOURCE: Record<string, string> = { live: "live feed", flex: "Flex query", csv: "statement import" };

export const bookWord = (book: string): string => BOOK[book] ?? book;
export const sourceWord = (source: string): string => SOURCE[source] ?? source;

/** "SPY 763/758 put spread", or a sentence saying the strikes are not known. */
export function spreadOrderTitle(
  o: Pick<SpreadOrder, "short_strike" | "long_strike" | "side">,
  underlying: string,
): string {
  if (o.short_strike == null || o.long_strike == null || !o.side) return `${underlying} credit spread, strikes n/a`;
  return `${underlying} ${o.short_strike}/${o.long_strike} ${o.side} spread`;
}
```

- [x] **Step 6: Restyle `OrdersTable`** — replace `web/components/options/OrdersTable.tsx` with:

```tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { kindWord, reasonWords, sentSentence } from "@/features/market/market";
import { whenET } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { EmptyState } from "./EmptyState";
import type { OrderListResponse, OrderSizing, OrderSummary } from "./types";

type Filter = "working" | "all" | "rejected";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "working", label: "Working" },
  { value: "all", label: "All" },
  { value: "rejected", label: "Rejected" },
];

const EMPTY_TEXT: Record<Filter, string> = {
  working: "No working orders.",
  all: "No orders.",
  rejected: "No rejected orders.",
};

const STATE_LABEL: Record<string, string> = {
  queued: "Queued",
  submitted: "Submitted",
  filled: "Filled",
  partial: "Partial",
  cancelled: "Cancelled",
  rejected: "Rejected",
};

const STRATEGY: Record<string, string> = {
  cash_secured_put: "cash-secured put",
  covered_call: "covered call",
  roll: "roll",
};

const CAP = 200;
const isClaude = (kind: string) => kind === "claude_cut" || kind === "claude_cut_unapplied";
const price = (v: number | null) =>
  v === null ? <span className="hatch text-unknown">{UNKNOWN}</span> : `$${v.toFixed(2)}`;

/** What shaped an order's size, in words. Claude's cut is the flag tone and its reason is labelled
 *  as Claude's; a rule's reason has its codes spelled out. */
function Sizing({ a }: { a: OrderSizing }) {
  const claude = isClaude(a.kind);
  return (
    <div className="mt-1 text-[0.8125rem]">
      <StatusWord tone={claude ? "flag" : "neutral"}>{kindWord(a.kind)}</StatusWord> <span>{sentSentence(a)}</span>
      {a.reason && (
        <p className="text-muted">
          {claude ? "Claude's reason: " : "Rule: "}
          {claude ? a.reason : reasonWords(a.reason)}
        </p>
      )}
    </div>
  );
}

function Row({ o }: { o: OrderSummary }) {
  const strike = `$${o.strike.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  return (
    <li className="border-t border-border py-[11px] first:border-t-0">
      <div className="text-sm">
        <span className="font-bold">{o.underlying}</span>{" "}
        <span className="font-bold">
          {strike} {STRATEGY[o.strategy] ?? o.strategy.replace(/_/g, " ")}
        </span>
        <span className="ml-1.5 align-[1px]">
          <StatusWord tone={o.state === "partial" ? "flag" : "neutral"}>{STATE_LABEL[o.state] ?? o.state}</StatusWord>
        </span>
        <div className="text-[0.8125rem] text-muted">
          {whenET(o.created_at)} · {o.is_live ? "live" : "paper"}
        </div>
        <div className="tabular font-mono text-xs text-muted">
          limit {price(o.limit_price)} · filled {o.filled_qty.toFixed(0)} · avg fill {price(o.avg_fill_price)}
        </div>
        {o.detail && <p className="mt-0.5 text-[0.8125rem] text-muted">{o.detail}</p>}
        {(o.sizing ?? []).map((a, i) => (
          <Sizing key={i} a={a} />
        ))}
      </div>
    </li>
  );
}

/**
 * The system's own orders for the wheel. A window (`days`) narrows All and Rejected; Working is
 * never windowed, so an order stuck for weeks cannot be hidden by it. Credit spreads record filled
 * orders only, so they appear under Fills.
 */
export function OrdersTable({ days }: { days?: number } = {}) {
  const [filter, setFilter] = useState<Filter>("working");
  const windowDays = filter === "working" ? undefined : days;
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "orders", filter, windowDays ?? null],
    queryFn: () =>
      apiFetch<OrderListResponse>(
        `/options/orders?state=${filter}${windowDays ? `&days=${windowDays}` : ""}&limit=${CAP}`,
      ),
    placeholderData: (prev) => prev,
  });
  const orders = data?.orders ?? [];

  return (
    <div className="grid gap-3">
      <SegmentedControl label="Filter orders" appearance="chips" options={FILTERS} value={filter} onChange={setFilter} />
      {isLoading ? (
        <p className="text-sm text-muted">Loading orders</p>
      ) : isError ? (
        <p className="text-sm text-muted">Could not load orders</p>
      ) : orders.length === 0 ? (
        <EmptyState text={EMPTY_TEXT[filter]} />
      ) : (
        <ul>
          {orders.map((o) => (
            <Row key={o.id} o={o} />
          ))}
        </ul>
      )}
      {orders.length >= CAP && (
        <p className="text-[0.8125rem] text-muted">
          Showing the latest {CAP} orders. Choose a shorter window to see every order in it.
        </p>
      )}
      {filter === "working" && (
        <p className="text-[0.8125rem] text-muted">
          A working order is cancelled in IBKR for now. The web cannot cancel one yet.
        </p>
      )}
    </div>
  );
}
```

  Check against the existing tests: "Working" is the default and its path includes `state=working`;
  `findByText("TSLA")` finds the ticker alone in its span; the rejected detail is rendered as
  written (never a raw code list); no button is named "roll".

- [x] **Step 7: Restyle `FillsTable`** — replace `web/components/options/FillsTable.tsx` with:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { StatusWord } from "@/components/ui/StatusWord";
import { whenET } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { EmptyState } from "./EmptyState";
import type { FillListResponse, FillSummary } from "./types";

const CAP = 500;
const usd = (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
const lastWindow = (days: number) => (days === 365 ? "the last year" : `the last ${days} days`);

function title(f: FillSummary): string {
  if (!f.underlying) return "Contract not on record";
  const strike = typeof f.strike === "number" ? usd(f.strike) : "strike n/a";
  return `${f.underlying} ${strike} ${f.right === "C" ? "call" : "put"}`;
}

/**
 * The system's own fills: what it recorded as filled, with the contract named from the order's
 * frozen snapshot or its candidate. A fill whose order and candidate are both gone says so and
 * keeps its candidate id; a missing commission is n/a, never $0.
 */
export function FillsTable({ days = 7 }: { days?: number } = {}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "fills", days],
    queryFn: () => apiFetch<FillListResponse>(`/options/fills?days=${days}&limit=${CAP}`),
    placeholderData: (prev) => prev,
  });

  if (isLoading) return <p className="text-sm text-muted">Loading fills</p>;
  if (isError) return <p className="text-sm text-muted">Could not load fills</p>;
  const fills = data?.fills ?? [];
  if (fills.length === 0) {
    return <EmptyState text={`No fills in ${lastWindow(days)}.`} />;
  }
  return (
    <div className="grid gap-2">
      <ul>
        {fills.map((f) => (
          <li key={f.id} className="border-t border-border py-[11px] first:border-t-0">
            <div className="flex items-start justify-between gap-3 text-sm">
              <div className="min-w-0">
                <span className="font-bold">{title(f)}</span>
                {!f.underlying && <span className="ml-1.5 font-mono text-xs text-muted">{f.candidate_id}</span>}
                <span className="ml-1.5 align-[1px]">
                  <StatusWord>{f.is_live ? "live" : "paper"}</StatusWord>
                </span>
                <div className="text-[0.8125rem] text-muted">{whenET(f.filled_at)}</div>
                <div className="tabular font-mono text-xs text-muted">
                  <span>commission</span>{" "}
                  {f.commission === null || f.commission === undefined ? (
                    <span className="hatch text-unknown">{UNKNOWN}</span>
                  ) : (
                    `$${Math.abs(f.commission).toFixed(2)}`
                  )}
                </div>
              </div>
              <div className="tabular text-right font-mono font-semibold">
                <span>
                  {f.action} {f.filled_qty.toFixed(0)}
                </span>
                <div>{`$${f.avg_price.toFixed(2)}`}</div>
                <div className="font-sans text-[0.8125rem] font-normal text-muted">a share</div>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {fills.length >= CAP && (
        <p className="text-[0.8125rem] text-muted">
          Showing the latest {CAP} fills. Choose a shorter window to see every fill in it.
        </p>
      )}
    </div>
  );
}
```

  `FillsTable` is in `components/options`, which must not import `features/activity`, so it keeps
  its own one-line `lastWindow` rather than the one in `fills.ts`.

- [x] **Step 8: Implement `web/features/activity/ExecutionsList.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { whenET } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { bookWord, executionTitle, lastWindow, sourceWord } from "./fills";
import type { LedgerExecutionsResponse } from "./types";

type BookFilter = "all" | "system" | "spreads" | "manual";
const BOOKS: { value: BookFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "system", label: "System" },
  { value: "spreads", label: "Spreads" },
  { value: "manual", label: "Manual" },
];
const LIMIT = 200;

/**
 * IBKR's own executions, newest first, from the ledger: every book, whether or not the system
 * placed the order. A commission of 0 is said as "none recorded" (the feed cannot tell a free
 * execution, such as an assignment, from one whose commission has not arrived), never as $0.
 */
export function ExecutionsList({ days }: { days: number }) {
  const [book, setBook] = useState<BookFilter>("all");
  const { data, isError } = useQuery({
    queryKey: ["ledger", "executions", days, book],
    queryFn: () =>
      apiFetch<LedgerExecutionsResponse>(
        `/ledger/executions?days=${days}&limit=${LIMIT}${book === "all" ? "" : `&book=${book}`}`,
      ),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });

  return (
    <div className="grid gap-3">
      <SegmentedControl label="Book" appearance="chips" options={BOOKS} value={book} onChange={setBook} />
      {isError && !data ? (
        <p className="text-sm text-muted">Could not load IBKR&apos;s executions.</p>
      ) : !data ? (
        <div role="status" aria-busy="true" aria-label="Loading IBKR's executions" className="h-24 rounded-xl bg-sunk" />
      ) : data.executions.length === 0 ? (
        <p className="text-sm text-muted">
          No executions at IBKR in {lastWindow(days)}. They arrive through the live feed, the Flex query or a
          statement import.
        </p>
      ) : (
        <ul>
          {data.executions.map((e) => (
            <li key={e.id} className="border-t border-border py-[11px] first:border-t-0">
              <div className="flex items-start justify-between gap-3 text-sm">
                <div className="min-w-0">
                  <span className="font-bold">{executionTitle(e)}</span>
                  <span className="ml-1.5 align-[1px]">
                    <StatusWord>{bookWord(e.book)}</StatusWord>
                  </span>
                  <div className="text-[0.8125rem] text-muted">
                    {whenET(e.trade_time)} · {sourceWord(e.source)}
                  </div>
                  <div className="tabular font-mono text-xs text-muted">
                    commission {e.commission === 0 ? "none recorded" : `$${Math.abs(e.commission).toFixed(2)}`}
                    {e.codes ? ` · codes ${e.codes}` : ""}
                    {e.exec_id ? ` · ${e.exec_id}` : ""}
                  </div>
                </div>
                <div className="tabular text-right font-mono font-semibold">
                  {`$${e.price.toFixed(2)}`}
                  <div className="font-sans text-[0.8125rem] font-normal text-muted">a share</div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {data?.truncated && (
        <p className="text-[0.8125rem] text-muted">
          Showing the latest {data.limit}. Choose a shorter window to see every execution in it.
        </p>
      )}
    </div>
  );
}
```

  The empty sentence is built from JSX text pieces; the test reads it as one string, which
  `getByText` matches because it joins the adjacent text nodes of one element.

- [x] **Step 9: Implement `web/features/activity/SpreadFills.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { StatusWord } from "@/components/ui/StatusWord";
import { whenET } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { lastWindow, spreadOrderTitle } from "./fills";
import type { SpreadOrdersResponse } from "./types";

/**
 * The credit-spreads book's filled orders (the book records filled orders only). An unreadable
 * file is "unavailable", never "none": unknown is not empty.
 */
export function SpreadFills({ days }: { days: number }) {
  const { data, isError } = useQuery({
    queryKey: ["spreads", "orders", days],
    queryFn: () => apiFetch<SpreadOrdersResponse>(`/spreads/orders?days=${days}&limit=200`),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });

  if (isError && !data) return <p className="text-sm text-muted">Credit spread fills are unavailable right now.</p>;
  if (!data) {
    return <div role="status" aria-busy="true" aria-label="Loading credit spread fills" className="h-16 rounded-xl bg-sunk" />;
  }
  if (!data.available) return <p className="text-sm text-muted">Credit spread fills are unavailable right now.</p>;
  // The generated type makes a defaulted list optional.
  const orders = data.orders ?? [];
  if (orders.length === 0) {
    return <p className="text-sm text-muted">No credit spread orders in {lastWindow(days)}.</p>;
  }
  return (
    <ul>
      {orders.map((o, i) => (
        <li key={`${o.spread_id}:${o.kind}:${i}`} className="border-t border-border py-[11px] first:border-t-0">
          <div className="flex items-start justify-between gap-3 text-sm">
            <div className="min-w-0">
              <span className="font-bold">{spreadOrderTitle(o, data.underlying)}</span>
              <span className="ml-1.5 align-[1px]">
                <StatusWord>{o.kind === "open" ? "Opened" : "Closed"}</StatusWord>
              </span>
              {o.mode && (
                <span className="ml-1.5 align-[1px]">
                  <StatusWord>{o.mode}</StatusWord>
                </span>
              )}
              <div className="text-[0.8125rem] text-muted">{whenET(o.created_at)}</div>
              <div className="tabular font-mono text-xs text-muted">
                {o.filled_qty} {o.filled_qty === 1 ? "contract" : "contracts"} · commission ${o.commission.toFixed(2)}
              </div>
              {o.reason && <p className="text-[0.8125rem] text-muted">Reason: {o.reason.replace(/_/g, " ")}</p>}
            </div>
            <div className="tabular text-right font-mono font-semibold">
              {o.price === null ? <span className="hatch text-unknown">{UNKNOWN}</span> : `$${o.price.toFixed(2)}`}
              <div className="font-sans text-[0.8125rem] font-normal text-muted">a share</div>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
```

- [x] **Step 10: Implement `web/features/activity/FillsView.tsx`**

```tsx
"use client";

import { useState } from "react";
import { FillsTable } from "@/components/options/FillsTable";
import { OrdersTable } from "@/components/options/OrdersTable";
import { Card } from "@/components/ui/Card";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { ExecutionsList } from "./ExecutionsList";
import { DEFAULT_WINDOW, WINDOWS, windowLabel } from "./fills";
import { SpreadFills } from "./SpreadFills";

type List = "orders" | "fills" | "ibkr";
const LISTS: { value: List; label: string }[] = [
  { value: "orders", label: "Orders" },
  { value: "fills", label: "Fills" },
  { value: "ibkr", label: "At IBKR" },
];

const SOURCE = "mt-1 text-[0.8125rem] text-muted";

/**
 * Three lists, each headed by whose record it is, and never merged: the system's orders, the
 * system's fills (the wheel, then the credit-spread book), and IBKR's own executions from the
 * ledger. Where they disagree is the finding, so the page does not paper over it. One window
 * (7 days to a year) applies to all of them.
 */
export function FillsView() {
  const [list, setList] = useState<List>("orders");
  const [days, setDays] = useState<number>(DEFAULT_WINDOW);
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <SegmentedControl label="List" appearance="chips" options={LISTS} value={list} onChange={setList} />
        <SegmentedControl
          label="Window"
          appearance="chips"
          options={WINDOWS.map((w) => ({ value: String(w), label: windowLabel(w) }))}
          value={String(days)}
          onChange={(v) => setDays(Number(v))}
        />
      </div>
      {list === "orders" && (
        <Card aria-labelledby="orders-title">
          <h2 id="orders-title" className="text-[1.0625rem] font-bold">
            Orders
          </h2>
          <p className={SOURCE}>
            The system&apos;s record: the wheel orders it sent to IBKR, and how each ended. Credit spreads record filled
            orders only, so they are under Fills.
          </p>
          <div className="mt-3">
            <OrdersTable days={days} />
          </div>
        </Card>
      )}
      {list === "fills" && (
        <>
          <Card aria-labelledby="wheel-fills-title">
            <h2 id="wheel-fills-title" className="text-[1.0625rem] font-bold">
              Wheel
            </h2>
            <p className={SOURCE}>The system&apos;s record: what it saw filled. IBKR&apos;s own list is under At IBKR.</p>
            <div className="mt-3">
              <FillsTable days={days} />
            </div>
          </Card>
          <Card aria-labelledby="spread-fills-title">
            <h2 id="spread-fills-title" className="text-[1.0625rem] font-bold">
              Credit spreads
            </h2>
            <p className={SOURCE}>The system&apos;s record, from the credit-spreads book.</p>
            <div className="mt-3">
              <SpreadFills days={days} />
            </div>
          </Card>
        </>
      )}
      {list === "ibkr" && (
        <Card aria-labelledby="ibkr-title">
          <h2 id="ibkr-title" className="text-[1.0625rem] font-bold">
            Executions at IBKR
          </h2>
          <p className={SOURCE}>
            IBKR&apos;s record: every execution the ledger holds, from the live feed, the Flex query and statement
            imports, in any book. It is not reconciled with the system&apos;s lists here: if they disagree, the
            disagreement is the finding.
          </p>
          <div className="mt-3">
            <ExecutionsList days={days} />
          </div>
        </Card>
      )}
    </div>
  );
}
```

  The window chips read "7 days", "30 days", "90 days" and "A year" (`windowLabel`); the empty
  sentences read "the last 30 days" and "the last year" (`lastWindow`).

- [x] **Step 11: Run the tests, then the gate**

Run: `cd web && npx vitest run features components/options && npx tsc --noEmit && npm run lint`
Expected: PASS: the new tests (`time` 3, `fills` 6, `FillsTable` 7, `OrdersTable` 5,
`ExecutionsList` 6, `SpreadFills` 5, `FillsView` 5), and every existing `OrdersTable` test (the
empty Working state, the n/a for a null fill price, the state label, no roll button, the rejected
detail) **unmodified**.

- [x] **Step 12: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/activity web/components/options/OrdersTable.tsx web/components/options/FillsTable.tsx`
Expected: exit 0, or every finding fixed in the code.

- [x] **Step 13: Commit** (with the Progress log row for Task 12 filled in)

```bash
git add web/features/activity web/features/trades/time.ts web/features/trades/time.test.ts \
  web/components/options/OrdersTable.tsx web/components/options/OrdersTable.test.tsx \
  web/components/options/FillsTable.tsx web/components/options/FillsTable.test.tsx \
  docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): Activity Fills and orders - the system's orders and fills, IBKR's executions, apart"
```

---

### Task 13: System — the sizing record, then the score against outcome

**Files:**
- Create: `web/features/activity/sizing.ts`, `sizing.test.ts`, `SizingRecord.tsx`,
  `SizingRecord.test.tsx`, `SystemView.tsx`, `SystemView.test.tsx`
- Modify (restyle in place, whole files): `web/components/pnl/SystemPanel.tsx`,
  `web/components/pnl/ScoreBucketTable.tsx`, `web/components/pnl/CorrelationTable.tsx`
- Modify: `web/components/pnl/SystemPanel.test.tsx` (+2)

**Interfaces:**
- Consumes: `SizingGroup`/`SizingRecordResponse` (`features/activity/types.ts`), `kindWord`
  (`features/market/market.ts`), `cutSentence` (`features/claude-context/format.ts`),
  `useClaudeContext`, `formatStubValue`, `SystemPerformanceResponse` (`components/pnl/types.ts`),
  `FIELD`, `FIELD_LABEL`, `Card`.
- Produces: `groupTitle`, `groupSub`, `groupNote`, `marks`, `rulesNote` (`sizing.ts`);
  `SizingRecord({ since })`; `WindowControls({ since, until, onSinceChange, onUntilChange })` and
  `SystemPanel({ ..., windowControls? })` (`components/pnl/SystemPanel.tsx`); `SystemView()`
  (Task 14 mounts it).

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: a reference sheet: one idea per
  card, Python's figures in the stub face, words that say what a positive number means, nothing
  that can change a limit, a size or a weight, no lime.

- [x] **Step 2: Write the failing tests**

Create `web/features/activity/sizing.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { groupNote, groupSub, groupTitle, marks, rulesNote } from "./sizing";

const group = (over: Record<string, unknown> = {}) =>
  ({
    key: "scale_in_zone:never_sent", kind: "scale_in_zone", split: "never_sent", count: 2,
    contracts_withheld: 4, resolved: 1, exact: 0, pnl_expiry: 120, pnl_rules: 80, rules_missing: 0,
    applied: null, unapplied: null, ...over,
  }) as never;

describe("groupTitle", () => {
  it("names the kind and what became of the puts", () => {
    expect(groupTitle(group())).toBe("Scale-in ladder · never sent");
    expect(groupTitle(group({ kind: "regime_budget", split: "sent_smaller" }))).toBe("Regime budget · sent smaller");
    expect(groupTitle(group({ kind: "cc_breakout_floor", split: "pushed_out" }))).toBe("Breakout rule · pushed out");
  });
  it("puts Claude's cuts on one line", () => {
    expect(groupTitle(group({ kind: "claude_cut", split: "overrides" }))).toBe("Claude's size cut");
  });
});

describe("groupSub", () => {
  it("counts the actions, the valued ones and the contracts held back", () => {
    expect(groupSub(group())).toBe("2 actions · 1 valued so far · 4 contracts held back");
    expect(groupSub(group({ count: 1, resolved: 0, contracts_withheld: 1 }))).toBe(
      "1 action · 0 valued so far · 1 contract held back",
    );
  });
  it("says a pushed-out line is counted and not valued", () => {
    expect(groupSub(group({ split: "pushed_out", count: 3, resolved: null, contracts_withheld: null }))).toBe(
      "3 actions · counted, not valued",
    );
  });
});

describe("groupNote", () => {
  it("says how many cuts were applied and how many only recorded", () => {
    expect(groupNote(group({ split: "overrides", applied: 1, unapplied: 2 }))).toBe("1 applied, 2 recorded only.");
  });
  it("explains a pushed-out line", () => {
    expect(groupNote(group({ split: "pushed_out" }))).toBe(
      "A covered call was still sold on the name that day, so the breakout rule only pushed it out.",
    );
  });
  it("says how many valued rows were valued at the traded contracts' realised P&L", () => {
    expect(groupNote(group({ exact: 2, resolved: 3 }))).toBe(
      "2 of the valued rows are valued at the realised P&L of the contracts that did trade.",
    );
    expect(groupNote(group({ exact: 1, resolved: 1 }))).toBe(
      "1 of the valued rows is valued at the realised P&L of the contract that did trade.",
    );
  });
  it("says nothing when there is nothing to add", () => {
    expect(groupNote(group())).toBeNull();
  });
});

describe("marks", () => {
  it("gives both marks when rows are valued", () => {
    expect(marks(group())).toEqual({ expiry: 120, rules: 80 });
  });
  it("gives neither when nothing is valued yet, never zeros", () => {
    expect(marks(group({ resolved: 0, pnl_expiry: 0, pnl_rules: 0 }))).toEqual({ expiry: null, rules: null });
  });
  it("leaves the exit-rule mark out when no valued row has an entry IV", () => {
    expect(marks(group({ resolved: 2, rules_missing: 2 }))).toEqual({ expiry: 120, rules: null });
  });
  it("keeps the exit-rule mark when only some valued rows lack one", () => {
    expect(marks(group({ resolved: 3, rules_missing: 1 })).rules).toBe(80);
  });
  it("gives no marks to a pushed-out line", () => {
    expect(marks(group({ split: "pushed_out", resolved: null, pnl_expiry: null, pnl_rules: null }))).toEqual({
      expiry: null,
      rules: null,
    });
  });
});

describe("rulesNote", () => {
  it("says how many valued rows have no entry IV", () => {
    expect(rulesNote(group({ rules_missing: 2 }))).toBe("2 valued rows have no entry IV, so their exit-rule mark is left out.");
    expect(rulesNote(group({ rules_missing: 1 }))).toBe("1 valued row has no entry IV, so its exit-rule mark is left out.");
  });
  it("is null when none is missing", () => {
    expect(rulesNote(group())).toBeNull();
    expect(rulesNote(group({ rules_missing: null }))).toBeNull();
  });
});
```

Create `web/features/activity/SizingRecord.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { SizingRecord } from "./SizingRecord";

const group = (over: Record<string, unknown> = {}) => ({
  key: "scale_in_zone:never_sent", kind: "scale_in_zone", split: "never_sent", count: 2,
  contracts_withheld: 4, resolved: 1, exact: 0, pnl_expiry: 120, pnl_rules: 80, rules_missing: 0,
  applied: null, unapplied: null, ...over,
});
const body = (groups: unknown[], since: string | null = null) => ({ as_of: "", since, groups });
const context = { available: true, claude_cut_mode: "record_only", account_mode: "live", claude_cut_breaker_tripped_today: false };
const serve = (b: unknown, since?: string) =>
  renderWithQuery(<SizingRecord since={since} />, { "/pnl/sizing": b, "/claude/context": context });
const row = async (title: string) => (await screen.findByText(title)).closest("li") as HTMLElement;

describe("SizingRecord", () => {
  it("says there is nothing on record, with no zeros", async () => {
    serve(body([]));
    expect(await screen.findByText("No sizing actions on record yet.")).toBeInTheDocument();
    expect(screen.queryByText("$0")).toBeNull();
  });

  it("names the window in the empty sentence when there is one", async () => {
    serve(body([], "2026-10-15"), "2026-10-15");
    expect(await screen.findByText("No sizing actions on record since 2026-10-15.")).toBeInTheDocument();
  });

  it("lists a kind of action with its counts and its two marks, in the stub face", async () => {
    serve(body([group()]));
    const r = await row("Scale-in ladder · never sent");
    expect(within(r).getByText("2 actions · 1 valued so far · 4 contracts held back")).toBeInTheDocument();
    expect(within(r).getByText("+$120.00")).toBeInTheDocument();
    expect(within(r).getByText("to expiry")).toBeInTheDocument();
    expect(within(r).getByText("+$80.00")).toBeInTheDocument();
    expect(within(r).getByText("exit rules")).toBeInTheDocument();
  });

  it("explains what a positive number means, in words", async () => {
    serve(body([group()]));
    expect(
      await screen.findByText(/A positive number is what the held-back contracts would have earned: the action cost that much/),
    ).toBeInTheDocument();
    expect(screen.getByText(/A negative number is a loss it avoided/)).toBeInTheDocument();
  });

  it("writes a negative mark with a real minus", async () => {
    serve(body([group({ pnl_expiry: -30, pnl_rules: -12 })]));
    const r = await row("Scale-in ladder · never sent");
    expect(within(r).getByText("−$30.00")).toBeInTheDocument();
  });

  it("shows hatched n/a marks, not zeros, when nothing is valued yet", async () => {
    serve(body([group({ resolved: 0, pnl_expiry: 0, pnl_rules: 0, contracts_withheld: 2, count: 1 })]));
    const r = await row("Scale-in ladder · never sent");
    const na = within(r).getAllByText("n/a");
    expect(na).toHaveLength(2);
    na.forEach((el) => expect(el).toHaveClass("hatch"));
    expect(within(r).queryByText("$0.00")).toBeNull();
  });

  it("leaves the exit-rule mark out, and says why, when no valued row has an entry IV", async () => {
    serve(body([group({ resolved: 2, rules_missing: 2 })]));
    const r = await row("Scale-in ladder · never sent");
    expect(within(r).getByText("+$120.00")).toBeInTheDocument();
    expect(within(r).getAllByText("n/a")).toHaveLength(1);
    expect(within(r).getByText("2 valued rows have no entry IV, so their exit-rule mark is left out.")).toBeInTheDocument();
  });

  it("counts a pushed-out line and gives it no money", async () => {
    serve(
      body([
        group({
          key: "cc_breakout_floor:pushed_out", kind: "cc_breakout_floor", split: "pushed_out", count: 1,
          contracts_withheld: null, resolved: null, exact: null, pnl_expiry: null, pnl_rules: null, rules_missing: null,
        }),
      ]),
    );
    const r = await row("Breakout rule · pushed out");
    expect(within(r).getByText("1 action · counted, not valued")).toBeInTheDocument();
    expect(within(r).queryByText("to expiry")).toBeNull();
  });

  it("puts Claude's cuts on one line with the applied and recorded-only counts", async () => {
    serve(
      body([group({ key: "claude_overrides", kind: "claude_cut", split: "overrides", count: 2, applied: 1, unapplied: 1 })]),
    );
    const r = await row("Claude's size cut");
    expect(within(r).getByText("1 applied, 1 recorded only.")).toBeInTheDocument();
  });

  it("says whether Claude's cut is applied or only recorded, from the standing setting", async () => {
    serve(body([group()]));
    expect(await screen.findByText("Claude's size cuts: recorded only (live).")).toBeInTheDocument();
  });

  it("asks for the window it was given", async () => {
    serve(body([group()]), "2026-10-01");
    await screen.findByText("Scale-in ladder · never sent");
    expect(apiFetchMock.mock.calls.map((c) => c[0])).toContain("/pnl/sizing?since=2026-10-01");
  });

  it("says it could not load, and that it tries again", async () => {
    renderWithQuery(<SizingRecord />, { "/claude/context": context });
    expect(await screen.findByText("Could not load the sizing record.")).toBeInTheDocument();
    expect(screen.getByText("It tries again every minute.")).toBeInTheDocument();
  });
});
```

Create `web/features/activity/SystemView.test.tsx`:

```tsx
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { SystemView } from "./SystemView";

const READONLY_NOTE =
  "Read-only: re-derive scoring_weights.yaml from this evidence by hand (the fence forbids any automatic feedback into the engine).";
const system = {
  as_of: "", since: null, until: null,
  report: {
    n_closed: 12, period_start: null, period_end: null, blended_score_buckets: [], component_buckets: [],
    signal_correlations: [], notes: ["Closed (executed+settled) trades only.", READONLY_NOTE],
  },
  agreement: { n_closed: 12, n_agreed: 9, agreement_rate: 0.75, claude_win_rate: 0.7, baseline_win_rate: 0.55 },
};
const world = (over: Record<string, unknown> = {}) => ({
  "/pnl/system": system,
  "/pnl/sizing": { as_of: "", since: null, groups: [] },
  "/claude/context": { available: false },
  ...over,
});

describe("SystemView", () => {
  it("puts the sizing record above the score against outcome", async () => {
    renderWithQuery(<SystemView />, world());
    const sizing = await screen.findByRole("heading", { name: "Sizing record" });
    const score = await screen.findByRole("heading", { name: "Score against outcome" });
    expect(sizing.compareDocumentPosition(score) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps the read-only sentence and offers no control but the two dates", async () => {
    const { container } = renderWithQuery(<SystemView />, world());
    expect(await screen.findByText(READONLY_NOTE)).toBeInTheDocument();
    const controls = container.querySelectorAll("button, input, select, textarea");
    expect(controls).toHaveLength(2);
    controls.forEach((c) => expect(c).toHaveAttribute("data-role", "window-control"));
  });

  it("sends Since to both requests and Until to the score only", async () => {
    renderWithQuery(<SystemView />, world());
    await screen.findByRole("heading", { name: "Score against outcome" });
    fireEvent.change(screen.getByLabelText("since"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByLabelText("until"), { target: { value: "2026-10-20" } });
    const calls = () => apiFetchMock.mock.calls.map((c) => String(c[0]));
    await waitFor(() => expect(calls()).toContain("/pnl/system?since=2026-10-01&until=2026-10-20"));
    expect(calls()).toContain("/pnl/sizing?since=2026-10-01");
    expect(calls().some((c) => c.startsWith("/pnl/sizing") && c.includes("until"))).toBe(false);
  });

  it("says the score report could not load and still shows the sizing record", async () => {
    renderWithQuery(<SystemView />, {
      "/pnl/sizing": { as_of: "", since: null, groups: [] },
      "/claude/context": { available: false },
    });
    expect(await screen.findByText("Could not load the score-vs-outcome report.")).toBeInTheDocument();
    expect(await screen.findByText("No sizing actions on record yet.")).toBeInTheDocument();
  });
});
```

  Append inside `describe("SystemPanel", ...)` in `SystemPanel.test.tsx`:

```tsx
  it("can leave its window controls to its page", () => {
    const { container } = render(<SystemPanel data={aReport()} windowControls={false} />);
    expect(container.querySelectorAll('[data-role="window-control"]')).toHaveLength(0);
    expect(screen.getByText(READONLY_NOTE)).toBeInTheDocument();
  });

  it("exports the two date controls on their own, labelled, for the System view", () => {
    render(<WindowControls since="2026-10-01" until="" />);
    expect(screen.getByLabelText("since")).toHaveValue("2026-10-01");
    expect(screen.getByLabelText("until")).toHaveValue("");
  });
```

  (add `WindowControls` to the `./SystemPanel` import.)

- [x] **Step 3: Run them to verify they fail**

Run: `cd web && npx vitest run features/activity components/pnl/SystemPanel.test.tsx`
Expected: FAIL (modules and exports missing).

- [x] **Step 4: Implement `web/features/activity/sizing.ts`**

```ts
import { formatStubValue } from "@/components/ui/Stub";
import { kindWord } from "@/features/market/market";
import type { SizingGroup } from "./types";

const SPLIT: Record<string, string> = {
  sent_smaller: "sent smaller",
  never_sent: "never sent",
  pushed_out: "pushed out",
};

/** "Scale-in ladder · never sent"; Claude's cuts are one line, whichever way they were recorded. */
export function groupTitle(g: Pick<SizingGroup, "kind" | "split">): string {
  if (g.split === "overrides") return "Claude's size cut";
  return `${kindWord(g.kind)} · ${SPLIT[g.split] ?? g.split.replace(/_/g, " ")}`;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "2 actions · 1 valued so far · 4 contracts held back". */
export function groupSub(g: SizingGroup): string {
  const actions = plural(g.count, "action", "actions");
  if (g.split === "pushed_out") return `${actions} · counted, not valued`;
  return [
    actions,
    `${g.resolved ?? 0} valued so far`,
    `${plural(g.contracts_withheld ?? 0, "contract", "contracts")} held back`,
  ].join(" · ");
}

/** The sentence under a line, when it has something to add; null otherwise. */
export function groupNote(g: SizingGroup): string | null {
  if (g.split === "overrides") return `${g.applied ?? 0} applied, ${g.unapplied ?? 0} recorded only.`;
  if (g.split === "pushed_out") {
    return "A covered call was still sold on the name that day, so the breakout rule only pushed it out.";
  }
  const exact = g.exact ?? 0;
  if (exact > 0) {
    return exact === 1
      ? "1 of the valued rows is valued at the realised P&L of the contract that did trade."
      : `${exact} of the valued rows are valued at the realised P&L of the contracts that did trade.`;
  }
  return null;
}

export type Marks = { expiry: number | null; rules: number | null };

/**
 * The two marks of a line, or null where there is none to give: nothing valued yet (never a
 * zero), a pushed-out line, or no entry IV on any valued row (no exit-rule mark).
 */
export function marks(g: SizingGroup): Marks {
  if (g.split === "pushed_out" || !g.resolved) return { expiry: null, rules: null };
  const rulesKnown = (g.rules_missing ?? 0) < g.resolved;
  return { expiry: g.pnl_expiry ?? null, rules: rulesKnown ? (g.pnl_rules ?? null) : null };
}

/** Why some valued rows have no exit-rule mark; null when none is missing. */
export function rulesNote(g: SizingGroup): string | null {
  const n = g.rules_missing ?? 0;
  if (n <= 0) return null;
  return n === 1
    ? "1 valued row has no entry IV, so its exit-rule mark is left out."
    : `${n} valued rows have no entry IV, so their exit-rule mark is left out.`;
}

export const signedMark = (v: number): string => formatStubValue(v, "signed-money");
```

- [x] **Step 5: Implement `web/features/activity/SizingRecord.tsx`**

```tsx
"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { cutSentence } from "@/features/claude-context/format";
import { useClaudeContext } from "@/features/claude-context/useClaudeContext";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { groupNote, groupSub, groupTitle, marks, rulesNote, signedMark } from "./sizing";
import type { SizingGroup, SizingRecordResponse } from "./types";

function Mark({ label, value }: { label: string; value: number | null }) {
  // No gain or loss colour: a positive number here is what an action COST, so green would mislead.
  return (
    <div>
      <span className={clsx(value === null && "hatch text-unknown")}>{value === null ? UNKNOWN : signedMark(value)}</span>{" "}
      <span className="font-sans text-xs font-normal text-muted">{label}</span>
    </div>
  );
}

function Line({ g }: { g: SizingGroup }) {
  const m = marks(g);
  const notes = [groupNote(g), rulesNote(g)].filter((n): n is string => n !== null);
  return (
    <li className="border-t border-border py-3 first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-sm">
          <span className="font-bold">{groupTitle(g)}</span>
          <div className="text-[0.8125rem] text-muted">{groupSub(g)}</div>
          {notes.map((n) => (
            <p key={n} className="mt-0.5 text-[0.8125rem] text-muted">
              {n}
            </p>
          ))}
        </div>
        {g.split !== "pushed_out" && (
          <div className="tabular text-right font-mono font-semibold">
            <Mark label="to expiry" value={m.expiry} />
            <Mark label="exit rules" value={m.rules} />
          </div>
        )}
      </div>
    </li>
  );
}

/**
 * The sizing record: what the market-regime limits, the scale-in ladder, the leveraged-ETF
 * ceiling, the guaranteed lots and Claude's size cut held back or changed, and what that would have
 * earned, valued so far. It is the review the live-cutover gate asks for. Display only: nothing
 * here can change a limit, a size or a weight. Rows not yet valued are counted and never valued.
 */
export function SizingRecord({ since }: { since?: string }) {
  const { data, isError } = useQuery({
    queryKey: ["pnl", "sizing", since ?? null],
    queryFn: () => apiFetch<SizingRecordResponse>(`/pnl/sizing${since ? `?since=${since}` : ""}`),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });
  const ctx = useClaudeContext().data;

  return (
    <Card aria-labelledby="sizing-title">
      <h2 id="sizing-title" className="text-[1.0625rem] font-bold">
        Sizing record
      </h2>
      <p className="mt-1 text-[0.8125rem] text-muted">
        What the market-regime limits, the scale-in ladder, the leveraged-ETF ceiling, the guaranteed lots and
        Claude&apos;s size cut held back or changed, and what that would have earned. A positive number is what the
        held-back contracts would have earned: the action cost that much. A negative number is a loss it avoided. This
        is the review the live cutover asks for before Claude&apos;s cut applies in live trading.
      </p>
      {ctx?.available && (
        <p className="mt-2 text-sm">
          {cutSentence(ctx.claude_cut_mode, ctx.account_mode, ctx.claude_cut_breaker_tripped_today)}
        </p>
      )}
      <div className="mt-2">
        {isError && !data ? (
          <>
            <p className="text-sm text-muted">Could not load the sizing record.</p>
            <p className="mt-1 text-[0.8125rem] text-muted">It tries again every minute.</p>
          </>
        ) : !data ? (
          <div role="status" aria-busy="true" aria-label="Loading the sizing record" className="h-24 rounded-xl bg-sunk" />
        ) : data.groups.length === 0 ? (
          <p className="py-2 text-sm text-muted">
            {since ? `No sizing actions on record since ${since}.` : "No sizing actions on record yet."}
          </p>
        ) : (
          <ul>
            {data.groups.map((g) => (
              <Line key={g.key} g={g} />
            ))}
          </ul>
        )}
      </div>
      <p className="mt-3 text-[0.8125rem] text-muted">
        Rows not yet valued are counted and wait for their expiry. &quot;To expiry&quot; marks each held-back option
        at its expiry close. &quot;Exit rules&quot; walks the daily closes and exits at the system&apos;s own
        profit-take line (and, for a leveraged ETF, its loss line).
      </p>
    </Card>
  );
}
```

- [x] **Step 6: Restyle `SystemPanel`, `ScoreBucketTable` and `CorrelationTable`** — replace
  `web/components/pnl/SystemPanel.tsx` with the file below. The notes, the agreement block and
  the two tables are the old content in the same order; the window controls become a named export
  (and can be turned off by a page that places them itself); the since and until inputs keep
  their `data-role` and `aria-label`.

```tsx
"use client";

import clsx from "clsx";
import type { ReactNode } from "react";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { UNKNOWN } from "@/lib/format";
import { CorrelationTable } from "./CorrelationTable";
import { ScoreBucketTable } from "./ScoreBucketTable";
import type { SystemPerformanceResponse, VerdictAgreementData } from "./types";

/**
 * The since/until window: the only controls on the surface. No apply button, no suggested weight,
 * no editable field that could reach the scoring config.
 */
export function WindowControls({
  since,
  until,
  onSinceChange,
  onUntilChange,
}: {
  since?: string;
  until?: string;
  onSinceChange?: (value: string) => void;
  onUntilChange?: (value: string) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="grid gap-1">
        <span className={FIELD_LABEL}>Since</span>
        <input
          type="date"
          data-role="window-control"
          aria-label="since"
          value={since ?? ""}
          onChange={(e) => onSinceChange?.(e.target.value)}
          className={clsx(FIELD, "w-full")}
        />
      </label>
      <label className="grid gap-1">
        <span className={FIELD_LABEL}>Until</span>
        <input
          type="date"
          data-role="window-control"
          aria-label="until"
          value={until ?? ""}
          onChange={(e) => onUntilChange?.(e.target.value)}
          className={clsx(FIELD, "w-full")}
        />
      </label>
    </div>
  );
}

/**
 * The score-vs-outcome evidence's reader (P3-P4 M6 Task 6.2) - the human `CLAUDE.md` says must
 * re-derive scoring_weights.yaml by hand from this evidence. Every note score_outcome_report
 * produces renders here in full and in order (the read-only sentence is why this surface is
 * allowed to exist at all); the panel offers no control that could change a weight, only the
 * since/until window, which a page may place itself (`windowControls={false}`). Presentational:
 * the page owns the fetch and the window state.
 */
export function SystemPanel({
  data,
  since,
  until,
  onSinceChange,
  onUntilChange,
  windowControls = true,
}: {
  data: SystemPerformanceResponse;
  since?: string;
  until?: string;
  onSinceChange?: (value: string) => void;
  onUntilChange?: (value: string) => void;
  windowControls?: boolean;
}) {
  const { report, agreement } = data;
  const notes = report.notes ?? [];

  return (
    <div className="space-y-5" data-testid="system-panel">
      {windowControls && (
        <WindowControls since={since} until={until} onSinceChange={onSinceChange} onUntilChange={onUntilChange} />
      )}

      <ul className="space-y-1 text-[0.8125rem] text-muted">
        {notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>

      <AgreementBlock agreement={agreement} />

      {report.n_closed > 0 && (
        <>
          <ScoreBucketTable buckets={report.blended_score_buckets ?? []} label="Blended score" />
          <ScoreBucketTable buckets={report.component_buckets ?? []} label="Score components" />
          <CorrelationTable correlations={report.signal_correlations ?? []} />
        </>
      )}
    </div>
  );
}

function AgreementBlock({ agreement }: { agreement: VerdictAgreementData }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4" data-testid="agreement-block">
      <Headline label="Verdicts agreed">
        <Rate value={agreement.agreement_rate} />
      </Headline>
      <Headline label="Claude win rate">
        <Rate value={agreement.claude_win_rate} />
      </Headline>
      <Headline label="Baseline win rate">
        <Rate value={agreement.baseline_win_rate} />
      </Headline>
      <Headline label="Closed trades compared">
        <span className="tabular font-mono text-content">{agreement.n_closed}</span>
      </Headline>
    </div>
  );
}

function Rate({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return <span className="tabular hatch font-mono text-unknown">{UNKNOWN}</span>;
  }
  return <span className="tabular font-mono text-content">{Math.round(value * 100)}%</span>;
}

function Headline({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[0.8125rem] text-muted">{label}</span>
      {children}
    </div>
  );
}
```

  Replace `web/components/pnl/ScoreBucketTable.tsx` with:

```tsx
"use client";

import { Money } from "@/components/portfolio/Money";
import type { ScoreBucketData } from "./types";

const SMALL_SAMPLE_THRESHOLD = 5;

/**
 * One score-vs-outcome bucket table (blended-score bands or per-component high/low split).
 * A bucket with n below SMALL_SAMPLE_THRESHOLD is labelled in words - a win rate from a
 * handful of trades is not evidence and must not read as one.
 */
export function ScoreBucketTable({ buckets, label }: { buckets: ScoreBucketData[]; label: string }) {
  if (buckets.length === 0) {
    return null;
  }
  const head = "py-1.5 pr-3 text-right font-semibold";
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">{label}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold tracking-[0.04em] text-muted">
              <th className="py-1.5 pr-3 font-semibold">Band</th>
              <th className={head}>n</th>
              <th className={head}>Win rate</th>
              <th className={head}>Mean P&amp;L</th>
              <th className={head}>Total P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.label} className="border-t border-border first:border-t-0">
                <td className="py-2 pr-3 font-mono text-content">{b.label}</td>
                <td className="tabular py-2 pr-3 text-right font-mono text-content">
                  {b.n}
                  {b.n < SMALL_SAMPLE_THRESHOLD && <span className="ml-1 text-xs text-unknown">small sample</span>}
                </td>
                <td className="tabular py-2 pr-3 text-right font-mono text-content">{Math.round(b.win_rate * 100)}%</td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  <Money value={b.mean_pnl} kind="realized" signed />
                </td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  <Money value={b.total_pnl} kind="realized" signed />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

  Replace `web/components/pnl/CorrelationTable.tsx` with:

```tsx
"use client";

import { Money } from "@/components/portfolio/Money";
import { UNKNOWN } from "@/lib/format";
import type { SignalCorrelationData } from "./types";

const na = <span className="hatch text-unknown">{UNKNOWN}</span>;

/**
 * How each signal relates to realized P&L. `pearson_r` and the low/high split render n/a
 * when undefined (n<2 or zero variance) - never a fabricated 0.
 */
export function CorrelationTable({ correlations }: { correlations: SignalCorrelationData[] }) {
  if (correlations.length === 0) {
    return null;
  }
  const head = "py-1.5 pr-3 text-right font-semibold";
  const cell = "tabular py-2 pr-3 text-right font-mono";
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">Signal correlations</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold tracking-[0.04em] text-muted">
              <th className="py-1.5 pr-3 font-semibold">Signal</th>
              <th className={head}>n</th>
              <th className={head}>Pearson r</th>
              <th className={head}>Low-half mean P&amp;L</th>
              <th className={head}>High-half mean P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {correlations.map((c) => (
              <tr key={c.signal} className="border-t border-border first:border-t-0">
                <td className="py-2 pr-3 font-mono text-content">{c.signal}</td>
                <td className={`${cell} text-content`}>{c.n}</td>
                <td className={cell}>{c.pearson_r == null ? na : c.pearson_r.toFixed(2)}</td>
                <td className={cell}>
                  {c.low_half_mean_pnl == null ? na : <Money value={c.low_half_mean_pnl} kind="realized" signed />}
                </td>
                <td className={cell}>
                  {c.high_half_mean_pnl == null ? na : <Money value={c.high_half_mean_pnl} kind="realized" signed />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [x] **Step 7: Implement `web/features/activity/SystemView.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { SystemPanel, WindowControls } from "@/components/pnl/SystemPanel";
import type { SystemPerformanceResponse } from "@/components/pnl/types";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";
import { SizingRecord } from "./SizingRecord";

/**
 * System: the sizing record, then the score against outcome, under one window. Both are read-only
 * evidence for a human (the fence in CLAUDE.md): nothing here can change a limit, a size or a
 * weight. Since narrows both (the day an action was taken, the day a trade closed); Until narrows
 * the score evidence only.
 */
export function SystemView() {
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const qs = new URLSearchParams();
  if (since) qs.set("since", since);
  if (until) qs.set("until", until);

  const system = useQuery({
    queryKey: ["pnl", "system", since, until],
    queryFn: () => apiFetch<SystemPerformanceResponse>(`/pnl/system?${qs.toString()}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  return (
    <div className="grid gap-4">
      <section aria-label="Window" className="grid gap-2">
        <WindowControls since={since} until={until} onSinceChange={setSince} onUntilChange={setUntil} />
        <p className="text-[0.8125rem] text-muted">
          Since narrows the sizing record and the score evidence. Until narrows the score evidence only.
        </p>
      </section>
      <SizingRecord since={since || undefined} />
      <Card aria-labelledby="score-title">
        <h2 id="score-title" className="text-[1.0625rem] font-bold">
          Score against outcome
        </h2>
        <div className="mt-3">
          {system.isError && !system.data ? (
            <>
              <p className="text-sm text-muted">Could not load the score-vs-outcome report.</p>
              <p className="mt-1 text-[0.8125rem] text-muted">It tries again every 30 seconds.</p>
            </>
          ) : !system.data ? (
            <div role="status" aria-busy="true" aria-label="Loading the score report" className="h-24 rounded-xl bg-sunk" />
          ) : (
            <SystemPanel data={system.data} windowControls={false} />
          )}
        </div>
      </Card>
    </div>
  );
}
```

- [x] **Step 8: Run the tests, then the gate**

Run: `cd web && npx vitest run features/activity components/pnl && npx tsc --noEmit && npm run lint`
Expected: PASS: `sizing` 15, `SizingRecord` 12, `SystemView` 4, the 2 new `SystemPanel` tests;
every existing `SystemPanel` test (the notes in order, no control that could change a weight, the
small-sample label, the buckets and correlations with n/a, the agreement block) **unmodified**.

- [x] **Step 9: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/activity web/components/pnl`
Expected: exit 0 over every non-test source file, or every finding fixed in the code.

- [x] **Step 10: Commit** (with the Progress log row for Task 13 filled in)

```bash
git add web/features/activity web/components/pnl/SystemPanel.tsx web/components/pnl/SystemPanel.test.tsx \
  web/components/pnl/ScoreBucketTable.tsx web/components/pnl/CorrelationTable.tsx \
  docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git commit -m "feat(web): Activity System - the sizing record over the score against outcome"
```

---

### Task 14: The Activity page at `/activity`, and `/ledger` joins it

**Files:**
- Create: `web/features/activity/views.ts`, `web/features/activity/ActivityPage.tsx`,
  `web/features/activity/ActivityPage.test.tsx`
- Modify: `web/app/activity/page.tsx`, `web/next.config.ts`, `web/next.config.test.ts`,
  `web/app/more/page.tsx`, `web/app/more/page.test.tsx`
- Delete: `web/app/ledger/page.tsx`

**Interfaces:**
- Consumes: `useViewParam` (Task 4), `PayView` (Tasks 8–9), `LedgerOverview` (Task 10),
  `FillsView` (Task 12), `SystemView` (Task 13), `SegmentedControl`.
- Produces: `ActivityPage()`; `ACTIVITY_VIEWS`, `VIEW_LABEL`, `ActivityView` (`views.ts`); the
  redirect `/ledger` → `/activity?view=ledger`.

- [x] **Step 1: Load da-vinci** if it is not already loaded. Brief: the page frame only: the title,
  the four view chips, the view.

- [x] **Step 2: Write the failing tests**

Create `web/features/activity/ActivityPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetchMock } from "@/lib/test-query";

const nav = vi.hoisted(() => ({ replace: vi.fn(), params: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.params,
  usePathname: () => "/activity",
}));

import { ActivityPage } from "./ActivityPage";

const now = () => new Date().toISOString();
const filters = { as_of: now(), symbol: null, strategy: null, outcome: null, since: null, until: null, book: "all" };

function serve() {
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path.startsWith("/pnl/month")) {
      return {
        as_of: now(), book: "paper", spreads_available: true,
        pay: {
          month: "2026-10-01", strategy: "all", premium_collected: 0, bought_back: 0, commissions: 0,
          commissions_complete: true, net: 0, n_opened: 0, n_closed: 0, month_start_value: null, target_pct: null,
          target_mode: "off", target_amount: null, target_base: null, target: null, progress_pct: null, days_left: 8,
        },
      };
    }
    if (path.startsWith("/pnl/summary")) {
      return {
        as_of: now(), filters, marks_as_of: null,
        summary: { realized_total: 0, unrealized_total: null, commissions_complete: true, n_open: 0, n_closed: 0, win_rate: null, by_strategy: [], by_symbol: [], best: null, worst: null },
      };
    }
    if (path.startsWith("/pnl/equity")) return { as_of: now(), filters, curve: { points: [], gaps: [], starts_at: null } };
    if (path.startsWith("/pnl/ledger")) return { as_of: now(), filters, campaigns: [], marks_as_of: null, n_legs: 0 };
    if (path.startsWith("/ledger/summary")) {
      return {
        as_of: now(),
        summary: {
          total_realized_usd: 0, interest_and_fees_usd: 0, contributed_usd: null, capital_utilised_usd: 0, available_usd: null,
          unrealized_usd: null, win_rate: null, n_trades: 0, n_open: 0, premium_this_month_usd: 0, months: [], curve: [],
          by_strategy: [], by_book: [], upcoming: [], fx_incomplete: false, orphan_closes: 0, unreviewed_corporate_actions: 0, marks_as_of: null,
        },
      };
    }
    if (path.startsWith("/ledger/tickers")) return { as_of: now(), tickers: [] };
    if (path.startsWith("/options/orders")) return { as_of: now(), orders: [] };
    if (path.startsWith("/options/fills")) return { as_of: now(), fills: [] };
    if (path.startsWith("/options/controls")) return {};
    if (path.startsWith("/spreads/orders")) return { as_of: now(), available: true, underlying: "SPY", orders: [] };
    if (path.startsWith("/ledger/executions")) return { as_of: now(), days: 30, limit: 200, truncated: false, executions: [] };
    if (path.startsWith("/pnl/system")) {
      return {
        as_of: now(), since: null, until: null,
        report: { n_closed: 0, period_start: null, period_end: null, blended_score_buckets: [], component_buckets: [], signal_correlations: [], notes: ["Read-only."] },
        agreement: { n_closed: 0, n_agreed: 0, agreement_rate: null, claude_win_rate: null, baseline_win_rate: null },
      };
    }
    if (path.startsWith("/pnl/sizing")) return { as_of: now(), since: null, groups: [] };
    if (path.startsWith("/claude/context")) return { available: false, dossiers: [] };
    throw new Error(`no mocked response for ${path}`);
  });
}

const mount = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // A function, so each rerender is a new element: React skips an identical one.
  const tree = () => (
    <QueryClientProvider client={qc}>
      <ActivityPage />
    </QueryClientProvider>
  );
  const r = render(tree());
  return { rerenderPage: () => r.rerender(tree()) };
};

beforeEach(() => {
  nav.replace.mockReset();
  nav.params = new URLSearchParams();
  serve();
});

describe("ActivityPage", () => {
  it("opens on Pay, with the four view chips", async () => {
    mount();
    expect(screen.getByRole("heading", { level: 1, name: "Activity" })).toBeInTheDocument();
    const views = screen.getByRole("group", { name: "View" });
    expect(within(views).getByRole("button", { name: "Pay" })).toHaveAttribute("aria-pressed", "true");
    for (const name of ["Ledger", "Fills and orders", "System"]) {
      expect(within(views).getByRole("button", { name })).toHaveAttribute("aria-pressed", "false");
    }
    expect(await screen.findByRole("group", { name: /pay stub$/ })).toBeInTheDocument();
  });

  it.each([
    ["ledger", /What IBKR reports, from the live feed/],
    ["fills", /The system's record: the wheel orders it sent to IBKR/],
    ["system", /A positive number is what the held-back contracts would have earned/],
  ])("opens the %s view the URL asks for", async (view, text) => {
    nav.params = new URLSearchParams(`view=${view}`);
    mount();
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("opens Pay for a view it does not know", async () => {
    nav.params = new URLSearchParams("view=bogus");
    mount();
    expect(await screen.findByRole("group", { name: /pay stub$/ })).toBeInTheDocument();
  });

  it("writes the chosen view into the URL and keeps the month", async () => {
    nav.params = new URLSearchParams("month=2026-09");
    mount();
    await screen.findByRole("group", { name: /pay stub$/ });
    fireEvent.click(screen.getByRole("button", { name: "Ledger" }));
    expect(nav.replace).toHaveBeenCalledWith("/activity?month=2026-09&view=ledger", { scroll: false });
  });

  it("changes view without asking for the other views' data", async () => {
    // The mock's call log spans the whole file, so look only at the calls this test makes.
    const start = apiFetchMock.mock.calls.length;
    const askedForExecutions = () =>
      apiFetchMock.mock.calls.slice(start).some((c) => String(c[0]).startsWith("/ledger/executions"));
    const page = mount();
    await screen.findByRole("group", { name: /pay stub$/ });
    expect(askedForExecutions()).toBe(false);
    nav.params = new URLSearchParams("view=system");
    page.rerenderPage();
    await screen.findByText(/A positive number is what the held-back contracts would have earned/);
    expect(askedForExecutions()).toBe(false);
  });
});
```

  In `web/next.config.test.ts` add inside `it("keeps every old URL working", ...)`:
  `expect(map["/ledger"].destination).toBe("/activity?view=ledger");`.

  In `web/app/more/page.test.tsx` change the test titled "links to Universe and Ledger, which have
  no tab or rail entry" to "links to Universe, and to the Ledger view on Activity" and its Ledger
  assertion (line 48) to
  `expect(screen.getByRole("link", { name: /^Ledger/ })).toHaveAttribute("href", "/activity?view=ledger");`
  (the "Import a statement" row keeps `/ledger/import`).

- [x] **Step 3: Run them to verify they fail**

Run: `cd web && npx vitest run features/activity/ActivityPage.test.tsx next.config.test.ts app/more`
Expected: FAIL (`ActivityPage` missing; no `/ledger` redirect; More still links `/ledger`).

- [x] **Step 4: Implement** — `web/features/activity/views.ts`:

```ts
/** The Activity page's views (web/DESIGN.md Surfaces → Activity). */
export type ActivityView = "pay" | "ledger" | "fills" | "system";

export const ACTIVITY_VIEWS: readonly ActivityView[] = ["pay", "ledger", "fills", "system"];

export const VIEW_LABEL: Record<ActivityView, string> = {
  pay: "Pay",
  ledger: "Ledger",
  fills: "Fills and orders",
  system: "System",
};
```

`web/features/activity/ActivityPage.tsx`:

```tsx
"use client";

import { LedgerOverview } from "@/components/ledger/LedgerOverview";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useViewParam } from "@/lib/useViewParam";
import { FillsView } from "./FillsView";
import { PayView } from "./PayView";
import { SystemView } from "./SystemView";
import { ACTIVITY_VIEWS, VIEW_LABEL } from "./views";

const SHELL = "mx-auto max-w-[1200px] px-4 py-5 md:px-7 md:py-6";

/**
 * Activity: what the money did and whether the records agree, in four views kept in the URL. Only
 * the chosen view mounts, so the other views' lists are not asked for until they are opened.
 */
export function ActivityPage() {
  const [view, setView] = useViewParam(ACTIVITY_VIEWS, "pay");
  const options = ACTIVITY_VIEWS.map((v) => ({ value: v, label: VIEW_LABEL[v] }));
  return (
    <div className={SHELL}>
      <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Activity</h1>
      <div className="mt-4">
        <SegmentedControl label="View" appearance="chips" options={options} value={view} onChange={setView} />
      </div>
      <div className="mt-5">
        {view === "pay" && <PayView />}
        {view === "ledger" && <LedgerOverview />}
        {view === "fills" && <FillsView />}
        {view === "system" && <SystemView />}
      </div>
    </div>
  );
}
```

Replace `web/app/activity/page.tsx` with:

```tsx
import { Suspense } from "react";
import { ActivityPage } from "@/features/activity/ActivityPage";

// useSearchParams (the view and the Pay month) needs a Suspense boundary under the App Router.
export default function Page() {
  return (
    <Suspense>
      <ActivityPage />
    </Suspense>
  );
}
```

In `web/next.config.ts` add to the `redirects()` list, after the `/pnl` entry:
`{ source: "/ledger", destination: "/activity?view=ledger", permanent: false },`.

In `web/app/more/page.tsx` change the Ledger row's `href: "/ledger"` to
`href: "/activity?view=ledger"` (its label and sub-line stay); the "Import a statement" row keeps
`/ledger/import`.

Delete `web/app/ledger/page.tsx` (`git rm web/app/ledger/page.tsx`): the redirect owns `/ledger`,
and `/ledger/trades`, `/ledger/import` and `/ledger/ticker/:symbol` keep their own page files.
`components/pnl/PnlShell.tsx` is now unmounted; it and `components/ledger/LedgerNav.tsx` stay for
Part 4 (ruling 12).

- [x] **Step 5: Run the tests, then the gate and a production build**

Run: `cd web && npx vitest run && npx tsc --noEmit && npm run lint`, then the scratch-copy build
from C2:

```bash
S="$(mktemp -d)/web" && rsync -a --exclude node_modules --exclude .next web/ "$S/" \
  && ln -s "$PWD/web/node_modules" "$S/node_modules" && (cd "$S" && npm run build)
```

Expected: PASS: 7 new `ActivityPage` tests (the `it.each` is three) and the config and More
changes; the whole suite green; the build lists `/activity`, `/portfolio`, `/ledger/trades`,
`/ledger/import` and `/ledger/ticker/[symbol]` and no `/ledger`.

- [x] **Step 6: da-vinci lint**

Run: `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/activity web/app/activity web/app/more`
Expected: exit 0, or every finding fixed in the code.

- [x] **Step 7: Commit** (with the Progress log row for Task 14 filled in)

```bash
git add web/features/activity web/app/activity/page.tsx web/next.config.ts web/next.config.test.ts \
  web/app/more/page.tsx web/app/more/page.test.tsx docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md
git rm web/app/ledger/page.tsx
git commit -m "feat(web): the Activity page - Pay, Ledger, Fills and orders, System; /ledger redirects into it"
```

---

## Section D — Docs and finish (Task 15) · model: sonnet (effort xhigh), then an opus whole-branch review

Looks at the result in a browser, runs the da-vinci finish, sweeps the docs and runs every gate.

**Entry checks (run before Task 15):**

- [ ] **D1. Section C landed.** `git log --oneline main..HEAD` shows fourteen commits (plus any
  review fix passes recorded in the Progress log); Tasks 8–14 are ticked.
- [ ] **D2. Every gate and the build green.** `python -m pytest -q && ruff check . && mypy src`,
  `cd web && npx vitest run && npx tsc --noEmit && npm run lint`, and the scratch-copy build from
  C2.
- [ ] **D3. The safety checks still hold.** C4 and C5 print what they printed in Section C (C4 only
  the two `TargetCard` files; C5 nothing).
- [ ] **D4. A browser is available for the visual check.** The Claude-in-Chrome or Playwright
  tools load, or the operator agrees to take the screenshots in Step 2 by hand.

**Section exit (plan done):** fifteen task commits (plus any review fix passes) and the
Progress-log commit; then the whole-branch review and superpowers:finishing-a-development-branch.
No merge or push without the operator.

---

### Task 15: Docs, the da-vinci finish, the full gate

**Files:**
- Modify: `web/DESIGN.md`, `web/CLAUDE.md`, `ARCHITECTURE.md`, `STATUS.md`, `SETUP.md`,
  `CLAUDE.md` (root), `docs/web/api.md`
- Modify: any file the finish review fixes (each fix with its test when behaviour changes)
- Create (scratch only, never committed): a mock API script in the session's scratchpad

**Interfaces:**
- Consumes: the whole branch.
- Produces: the finished Part 3; the Progress log complete.

- [x] **Step 1: Run a synthetic API for the visual check.** Never point the console at the live
  API for this. Write this script to the scratchpad (not the repo) and run it in the background:

```python
"""A synthetic API for the Portfolio and Activity visual check (web overhaul Part 3, Task 15).
Never the live one. Serves the paths the shell, Portfolio and Activity read."""

import json
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

now = datetime.now(UTC)
iso = lambda d: d.isoformat().replace("+00:00", "Z")  # noqa: E731
AT = iso(now)
FILT = {"as_of": AT, "symbol": None, "strategy": None, "outcome": None, "since": None, "until": None, "book": "all"}
S = lambda v, stale=False: {"value": v, "source": "ibkr", "as_of": AT, "stale": stale}  # noqa: E731


def leg(sym, right, strike, exp, dte, pnl, **o):
    d = {"as_of": AT, "symbol": sym, "right": right, "strike": strike, "expiry": exp, "dte": dte, "contracts": 1,
         "short": True, "delta": -0.21, "delta_source": "ibkr", "market_price": 1.42, "market_value": -142,
         "unrealized_pnl": pnl, "moneyness": "otm", "assignment_risk": False}
    d.update(o)
    return d


EXP = (now + timedelta(days=28)).date().isoformat()
POSITIONS = {"as_of": AT, "source": "monitor", "degraded": False, "groups": [
    {"as_of": AT, "underlying": "AAPL", "stock": {"as_of": AT, "shares": 100, "avg_cost": 182.4, "adjusted_cost_basis": 176.1,
     "market_price": 190, "market_value": 19000, "unrealized_pnl": 760, "unrealized_pnl_adjusted": 1390},
     "options": [leg("AAPL  A", "C", 200, EXP, 28, -12)]},
    {"as_of": AT, "underlying": "NVDA", "stock": None, "options": [leg("NVDA  B", "P", 165, EXP, 28, 38),
     leg("NVDA  C", "P", 160, EXP, 28, None)]},
]}
CAMPAIGNS = {"as_of": AT, "campaigns": [
    {"as_of": AT, "campaign_id": "c1", "symbol": "AAPL", "status": "open", "opened_date": "2026-09-01", "closed_date": None,
     "legs": [{"as_of": AT, "candidate_id": "a", "strategy": "cash_secured_put", "right": "P", "strike": 180, "expiry": EXP, "known": True},
              {"as_of": AT, "candidate_id": "b", "strategy": "covered_call", "right": None, "strike": None, "expiry": None, "known": False}],
     "total_premium_collected": 600, "total_debit_paid": 0, "net_premium": 600, "assigned": True,
     "adjusted_cost_basis": 176.1, "realized_stock_pnl": None}]}
CALENDAR = {"as_of": AT, "source": "monitor", "degraded": False, "horizon_days": 45, "days": [
    {"as_of": AT, "expiry": EXP, "dte": 28, "entries": [
        {"as_of": AT, "symbol": "AAPL  A", "underlying": "AAPL", "right": "C", "strike": 200, "contracts": 1, "short": True,
         "moneyness": "otm", "consequence": "expires_worthless", "assignment_risk": False},
        {"as_of": AT, "symbol": "NVDA  C", "underlying": "NVDA", "right": "P", "strike": 160, "contracts": 1, "short": True,
         "moneyness": None, "consequence": "unknown", "assignment_risk": False}]}]}
SUMMARY = {"as_of": AT, "source": "monitor", "degraded": False, "note": None,
           "account": {"as_of": AT, "net_liquidation": S(125000), "total_cash": S(40000), "buying_power": S(80000),
                       "maintenance_margin": S(None), "excess_liquidity": S(68000, True)},
           "exposure": {"as_of": AT, "open_positions": 3, "open_shorts": 3, "open_campaigns": 1, "net_delta_exposure": -150,
                        "cash_secured_against_puts": 33000, "buying_power_utilisation_pct": 22.5, "shorts_at_assignment_risk": 0}}
PAY = {"as_of": AT, "book": "paper", "spreads_available": True, "pay": {
    "month": now.date().replace(day=1).isoformat(), "strategy": "all", "premium_collected": 2000, "bought_back": 400,
    "commissions": 26, "commissions_complete": True, "net": 1574, "n_opened": 12, "n_closed": 9, "month_start_value": 100000,
    "target_pct": None, "target_mode": "fixed", "target_amount": 2000, "target_base": None, "target": 2000,
    "progress_pct": 78.7, "days_left": 8}}
LEG = {"candidate_id": "x1", "campaign_id": "c1", "symbol": "NVDA 261016 00170000P", "underlying": "NVDA", "strategy": "cash_secured_put",
       "right": "P", "strike": 170, "expiry": "2026-10-16", "contracts": 1, "opened_at": AT, "closed_at": AT, "credit": 150, "debit": 0,
       "commissions": 1, "commissions_complete": True, "net_pnl": 149, "unrealized_pnl": None, "days_held": 5, "roc_pct": 0.88,
       "annualized_pct": None, "outcome": "expired_worthless", "is_live": False}
EX = {"id": 1, "source": "live", "exec_id": "e1", "trade_time": AT, "trade_date": now.date().isoformat(), "underlying": "NVDA",
      "sec_type": "OPT", "right": "P", "strike": 165, "expiry": EXP, "multiplier": 100, "currency": "USD", "quantity": -1,
      "price": 2.35, "proceeds": 235, "commission": -1.3, "codes": "O", "book": "system", "ib_order_id": 11, "perm_id": 900}
ROUTES = {
    "/portfolio/summary": SUMMARY, "/portfolio/positions": POSITIONS, "/portfolio/campaigns": CAMPAIGNS,
    "/portfolio/calendar": CALENDAR, "/spreads/positions": {"as_of": AT, "available": True, "underlying": "SPY", "mode": "paper", "positions": []},
    "/options/shorts": {"as_of": AT, "shorts": []}, "/options/approvals": {"as_of": AT, "approvals": []},
    "/options/controls": {"as_of": AT, "autonomy": {"level": "full", "label": "Full"}, "rungs": [], "halted": False, "mode": "paper",
                          "drain_healthy": True, "drain_last_seen": AT, "pending_commands": 0},
    "/claude/context": {"as_of": AT, "available": True, "claude_cut_mode": "record_only", "account_mode": "live",
                        "claude_cut_breaker_tripped_today": False,
                        "dossiers": [{"symbol": "NVDA", "health": "weak", "events": [
                            {"id": "E1", "title": "Earnings", "on": (now + timedelta(days=9)).date().isoformat(), "evidence": "C1", "quote": "q"}]}]},
    "/pnl/month": PAY,
    "/pnl/summary": {"as_of": AT, "filters": FILT, "marks_as_of": AT, "summary": {
        "realized_total": 320, "unrealized_total": 115, "commissions_complete": True, "n_open": 2, "n_closed": 4, "win_rate": 0.75,
        "by_strategy": [{"label": "cash_secured_put", "n_closed": 4, "realized": 320, "win_rate": 0.75, "mean_days_held": 12.5, "mean_roc_pct": 2.1}],
        "by_symbol": [], "best": LEG, "worst": None}},
    "/pnl/equity": {"as_of": AT, "filters": FILT, "curve": {"points": [
        {"entry_date": (now - timedelta(days=d)).date().isoformat(), "net_liquidation": 250000, "unrealized_pnl": 100,
         "cumulative_realized": 40 * (10 - d), "premium_cashflow": 55 * (10 - d)} for d in range(9, -1, -1)], "gaps": [], "starts_at": "2026-06-24"}},
    "/pnl/ledger": {"as_of": AT, "filters": FILT, "marks_as_of": AT, "n_legs": 1, "campaigns": [
        {"campaign_id": "c1", "symbol": "NVDA", "status": "open", "opened_date": "2026-09-01", "closed_date": None, "legs": [LEG],
         "option_realized": 149, "option_unrealized": None, "stock_realized": None, "stock_unrealized": None, "assigned": False,
         "adjusted_cost_basis": None, "total_net": 149}]},
    "/ledger/summary": {"as_of": AT, "summary": {"total_realized_usd": 2575.84, "interest_and_fees_usd": 0, "contributed_usd": None,
        "capital_utilised_usd": 17000, "available_usd": None, "unrealized_usd": None, "win_rate": 0.75, "n_trades": 6, "n_open": 1,
        "premium_this_month_usd": 401, "months": [{"month": "2026-09", "premium_usd": 900, "realized_usd": 700}],
        "curve": [{"point_date": "2026-09-01", "cumulative_usd": 100}, {"point_date": "2026-10-01", "cumulative_usd": 2575.84}],
        "by_strategy": [{"label": "CSP", "n_closed": 4, "realized_usd": 900, "win_rate": 0.75}], "by_book": [],
        "upcoming": [], "fx_incomplete": False, "orphan_closes": 2, "unreviewed_corporate_actions": 0, "marks_as_of": None}},
    "/ledger/tickers": {"as_of": AT, "tickers": []},
    "/ledger/trades": {"as_of": AT, "n": 0, "trades": [], "filters": {}},
    "/ledger/executions": {"as_of": AT, "days": 30, "limit": 200, "truncated": False, "executions": [EX]},
    "/options/orders": {"as_of": AT, "orders": [
        {"as_of": AT, "id": 1, "candidate_id": "c1", "approval_id": 5, "underlying": "NVDA", "strategy": "cash_secured_put", "strike": 165,
         "expiry": EXP, "state": "filled", "limit_price": 2.4, "filled_qty": 1, "avg_fill_price": 2.35, "is_live": False, "detail": None,
         "created_at": AT, "updated_at": AT,
         "sizing": [{"kind": "claude_cut", "deterministic_contracts": 3, "sent_contracts": 1, "reason": "Claude suggested 1"}]}]},
    "/options/fills": {"as_of": AT, "fills": [{"as_of": AT, "id": 1, "order_id": 1, "candidate_id": "c1", "action": "SELL", "filled_qty": 1,
        "avg_price": 2.35, "commission": 1.3, "is_live": False, "filled_at": AT, "underlying": "NVDA", "strategy": "cash_secured_put",
        "right": "P", "strike": 165, "expiry": EXP}]},
    "/spreads/orders": {"as_of": AT, "available": True, "underlying": "SPY", "orders": [
        {"spread_id": "s1", "kind": "close", "ib_order_id": 11, "perm_id": 4001, "filled_qty": 2, "price": 0.05, "commission": 2.6,
         "reason": "profit_take", "created_at": AT, "mode": "paper", "side": "put", "expiry": EXP, "short_strike": 763, "long_strike": 758}]},
    "/pnl/system": {"as_of": AT, "since": None, "until": None, "report": {"n_closed": 12, "period_start": None, "period_end": None,
        "blended_score_buckets": [{"label": "70-80", "n": 3, "win_rate": 0.6, "mean_pnl": 45.5, "total_pnl": 136.5}],
        "component_buckets": [], "signal_correlations": [{"signal": "blended_score", "n": 12, "pearson_r": None,
        "low_half_mean_pnl": None, "high_half_mean_pnl": 60}], "notes": ["Closed (executed+settled) trades only.",
        "Read-only: re-derive scoring_weights.yaml from this evidence by hand (the fence forbids any automatic feedback into the engine)."]},
        "agreement": {"n_closed": 12, "n_agreed": 9, "agreement_rate": 0.75, "claude_win_rate": 0.7, "baseline_win_rate": None}},
    "/pnl/sizing": {"as_of": AT, "since": None, "groups": [
        {"key": "scale_in_zone:never_sent", "kind": "scale_in_zone", "split": "never_sent", "count": 5, "contracts_withheld": 8,
         "resolved": 2, "exact": 0, "pnl_expiry": 120, "pnl_rules": 80, "rules_missing": 0, "applied": None, "unapplied": None},
        {"key": "claude_overrides", "kind": "claude_cut", "split": "overrides", "count": 2, "contracts_withheld": 0, "resolved": 0,
         "exact": 0, "pnl_expiry": 0, "pnl_rules": 0, "rules_missing": 0, "applied": 1, "unapplied": 1},
        {"key": "cc_breakout_floor:pushed_out", "kind": "cc_breakout_floor", "split": "pushed_out", "count": 1, "contracts_withheld": None,
         "resolved": None, "exact": None, "pnl_expiry": None, "pnl_rules": None, "rules_missing": None, "applied": None, "unapplied": None}]},
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        body = ROUTES.get(path)
        code = 200 if body is not None else 404
        payload = json.dumps(body if body is not None else {"detail": f"mock: no route for {self.path}"}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


HTTPServer(("127.0.0.1", 8799), Handler).serve_forever()
```

Start a dev server on a scratch copy pointed at it (never the operator's `web/` and its `.next`):

```bash
S="$(mktemp -d)/web" && rsync -a --exclude node_modules --exclude .next web/ "$S/" \
  && ln -s "$PWD/web/node_modules" "$S/node_modules" \
  && (cd "$S" && API_URL=http://127.0.0.1:8799 API_TOKEN=mock npx next dev -p 3100)
```

Run both in the background. A page that reads a route the mock lacks shows its error sentence,
which is fine: the check is Portfolio, Activity and the ledger's own pages.

- [x] **Step 2: Look at it.** At 1440px and 390px wide, in light and in dark (More → theme), open:
  `/portfolio` (Positions: the AAPL card with its shares row, the NVDA card whose total is `n/a`
  because one leg is unknown, the "Weak health" and "Event" words on NVDA; then Campaigns, with the
  assigned thread open and the pruned leg; then Calendar, with the event word on NVDA and "Consequence
  unknown"), `/activity` (Pay for this month with the meter, then `?month=` a past month, with
  Previous disabled at the first month; the filters, the totals, the curve, the legs with a thread
  open; Ledger; Fills and orders: Orders with Claude's cut, Fills with the credit-spread section,
  At IBKR; System with the sizing record and the score evidence), `/ledger/trades` (open a trade:
  the sheet), `/ledger/ticker/NVDA` and `/ledger/import`. Then 320px for `/portfolio` and
  `/activity?view=fills`: no horizontal scroll of the page (check `document.documentElement.scrollWidth`
  and `main.scrollWidth` against the viewport). Take a screenshot of each; keep them in the
  scratchpad, not the repo.

- [x] **Step 3: da-vinci finish.** With da-vinci loaded, run its `critique` and `audit` over
  `/portfolio` (all views), `/activity` (all views) and the three ledger pages, then `polish` what
  they find. Rules for the fixes:
  - every behaviour change gets a test (RED first, then GREEN), recorded in the Progress log;
  - no new colour, font, radius, elevation or token without the operator (propose it in the log);
  - nothing in the protected files changes; if a finding is about their look, it goes to
    DESIGN.md's Open Decisions, not into code;
  - `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features web/components/pnl web/components/ledger web/components/portfolio web/components/options web/components/ui`
    exits 0 over every non-test source file at the end (it exited 1 on `main` over em dashes in
    legacy test titles; that is not copy and not this plan's to reword).
  Commit the fixes on their own: `git commit -m "fix(web): da-vinci finish of Portfolio and Activity"`.

- [x] **Step 4: The doc sweep** (the root CLAUDE.md's mandatory doc-update table). Each item is a
  concrete edit:
  - **`web/DESIGN.md`**: under `## Components`, after **Meter**, add **Account card** (Portfolio:
    the title, the age of the reading in words with a Delayed flag word when it is older than 30
    minutes or degraded, the API's note verbatim in a pressed-sage block, then two blocks of figure
    lines side by side from 640px; a figure we do not have is a hatched n/a and a stale one says
    stale), **Name card** (Portfolio, Positions: the ticker bold with its flag words and the name's
    open P&L at the right, which is n/a when any row's is unknown; Home's rows beneath, each with a
    figure line of delta, mark and value), **Campaign thread** (symbol, a status word, the net
    premium labelled "before commissions", the legs behind a disclosure, the adjusted basis and
    realised stock P&L when assigned), **Expiry day** (the date and the days left, each contract a
    row with its status words and what happens at expiry in a sentence, an event word where a
    verified date falls before the expiry), **Month stepper** (Activity, Pay: previous, the month,
    This month, next; next stops at this month and previous at the month the system began; the month
    is a stub, always open, with "Net for the month" for a past month), **Order row**, **Fill row**
    and **Execution row** (Activity, Fills and orders: the contract bold, state words, figures in
    the stub face with n/a hatched, a labelled source on each list: "The system's record", "IBKR's
    record"; an order's sizing in words, Claude's cut in the flag tone with its reason labelled as
    Claude's), **Sizing record** (Activity, System: one line per kind of action with its counts and
    two marks in the stub face, no gain or loss colour because a positive number is what an action
    cost; unvalued is n/a, a pushed-out line has no money) and **Ledger figure lines** (the ledger's
    tiles as figure lines under a perforation, outcomes as status words, the trade detail in the
    sheet). Under **Open Decisions**, extend "A disabled quiet button" with the month stepper. Add a
    Decision Log entry dated the day of the work: Part 3 built (the operator asked for it to be
    planned with its own rulings): Portfolio's three views and Account card, Positions grouped by
    name over Home's rows with totals that never hide an n/a, Campaigns before commissions, the
    Calendar with event words; Activity's four views, Pay a month at a time with the totals, the
    curve and the legs under one set of filters, the Ledger overview in the figure face with its
    pages leading back, Fills and orders as three lists never merged, System with the sizing
    record; `/ledger` redirects into Activity; "no new colour, font, radius, elevation or token" (or
    the operator-approved exceptions). Update the marker's `updated=` date; keep `status=ratified`.
    Run `python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md` → exit 0.
  - **`web/CLAUDE.md`** (`## Layout`): replace the `portfolio/` and `activity/`/`pnl/` page entries
    with the new pages (`app/portfolio/page.tsx` mounts `<PortfolioPage/>` from `features/portfolio/`:
    the Account card, Positions, Campaigns and Calendar in `?view=`, Refresh in the header;
    `app/activity/page.tsx` mounts `<ActivityPage/>` from `features/activity/`: Pay, Ledger, Fills
    and orders and System in `?view=`, Pay's month in `?month=`); `ledger/`: `/ledger` redirects to
    `/activity?view=ledger`, the three pages keep their routes, lead back with `BackToLedger`, and
    open a trade in the Sheet; add `features/portfolio/` and `features/activity/` entries (every
    file by name and job) and `lib/useViewParam.ts` and `components/ui/field.ts`; under
    `components/portfolio/` note that `PortfolioShell`, `SummaryPanel`, `PositionsPanel`,
    `PositionGroup`, `StockLegRow`, `OptionLegRow`, `CampaignsPanel`, `CampaignThread` and
    `CalendarPanel` are no longer mounted and stay for their tests until Part 4, and that
    `RefreshControl` and `DegradedNotice` are restyled; under `components/pnl/` that `PnlShell` is
    unmounted and the rest are restyled in place under their tests; under `components/ledger/` that
    `LedgerNav` is unmounted and the rest are restyled; under `components/options/` that
    `OrdersTable` and `FillsTable` are mounted on Activity (replace the Part 2 sentence that says
    they are unmounted); under `features/home/` `PositionRowItem`; under `features/market/`
    `eventBefore`; under `features/trades/` `whenET`.
  - **`ARCHITECTURE.md`**: the `src/api/` folder guide (`routers/pnl.py` gains `GET /pnl/sizing`,
    read behind the eval fence like `/pnl/system`; `routers/ledger.py` gains
    `GET /ledger/executions`; `routers/spreads.py` gains `GET /spreads/orders`; `spreads_db.py`
    gains `try_read_spread_order_rows`; the orders routes carry `sizing` and `days`, the fills
    route names its contract); the web routes paragraph (`/portfolio`, `/activity`, the
    `/ledger` redirect and its three pages); the `web/` folder guide gains `features/portfolio/`
    and `features/activity/`. No `src/` module outside `src/api/` changed, so no other section does.
  - **`docs/web/api.md`**: `GET /options/orders` (`days`; `sizing`: the sizing actions linked to
    the order, `kind`, `deterministic_contracts`, `sent_contracts`, `reason`, empty when none);
    `GET /options/fills` (`days` up to 365; `underlying`, `strategy`, `right`, `strike`, `expiry`:
    from the order's frozen snapshot, then its candidate, null when neither is on record); then
    three sections: `GET /pnl/sizing` (owner-only; `?since=`; every field of `SizingRecordResponse`
    and `SizingGroupOut`; a positive P&L is what the held-back contracts would have earned; rows not
    yet valued count and are not valued; a `pushed_out` line carries no figures; it reads behind the
    eval fence and recomputes nothing), `GET /ledger/executions` (owner-only; `days`, `book`,
    `symbol`, `limit`; real executions only, superseded rows and statement order rows excluded;
    `quantity` signed; `truncated`) and `GET /spreads/orders` (owner-only; `days`, `limit`;
    `available: false` only when the file is missing or unreadable, an older file without the table
    answers `available: true` with no orders; the spread's fields are null when its position row is
    missing).
  - **`STATUS.md`**: a built entry "Web overhaul Part 3 — Portfolio and Activity (date)" listing
    what shipped; update the "Web overhaul (Parts 1-4)" table row and Part 2's note that the raw
    order and fill lists are unmounted until Part 3 (they are now mounted on Activity); under
    known limitations and deferred: the ladder's next-lot zone per held name, a "room left under the
    regime budget" card and a governing regime per held name are not built (each needs trading-side
    computation and its own spec); the three fills lists are never reconciled, so a fill the system
    recorded and IBKR did not (or the reverse) is visible but not flagged; an IBKR execution with a
    commission of 0 reads "none recorded" because the feed cannot tell a free execution from one
    whose commission has not arrived; lists are capped (200 orders, 500 fills, 200 executions per
    window); Activity has no strategy switcher; a working order cannot be cancelled from the web
    until Part 5; the legacy files named in ruling 12 stay for Part 4; the API must be restarted for
    the new routes and shapes (no trading-side change, so the trading service need not be).
  - **`SETUP.md`**: the web console table: positions, campaigns and the expiry calendar → Portfolio;
    the manual refresh → Portfolio, Refresh; what the system earned in a month → Activity → Pay;
    the broker-truth ledger, a statement import and a trade's notes → Activity → Ledger (import also
    from More); what was sent, filled and executed → Activity → Fills and orders; the sizing record
    and the score against outcome → Activity → System. Find the existing rows with
    `grep -n "Portfolio\|P&L\|/pnl\|/ledger\|Ledger" SETUP.md`.
  - **Root `CLAUDE.md`** (three edits, each at an anchor that occurs once):
    1. In "The spreads fence", the bullet that begins "**The web API reads `data/spreads.db` only
       through `src/api/spreads_db.py`**": change `` `GET /spreads/positions`, `GET /spreads/picks`
       and `GET /pnl/month` `` to `` `GET /spreads/positions`, `GET /spreads/picks`,
       `GET /spreads/orders` and `GET /pnl/month` ``.
    2. In "## The fence — the enrichment learning loop may not touch the deterministic layer", the
       paragraph that ends "everything `eval/` produces is read by a human, never auto-applied.":
       append the sentence "The web reads two of those human-facing reports, both display only:
       `GET /pnl/system` (the score-vs-outcome report) and `GET /pnl/sizing` (web overhaul Part 3,
       over `src/claude/eval/sizing_counterfactual.py::summarize`, recomputing nothing)."
    3. In "## The web layer and the trading database", the paragraph that begins "P3 and P4
       (portfolio, P&L, and `GET /pnl/system`'s read": append the sentence "Part 3 of the web
       overhaul (`GET /pnl/sizing`, `GET /ledger/executions`, `GET /spreads/orders`, the order
       `sizing` and fill contract fields) adds no write either: `GET /ledger/executions` only reads
       the ledger tables, and nothing in `src/ledger/` changes."
  - **`README.md`**: no change (no new Telegram command or top-level directory). Confirm and say
    so in the Progress log.

- [x] **Step 5: The full gate.** All of these, with the counts recorded:

```bash
python -m pytest -q && ruff check . && mypy src
cd web && npx vitest run && npx tsc --noEmit && npm run lint && cd ..
python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features web/components/pnl web/components/ledger web/components/portfolio web/components/options web/components/ui   # non-test files: exit 0 (legacy test titles keep their em dashes)
python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md
grep -rn "submitCommand\|confirmCommand" web/features            # only features/more/TargetCard.tsx and its test
git diff --stat main -- web/components/options/DecideControls.tsx web/components/options/ConfirmAction.tsx \
  web/components/options/CommandReceipt.tsx web/components/options/HaltControl.tsx \
  web/components/options/AutonomyControl.tsx web/components/options/RollModeControl.tsx \
  web/lib/commands.ts web/lib/receipt.ts                          # prints nothing
```

and the scratch-copy `next build` from C2. Expected: pytest = baseline + 30 (10 + 9 + 11); vitest
green with every new test; everything else clean.

- [x] **Step 6: Commit the docs, then the Progress log**

```bash
git add web/DESIGN.md web/CLAUDE.md ARCHITECTURE.md STATUS.md SETUP.md CLAUDE.md docs/web/api.md
git commit -m "docs: web overhaul Part 3 - Portfolio, Activity, the sizing record, the audit lists"
```

Fill in the Task 15 row (both commits, the gate counts, the screenshots taken, every ruling and
finish fix) and commit the plan file:
`git commit -am "docs(plan): web overhaul Part 3 Progress log"` (only the plan file is modified at
this point; check `git status` first).

- [ ] **Step 7: Hand off.** Run the whole-branch review on the most capable model (opus):
  superpowers:requesting-code-review over `main..HEAD`, with this plan, `web/DESIGN.md` and the
  Review Focus above as its brief. Fix what it finds as one review fix pass (a commit, a Progress
  log line). Then superpowers:finishing-a-development-branch (no merge or push without the
  operator). Tell the operator that the **API** needs a restart before the new routes and shapes
  appear (`GET /pnl/sizing`, `GET /ledger/executions`, `GET /spreads/orders`, the order `sizing`
  and the fill contract fields). `./ibkr restart` is the command: it stops and starts the whole
  supervised stack, since there is no API-only restart. Only the API's code changed, so the
  trading service, the scan loop and the monitor come back on the same behaviour. Processes do
  not hot-reload, so after the restart check with `ps -eo lstart,command | grep run_` that the
  API started after the merge. Until then the console degrades gracefully: an order with no
  `sizing` field shows no sizing words, a fill with no contract says "Contract not on record".

---

## Self-review (run by the plan's author, 2026-10-23)

- **Spec coverage.** Roadmap Part 3, as the operator revised it on 2026-10-19:
  - Portfolio: Positions, Campaigns and the Expiry calendar on the new rows (Tasks 4–7); the
    `Propose a roll` move was done in Part 2 (the position page), so Portfolio's rows link there;
  - Activity: Pay (the P&L summary and the equity curve, Tasks 8–9), Ledger (Tasks 10–11), Fills
    and orders (Task 12) and System (Task 13), with the ledger tables in the figure face;
  - "Fills and orders" as the raw list for auditing, every fill and every order (Working, All,
    Rejected) in every book: the system's orders and fills, the credit-spread book's fills and
    IBKR's own executions (Tasks 2, 3, 12), `OrdersTable` and `FillsTable` restyled and mounted;
  - "Trades → History tells each trade's story; one sentence on each page links to the other":
    **not built here**, and said so: Part 2's History links each card to its detail page, and the
    Fills and orders page names where the story lives in its source lines. A link in each direction
    is a one-sentence follow-up if the operator wants it, and is listed in `STATUS.md`.
  - The market-picture additions where relevant: the name flags and event words (Tasks 5–6), the
    sizing words on an order (Tasks 2 and 12) and the sizing record (Tasks 1 and 13).
  - DESIGN.md's Portfolio and Activity surfaces are written in Task 4 and built in Tasks 4–14.
- **Placeholders.** None: every code step carries its code or the exact replacements, and the doc
  sweep names each edit.
- **Type consistency.**
  - `useViewParam(views, fallback)` (Task 4) is what Tasks 7 and 14 call.
  - `PositionRowItem({ row, flags?, detail? })` (Task 5) is what Home's card and Portfolio mount.
  - `FIELD` / `FIELD_LABEL` (Task 6) are what Tasks 6, 9, 11 and 13 import.
  - `useLegFilters()` and `useEquity(qs)` (Task 8) are what Task 9 builds on; `LegsFilters` and
    `LegsCard` (Task 9) are what `PayView` composes.
  - `whenET` (Task 12) is what `OrdersTable`, `FillsTable`, `ExecutionsList` and `SpreadFills` use.
  - The generated types `SizingGroupOut`, `SizingRecordResponse`, `LedgerExecutionRowOut`,
    `LedgerExecutionsResponse`, `SpreadOrderOut` and `SpreadOrdersResponse` are checked against the
    contract by B3.
  - `WindowControls` and `SystemPanel`'s `windowControls` prop (Task 13) are what `SystemView` uses.
- **Review Focus.** Each of the nine lines names the test that pins it, in the task that owns the
  code.
- **Proportion.** The plan is long because the operator's two earlier plans are, and because every
  restyle of a legacy component is given as exact replacements under that component's existing
  tests, which are the proof the restyle changed no behaviour. Nothing here is a guess about what
  the code looks like: each legacy file was read before its replacement was written.


## Re-verification (2026-10-28, before execution)

- **What was checked.** Every task's text was applied as written (whole files from their blocks,
  insertions at the named anchors) to a scratch worktree of `main` at c692a1b, with the gates the
  tasks name run after each one: Section A's pytest, fences, ruff, mypy and the regenerated
  contract; each web task's vitest scope, `tsc`, eslint and the da-vinci lint; then the full suites
  and a scratch-copy `next build`. Results are in the Progress log's "Plan re-verified" row.
- **What had moved under the plan.** Only f4af002's `partial` rule touched code the plan replaces
  (Task 2's `list_orders`); it is now kept and pinned by a test. f4af002's USD-only account value
  and c692a1b's research chart refresh touch nothing the plan writes. Every other anchor (the
  DESIGN.md surface entries, `PositionsCard`'s row, the ledger and P&L components, the router
  import lists, `next.config.ts`, the More page) still occurs exactly once as the plan quotes it.
- **Execution.** Each section is sized for one Sonnet subagent at xhigh, with the next section's
  entry checks run between sections as "How a section runs" says; the whole-branch review stays
  on Opus.
