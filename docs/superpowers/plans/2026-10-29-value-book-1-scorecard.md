# Value Book, Part 1: The Scorecard and the Calibration Dry Run — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan **section by section** (one subagent per section, never per task — see "Execution model"). Every section opens with **entry checks** the orchestrator runs itself before it spawns the section's subagent. Each section carries a **model label**. No section of Part 1 touches `web/`; if one ever does, its subagent invokes the `da-vinci` skill first and its prompt says so. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Stage 1's deterministic scorecard for the value book — config, point-in-time
filings, the input loader, the data-quality and health gates (operating, cyclical, bank and
insurer sets), valuation methods A/B/D and justified P/TBV, the two lists' entry rules, timing,
the baseline verdict, the rank score and the ticker file in `data/value.db` — then run the
calibration dry run over the S&P 500 and the operator's lists, and freeze `value_rules: v1`
once the operator has read the pass funnel.

**Architecture:** `src/value/` is a new deterministic package and the only writer of
`data/value.db` (its own `ValueBase`, the `src/spreads/store.py` pattern). Its scorecard is a pure
function: `build_scorecard(ValueInputs, ValueCfg) -> ValueScorecard`, no I/O, so Part 6's API can
compute a ticker file during a request. Inputs come from one neutral, read-only loader,
`src/common/value_inputs.py` (`research.db` opened `mode=ro`, the regime through
`src.storage.regime_state.load_regime_state`, technicals from `src/analytics/technicals.py`),
whose plain shapes live in `src/common/value_types.py`. The research worker owns every SEC and
price fetch: `select_periods` gains `as_of`, a new `select_ttm` adds trailing twelve months, the
concept map gains the value line items, `drain_ingest_jobs` gains a `prices` job kind and the
worker a (default-off) nightly value sweep. `scripts/value_dry_run.py` backfills a database copy
and prints the funnel. Nothing in Part 1 can place, size or gate an order, and nothing on the
trading path imports `src.value` (a fence test says so).

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 (SQLite, WAL; `mode=ro` URIs), pandas,
httpx + the standard-library `html.parser` (snapshot builder only), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` (revisions 1–3, §19 and
§20 record the operator's decisions; §14: no open decisions). Part 1 implements §6.0–§6.7, §6.8's
rank score and ruleset fingerprint, §6.9's Part 1 of the ticker file, §16's fence and unit tests
for what Part 1 builds, §17's calibration dry run and §18's docs for Part 1. Executors read the
spec sections each section cites, not the whole spec.

## Execution model

| Section | Tasks | Model | Why this model |
|---|---|---|---|
| **A — Foundations** | 1–4 | **sonnet** | Config wiring, two small additions to `concepts.py`, the loader and the universes. Every line of code and every test is given; the risk is wiring, which the targeted gates catch. |
| **B — The scorecard** | 5–9 | **sonnet** | Pure functions with every formula given in full and every expected number pinned in a test (computed by the plan's author against a working prototype). |
| **C — Ticker file, rank, dry-run tooling, fences, docs** | 10–14 | **sonnet** | Storage on the established separate-Base pattern, the ast fence on `tests/test_spreads_fence.py`'s parser, a script with an end-to-end test, and a doc sweep given as text. |
| **Whole-branch review** | after C | **opus**, then one **sonnet** fix pass | One review of the whole branch; Critical/Important findings fixed in one pass. No per-task reviews. |
| **D — Calibration dry run and the freeze** | 15–16 | **the orchestrator itself (sonnet), with the operator** | Runs scripts against database copies and puts numbers in front of the operator; the freeze applies the operator's decisions. No subagent. |

**How the orchestrator runs a section (the main session, Sonnet):**

1. Run the section's **entry checks** itself, in order, from the worktree. Any check fails →
   stop, report the failing command and its output, and do not spawn. A failure that belongs to
   the previous section is fixed there first (reopen its last task, record the ruling).
2. All pass → add a "Section X entry" row to the Progress log (gate result, date).
3. Spawn **one subagent for the whole section** on the labelled model, with this prompt (fill
   the brackets):

   > You are executing Section [X] of `docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md`
   > in the git worktree `.claude/worktrees/value-book-1` (branch `feat/value-book-1`). Read, in
   > this order: the plan's "Rulings made up front", "Global Constraints" and Section [X] in full;
   > the spec sections Section [X] cites; and only the files its tasks list. Do the tasks in order,
   > TDD as written: each failing test first, then the code, then the gates the task names. One
   > commit per task, message ending `Co-Authored-By: <your model name> <noreply@anthropic.com>`.
   > After each task tick its checkboxes and fill its Progress-log row (status, commit, gate
   > counts, date, every ruling with its cost-if-wrong) and commit that with the next task (the
   > last task's row goes in a final `docs(plan)` commit). Never import a `scripts.run_*` module;
   > never touch `data/*.db` of the main checkout; never edit a private `config/*.yaml`. If an
   > entry-check fact turns out false mid-task, stop and report instead of improvising. [If the
   > section touches `web/`: invoke the `da-vinci` skill before any UI code.] Report: commits,
   > gate counts, rulings, anything left undone.

4. When the subagent reports, **verify it yourself** before anything else: `git log --oneline
   main..HEAD` (the commit count the section exit names), `git status --short` (clean), the
   section exit's gate command and its counts, and the protected-file diff (Global Constraints).
5. **Stop and ask the operator** whether to continue to the next section or stop here. Never
   start the next section without that answer.

After Section C: spawn **one opus subagent** for a whole-branch review (superpowers:requesting-
code-review; prompt: the plan, the spec §§6, 16, 17, and `git diff main...HEAD`), then **one
sonnet subagent** that fixes every Critical and Important finding in one commit, then ask the
operator before Section D. **Ask the operator before merging or pushing**, after Section D.

**Commits.** Each task is one commit; Task 1's commit also adds the spec and this plan file. The
review fix pass adds one commit; record it in the Progress log. Every commit message ends with
the trailer `Co-Authored-By: <model> <noreply@anthropic.com>`, where `<model>` is the executing
agent's own model name (a Sonnet executor writes its Sonnet name; an Opus one writes
`Claude Opus 5.5`).

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **A entry checks** | done | (none) | A0–A5 pass; baseline pytest 4996 passed + 1 skipped (4997 collected), ruff clean, mypy clean (297 files). A3 anchors all at the stated lines | 2026-10-29 | Ruling: pytest must run from the worktree root — run from the main checkout's cwd it shows 4 spurious failures (ledger wiring, openapi, web fence). Cost if wrong: none |
| 1 Config, ruleset fingerprint, package | done | de09566 | `tests/test_value_config.py` 9 passed; with `test_private_config.py` + `test_spreads_config.py` 38 passed; ruff check/format clean, mypy clean (3 files) | 2026-10-29 | Ruling: the doc-update trigger table (new module, new config key) is deferred to Task 14 as the plan schedules it, not done per task. Cost if wrong: none (Task 14 sweeps ARCHITECTURE/SETUP/STATUS/CLAUDE) |
| 2 Point in time: `as_of`, `select_ttm`, the concept map | done | 6f5ea05 | periods+concepts+units+materialize 45 passed (periods 17, concepts 11 as the plan expected); ruff check/format clean; mypy src/research clean (31 files) | 2026-10-29 | Ruling: the source edits (`select_periods(as_of)`, `select_ttm`, `TtmValue`) were applied before the new tests were first run, so only the concept-map test was observed red (the yaml came last); the periods tests were green on first run. Cost if wrong: none (the tests pin both as_of directions and TTM bases) |
| 3 Value inputs: types and the read-only loader | done | c463698 | `tests/test_value_inputs.py` 11 passed; ruff check/format clean; mypy clean (2 files) | 2026-10-29 | Ruling: tests and code were written together and first run together (11 green at once), so no red run was observed; the tests carry the plan's pinned numbers verbatim. Cost if wrong: none |
| 4 Universes, snapshots, the research worker's jobs | done | dfb76b6 | `test_value_universe.py` 10 + `test_research_materialize.py` + `test_research_worker.py` = 29 passed; ruff check/format clean; mypy clean (33 files). Snapshot run printed `S&P 500: 503 rows; S&P 100: 101 rows; as of 2026-10-29`. **Section A exit gate:** pytest 5034 passed + 1 skipped (baseline 4996 + 38), ruff check . clean, mypy src clean (303 files); protected-file diff empty | 2026-10-29 | Ruling: tests and code written together, first full run green (no red run observed). Ruling: Tasks 3-4's plan checkboxes and Tasks 2-3's log rows ride the following task's commit as the plan says; Task 4's row and ticks are this final `docs(plan)` commit, so the branch is 4 task commits + 1 docs commit = 5 ahead of main (the plan's exit text says 4; the extra commit is the one the section prompt requires). Cost if wrong: none |
| **B entry checks** | done | (none) | B1–B4 pass; Section A exit re-verified by the orchestrator: pytest 5034 passed + 1 skipped, ruff clean, mypy clean (303 files), protected-file diff empty | 2026-10-29 | Ruling: Section A left 5 commits ahead of main (4 task commits + 1 `docs(plan)`), so B1's "prints 4" and B's exit "9 in all" become 5 and 11 (B adds 5 task commits + 1 final `docs(plan)` commit for Task 9's row; the B entry row rides Task 5's commit). Cost if wrong: none |
| 5 Schemas, per-year metrics, test fixtures | done | 157c174 | test_value_metrics.py 8 passed; ruff check/format clean; mypy src/value clean (4 files) | 2026-10-29 | Ruling: code blocks were extracted verbatim from the plan and tests run together, so no red run was observed (8 green at once). Cost if wrong: none |
| 6 Piotroski, Altman, Beneish | done | 56fda13 | test_value_scores.py 7 passed; ruff check/format clean; mypy src/value clean (5 files) | 2026-10-29 | Ruling: code extracted verbatim from the plan; tests green on first run, no red run observed. Cost if wrong: none |
| 7 Classification, data quality, health gates | done | 4a3e95b | test_value_gates.py 28 passed; ruff check/format clean; mypy src/value clean (6 files) | 2026-10-29 | Ruling: code extracted verbatim; tests green on first run, no red run observed. Cost if wrong: none |
| 8 Valuation: A, B, C, D, P/TBV | done | 7171170 | test_value_valuation.py 10 passed; ruff check/format clean; mypy src/value clean (7 files) | 2026-10-29 | Ruling: code extracted verbatim; tests green on first run, no red run observed. Cost if wrong: none |
| 9 Timing and the scorecard | done | e5af279 | test_value_scorecard.py 24 passed; all tests/test_value_*.py 107 passed. **Section B exit gate:** pytest 5111 passed + 1 skipped (baseline 4996 + 115), ruff check . clean, mypy src clean (310 files); protected-file diff empty | 2026-10-29 | Ruling: code extracted verbatim; no red run observed, every pinned number matched first time. Ruling: the section prompt's 'baseline-plus-115 = 5034 + 115 = 5149' double-counted Section A; the 115 new tests (8+7+28+10+24 = 77 in B, plus A's 38) are relative to the 4996 baseline, so the exit count is 5111 (5034 + 77). Branch is 5 (A) + 5 task commits + 1 docs commit = 11 ahead of main. Cost if wrong: none |
| **C entry checks** | done | (none) | C1–C4 pass; Section B exit re-verified by the orchestrator: 11 commits ahead of main, pytest 5111 passed + 1 skipped, ruff clean, mypy clean (310 files), protected-file diff empty, 77 new Section B tests | 2026-10-29 | Ruling: C3's grep matches the word "yfinance" in a `detail=` string (gates.py:128, :140) and a comment (timing.py:35) — no import, no I/O, so the scorecard is still pure. Ruling: counts shift by Section A/B's extra `docs(plan)` commits — C1's "prints 9" is 11, C's exit "14 in all" is 17 (5 task commits + 1 final `docs(plan)`), and C's pytest target is baseline 4996 + 141 = 5137. The C entry row rides Task 10's commit. Cost if wrong: none |
| 10 Rank score and the relative-strength line | done | f73a288 | test_value_rank.py 5 passed; ruff check/format clean; mypy src/value/rank.py clean | 2026-10-29 | Ruling: code and tests extracted verbatim from the plan and run together, so no red run was observed (5 green at once, pinned numbers matched). Cost if wrong: none |
| 11 `value.db` and the ticker file | done | 0c98576 | test_value_store.py 6 passed; ruff check/format clean; mypy src/value clean (12 files) | 2026-10-29 | Ruling: code and tests extracted verbatim and run together; no red run observed (6 green at once, the pinned fair value 46.853626592284414 matched). Cost if wrong: none |
| 12 Funnel and fences | done | 7f62b32 | test_value_funnel.py 2 + test_value_fence.py 10 + the five other fence suites (spreads, regime, news, web, eval_skills) = 72 passed; ruff check/format clean; mypy src/value clean (12 files) | 2026-10-29 | Ruling: code and tests extracted verbatim and run together, so the red run (funnel/fence failing before funnel.py existed) was not observed; Step 2's note that the other fence tests pass already was therefore not re-observed, but all 10 fence tests pass now, so Tasks 1-11 sit inside the fence. Ruling: `mypy tests/value_fixtures.py` reports a pre-existing arg-type error at line 83 (Task 5's fixture); the gate is `mypy src`, which tests are outside, so left alone. Cost if wrong: none |
| 13 The dry-run script | done | 57aa539 | test_value_dry_run.py 3 passed; ruff check clean, ruff format clean (after one blank line in the appended fixture); mypy scripts/value_dry_run.py clean; py_compile of both scripts silent | 2026-10-29 | Ruling: code and tests extracted verbatim and run together; no red run observed (3 green at once). Ruling: the appended `companyfacts` fixture needed a second blank line before it for ruff format; nothing else changed. Cost if wrong: none |
| 14 Docs | pending | | | | |
| **Whole-branch review (opus)** | pending | | | | |
| **Review fix pass (sonnet)** | pending | | | | |
| **D entry checks** | pending | (none) | | | |
| 15 Calibration dry run (orchestrator + operator) | pending | | | | |
| 16 The freeze: `value_rules: v1` | pending | | | | |

## Roadmap (this plan is Part 1 of 6)

Each later part is written **after the previous part merges**, so its code matches reality.
Every part runs on this plan's execution model (Sonnet orchestrator, one subagent per section,
stop-and-ask between sections, one Opus whole-branch review).

- **Part 1 — The scorecard and the calibration dry run.** This plan. Spec §6.0–§6.7, §6.8 (rank
  score, ruleset fingerprint), §6.9 Part 1 storage, §16 (Part-1 tests), §17, §18 (Part-1 docs).
- **Part 2 — The value process and the shadow record.** `scripts/run_value.py` (no IBKR; nightly
  scoring of both universes; `value_runs`; the follow window; session history rows; registered in
  `./ibkr`; `research_sweep.enabled: true`), earnings dates from `news.db` as plain data, the
  shadow ledger `value_shadow` (Claude and baseline tracks — the baseline track only until Part 4;
  control groups; evidence-universe entries; returns at 21/63/126 sessions and at exit, against
  SPY), the ranked monthly record (top/bottom tenth and whole universe per list), the exit engine
  as a state machine with the three policies (`full`, `value`, `hold12`) and `scripts/value_report.py`.
  Spec §6.8, §7 (not §7.1), §11's postmortem, §12's measurement. Depends on Part 1's frozen v1.
  Models: sonnet sections, opus review (the exit engine is the riskiest logic).
- **Part 3 — Re-evaluation and Stage 1b.** The research worker's `submissions/CIK*.json` job kind
  (new accessions, 8-K item tags), the sector-ETF residual model, the eight §7.1 triggers with
  debounce and severity, `value_reevaluations`, the original-plan shadow twin, and the mandatory
  point-in-time backtest of Python's rules (Stage 1b) over `as_of` dates with the survivorship
  caveat printed. Spec §7.1, §8.5 (submissions feed only), §12 (Stage 1b). Depends on Part 2.
  *(The suggested roadmap put §7.1 and Stage 1b inside Part 2; they are split out because the submissions
  feed and the residual model are a cohesive research-worker + statistics unit, and Part 2 is
  already the largest part. Cost if wrong: one more plan to write and review.)*
- **Part 4 — Stage 2: Claude as the analyst.** `src/value_ai/` (bounded drivers, prompts and
  schema, `validated_items_call`), `src/value/claude_valuation.py` (Python computes and clamps at
  1.5×), `src/value/grounding.py`, `value_claude_verdicts` and the Part 2 tables, the breaker,
  model routing per call kind and budgets, `src/common/value_text.py` (`VALUE NOTE`), the
  `.claude/skills/value/` skill, and the Claude track in the shadow ledger. Spec §8, §6.7's
  effective verdict, §18's core-invariant exception text. Depends on Parts 2–3.
- **Part 5 — Stage 3: money (paper).** Pot arithmetic and `books.value_liquidity_claim`, the
  `resolve_caps` change, the gross and combined caps, `src/value/risk.py::validate`,
  `src/value/executor.py` on clientId 31 with `orderRef = "value:<lot_id>"`, `ParsedExecution.
  order_ref` and ledger tagging, value approvals in `value.db` with `value_approve` /
  `value_reject` intents, W/V share attribution with fail-closed reads, wheel-only cost basis,
  the sell cap, the seven fault drills, and the put flow (`promote` refusing
  `above_value_ceiling`). Spec §9, §11, §13, §16 revision-3 tests. Depends on Part 4 (the gate
  reads `value_claude_verdicts`). Models: opus for the Rules-Engine and attribution sections.
- **Part 6 — Web and Telegram.** `src/api/value_db.py` (read-only), the `value_snapshot` intent
  carrying its fingerprint, fresh-on-search inside the materialisation budget, the Research
  strip (Deep value / Quality growth), the rebuilt stock page, the Home Value card and the
  `value` kind across Home, `/value`, `/value NAME`, `/value NAME analyse`, proposal and
  re-evaluation cards in `TELEGRAM_THREAD_VALUE`. Spec §6.9 (API path), §10. Every UI task
  invokes da-vinci. *(Could move ahead of Part 4 if the operator wants to see the strip on
  Python's baseline first; it depends only on Part 2's nightly files.)*

## Rulings made up front (the operator may overturn any of them)

Every ruling below was checked against the code at `main` `e2bf506` and, where it touches
filings, against real companyfacts payloads (BAC, JPM, TRV, GOOGL, META, MU, AAPL, NVDA, AMD,
HOOD) fetched on 2026-10-29. "Cost if wrong" is what reversing it would take.

**Spec points the code contradicts, and how this plan handles them**

1. **"`select_periods(as_of)` returns the value *first filed* on or before that date."** Read
   as: only facts filed on or before `as_of` exist, and among them the latest filed wins. A
   restatement filed *after* `as_of` never leaks (the spec's purpose, §6.2); one filed *before* it
   was public that day and is used. Taking the earliest-filed fact would ignore known
   restatements. Task 2's tests pin both directions. *Cost if wrong: one comparison flips.*
2. **10-Q cash-flow facts are year-to-date, not quarters**, so TTM cannot be four summed
   quarters. New `select_ttm`: latest fiscal year + current YTD − prior-year YTD; the fiscal year
   alone (`basis="fy"`) when no YTD or comparative exists. *Cost if wrong: none found.*
3. **CET1 is not tagged in companyfacts** for BAC or JPM (checked: no `CommonEquityTierOne*`
   concept with data). The spec's rule ("from XBRL where tagged, otherwise UNKNOWN — never a
   silent pass") therefore makes **every bank's health UNKNOWN**. Built as written behind
   `rules.banks.require_cet1: true`; Task 15 puts the choice to the operator (keep, or set
   `false`, which marks the check `not_applicable` "disabled by config"). *Cost if wrong: a
   config value.*
4. **No cover-page share count for multi-class filers.** `dei:EntityCommonStockSharesOutstanding`
   is absent for META, GOOGL and HOOD (dimensional facts are dropped from companyfacts), and
   GOOGL tags undimensioned weighted diluted shares only from FY2022. EDGAR shares for the
   market-cap check: cover count → newest balance-sheet `CommonStockSharesOutstanding` (new line
   item `shares_outstanding`) → newest weighted diluted (quarterly, then annual). Per-year shares:
   weighted diluted, else year-end `shares_outstanding`. *Cost if wrong: the fallback order.*
5. **Splits break per-share history** (GOOGL 20:1, NVDA 4:1 and 10:1 show up inside eleven
   years because an old year's last filing predates the split). `normalise_shares` walks newest
   to oldest; a ratio ≥ 1.8 (either way) within 5% of a split factor (1.5, 2–8, 10, 15, 20, 25,
   30, 40, 50) rescales every older year and is recorded in `adjustments`; any other jump is
   `dq.share_continuity` UNKNOWN. An acquisition below 1.8× is left alone; one at ~2× would be
   misread as a split (accepted). *Cost if wrong: one table of factors.*
6. **Interest expense changes concept or stops.** GOOGL and META stop tagging `InterestExpense`
   (2024/2023) for `InterestExpenseNonoperating`; Apple stops after FY2023. The concept map pools
   both aliases; with none tagged, net cash passes coverage and net debt gets an **implied**
   coverage = EBIT / (gross debt × `health.assumed_interest_rate` 8%), labelled implied. A TTM or
   latest item ending more than `data_quality.stale_item_days` (200) before the newest one is
   dropped (BAC's `InterestExpense` ends 2024-03). *Cost if wrong: one fallback and one key.*
7. **"6-month relative strength not in the bottom 30%" is cross-sectional**, so it cannot live
   inside a per-name pure function. The run computes `rs_cutoff(..., 30)` (the 30th percentile of
   6-month return less SPY's, linear interpolation, None below 10 names) and hands it to every
   name's `ValueInputs.rs_cutoff_6m`, as market data. *Cost if wrong: none (same rule).*
8. **yfinance returns the last report date until the next is announced.** A past date no more
   than `timing.recent_report_days` (70) ago passes the earnings window ("inferred: reported N
   days ago"): the next report is a quarter away. Older past dates stay UNKNOWN (§6.6's "never a
   pass" on a missing date). *Cost if wrong: META-like names read UNKNOWN timing for a few weeks
   after each report.*
9. **`AMD` tags no `Liabilities` total.** Total liabilities fall back to assets − equity.

**Builder's calls the spec left open (§17)**

10. **The concept map is shared.** The 23 value line items go into `config/research_concepts.yaml`
    (one map; §6.9 reads financials "through `select_periods`"). The research page's
    `financials` table gains rows; `web/components/stock/StatementsTable.tsx` renders a fixed
    `ROWS` list, so nothing visible changes.
11. **Classification:** the snapshot's GICS sub-industry, else yfinance's `industry`. Banks =
    Diversified Banks, Regional Banks (and yfinance's `Banks - *`); insurers = the four GICS
    insurance sub-industries (and yfinance `Insurance - *`). Brokers, custody banks, consumer
    finance and exchanges are operating companies, as the spec's wording has it. REIT = "REIT" in
    the industry. Cyclical = an industry on `classification.cyclical_industries`, or a 5-year
    FCF-margin population standard deviation above 8 points. All lists are config.
12. **Order of the card:** ETF (`not_applicable`) → data quality (UNKNOWN) → REIT / pre-profit
    (`not_applicable`) → health. Pre-profit = a net loss in ≥ 3 of the last 5 fiscal years; the
    spec's "biotech" is read as pre-profit biotech, so profitable biotechs are scored.
13. **A health gate UNKNOWN with none FAILED makes the list verdict UNKNOWN** (never READY, never
    NO): the spec defines UNKNOWN for data quality only; this extends it to untagged health data.
14. **Cyclicals:** coverage also uses 5-year median EBIT (the spec names FCF, profitability and
    net debt / EBITDA; MU at a trough would otherwise fail coverage when cheapest), and the
    cyclical FCF normalisation (5-year median margin × TTM revenue) applies to every FCF base
    (A, B and D).
15. **Realised growth** = CAGR of plain FCF per share (operating cash flow − capex, split-
    normalised) over up to five years, minimum a four-year span (five annual periods, the data-
    quality floor). The spec's GOOGL example ("14% realised") is this measure (13.6% on the
    2026-10 payload). B's growth = 0.7 × realised capped at 15%; a negative realised rate is not
    haircut upward.
16. **The DCF:** year 1 grows at g, fading linearly to 2.5% in year 10; terminal = year-10 cash ×
    1.025 / (r − 0.025). This reproduces the spec's GOOGL figures exactly ($101.33 at r 9% full
    SBC; $150.52 at r 8% half SBC) — Task 8 pins both.
17. **Justified P/TBV:** g = terminal growth (2.5%), r = the deep-value rate (9%), ROTE = the
    5-year median of net income to common over *average* tangible common equity (equity −
    goodwill − intangibles − preferred), tangible book from the newest balance sheet over the
    newest weighted diluted count.
18. **Scores:** Piotroski uses beginning-of-year assets; "leverage fell" also scores a company
    with no long-term debt in either year; more than 2 missing components → None. Altman is the
    original Z with MVE = EDGAR market cap, strictly above 1.8. Beneish requires DSRI, GMI, SGI
    and TATA; AQI, DEPI, SGAI and LVGI fall back to a neutral 1.0 and are listed.
19. **ROIC** = EBIT × (1 − t) / (equity + debt − cash) at year end; t = tax / pre-tax clamped to
    [0, 35%], 21% when unusable. Gross-margin stability = population standard deviation of the
    last five gross margins. Untagged SBC counts as 0 in normalised FCF; untagged D&A makes
    EBITDA = EBIT (errs toward failing net debt / EBITDA). Debt = long-term + current portion +
    commercial paper + short-term borrowings (may double-count CP for a filer whose `DebtCurrent`
    includes it — errs strict).
20. **Timing details:** sessions = weekdays (holidays unknown; errs by a day or two). "Stopped
    falling" = a close above its own 20-day SMA after the lowest close of the last 63 sessions.
    "New 52-week low" = the lowest close of 252 sessions was set within the last 5.
21. **Regime** = SPY's effective regime; none recorded → normal (as `src/regime/context.py`
    does), with `"unknown"` in the fingerprint.
22. **Lists:** deep value holds every healthy name; quality growth holds operating and cyclical
    names (banks and insurers are deep value only), with the entry rule as a gate. A name that
    qualifies for both is filed on the list with the higher rank score; ties go to deep value.
23. **Rank score:** percentiles with averaged ties (lowest 0, highest 1, a lone value 0.5). Value
    = margin-of-safety percentile among names with a fair value, else normalised-FCF-yield
    percentile. Quality = mean of component percentiles: F-score, 5-year median ROIC, negated
    gross-margin stdev (+ revenue CAGR on the growth list); banks/insurers: ROTE median, negated
    ROTE stdev. Population: data quality pass, not `not_applicable`, on that list.
24. **`value.db` (Part 1):** `value_ticker_files` (latest, one row per symbol),
    `value_ticker_history` (a full row whenever a verdict, a fair value by > 1%, a 5-point
    margin-of-safety band, or any data-quality / health / entry / timing state changes; a compact
    row once per `as_of` otherwise), `value_runs`. Naive-UTC timestamps.
25. **Fingerprint** = newest accession and filing date among mapped facts, price-bar date and
    close, regime, ruleset version and hash; `key()` = sha256[:16] of its JSON.
26. **Ruleset fingerprint** = `ruleset_version` + sha256[:12] of the canonical JSON of the
    `rules:` block only (non-rule keys never move it). `src/value/ruleset.py::FROZEN` pins a
    version's hash at the freeze; a mismatch raises.
27. **Config:** `config/value.yaml` is private (added to `PRIVATE_CONFIG_FILES` and
    `.gitignore`), `config/examples/value.yaml` is committed and equals the model defaults
    (tested). Every value model forbids unknown keys. `research_sweep.enabled: false` until
    Part 2 has a consumer.
28. **Snapshots** come from Wikipedia's MediaWiki parse API (the plain page and a contact-less
    User-Agent both get 403; the UA carries the operator's public GitHub URL). Class tickers are
    dashed (BRK-B). GOOG, FOX and NWS are scored once under GOOGL, FOXA and NWSA.
29. **ETFs** = `universe.yaml` `indexes` ∪ `leveraged_etfs`, yfinance `quoteType == "ETF"`, or
    `SymbolRow.is_etf` → `not_applicable`.
30. **Market facts** (yfinance market cap, sector, industry, next earnings) are fetched by the
    caller through `src/data`, never by `src/value`. Earnings: `news.db` first (spec §6.6),
    yfinance's calendar as the fallback.
31. **The research worker** gets a `prices` job kind in `drain_ingest_jobs` and a `value_sweep`
    cron job (behind `research_sweep.enabled`) that queues `fundamentals` when a raw payload is
    missing or older than a day and `prices` when bars are fewer than 260 or 4+ days stale.
32. **The dry run runs inside the worktree on `sqlite3 .backup` copies** of `research.db`,
    `income_system.db` (for the regime) and `news.db` (for earnings dates), with
    `--env-file` pointing at the main checkout's `.env` (for `SEC_CONTACT_EMAIL`) and
    `--universe-file` at the operator's private `config/universe.yaml` (read only).
33. **Method C is absent** in Part 1 (it needs ten years of point-in-time prices; the spec says
    absent until then). Deep value is median(A, B); quality growth is D alone.
34. **A margin of safety above 60%** sets `mos_review` on the list evaluation only; the Stage 3
    gate that acts on it is Part 5.
35. **Execution:** the Opus whole-branch review runs after Section C, the last section that
    writes product code, so the operator reads dry-run numbers from reviewed code; Section D is
    the orchestrator's with the operator. *Cost if wrong: the review does not see Task 16's
    commit, which changes config values and one pinned hash.*

**Heads-up from the prototype run on real 2026-10 payloads** (not decisions; Task 15 shows the
real numbers): GOOGL's TTM FCF is ~$53B (≈ $132B capex), so D ≈ $94 against a ~$320 price;
META's D ≈ $376 against ~$620; BAC's P/TBV ≈ $51 against ~$51 (WAIT, and UNKNOWN until CET1 is
settled); NVDA and MU fail Beneish (sales growth drives SGI) and NVDA fails Piotroski; AMD fails
dilution (Xilinx); TRV fails ROTE stability (4.4 points). These are the gates doing what they
say; the operator decides at Task 15 whether any threshold refuses everything or nothing.

## Global Constraints

- **The core invariant holds unchanged:** nothing in Part 1 can place, size or gate an order.
  `src/engine/`, `src/execution/`, `src/strategies/`, `src/orchestrator/`, `src/monitor/`,
  `src/notify/`, `src/spreads/`, `src/news/` and `src/claude/` never import `src.value`.
- `src/value/` imports nothing from `src.claude`, `src.news`, `src.value_ai`, `src.spreads*`,
  `src.notify`, `src.api`, the trading path, `src.ledger`, `src.reporting` or the enrichment
  analytics; from `src.research` only `src.research.ingest.concepts` and `src.research.schemas`.
  `src/common/value_inputs.py`, `value_types.py` and `value_universe.py` import no enrichment and
  no `src.value`. (Spec §16; Task 12's fence tests.)
- The pure modules (`schemas`, `metrics`, `scores`, `gates`, `valuation`, `timing`, `scorecard`,
  `rank`, `funnel`, `ruleset`) do no I/O: no SQLAlchemy, HTTP, yfinance, `src.data`,
  `src.storage`, `open()`.
- Only `src/value/` constructs `value.db` rows. The research worker owns every SEC and price
  fetch; `src/value/` opens no SEC client.
- **Unknown is never zero.** A missing figure is `None` and a check that needs it says
  `unknown` with a reason — except where a ruling above names a fallback.
- Money in dollars, shares in shares, per-share in dollars; percentages in config are percent
  (25.0), fractions in code are fractions (0.25); every conversion is explicit.
- **Never import `scripts.run_*`.** Check scripts with `.venv/bin/python -m py_compile`. Never
  open the main checkout's `data/*.db` for writing; Section D works on `.backup` copies inside the
  worktree.
- Worktree Bash: plain single commands, absolute paths; no heredocs, no `cd x && …`.
- New config keys go into `config/examples/value.yaml` with a code default; the operator's
  private `config/*.yaml` is never edited (operator to-dos at the end).
- **Protected files** (diff against `main` must be empty at every section exit):
  `src/engine/risk_engine.py`, `src/engine/capital.py`, `src/execution/`, `src/strategies/`,
  `src/notify/`, `src/orchestrator/`, `src/spreads/`, `src/api/`, `web/`, `config/settings.yaml`
  etc. (every private config). Check: `git diff --stat main...HEAD -- src/engine src/execution
  src/strategies src/notify src/orchestrator src/spreads src/api web` prints nothing.
- Per-task gate: the task's test files + `.venv/bin/ruff check <touched paths>` +
  `.venv/bin/ruff format --check <touched paths>` + `.venv/bin/mypy <touched src paths>`. Full
  gate at section exits only: `.venv/bin/python -m pytest -q`, `.venv/bin/ruff check .`,
  `.venv/bin/mypy src`.
- `ruff format` only the files a task touches (pre-existing format drift elsewhere is left).

## Review Focus

1. **A filer that renamed or stopped tagging a concept** (GOOGL's interest, BAC's interest after
   2024-03): the old figure must not pass for a current one, and the history keeps it → Task 3
   `test_a_concept_the_filer_stopped_tagging_is_dropped_from_ttm`; Task 7
   `test_coverage_is_implied_when_interest_is_untagged_and_debt_is_net`.
2. **A stock split inside the window** (NVDA, GOOGL): per-share series continuous, and an
   unexplained jump is UNKNOWN, never a 20× "growth" → Task 5
   `test_a_twenty_for_one_split_rescales_every_older_year`,
   `test_a_split_after_the_last_10k_rescales_the_whole_series`,
   `test_a_jump_that_is_no_split_is_unexplained`; Task 7 `test_each_data_quality_check_says_unknown`.
3. **yfinance throttled or down during the run:** a missing market cap is data-quality UNKNOWN,
   counted and printed, never a pass → Task 7 `test_a_missing_yfinance_cap_is_unknown_never_a_pass`;
   Task 3 `test_market_facts_come_from_the_provider_and_never_raise`; Task 13's report line
   `no yfinance market cap: N`.
4. **A bank whose CET1 is not tagged:** UNKNOWN, never a silent pass, and the operator's switch
   works → Task 7 `test_a_bank_without_tagged_cet1_is_unknown_never_a_silent_pass`,
   `test_the_operator_may_switch_the_cet1_check_off`.
5. **A multi-class filer** (META, GOOGL, HOOD): the market-cap cross-check still has a share
   count → Task 7 `test_edgar_shares_fall_back_for_a_multi_class_filer`.

---

## File structure

```
config/
  examples/value.yaml                     CREATE  every Part-1 key, equal to the model defaults
  value_universe.csv                      CREATE  S&P 100 snapshot (generated, Task 4)
  value_evidence_universe.csv             CREATE  S&P 500 snapshot (generated, Task 4)
  research_concepts.yaml                  MODIFY  +23 value line items (Task 2)
.gitignore                                MODIFY  + config/value.yaml
src/
  common/config.py                        MODIFY  Value*Cfg models, Config.value, "value.yaml",
                                                  value_db_url_abs
  common/value_types.py                   CREATE  plain input shapes (pydantic only)
  common/value_inputs.py                  CREATE  read-only loader: filings, prices, regime,
                                                  market facts, fingerprint parts
  common/value_universe.py                CREATE  trading + evidence universes, snapshots
  research/schemas.py                     MODIFY  TtmValue
  research/ingest/concepts.py             MODIFY  select_periods(as_of=), select_ttm
  research/ingest/materialize.py          MODIFY  drain_ingest_jobs: "prices" job kind
  research/ingest/value_universe.py       CREATE  enqueue_value_universe (the nightly sweep)
  research/ingest/jobs.py                 MODIFY  value_sweep cron (behind research_sweep.enabled)
  value/__init__.py                       CREATE  package docstring (the fence)
  value/ruleset.py                        CREATE  ruleset_hash, ruleset_id, FROZEN
  value/schemas.py                        CREATE  Check, ListEvaluation, Fingerprint, ValueScorecard
  value/metrics.py                        CREATE  Year, build_years, normalise_shares, cagr, roic…
  value/scores.py                         CREATE  piotroski, altman_z, beneish_m
  value/gates.py                          CREATE  classify, data_quality, operating/financial health
  value/valuation.py                      CREATE  dcf, implied_growth, methods A/B/C/D, P/TBV
  value/timing.py                         CREATE  earnings window, deep-value and growth timing
  value/scorecard.py                      CREATE  build_scorecard (pure)
  value/rank.py                           CREATE  percentiles, rank_list, filed_lists, rs_cutoff
  value/store.py                          CREATE  ValueBase, three tables, engine/session
  value/ticker_file.py                    CREATE  summary, what_changed, persist, is_fresh
  value/funnel.py                         CREATE  build_funnel, render_funnel, render_name
scripts/
  value_universe_snapshot.py              CREATE  rebuilds the two snapshot CSVs
  value_dry_run.py                        CREATE  backfill | run (spec §17)
tests/
  value_fixtures.py                       CREATE  Steady Co, Harbour Bank, price(), inputs(),
                                                  companyfacts()
  test_value_config.py                    CREATE  (9)
  test_research_periods.py                MODIFY  (+7)
  test_research_concepts.py               MODIFY  (+1)
  test_value_inputs.py                    CREATE  (11)
  test_value_universe.py                  CREATE  (10)
  test_value_metrics.py                   CREATE  (8)
  test_value_scores.py                    CREATE  (7)
  test_value_gates.py                     CREATE  (28)
  test_value_valuation.py                 CREATE  (10)
  test_value_scorecard.py                 CREATE  (24)
  test_value_rank.py                      CREATE  (5)
  test_value_store.py                     CREATE  (6)
  test_value_funnel.py                    CREATE  (2)
  test_value_fence.py                     CREATE  (10)
  test_value_dry_run.py                   CREATE  (3)
ARCHITECTURE.md, SETUP.md, STATUS.md, CLAUDE.md   MODIFY (Task 14)
docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md   this plan (Progress log)
docs/superpowers/specs/2026-10-28-value-swing-book-design.md  the spec (added in Task 1)
```

141 new tests in all. Part 1 adds no API route, no command kind, no Telegram command, no
process and no new top-level directory, so `README.md`, `docs/web/commands.md` and
`docs/web/api.md` are unchanged.

---

## Section A — Foundations (Tasks 1–4) · model: sonnet

The config and its fingerprint, point-in-time filings, the read-only input loader, and the two
universes with the research worker's jobs. Nothing here scores a company yet.

**Spec to read:** §6.1, §6.2, §6.3 (first paragraph), §6.8 (last paragraph: the ruleset), §6.9
("Fresh on search" bullets 3–5 and "Where the inputs come from"), §16 first bullet, §17 first
paragraph.

**Files the subagent reads:** `src/common/config.py` (lines 20–45, 1367–1390, 1939–2015,
2100–2135), `src/research/ingest/concepts.py`, `src/research/schemas.py`,
`src/research/ingest/materialize.py` (lines 30–40, 380–427), `src/research/ingest/jobs.py`,
`src/research/ingest/prices.py`, `src/research/store/models.py`, `src/research/store/session.py`,
`src/analytics/technicals.py` (lines 145–190), `src/storage/regime_state.py` (lines 60–80),
`src/news/store/readonly.py`, `src/common/universe.py` (lines 97–160), `config/examples/
universe.yaml` (keys only), `tests/test_research_periods.py`, `tests/test_research_concepts.py`,
`tests/test_research_materialize.py` (its `db` fixture), `tests/test_private_config.py`.

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **A0. The worktree exists and is set up.** If `.claude/worktrees/value-book-1` does not
  exist yet, create it from the main checkout (EnterWorktree, or these single commands):

  ```bash
  git -C "/Users/ianlim/Desktop/IBKR Investments" worktree add "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/value-book-1" -b feat/value-book-1
  ```

  Then, from the worktree root, one command each:

  ```bash
  ln -s "/Users/ianlim/Desktop/IBKR Investments/.venv" .venv
  cp "/Users/ianlim/Desktop/IBKR Investments/docs/superpowers/specs/2026-10-28-value-swing-book-design.md" docs/superpowers/specs/
  cp "/Users/ianlim/Desktop/IBKR Investments/docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md" docs/superpowers/plans/
  IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"
  ```

  (No `web/node_modules` link: Part 1 runs no web test.)
- [ ] **A1. Branch and a clean start.** `git branch --show-current` prints `feat/value-book-1`;
  `git status --short` prints exactly the two copied docs:

  ```
  ?? docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  ?? docs/superpowers/specs/2026-10-28-value-swing-book-design.md
  ```

- [ ] **A2. A green baseline.** Each passes; record the pytest count in the Progress log (every
  later count is "baseline + N"; at `e2bf506` 4997 tests were collected):

  ```bash
  .venv/bin/python -m pytest -q
  .venv/bin/ruff check .
  .venv/bin/mypy src
  ```

  A red baseline is not this plan's to fix: stop and report it.
- [ ] **A3. The code Section A edits is where this plan says.** Each command prints exactly the
  line shown (line numbers as of `e2bf506`; a moved line is fine if the text matches — record it):

  ```bash
  grep -n "^from pydantic import BaseModel, Field, field_validator, model_validator$" src/common/config.py   # 22:
  grep -n '^    "news.yaml",$' src/common/config.py                     # 42:    "news.yaml",
  grep -n "^class _KeyedCfg(BaseModel):$" src/common/config.py           # 1384:class _KeyedCfg(BaseModel):
  grep -n "^    web: WebCfg = Field(default_factory=WebCfg)$" src/common/config.py              # 1960:
  grep -n "^    def contract_cache_url_abs(self) -> str:$" src/common/config.py                # 2009:
  grep -n '^        web=WebCfg(\*\*(settings.get("web") or {})),$' src/common/config.py        # 2128:
  grep -n "^config/news.yaml$" .gitignore                                 # 22:config/news.yaml
  grep -n "^from datetime import date, datetime$" src/research/ingest/concepts.py              # 13:
  grep -n "^from src.research.schemas import Fact$" src/research/ingest/concepts.py            # 19:
  grep -n "^def select_periods($" src/research/ingest/concepts.py         # 119:def select_periods(
  grep -n "^SUPPORTED_UNITS = frozenset" src/research/ingest/concepts.py  # 158:
  grep -n "^from datetime import date$" src/research/schemas.py           # 6:from datetime import date
  grep -n "^class LineItemValue(BaseModel):$" src/research/schemas.py     # 34:
  grep -n "^from src.research.ingest.fundamentals import ingest_fundamentals, load_cached_financials$" src/research/ingest/materialize.py   # 35:
  grep -n '^        if kind == "fundamentals" and cik:$' src/research/ingest/materialize.py   # 406:
  grep -n "^from src.research.ingest.symbols import refresh_symbol_directory$" src/research/ingest/jobs.py   # 20:
  grep -n '^        lambda: run_job("quotes", refresh_quotes),$' src/research/ingest/jobs.py  # 105:
  grep -n "^from src.research.ingest.concepts import select_periods$" tests/test_research_periods.py        # 7:
  tail -n 2 config/research_concepts.yaml       # "      - PaymentsOfDividendsCommonStock" then "      - PaymentsOfDividends" (no trailing newline)
  ```

- [ ] **A4. The pieces Section A builds on exist.** Each prints at least one line:

  ```bash
  grep -n "^def atr14_series\|^def rsi14_series" src/analytics/technicals.py
  grep -n "^def load_regime_state" src/storage/regime_state.py
  grep -n "^class SymbolRow\|^class CompanyFactsRawRow\|^class FinancialRow\|^class DailyBarRow\|^class IngestJobRow" src/research/store/models.py
  grep -n "materialization_budget_seconds" src/common/config.py
  grep -n "^def enqueue\|^def drain_ingest_jobs" src/research/ingest/materialize.py
  grep -n "^def ingest_daily_bars" src/research/ingest/prices.py
  grep -n "^def effective_universe" src/common/universe.py
  grep -n "^def read_only_session\|^def earnings_between" src/news/store/readonly.py src/news/store/queries.py
  grep -n "^def get_fundamentals_provider" src/data/factory.py
  ```

  And this prints nothing (no value code exists yet):

  ```bash
  grep -rln "src\.value\|ValueCfg\|value_inputs" src tests scripts
  ```

- [ ] **A5. Wikipedia's API answers (Task 4 needs it).** Prints `200`:

  ```bash
  curl -s -o /dev/null -w "%{http_code}" -A "IBKR-Income-System/1.0 (https://github.com/IandominusRex)" "https://en.wikipedia.org/w/api.php?action=parse&page=S%26P_100&prop=text&format=json&formatversion=2"
  ```

**Section exit:** four commits on `feat/value-book-1` (`git log --oneline main..HEAD | wc -l`
prints `4`); Tasks 1–4 ticked; full gate green with pytest = baseline + 38; protected files
untouched.

---

### Task 1: Config, the ruleset fingerprint and the package

**Files:**
- Modify: `src/common/config.py` (import line 22; `PRIVATE_CONFIG_FILES` line 42; insert before
  line 1384; `Config` after line 1960; before line 2009; `get_config` after line 2128)
- Modify: `.gitignore` (after line 22)
- Create: `config/examples/value.yaml`, `src/value/__init__.py`, `src/value/ruleset.py`,
  `tests/test_value_config.py`
- Add: the spec and this plan (first commit of the branch)

**Interfaces:**
- Produces: `ValueCfg` (`ruleset_version`, `db_url`, `universe: ValueUniverseCfg`, `ticker_file:
  ValueTickerFileCfg`, `research_sweep: ValueResearchSweepCfg`, `rules: ValueRulesCfg`) and its
  sub-models `ValueDataQualityCfg`, `ValueClassificationCfg`, `ValueHealthCfg`, `ValueBankCfg`,
  `ValueValuationCfg`, `ValueGrowthListCfg`, `ValueMarginCfg` (`deep_value` / `quality_growth`:
  `dict[MarketRegime, float]`), `ValueTimingCfg`; `get_config().value`;
  `Config.value_db_url_abs() -> str`; `ruleset_hash(rules: ValueRulesCfg) -> str` (12 hex);
  `ruleset_id(cfg: ValueCfg) -> tuple[str, str]`; `FROZEN: dict[str, str]`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_config.py`

```python
"""config/value.yaml: the typed model, its committed example and the ruleset hash (Part 1)."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from src.common.config import CONFIG_DIR, PRIVATE_CONFIG_FILES, ValueCfg, get_config
from src.common.schemas import MarketRegime
from src.value.ruleset import FROZEN, ruleset_hash, ruleset_id


def test_value_yaml_is_a_private_file_with_a_committed_example() -> None:
    assert "value.yaml" in PRIVATE_CONFIG_FILES
    assert (CONFIG_DIR / "examples" / "value.yaml").exists()


def test_the_example_spells_out_exactly_the_model_defaults() -> None:
    raw = yaml.safe_load((CONFIG_DIR / "examples" / "value.yaml").read_text(encoding="utf-8"))
    assert ValueCfg(**raw).model_dump() == ValueCfg().model_dump()


def test_get_config_loads_the_value_block() -> None:
    cfg = get_config().value
    assert cfg.ruleset_version == "v0-dryrun"
    assert cfg.rules.margin_of_safety.deep_value[MarketRegime.NORMAL] == 25.0
    assert cfg.rules.margin_of_safety.quality_growth[MarketRegime.CRISIS] == 25.0
    assert cfg.rules.valuation.discount_rate_growth == 0.08
    assert get_config().value_db_url_abs().endswith("/data/value.db")


def test_a_misspelt_rule_is_refused_not_ignored() -> None:
    with pytest.raises(ValidationError):
        ValueCfg(**{"rules": {"health": {"piotroski_minimum": 7}}})


def test_a_margin_table_missing_a_regime_is_refused() -> None:
    with pytest.raises(ValidationError):
        ValueCfg(**{"rules": {"margin_of_safety": {"deep_value": {"normal": 25.0}}}})


def test_a_discount_rate_at_or_below_terminal_growth_is_refused() -> None:
    with pytest.raises(ValidationError):
        ValueCfg(**{"rules": {"valuation": {"discount_rate_growth": 0.025}}})


def test_the_ruleset_hash_is_stable_and_moves_with_any_rule() -> None:
    base = ValueCfg()
    assert ruleset_hash(base.rules) == ruleset_hash(ValueCfg().rules)
    assert len(ruleset_hash(base.rules)) == 12
    moved = ValueCfg(**{"rules": {"health": {"piotroski_min": 7}}})
    assert ruleset_hash(moved.rules) != ruleset_hash(base.rules)


def test_non_rule_keys_do_not_move_the_hash() -> None:
    other = ValueCfg(**{"ticker_file": {"follow_days": 90}, "research_sweep": {"enabled": True}})
    assert ruleset_hash(other.rules) == ruleset_hash(ValueCfg().rules)


def test_a_frozen_version_refuses_rules_that_no_longer_match(monkeypatch) -> None:
    monkeypatch.setitem(FROZEN, "v9", "000000000000")
    with pytest.raises(ValueError, match="frozen"):
        ruleset_id(ValueCfg(ruleset_version="v9"))
    assert ruleset_id(ValueCfg()) == ("v0-dryrun", ruleset_hash(ValueCfg().rules))
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_config.py`
  Expected: collection error, `ImportError: cannot import name 'ValueCfg' from 'src.common.config'`.

- [x] **Step 3: Wire the config model into `src/common/config.py`**

  (a) Line 22 becomes:

  ```python
  from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
  ```

  (b) In `PRIVATE_CONFIG_FILES` (lines 36–43), after `    "news.yaml",` add `    "value.yaml",`.

  (c) Insert this block immediately before `class _KeyedCfg(BaseModel):` (line 1384), leaving two
  blank lines on each side:

```python
# ── The value book (docs/superpowers/specs/2026-10-28-value-swing-book-design.md) ─────────────
# Every model forbids unknown keys: a misspelt threshold silently ignored would leave the
# operator believing a rule changed when it did not.

_REGIMES = (MarketRegime.NORMAL, MarketRegime.CAUTIOUS, MarketRegime.STRESSED, MarketRegime.CRISIS)


class _ValueModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValueDataQualityCfg(_ValueModel):
    """Spec §6.3: a failure here is UNKNOWN, never FAIL."""

    min_annual_periods: int = 5
    max_filing_age_days: int = 200
    market_cap_tolerance: float = 0.10  # EDGAR vs yfinance market cap, as a fraction
    min_price_sessions: int = 210
    stale_item_days: int = 200  # a line item this far behind the newest filing is dropped


class ValueClassificationCfg(_ValueModel):
    """Spec §6.4-6.5. Industry names are GICS sub-industries (the snapshot) and yfinance
    industries (names outside it)."""

    bank_industries: list[str] = Field(
        default_factory=lambda: [
            "Diversified Banks",
            "Regional Banks",
            "Banks - Diversified",
            "Banks - Regional",
        ]
    )
    insurer_industries: list[str] = Field(
        default_factory=lambda: [
            "Property & Casualty Insurance",
            "Multi-line Insurance",
            "Reinsurance",
            "Life & Health Insurance",
            "Insurance - Property & Casualty",
            "Insurance - Diversified",
            "Insurance - Reinsurance",
            "Insurance - Specialty",
            "Insurance - Life",
        ]
    )
    combined_ratio_industries: list[str] = Field(
        default_factory=lambda: [
            "Property & Casualty Insurance",
            "Multi-line Insurance",
            "Reinsurance",
            "Insurance - Property & Casualty",
            "Insurance - Diversified",
            "Insurance - Reinsurance",
            "Insurance - Specialty",
        ]
    )
    reit_marker: str = "REIT"
    cyclical_industries: list[str] = Field(
        default_factory=lambda: [
            "Semiconductors",
            "Semiconductor Materials & Equipment",
            "Semiconductor Equipment & Materials",
            "Steel",
            "Copper",
            "Gold",
            "Commodity Chemicals",
            "Chemicals",
            "Fertilizers & Agricultural Chemicals",
            "Agricultural Inputs",
            "Integrated Oil & Gas",
            "Oil & Gas Exploration & Production",
            "Oil & Gas Equipment & Services",
            "Oil & Gas Refining & Marketing",
            "Oil & Gas Integrated",
            "Oil & Gas E&P",
            "Automobile Manufacturers",
            "Auto Manufacturers",
            "Homebuilding",
            "Residential Construction",
            "Construction Machinery & Heavy Transportation Equipment",
            "Agricultural & Farm Machinery",
            "Farm & Heavy Construction Machinery",
            "Passenger Airlines",
            "Airlines",
        ]
    )
    cyclical_fcf_margin_stdev_pts: float = 8.0
    preprofit_loss_years_min: int = 3  # net loss in this many of the last 5 years


class ValueHealthCfg(_ValueModel):
    """Spec §6.4, operating companies (the cyclical keys relax two counts, §6.4)."""

    piotroski_min: int = 6
    altman_z_min: float = 1.8
    profitable_years_min: int = 4
    fcf_positive_years_min: int = 3
    net_debt_to_ebitda_max: float = 3.0
    interest_coverage_min: float = 4.0
    beneish_m_max: float = -1.78
    dilution_max_pct: float = 3.0
    assumed_interest_rate: float = 0.08  # implied coverage when interest expense is untagged
    cyclical_profitable_years_min: int = 3
    cyclical_fcf_positive_years_min: int = 3


class ValueBankCfg(_ValueModel):
    """Spec §6.4, banks and insurers."""

    profitable_years_min: int = 4
    rote_median_min_pct: float = 10.0
    rote_stdev_max_pts: float = 4.0
    nco_multiple_max: float = 1.5
    require_cet1: bool = True
    cet1_min_pct: float = 6.5  # the 4.5% regulatory minimum + 2 points
    combined_ratio_max_pct: float = 100.0
    combined_ratio_years_min: int = 4


class ValueValuationCfg(_ValueModel):
    """Spec §6.5."""

    discount_rate_deep: float = 0.09
    discount_rate_growth: float = 0.08
    g_floor: float = 0.02
    terminal_growth: float = 0.025
    dcf_years: int = 10
    reverse_dcf_haircut: float = 0.7
    realised_cap_deep: float = 0.15
    realised_cap_growth: float = 0.20
    growth_sbc_share: float = 0.5
    terminal_value_max_share: float = 0.75

    @model_validator(mode="after")
    def _rates_above_growth(self) -> ValueValuationCfg:
        for name in ("discount_rate_deep", "discount_rate_growth"):
            if getattr(self, name) <= self.terminal_growth:
                raise ValueError(f"value valuation.{name} must exceed terminal_growth")
        if self.discount_rate_deep <= self.g_floor:
            raise ValueError("value valuation.discount_rate_deep must exceed g_floor")
        if self.dcf_years < 2:
            raise ValueError("value valuation.dcf_years must be at least 2")
        return self


class ValueGrowthListCfg(_ValueModel):
    """Spec §6.0, the quality-growth entry rule."""

    revenue_cagr_min_pct: float = 10.0
    fcf_ps_cagr_min_pct: float = 10.0
    roic_median_min_pct: float = 15.0
    gross_margin_stdev_max_pts: float = 5.0


class ValueMarginCfg(_ValueModel):
    """Spec §6.0 and §9.6: the required margin of safety, in percent, by market regime."""

    deep_value: dict[MarketRegime, float] = Field(
        default_factory=lambda: dict(zip(_REGIMES, (25.0, 30.0, 35.0, 40.0), strict=True))
    )
    quality_growth: dict[MarketRegime, float] = Field(
        default_factory=lambda: dict(zip(_REGIMES, (10.0, 15.0, 20.0, 25.0), strict=True))
    )
    review_above_pct: float = 60.0

    @model_validator(mode="after")
    def _every_regime(self) -> ValueMarginCfg:
        for name in ("deep_value", "quality_growth"):
            missing = set(_REGIMES) - set(getattr(self, name))
            if missing:
                raise ValueError(f"value margin_of_safety.{name} lacks {sorted(missing)}")
        return self


class ValueTimingCfg(_ValueModel):
    """Spec §6.6."""

    earnings_window_sessions: int = 10
    recent_report_days: int = 70  # a report this recent dates the next one past the window
    rs_bottom_pct: float = 30.0
    low_lookback_sessions: int = 63
    new_low_window_sessions: int = 5


class ValueRulesCfg(_ValueModel):
    """Every key that can change a verdict. Hashed into the ruleset fingerprint (spec §6.8)."""

    data_quality: ValueDataQualityCfg = Field(default_factory=ValueDataQualityCfg)
    classification: ValueClassificationCfg = Field(default_factory=ValueClassificationCfg)
    health: ValueHealthCfg = Field(default_factory=ValueHealthCfg)
    banks: ValueBankCfg = Field(default_factory=ValueBankCfg)
    valuation: ValueValuationCfg = Field(default_factory=ValueValuationCfg)
    quality_growth: ValueGrowthListCfg = Field(default_factory=ValueGrowthListCfg)
    margin_of_safety: ValueMarginCfg = Field(default_factory=ValueMarginCfg)
    timing: ValueTimingCfg = Field(default_factory=ValueTimingCfg)


class ValueUniverseCfg(_ValueModel):
    """Spec §6.1. The trading universe is ``universe.yaml``'s would_own + watchlist plus the
    trading snapshot; the evidence universe is the wider snapshot."""

    trading_snapshot: str = "config/value_universe.csv"
    evidence_snapshot: str = "config/value_evidence_universe.csv"
    share_class_primary: dict[str, str] = Field(
        default_factory=lambda: {"GOOG": "GOOGL", "FOX": "FOXA", "NWS": "NWSA"}
    )


class ValueTickerFileCfg(_ValueModel):
    """Spec §6.9."""

    follow_days: int = 30
    mos_band_pts: float = 5.0  # a history row when the margin of safety crosses a band
    fair_value_change_pct: float = 1.0  # ... or fair value moves by more than this


class ValueResearchSweepCfg(_ValueModel):
    """The research worker's nightly enqueue of every value name's filings and bars."""

    enabled: bool = False
    hour_et: int = 2


class ValueCfg(_ValueModel):
    """The value book (config/value.yaml). Part 1: the scorecard, nothing that trades."""

    ruleset_version: str = "v0-dryrun"
    db_url: str = "sqlite:///data/value.db"
    universe: ValueUniverseCfg = Field(default_factory=ValueUniverseCfg)
    ticker_file: ValueTickerFileCfg = Field(default_factory=ValueTickerFileCfg)
    research_sweep: ValueResearchSweepCfg = Field(default_factory=ValueResearchSweepCfg)
    rules: ValueRulesCfg = Field(default_factory=ValueRulesCfg)
```

  (d) In `class Config`, after `    web: WebCfg = Field(default_factory=WebCfg)` (line 1960):

  ```python
      value: ValueCfg = Field(default_factory=ValueCfg)
  ```

  (e) Before `    def contract_cache_url_abs(self) -> str:` (line 2009):

  ```python
      def value_db_url_abs(self) -> str:
          """Resolve the relative value-book sqlite path against the project root."""
          url = self.value.db_url
          if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
              rel = url[len("sqlite:///") :]
              return f"sqlite:///{(ROOT / rel).as_posix()}"
          return url

  ```

  (f) In `get_config()`, after `        web=WebCfg(**(settings.get("web") or {})),` (line 2128):

  ```python
          value=ValueCfg(**_load_yaml("value.yaml")),
  ```

- [x] **Step 4: Create `config/examples/value.yaml`** (it must equal the model defaults; a test
  says so)

```yaml
# The value book (docs/superpowers/specs/2026-10-28-value-swing-book-design.md).
#
# Copy to config/value.yaml (git-ignored) to tune it. Part 1 builds the scorecard only: nothing
# here can place, size or gate an order.
#
# Everything under `rules:` can change a verdict, so it is hashed into the ruleset fingerprint
# (src/value/ruleset.py). Once `ruleset_version` is frozen (v1, after the calibration dry run,
# spec §17), changing any rule is a version bump with a written reason, at most quarterly.

ruleset_version: v0-dryrun
db_url: sqlite:///data/value.db

universe:
  # Committed snapshots, each with its as-of date on the first line. Rebuild with
  # `python -m scripts.value_universe_snapshot`.
  trading_snapshot: config/value_universe.csv            # S&P 100
  evidence_snapshot: config/value_evidence_universe.csv  # S&P 500
  # A second share class of one filer is scored once, under its primary ticker.
  share_class_primary:
    GOOG: GOOGL
    FOX: FOXA
    NWS: NWSA

ticker_file:
  follow_days: 30            # a looked-up name outside the universe is refreshed this long
  mos_band_pts: 5.0          # a history row when the margin of safety crosses a 5-point band
  fair_value_change_pct: 1.0 # ... or fair value moves by more than 1%

research_sweep:
  enabled: false             # the research worker's nightly enqueue (Part 2 turns it on)
  hour_et: 2

rules:
  data_quality:              # spec §6.3: a failure is UNKNOWN, never FAIL
    min_annual_periods: 5
    max_filing_age_days: 200
    market_cap_tolerance: 0.10
    min_price_sessions: 210
    stale_item_days: 200

  classification:            # spec §6.4-6.5
    bank_industries: [Diversified Banks, Regional Banks, Banks - Diversified, Banks - Regional]
    insurer_industries:
      - Property & Casualty Insurance
      - Multi-line Insurance
      - Reinsurance
      - Life & Health Insurance
      - Insurance - Property & Casualty
      - Insurance - Diversified
      - Insurance - Reinsurance
      - Insurance - Specialty
      - Insurance - Life
    combined_ratio_industries:
      - Property & Casualty Insurance
      - Multi-line Insurance
      - Reinsurance
      - Insurance - Property & Casualty
      - Insurance - Diversified
      - Insurance - Reinsurance
      - Insurance - Specialty
    reit_marker: REIT
    cyclical_industries:
      - Semiconductors
      - Semiconductor Materials & Equipment
      - Semiconductor Equipment & Materials
      - Steel
      - Copper
      - Gold
      - Commodity Chemicals
      - Chemicals
      - Fertilizers & Agricultural Chemicals
      - Agricultural Inputs
      - Integrated Oil & Gas
      - Oil & Gas Exploration & Production
      - Oil & Gas Equipment & Services
      - Oil & Gas Refining & Marketing
      - Oil & Gas Integrated
      - Oil & Gas E&P
      - Automobile Manufacturers
      - Auto Manufacturers
      - Homebuilding
      - Residential Construction
      - Construction Machinery & Heavy Transportation Equipment
      - Agricultural & Farm Machinery
      - Farm & Heavy Construction Machinery
      - Passenger Airlines
      - Airlines
    cyclical_fcf_margin_stdev_pts: 8.0
    preprofit_loss_years_min: 3

  health:                    # spec §6.4, operating companies: hard, a conjunction
    piotroski_min: 6
    altman_z_min: 1.8
    profitable_years_min: 4
    fcf_positive_years_min: 3
    net_debt_to_ebitda_max: 3.0
    interest_coverage_min: 4.0
    beneish_m_max: -1.78
    dilution_max_pct: 3.0
    assumed_interest_rate: 0.08  # implied coverage when interest expense is not tagged
    cyclical_profitable_years_min: 3
    cyclical_fcf_positive_years_min: 3

  banks:                     # spec §6.4, banks and insurers
    profitable_years_min: 4
    rote_median_min_pct: 10.0
    rote_stdev_max_pts: 4.0
    nco_multiple_max: 1.5
    require_cet1: true       # CET1 is not tagged in companyfacts for BAC or JPM (2026-10-29)
    cet1_min_pct: 6.5
    combined_ratio_max_pct: 100.0
    combined_ratio_years_min: 4

  valuation:                 # spec §6.5
    discount_rate_deep: 0.09
    discount_rate_growth: 0.08
    g_floor: 0.02
    terminal_growth: 0.025
    dcf_years: 10
    reverse_dcf_haircut: 0.7
    realised_cap_deep: 0.15
    realised_cap_growth: 0.20
    growth_sbc_share: 0.5
    terminal_value_max_share: 0.75

  quality_growth:            # spec §6.0, the entry rule
    revenue_cagr_min_pct: 10.0
    fcf_ps_cagr_min_pct: 10.0
    roic_median_min_pct: 15.0
    gross_margin_stdev_max_pts: 5.0

  margin_of_safety:          # spec §6.0 and §9.6, percent, by market regime
    deep_value: {normal: 25.0, cautious: 30.0, stressed: 35.0, crisis: 40.0}
    quality_growth: {normal: 10.0, cautious: 15.0, stressed: 20.0, crisis: 25.0}
    review_above_pct: 60.0

  timing:                    # spec §6.6
    earnings_window_sessions: 10
    recent_report_days: 70   # a report this recent dates the next one past the window
    rs_bottom_pct: 30.0
    low_lookback_sessions: 63
    new_low_window_sessions: 5
```

- [x] **Step 5: Ignore the private copy.** In `.gitignore`, after line 22 `config/news.yaml`, add
  the line `config/value.yaml`. (`data/value.db` is already covered by `data/*.db`, line 42.)

- [x] **Step 6: Create the package and the ruleset module** — `src/value/__init__.py`:

```python
"""The value book (docs/superpowers/specs/2026-10-28-value-swing-book-design.md).

Deterministic tier. Imports nothing from ``src.claude``, ``src.news``, ``src.value_ai``,
``src.spreads*``, ``src.notify``, ``src.api`` or the trading path, and from ``src.research`` only
``src.research.ingest.concepts`` and ``src.research.schemas`` (tests/test_value_fence.py).
``src/value/`` is the only writer of ``data/value.db``.
"""
```

  `src/value/ruleset.py`:

```python
"""The ruleset fingerprint (spec §6.8): ``value_rules`` version plus a hash of the rule keys.

Every scorecard, ticker-file row and (later) shadow row carries both, so a verdict can always be
traced to the exact thresholds that produced it.
"""

from __future__ import annotations

import hashlib
import json

from src.common.config import ValueCfg, ValueRulesCfg

# Filled at the freeze (Part 1, Task 16): ruleset version -> the hash its rules must have.
FROZEN: dict[str, str] = {}


def ruleset_hash(rules: ValueRulesCfg) -> str:
    """12 hex characters of sha256 over the canonical JSON of every rule key."""
    canonical = json.dumps(rules.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def ruleset_id(cfg: ValueCfg) -> tuple[str, str]:
    """``(version, hash)``. A frozen version whose rules no longer hash to the pinned value
    raises, because a verdict would otherwise carry a version whose rules quietly changed."""
    digest = ruleset_hash(cfg.rules)
    pinned = FROZEN.get(cfg.ruleset_version)
    if pinned is not None and pinned != digest:
        raise ValueError(
            f"value ruleset {cfg.ruleset_version} is frozen at {pinned}, but config/value.yaml's "
            f"rules hash to {digest}: bump ruleset_version (spec §6.8)"
        )
    return cfg.ruleset_version, digest
```

- [x] **Step 7: Stage the example (the private-config test checks it is tracked) and run**

  ```bash
  git add config/examples/value.yaml .gitignore
  .venv/bin/python -m pytest -q tests/test_value_config.py tests/test_private_config.py tests/test_spreads_config.py
  ```

  Expected: all pass (`test_value_config.py`: 9 passed).

- [x] **Step 8: Gates**

  ```bash
  .venv/bin/ruff check src/common/config.py src/value tests/test_value_config.py
  .venv/bin/ruff format --check src/value tests/test_value_config.py
  .venv/bin/mypy src/common/config.py src/value
  ```

  Expected: `All checks passed!`, every file already formatted (run `ruff format` on exactly
  these files if not), `Success: no issues found`.

- [x] **Step 9: Commit**

  ```bash
  git add src/common/config.py .gitignore config/examples/value.yaml src/value/__init__.py src/value/ruleset.py tests/test_value_config.py docs/superpowers/specs/2026-10-28-value-swing-book-design.md docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): config/value.yaml, the value config model and the ruleset fingerprint"
  ```

  (Message body ends with the `Co-Authored-By:` trailer, as in Execution model.)

---

### Task 2: Point in time — `select_periods(as_of=)`, `select_ttm`, and the concept map

**Files:**
- Modify: `src/research/schemas.py` (line 6; insert before line 34)
- Modify: `src/research/ingest/concepts.py` (line 13; line 19; replace lines 119–157)
- Modify: `config/research_concepts.yaml` (append after the last line, 144)
- Modify: `tests/test_research_periods.py` (line 7; append), `tests/test_research_concepts.py`
  (append)

**Interfaces:**
- Produces: `select_periods(facts, *, kind, period_type, limit, as_of: date | None = None)`;
  `select_ttm(facts: list[Fact], *, as_of: date | None = None) -> TtmValue | None`;
  `TtmValue(value: float, end: date, basis: Literal["ytd","fy"], accn: str, filed: date)` in
  `src/research/schemas.py`; 23 new line items (names in the test below).

- [x] **Step 1: Write the failing tests.** In `tests/test_research_periods.py`, line 7 becomes
  `from src.research.ingest.concepts import select_periods, select_ttm`, and append:

```python
# ── as_of and TTM (value book spec §6.2) ─────────────────────────────────────────────────────


def test_as_of_hides_a_restatement_filed_later() -> None:
    """Point in time: the value the filings showed that day, never a later restatement."""
    facts = [
        _fact(
            start=date(2023, 1, 1),
            end=date(2023, 12, 31),
            val=100,
            filed=date(2024, 2, 1),
            accn="original",
        ),
        _fact(
            start=date(2023, 1, 1),
            end=date(2023, 12, 31),
            val=94,
            filed=date(2025, 2, 1),
            accn="restated",
        ),
    ]
    before = select_periods(
        facts, kind="duration", period_type="annual", limit=5, as_of=date(2024, 6, 30)
    )
    after = select_periods(
        facts, kind="duration", period_type="annual", limit=5, as_of=date(2025, 3, 1)
    )
    assert [(f.value, f.accn) for f in before] == [(100, "original")]
    assert [(f.value, f.accn) for f in after] == [(94, "restated")]


def test_as_of_hides_a_period_not_yet_filed() -> None:
    facts = [
        _fact(start=date(2023, 1, 1), end=date(2023, 12, 31), val=1, filed=date(2024, 2, 1)),
        _fact(start=date(2024, 1, 1), end=date(2024, 12, 31), val=2, filed=date(2025, 2, 1)),
    ]
    out = select_periods(
        facts, kind="duration", period_type="annual", limit=5, as_of=date(2024, 12, 31)
    )
    assert [f.value for f in out] == [1]


def _ttm_facts() -> list:
    return [
        _fact(
            start=date(2024, 1, 1),
            end=date(2024, 12, 31),
            val=400,
            filed=date(2025, 2, 1),
            accn="k24",
        ),
        _fact(
            start=date(2025, 1, 1),
            end=date(2025, 3, 31),
            val=110,
            filed=date(2025, 5, 1),
            form="10-Q",
            accn="q1",
        ),
        _fact(
            start=date(2024, 1, 1),
            end=date(2024, 3, 31),
            val=95,
            filed=date(2025, 5, 1),
            form="10-Q",
            accn="q1",
        ),
        _fact(
            start=date(2025, 1, 1),
            end=date(2025, 6, 30),
            val=230,
            filed=date(2025, 8, 1),
            form="10-Q",
            accn="q2",
        ),
        _fact(
            start=date(2024, 1, 1),
            end=date(2024, 6, 30),
            val=190,
            filed=date(2025, 8, 1),
            form="10-Q",
            accn="q2",
        ),
        # a discrete second quarter: starts mid-year, so it is not a year-to-date figure
        _fact(
            start=date(2025, 4, 1),
            end=date(2025, 6, 30),
            val=120,
            filed=date(2025, 8, 1),
            form="10-Q",
            accn="q2",
        ),
    ]


def test_ttm_is_the_fiscal_year_plus_this_ytd_less_last_years_ytd() -> None:
    ttm = select_ttm(_ttm_facts())
    assert ttm is not None
    assert (ttm.value, ttm.end, ttm.basis, ttm.accn) == (440.0, date(2025, 6, 30), "ytd", "q2")


def test_ttm_respects_as_of() -> None:
    q1 = select_ttm(_ttm_facts(), as_of=date(2025, 7, 1))
    assert q1 is not None and (q1.value, q1.end) == (415.0, date(2025, 3, 31))
    fy = select_ttm(_ttm_facts(), as_of=date(2025, 4, 1))
    assert fy is not None and (fy.value, fy.basis) == (400.0, "fy")


def test_ttm_without_a_prior_year_comparative_is_the_fiscal_year() -> None:
    facts = [f for f in _ttm_facts() if f.value not in (95, 190)]
    ttm = select_ttm(facts)
    assert ttm is not None and (ttm.value, ttm.basis) == (400.0, "fy")


def test_ttm_handles_a_52_53_week_fiscal_year() -> None:
    facts = [
        _fact(start=date(2023, 9, 1), end=date(2024, 8, 29), val=250, filed=date(2024, 10, 3)),
        _fact(
            start=date(2024, 8, 30),
            end=date(2024, 11, 28),
            val=87,
            filed=date(2024, 12, 19),
            form="10-Q",
        ),
        _fact(
            start=date(2023, 9, 1),
            end=date(2023, 11, 30),
            val=47,
            filed=date(2024, 12, 19),
            form="10-Q",
        ),
    ]
    ttm = select_ttm(facts)
    assert ttm is not None and (ttm.value, ttm.end, ttm.basis) == (290.0, date(2024, 11, 28), "ytd")


def test_ttm_is_none_without_an_annual_fact() -> None:
    assert (
        select_ttm(
            [_fact(start=date(2025, 1, 1), end=date(2025, 3, 31), val=1, filed=date(2025, 5, 1))]
        )
        is None
    )
```

  Append to `tests/test_research_concepts.py`:

```python
def test_the_concept_map_carries_the_value_books_line_items() -> None:
    """Value book spec §6.4-6.5: every line item the scorecard reads is mapped."""
    m = load_concept_map()
    value_items = {
        "sbc": "duration",
        "interest_expense": "duration",
        "depreciation_amortization": "duration",
        "accounts_receivable": "instant",
        "ppe_net": "instant",
        "sga": "duration",
        "retained_earnings": "instant",
        "pretax_income": "duration",
        "income_tax": "duration",
        "long_term_debt_current": "instant",
        "commercial_paper": "instant",
        "short_term_borrowings": "instant",
        "marketable_securities": "instant",
        "goodwill": "instant",
        "intangibles": "instant",
        "preferred_equity": "instant",
        "net_income_common": "duration",
        "net_charge_offs": "duration",
        "loans": "instant",
        "cet1_ratio": "instant",
        "premiums_earned": "duration",
        "benefits_losses_expenses": "duration",
        "shares_outstanding": "instant",
    }
    for name, kind in value_items.items():
        assert name in m, name
        assert m[name].kind == kind, name
    assert m["interest_expense"].concepts[:2] == ["InterestExpense", "InterestExpenseNonoperating"]
    assert m["cet1_ratio"].units == ["pure"]
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_research_periods.py tests/test_research_concepts.py`
  Expected: collection error, `ImportError: cannot import name 'select_ttm'`.

- [x] **Step 3: Add `TtmValue` to `src/research/schemas.py`.** After line 6 (`from datetime import
  date`) add `from typing import Literal`; insert before `class LineItemValue(BaseModel):` (line 34):

```python
@dataclass(frozen=True, slots=True)
class TtmValue:
    """A trailing-twelve-month figure (value book spec §6.2). ``basis`` is ``"ytd"`` when it is
    fiscal year + year-to-date - prior year-to-date, ``"fy"`` when the fiscal year stands alone."""

    value: float
    end: date
    basis: Literal["ytd", "fy"]
    accn: str
    filed: date
```

- [x] **Step 4: Edit `src/research/ingest/concepts.py`.** Line 13 becomes `from datetime import
  date, datetime, timedelta`; line 19 becomes `from src.research.schemas import Fact, TtmValue`;
  replace everything from line 119 (`def select_periods(`) up to, not including, line 158
  (`SUPPORTED_UNITS = …`) with the block below, followed by two blank lines:

```python
def select_periods(
    facts: list[Fact],
    *,
    kind: str,
    period_type: str,
    limit: int,
    as_of: date | None = None,
) -> list[Fact]:
    """Pick one fact per reporting period, newest first.

    Three rules carry the correctness of this function:

    1. `kind` is enforced. A duration fact can never satisfy an instant line item and vice
       versa. Summing four quarterly durations into "total assets", or reading an instant as
       a year of revenue, produces plausible nonsense.
    2. When two filings report the same period, the one filed LATER wins. That is how a
       restatement becomes the current answer instead of silently reverting.
    3. With `as_of`, only facts filed on or before that date exist (value book spec §6.2):
       the answer is what the filings said that day, so a restatement filed later never
       leaks into a past verdict. Without it (display), every filing counts.
    """
    if as_of is not None:
        facts = [f for f in facts if f.filed <= as_of]
    if kind == "duration":
        lo, hi = _ANNUAL_DAYS if period_type == "annual" else _QUARTER_DAYS
        candidates = [
            f for f in facts if f.start is not None and lo <= (f.end - f.start).days <= hi
        ]
    elif kind == "instant":
        candidates = [f for f in facts if f.start is None]
        if period_type == "annual":
            candidates = [f for f in candidates if f.form in _ANNUAL_FORMS]
    else:
        raise ValueError(f"kind must be 'duration' or 'instant', got {kind!r}")

    # One fact per period_end; the latest filing wins.
    by_period: dict[date, Fact] = {}
    for fact in candidates:
        current = by_period.get(fact.end)
        if current is None or fact.filed > current.filed:
            by_period[fact.end] = fact

    return sorted(by_period.values(), key=lambda f: f.end, reverse=True)[:limit]


# How far a year-to-date fact's start may sit from the fiscal year's first day, in days. 52/53
# week fiscal years (Apple, Micron) start on a different weekday each year.
_YTD_START_TOLERANCE_DAYS = 10
_YTD_DAYS = (60, 300)


def select_ttm(facts: list[Fact], *, as_of: date | None = None) -> TtmValue | None:
    """The trailing-twelve-month value of a duration line item, as known on `as_of`.

    10-Q cash-flow statements report year-to-date figures (3, 6, 9 months), not quarters, so
    four quarters cannot be summed. TTM = latest fiscal year + the current year-to-date - the
    same year-to-date a year earlier. With no year-to-date figure since the last fiscal year
    (a 10-K just filed), or no prior-year comparative, the fiscal year stands alone and the
    result says so (``basis="fy"``). None when the item has no annual fact at all.
    """
    pool = [f for f in facts if f.start is not None and (as_of is None or f.filed <= as_of)]
    annual = select_periods(pool, kind="duration", period_type="annual", limit=1)
    if not annual:
        return None
    fy = annual[0]
    fy_only = TtmValue(value=fy.value, end=fy.end, basis="fy", accn=fy.accn, filed=fy.filed)
    lo, hi = _YTD_DAYS
    year_start = fy.end + timedelta(days=1)
    ytd_pool = [
        f
        for f in pool
        if f.start is not None
        and abs((f.start - year_start).days) <= _YTD_START_TOLERANCE_DAYS
        and lo <= (f.end - f.start).days <= hi
    ]
    if not ytd_pool:
        return fy_only
    ytd_end = max(f.end for f in ytd_pool)
    ytd = max((f for f in ytd_pool if f.end == ytd_end), key=lambda f: f.filed)
    assert ytd.start is not None and fy.start is not None
    length = (ytd.end - ytd.start).days
    prior_pool = [
        f
        for f in pool
        if f.start is not None
        and abs((f.start - fy.start).days) <= _YTD_START_TOLERANCE_DAYS
        and abs((f.end - f.start).days - length) <= _YTD_START_TOLERANCE_DAYS
    ]
    if not prior_pool:
        return fy_only
    prior = max(prior_pool, key=lambda f: f.filed)
    return TtmValue(
        value=fy.value + ytd.value - prior.value,
        end=ytd.end,
        basis="ytd",
        accn=ytd.accn,
        filed=max(ytd.filed, fy.filed),
    )
```

- [x] **Step 5: Map the value line items.** The file ends without a newline after
  `      - PaymentsOfDividends`. Append a newline and one blank line, then this block (it ends
  with a newline):

```yaml
  # ── Value book line items (docs/superpowers/specs/2026-10-28-value-swing-book-design.md §6.4-6.5).
  # Aliases verified against BAC, JPM, TRV, GOOGL, META, MU, AAPL, NVDA, AMD and HOOD companyfacts
  # (2026-10-29). Several concepts change name over the years (GOOGL and META stop tagging
  # InterestExpense after 2023/2024 and tag InterestExpenseNonoperating instead); pooling the
  # aliases keeps every year.

  sbc:
    statement: cash_flow
    kind: duration
    units: [USD]
    concepts:
      - ShareBasedCompensation
      - AllocatedShareBasedCompensationExpense

  interest_expense:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - InterestExpense
      - InterestExpenseNonoperating
      - InterestExpenseDebt

  depreciation_amortization:
    statement: cash_flow
    kind: duration
    units: [USD]
    concepts:
      - DepreciationDepletionAndAmortization
      - DepreciationAmortizationAndAccretionNet
      - DepreciationAndAmortization
      - Depreciation

  accounts_receivable:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - AccountsReceivableNetCurrent
      - ReceivablesNetCurrent

  ppe_net:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - PropertyPlantAndEquipmentNet
      - PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization

  sga:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - SellingGeneralAndAdministrativeExpense
      - GeneralAndAdministrativeExpense

  retained_earnings:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - RetainedEarningsAccumulatedDeficit

  pretax_income:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest
      - IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments

  income_tax:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - IncomeTaxExpenseBenefit

  long_term_debt_current:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - LongTermDebtCurrent
      - DebtCurrent

  commercial_paper:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - CommercialPaper

  short_term_borrowings:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - ShortTermBorrowings

  marketable_securities:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - MarketableSecuritiesCurrent
      - ShortTermInvestments
      - AvailableForSaleSecuritiesDebtSecuritiesCurrent

  goodwill:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - Goodwill

  intangibles:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - IntangibleAssetsNetExcludingGoodwill

  preferred_equity:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - PreferredStockIncludingAdditionalPaidInCapital
      - PreferredStockIncludingAdditionalPaidInCapitalNetOfDiscount
      - PreferredStockValue
      - PreferredStockValueOutstanding

  net_income_common:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - NetIncomeLossAvailableToCommonStockholdersBasic

  net_charge_offs:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - FinancingReceivableExcludingAccruedInterestAllowanceForCreditLossWriteoffAfterRecovery
      - FinancingReceivableAllowanceForCreditLossWriteoffAfterRecovery
      - AllowanceForLoanAndLeaseLossesWriteoffsNet

  loans:
    statement: balance
    kind: instant
    units: [USD]
    concepts:
      - FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss
      - LoansAndLeasesReceivableNetOfDeferredIncome
      - LoansAndLeasesReceivableNetReportedAmount

  # Not tagged by BAC or JPM in companyfacts (checked 2026-10-29): kept so a filer that does tag
  # it is read, and so the bank set reports UNKNOWN rather than a silent pass (spec §6.4).
  cet1_ratio:
    statement: balance
    kind: instant
    units: [pure]
    concepts:
      - CommonEquityTierOneCapitalRatio
      - CommonEquityTierOneCapitalToRiskWeightedAssets

  premiums_earned:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - PremiumsEarnedNet

  benefits_losses_expenses:
    statement: income
    kind: duration
    units: [USD]
    concepts:
      - BenefitsLossesAndExpenses

  # Instant, balance-sheet share count: the per-share fallback for a fiscal year whose weighted
  # diluted count is not tagged without a class dimension (Alphabet before FY2022).
  shares_outstanding:
    statement: balance
    kind: instant
    units: [shares]
    concepts:
      - CommonStockSharesOutstanding
```

- [x] **Step 6: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_research_periods.py tests/test_research_concepts.py tests/test_research_units.py tests/test_research_materialize.py`
  Expected: all pass (periods 17, concepts 11).

- [x] **Step 7: Gates**

  ```bash
  .venv/bin/ruff check src/research tests/test_research_periods.py tests/test_research_concepts.py
  .venv/bin/ruff format --check src/research/schemas.py src/research/ingest/concepts.py tests/test_research_periods.py tests/test_research_concepts.py
  .venv/bin/mypy src/research
  ```

- [x] **Step 8: Commit**

  ```bash
  git add src/research/schemas.py src/research/ingest/concepts.py config/research_concepts.yaml tests/test_research_periods.py tests/test_research_concepts.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(research): point-in-time select_periods(as_of), select_ttm, and the value line items"
  ```

---

### Task 3: Value inputs — the plain types and the read-only loader

**Files:**
- Create: `src/common/value_types.py`, `src/common/value_inputs.py`, `tests/test_value_inputs.py`

**Interfaces:**
- Consumes: `select_periods(..., as_of=)`, `select_ttm`, `load_concept_map`, `resolve_line_item`
  (Task 2); `atr14_series`, `rsi14_series` (`src/analytics/technicals.py`); `SymbolRow`,
  `CompanyFactsRawRow`, `DailyBarRow`, `FinancialRow`; `load_regime_state`;
  `get_fundamentals_provider().get_info/get_calendar`.
- Produces (types, `src/common/value_types.py`): `AnnualPeriod`, `TtmPoint`, `InstantPoint`,
  `ValueFinancials`, `PriceSeries`, `Classification`, `MarketFacts`, `ValueInputs` (fields as
  written below).
- Produces (loader, `src/common/value_inputs.py`): `ANNUAL_LIMIT = 11`;
  `build_value_financials(payload: dict, *, as_of: date, stale_item_days: int = 200) ->
  ValueFinancials`; `build_price_series(bars: pd.DataFrame, spy: pd.DataFrame | None) ->
  PriceSeries | None`; `research_read() -> ContextManager[Session | None]`; `reset_engine()`;
  `_resolve_path()` (patched in tests); `read_payload(session, symbol) -> tuple[str | None, dict
  | None]`; `read_bars(session, symbol, as_of) -> pd.DataFrame` (index `date`; columns `high, low,
  close, volume`); `current_fingerprint_parts(session, symbol) -> dict`; `load_regime() -> str`;
  `fetch_market_facts(symbol) -> MarketFacts`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_inputs.py`

```python
"""src/common/value_inputs.py: the neutral, read-only loader (value book spec §6.9)."""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import src.common.value_inputs as vi
from src.common.schemas import MarketRegime
from src.research.store.models import (
    Base,
    CompanyFactsRawRow,
    DailyBarRow,
    FinancialRow,
    SymbolRow,
)


def _e(val, end, filed, *, start=None, form="10-K", accn="k25"):
    out = {
        "val": val,
        "end": end,
        "filed": filed,
        "form": form,
        "accn": accn,
        "fy": 2025,
        "fp": "FY",
    }
    if start:
        out["start"] = start
    return out


PAYLOAD = {
    "cik": 1,
    "entityName": "Steady Co",
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        _e(101e6, "2025-01-31", "2025-02-10"),
                        _e(100e6, "2025-07-25", "2025-08-05", form="10-Q", accn="q2"),
                    ]
                }
            }
        },
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        _e(900e6, "2023-12-31", "2024-02-10", start="2023-01-01", accn="k23"),
                        _e(1000e6, "2024-12-31", "2025-02-10", start="2024-01-01", accn="k24"),
                        _e(
                            520e6,
                            "2025-06-30",
                            "2025-08-05",
                            start="2025-01-01",
                            form="10-Q",
                            accn="q2",
                        ),
                        _e(
                            470e6,
                            "2024-06-30",
                            "2025-08-05",
                            start="2024-01-01",
                            form="10-Q",
                            accn="q2",
                        ),
                    ]
                }
            },
            "InterestExpense": {
                "units": {
                    "USD": [_e(10e6, "2023-12-31", "2024-02-10", start="2023-01-01", accn="k23")]
                }
            },
            "Assets": {
                "units": {
                    "USD": [
                        _e(3000e6, "2024-12-31", "2025-02-10", accn="k24"),
                        _e(3100e6, "2025-06-30", "2025-08-05", form="10-Q", accn="q2"),
                    ]
                }
            },
            "WeightedAverageNumberOfDilutedSharesOutstanding": {
                "units": {
                    "shares": [
                        _e(102e6, "2024-12-31", "2025-02-10", start="2024-01-01", accn="k24"),
                        _e(
                            100.5e6,
                            "2025-06-30",
                            "2025-08-05",
                            start="2025-04-01",
                            form="10-Q",
                            accn="q2",
                        ),
                    ]
                }
            },
        },
    },
}


def test_financials_read_annual_ttm_latest_and_shares() -> None:
    fin = vi.build_value_financials(PAYLOAD, as_of=date(2025, 9, 1))
    assert [p.period_end for p in fin.annual] == [date(2024, 12, 31), date(2023, 12, 31)]
    assert fin.annual[0].items["revenue"] == 1000e6
    assert fin.annual[0].accns["revenue"] == "k24"
    assert fin.ttm["revenue"].value == 1050e6  # 1000 + 520 - 470
    assert fin.ttm["revenue"].basis == "ytd"
    assert fin.latest["total_assets"].value == 3100e6
    assert fin.shares_latest == 100.5e6
    assert fin.cover_shares == 100e6
    assert (fin.latest_accn, fin.latest_filed) == ("q2", date(2025, 8, 5))


def test_a_concept_the_filer_stopped_tagging_is_dropped_from_ttm() -> None:
    """InterestExpense ends 2023-12-31, 547 days before the newest period: stale."""
    fin = vi.build_value_financials(PAYLOAD, as_of=date(2025, 9, 1))
    assert "interest_expense" not in fin.ttm
    assert fin.annual[1].items["interest_expense"] == 10e6  # history keeps it


def test_as_of_sees_only_what_was_filed_by_then() -> None:
    fin = vi.build_value_financials(PAYLOAD, as_of=date(2025, 3, 1))
    assert fin.ttm["revenue"].value == 1000e6 and fin.ttm["revenue"].basis == "fy"
    assert fin.latest["total_assets"].value == 3000e6
    assert fin.cover_shares == 101e6
    assert fin.latest_accn == "k24"


def test_a_filer_without_us_gaap_facts_says_so() -> None:
    fin = vi.build_value_financials({"facts": {"ifrs-full": {}}}, as_of=date(2025, 9, 1))
    assert fin.has_us_gaap is False and fin.annual == []


def _bars(n: int = 300) -> tuple[pd.DataFrame, pd.DataFrame]:
    days = pd.bdate_range("2024-06-03", periods=n).date
    spy_r = [0.01 * math.sin(i / 3.0) for i in range(n)]
    spy_close, stock_close = [400.0], [100.0]
    for r in spy_r[1:]:
        spy_close.append(spy_close[-1] * (1 + r))
        stock_close.append(stock_close[-1] * (1 + 2 * r))

    def frame(close: list[float]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "high": [c + 1 for c in close],
                "low": [c - 1 for c in close],
                "close": close,
                "volume": [1e6] * n,
            },
            index=pd.Index(days, name="date"),
        )

    return frame(stock_close), frame(spy_close)


def test_price_series_computes_the_fixed_window_technicals() -> None:
    bars, spy = _bars()
    ps = vi.build_price_series(bars, spy)
    assert ps is not None
    close = bars["close"]
    assert ps.sessions == 300 and len(ps.closes) == 260 and len(ps.sma20s) == 260
    assert ps.close == pytest.approx(close.iloc[-1])
    assert ps.sma20 == pytest.approx(close.iloc[-20:].mean())
    assert ps.sma200 == pytest.approx(close.iloc[-200:].mean())
    assert ps.ret_6m == pytest.approx(close.iloc[-1] / close.iloc[-127] - 1)
    assert ps.beta_250 == pytest.approx(2.0, rel=1e-6)
    assert ps.adv_dollar_20 == pytest.approx((close.iloc[-20:] * 1e6).mean())


def test_price_series_is_none_without_bars() -> None:
    empty = pd.DataFrame(columns=["high", "low", "close", "volume"])
    assert vi.build_price_series(empty, None) is None


@pytest.fixture()
def research_file(tmp_path, monkeypatch):
    path = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001", name="Steady Co"))
        s.add(
            CompanyFactsRawRow(
                cik="0000000001", payload_json=json.dumps(PAYLOAD), fetched_at=datetime(2025, 9, 1)
            )
        )
        for i, d in enumerate(pd.bdate_range("2025-08-25", periods=6).date):
            s.add(
                DailyBarRow(
                    symbol="STDY", date=d, open=10, high=11, low=9, close=10 + i, volume=1e6
                )
            )
        s.add(
            FinancialRow(
                symbol="STDY",
                period_end=date(2025, 6, 30),
                period_type="quarterly",
                line_item="revenue",
                value=1.0,
                accn="q2",
                filed=date(2025, 8, 5),
            )
        )
        s.add(
            FinancialRow(
                symbol="STDY",
                period_end=date(2024, 12, 31),
                period_type="annual",
                line_item="revenue",
                value=1.0,
                accn="k24",
                filed=date(2025, 2, 10),
            )
        )
        s.commit()
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(path))
    vi.reset_engine()
    yield path
    vi.reset_engine()


def test_reads_come_from_a_read_only_research_db(research_file) -> None:
    with vi.research_read() as s:
        assert s is not None
        cik, payload = vi.read_payload(s, "STDY")
        assert cik == "0000000001" and payload is not None and payload["entityName"] == "Steady Co"
        bars = vi.read_bars(s, "STDY", date(2025, 8, 28))
        assert list(bars["close"]) == [10.0, 11.0, 12.0, 13.0]
        parts = vi.current_fingerprint_parts(s, "STDY")
        assert parts == {
            "latest_accn": "q2",
            "latest_filed": date(2025, 8, 5),
            "price_date": date(2025, 9, 1),
            "price_close": 15.0,
        }
        with pytest.raises(OperationalError):
            s.execute(text("DELETE FROM symbols"))


def test_a_missing_research_db_is_none_not_an_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    vi.reset_engine()
    with vi.research_read() as s:
        assert s is None


def test_an_unknown_symbol_has_no_payload(research_file) -> None:
    with vi.research_read() as s:
        assert s is not None
        assert vi.read_payload(s, "NOPE") == (None, None)


def test_market_facts_come_from_the_provider_and_never_raise(monkeypatch) -> None:
    class Provider:
        def get_info(self, symbol):
            return {
                "marketCap": 3.2e12,
                "sector": "Technology",
                "industry": "Internet Content & Information",
                "quoteType": "EQUITY",
            }

        def get_calendar(self, symbol):
            return {"Earnings Date": [date(2026, 2, 3), date(2026, 2, 5)]}

    monkeypatch.setattr("src.data.factory.get_fundamentals_provider", lambda: Provider())
    mf = vi.fetch_market_facts("GOOGL")
    assert (mf.market_cap, mf.industry, mf.next_earnings) == (
        3.2e12,
        "Internet Content & Information",
        date(2026, 2, 3),
    )

    class Broken:
        def get_info(self, symbol):
            raise RuntimeError("down")

        def get_calendar(self, symbol):
            raise RuntimeError("down")

    monkeypatch.setattr("src.data.factory.get_fundamentals_provider", lambda: Broken())
    assert vi.fetch_market_facts("GOOGL").market_cap is None


def test_the_regime_is_spys_effective_regime_or_unknown(monkeypatch) -> None:
    state = SimpleNamespace(spy=SimpleNamespace(effective=MarketRegime.CAUTIOUS))
    monkeypatch.setattr("src.storage.regime_state.load_regime_state", lambda: state)
    assert vi.load_regime() == "cautious"
    monkeypatch.setattr("src.storage.regime_state.load_regime_state", lambda: None)
    assert vi.load_regime() == "unknown"
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_inputs.py`
  Expected: `ModuleNotFoundError: No module named 'src.common.value_inputs'`.

- [x] **Step 3: Create `src/common/value_types.py`**

```python
"""Plain input shapes for the value book's scorecard.

docs/superpowers/specs/2026-10-28-value-swing-book-design.md §6.9. Neutral on purpose: this
module imports only the standard library and pydantic, so the pure modules of ``src/value/``,
the loader (``src/common/value_inputs.py``) and, later, the API share one definition without
any of them importing more of ``src.value`` than the fence allows.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class AnnualPeriod(BaseModel):
    """One fiscal year's line items (canonical names from config/research_concepts.yaml)."""

    period_end: date
    items: dict[str, float] = Field(default_factory=dict)
    accns: dict[str, str] = Field(default_factory=dict)


class TtmPoint(BaseModel):
    value: float
    end: date
    basis: Literal["ytd", "fy"]


class InstantPoint(BaseModel):
    value: float
    end: date


class ValueFinancials(BaseModel):
    """Everything the scorecard reads from filings, as known on one date (``as_of``)."""

    entity_name: str = ""
    has_us_gaap: bool = True
    annual: list[AnnualPeriod] = Field(default_factory=list)  # newest first
    ttm: dict[str, TtmPoint] = Field(default_factory=dict)  # duration items
    latest: dict[str, InstantPoint] = Field(default_factory=dict)  # balance-sheet items
    shares_latest: float | None = None  # newest quarterly weighted diluted count
    cover_shares: float | None = None  # dei cover page (absent for multi-class filers)
    latest_accn: str | None = None
    latest_filed: date | None = None


class PriceSeries(BaseModel):
    """Daily closes and the fixed-window technicals the scorecard reads (spec §6.6)."""

    as_of: date  # the last bar's date
    close: float
    sessions: int  # bars available up to as_of
    closes: list[float]  # ascending, at most the last 260
    sma20s: list[float | None]  # aligned with closes
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    atr14: float | None = None
    rsi14: float | None = None
    ret_6m: float | None = None  # 126-session return
    spy_ret_6m: float | None = None
    beta_250: float | None = None
    adv_dollar_20: float | None = None


class Classification(BaseModel):
    sector: str | None = None
    industry: str | None = None
    source: Literal["snapshot", "yfinance", "none"] = "none"
    is_etf: bool = False


class MarketFacts(BaseModel):
    """What the caller fetched from yfinance for one name. Never fetched by src/value."""

    market_cap: float | None = None
    sector: str | None = None
    industry: str | None = None
    quote_type: str | None = None
    next_earnings: date | None = None


class ValueInputs(BaseModel):
    """One name's complete scorecard input. ``src/value/scorecard.py`` is a pure function of
    this plus the config."""

    symbol: str
    cik: str | None = None
    as_of: date
    financials: ValueFinancials | None = None
    price: PriceSeries | None = None
    classification: Classification = Field(default_factory=Classification)
    yf_market_cap: float | None = None
    next_earnings: date | None = None
    regime: str = "unknown"  # MarketRegime value, or "unknown"
    rs_cutoff_6m: float | None = None  # the run's 30th percentile of 6-month excess return
```

- [x] **Step 4: Create `src/common/value_inputs.py`**

```python
"""The value book's input loader: one neutral, read-only module (spec §6.9, revision 3).

Reads ``data/research.db`` (``mode=ro``: the raw companyfacts payload through
``select_periods``/``select_ttm``, and daily bars) and the regime record through
``src.storage.regime_state.load_regime_state``, and computes the technical inputs with the
deterministic ``src/analytics/technicals.py``. The API and the value process load identical
inputs through it. It imports nothing from ``src.value`` and no enrichment module
(tests/test_value_fence.py), and it never writes.

``fetch_market_facts`` is the one network read here (yfinance through ``src/data``); callers
decide when to pay for it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.analytics.technicals import atr14_series, rsi14_series
from src.common.config import get_config
from src.common.value_types import (
    AnnualPeriod,
    InstantPoint,
    MarketFacts,
    PriceSeries,
    TtmPoint,
    ValueFinancials,
)
from src.research.ingest.concepts import (
    load_concept_map,
    resolve_line_item,
    select_periods,
    select_ttm,
)
from src.research.schemas import Fact
from src.research.store.models import CompanyFactsRawRow, DailyBarRow, FinancialRow, SymbolRow

log = logging.getLogger(__name__)

ANNUAL_LIMIT = 11  # ten years of history plus the newest
CLOSES_KEPT = 260
_RS_SESSIONS = 126
_BETA_SESSIONS = 250


# ── pure: filings ───────────────────────────────────────────────────────────────────────────


def _dei_cover_shares(payload: dict, as_of: date) -> float | None:
    """The newest undimensioned cover-page share count filed on or before *as_of*."""
    try:
        entries = payload["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
    except (KeyError, TypeError):
        return None
    best: tuple[str, str, float] | None = None
    for e in entries or []:
        filed, end, val = e.get("filed"), e.get("end"), e.get("val")
        if (
            not isinstance(filed, str)
            or not isinstance(end, str)
            or not isinstance(val, int | float)
        ):
            continue
        if date.fromisoformat(filed) > as_of:
            continue
        key = (end, filed, float(val))
        if best is None or key[:2] > best[:2]:
            best = key
    return best[2] if best else None


def build_value_financials(
    payload: dict, *, as_of: date, stale_item_days: int = 200
) -> ValueFinancials:
    """Every line item of the concept map, as the filings stood on *as_of* (spec §6.2).

    Annual periods keep up to ``ANNUAL_LIMIT`` fiscal years. A TTM or latest-balance item whose
    period ends more than *stale_item_days* before the newest one is dropped: a concept the
    filer stopped tagging must not pass for a current figure.
    """
    concept_map = load_concept_map()
    us_gaap = (payload.get("facts") or {}).get("us-gaap")
    fin = ValueFinancials(entity_name=str(payload.get("entityName", "")), has_us_gaap=bool(us_gaap))
    if not us_gaap:
        return fin

    annual: dict[date, AnnualPeriod] = {}
    newest_fact: Fact | None = None
    for name, spec in concept_map.items():
        facts = resolve_line_item(payload, spec)
        if not facts:
            continue
        known = [f for f in facts if f.filed <= as_of]
        if known:
            top = max(known, key=lambda f: (f.filed, f.end))
            if newest_fact is None or (top.filed, top.end) > (newest_fact.filed, newest_fact.end):
                newest_fact = top
        for f in select_periods(
            facts, kind=spec.kind, period_type="annual", limit=ANNUAL_LIMIT, as_of=as_of
        ):
            period = annual.setdefault(f.end, AnnualPeriod(period_end=f.end))
            period.items[name] = f.value
            period.accns[name] = f.accn
        if spec.kind == "duration":
            ttm = select_ttm(facts, as_of=as_of)
            if ttm is not None:
                fin.ttm[name] = TtmPoint(value=ttm.value, end=ttm.end, basis=ttm.basis)
        else:
            latest = select_periods(
                facts, kind="instant", period_type="quarterly", limit=1, as_of=as_of
            )
            if latest:
                fin.latest[name] = InstantPoint(value=latest[0].value, end=latest[0].end)
        if name == "shares_diluted":
            quarter = select_periods(
                facts, kind="duration", period_type="quarterly", limit=1, as_of=as_of
            )
            if quarter:
                fin.shares_latest = quarter[0].value

    fin.annual = [annual[k] for k in sorted(annual, reverse=True)][:ANNUAL_LIMIT]
    ends = [p.end for p in fin.ttm.values()] + [p.end for p in fin.latest.values()]
    if ends:
        cutoff = max(ends) - timedelta(days=stale_item_days)
        fin.ttm = {k: v for k, v in fin.ttm.items() if v.end >= cutoff}
        fin.latest = {k: v for k, v in fin.latest.items() if v.end >= cutoff}
    fin.cover_shares = _dei_cover_shares(payload, as_of)
    if newest_fact is not None:
        fin.latest_accn = newest_fact.accn
        fin.latest_filed = newest_fact.filed
    return fin


# ── pure: prices ────────────────────────────────────────────────────────────────────────────


def _last(series: pd.Series) -> float | None:
    if series.empty:
        return None
    v = series.iloc[-1]
    return None if pd.isna(v) else float(v)


def build_price_series(bars: pd.DataFrame, spy: pd.DataFrame | None) -> PriceSeries | None:
    """Fixed-window technicals from daily bars (columns high, low, close, volume; a date index,
    ascending, already cut at as_of). None without a single bar."""
    if bars.empty:
        return None
    close = bars["close"].astype(float)
    sma20 = close.rolling(20).mean()
    atr = atr14_series(bars["high"].astype(float), bars["low"].astype(float), close)
    rsi = rsi14_series(close)
    n = len(close)
    ret_6m = float(close.iloc[-1] / close.iloc[-1 - _RS_SESSIONS] - 1) if n > _RS_SESSIONS else None
    spy_ret = beta = None
    if spy is not None and not spy.empty:
        spy_close = spy["close"].astype(float)
        if len(spy_close) > _RS_SESSIONS:
            spy_ret = float(spy_close.iloc[-1] / spy_close.iloc[-1 - _RS_SESSIONS] - 1)
        joined = pd.concat(
            [close.pct_change(), spy_close.pct_change()], axis=1, join="inner"
        ).dropna()
        joined = joined.iloc[-_BETA_SESSIONS:]
        if len(joined) >= 60:
            var = float(joined.iloc[:, 1].var())
            if var > 0:
                beta = float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / var)
    dollar = (close * bars["volume"].astype(float)).iloc[-20:]
    tail = close.iloc[-CLOSES_KEPT:]
    return PriceSeries(
        as_of=pd.Timestamp(close.index[-1]).date(),
        close=float(close.iloc[-1]),
        sessions=n,
        closes=[float(c) for c in tail],
        sma20s=[None if pd.isna(s) else float(s) for s in sma20.iloc[-CLOSES_KEPT:]],
        sma20=_last(sma20) if n >= 20 else None,
        sma50=_last(close.rolling(50).mean()) if n >= 50 else None,
        sma200=_last(close.rolling(200).mean()) if n >= 200 else None,
        atr14=_last(atr) if n >= 15 else None,
        rsi14=_last(rsi) if n >= 15 else None,
        ret_6m=ret_6m,
        spy_ret_6m=spy_ret,
        beta_250=beta,
        adv_dollar_20=float(dollar.mean()) if len(dollar) else None,
    )


# ── I/O: read-only research.db ───────────────────────────────────────────────────────────────

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_path() -> str:
    """Filesystem path of data/research.db. Patched in tests."""
    url = get_config().research_db_url_abs()
    return url[len("sqlite:///") :] if url.startswith("sqlite:///") else url


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


@contextmanager
def research_read() -> Iterator[Session | None]:
    """A ``mode=ro`` session on research.db; None when the file does not exist."""
    global _engine, _SessionLocal
    path = _resolve_path()
    if not Path(path).exists():
        yield None
        return
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///file:{path}?mode=ro&uri=true", future=True, connect_args={"timeout": 10}
        )
        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def read_payload(session: Session, symbol: str) -> tuple[str | None, dict | None]:
    """(CIK, raw companyfacts payload) for *symbol*; None parts when missing or unparseable."""
    row = session.get(SymbolRow, symbol)
    cik = row.cik if row else None
    if not cik:
        return None, None
    raw = session.get(CompanyFactsRawRow, cik)
    if raw is None:
        return cik, None
    try:
        return cik, json.loads(raw.payload_json)
    except (json.JSONDecodeError, TypeError):
        log.warning("value_inputs: raw payload for %s is unparseable", symbol)
        return cik, None


def read_bars(session: Session, symbol: str, as_of: date) -> pd.DataFrame:
    rows = session.execute(
        select(DailyBarRow)
        .where(DailyBarRow.symbol == symbol, DailyBarRow.date <= as_of)
        .order_by(DailyBarRow.date)
    ).scalars()
    data = [
        (r.date, r.high, r.low, r.close, r.volume or 0.0)
        for r in rows
        if r.close is not None and r.high is not None and r.low is not None
    ]
    frame = pd.DataFrame(data, columns=["date", "high", "low", "close", "volume"])
    return frame.set_index("date")


def current_fingerprint_parts(session: Session, symbol: str) -> dict[str, Any]:
    """The cheap half of the ticker-file fingerprint (spec §6.9): the newest accession in
    ``financials`` and the newest bar, without parsing the raw payload."""
    fin = session.execute(
        select(FinancialRow.accn, FinancialRow.filed)
        .where(FinancialRow.symbol == symbol, FinancialRow.filed.is_not(None))
        .order_by(FinancialRow.filed.desc(), FinancialRow.accn.desc())
        .limit(1)
    ).first()
    bar = session.execute(
        select(DailyBarRow.date, DailyBarRow.close)
        .where(DailyBarRow.symbol == symbol)
        .order_by(DailyBarRow.date.desc())
        .limit(1)
    ).first()
    return {
        "latest_accn": fin[0] if fin else None,
        "latest_filed": fin[1] if fin else None,
        "price_date": bar[0] if bar else None,
        "price_close": bar[1] if bar else None,
    }


def load_regime() -> str:
    """SPY's effective market regime, or "unknown" when none is recorded."""
    from src.storage.regime_state import load_regime_state

    state = load_regime_state()
    return state.spy.effective.value if state is not None else "unknown"


def fetch_market_facts(symbol: str) -> MarketFacts:
    """yfinance market cap, sector, industry, quote type and next earnings date. Never raises;
    a failed fetch is an empty ``MarketFacts`` (the data-quality gate then says UNKNOWN)."""
    from src.data.factory import get_fundamentals_provider

    provider = get_fundamentals_provider()
    try:
        info = provider.get_info(symbol) or {}
    except Exception:  # noqa: BLE001 - a provider failure is missing data, not a crash
        info = {}
    cap = info.get("marketCap")
    next_earnings: date | None = None
    if info.get("quoteType") != "ETF":
        try:
            cal = provider.get_calendar(symbol) or {}
            for ts in cal.get("Earnings Date", []) or []:
                d = ts.date() if hasattr(ts, "date") else ts
                if isinstance(d, date):
                    next_earnings = d if next_earnings is None else min(next_earnings, d)
        except Exception:  # noqa: BLE001
            next_earnings = None
    return MarketFacts(
        market_cap=float(cap) if isinstance(cap, int | float) and cap > 0 else None,
        sector=info.get("sector") if isinstance(info.get("sector"), str) else None,
        industry=info.get("industry") if isinstance(info.get("industry"), str) else None,
        quote_type=info.get("quoteType") if isinstance(info.get("quoteType"), str) else None,
        next_earnings=next_earnings,
    )
```

- [x] **Step 5: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_inputs.py`
  Expected: 11 passed.

- [x] **Step 6: Gates**

  ```bash
  .venv/bin/ruff check src/common/value_types.py src/common/value_inputs.py tests/test_value_inputs.py
  .venv/bin/ruff format --check src/common/value_types.py src/common/value_inputs.py tests/test_value_inputs.py
  .venv/bin/mypy src/common/value_types.py src/common/value_inputs.py
  ```

- [x] **Step 7: Commit**

  ```bash
  git add src/common/value_types.py src/common/value_inputs.py tests/test_value_inputs.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): the neutral read-only input loader and its plain types"
  ```

---

### Task 4: The universes, the snapshot files and the research worker's jobs

**Files:**
- Create: `src/common/value_universe.py`, `scripts/value_universe_snapshot.py`,
  `src/research/ingest/value_universe.py`, `tests/test_value_universe.py`,
  `config/value_universe.csv`, `config/value_evidence_universe.csv` (generated)
- Modify: `src/research/ingest/materialize.py` (line 35; lines 406–412),
  `src/research/ingest/jobs.py` (line 20; before line 104)

**Interfaces:**
- Consumes: `ValueCfg.universe` (Task 1), `ROOT`; `enqueue`, `drain_ingest_jobs`,
  `ingest_daily_bars`; `effective_universe`.
- Produces: `SnapshotName`; `ValueUniverse(trading, evidence, etfs, classification,
  trading_as_of, evidence_as_of)` with `all_names()` and `tag(symbol) -> "trading" | "evidence"`;
  `normalise_symbol`, `read_snapshot(path) -> (date | None, list[SnapshotName])`,
  `build_value_universe(cfg: ValueCfg, universe: dict) -> ValueUniverse`;
  `enqueue_value_universe(names: list[str] | None = None, *, today: date | None = None) ->
  dict[str, int]` (keys `fundamentals`, `prices`, `no_cik`); job kind `"prices"`; scheduler job
  id `value_sweep`; the snapshot script's `parse_constituents`, `sp500_rows`, `sp100_rows`,
  `write_snapshot`, `main`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_universe.py`

```python
"""The value book's universes, the snapshot builder, and the research worker's sweep (Part 1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

import src.common.value_universe as vu
from scripts.value_universe_snapshot import parse_constituents, sp100_rows, sp500_rows
from src.common.config import ValueCfg

SP500_HTML = """
<table class="wikitable" id="constituents"><tbody>
<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th>
<th>Headquarters Location</th><th>Date added</th><th>CIK</th><th>Founded</th></tr>
<tr><td><a href="x">BRK.B</a></td><td>Berkshire Hathaway</td><td>Financials</td>
<td>Multi-Sector Holdings</td><td>Omaha</td><td>2010-02-16</td><td>0001067983</td><td>1839</td></tr>
<tr><td>GOOG</td><td>Alphabet Inc. (Class C)</td><td>Communication Services</td>
<td>Interactive Media &amp; Services</td><td>Mountain View</td><td>2006-04-03</td><td>0001652044</td><td>1998</td></tr>
<tr><td>GOOGL</td><td>Alphabet Inc. (Class A)</td><td>Communication Services</td>
<td>Interactive Media &amp; Services</td><td>Mountain View</td><td>2014-04-03</td><td>0001652044</td><td>1998</td></tr>
<tr><td>BAC</td><td>Bank of America</td><td>Financials</td><td>Diversified Banks</td>
<td>Charlotte</td><td>1976-06-30</td><td>0000070858</td><td>1998</td></tr>
</tbody></table>
<table id="other"><tr><th>x</th></tr><tr><td>y</td></tr></table>
"""

SP100_HTML = """
<table class="wikitable sortable" id="constituents"><tbody>
<tr><th>Symbol</th><th>Name</th><th>Sector</th></tr>
<tr><td>BAC</td><td>Bank of America</td><td>Financials</td></tr>
<tr><td>NEWCO</td><td>New Co</td><td>Industrials</td></tr>
</tbody></table>
"""


def test_the_snapshot_parser_reads_the_constituents_table_only() -> None:
    rows = parse_constituents(SP500_HTML)
    assert [r["Symbol"] for r in rows] == ["BRK.B", "GOOG", "GOOGL", "BAC"]
    assert rows[1]["GICS Sub-Industry"] == "Interactive Media & Services"


def test_sp500_rows_use_dashed_class_tickers_and_ten_digit_ciks() -> None:
    rows = sp500_rows(SP500_HTML)
    assert rows[0] == {
        "symbol": "BRK-B",
        "name": "Berkshire Hathaway",
        "sector": "Financials",
        "industry": "Multi-Sector Holdings",
        "cik": "0001067983",
    }


def test_sp100_rows_take_the_sp500_industry_and_keep_names_it_lacks() -> None:
    rows = sp100_rows(SP100_HTML, sp500_rows(SP500_HTML))
    assert rows[0]["industry"] == "Diversified Banks"
    assert rows[1] == {
        "symbol": "NEWCO",
        "name": "New Co",
        "sector": "Industrials",
        "industry": "",
        "cik": "",
    }


def _write(path, rows: list[str], as_of: str = "2026-10-29") -> None:
    path.write_text(
        f"# as_of: {as_of} source: test\nsymbol,name,sector,industry,cik\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )


def test_read_snapshot_returns_its_date_and_rows(tmp_path) -> None:
    p = tmp_path / "snap.csv"
    _write(p, ["BRK.B,Berkshire,Financials,Multi-Sector Holdings,1067983"])
    as_of, rows = vu.read_snapshot(p)
    assert as_of == date(2026, 10, 29)
    assert rows[0].symbol == "BRK-B" and rows[0].cik == "0001067983"
    assert vu.read_snapshot(tmp_path / "absent.csv") == (None, [])


def test_the_universes_merge_lists_snapshots_and_share_classes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vu, "ROOT", tmp_path)
    _write(tmp_path / "trading.csv", ["BAC,Bank of America,Financials,Diversified Banks,70858"])
    _write(
        tmp_path / "evidence.csv",
        [
            "BAC,Bank of America,Financials,Diversified Banks,70858",
            "GOOG,Alphabet C,Communication Services,Interactive Media & Services,1652044",
            "GOOGL,Alphabet A,Communication Services,Interactive Media & Services,1652044",
        ],
    )
    cfg = ValueCfg(
        universe={"trading_snapshot": "trading.csv", "evidence_snapshot": "evidence.csv"}
    )
    universe = {
        "indexes": ["QQQ"],
        "leveraged_etfs": ["SOXL"],
        "would_own": ["GOOGL", "QQQ", "HIMS"],
        "watchlist": ["META"],
    }
    out = vu.build_value_universe(cfg, universe)
    assert out.trading == ["BAC", "GOOGL", "HIMS", "META", "QQQ"]
    assert out.evidence == ["BAC", "GOOGL"]  # GOOG scored once, as GOOGL
    assert out.etfs == {"QQQ", "SOXL"}
    assert out.classification["GOOGL"] == ("Communication Services", "Interactive Media & Services")
    assert out.all_names() == ["BAC", "GOOGL", "HIMS", "META", "QQQ"]
    assert (out.tag("HIMS"), out.tag("BAC")) == ("trading", "trading")
    assert out.trading_as_of == date(2026, 10, 29)


def test_the_committed_snapshots_exist_and_are_dated() -> None:
    from src.common.config import ROOT, get_config

    cfg = get_config().value
    for rel, low, high in (
        (cfg.universe.trading_snapshot, 95, 110),
        (cfg.universe.evidence_snapshot, 495, 510),
    ):
        as_of, rows = vu.read_snapshot(ROOT / rel)
        assert as_of is not None, rel
        assert low <= len(rows) <= high, (rel, len(rows))


# ── the research worker's side ──────────────────────────────────────────────────────────────


@pytest.fixture()
def research_db(tmp_path, monkeypatch):
    from src.research.store.session import init_research_db

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def test_the_sweep_queues_only_what_each_name_lacks(research_db) -> None:
    from src.research.ingest.value_universe import enqueue_value_universe
    from src.research.store.models import CompanyFactsRawRow, DailyBarRow, IngestJobRow, SymbolRow
    from src.research.store.session import research_session

    today = date(2026, 10, 29)
    now = datetime.now(UTC).replace(tzinfo=None)
    with research_session() as s:
        s.add(SymbolRow(symbol="FRESH", cik="0000000001"))
        s.add(SymbolRow(symbol="STALE", cik="0000000002"))
        s.add(CompanyFactsRawRow(cik="0000000001", payload_json="{}", fetched_at=now))
        s.add(
            CompanyFactsRawRow(
                cik="0000000002", payload_json="{}", fetched_at=now - timedelta(days=3)
            )
        )
        for i in range(260):
            s.add(DailyBarRow(symbol="FRESH", date=today - timedelta(days=260 - i), close=1.0))
    counts = enqueue_value_universe(["FRESH", "STALE", "NOCIK"], today=today)
    assert counts == {"fundamentals": 1, "prices": 2, "no_cik": 1}
    with research_session() as s:
        jobs = sorted((j.symbol, j.kind) for j in s.query(IngestJobRow))
    assert jobs == [("NOCIK", "prices"), ("STALE", "fundamentals"), ("STALE", "prices")]


def test_the_drain_runs_a_prices_job(research_db, monkeypatch) -> None:
    from src.research.ingest import materialize
    from src.research.store.models import IngestJobRow
    from src.research.store.session import research_session

    calls: list[str] = []
    monkeypatch.setattr(
        materialize, "ingest_daily_bars", lambda symbol: calls.append(symbol) or 250
    )
    materialize.enqueue("MU", "prices")
    assert materialize.drain_ingest_jobs() == 1
    assert calls == ["MU"]
    with research_session() as s:
        assert s.query(IngestJobRow).one().status == "done"


def test_a_prices_job_with_no_bars_is_retried_then_failed(research_db, monkeypatch) -> None:
    from src.research.ingest import materialize
    from src.research.store.models import IngestJobRow
    from src.research.store.session import research_session

    monkeypatch.setattr(materialize, "ingest_daily_bars", lambda symbol: 0)
    materialize.enqueue("ZZZZ", "prices")
    for _ in range(3):
        materialize.drain_ingest_jobs()
    with research_session() as s:
        job = s.query(IngestJobRow).one()
    assert (job.status, job.attempts) == ("failed", 3)
    assert "No daily bars" in (job.last_error or "")


def test_the_scheduler_adds_the_sweep_only_when_enabled(monkeypatch) -> None:
    from src.common.config import get_config
    from src.research.ingest.jobs import build_scheduler

    assert "value_sweep" not in {j.id for j in build_scheduler().get_jobs()}
    monkeypatch.setattr(get_config().value.research_sweep, "enabled", True)
    assert "value_sweep" in {j.id for j in build_scheduler().get_jobs()}
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_universe.py`
  Expected: `ModuleNotFoundError: No module named 'src.common.value_universe'`.

- [x] **Step 3: Create `src/common/value_universe.py`**

```python
"""The value book's two universes (spec §6.1). Neutral: the research worker's nightly sweep
and the value process read the same lists through it.

- **Trading universe**: ``universe.yaml``'s ``would_own`` + ``watchlist`` plus the trading
  snapshot (S&P 100). The names the strip shows and Stage 3 may act on.
- **Evidence universe**: the wider snapshot (S&P 500), scored by the same code for the shadow
  ledger only.

Snapshots are committed CSVs (``symbol,name,sector,industry,cik``) whose first line is
``# as_of: YYYY-MM-DD source: ...``; ``scripts/value_universe_snapshot.py`` rebuilds them.
A second share class of one filer is scored once, under its primary ticker.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.common.config import ROOT, ValueCfg

SNAPSHOT_COLUMNS = ("symbol", "name", "sector", "industry", "cik")


@dataclass(frozen=True, slots=True)
class SnapshotName:
    symbol: str
    name: str
    sector: str
    industry: str
    cik: str


@dataclass(slots=True)
class ValueUniverse:
    trading: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    etfs: set[str] = field(default_factory=set)
    classification: dict[str, tuple[str, str]] = field(default_factory=dict)  # sector, industry
    trading_as_of: date | None = None
    evidence_as_of: date | None = None

    def all_names(self) -> list[str]:
        return sorted(set(self.trading) | set(self.evidence))

    def tag(self, symbol: str) -> str:
        return "trading" if symbol in set(self.trading) else "evidence"


def normalise_symbol(raw: str) -> str:
    """EDGAR and yfinance spell a class share with a dash (BRK-B), Wikipedia with a dot."""
    return raw.strip().upper().replace(".", "-")


def read_snapshot(path: Path) -> tuple[date | None, list[SnapshotName]]:
    """``(as_of, rows)``; a missing file is ``(None, [])``."""
    if not path.exists():
        return None, []
    as_of: date | None = None
    rows: list[SnapshotName] = []
    with path.open(encoding="utf-8", newline="") as fh:
        lines = fh.read().splitlines()
    data = []
    for line in lines:
        if line.startswith("#"):
            if "as_of:" in line:
                token = line.split("as_of:", 1)[1].split()[0]
                as_of = date.fromisoformat(token)
            continue
        data.append(line)
    for rec in csv.DictReader(data):
        rows.append(
            SnapshotName(
                symbol=normalise_symbol(rec["symbol"]),
                name=rec.get("name", ""),
                sector=rec.get("sector", ""),
                industry=rec.get("industry", ""),
                cik=(rec.get("cik") or "").zfill(10) if rec.get("cik") else "",
            )
        )
    return as_of, rows


def _primary(symbol: str, share_class_primary: dict[str, str]) -> str:
    return share_class_primary.get(symbol, symbol)


def build_value_universe(cfg: ValueCfg, universe: dict[str, Any]) -> ValueUniverse:
    """Both universes from the config, *universe* (``effective_universe()`` or a YAML the
    caller read) and the two snapshots."""
    primary = {k.upper(): v.upper() for k, v in cfg.universe.share_class_primary.items()}
    trading_as_of, trading_rows = read_snapshot(ROOT / cfg.universe.trading_snapshot)
    evidence_as_of, evidence_rows = read_snapshot(ROOT / cfg.universe.evidence_snapshot)
    out = ValueUniverse(trading_as_of=trading_as_of, evidence_as_of=evidence_as_of)
    for row in [*evidence_rows, *trading_rows]:
        out.classification[_primary(row.symbol, primary)] = (row.sector, row.industry)
    out.etfs = {
        normalise_symbol(str(s))
        for key in ("indexes", "leveraged_etfs")
        for s in universe.get(key) or []
    }
    lists = {
        normalise_symbol(str(s))
        for key in ("would_own", "watchlist")
        for s in universe.get(key) or []
    }
    out.trading = sorted({_primary(s, primary) for s in lists | {r.symbol for r in trading_rows}})
    out.evidence = sorted({_primary(r.symbol, primary) for r in evidence_rows})
    return out
```

- [x] **Step 4: Create `scripts/value_universe_snapshot.py`**

```python
"""Rebuild the value book's committed universe snapshots (spec §6.1).

    python -m scripts.value_universe_snapshot [--as-of YYYY-MM-DD]

Writes ``config/value_evidence_universe.csv`` (S&P 500) and ``config/value_universe.csv``
(S&P 100, its sector and industry joined from the S&P 500 table), each headed by
``# as_of: <date> source: ...``. Source: the constituents tables of Wikipedia's "List of S&P 500
companies" and "S&P 100" pages, through the MediaWiki parse API (the plain page refuses
scripted clients). Network only; touches no database. Review the diff before committing.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "https://en.wikipedia.org/w/api.php"
# Wikimedia refuses a client without a contact URL in its User-Agent.
USER_AGENT = "IBKR-Income-System/1.0 (https://github.com/IandominusRex)"
SP500_PAGE = "List of S&P 500 companies"
SP100_PAGE = "S&P 100"
COLUMNS = ("symbol", "name", "sector", "industry", "cik")


class ConstituentsTable(HTMLParser):
    """Collects the text of every cell of the ``<table id="constituents">``, row by row."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._inside = False
        self._depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            if self._inside:
                self._depth += 1
            elif dict(attrs).get("id") == "constituents":
                self._inside, self._depth = True, 0
        if not self._inside:
            return
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if not self._inside:
            return
        if tag == "table":
            if self._depth == 0:
                self._inside = False
            else:
                self._depth -= 1
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_constituents(html: str) -> list[dict[str, str]]:
    """The constituents table as dicts keyed by its header cells."""
    table = ConstituentsTable()
    table.feed(html)
    if not table.rows:
        raise ValueError("no constituents table in the page")
    header, *body = table.rows
    return [dict(zip(header, row, strict=False)) for row in body if len(row) >= len(header)]


def fetch_page(page: str) -> str:
    resp = httpx.get(
        API,
        params={
            "action": "parse",
            "page": page,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return str(resp.json()["parse"]["text"])


def sp500_rows(html: str) -> list[dict[str, str]]:
    out = []
    for rec in parse_constituents(html):
        out.append(
            {
                "symbol": rec["Symbol"].replace(".", "-"),
                "name": rec["Security"],
                "sector": rec["GICS Sector"],
                "industry": rec["GICS Sub-Industry"],
                "cik": rec.get("CIK", "").zfill(10) if rec.get("CIK") else "",
            }
        )
    return out


def sp100_rows(html: str, sp500: list[dict[str, str]]) -> list[dict[str, str]]:
    by_symbol = {r["symbol"]: r for r in sp500}
    out = []
    for rec in parse_constituents(html):
        symbol = rec["Symbol"].replace(".", "-")
        joined = by_symbol.get(symbol)
        out.append(
            joined
            if joined is not None
            else {
                "symbol": symbol,
                "name": rec["Name"],
                "sector": rec["Sector"],
                "industry": "",
                "cik": "",
            }
        )
    return out


def write_snapshot(path: Path, rows: list[dict[str, str]], as_of: date, source: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(f"# as_of: {as_of.isoformat()} source: {source}\n")
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["symbol"]):
            writer.writerow({k: row.get(k, "") for k in COLUMNS})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    sp500 = sp500_rows(fetch_page(SP500_PAGE))
    sp100 = sp100_rows(fetch_page(SP100_PAGE), sp500)
    write_snapshot(
        ROOT / "config" / "value_evidence_universe.csv",
        sp500,
        args.as_of,
        f"Wikipedia, {SP500_PAGE}",
    )
    write_snapshot(
        ROOT / "config" / "value_universe.csv", sp100, args.as_of, f"Wikipedia, {SP100_PAGE}"
    )
    print(f"S&P 500: {len(sp500)} rows; S&P 100: {len(sp100)} rows; as of {args.as_of}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 5: Generate and inspect the snapshots**

  ```bash
  .venv/bin/python -m py_compile scripts/value_universe_snapshot.py
  .venv/bin/python -m scripts.value_universe_snapshot
  head -3 config/value_universe.csv
  ```

  Expected: `S&P 500: 50x rows; S&P 100: 10x rows; as of <today>` (503 and 101 on 2026-10-29); the
  head shows `# as_of: …`, `symbol,name,sector,industry,cik`, then `AAPL,…`. If the API refuses,
  stop and report (do not hand-write the files).

- [x] **Step 6: Add the `prices` job kind.** In `src/research/ingest/materialize.py`, after line
  35 add `from src.research.ingest.prices import ingest_daily_bars`; replace lines 406–412 (the
  `if kind == "fundamentals" and cik:` … `error = f"Cannot run job kind …"` block) with:

  ```python
          if kind == "fundamentals" and cik:
              try:
                  ingest_fundamentals(symbol, cik)
              except Exception as exc:
                  error = str(exc)
          elif kind == "prices":
              # Daily bars for a name no warm tier covers (the value book's universes, spec §6.1).
              try:
                  if ingest_daily_bars(symbol) == 0:
                      error = f"No daily bars returned for {symbol}"
              except Exception as exc:
                  error = str(exc)
          else:
              error = f"Cannot run job kind {kind!r} for {symbol}"
  ```

- [x] **Step 7: Create `src/research/ingest/value_universe.py`**

```python
"""The research worker's nightly sweep for the value book (spec §6.1, §6.9).

The research worker owns every SEC and price fetch; the value process only reads research.db.
This queues a ``fundamentals`` job (companyfacts, ETag-reused) for every name whose raw payload
is missing or older than a day, and a ``prices`` job for every name whose daily bars are short
or stale, across both value universes. ``drain_ingest_jobs`` runs them at its own pace (EDGAR is
rate-limited to 10 requests a second in ``EdgarClient``).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from src.common.config import get_config
from src.common.value_universe import build_value_universe
from src.research.ingest.materialize import enqueue
from src.research.store.models import CompanyFactsRawRow, DailyBarRow, SymbolRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

MIN_BARS = 260
FACTS_MAX_AGE = timedelta(days=1)
BARS_MAX_AGE_DAYS = 4  # a long weekend is not stale


def value_names() -> list[str]:
    from src.common.universe import effective_universe

    cfg = get_config()
    return build_value_universe(cfg.value, effective_universe()).all_names()


def enqueue_value_universe(
    names: list[str] | None = None, *, today: date | None = None
) -> dict[str, int]:
    """Queue what each name lacks. Returns counts: fundamentals, prices, no_cik."""
    names = names if names is not None else value_names()
    today = today or datetime.now(UTC).date()
    now = datetime.now(UTC).replace(tzinfo=None)
    counts = {"fundamentals": 0, "prices": 0, "no_cik": 0}
    with research_session() as s:
        ciks = {r.symbol: r.cik for r in s.query(SymbolRow).filter(SymbolRow.symbol.in_(names))}
        fetched = {r.cik: r.fetched_at for r in s.query(CompanyFactsRawRow)}
        bars = {
            sym: (n, last)
            for sym, n, last in s.execute(
                select(DailyBarRow.symbol, func.count(), func.max(DailyBarRow.date))
                .where(DailyBarRow.symbol.in_(names))
                .group_by(DailyBarRow.symbol)
            )
        }
    for symbol in names:
        cik = ciks.get(symbol)
        if not cik:
            counts["no_cik"] += 1
        else:
            at = fetched.get(cik)
            if at is None or now - at.replace(tzinfo=None) > FACTS_MAX_AGE:
                enqueue(symbol, "fundamentals")
                counts["fundamentals"] += 1
        n, last = bars.get(symbol, (0, None))
        if n < MIN_BARS or last is None or (today - last).days > BARS_MAX_AGE_DAYS:
            enqueue(symbol, "prices")
            counts["prices"] += 1
    log.info("Value sweep queued %s for %d names", counts, len(names))
    return counts
```

- [x] **Step 8: Schedule the sweep.** In `src/research/ingest/jobs.py`, after line 20 add
  `from src.research.ingest.value_universe import enqueue_value_universe`; immediately before
  the `sched.add_job(` whose first argument is `lambda: run_job("quotes", refresh_quotes),`
  (line 104) insert:

  ```python
      sweep = get_config().value.research_sweep
      if sweep.enabled:
          # The value book's two universes (spec §6.1): companyfacts and bars for ~520 names.
          sched.add_job(
              lambda: run_job("value_sweep", enqueue_value_universe),
              CronTrigger(hour=sweep.hour_et, minute=0),
              id="value_sweep",
              replace_existing=True,
          )
  ```

- [x] **Step 9: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_universe.py tests/test_research_materialize.py tests/test_research_worker.py`
  Expected: all pass (`test_value_universe.py`: 10 passed).

- [x] **Step 10: Gates**

  ```bash
  .venv/bin/ruff check src/common/value_universe.py src/research scripts/value_universe_snapshot.py tests/test_value_universe.py
  .venv/bin/ruff format --check src/common/value_universe.py src/research/ingest/value_universe.py src/research/ingest/materialize.py src/research/ingest/jobs.py scripts/value_universe_snapshot.py tests/test_value_universe.py
  .venv/bin/mypy src/common/value_universe.py src/research
  ```

- [x] **Step 11: Commit**

  ```bash
  git add src/common/value_universe.py scripts/value_universe_snapshot.py src/research/ingest/value_universe.py src/research/ingest/materialize.py src/research/ingest/jobs.py tests/test_value_universe.py config/value_universe.csv config/value_evidence_universe.csv docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): the trading and evidence universes, their snapshots, and the research worker's prices job and sweep"
  ```

**Section A exit (orchestrator):** `git log --oneline main..HEAD | wc -l` → `4`;
`.venv/bin/python -m pytest -q` → baseline + 38 passed; `.venv/bin/ruff check .` and
`.venv/bin/mypy src` clean; the protected-file diff prints nothing. Then ask the operator.

---

## Section B — The scorecard (Tasks 5–9) · model: sonnet

Pure functions from `ValueInputs` and `ValueCfg` to a `ValueScorecard`: per-year figures, the
three accounting scores, the gates, the valuation methods, timing and the verdict. Every number
in these tests was computed by the plan's author on a working prototype of exactly this code.

**Spec to read:** §6.0, §6.3, §6.4, §6.5, §6.6, §6.7 (Python's baseline only — Claude's verdict
is Part 4), §9.6 first bullet (margin of safety by regime).

**Files the subagent reads:** this section; `src/common/value_types.py`, `src/common/config.py`'s
value block (Task 1), `src/research/ingest/concepts.py` (`load_concept_map` only),
`src/common/schemas.py` (`class MarketRegime`, line 52), `src/value/ruleset.py`.

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **B1. Section A landed.** `git log --oneline main..HEAD | wc -l` prints `4`; Tasks 1–4 are
  ticked with commits in the Progress log.
- [ ] **B2. Green.** `.venv/bin/python -m pytest -q` (baseline + 38), `.venv/bin/ruff check .`,
  `.venv/bin/mypy src`.
- [ ] **B3. The inputs Section B builds on are what Section A produced.** Each prints a line:

  ```bash
  grep -n "^class ValueInputs\|^class ValueFinancials\|^class PriceSeries\|^class Classification" src/common/value_types.py
  grep -n "^def ruleset_id" src/value/ruleset.py
  grep -n "^class ValueRulesCfg\|^class ValueValuationCfg\|^class ValueTimingCfg\|^class ValueTickerFileCfg\|^class ValueCfg" src/common/config.py
  grep -n "    assumed_interest_rate: float = 0.08\|    recent_report_days: int = 70" src/common/config.py
  .venv/bin/python -c "from src.research.ingest.concepts import load_concept_map as m; print(sorted({'sbc','shares_outstanding','cet1_ratio','premiums_earned'} - set(m())))"
  ```

  The last prints `[]`.
- [ ] **B4. Nothing exists yet under the names Section B creates.** Prints nothing:

  ```bash
  ls src/value/schemas.py src/value/metrics.py src/value/scores.py src/value/gates.py src/value/valuation.py src/value/timing.py src/value/scorecard.py tests/value_fixtures.py 2>/dev/null
  ```

**Section exit:** five more commits (9 in all); full gate green with pytest = baseline + 115.

---

### Task 5: Output schemas, per-year metrics and the test fixtures

**Files:**
- Create: `src/value/schemas.py`, `src/value/metrics.py`, `tests/value_fixtures.py`,
  `tests/test_value_metrics.py`

**Interfaces:**
- Produces (`schemas.py`): `GateState`, `Verdict`, `ListName`, `CompanyClass`, `MethodName`,
  `MethodState` (Literals); `LISTS = ("deep_value", "quality_growth")`; `Check(id, state, actual,
  threshold, detail)`; `combine(checks) -> GateState`; `MethodValue`; `ListEvaluation`
  (`list_name, entry, entry_checks, methods, fair_value, required_mos_pct, margin_of_safety,
  entry_ceiling, timing, timing_checks, verdict, reasons, mos_review`); `Fingerprint` with
  `key() -> str`; `ValueScorecard` with `verdict_for(list_name) -> str`.
- Produces (`metrics.py`): `Year` (frozen dataclass; properties `fcf`, `gross_margin`,
  `fcf_margin`, `tangible_equity`); `ShareNormalisation(adjustments, unexplained)`;
  `normalise_shares(newest, annual, ends)`; `build_years(fin) -> (list[Year], ShareNormalisation)`;
  `cagr(series, max_years=5, min_years=4)`; `last_n`, `median_of`, `stdev_of`, `count_positive`;
  `roic(y)`; `SPLIT_RATIO = 1.8`.
- Produces (`tests/value_fixtures.py`): `AS_OF = date(2026, 3, 31)`, `YEAR_ENDS`, `STEADY`,
  `BANK`, `DURATION`, `financials(table=None, *, filed=…, accn=…, **overrides)`, `price(close, *,
  sma200=None, closes=None, ret_6m=0.05, spy_ret_6m=0.03, sessions=400)`, `inputs(*, symbol="STDY",
  fin=None, close=30.0, price_series=None, industry="Application Software", is_etf=False,
  yf_market_cap=None, next_earnings=AS_OF+60d, regime="normal", rs_cutoff_6m=-0.10)`.
  (`companyfacts()` is appended in Task 13.)

- [x] **Step 1: Create the fixtures** — `tests/value_fixtures.py` (a helper, not a test file):

```python
"""Synthetic companies for the value book's tests (Part 1). Values in $ millions, shares in
millions, so per-share figures are dollars."""

from __future__ import annotations

from datetime import date, timedelta

from src.common.value_types import (
    AnnualPeriod,
    Classification,
    InstantPoint,
    PriceSeries,
    TtmPoint,
    ValueFinancials,
    ValueInputs,
)

AS_OF = date(2026, 3, 31)
YEAR_ENDS = [date(y, 12, 31) for y in (2025, 2024, 2023, 2022, 2021)]

# "Steady Co": a healthy grower, newest year first.
STEADY: dict[str, list[float]] = {
    "revenue": [1600, 1420, 1270, 1130, 1000],
    "gross_profit": [960, 852, 762, 678, 600],
    "operating_income": [400, 355, 317.5, 282.5, 250],
    "net_income": [300, 266, 238, 212, 187],
    "operating_cash_flow": [380, 335, 300, 268, 240],
    "capital_expenditure": [80, 75, 70, 66, 60],
    "sbc": [40, 36, 32, 29, 26],
    "depreciation_amortization": [60, 55, 50, 46, 42],
    "interest_expense": [10, 10, 10, 10, 10],
    "pretax_income": [380, 337, 300, 268, 236],
    "income_tax": [80, 71, 62, 56, 49],
    "sga": [300, 270, 240, 215, 190],
    "total_assets": [3000, 2800, 2600, 2450, 2300],
    "total_liabilities": [1200, 1150, 1100, 1060, 1020],
    "stockholders_equity": [1800, 1650, 1500, 1390, 1280],
    "current_assets": [1200, 1100, 1000, 950, 900],
    "current_liabilities": [600, 580, 560, 540, 520],
    "long_term_debt": [400, 420, 440, 460, 480],
    "cash_and_equivalents": [500, 450, 400, 350, 300],
    "accounts_receivable": [200, 180, 160, 145, 130],
    "ppe_net": [900, 850, 800, 760, 720],
    "retained_earnings": [1500, 1300, 1120, 960, 820],
    "shares_diluted": [100, 101, 102, 103, 104],
}

DURATION = {
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "net_income_common",
    "operating_cash_flow",
    "capital_expenditure",
    "sbc",
    "depreciation_amortization",
    "interest_expense",
    "pretax_income",
    "income_tax",
    "sga",
    "shares_diluted",
    "net_charge_offs",
    "premiums_earned",
    "benefits_losses_expenses",
}


def financials(
    table: dict[str, list[float | None]] | None = None,
    *,
    filed: date = date(2026, 2, 10),
    accn: str = "0000000001-26-000001",
    **overrides: list[float | None],
) -> ValueFinancials:
    """A ValueFinancials whose TTM and latest balance sheet equal the newest fiscal year."""
    data: dict[str, list[float | None]] = {k: list(v) for k, v in (table or STEADY).items()}
    data.update(overrides)
    n = max(len(v) for v in data.values())
    annual = []
    for i in range(n):
        items = {k: float(v[i]) for k, v in data.items() if i < len(v) and v[i] is not None}
        annual.append(
            AnnualPeriod(
                period_end=YEAR_ENDS[i] if i < 5 else date(2020 - (i - 5), 12, 31),
                items=items,
                accns={k: accn for k in items},
            )
        )
    newest = annual[0]
    return ValueFinancials(
        entity_name="Steady Co",
        annual=annual,
        ttm={
            k: TtmPoint(value=v, end=newest.period_end, basis="fy")
            for k, v in newest.items.items()
            if k in DURATION
        },
        latest={
            k: InstantPoint(value=v, end=newest.period_end)
            for k, v in newest.items.items()
            if k not in DURATION
        },
        shares_latest=newest.items.get("shares_diluted"),
        cover_shares=newest.items.get("shares_diluted"),
        latest_accn=accn,
        latest_filed=filed,
    )


def price(
    close: float,
    *,
    sma200: float | None = None,
    closes: list[float] | None = None,
    ret_6m: float | None = 0.05,
    spy_ret_6m: float | None = 0.03,
    sessions: int = 400,
) -> PriceSeries:
    """A price series ending at *close*. By default a gentle rise with a dip and recovery
    inside the last 63 sessions (deep-value timing passes) and the close above its 200-day
    average."""
    if closes is None:
        closes = [close * (0.80 + 0.20 * i / 259) for i in range(260)]
        for j in range(200, 230):  # a dip, then a recovery above the 20-day average
            closes[j] *= 0.96
        closes[-1] = close
    sma20s: list[float | None] = [
        None if i < 19 else sum(closes[i - 19 : i + 1]) / 20 for i in range(len(closes))
    ]
    avg200 = sum(closes[-200:]) / 200 if sma200 is None else sma200
    return PriceSeries(
        as_of=AS_OF,
        close=close,
        sessions=sessions,
        closes=closes,
        sma20s=sma20s,
        sma20=sma20s[-1],
        sma50=sum(closes[-50:]) / 50,
        sma200=avg200,
        atr14=close * 0.02,
        rsi14=55.0,
        ret_6m=ret_6m,
        spy_ret_6m=spy_ret_6m,
        beta_250=1.0,
        adv_dollar_20=close * 5_000_000,
    )


def inputs(
    *,
    symbol: str = "STDY",
    fin: ValueFinancials | None = None,
    close: float = 30.0,
    price_series: PriceSeries | None = None,
    industry: str | None = "Application Software",
    is_etf: bool = False,
    yf_market_cap: float | None = None,
    next_earnings: date | None = AS_OF + timedelta(days=60),
    regime: str = "normal",
    rs_cutoff_6m: float | None = -0.10,
) -> ValueInputs:
    fin = fin if fin is not None else financials()
    series = price_series if price_series is not None else price(close)
    shares = fin.cover_shares or fin.shares_latest or 0.0
    return ValueInputs(
        symbol=symbol,
        cik="0000000001",
        as_of=AS_OF,
        financials=fin,
        price=series,
        classification=Classification(
            sector="Information Technology", industry=industry, source="snapshot", is_etf=is_etf
        ),
        yf_market_cap=yf_market_cap if yf_market_cap is not None else shares * series.close,
        next_earnings=next_earnings,
        regime=regime,
        rs_cutoff_6m=rs_cutoff_6m,
    )


# "Harbour Bank": a healthy bank, newest year first (CET1 is not tagged, as at BAC and JPM).
BANK: dict[str, list[float | None]] = {
    "revenue": [100, 96, 92, 88, 85],
    "net_income": [30, 28, 27, 25, 22],
    "net_income_common": [29, 27, 26, 24, 21],
    "total_assets": [3000, 2900, 2800, 2700, 2600],
    "total_liabilities": [2700, 2615, 2530, 2445, 2360],
    "stockholders_equity": [300, 285, 270, 255, 240],
    "goodwill": [60, 60, 60, 60, 60],
    "intangibles": [5, 5, 5, 5, 5],
    "preferred_equity": [20, 20, 20, 20, 20],
    "shares_diluted": [10.0, 10.2, 10.4, 10.6, 10.8],
    "net_charge_offs": [2.0, 1.8, 1.6, 1.4, 1.5],
    "loans": [1000, 950, 900, 850, 800],
    "cash_and_equivalents": [200, 190, 180, 170, 160],
    "long_term_debt": [300, 290, 280, 270, 260],
}
```

- [x] **Step 2: Write the failing tests** — `tests/test_value_metrics.py`

```python
"""src/value/metrics.py: per-year figures, split normalisation, series helpers (Part 1)."""

from __future__ import annotations

from datetime import date

import pytest

from src.value.metrics import (
    build_years,
    cagr,
    count_positive,
    median_of,
    normalise_shares,
    roic,
    stdev_of,
)
from tests.value_fixtures import financials

ENDS = [date(y, 12, 31) for y in (2025, 2024, 2023, 2022, 2021, 2020)]


def test_a_twenty_for_one_split_rescales_every_older_year() -> None:
    shares, note = normalise_shares(12.3, [12.23, 12.45, 12.72, 13.16, 0.68, 0.69], ENDS)
    assert shares[4] == pytest.approx(13.6) and shares[5] == pytest.approx(13.8)
    assert shares[:4] == [12.23, 12.45, 12.72, 13.16]
    assert note.adjustments == ["shares FY2021 and earlier x20 (split)"]
    assert note.unexplained == []


def test_a_split_after_the_last_10k_rescales_the_whole_series() -> None:
    shares, note = normalise_shares(24.3, [2.43, 2.45, 2.47, 2.48, 0.62, 0.61], ENDS)
    assert shares[0] == pytest.approx(24.3) and shares[5] == pytest.approx(24.4)
    assert note.adjustments == [
        "shares FY2025 and earlier x10 (split)",
        "shares FY2021 and earlier x4 (split)",
    ]


def test_an_acquisition_sized_change_is_left_alone() -> None:
    shares, note = normalise_shares(None, [100, 101, 137, 140, 141, 142], ENDS)
    assert shares == [100, 101, 137, 140, 141, 142]
    assert note.adjustments == [] and note.unexplained == []


def test_a_jump_that_is_no_split_is_unexplained() -> None:
    _, note = normalise_shares(None, [100, 37, 37, 37, 37, 37], ENDS)
    assert note.unexplained == ["share count jumps 2.70x into FY2024"]


def test_cagr_uses_up_to_five_years_and_needs_positive_ends() -> None:
    assert cagr([200, None, 150, 120, 110, 100]) == pytest.approx(2 ** (1 / 5) - 1)
    assert cagr([200, 180, 160, 140, 100]) == pytest.approx(2 ** (1 / 4) - 1)  # 4-year span
    assert cagr([200, 150, None, None, None]) is None
    assert cagr([-1, 1, 1, 1, 1]) is None


def test_series_helpers_ignore_missing_years() -> None:
    assert median_of([5, None, 1, 3, 9, 100]) == 4.0  # the newest five: 5, 1, 3, 9
    assert stdev_of([1.0, None]) is None
    assert stdev_of([2.0, 4.0, 4.0, 4.0, 5.0]) == pytest.approx(0.9797958971)
    assert count_positive([1, -1, None, 2, 0, 5]) == 2


def test_years_derive_gross_profit_debt_cash_and_cet1() -> None:
    fin = financials(
        gross_profit=[None, None, None, None, None],
        cost_of_revenue=[640, 568, 508, 452, 400],
        long_term_debt_current=[50, 0, 0, 0, 0],
        marketable_securities=[100, 0, 0, 0, 0],
        cet1_ratio=[0.118, None, None, None, None],
        total_liabilities=[None, 1150, 1100, 1060, 1020],
    )
    years, _ = build_years(fin)
    y = years[0]
    assert y.gross_profit == 960.0 and y.gross_margin == pytest.approx(0.6)
    assert y.debt == 450.0 and y.cash == 600.0
    assert y.cet1_pct == pytest.approx(11.8)
    assert y.total_liabilities == 1200.0  # assets less equity when the total is untagged
    assert y.fcf == 300.0 and y.fcf_margin == pytest.approx(0.1875)


def test_roic_is_nopat_over_invested_capital() -> None:
    years, _ = build_years(financials())
    # 400 x (1 - 80/380) / (1800 + 400 - 500)
    assert roic(years[0]) == pytest.approx(0.18575851393188855)
```

- [x] **Step 3: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_metrics.py`
  Expected: `ModuleNotFoundError: No module named 'src.value.metrics'`.

- [x] **Step 4: Create `src/value/schemas.py`**

```python
"""The value book's output shapes (spec §6.7, §6.9). Pydantic only: the API may import this
module (tests/test_value_fence.py)."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from src.common.value_types import Classification

GateState = Literal["pass", "fail", "unknown", "not_applicable"]
Verdict = Literal["READY", "WATCH", "WAIT", "NO", "UNKNOWN", "NOT_APPLICABLE"]
ListName = Literal["deep_value", "quality_growth"]
CompanyClass = Literal["operating", "cyclical", "bank", "insurer", "reit", "etf"]
MethodName = Literal["A", "B", "C", "D", "PTBV"]
MethodState = Literal["ok", "absent", "unreliable", "not_applicable"]

LISTS: tuple[ListName, ListName] = ("deep_value", "quality_growth")


class Check(BaseModel):
    """One gate or rule, with the number it read and the bar it was held to."""

    id: str
    state: GateState
    actual: float | None = None
    threshold: float | None = None
    detail: str = ""


def combine(checks: list[Check]) -> GateState:
    """A conjunction: any fail -> fail; else any unknown -> unknown; else pass.
    Checks that do not apply are ignored; all of them not applying -> not_applicable."""
    states = [c.state for c in checks if c.state != "not_applicable"]
    if not states:
        return "not_applicable"
    if "fail" in states:
        return "fail"
    if "unknown" in states:
        return "unknown"
    return "pass"


class MethodValue(BaseModel):
    """One valuation method's per-share value (spec §6.5)."""

    method: MethodName
    value: float | None = None
    state: MethodState = "absent"
    detail: str = ""
    inputs: dict[str, float | None] = Field(default_factory=dict)


class ListEvaluation(BaseModel):
    """Python's baseline for one list (spec §6.7)."""

    list_name: ListName
    entry: GateState  # deep value: always pass; quality growth: the entry rule
    entry_checks: list[Check] = Field(default_factory=list)
    methods: list[MethodValue] = Field(default_factory=list)
    fair_value: float | None = None
    required_mos_pct: float
    margin_of_safety: float | None = None  # a fraction: (fair value - price) / fair value
    entry_ceiling: float | None = None
    timing: GateState = "unknown"
    timing_checks: list[Check] = Field(default_factory=list)
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)
    mos_review: bool = False  # a margin above review_above_pct goes to a human (spec §9.4)


class Fingerprint(BaseModel):
    """The inputs a ticker file was computed from (spec §6.9)."""

    latest_accn: str | None = None
    latest_filed: date | None = None
    price_date: date | None = None
    price_close: float | None = None
    regime: str = "unknown"
    ruleset_version: str
    ruleset_hash: str

    def key(self) -> str:
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class ValueScorecard(BaseModel):
    """Part 1 of a ticker file: every number, gate and baseline verdict for one name."""

    symbol: str
    as_of: date
    ruleset_version: str
    ruleset_hash: str
    company_class: CompanyClass
    classification: Classification
    data_quality: GateState
    data_quality_checks: list[Check] = Field(default_factory=list)
    health: GateState = "unknown"
    health_checks: list[Check] = Field(default_factory=list)
    not_applicable_reason: str | None = None
    price: float | None = None
    market_cap_edgar: float | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    reverse_dcf_implied_growth: float | None = None
    realised_fcf_ps_cagr: float | None = None
    lists: dict[str, ListEvaluation] = Field(default_factory=dict)
    adjustments: list[str] = Field(default_factory=list)
    fingerprint: Fingerprint

    def verdict_for(self, list_name: str) -> str:
        """The list's baseline verdict. NOT_APPLICABLE and UNKNOWN are the whole card's; a
        healthy name that is not on a list reads NO for that list."""
        if self.not_applicable_reason is not None:
            return "NOT_APPLICABLE"
        if self.data_quality != "pass":
            return "UNKNOWN"
        ev = self.lists.get(list_name)
        return ev.verdict if ev is not None else "NO"
```

- [x] **Step 5: Create `src/value/metrics.py`**

```python
"""Per-year figures derived from filed line items (spec §6.4-6.5). Pure: no I/O.

Line-item names are the canonical keys of ``config/research_concepts.yaml``. A missing item is
None, never zero, except where a docstring says otherwise and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median, pstdev

from src.common.value_types import ValueFinancials

# A ratio between adjacent share counts at or beyond this (or its inverse) is a split, a reverse
# split, or something the scorecard cannot explain (spec §6.3, "share-class mapping applied").
SPLIT_RATIO = 1.8
_SPLIT_FACTORS = (1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0)
_SPLIT_TOLERANCE = 0.05


@dataclass(frozen=True, slots=True)
class Year:
    """One fiscal year, every figure in dollars (shares in shares)."""

    end: date
    revenue: float | None
    gross_profit: float | None
    operating_income: float | None
    net_income: float | None
    net_income_common: float | None
    ocf: float | None
    capex: float | None
    sbc: float | None
    da: float | None
    interest: float | None
    pretax: float | None
    tax: float | None
    sga: float | None
    total_assets: float | None
    total_liabilities: float | None
    equity: float | None
    current_assets: float | None
    current_liabilities: float | None
    long_term_debt: float | None
    debt: float | None  # every interest-bearing line tagged; None when none is
    cash: float | None  # cash + current marketable securities
    receivables: float | None
    ppe: float | None
    retained: float | None
    goodwill: float | None
    intangibles: float | None
    preferred: float | None
    shares: float | None  # split-normalised
    nco: float | None
    loans: float | None
    cet1_pct: float | None
    premiums: float | None
    benefits_losses_expenses: float | None

    @property
    def fcf(self) -> float | None:
        if self.ocf is None or self.capex is None:
            return None
        return self.ocf - self.capex

    @property
    def gross_margin(self) -> float | None:
        if self.gross_profit is None or not self.revenue:
            return None
        return self.gross_profit / self.revenue

    @property
    def fcf_margin(self) -> float | None:
        fcf = self.fcf
        if fcf is None or not self.revenue:
            return None
        return fcf / self.revenue

    @property
    def tangible_equity(self) -> float | None:
        """Common equity less goodwill, intangibles and preferred (absent parts count as 0)."""
        if self.equity is None:
            return None
        return (
            self.equity
            - (self.goodwill or 0.0)
            - (self.intangibles or 0.0)
            - (self.preferred or 0.0)
        )


@dataclass(slots=True)
class ShareNormalisation:
    adjustments: list[str] = field(default_factory=list)
    unexplained: list[str] = field(default_factory=list)


def _sum_present(*values: float | None) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _liabilities(items: dict[str, float]) -> float | None:
    """Total liabilities, else total assets less equity (the balance-sheet identity; AMD tags
    no ``Liabilities`` total)."""
    if items.get("total_liabilities") is not None:
        return items["total_liabilities"]
    assets, equity = items.get("total_assets"), items.get("stockholders_equity")
    if assets is None or equity is None:
        return None
    return assets - equity


def _split_factor(ratio: float) -> float | None:
    for f in _SPLIT_FACTORS:
        for candidate in (f, 1.0 / f):
            if abs(ratio / candidate - 1.0) <= _SPLIT_TOLERANCE:
                return candidate
    return None


def normalise_shares(
    newest: float | None, annual: list[float | None], ends: list[date]
) -> tuple[list[float | None], ShareNormalisation]:
    """Rescale older share counts across splits so per-share series are comparable.

    *newest* is the most recent count (a 10-Q filed after the last 10-K, or None); *annual* is
    newest first. Walking back, a ratio between the newer and the older count at or beyond
    ``SPLIT_RATIO`` (either way) that sits within 5% of a whole split factor rescales every older
    year by that factor and is recorded; one that does not is recorded as unexplained, which the
    data-quality gate turns into UNKNOWN.
    """
    out = list(annual)
    note = ShareNormalisation()
    chain: list[tuple[float | None, str]] = [(newest, "latest")] + [
        (v, str(e.year)) for v, e in zip(out, ends, strict=True)
    ]
    for i in range(1, len(chain)):
        newer = next((v for v, _ in reversed(chain[:i]) if v), None)
        older, label = chain[i]
        if not newer or not older:
            continue
        ratio = newer / older
        if 1.0 / SPLIT_RATIO < ratio < SPLIT_RATIO:
            continue
        factor = _split_factor(ratio)
        if factor is None:
            note.unexplained.append(f"share count jumps {ratio:.2f}x into FY{label}")
            continue
        for j in range(i, len(chain)):
            v, lab = chain[j]
            chain[j] = (v * factor if v is not None else None, lab)
        note.adjustments.append(f"shares FY{label} and earlier x{factor:g} (split)")
    return [v for v, _ in chain[1:]], note


def build_years(fin: ValueFinancials) -> tuple[list[Year], ShareNormalisation]:
    """Every fiscal year in *fin*, newest first, with split-normalised share counts."""
    raw_shares: list[float | None] = []
    for p in fin.annual:
        it = p.items
        raw_shares.append(it.get("shares_diluted") or it.get("shares_outstanding"))
    newest = fin.shares_latest
    shares, note = normalise_shares(newest, raw_shares, [p.period_end for p in fin.annual])

    years: list[Year] = []
    for p, sh in zip(fin.annual, shares, strict=True):
        it = p.items
        revenue = it.get("revenue")
        gross = it.get("gross_profit")
        if gross is None and revenue is not None and it.get("cost_of_revenue") is not None:
            gross = revenue - it["cost_of_revenue"]
        cet1 = it.get("cet1_ratio")
        if cet1 is not None and cet1 <= 1.0:
            cet1 *= 100.0
        years.append(
            Year(
                end=p.period_end,
                revenue=revenue,
                gross_profit=gross,
                operating_income=it.get("operating_income"),
                net_income=it.get("net_income"),
                net_income_common=it.get("net_income_common", it.get("net_income")),
                ocf=it.get("operating_cash_flow"),
                capex=it.get("capital_expenditure"),
                sbc=it.get("sbc"),
                da=it.get("depreciation_amortization"),
                interest=it.get("interest_expense"),
                pretax=it.get("pretax_income"),
                tax=it.get("income_tax"),
                sga=it.get("sga"),
                total_assets=it.get("total_assets"),
                total_liabilities=_liabilities(it),
                equity=it.get("stockholders_equity"),
                current_assets=it.get("current_assets"),
                current_liabilities=it.get("current_liabilities"),
                long_term_debt=it.get("long_term_debt"),
                debt=_sum_present(
                    it.get("long_term_debt"),
                    it.get("long_term_debt_current"),
                    it.get("commercial_paper"),
                    it.get("short_term_borrowings"),
                ),
                cash=_sum_present(it.get("cash_and_equivalents"), it.get("marketable_securities")),
                receivables=it.get("accounts_receivable"),
                ppe=it.get("ppe_net"),
                retained=it.get("retained_earnings"),
                goodwill=it.get("goodwill"),
                intangibles=it.get("intangibles"),
                preferred=it.get("preferred_equity"),
                shares=sh,
                nco=it.get("net_charge_offs"),
                loans=it.get("loans"),
                cet1_pct=cet1,
                premiums=it.get("premiums_earned"),
                benefits_losses_expenses=it.get("benefits_losses_expenses"),
            )
        )
    return years, note


# ── series helpers ──────────────────────────────────────────────────────────────────────────


def cagr(series: list[float | None], max_years: int = 5, min_years: int = 4) -> float | None:
    """Compound annual growth from the oldest usable year (at most *max_years* back) to the
    newest. *series* is newest first. None unless both ends are positive and the span is at
    least *min_years* (spec §6.0's "5-year" rates use 4 years when only five periods exist)."""
    if not series or series[0] is None or series[0] <= 0:
        return None
    span = min(max_years, len(series) - 1)
    while span >= min_years:
        base = series[span]
        if base is not None and base > 0:
            return (series[0] / base) ** (1.0 / span) - 1.0
        span -= 1
    return None


def last_n(series: list[float | None], n: int = 5) -> list[float]:
    """The present values among the newest *n*."""
    return [v for v in series[:n] if v is not None]


def median_of(series: list[float | None], n: int = 5) -> float | None:
    vals = last_n(series, n)
    return median(vals) if vals else None


def stdev_of(series: list[float | None], n: int = 5) -> float | None:
    """Population standard deviation of the newest *n* present values (None below 3)."""
    vals = last_n(series, n)
    return pstdev(vals) if len(vals) >= 3 else None


def count_positive(series: list[float | None], n: int = 5) -> int:
    return sum(1 for v in series[:n] if v is not None and v > 0)


def roic(y: Year) -> float | None:
    """NOPAT over year-end invested capital (equity + debt - cash), as a fraction.

    Tax rate = tax / pre-tax income, clamped to [0, 35%]; 21% when either is missing or pre-tax
    income is not positive. None when invested capital is not positive."""
    if y.operating_income is None or y.equity is None:
        return None
    rate = 0.21
    if y.tax is not None and y.pretax is not None and y.pretax > 0:
        rate = min(max(y.tax / y.pretax, 0.0), 0.35)
    invested = y.equity + (y.debt or 0.0) - (y.cash or 0.0)
    if invested <= 0:
        return None
    return y.operating_income * (1.0 - rate) / invested
```

- [x] **Step 6: Run the tests** — `.venv/bin/python -m pytest -q tests/test_value_metrics.py` →
  8 passed.

- [x] **Step 7: Gates**

  ```bash
  .venv/bin/ruff check src/value tests/value_fixtures.py tests/test_value_metrics.py
  .venv/bin/ruff format --check src/value tests/value_fixtures.py tests/test_value_metrics.py
  .venv/bin/mypy src/value
  ```

- [x] **Step 8: Commit**

  ```bash
  git add src/value/schemas.py src/value/metrics.py tests/value_fixtures.py tests/test_value_metrics.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): scorecard schemas, per-year metrics with split normalisation, test fixtures"
  ```

---

### Task 6: Piotroski F-score, Altman Z, Beneish M

**Files:** Create `src/value/scores.py`, `tests/test_value_scores.py`

**Interfaces:**
- Consumes: `Year`, `build_years` (Task 5); fixtures.
- Produces: `Score(value, parts, missing)`; `piotroski(years, max_missing=2) -> Score`;
  `altman_z(year, market_cap) -> Score`; `beneish_m(years) -> Score`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_scores.py`

```python
"""Piotroski, Altman and Beneish on the Steady Co fixture, pinned (value book spec §6.4)."""

from __future__ import annotations

import pytest

from src.value.metrics import build_years
from src.value.scores import altman_z, beneish_m, piotroski
from tests.value_fixtures import financials


def _years(**overrides):
    return build_years(financials(**overrides))[0]


def test_piotroski_scores_eight_of_nine() -> None:
    f = piotroski(_years())
    assert f.value == 8.0
    assert f.parts["gross_margin_rose"] == 0.0  # 60% both years
    assert f.missing == []


def test_piotroski_with_too_much_missing_is_none() -> None:
    f = piotroski(
        _years(
            current_assets=[None] * 5,
            current_liabilities=[None] * 5,
            gross_profit=[None] * 5,
            accounts_receivable=[None] * 5,
            operating_cash_flow=[None] * 5,
        )
    )
    assert f.value is None
    assert set(f.missing) >= {"liquidity_rose", "gross_margin_rose", "ocf_positive", "accruals"}


def test_piotroski_does_not_punish_a_debt_free_company() -> None:
    f = piotroski(_years(long_term_debt=[0, 0, 0, 0, 0]))
    assert f.parts["leverage_fell"] == 1.0


def test_altman_z_pinned() -> None:
    z = altman_z(_years()[0], market_cap=3000.0)
    # 1.2(600/3000) + 1.4(1500/3000) + 3.3(400/3000) + 0.6(3000/1200) + 1600/3000
    assert z.value == pytest.approx(3.4133333333)
    assert altman_z(_years(retained_earnings=[None] * 5)[0], 3000.0).value is None


def test_beneish_m_pinned() -> None:
    m = beneish_m(_years())
    assert m.value == pytest.approx(-2.488221536443591)
    assert m.parts["sgi"] == pytest.approx(1600 / 1420)
    assert m.parts["tata"] == pytest.approx((300 - 380) / 3000)


def test_beneish_needs_its_four_heavy_indices() -> None:
    assert beneish_m(_years(accounts_receivable=[None] * 5)).value is None


def test_beneish_falls_back_to_neutral_for_the_light_indices() -> None:
    m = beneish_m(_years(sga=[None] * 5))
    assert "sgai" in m.missing and m.value is not None
```

- [x] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named
  'src.value.scores'`.

- [x] **Step 3: Create `src/value/scores.py`**

```python
"""Piotroski F-score, Altman Z and Beneish M (spec §6.4). Pure: no I/O.

Each takes fiscal years newest first (``src.value.metrics.Year``) and returns the score plus
what it could not compute, so a gate can say UNKNOWN instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.value.metrics import Year


@dataclass(slots=True)
class Score:
    value: float | None
    parts: dict[str, float | None] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def piotroski(years: list[Year], max_missing: int = 2) -> Score:
    """The nine-point F-score for the newest year against the one before.

    Return on assets uses beginning-of-year assets, so three years are needed. A component
    whose inputs are missing scores 0 and is listed; more than *max_missing* missing makes the
    score None. Leverage counts as improved when long-term debt / assets fell, or when the
    company carried none in either year (a debt-free company is not penalised)."""
    if len(years) < 3:
        return Score(None, missing=["fewer than three fiscal years"])
    t, p, pp = years[0], years[1], years[2]
    parts: dict[str, float | None] = {}
    missing: list[str] = []

    def point(name: str, ok: bool | None) -> None:
        if ok is None:
            missing.append(name)
            parts[name] = None
        else:
            parts[name] = 1.0 if ok else 0.0

    roa_t = _div(t.net_income, p.total_assets)
    roa_p = _div(p.net_income, pp.total_assets)
    point("roa_positive", None if roa_t is None else roa_t > 0)
    point("ocf_positive", None if t.ocf is None else t.ocf > 0)
    point("roa_improved", None if roa_t is None or roa_p is None else roa_t > roa_p)
    cfo_ta = _div(t.ocf, p.total_assets)
    point("accruals", None if cfo_ta is None or roa_t is None else cfo_ta > roa_t)
    lev_t = _div(t.long_term_debt or 0.0, t.total_assets)
    lev_p = _div(p.long_term_debt or 0.0, p.total_assets)
    point(
        "leverage_fell",
        None if lev_t is None or lev_p is None else (lev_t < lev_p or (lev_t == 0 and lev_p == 0)),
    )
    cr_t = _div(t.current_assets, t.current_liabilities)
    cr_p = _div(p.current_assets, p.current_liabilities)
    point("liquidity_rose", None if cr_t is None or cr_p is None else cr_t > cr_p)
    point(
        "no_dilution",
        None if t.shares is None or p.shares is None else t.shares <= p.shares,
    )
    gm_t, gm_p = t.gross_margin, p.gross_margin
    point("gross_margin_rose", None if gm_t is None or gm_p is None else gm_t > gm_p)
    at_t = _div(t.revenue, p.total_assets)
    at_p = _div(p.revenue, pp.total_assets)
    point("asset_turnover_rose", None if at_t is None or at_p is None else at_t > at_p)

    if len(missing) > max_missing:
        return Score(None, parts, missing)
    return Score(sum(v for v in parts.values() if v is not None), parts, missing)


def altman_z(year: Year, market_cap: float | None) -> Score:
    """Original Altman Z (public manufacturer):
    1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 MVE/TL + 1.0 Sales/TA.
    Every input is required; any missing one makes it None."""
    ta, tl = year.total_assets, year.total_liabilities
    wc = None
    if year.current_assets is not None and year.current_liabilities is not None:
        wc = year.current_assets - year.current_liabilities
    parts = {
        "wc_ta": _div(wc, ta),
        "re_ta": _div(year.retained, ta),
        "ebit_ta": _div(year.operating_income, ta),
        "mve_tl": _div(market_cap, tl),
        "sales_ta": _div(year.revenue, ta),
    }
    missing = [k for k, v in parts.items() if v is None]
    if missing:
        return Score(None, parts, missing)
    v = {k: float(x) for k, x in parts.items() if x is not None}
    z = 1.2 * v["wc_ta"] + 1.4 * v["re_ta"] + 3.3 * v["ebit_ta"] + 0.6 * v["mve_tl"] + v["sales_ta"]
    return Score(z, parts, [])


_BENEISH_REQUIRED = ("dsri", "gmi", "sgi", "tata")


def beneish_m(years: list[Year]) -> Score:
    """Eight-variable Beneish M for the newest year against the one before:
    -4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI
    + 4.679 TATA - 0.327 LVGI.

    DSRI, GMI, SGI and TATA are required (None without them). AQI, DEPI, SGAI and LVGI fall
    back to the neutral 1.0 when their inputs are missing, and are listed."""
    if len(years) < 2:
        return Score(None, missing=["fewer than two fiscal years"])
    t, p = years[0], years[1]

    def ratio(a: float | None, b: float | None) -> float | None:
        return _div(a, b)

    dsri = ratio(ratio(t.receivables, t.revenue), ratio(p.receivables, p.revenue))
    gmi = ratio(p.gross_margin, t.gross_margin)
    sgi = ratio(t.revenue, p.revenue)
    tata = None
    if t.net_income is not None and t.ocf is not None and t.total_assets:
        tata = (t.net_income - t.ocf) / t.total_assets

    def aq(y: Year) -> float | None:
        if y.current_assets is None or y.ppe is None or not y.total_assets:
            return None
        return 1.0 - (y.current_assets + y.ppe) / y.total_assets

    aqi = ratio(aq(t), aq(p))

    def dep_rate(y: Year) -> float | None:
        if y.da is None or y.ppe is None or (y.da + y.ppe) == 0:
            return None
        return y.da / (y.da + y.ppe)

    depi = ratio(dep_rate(p), dep_rate(t))
    sgai = ratio(ratio(t.sga, t.revenue), ratio(p.sga, p.revenue))

    def lev(y: Year) -> float | None:
        if y.current_liabilities is None or not y.total_assets:
            return None
        return (y.current_liabilities + (y.long_term_debt or 0.0)) / y.total_assets

    lvgi = ratio(lev(t), lev(p))
    parts: dict[str, float | None] = {
        "dsri": dsri,
        "gmi": gmi,
        "aqi": aqi,
        "sgi": sgi,
        "depi": depi,
        "sgai": sgai,
        "tata": tata,
        "lvgi": lvgi,
    }
    missing = [k for k, v in parts.items() if v is None]
    if any(parts[k] is None for k in _BENEISH_REQUIRED):
        return Score(None, parts, missing)

    def neutral(name: str) -> float:
        v = parts[name]
        return 1.0 if v is None else v

    m = (
        -4.84
        + 0.920 * neutral("dsri")
        + 0.528 * neutral("gmi")
        + 0.404 * neutral("aqi")
        + 0.892 * neutral("sgi")
        + 0.115 * neutral("depi")
        - 0.172 * neutral("sgai")
        + 4.679 * neutral("tata")
        - 0.327 * neutral("lvgi")
    )
    return Score(m, parts, missing)
```

- [x] **Step 4: Run the tests** — `.venv/bin/python -m pytest -q tests/test_value_scores.py` →
  7 passed.

- [x] **Step 5: Gates** — `ruff check`, `ruff format --check` and `mypy` on `src/value/scores.py
  tests/test_value_scores.py` (mypy on the `src` path).

- [x] **Step 6: Commit**

  ```bash
  git add src/value/scores.py tests/test_value_scores.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): Piotroski F-score, Altman Z and Beneish M"
  ```

---

### Task 7: Classification, the data-quality gate and the health gates

**Files:** Create `src/value/gates.py`, `tests/test_value_gates.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 5, 6.
- Produces: `classify(inputs, years, rules) -> CompanyClass`; `preprofit(years, rules) -> bool`;
  `edgar_shares(inputs) -> float | None`; `data_quality(inputs, years, shares, rules) ->
  list[Check]` (ids `dq.filings`, `dq.annual_periods`, `dq.filing_age`, `dq.price_history`,
  `dq.market_cap`, `dq.share_continuity`); `ttm_fcf(inputs)`; `gross_debt_latest(inputs)`;
  `net_debt_latest(inputs)`; `check_at_least(id_, actual, bar, detail="")`;
  `check_at_most(...)`; `dilution_pct(years)`; `operating_health(inputs, years, market_cap,
  rules, *, cyclical) -> list[Check]` (ids `health.piotroski`, `health.altman_z`,
  `health.profitable_years`, `health.fcf_positive_years`, `health.fcf_ttm_positive` (not for
  cyclicals), `health.net_debt_to_ebitda`, `health.interest_coverage`, `health.beneish_m`,
  `health.dilution`); `rote_series(years)`; `tbv_per_share(y)`; `financial_health(inputs, years,
  rules, *, insurer) -> list[Check]` (ids `bank.profitable_years`, `bank.rote_median`,
  `bank.rote_stdev`, `bank.tbv_growth`, `bank.nco`, `bank.cet1`, `bank.combined_ratio`,
  `bank.dilution`); `build_years_for(inputs)`; `latest_tbv_per_share(inputs, years)`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_gates.py`

```python
"""Classification, data quality and the health gates (value book spec §6.3-6.5)."""

from __future__ import annotations

from datetime import date

import pytest

from src.common.config import ValueCfg, get_config
from src.value import gates
from src.value.metrics import build_years
from src.value.schemas import combine
from tests.value_fixtures import BANK, financials, inputs, price

RULES = get_config().value.rules


def _years(fin):
    return build_years(fin)


@pytest.mark.parametrize(
    ("industry", "is_etf", "expected"),
    [
        ("Application Software", True, "etf"),
        ("Retail REITs", False, "reit"),
        ("Diversified Banks", False, "bank"),
        ("Banks - Regional", False, "bank"),
        ("Property & Casualty Insurance", False, "insurer"),
        ("Semiconductors", False, "cyclical"),
        ("Application Software", False, "operating"),
    ],
)
def test_classify_by_industry(industry, is_etf, expected) -> None:
    inp = inputs(industry=industry, is_etf=is_etf)
    years, _ = _years(inp.financials)
    assert gates.classify(inp, years, RULES) == expected


def test_a_swinging_fcf_margin_makes_a_cyclical() -> None:
    fin = financials(operating_cash_flow=[500, 80, 400, 60, 300])  # margins 26%, 0%, 26%, -1%, 24%
    inp = inputs(fin=fin)
    years, _ = _years(fin)
    assert gates.classify(inp, years, RULES) == "cyclical"


def test_preprofit_is_three_losses_in_five_years() -> None:
    years, _ = _years(financials(net_income=[-50, -40, -30, 10, 5]))
    assert gates.preprofit(years, RULES) is True
    years, _ = _years(financials(net_income=[-50, -40, 30, 10, 5]))
    assert gates.preprofit(years, RULES) is False


def _dq(inp):
    years, shares = gates.build_years_for(inp)
    return {c.id: c.state for c in gates.data_quality(inp, years, shares, RULES)}


def test_data_quality_passes_on_the_fixture() -> None:
    assert set(_dq(inputs()).values()) == {"pass"}


@pytest.mark.parametrize(
    ("kwargs", "failing"),
    [
        ({"yf_market_cap": 3000.0 * 1.2}, "dq.market_cap"),
        ({"price_series": price(30.0, sessions=150)}, "dq.price_history"),
        ({"fin": financials(filed=date(2025, 6, 1))}, "dq.filing_age"),
        ({"fin": financials(shares_diluted=[100, 37, 37, 37, 37])}, "dq.share_continuity"),
    ],
)
def test_each_data_quality_check_says_unknown(kwargs, failing) -> None:
    assert _dq(inputs(**kwargs))[failing] == "unknown"


def test_too_few_annual_periods_is_unknown() -> None:
    fin = financials()
    fin.annual = fin.annual[:4]
    assert _dq(inputs(fin=fin))["dq.annual_periods"] == "unknown"


def test_a_missing_yfinance_cap_is_unknown_never_a_pass() -> None:
    inp = inputs().model_copy(update={"yf_market_cap": None})
    assert _dq(inp)["dq.market_cap"] == "unknown"


def test_no_us_gaap_facts_is_one_unknown_check() -> None:
    fin = financials()
    fin.has_us_gaap = False
    assert _dq(inputs(fin=fin)) == {"dq.filings": "unknown"}


def _health(inp, *, cyclical=False):
    years, _ = gates.build_years_for(inp)
    checks = gates.operating_health(inp, years, 3000.0, RULES, cyclical=cyclical)
    return {c.id: c for c in checks}


def test_the_steady_fixture_passes_every_operating_gate() -> None:
    h = _health(inputs())
    assert {k: v.state for k, v in h.items()} == {
        "health.piotroski": "pass",
        "health.altman_z": "pass",
        "health.profitable_years": "pass",
        "health.fcf_positive_years": "pass",
        "health.fcf_ttm_positive": "pass",
        "health.net_debt_to_ebitda": "pass",
        "health.interest_coverage": "pass",
        "health.beneish_m": "pass",
        "health.dilution": "pass",
    }
    assert h["health.net_debt_to_ebitda"].detail == "net cash"  # 400 debt, 500 cash
    assert h["health.interest_coverage"].actual == 40.0


def test_net_debt_over_ebitda_and_coverage_with_debt() -> None:
    fin = financials(long_term_debt=[1500, 420, 440, 460, 480])
    h = _health(inputs(fin=fin))
    assert h["health.net_debt_to_ebitda"].actual == pytest.approx(1000 / 460)
    assert h["health.net_debt_to_ebitda"].state == "pass"


def test_coverage_is_implied_when_interest_is_untagged_and_debt_is_net() -> None:
    fin = financials(long_term_debt=[1500, 420, 440, 460, 480])
    fin.ttm.pop("interest_expense")
    h = _health(inputs(fin=fin))
    assert h["health.interest_coverage"].actual == pytest.approx(400 / (1500 * 0.08))
    assert h["health.interest_coverage"].detail.startswith("implied")


def test_a_cyclical_is_judged_across_the_cycle() -> None:
    fin = financials(
        operating_income=[-50, 355, 317.5, 282.5, 250], operating_cash_flow=[30, 335, 300, 268, 240]
    )
    h = _health(inputs(fin=fin), cyclical=True)
    assert "health.fcf_ttm_positive" not in h
    assert h["health.fcf_positive_years"].state == "pass"  # 4 of 5 positive
    assert h["health.interest_coverage"].detail == "5-year median EBIT"
    assert h["health.interest_coverage"].actual == pytest.approx(282.5 / 10)


def test_net_debt_with_negative_ebitda_fails() -> None:
    fin = financials(
        long_term_debt=[1500, 420, 440, 460, 480],
        operating_income=[-200, 355, 317.5, 282.5, 250],
        depreciation_amortization=[60, 55, 50, 46, 42],
    )
    h = _health(inputs(fin=fin))
    assert h["health.net_debt_to_ebitda"].state == "fail"


def _bank(cfg: ValueCfg | None = None, **overrides):
    rules = (cfg or ValueCfg()).rules
    inp = inputs(
        symbol="HBR", fin=financials(BANK, **overrides), close=40.0, industry="Diversified Banks"
    )
    years, _ = gates.build_years_for(inp)
    return {c.id: c for c in gates.financial_health(inp, years, rules, insurer=False)}


def test_a_bank_without_tagged_cet1_is_unknown_never_a_silent_pass() -> None:
    h = _bank()
    assert h["bank.cet1"].state == "unknown"
    assert h["bank.rote_median"].actual == pytest.approx(14.025974025974024)
    assert h["bank.nco"].actual == pytest.approx((2.0 / 1000) / (1.5 / 800))
    assert combine(list(h.values())) == "unknown"


def test_the_operator_may_switch_the_cet1_check_off() -> None:
    h = _bank(ValueCfg(rules={"banks": {"require_cet1": False}}))
    assert h["bank.cet1"].state == "not_applicable"
    assert combine(list(h.values())) == "pass"


def test_a_tagged_cet1_is_checked() -> None:
    assert _bank(cet1_ratio=[0.118, None, None, None, None])["bank.cet1"].state == "pass"
    assert _bank(cet1_ratio=[0.05, None, None, None, None])["bank.cet1"].state == "fail"


def test_a_credit_turn_fails_the_charge_off_gate() -> None:
    assert _bank(net_charge_offs=[4.0, 1.8, 1.6, 1.4, 1.5])["bank.nco"].state == "fail"


def test_an_insurer_reads_its_combined_ratio() -> None:
    table = dict(
        BANK, premiums_earned=[80, 78, 76, 74, 72], benefits_losses_expenses=[76, 70, 80, 72, 68]
    )
    inp = inputs(
        symbol="INS", fin=financials(table), close=40.0, industry="Property & Casualty Insurance"
    )
    years, _ = gates.build_years_for(inp)
    h = {c.id: c for c in gates.financial_health(inp, years, RULES, insurer=True)}
    assert h["bank.combined_ratio"].actual == 4.0  # 2023's 105% is the one bad year
    assert h["bank.combined_ratio"].state == "pass"
    assert h["bank.cet1"].state == "not_applicable" and h["bank.nco"].state == "not_applicable"


def test_edgar_shares_fall_back_for_a_multi_class_filer() -> None:
    """META, GOOGL and HOOD tag no undimensioned cover-page count (checked 2026-10-29)."""
    from src.common.value_types import InstantPoint

    fin = financials()
    fin.cover_shares = None
    fin.latest["shares_outstanding"] = InstantPoint(value=99.0, end=date(2025, 12, 31))
    assert gates.edgar_shares(inputs(fin=fin)) == 99.0
    fin.latest.pop("shares_outstanding")
    assert gates.edgar_shares(inputs(fin=fin)) == 100.0  # the newest weighted diluted count
    fin.shares_latest = None
    assert gates.edgar_shares(inputs(fin=fin)) == 100.0  # the last fiscal year's
```

- [x] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named
  'src.value.gates'`.

- [x] **Step 3: Create `src/value/gates.py`**

```python
"""Classification, the data-quality gate and the health gates (spec §6.3-6.5). Pure: no I/O.

Health is hard and a conjunction: any FAIL is NO whatever anyone thinks of the story; an
UNKNOWN (never a silent pass) keeps the name off both lists until the data exists.
"""

from __future__ import annotations

from src.common.config import ValueRulesCfg
from src.common.value_types import ValueInputs
from src.value.metrics import (
    ShareNormalisation,
    Year,
    build_years,
    cagr,
    count_positive,
    median_of,
    stdev_of,
)
from src.value.schemas import Check, CompanyClass
from src.value.scores import altman_z, beneish_m, piotroski


def _industry_in(inputs: ValueInputs, names: list[str]) -> bool:
    industry = (inputs.classification.industry or "").strip().lower()
    return bool(industry) and industry in {n.strip().lower() for n in names}


def classify(inputs: ValueInputs, years: list[Year], rules: ValueRulesCfg) -> CompanyClass:
    """etf -> reit -> bank -> insurer -> cyclical (industry list, or FCF-margin variability
    above the bar) -> operating."""
    c = rules.classification
    if inputs.classification.is_etf:
        return "etf"
    marker = c.reit_marker.lower()
    if marker and marker in (inputs.classification.industry or "").lower():
        return "reit"
    if _industry_in(inputs, c.bank_industries):
        return "bank"
    if _industry_in(inputs, c.insurer_industries):
        return "insurer"
    if _industry_in(inputs, c.cyclical_industries):
        return "cyclical"
    spread = stdev_of([y.fcf_margin for y in years])
    if spread is not None and spread * 100.0 > c.cyclical_fcf_margin_stdev_pts:
        return "cyclical"
    return "operating"


def preprofit(years: list[Year], rules: ValueRulesCfg) -> bool:
    """A net loss in at least ``preprofit_loss_years_min`` of the last five fiscal years."""
    losses = sum(1 for y in years[:5] if y.net_income is not None and y.net_income <= 0)
    return losses >= rules.classification.preprofit_loss_years_min


def edgar_shares(inputs: ValueInputs) -> float | None:
    """Cover-page count, else the newest balance-sheet count, else the newest weighted diluted
    count, quarterly then annual (multi-class filers tag no undimensioned cover count)."""
    fin = inputs.financials
    if fin is None:
        return None
    if fin.cover_shares:
        return fin.cover_shares
    point = fin.latest.get("shares_outstanding")
    if point is not None and point.value > 0:
        return point.value
    if fin.shares_latest:
        return fin.shares_latest
    return fin.annual[0].items.get("shares_diluted") if fin.annual else None


def data_quality(
    inputs: ValueInputs, years: list[Year], shares: ShareNormalisation, rules: ValueRulesCfg
) -> list[Check]:
    """Spec §6.3. Each check is pass or unknown; the gate is their conjunction."""
    dq = rules.data_quality
    fin = inputs.financials
    checks: list[Check] = []
    if fin is None or not fin.has_us_gaap:
        return [Check(id="dq.filings", state="unknown", detail="no us-gaap XBRL facts")]

    n = len(years)
    checks.append(
        Check(
            id="dq.annual_periods",
            state="pass" if n >= dq.min_annual_periods else "unknown",
            actual=float(n),
            threshold=float(dq.min_annual_periods),
        )
    )
    if fin.latest_filed is None:
        checks.append(Check(id="dq.filing_age", state="unknown", detail="no filing date"))
    else:
        age = (inputs.as_of - fin.latest_filed).days
        checks.append(
            Check(
                id="dq.filing_age",
                state="pass" if age <= dq.max_filing_age_days else "unknown",
                actual=float(age),
                threshold=float(dq.max_filing_age_days),
            )
        )
    price = inputs.price
    if price is None or price.sessions < dq.min_price_sessions:
        checks.append(
            Check(
                id="dq.price_history",
                state="unknown",
                actual=float(price.sessions) if price else 0.0,
                threshold=float(dq.min_price_sessions),
            )
        )
    else:
        checks.append(
            Check(
                id="dq.price_history",
                state="pass",
                actual=float(price.sessions),
                threshold=float(dq.min_price_sessions),
            )
        )
    count = edgar_shares(inputs)
    if count is None or price is None or not inputs.yf_market_cap:
        checks.append(
            Check(
                id="dq.market_cap",
                state="unknown",
                detail="EDGAR share count, price or yfinance market cap missing",
            )
        )
    else:
        edgar_cap = count * price.close
        gap = abs(edgar_cap - inputs.yf_market_cap) / inputs.yf_market_cap
        checks.append(
            Check(
                id="dq.market_cap",
                state="pass" if gap <= dq.market_cap_tolerance else "unknown",
                actual=gap,
                threshold=dq.market_cap_tolerance,
                detail=f"EDGAR {edgar_cap / 1e9:.1f}B vs yfinance {inputs.yf_market_cap / 1e9:.1f}B",
            )
        )
    checks.append(
        Check(
            id="dq.share_continuity",
            state="unknown" if shares.unexplained else "pass",
            detail="; ".join(shares.unexplained or shares.adjustments),
        )
    )
    return checks


def _ttm(inputs: ValueInputs, item: str) -> float | None:
    fin = inputs.financials
    if fin is None:
        return None
    point = fin.ttm.get(item)
    return point.value if point is not None else None


def _latest(inputs: ValueInputs, item: str) -> float | None:
    fin = inputs.financials
    if fin is None:
        return None
    point = fin.latest.get(item)
    return point.value if point is not None else None


def ttm_fcf(inputs: ValueInputs) -> float | None:
    ocf, capex = _ttm(inputs, "operating_cash_flow"), _ttm(inputs, "capital_expenditure")
    if ocf is None or capex is None:
        return None
    return ocf - capex


def gross_debt_latest(inputs: ValueInputs) -> float | None:
    parts = [
        _latest(inputs, k)
        for k in (
            "long_term_debt",
            "long_term_debt_current",
            "commercial_paper",
            "short_term_borrowings",
        )
    ]
    present = [v for v in parts if v is not None]
    return sum(present) if present else None


def net_debt_latest(inputs: ValueInputs) -> float | None:
    """Newest balance sheet: every interest-bearing line tagged, less cash and current
    marketable securities. None when neither debt nor cash is tagged."""
    debt_parts = [
        _latest(inputs, k)
        for k in (
            "long_term_debt",
            "long_term_debt_current",
            "commercial_paper",
            "short_term_borrowings",
        )
    ]
    cash_parts = [_latest(inputs, k) for k in ("cash_and_equivalents", "marketable_securities")]
    if all(v is None for v in debt_parts + cash_parts):
        return None
    return sum(v for v in debt_parts if v is not None) - sum(v for v in cash_parts if v is not None)


def check_at_least(id_: str, actual: float | None, bar: float, detail: str = "") -> Check:
    if actual is None:
        return Check(id=id_, state="unknown", threshold=bar, detail=detail or "not computable")
    return Check(
        id=id_,
        state="pass" if actual >= bar else "fail",
        actual=actual,
        threshold=bar,
        detail=detail,
    )


def check_at_most(id_: str, actual: float | None, bar: float, detail: str = "") -> Check:
    if actual is None:
        return Check(id=id_, state="unknown", threshold=bar, detail=detail or "not computable")
    return Check(
        id=id_,
        state="pass" if actual <= bar else "fail",
        actual=actual,
        threshold=bar,
        detail=detail,
    )


def dilution_pct(years: list[Year]) -> float | None:
    g = cagr([y.shares for y in years])
    return None if g is None else g * 100.0


def operating_health(
    inputs: ValueInputs,
    years: list[Year],
    market_cap: float | None,
    rules: ValueRulesCfg,
    *,
    cyclical: bool,
) -> list[Check]:
    """Spec §6.4: financial health, earnings quality and dilution. Cyclicals are judged across
    the cycle: counts of five years instead of TTM, and 5-year median EBITDA and EBIT."""
    h = rules.health
    checks: list[Check] = []
    f = piotroski(years)
    checks.append(
        check_at_least("health.piotroski", f.value, float(h.piotroski_min), ", ".join(f.missing))
    )
    z = altman_z(years[0], market_cap) if years else None
    z_value = z.value if z else None
    checks.append(
        Check(
            id="health.altman_z",
            state="unknown"
            if z_value is None
            else ("pass" if z_value > h.altman_z_min else "fail"),
            actual=z_value,
            threshold=h.altman_z_min,
            detail=", ".join(z.missing) if z else "no fiscal year",
        )
    )

    min_profitable = h.cyclical_profitable_years_min if cyclical else h.profitable_years_min
    ni = [y.net_income for y in years]
    checks.append(
        check_at_least(
            "health.profitable_years",
            float(count_positive(ni)) if len(years) >= 5 else None,
            float(min_profitable),
        )
    )
    min_fcf_years = h.cyclical_fcf_positive_years_min if cyclical else h.fcf_positive_years_min
    fcf_years = [y.fcf for y in years]
    checks.append(
        check_at_least(
            "health.fcf_positive_years",
            float(count_positive(fcf_years)) if len(years) >= 5 else None,
            float(min_fcf_years),
        )
    )
    if not cyclical:
        fcf = ttm_fcf(inputs)
        checks.append(
            Check(
                id="health.fcf_ttm_positive",
                state="unknown" if fcf is None else ("pass" if fcf > 0 else "fail"),
                actual=fcf,
                threshold=0.0,
            )
        )

    nd = net_debt_latest(inputs)
    ebit_ttm, da_ttm = _ttm(inputs, "operating_income"), _ttm(inputs, "depreciation_amortization")
    if cyclical:
        ebitda = median_of(
            [
                None if y.operating_income is None else y.operating_income + (y.da or 0.0)
                for y in years
            ]
        )
        ebit = median_of([y.operating_income for y in years])
        basis = "5-year median"
    else:
        ebitda = None if ebit_ttm is None else ebit_ttm + (da_ttm or 0.0)
        ebit = ebit_ttm
        basis = "TTM"
    if nd is not None and nd <= 0:
        checks.append(
            Check(
                id="health.net_debt_to_ebitda",
                state="pass",
                actual=0.0,
                threshold=h.net_debt_to_ebitda_max,
                detail="net cash",
            )
        )
    elif nd is None or ebitda is None:
        checks.append(
            Check(
                id="health.net_debt_to_ebitda", state="unknown", threshold=h.net_debt_to_ebitda_max
            )
        )
    elif ebitda <= 0:
        checks.append(
            Check(
                id="health.net_debt_to_ebitda",
                state="fail",
                threshold=h.net_debt_to_ebitda_max,
                detail=f"net debt with non-positive {basis} EBITDA",
            )
        )
    else:
        checks.append(
            check_at_most(
                "health.net_debt_to_ebitda",
                nd / ebitda,
                h.net_debt_to_ebitda_max,
                f"{basis} EBITDA" + ("" if da_ttm is not None or cyclical else ", D&A not tagged"),
            )
        )

    interest = _ttm(inputs, "interest_expense")
    if interest is not None and interest > 0:
        checks.append(
            check_at_least(
                "health.interest_coverage",
                None if ebit is None else ebit / interest,
                h.interest_coverage_min,
                f"{basis} EBIT",
            )
        )
    elif nd is not None and nd <= 0:
        checks.append(
            Check(
                id="health.interest_coverage",
                state="pass",
                threshold=h.interest_coverage_min,
                detail="no material interest expense (net cash)",
            )
        )
    else:
        # Apple stopped tagging InterestExpense after FY2023. Coverage implied by charging the
        # gross debt a conservative rate, labelled as implied.
        debt = gross_debt_latest(inputs)
        implied = None if ebit is None or not debt else ebit / (debt * h.assumed_interest_rate)
        checks.append(
            check_at_least(
                "health.interest_coverage",
                implied,
                h.interest_coverage_min,
                f"implied: interest expense not tagged; gross debt charged "
                f"{h.assumed_interest_rate:.0%}",
            )
        )

    m = beneish_m(years)
    checks.append(check_at_most("health.beneish_m", m.value, h.beneish_m_max, ", ".join(m.missing)))
    checks.append(check_at_most("health.dilution", dilution_pct(years), h.dilution_max_pct))
    return checks


def rote_series(years: list[Year]) -> list[float | None]:
    """Return on average tangible common equity, newest first (a fraction)."""
    out: list[float | None] = []
    for i, y in enumerate(years):
        prev = years[i + 1] if i + 1 < len(years) else None
        tce = y.tangible_equity
        if tce is None or y.net_income_common is None:
            out.append(None)
            continue
        base = (
            tce
            if prev is None or prev.tangible_equity is None
            else (tce + prev.tangible_equity) / 2
        )
        out.append(y.net_income_common / base if base > 0 else None)
    return out


def _combined_ratio_pct(y: Year) -> float | None:
    """Approximate combined ratio: total benefits, losses and expenses less interest, over
    earned premiums (XBRL tags no combined ratio)."""
    if not y.premiums or y.benefits_losses_expenses is None:
        return None
    return (y.benefits_losses_expenses - (y.interest or 0.0)) / y.premiums * 100.0


def tbv_per_share(y: Year) -> float | None:
    if y.tangible_equity is None or not y.shares:
        return None
    return y.tangible_equity / y.shares


def financial_health(
    inputs: ValueInputs, years: list[Year], rules: ValueRulesCfg, *, insurer: bool
) -> list[Check]:
    """Spec §6.4, banks and insurers: no FCF, coverage, Piotroski, Altman or Beneish."""
    b = rules.banks
    checks: list[Check] = []
    ni = [y.net_income for y in years]
    checks.append(
        check_at_least(
            "bank.profitable_years",
            float(count_positive(ni)) if len(years) >= 5 else None,
            float(b.profitable_years_min),
        )
    )
    rote = rote_series(years)
    med = median_of(rote)
    checks.append(
        check_at_least(
            "bank.rote_median", None if med is None else med * 100.0, b.rote_median_min_pct
        )
    )
    sd = stdev_of(rote)
    checks.append(
        check_at_most("bank.rote_stdev", None if sd is None else sd * 100.0, b.rote_stdev_max_pts)
    )
    tbv_now = tbv_per_share(years[0]) if years else None
    tbv_then = tbv_per_share(years[min(5, len(years) - 1)]) if len(years) >= 5 else None
    if tbv_now is None or tbv_then is None:
        checks.append(Check(id="bank.tbv_growth", state="unknown"))
    else:
        checks.append(
            Check(
                id="bank.tbv_growth",
                state="pass" if tbv_now > tbv_then else "fail",
                actual=tbv_now,
                threshold=tbv_then,
                detail="tangible book per share now vs five years earlier",
            )
        )
    if insurer:
        checks.append(Check(id="bank.nco", state="not_applicable"))
        checks.append(Check(id="bank.cet1", state="not_applicable"))
        if _industry_in(inputs, rules.classification.combined_ratio_industries):
            ratios = [_combined_ratio_pct(y) for y in years[:5]]
            present = [r for r in ratios if r is not None]
            good = sum(1 for r in present if r <= b.combined_ratio_max_pct)
            checks.append(
                Check(
                    id="bank.combined_ratio",
                    state="unknown"
                    if len(present) < 5
                    else ("pass" if good >= b.combined_ratio_years_min else "fail"),
                    actual=float(good),
                    threshold=float(b.combined_ratio_years_min),
                    detail="years at or under 100% (approximate: total benefits, losses and "
                    "expenses less interest, over earned premiums)",
                )
            )
        else:
            checks.append(Check(id="bank.combined_ratio", state="not_applicable"))
    else:
        nco_ratios = [None if y.nco is None or not y.loans else y.nco / y.loans for y in years[:5]]
        med_nco = median_of(nco_ratios)
        if nco_ratios[0] is None or med_nco is None:
            checks.append(Check(id="bank.nco", state="unknown", threshold=b.nco_multiple_max))
        elif med_nco == 0:
            checks.append(
                Check(
                    id="bank.nco",
                    state="pass" if nco_ratios[0] == 0 else "fail",
                    actual=nco_ratios[0],
                    threshold=b.nco_multiple_max,
                )
            )
        else:
            checks.append(
                check_at_most(
                    "bank.nco",
                    nco_ratios[0] / med_nco,
                    b.nco_multiple_max,
                    "NCO/loans vs own 5-year median",
                )
            )
        cet1 = years[0].cet1_pct if years else None
        if not b.require_cet1:
            checks.append(
                Check(id="bank.cet1", state="not_applicable", detail="disabled by config")
            )
        else:
            checks.append(
                check_at_least(
                    "bank.cet1",
                    cet1,
                    b.cet1_min_pct,
                    "" if cet1 is not None else "CET1 not tagged in XBRL",
                )
            )
        checks.append(Check(id="bank.combined_ratio", state="not_applicable"))
    checks.append(
        check_at_most("bank.dilution", dilution_pct(years), rules.health.dilution_max_pct)
    )
    return checks


def build_years_for(inputs: ValueInputs) -> tuple[list[Year], ShareNormalisation]:
    if inputs.financials is None:
        return [], ShareNormalisation()
    return build_years(inputs.financials)


def latest_tbv_per_share(inputs: ValueInputs, years: list[Year]) -> float | None:
    """Tangible book per share from the newest balance sheet (a 10-Q's when newer than the
    10-K), else the last fiscal year's."""
    equity = _latest(inputs, "stockholders_equity")
    count = inputs.financials.shares_latest if inputs.financials else None
    if equity is not None and count:
        tangible = equity - sum(
            v or 0.0
            for v in (_latest(inputs, k) for k in ("goodwill", "intangibles", "preferred_equity"))
        )
        return tangible / count
    return tbv_per_share(years[0]) if years else None
```

- [x] **Step 4: Run the tests** — `.venv/bin/python -m pytest -q tests/test_value_gates.py` →
  28 passed.

- [x] **Step 5: Gates** — `ruff check`, `ruff format --check`, `mypy` on `src/value/gates.py
  tests/test_value_gates.py`.

- [x] **Step 6: Commit**

  ```bash
  git add src/value/gates.py tests/test_value_gates.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): classification, the data-quality gate, and the operating, cyclical, bank and insurer health sets"
  ```

---

### Task 8: Valuation — methods A, B, C, D and justified P/TBV

**Files:** Create `src/value/valuation.py`, `tests/test_value_valuation.py`

**Interfaces:**
- Consumes: `ValueValuationCfg` (Task 1), `MethodValue` (Task 5).
- Produces: `Dcf(value, terminal_share)`; `dcf(base, growth, rate, terminal, years) -> Dcf |
  None`; `implied_growth(price, base, rate, terminal, years) -> float | None`; `method_a(base_ps,
  cfg)`; `haircut_growth(realised, cfg)`; `method_b(base_ps, realised, cfg)`; `method_d(base_ps,
  realised, cfg)`; `method_c()`; `method_ptbv(rote_median, tbv_ps, cfg)`; `fair_value(methods,
  use: tuple[str, ...]) -> float | None`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_valuation.py`

```python
"""Python's fair value, pinned (value book spec §6.5)."""

from __future__ import annotations

import pytest

from src.common.config import ValueValuationCfg
from src.value.valuation import (
    dcf,
    fair_value,
    haircut_growth,
    implied_growth,
    method_a,
    method_b,
    method_c,
    method_d,
    method_ptbv,
)

CFG = ValueValuationCfg()


def test_the_dcf_reproduces_the_specs_googl_growth_value() -> None:
    """Spec §6.5: FCF ~$73B, SBC ~$24B, 12.2B shares, 14% growth, r 8%, half SBC -> ~$151."""
    out = dcf((73 - 12) / 12.2, 0.14, 0.08, 0.025, 10)
    assert out is not None
    assert out.value == pytest.approx(150.5160010022292)
    assert out.terminal_share == pytest.approx(0.629928628446452)
    full_sbc = dcf((73 - 24) / 12.2, 0.14, 0.09, 0.025, 10)
    assert full_sbc is not None and full_sbc.value == pytest.approx(101.33, abs=0.01)


def test_the_dcf_refuses_a_rate_at_or_below_terminal_growth() -> None:
    assert dcf(1.0, 0.1, 0.02, 0.025, 10) is None


def test_implied_growth_round_trips() -> None:
    g = implied_growth(30.0, 2.6, 0.09, 0.025, 10)
    assert g == pytest.approx(-0.0487482551644291)
    out = dcf(2.6, g, 0.09, 0.025, 10)
    assert out is not None and out.value == pytest.approx(30.0)
    assert implied_growth(1e6, 2.6, 0.09, 0.025, 10) is None  # needs more than 100%/yr
    assert implied_growth(1.0, 2.6, 0.09, 0.025, 10) == -0.5
    assert implied_growth(30.0, -1.0, 0.09, 0.025, 10) is None


def test_method_a_is_earnings_power() -> None:
    assert method_a(2.6, CFG).value == pytest.approx(2.6 / 0.07)
    assert method_a(-1.0, CFG).state == "absent"
    assert method_a(None, CFG).state == "absent"


def test_method_b_haircuts_realised_growth() -> None:
    b = method_b(2.6, 0.1474149978141155, CFG)
    assert b.state == "ok"
    assert b.inputs["growth"] == pytest.approx(0.7 * 0.1474149978141155)
    assert b.value == pytest.approx(56.564396041711674)
    assert haircut_growth(0.30, CFG) == pytest.approx(0.105)  # capped at 15% first
    assert haircut_growth(-0.05, CFG) == -0.05  # a decline is not haircut upward


def test_method_b_drops_a_terminal_heavy_valuation() -> None:
    loose = ValueValuationCfg(discount_rate_deep=0.03, g_floor=0.01)
    b = method_b(1.0, 0.1, loose)
    assert b.state == "unreliable"
    assert b.inputs["terminal_share"] == pytest.approx(0.9550167581948823)


def test_method_d_is_the_growth_dcf_capped_at_twenty_percent() -> None:
    d = method_d(2.8, 0.1474149978141155, CFG)
    assert d.value == pytest.approx(86.86667560395772)
    assert method_d(2.8, 0.35, CFG).inputs["growth"] == 0.2
    assert method_d(2.8, -0.01, CFG).state == "absent"


def test_method_c_is_absent_until_point_in_time_prices_exist() -> None:
    assert method_c().state == "absent"


def test_justified_price_to_tangible_book() -> None:
    p = method_ptbv(0.14, 28.0, CFG)
    assert p.value == pytest.approx((0.14 - 0.025) / (0.09 - 0.025) * 28.0)
    assert method_ptbv(0.02, 28.0, CFG).state == "absent"
    assert method_ptbv(None, 28.0, CFG).state == "absent"


def test_fair_value_is_the_median_of_the_methods_present() -> None:
    methods = [method_a(2.6, CFG), method_b(2.6, 0.1474149978141155, CFG), method_c()]
    assert fair_value(methods, ("A", "B", "C")) == pytest.approx(
        (37.142857142857146 + 56.564396041711674) / 2
    )
    assert fair_value([method_c()], ("C",)) is None
```

- [x] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named
  'src.value.valuation'`.

- [x] **Step 3: Create `src/value/valuation.py`**

```python
"""Python's fair value (spec §6.5): methods A, B, D and justified P/TBV. Pure: no I/O.

Every input comes from filed history. C (own-history percentile) needs ten years of
point-in-time prices and is absent until they exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from src.common.config import ValueValuationCfg
from src.value.schemas import MethodValue

_GROWTH_LO, _GROWTH_HI = -0.5, 1.0


@dataclass(frozen=True, slots=True)
class Dcf:
    value: float
    terminal_share: float  # present value of the terminal value / the whole


def dcf(base: float, growth: float, rate: float, terminal: float, years: int) -> Dcf | None:
    """Per-share DCF. Year 1 grows at *growth*, fading linearly to *terminal* in the last
    year; the terminal value is the last year's cash flow grown once at *terminal* and
    capitalised at (rate - terminal). None when rate <= terminal (spec §6.5's validator)."""
    if rate <= terminal or years < 2:
        return None
    cash, pv = base, 0.0
    for k in range(1, years + 1):
        g = growth + (terminal - growth) * (k - 1) / (years - 1)
        cash *= 1.0 + g
        pv += cash / (1.0 + rate) ** k
    pv_terminal = cash * (1.0 + terminal) / (rate - terminal) / (1.0 + rate) ** years
    total = pv + pv_terminal
    if total <= 0:
        return None
    return Dcf(value=total, terminal_share=pv_terminal / total)


def implied_growth(
    price: float, base: float, rate: float, terminal: float, years: int
) -> float | None:
    """The year-1 growth (fading to *terminal*) at which the DCF equals *price*. Bisection over
    -50%..100%; None when the base is not positive or the price needs more than 100%."""
    if base <= 0 or price <= 0:
        return None
    lo_v = dcf(base, _GROWTH_LO, rate, terminal, years)
    hi_v = dcf(base, _GROWTH_HI, rate, terminal, years)
    if lo_v is None or hi_v is None:
        return None
    if price <= lo_v.value:
        return _GROWTH_LO
    if price > hi_v.value:
        return None
    lo, hi = _GROWTH_LO, _GROWTH_HI
    for _ in range(80):
        mid = (lo + hi) / 2.0
        v = dcf(base, mid, rate, terminal, years)
        assert v is not None
        if v.value < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def method_a(base_ps: float | None, cfg: ValueValuationCfg) -> MethodValue:
    """Earnings power: normalised, SBC-adjusted FCF per share / (r - g_floor)."""
    inputs = {"fcf_ps": base_ps, "rate": cfg.discount_rate_deep, "g_floor": cfg.g_floor}
    if base_ps is None:
        return MethodValue(method="A", state="absent", detail="no normalised FCF", inputs=inputs)
    if base_ps <= 0:
        return MethodValue(
            method="A", state="absent", detail="normalised FCF not positive", inputs=inputs
        )
    return MethodValue(
        method="A",
        value=base_ps / (cfg.discount_rate_deep - cfg.g_floor),
        state="ok",
        inputs=inputs,
    )


def haircut_growth(realised: float, cfg: ValueValuationCfg) -> float:
    """B's growth: 0.7 x realised (capped at 15%); a negative realised rate is not haircut."""
    capped = min(realised, cfg.realised_cap_deep)
    return capped * cfg.reverse_dcf_haircut if capped > 0 else capped


def method_b(base_ps: float | None, realised: float | None, cfg: ValueValuationCfg) -> MethodValue:
    """The DCF at the haircut growth, r = 9%, fading to 2.5%. Unreliable (dropped) when the
    terminal value is above 75% of the whole."""
    inputs = {"fcf_ps": base_ps, "realised_growth": realised, "rate": cfg.discount_rate_deep}
    if base_ps is None or base_ps <= 0:
        return MethodValue(
            method="B", state="absent", detail="normalised FCF not positive", inputs=inputs
        )
    if realised is None:
        return MethodValue(
            method="B", state="absent", detail="no realised FCF/share growth", inputs=inputs
        )
    g = haircut_growth(realised, cfg)
    inputs["growth"] = g
    out = dcf(base_ps, g, cfg.discount_rate_deep, cfg.terminal_growth, cfg.dcf_years)
    if out is None:
        return MethodValue(
            method="B", state="unreliable", detail="rate at or below terminal growth", inputs=inputs
        )
    inputs["terminal_share"] = out.terminal_share
    if out.terminal_share > cfg.terminal_value_max_share:
        return MethodValue(
            method="B",
            value=out.value,
            state="unreliable",
            detail="terminal value above 75%",
            inputs=inputs,
        )
    return MethodValue(method="B", value=out.value, state="ok", inputs=inputs)


def method_d(base_ps: float | None, realised: float | None, cfg: ValueValuationCfg) -> MethodValue:
    """Growth DCF (quality growth only): FCF less half of SBC, per share, at the realised
    growth capped at 20%, r = 8%, fading to 2.5%."""
    inputs = {"fcf_ps": base_ps, "realised_growth": realised, "rate": cfg.discount_rate_growth}
    if base_ps is None or base_ps <= 0:
        return MethodValue(
            method="D", state="absent", detail="growth-normalised FCF not positive", inputs=inputs
        )
    if realised is None or realised <= 0:
        return MethodValue(
            method="D", state="absent", detail="no positive realised growth", inputs=inputs
        )
    g = min(realised, cfg.realised_cap_growth)
    inputs["growth"] = g
    out = dcf(base_ps, g, cfg.discount_rate_growth, cfg.terminal_growth, cfg.dcf_years)
    if out is None:
        return MethodValue(
            method="D", state="unreliable", detail="rate at or below terminal growth", inputs=inputs
        )
    inputs["terminal_share"] = out.terminal_share
    if out.terminal_share > cfg.terminal_value_max_share:
        return MethodValue(
            method="D",
            value=out.value,
            state="unreliable",
            detail="terminal value above 75%",
            inputs=inputs,
        )
    return MethodValue(method="D", value=out.value, state="ok", inputs=inputs)


def method_c() -> MethodValue:
    return MethodValue(
        method="C", state="absent", detail="needs ten years of point-in-time prices (spec §6.5)"
    )


def method_ptbv(
    rote_median: float | None, tbv_ps: float | None, cfg: ValueValuationCfg
) -> MethodValue:
    """Banks and insurers: justified P/TBV = (ROTE - g) / (r - g) x tangible book per share,
    with g the terminal growth rate and r the deep-value rate."""
    g, r = cfg.terminal_growth, cfg.discount_rate_deep
    inputs = {"rote_median": rote_median, "tbv_ps": tbv_ps, "rate": r, "growth": g}
    if rote_median is None or tbv_ps is None or tbv_ps <= 0:
        return MethodValue(
            method="PTBV", state="absent", detail="ROTE or tangible book missing", inputs=inputs
        )
    if rote_median <= g:
        return MethodValue(
            method="PTBV", state="absent", detail="ROTE at or below growth", inputs=inputs
        )
    return MethodValue(
        method="PTBV", value=(rote_median - g) / (r - g) * tbv_ps, state="ok", inputs=inputs
    )


def fair_value(methods: list[MethodValue], use: tuple[str, ...]) -> float | None:
    """The median of the listed methods that are ``ok`` (two present -> their mean)."""
    vals = [m.value for m in methods if m.method in use and m.state == "ok" and m.value is not None]
    return median(vals) if vals else None
```

- [x] **Step 4: Run the tests** — 10 passed.

- [x] **Step 5: Gates** — `ruff check`, `ruff format --check`, `mypy` on `src/value/valuation.py
  tests/test_value_valuation.py`.

- [x] **Step 6: Commit**

  ```bash
  git add src/value/valuation.py tests/test_value_valuation.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): the DCF, reverse DCF, methods A/B/C/D and justified P/TBV"
  ```

---

### Task 9: Timing and the scorecard

**Files:** Create `src/value/timing.py`, `src/value/scorecard.py`, `tests/test_value_scorecard.py`

**Interfaces:**
- Consumes: everything in Tasks 1–8.
- Produces (`timing.py`): `sessions_between(start, end) -> int`; `earnings_check(as_of,
  next_earnings, cfg) -> Check` (id `timing.earnings`); `deep_value_timing(price, rs_cutoff, cfg)
  -> list[Check]` (ids `timing.trend`, `timing.stopped_falling`); `growth_timing(price, cfg) ->
  list[Check]` (id `timing.not_breaking_down`).
- Produces (`scorecard.py`): `build_scorecard(inputs: ValueInputs, cfg: ValueCfg) ->
  ValueScorecard` (pure; `lists["deep_value"]` for every name that reaches the health gates;
  `lists["quality_growth"]` for operating and cyclical names); `fingerprint(inputs, version,
  digest)`; `per_share_count`; `normalised_fcf(inputs, years, company_class, sbc_share)`;
  `growth_entry_checks(inputs, years, cfg)` (ids `growth.cagr`, `growth.roic_median`,
  `growth.gross_margin_stdev`). Metric keys: `fcf_ttm`, `sbc_ttm`, `revenue_ttm`,
  `normalised_fcf_ps`, `growth_fcf_ps`, `per_share_count`, `net_debt`, `roic_median_5y`,
  `gross_margin_stdev_5y`, `revenue_cagr_5y` (+ `rote_median_5y`, `tbv_ps` for banks/insurers).

- [x] **Step 1: Write the failing tests** — `tests/test_value_scorecard.py`

```python
"""Timing and the scorecard's baseline verdicts (value book spec §6.6-6.7, §6.9)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.config import ValueCfg, get_config
from src.value.scorecard import build_scorecard
from src.value.timing import (
    deep_value_timing,
    earnings_check,
    growth_timing,
    sessions_between,
)
from tests.value_fixtures import AS_OF, BANK, financials, inputs, price

CFG = get_config().value
TIMING = CFG.rules.timing


def test_sessions_count_weekdays() -> None:
    assert sessions_between(date(2026, 3, 30), date(2026, 4, 6)) == 5  # Monday to Monday


@pytest.mark.parametrize(
    ("next_earnings", "state"),
    [
        (AS_OF + timedelta(days=7), "fail"),  # 5 sessions
        (AS_OF + timedelta(days=30), "pass"),
        (None, "unknown"),
        (AS_OF - timedelta(days=20), "pass"),  # reported recently: next is a quarter away
        (AS_OF - timedelta(days=100), "unknown"),
    ],
)
def test_the_earnings_window(next_earnings, state) -> None:
    assert earnings_check(AS_OF, next_earnings, TIMING).state == state


def _falling(n: int = 260) -> list[float]:
    return [100.0 - 0.2 * i for i in range(n)]


def test_deep_value_needs_trend_and_a_stop_in_the_fall() -> None:
    up = {c.id: c.state for c in deep_value_timing(price(30.0), -0.10, TIMING)}
    assert up == {"timing.trend": "pass", "timing.stopped_falling": "pass"}
    down = price(48.2, closes=_falling(), ret_6m=-0.30, spy_ret_6m=0.05)
    checks = {c.id: c.state for c in deep_value_timing(down, -0.10, TIMING)}
    assert checks == {"timing.trend": "fail", "timing.stopped_falling": "fail"}


def test_relative_strength_rescues_a_name_below_its_200_day_average() -> None:
    below = price(48.2, closes=_falling(), ret_6m=0.02, spy_ret_6m=0.05)
    trend = deep_value_timing(below, -0.10, TIMING)[0]
    assert (trend.state, trend.actual) == ("pass", pytest.approx(-0.03))
    assert deep_value_timing(below, None, TIMING)[0].state == "unknown"


def test_growth_is_refused_only_below_the_average_and_at_a_new_low() -> None:
    assert growth_timing(price(48.2, closes=_falling()), TIMING)[0].state == "fail"
    dip = [100.0 - 0.2 * i for i in range(250)] + [51.0 + i for i in range(10)]
    assert growth_timing(price(60.0, closes=dip), TIMING)[0].state == "pass"


# ── the scorecard ───────────────────────────────────────────────────────────────────────────


def test_a_healthy_cheap_grower_is_ready_on_both_lists() -> None:
    card = build_scorecard(inputs(close=30.0), CFG)
    assert (card.company_class, card.data_quality, card.health) == ("operating", "pass", "pass")
    deep, growth = card.lists["deep_value"], card.lists["quality_growth"]
    assert deep.verdict == "READY" and growth.verdict == "READY"
    assert deep.fair_value == pytest.approx(46.853626592284414)
    assert deep.margin_of_safety == pytest.approx(0.3597080486200778)
    assert deep.entry_ceiling == pytest.approx(35.140219944213314)
    assert growth.fair_value == pytest.approx(86.86667560395772)
    assert growth.mos_review is True  # a 65% margin goes to a human (spec §9.4)
    assert card.reverse_dcf_implied_growth == pytest.approx(-0.0487482551644291)
    assert card.realised_fcf_ps_cagr == pytest.approx(0.1474149978141155)


@pytest.mark.parametrize(
    ("close", "regime", "deep", "growth"),
    [
        (32.0, "normal", "READY", "READY"),
        (32.0, "stressed", "WAIT", "READY"),  # 35% required: ceiling 30.45
        (40.0, "normal", "WAIT", "READY"),
        (90.0, "normal", "WAIT", "WAIT"),
    ],
)
def test_the_regime_sets_how_demanding_the_entry_is(close, regime, deep, growth) -> None:
    card = build_scorecard(inputs(close=close, regime=regime), CFG)
    assert (card.lists["deep_value"].verdict, card.lists["quality_growth"].verdict) == (
        deep,
        growth,
    )


def test_cheap_with_timing_failing_is_watch() -> None:
    card = build_scorecard(inputs(close=30.0, next_earnings=AS_OF + timedelta(days=3)), CFG)
    assert card.lists["deep_value"].verdict == "WATCH"
    assert card.lists["deep_value"].reasons == ["cheap enough; timing fail"]


def test_a_failed_health_gate_is_no_on_every_list() -> None:
    card = build_scorecard(inputs(fin=financials(shares_diluted=[110, 104, 98, 92, 86])), CFG)
    assert card.health == "fail"
    for ev in card.lists.values():
        assert ev.verdict == "NO" and ev.reasons == ["health gate failed: health.dilution"]


def test_a_slow_grower_is_off_the_growth_list_but_still_valued_as_deep_value() -> None:
    slow = financials(
        revenue=[1200, 1150, 1100, 1050, 1000],
        operating_cash_flow=[300, 295, 290, 285, 280],
        capital_expenditure=[60, 60, 60, 60, 60],
    )
    card = build_scorecard(inputs(fin=slow), CFG)
    growth = card.lists["quality_growth"]
    assert growth.entry == "fail" and growth.verdict == "NO"
    assert card.lists["deep_value"].verdict in ("READY", "WATCH", "WAIT")


def test_a_data_quality_failure_is_unknown_and_never_reaches_the_lists() -> None:
    card = build_scorecard(inputs(yf_market_cap=6000.0), CFG)
    assert card.data_quality == "unknown" and card.lists == {}
    assert card.verdict_for("deep_value") == "UNKNOWN"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"is_etf": True}, "ETF"),
        ({"industry": "Retail REITs"}, "REIT: FFO is not reliably tagged"),
        (
            {
                "fin": financials(
                    net_income=[-50, -40, -30, 10, 5], operating_cash_flow=[-20, -10, 5, 30, 30]
                )
            },
            "pre-profit",
        ),
    ],
)
def test_names_the_scorecard_does_not_cover_are_not_applicable(kwargs, reason) -> None:
    card = build_scorecard(inputs(**kwargs), CFG)
    assert card.not_applicable_reason == reason
    assert card.verdict_for("deep_value") == card.verdict_for("quality_growth") == "NOT_APPLICABLE"


def test_a_bank_is_valued_on_tangible_book_and_held_unknown_without_cet1() -> None:
    card = build_scorecard(
        inputs(symbol="HBR", fin=financials(BANK), close=40.0, industry="Diversified Banks"), CFG
    )
    assert card.company_class == "bank" and list(card.lists) == ["deep_value"]
    deep = card.lists["deep_value"]
    assert deep.fair_value == pytest.approx(38.12437562437562)
    assert deep.verdict == "UNKNOWN"
    off = ValueCfg(ruleset_version="test", rules={"banks": {"require_cet1": False}})
    assert (
        build_scorecard(
            inputs(symbol="HBR", fin=financials(BANK), close=40.0, industry="Diversified Banks"),
            off,
        )
        .lists["deep_value"]
        .verdict
        == "WAIT"
    )


def test_the_fingerprint_names_the_inputs_and_moves_with_the_price() -> None:
    a = build_scorecard(inputs(close=30.0), CFG)
    b = build_scorecard(inputs(close=30.5), CFG)
    assert a.fingerprint.latest_accn == "0000000001-26-000001"
    assert a.fingerprint.price_close == 30.0 and a.fingerprint.regime == "normal"
    assert a.fingerprint.key() != b.fingerprint.key()


def test_the_scorecard_is_a_pure_function_of_its_inputs() -> None:
    assert (
        build_scorecard(inputs(), CFG).model_dump_json()
        == build_scorecard(inputs(), CFG).model_dump_json()
    )
```

- [x] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named
  'src.value.timing'`.

- [x] **Step 3: Create `src/value/timing.py`**

```python
"""Entry timing (spec §6.6): strict for deep value, soft for quality growth. Pure: no I/O.

A hard gate on both lists: a READY whose timing does not pass is WATCH.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.common.config import ValueTimingCfg
from src.common.value_types import PriceSeries
from src.value.schemas import Check


def sessions_between(start: date, end: date) -> int:
    """Weekdays in [start, end): the sessions before *end* counting *start* (holidays are not
    known here, so this errs by at most a day or two)."""
    n, d = 0, start
    while d < end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def earnings_check(as_of: date, next_earnings: date | None, cfg: ValueTimingCfg) -> Check:
    """Refused within ``earnings_window_sessions`` sessions before earnings. A missing date,
    or one already past with no newer one, is UNKNOWN, never a pass."""
    window = float(cfg.earnings_window_sessions)
    if next_earnings is None:
        return Check(
            id="timing.earnings", state="unknown", threshold=window, detail="no earnings date"
        )
    if next_earnings < as_of:
        # yfinance returns the last report until the next is announced. A report this recent
        # means the next one is a quarter away, well past the window.
        ago = (as_of - next_earnings).days
        if ago <= cfg.recent_report_days:
            return Check(
                id="timing.earnings",
                state="pass",
                threshold=window,
                detail=f"inferred: reported {ago} days ago ({next_earnings}), next not yet dated",
            )
        return Check(
            id="timing.earnings",
            state="unknown",
            threshold=window,
            detail=f"last known earnings date {next_earnings} has passed",
        )
    n = sessions_between(as_of, next_earnings)
    return Check(
        id="timing.earnings",
        state="fail" if n <= cfg.earnings_window_sessions else "pass",
        actual=float(n),
        threshold=window,
        detail=f"earnings {next_earnings}",
    )


def _low_index(closes: list[float]) -> int:
    """Index of the lowest close (the latest one on a tie)."""
    low = min(closes)
    return max(i for i, c in enumerate(closes) if c == low)


def deep_value_timing(
    price: PriceSeries | None, rs_cutoff: float | None, cfg: ValueTimingCfg
) -> list[Check]:
    """Strict: (above the 200-day SMA, or 6-month relative strength vs SPY not in the bottom
    30% of the run) and has stopped falling (a close above its 20-day SMA after the low of the
    last ``low_lookback_sessions``)."""
    if price is None:
        return [
            Check(id="timing.trend", state="unknown"),
            Check(id="timing.stopped_falling", state="unknown"),
        ]
    checks: list[Check] = []
    if price.sma200 is not None and price.close > price.sma200:
        checks.append(
            Check(
                id="timing.trend",
                state="pass",
                actual=price.close,
                threshold=price.sma200,
                detail="above the 200-day SMA",
            )
        )
    elif price.ret_6m is None or price.spy_ret_6m is None or rs_cutoff is None:
        checks.append(
            Check(
                id="timing.trend",
                state="unknown",
                detail="below or without a 200-day SMA; relative strength not computable",
            )
        )
    else:
        excess = price.ret_6m - price.spy_ret_6m
        checks.append(
            Check(
                id="timing.trend",
                state="pass" if excess >= rs_cutoff else "fail",
                actual=excess,
                threshold=rs_cutoff,
                detail="6-month return less SPY's, against the run's bottom-30% line",
            )
        )
    window = price.closes[-cfg.low_lookback_sessions :]
    smas = price.sma20s[-cfg.low_lookback_sessions :]
    if len(window) < cfg.low_lookback_sessions:
        checks.append(
            Check(id="timing.stopped_falling", state="unknown", detail="too little history")
        )
    else:
        low = _low_index(window)
        after = [
            (c, s) for c, s in zip(window[low + 1 :], smas[low + 1 :], strict=True) if s is not None
        ]
        recovered = any(c > s for c, s in after)
        checks.append(
            Check(
                id="timing.stopped_falling",
                state="pass" if recovered else "fail",
                actual=float(len(window) - 1 - low),
                detail="sessions since the low; passes on a close above the 20-day SMA after it",
            )
        )
    return checks


def growth_timing(price: PriceSeries | None, cfg: ValueTimingCfg) -> list[Check]:
    """Soft: refused only below the 200-day SMA and at a new 52-week low (the lowest close of
    the last 252 sessions set within the last ``new_low_window_sessions``)."""
    if price is None or price.sma200 is None:
        return [Check(id="timing.not_breaking_down", state="unknown")]
    year = price.closes[-252:]
    low = _low_index(year)
    new_low = (len(year) - 1 - low) < cfg.new_low_window_sessions
    below = price.close < price.sma200
    return [
        Check(
            id="timing.not_breaking_down",
            state="fail" if (below and new_low) else "pass",
            actual=price.close,
            threshold=price.sma200,
            detail="below the 200-day SMA and at a new 52-week low"
            if (below and new_low)
            else "not both below the 200-day SMA and at a new 52-week low",
        )
    ]
```

- [x] **Step 4: Create `src/value/scorecard.py`**

```python
"""The scorecard: one pure function from inputs and config to Part 1 of a ticker file.

docs/superpowers/specs/2026-10-28-value-swing-book-design.md §6.3-6.7, §6.9. No I/O: the API
may import this module and compute a ticker file during a request (tests/test_value_fence.py).
"""

from __future__ import annotations

from statistics import median

from src.common.config import ValueCfg
from src.common.schemas import MarketRegime
from src.common.value_types import ValueInputs
from src.value import gates, timing, valuation
from src.value.metrics import Year, cagr, median_of, roic, stdev_of
from src.value.ruleset import ruleset_id
from src.value.schemas import (
    Check,
    CompanyClass,
    Fingerprint,
    GateState,
    ListEvaluation,
    ListName,
    MethodValue,
    ValueScorecard,
    Verdict,
    combine,
)

_FINANCIAL: tuple[CompanyClass, ...] = ("bank", "insurer")


def _regime(inputs: ValueInputs) -> MarketRegime:
    try:
        return MarketRegime(inputs.regime)
    except ValueError:
        return MarketRegime.NORMAL


def fingerprint(inputs: ValueInputs, version: str, digest: str) -> Fingerprint:
    fin, price = inputs.financials, inputs.price
    return Fingerprint(
        latest_accn=fin.latest_accn if fin else None,
        latest_filed=fin.latest_filed if fin else None,
        price_date=price.as_of if price else None,
        price_close=price.close if price else None,
        regime=inputs.regime,
        ruleset_version=version,
        ruleset_hash=digest,
    )


def _ttm(inputs: ValueInputs, item: str) -> float | None:
    point = inputs.financials.ttm.get(item) if inputs.financials else None
    return point.value if point is not None else None


def per_share_count(inputs: ValueInputs, years: list[Year]) -> float | None:
    """The newest weighted diluted count (a 10-Q's, else the last fiscal year's)."""
    fin = inputs.financials
    if fin is not None and fin.shares_latest:
        return fin.shares_latest
    return years[0].shares if years else None


def normalised_fcf(
    inputs: ValueInputs, years: list[Year], company_class: CompanyClass, sbc_share: float
) -> float | None:
    """TTM FCF less *sbc_share* of TTM SBC; for a cyclical, the 5-year median of that margin
    times TTM revenue. Untagged SBC counts as zero."""
    if company_class == "cyclical":
        margins = [
            (y.fcf - sbc_share * (y.sbc or 0.0)) / y.revenue
            for y in years[:5]
            if y.fcf is not None and y.revenue
        ]
        revenue = _ttm(inputs, "revenue")
        if not margins or revenue is None:
            return None
        return median(margins) * revenue
    fcf = gates.ttm_fcf(inputs)
    if fcf is None:
        return None
    return fcf - sbc_share * (_ttm(inputs, "sbc") or 0.0)


def _fcf_ps_series(years: list[Year]) -> list[float | None]:
    return [None if y.fcf is None or not y.shares else y.fcf / y.shares for y in years]


def _verdict(
    health: GateState,
    health_checks: list[Check],
    entry: GateState,
    fair: float | None,
    price: float,
    ceiling: float | None,
    timing_state: GateState,
) -> tuple[Verdict, list[str]]:
    if health == "fail":
        failed = [c.id for c in health_checks if c.state == "fail"]
        return "NO", [f"health gate failed: {', '.join(failed)}"]
    if health == "unknown":
        unknown = [c.id for c in health_checks if c.state == "unknown"]
        return "UNKNOWN", [f"health gate unknown: {', '.join(unknown)}"]
    if entry != "pass":
        return "NO", [f"entry rule {entry}"]
    if fair is None or ceiling is None:
        return "NO", ["no fair value"]
    if price > ceiling:
        return "WAIT", [f"price {price:.2f} above the entry ceiling {ceiling:.2f}"]
    if timing_state != "pass":
        return "WATCH", [f"cheap enough; timing {timing_state}"]
    return "READY", ["healthy, cheap enough, timing passes"]


def _evaluate(
    list_name: ListName,
    *,
    inputs: ValueInputs,
    cfg: ValueCfg,
    health: GateState,
    health_checks: list[Check],
    entry_checks: list[Check],
    methods: list[MethodValue],
    use: tuple[str, ...],
    timing_checks: list[Check],
) -> ListEvaluation:
    rules = cfg.rules
    assert inputs.price is not None
    price = inputs.price.close
    required = getattr(rules.margin_of_safety, list_name)[_regime(inputs)]
    entry = combine(entry_checks) if entry_checks else "pass"
    fair = valuation.fair_value(methods, use)
    mos = None if fair is None else (fair - price) / fair
    ceiling = None if fair is None else fair * (1.0 - required / 100.0)
    timing_state = combine(timing_checks)
    verdict, reasons = _verdict(health, health_checks, entry, fair, price, ceiling, timing_state)
    return ListEvaluation(
        list_name=list_name,
        entry=entry,
        entry_checks=entry_checks,
        methods=methods,
        fair_value=fair,
        required_mos_pct=required,
        margin_of_safety=mos,
        entry_ceiling=ceiling,
        timing=timing_state,
        timing_checks=timing_checks,
        verdict=verdict,
        reasons=reasons,
        mos_review=mos is not None and mos * 100.0 > rules.margin_of_safety.review_above_pct,
    )


def growth_entry_checks(inputs: ValueInputs, years: list[Year], cfg: ValueCfg) -> list[Check]:
    """Spec §6.0: 5-year revenue CAGR >= 10% (or FCF/share CAGR >= 10%), 5-year median ROIC
    >= 15%, gross-margin standard deviation <= 5 points."""
    q = cfg.rules.quality_growth
    rev = cagr([y.revenue for y in years])
    fcf_ps = cagr(_fcf_ps_series(years))
    grows = [g for g in (rev, fcf_ps) if g is not None]
    if not grows:
        growth = Check(id="growth.cagr", state="unknown", threshold=q.revenue_cagr_min_pct)
    else:
        ok = (rev is not None and rev * 100 >= q.revenue_cagr_min_pct) or (
            fcf_ps is not None and fcf_ps * 100 >= q.fcf_ps_cagr_min_pct
        )
        growth = Check(
            id="growth.cagr",
            state="pass" if ok else "fail",
            actual=max(grows) * 100,
            threshold=q.revenue_cagr_min_pct,
            detail=f"revenue {_pct(rev)}, FCF/share {_pct(fcf_ps)}",
        )
    roic_med = median_of([roic(y) for y in years])
    gm_sd = stdev_of([y.gross_margin for y in years])
    return [
        growth,
        gates.check_at_least(
            "growth.roic_median",
            None if roic_med is None else roic_med * 100,
            q.roic_median_min_pct,
        ),
        gates.check_at_most(
            "growth.gross_margin_stdev",
            None if gm_sd is None else gm_sd * 100,
            q.gross_margin_stdev_max_pts,
        ),
    ]


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def build_scorecard(inputs: ValueInputs, cfg: ValueCfg) -> ValueScorecard:
    """Part 1 of the ticker file for one name. Never raises on missing data: it says UNKNOWN."""
    version, digest = ruleset_id(cfg)
    rules = cfg.rules
    card = ValueScorecard(
        symbol=inputs.symbol,
        as_of=inputs.as_of,
        ruleset_version=version,
        ruleset_hash=digest,
        company_class="etf" if inputs.classification.is_etf else "operating",
        classification=inputs.classification,
        data_quality="unknown",
        price=inputs.price.close if inputs.price else None,
        fingerprint=fingerprint(inputs, version, digest),
    )
    if inputs.classification.is_etf:
        return card.model_copy(
            update={"data_quality": "not_applicable", "not_applicable_reason": "ETF"}
        )

    years, shares = gates.build_years_for(inputs)
    dq_checks = gates.data_quality(inputs, years, shares, rules)
    dq = combine(dq_checks)
    company_class = gates.classify(inputs, years, rules)
    count = gates.edgar_shares(inputs)
    edgar_cap = count * inputs.price.close if count and inputs.price else None
    card = card.model_copy(
        update={
            "company_class": company_class,
            "data_quality": dq,
            "data_quality_checks": dq_checks,
            "market_cap_edgar": edgar_cap,
            "adjustments": shares.adjustments,
        }
    )
    if dq != "pass":
        return card
    assert inputs.price is not None

    v = rules.valuation
    nfcf = normalised_fcf(inputs, years, company_class, 1.0)
    gfcf = normalised_fcf(inputs, years, company_class, v.growth_sbc_share)
    per_share = per_share_count(inputs, years)
    nfcf_ps = None if nfcf is None or not per_share else nfcf / per_share
    gfcf_ps = None if gfcf is None or not per_share else gfcf / per_share
    realised = cagr(_fcf_ps_series(years))
    implied = (
        None
        if nfcf_ps is None
        else valuation.implied_growth(
            inputs.price.close, nfcf_ps, v.discount_rate_deep, v.terminal_growth, v.dcf_years
        )
    )
    metrics: dict[str, float | None] = {
        "fcf_ttm": gates.ttm_fcf(inputs),
        "sbc_ttm": _ttm(inputs, "sbc"),
        "revenue_ttm": _ttm(inputs, "revenue"),
        "normalised_fcf_ps": nfcf_ps,
        "growth_fcf_ps": gfcf_ps,
        "per_share_count": per_share,
        "net_debt": gates.net_debt_latest(inputs),
        "roic_median_5y": median_of([roic(y) for y in years]),
        "gross_margin_stdev_5y": stdev_of([y.gross_margin for y in years]),
        "revenue_cagr_5y": cagr([y.revenue for y in years]),
    }
    card = card.model_copy(
        update={
            "metrics": metrics,
            "reverse_dcf_implied_growth": implied,
            "realised_fcf_ps_cagr": realised,
        }
    )
    if company_class == "reit":
        return card.model_copy(update={"not_applicable_reason": "REIT: FFO is not reliably tagged"})
    if company_class not in _FINANCIAL and gates.preprofit(years, rules):
        return card.model_copy(update={"not_applicable_reason": "pre-profit"})

    deep_use: tuple[str, ...]
    if company_class in _FINANCIAL:
        health_checks = gates.financial_health(
            inputs, years, rules, insurer=company_class == "insurer"
        )
        rote_med = median_of(gates.rote_series(years))
        tbv_ps = gates.latest_tbv_per_share(inputs, years)
        metrics["rote_median_5y"] = rote_med
        metrics["tbv_ps"] = tbv_ps
        deep_methods = [valuation.method_ptbv(rote_med, tbv_ps, v)]
        deep_use = ("PTBV",)
    else:
        health_checks = gates.operating_health(
            inputs, years, edgar_cap, rules, cyclical=company_class == "cyclical"
        )
        deep_methods = [
            valuation.method_a(nfcf_ps, v),
            valuation.method_b(nfcf_ps, realised, v),
            valuation.method_c(),
        ]
        deep_use = ("A", "B", "C")
    health = combine(health_checks)
    earnings = timing.earnings_check(inputs.as_of, inputs.next_earnings, rules.timing)
    lists: dict[str, ListEvaluation] = {
        "deep_value": _evaluate(
            "deep_value",
            inputs=inputs,
            cfg=cfg,
            health=health,
            health_checks=health_checks,
            entry_checks=[],
            methods=deep_methods,
            use=deep_use,
            timing_checks=[
                earnings,
                *timing.deep_value_timing(inputs.price, inputs.rs_cutoff_6m, rules.timing),
            ],
        )
    }
    if company_class not in _FINANCIAL:
        lists["quality_growth"] = _evaluate(
            "quality_growth",
            inputs=inputs,
            cfg=cfg,
            health=health,
            health_checks=health_checks,
            entry_checks=growth_entry_checks(inputs, years, cfg),
            methods=[
                valuation.method_d(gfcf_ps, realised, v),
                valuation.method_c(),
                deep_methods[0],
            ],
            use=("D", "C"),
            timing_checks=[earnings, *timing.growth_timing(inputs.price, rules.timing)],
        )
    return card.model_copy(
        update={
            "metrics": metrics,
            "health": health,
            "health_checks": health_checks,
            "lists": lists,
        }
    )
```

- [x] **Step 5: Run the tests** — `.venv/bin/python -m pytest -q tests/test_value_scorecard.py`
  → 24 passed; then every value test so far: `.venv/bin/python -m pytest -q tests/test_value_*.py`
  → 107 passed.

- [x] **Step 6: Gates** — `ruff check`, `ruff format --check`, `mypy` on `src/value
  tests/test_value_scorecard.py`.

- [x] **Step 7: Commit**

  ```bash
  git add src/value/timing.py src/value/scorecard.py tests/test_value_scorecard.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): entry timing and the pure scorecard with Python's baseline verdict per list"
  ```

**Section B exit (orchestrator):** `git log --oneline main..HEAD | wc -l` → `9`; full gate green,
pytest = baseline + 115; protected-file diff empty. Then ask the operator.

---

## Section C — Ticker file, rank, dry-run tooling, fences, docs (Tasks 10–14) · model: sonnet

The cross-sectional rank, `value.db` with the ticker file, the funnel, the fence tests, the
dry-run script and the documentation sweep. After this section the code of Part 1 is complete.

**Spec to read:** §6.8 (the ranked record's score; the ruleset), §6.9 (the ticker file, Part 1),
§16, §17, §18.

**Files the subagent reads:** this section; `src/value/schemas.py`, `src/value/scorecard.py`
(signatures), `src/spreads/store.py` (lines 1–60, 215–285: the separate-Base pattern),
`tests/test_spreads_fence.py` (lines 1–90: `imported_modules`, `_reaches`),
`src/research/ingest/materialize.py` (`drain_ingest_jobs`), `src/news/store/queries.py`
(`earnings_between`), and for Task 14 the doc anchors it names.

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **C1. Section B landed.** `git log --oneline main..HEAD | wc -l` prints `9`; Tasks 5–9
  ticked.
- [ ] **C2. Green.** `.venv/bin/python -m pytest -q` (baseline + 115), `.venv/bin/ruff check .`,
  `.venv/bin/mypy src`.
- [ ] **C3. The scorecard is pure today.** Prints nothing:

  ```bash
  grep -n "sqlalchemy\|httpx\|yfinance\|src.data\|src.storage\|open(" src/value/schemas.py src/value/metrics.py src/value/scores.py src/value/gates.py src/value/valuation.py src/value/timing.py src/value/scorecard.py src/value/ruleset.py
  ```

- [ ] **C4. The pieces Section C reuses exist under these names.** Each prints a line:

  ```bash
  grep -n "^def imported_modules\|^def _reaches" tests/test_spreads_fence.py
  grep -n "^class SpreadsBase\|^def get_spreads_engine\|^def spreads_session" src/spreads/store.py
  grep -n "^def build_scorecard\|^def fingerprint" src/value/scorecard.py
  grep -n "^def earnings_between" src/news/store/queries.py
  grep -n "^## 18. Market regime\|^## Troubleshooting" SETUP.md
  grep -n "^### \`src/ops/\`\|^## Key invariants\|^### \`scripts/\`\|^### \`src/common/\`\|^### \`config/\`" ARCHITECTURE.md
  grep -n "^## Not built (deliberately deferred)\|^## Built (2026-10-28" STATUS.md
  grep -n "^### The news fence\|^## Reference documentation" CLAUDE.md
  ```

**Section exit:** five more commits (14 in all); full gate green with pytest = baseline + 141;
`.venv/bin/python -m py_compile scripts/value_dry_run.py scripts/value_universe_snapshot.py`
silent; protected-file diff empty.

---

### Task 10: The rank score, the filed list and the relative-strength line

**Files:** Create `src/value/rank.py`, `tests/test_value_rank.py`

**Interfaces:**
- Consumes: `ValueScorecard`, `ListName` (Task 5), `PriceSeries` (Task 3).
- Produces: `RankEntry(symbol, list_name, value_pct, quality_pct, score)`;
  `percentiles(values: dict[str, float]) -> dict[str, float]`; `rank_list(cards, list_name) ->
  dict[str, RankEntry]`; `filed_lists(cards, deep, growth) -> dict[str, ListName]`;
  `rs_cutoff(prices, bottom_pct) -> float | None`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_rank.py`

```python
"""The rank score, the filed list and the relative-strength line (value book spec §6.6, §6.8)."""

from __future__ import annotations

import pytest

from src.common.config import get_config
from src.value.rank import filed_lists, percentiles, rank_list, rs_cutoff
from src.value.scorecard import build_scorecard
from tests.value_fixtures import financials, inputs, price

CFG = get_config().value


def test_percentiles_share_ties_and_span_zero_to_one() -> None:
    assert percentiles({"a": 1.0, "b": 2.0, "c": 2.0, "d": 3.0}) == {
        "a": 0.0,
        "b": 0.5,
        "c": 0.5,
        "d": 1.0,
    }
    assert percentiles({"a": 5.0}) == {"a": 0.5}
    assert percentiles({}) == {}


def _cards():
    return [
        build_scorecard(inputs(symbol="CHEAP", close=25.0), CFG),
        build_scorecard(inputs(symbol="MID", close=35.0), CFG),
        build_scorecard(inputs(symbol="DEAR", close=60.0), CFG),
        build_scorecard(inputs(symbol="ETF", is_etf=True), CFG),
        build_scorecard(inputs(symbol="BAD", yf_market_cap=1.0), CFG),
    ]


def test_rank_orders_by_value_then_quality_and_skips_the_unscored() -> None:
    ranks = rank_list(_cards(), "deep_value")
    assert set(ranks) == {"CHEAP", "MID", "DEAR"}
    assert [ranks[s].value_pct for s in ("CHEAP", "MID", "DEAR")] == [1.0, 0.5, 0.0]
    assert ranks["CHEAP"].quality_pct == 0.5  # identical fundamentals: every component ties
    assert ranks["CHEAP"].score == pytest.approx(0.75)


def test_a_name_on_both_lists_is_filed_where_it_ranks_higher() -> None:
    cards = _cards()
    deep, growth = rank_list(cards, "deep_value"), rank_list(cards, "quality_growth")
    filed = filed_lists(cards, deep, growth)
    assert filed["CHEAP"] == "deep_value"  # ties go to deep value
    deep["MID"] = deep["MID"].model_copy(update={"score": 0.1})
    assert filed_lists(cards, deep, growth)["MID"] == "quality_growth"
    assert filed["ETF"] == "deep_value" and filed["BAD"] == "deep_value"


def test_a_name_off_the_growth_list_is_never_filed_there() -> None:
    slow = financials(
        revenue=[1200, 1150, 1100, 1050, 1000],
        operating_cash_flow=[300, 295, 290, 285, 280],
        capital_expenditure=[60, 60, 60, 60, 60],
    )
    cards = [build_scorecard(inputs(symbol="SLOW", fin=slow), CFG)]
    growth = rank_list(cards, "quality_growth")
    deep = {"SLOW": rank_list(cards, "deep_value")["SLOW"].model_copy(update={"score": 0.0})}
    assert filed_lists(cards, deep, growth)["SLOW"] == "deep_value"


def test_the_relative_strength_line_is_the_bottom_thirty_percent() -> None:
    series = [price(30.0, ret_6m=r / 100.0, spy_ret_6m=0.0) for r in range(0, 11)]  # 0..10%
    assert rs_cutoff(series, 30.0) == pytest.approx(0.03)
    assert rs_cutoff(series[:5], 30.0) is None
    assert rs_cutoff([None, *series], 30.0) == pytest.approx(0.03)
```

- [x] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named
  'src.value.rank'`.

- [x] **Step 3: Create `src/value/rank.py`**

```python
"""The rank score (spec §6.8) and the run's relative-strength line (spec §6.6). Pure: no I/O.

Cross-sectional, so it runs over a whole night's scorecards, never inside one. It orders names
within a verdict state, decides which list a name that qualifies for both is filed on, and (Part
2) which healthy names Claude reads first. It never feeds a gate or a size.
"""

from __future__ import annotations

from statistics import mean

from pydantic import BaseModel

from src.common.value_types import PriceSeries
from src.value.schemas import ListName, ValueScorecard


class RankEntry(BaseModel):
    symbol: str
    list_name: ListName
    value_pct: float | None
    quality_pct: float | None
    score: float | None


def percentiles(values: dict[str, float]) -> dict[str, float]:
    """0 for the lowest, 1 for the highest, ties share the average; a lone value is 0.5."""
    n = len(values)
    if n == 0:
        return {}
    if n == 1:
        return {k: 0.5 for k in values}
    ordered = sorted(values.values())
    out: dict[str, float] = {}
    for key, v in values.items():
        less = sum(1 for x in ordered if x < v)
        equal = sum(1 for x in ordered if x == v)
        out[key] = (less + (equal - 1) / 2.0) / (n - 1)
    return out


def _check_actual(card: ValueScorecard, check_id: str) -> float | None:
    for c in card.health_checks:
        if c.id == check_id:
            return c.actual
    return None


def _quality_components(card: ValueScorecard, list_name: ListName) -> dict[str, float]:
    """Higher is better for every component (variabilities are negated)."""
    m = card.metrics
    raw: dict[str, float | None]
    if card.company_class in ("bank", "insurer"):
        sd = _check_actual(card, "bank.rote_stdev")
        raw = {
            "rote_median": m.get("rote_median_5y"),
            "rote_stability": None if sd is None else -sd,
        }
    else:
        gm = m.get("gross_margin_stdev_5y")
        raw = {
            "piotroski": _check_actual(card, "health.piotroski"),
            "roic_median": m.get("roic_median_5y"),
            "margin_stability": None if gm is None else -gm,
        }
        if list_name == "quality_growth":
            raw["revenue_growth"] = m.get("revenue_cagr_5y")
    return {k: v for k, v in raw.items() if v is not None}


def rank_list(cards: list[ValueScorecard], list_name: ListName) -> dict[str, RankEntry]:
    """Rank every scored name on *list_name*: the mean of a value percentile (margin of safety;
    normalised FCF yield where fair value is missing) and a quality percentile (the mean of its
    component percentiles). Data-quality failures and not-applicable names are excluded."""
    pop = [
        c
        for c in cards
        if c.data_quality == "pass" and c.not_applicable_reason is None and list_name in c.lists
    ]
    mos: dict[str, float] = {}
    fcf_yield: dict[str, float] = {}
    for c in pop:
        ev = c.lists[list_name]
        if ev.margin_of_safety is not None:
            mos[c.symbol] = ev.margin_of_safety
        nfcf = c.metrics.get("normalised_fcf_ps")
        if nfcf is not None and c.price:
            fcf_yield[c.symbol] = nfcf / c.price
    mos_pct, yield_pct = percentiles(mos), percentiles(fcf_yield)

    components = {c.symbol: _quality_components(c, list_name) for c in pop}
    names = sorted({k for comp in components.values() for k in comp})
    comp_pct = {
        name: percentiles({s: comp[name] for s, comp in components.items() if name in comp})
        for name in names
    }
    out: dict[str, RankEntry] = {}
    for c in pop:
        value = mos_pct.get(c.symbol, yield_pct.get(c.symbol))
        mine = [comp_pct[n][c.symbol] for n in names if c.symbol in comp_pct[n]]
        quality = mean(mine) if mine else None
        parts = [p for p in (value, quality) if p is not None]
        out[c.symbol] = RankEntry(
            symbol=c.symbol,
            list_name=list_name,
            value_pct=value,
            quality_pct=quality,
            score=mean(parts) if parts else None,
        )
    return out


def filed_lists(
    cards: list[ValueScorecard],
    deep: dict[str, RankEntry],
    growth: dict[str, RankEntry],
) -> dict[str, ListName]:
    """Deep value, unless the name passes health and the quality-growth entry rule and ranks
    higher there (spec §6.0: filed on the list where its rank score is higher)."""
    out: dict[str, ListName] = {}
    for c in cards:
        ev = c.lists.get("quality_growth")
        qualifies = c.health == "pass" and ev is not None and ev.entry == "pass"
        g = growth.get(c.symbol)
        d = deep.get(c.symbol)
        g_score = g.score if g and g.score is not None else None
        d_score = d.score if d and d.score is not None else None
        if qualifies and g_score is not None and (d_score is None or g_score > d_score):
            out[c.symbol] = "quality_growth"
        else:
            out[c.symbol] = "deep_value"
    return out


def rs_cutoff(prices: list[PriceSeries | None], bottom_pct: float) -> float | None:
    """The *bottom_pct* percentile of 6-month return less SPY's across the run (linear
    interpolation between ranks). None with fewer than 10 names."""
    excess = sorted(
        p.ret_6m - p.spy_ret_6m
        for p in prices
        if p is not None and p.ret_6m is not None and p.spy_ret_6m is not None
    )
    if len(excess) < 10:
        return None
    k = (len(excess) - 1) * bottom_pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(excess) - 1)
    return excess[lo] + (excess[hi] - excess[lo]) * (k - lo)
```

- [x] **Step 4: Run the tests** — 5 passed.

- [x] **Step 5: Gates** — `ruff check`, `ruff format --check`, `mypy` on `src/value/rank.py
  tests/test_value_rank.py`.

- [x] **Step 6: Commit**

  ```bash
  git add src/value/rank.py tests/test_value_rank.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): the rank score, the filed list and the relative-strength line"
  ```

---

### Task 11: `value.db` and the ticker file

**Files:** Create `src/value/store.py`, `src/value/ticker_file.py`, `tests/test_value_store.py`

**Interfaces:**
- Consumes: `ValueScorecard`, `Fingerprint`, `LISTS` (Task 5); `ValueTickerFileCfg` (Task 1).
- Produces (`store.py`): `ValueBase`; `ValueTickerFileRow` (`value_ticker_files`, one row per
  symbol), `ValueTickerHistoryRow` (`value_ticker_history`), `ValueRunRow` (`value_runs`);
  `_resolve_url()` (patched in tests), `get_value_engine()`, `reset_engine()`,
  `init_value_db()`, `value_session()`.
- Produces (`ticker_file.py`): `WriteResult(changed, history_reason)`; `summary(card, ranks,
  filed) -> dict`; `what_changed(prev, new, cfg) -> list[str]`; `persist(session, card, *,
  universe, ranks, filed, cfg, session_row) -> WriteResult`; `is_fresh(stored, current) -> bool`;
  `stored_fingerprint(session, symbol) -> Fingerprint | None`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_store.py`

```python
"""value.db and the ticker file: latest row, history on change, one session row, freshness
(value book spec §6.9)."""

from __future__ import annotations

import json

import pytest

import src.value.store as store
from src.common.config import get_config
from src.value.scorecard import build_scorecard
from src.value.store import ValueTickerFileRow, ValueTickerHistoryRow, init_value_db, value_session
from src.value.ticker_file import is_fresh, persist, stored_fingerprint, what_changed
from tests.value_fixtures import inputs

CFG = get_config().value


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def _save(card, *, session_row: bool = True):
    with value_session() as s:
        return persist(
            s,
            card,
            universe="trading",
            ranks={"deep_value": 0.7},
            filed="deep_value",
            cfg=CFG.ticker_file,
            session_row=session_row,
        )


def _history():
    with value_session() as s:
        return [
            (r.reason, json.loads(r.changed), r.scorecard_json is not None)
            for r in s.query(ValueTickerHistoryRow).order_by(ValueTickerHistoryRow.id)
        ]


def test_a_new_name_writes_its_file_and_a_full_history_row(value_db) -> None:
    result = _save(build_scorecard(inputs(close=30.0), CFG))
    assert result.changed == ["new"] and result.history_reason == "changed"
    with value_session() as s:
        row = s.get(ValueTickerFileRow, "STDY")
        assert row is not None
        assert (row.verdict_deep, row.verdict_growth, row.filed_list, row.rank_deep) == (
            "READY",
            "READY",
            "deep_value",
            0.7,
        )
        assert row.fair_value_deep == pytest.approx(46.853626592284414)
    assert _history() == [("changed", ["new"], True)]


def test_the_same_day_again_writes_no_second_row(value_db) -> None:
    _save(build_scorecard(inputs(close=30.0), CFG))
    result = _save(build_scorecard(inputs(close=30.0), CFG))
    assert result.changed == [] and result.history_reason is None
    assert len(_history()) == 1


def test_a_new_session_with_nothing_changed_writes_one_compact_row(value_db) -> None:
    card = build_scorecard(inputs(close=30.0), CFG)
    _save(card)
    later = card.model_copy(update={"as_of": card.as_of.replace(day=card.as_of.day - 1)})
    assert _save(later).history_reason == "session"
    assert _save(later).history_reason is None
    assert _history()[-1] == ("session", [], False)


def test_a_verdict_or_a_band_change_is_recorded_with_what_changed(value_db) -> None:
    _save(build_scorecard(inputs(close=30.0), CFG))
    result = _save(build_scorecard(inputs(close=40.0), CFG))
    assert "deep_value.verdict" in result.changed and "deep_value.mos_band" in result.changed
    assert _history()[-1][0] == "changed"


def test_a_small_fair_value_move_is_not_a_change() -> None:
    prev = {"lists": {"deep_value": {"fair_value": 100.0, "mos": 0.30}}}
    new = {"lists": {"deep_value": {"fair_value": 100.5, "mos": 0.31}}}
    assert what_changed(prev, new, CFG.ticker_file) == []
    new["lists"]["deep_value"]["fair_value"] = 102.0
    assert what_changed(prev, new, CFG.ticker_file) == ["deep_value.fair_value"]


def test_freshness_is_fingerprint_equality(value_db) -> None:
    card = build_scorecard(inputs(close=30.0), CFG)
    _save(card)
    with value_session() as s:
        stored = stored_fingerprint(s, "STDY")
    assert is_fresh(stored, card.fingerprint)
    assert not is_fresh(stored, build_scorecard(inputs(close=31.0), CFG).fingerprint)
    assert not is_fresh(None, card.fingerprint)
```

- [x] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named
  'src.value.store'`.

- [x] **Step 3: Create `src/value/store.py`**

```python
"""The value book's own SQLite database (``data/value.db``), spec §6.9 and §9.7.

A separate engine and DeclarativeBase (the ``src/spreads/store.py`` pattern), so ``create_all``
can never build a value table in another database. ``src/value/`` is its only writer
(tests/test_web_fence.py). Timestamps are naive UTC.

Part 1 tables:
- ``value_ticker_files`` - the latest Part 1 of every name ever scored (one row per symbol);
- ``value_ticker_history`` - append-only: a full row when anything that matters changed, a
  compact row once per session for names in the ranked universe;
- ``value_runs`` - one row per scoring run (the dry run included).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.common.config import get_config


class ValueBase(DeclarativeBase):
    pass


class ValueTickerFileRow(ValueBase):
    __tablename__ = "value_ticker_files"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime)
    as_of: Mapped[date] = mapped_column(Date)
    universe: Mapped[str] = mapped_column(String(16))  # trading | evidence | lookup
    fingerprint_key: Mapped[str] = mapped_column(String(16))
    fingerprint_json: Mapped[str] = mapped_column(Text)
    ruleset_version: Mapped[str] = mapped_column(String(32))
    ruleset_hash: Mapped[str] = mapped_column(String(12))
    company_class: Mapped[str] = mapped_column(String(16))
    data_quality: Mapped[str] = mapped_column(String(16))
    health: Mapped[str] = mapped_column(String(16))
    verdict_deep: Mapped[str] = mapped_column(String(16))
    verdict_growth: Mapped[str] = mapped_column(String(16))
    filed_list: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fair_value_deep: Mapped[float | None] = mapped_column(Float, nullable=True)
    fair_value_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    mos_deep: Mapped[float | None] = mapped_column(Float, nullable=True)
    mos_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_deep: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text)
    scorecard_json: Mapped[str] = mapped_column(Text)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ValueTickerHistoryRow(ValueBase):
    __tablename__ = "value_ticker_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16))
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    as_of: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(16))  # changed | session
    changed: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of what changed
    fingerprint_key: Mapped[str] = mapped_column(String(16))
    ruleset_version: Mapped[str] = mapped_column(String(32))
    summary_json: Mapped[str] = mapped_column(Text)
    scorecard_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # full on "changed"

    __table_args__ = (Index("ix_value_history_symbol_asof", "symbol", "as_of"),)


class ValueRunRow(ValueBase):
    __tablename__ = "value_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))  # dry_run | nightly | lookup
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    as_of: Mapped[date] = mapped_column(Date)
    ruleset_version: Mapped[str] = mapped_column(String(32))
    ruleset_hash: Mapped[str] = mapped_column(String(12))
    names: Mapped[int] = mapped_column(Integer, default=0)
    rs_cutoff_6m: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_url() -> str:
    """Absolute sqlite URL for the value database. Patched in tests."""
    return get_config().value_db_url_abs()


def get_value_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = _resolve_url()
        if url.startswith("sqlite:///"):
            Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True)

        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


def init_value_db() -> None:
    ValueBase.metadata.create_all(get_value_engine())


@contextmanager
def value_session() -> Iterator[Session]:
    get_value_engine()
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
```

- [x] **Step 4: Create `src/value/ticker_file.py`**

```python
"""The ticker file (spec §6.9): every name ever scored keeps Part 1, fresh on search.

``persist`` writes the latest row and, when anything that matters changed, an append-only
history row; names in the ranked universe also get one compact row per session. Nothing is
deleted. ``is_fresh`` compares a stored fingerprint with the current one.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import ValueTickerFileCfg
from src.value.schemas import LISTS, Fingerprint, ValueScorecard
from src.value.store import ValueTickerFileRow, ValueTickerHistoryRow


@dataclass(frozen=True, slots=True)
class WriteResult:
    changed: list[str]
    history_reason: str | None  # "changed" | "session" | None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def summary(
    card: ValueScorecard, ranks: dict[str, float | None], filed: str | None
) -> dict[str, Any]:
    """The compact record history rows keep every session, and the fields a change is read
    from."""
    gates = {c.id: c.state for c in [*card.data_quality_checks, *card.health_checks]}
    lists: dict[str, Any] = {}
    for name in LISTS:
        ev = card.lists.get(name)
        lists[name] = {
            "verdict": card.verdict_for(name),
            "fair_value": ev.fair_value if ev else None,
            "mos": ev.margin_of_safety if ev else None,
            "entry": ev.entry if ev else None,
            "timing": ev.timing if ev else None,
            "rank": ranks.get(name),
        }
    return {
        "as_of": card.as_of.isoformat(),
        "price": card.price,
        "data_quality": card.data_quality,
        "health": card.health,
        "not_applicable": card.not_applicable_reason,
        "gates": gates,
        "lists": lists,
        "filed_list": filed,
    }


def _band(mos: float | None, width: float) -> int | None:
    return None if mos is None else math.floor(mos * 100.0 / width)


def what_changed(
    prev: dict[str, Any] | None, new: dict[str, Any], cfg: ValueTickerFileCfg
) -> list[str]:
    """Spec §6.9: the verdict, fair value (by more than ``fair_value_change_pct``), the margin
    of safety's band, or any gate result."""
    if prev is None:
        return ["new"]
    out: list[str] = []
    for key in ("data_quality", "health", "not_applicable"):
        if prev.get(key) != new.get(key):
            out.append(key)
    old_gates, new_gates = prev.get("gates", {}), new.get("gates", {})
    for gate in sorted(set(old_gates) | set(new_gates)):
        if old_gates.get(gate) != new_gates.get(gate):
            out.append(f"gate:{gate}")
    for name in LISTS:
        a, b = prev["lists"].get(name, {}), new["lists"].get(name, {})
        for key in ("verdict", "entry", "timing"):
            if a.get(key) != b.get(key):
                out.append(f"{name}.{key}")
        fa, fb = a.get("fair_value"), b.get("fair_value")
        if (fa is None) != (fb is None) or (
            fa and fb and abs(fb - fa) / abs(fa) * 100.0 > cfg.fair_value_change_pct
        ):
            out.append(f"{name}.fair_value")
        if _band(a.get("mos"), cfg.mos_band_pts) != _band(b.get("mos"), cfg.mos_band_pts):
            out.append(f"{name}.mos_band")
    return out


def persist(
    session: Session,
    card: ValueScorecard,
    *,
    universe: str,
    ranks: dict[str, float | None],
    filed: str | None,
    cfg: ValueTickerFileCfg,
    session_row: bool,
) -> WriteResult:
    """Upsert the latest row; append history when something changed, else (when
    *session_row*) one compact row per as-of date."""
    now = _now()
    new = summary(card, ranks, filed)
    row = session.get(ValueTickerFileRow, card.symbol)
    prev = json.loads(row.summary_json) if row is not None else None
    changed = what_changed(prev, new, cfg)
    full = card.model_dump_json()
    deep, growth = card.lists.get("deep_value"), card.lists.get("quality_growth")
    values = dict(
        computed_at=now,
        as_of=card.as_of,
        universe=universe,
        fingerprint_key=card.fingerprint.key(),
        fingerprint_json=card.fingerprint.model_dump_json(),
        ruleset_version=card.ruleset_version,
        ruleset_hash=card.ruleset_hash,
        company_class=card.company_class,
        data_quality=card.data_quality,
        health=card.health,
        verdict_deep=card.verdict_for("deep_value"),
        verdict_growth=card.verdict_for("quality_growth"),
        filed_list=filed,
        fair_value_deep=deep.fair_value if deep else None,
        fair_value_growth=growth.fair_value if growth else None,
        mos_deep=deep.margin_of_safety if deep else None,
        mos_growth=growth.margin_of_safety if growth else None,
        rank_deep=ranks.get("deep_value"),
        rank_growth=ranks.get("quality_growth"),
        price=card.price,
        summary_json=json.dumps(new, sort_keys=True),
        scorecard_json=full,
    )
    if row is None:
        session.add(ValueTickerFileRow(symbol=card.symbol, **values))
    else:
        for key, value in values.items():
            setattr(row, key, value)

    reason: str | None = None
    if changed:
        reason = "changed"
    elif session_row:
        seen = session.execute(
            select(ValueTickerHistoryRow.id).where(
                ValueTickerHistoryRow.symbol == card.symbol,
                ValueTickerHistoryRow.as_of == card.as_of,
            )
        ).first()
        reason = None if seen else "session"
    if reason is not None:
        session.add(
            ValueTickerHistoryRow(
                symbol=card.symbol,
                recorded_at=now,
                as_of=card.as_of,
                reason=reason,
                changed=json.dumps(changed),
                fingerprint_key=card.fingerprint.key(),
                ruleset_version=card.ruleset_version,
                summary_json=json.dumps(new, sort_keys=True),
                scorecard_json=full if reason == "changed" else None,
            )
        )
    return WriteResult(changed=changed, history_reason=reason)


def is_fresh(stored: Fingerprint | None, current: Fingerprint) -> bool:
    """Equal fingerprints mean the stored file stands; anything else recomputes (spec §6.9)."""
    return stored is not None and stored.key() == current.key()


def stored_fingerprint(session: Session, symbol: str) -> Fingerprint | None:
    row = session.get(ValueTickerFileRow, symbol)
    return None if row is None else Fingerprint.model_validate_json(row.fingerprint_json)
```

- [x] **Step 5: Run the tests** — 6 passed.

- [x] **Step 6: Gates** — `ruff check`, `ruff format --check`, `mypy` on `src/value/store.py
  src/value/ticker_file.py tests/test_value_store.py`.

- [x] **Step 7: Commit**

  ```bash
  git add src/value/store.py src/value/ticker_file.py tests/test_value_store.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): value.db with the ticker file's latest rows, append-only history and runs"
  ```

---

### Task 12: The pass funnel and the value fence

**Files:** Create `src/value/funnel.py`, `tests/test_value_funnel.py`, `tests/test_value_fence.py`

**Interfaces:**
- Consumes: `ValueScorecard`, `Check`, `LISTS`; `imported_modules`, `_reaches`
  (`tests/test_spreads_fence.py`).
- Produces: `GateTally`, `ListFunnel`, `Funnel`; `build_funnel(cards) -> Funnel`;
  `render_funnel(funnel, title) -> str`; `render_name(card) -> str`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_funnel.py`

```python
"""The dry run's pass funnel (value book spec §17)."""

from __future__ import annotations

from datetime import timedelta

from src.common.config import get_config
from src.value.funnel import build_funnel, render_funnel, render_name
from src.value.scorecard import build_scorecard
from tests.value_fixtures import AS_OF, financials, inputs

CFG = get_config().value


def _cards():
    return [
        build_scorecard(inputs(symbol="READY", close=30.0), CFG),
        build_scorecard(
            inputs(symbol="WATCH", close=30.0, next_earnings=AS_OF + timedelta(days=3)), CFG
        ),
        build_scorecard(inputs(symbol="DEAR", close=60.0), CFG),
        build_scorecard(
            inputs(symbol="DILUTE", fin=financials(shares_diluted=[110, 104, 98, 92, 86])), CFG
        ),
        build_scorecard(inputs(symbol="ETF", is_etf=True), CFG),
        build_scorecard(inputs(symbol="BAD", yf_market_cap=1.0), CFG),
        build_scorecard(inputs(symbol="REIT", industry="Retail REITs"), CFG),
    ]


def test_the_funnel_counts_every_step() -> None:
    f = build_funnel(_cards())
    assert (f.names, f.etf, f.data_quality_pass) == (7, 1, 5)
    assert f.data_quality["dq.market_cap"].unknown == 1
    assert dict(f.not_applicable) == {"REIT: FFO is not reliably tagged": 1}
    assert dict(f.health_states) == {"pass": 3, "fail": 1}
    assert f.health["operating"]["health.dilution"].failed == 1
    deep = f.lists["deep_value"]
    assert (deep.scored, deep.entry_pass, deep.fair_value, deep.mos_pass, deep.timing_pass) == (
        3,
        3,
        3,
        2,
        1,
    )
    assert dict(deep.verdicts) == {"READY": 1, "WATCH": 1, "WAIT": 1, "NO": 1}
    assert f.lists["quality_growth"].mos_pass == 3  # the growth ceiling (78.18) is above 60


def test_the_rendered_funnel_and_name_carry_the_numbers() -> None:
    cards = _cards()
    text = render_funnel(build_funnel(cards), "Test")
    assert "== Test: 7 names ==" in text and "health.dilution" in text
    detail = render_name(cards[0])
    assert detail.startswith("## READY  class=operating  price=30.00")
    assert "[deep_value] READY: fair value 46.85" in detail
    assert "realised FCF/share CAGR 14.7%" in detail
```

  and `tests/test_value_fence.py` (spec §16; it also covers what Part 1 added outside
  `src/value/`):

```python
"""The value fence (value book spec §16): src/value/ is deterministic and its own system.

Imports are parsed with ``ast`` (tests/test_spreads_fence.py's parser), so ``from src import x``,
relative imports and ``importlib`` count.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_spreads_fence import _reaches, imported_modules

ROOT = Path(__file__).resolve().parents[1]
VALUE = sorted((ROOT / "src" / "value").rglob("*.py"))
# The pure modules: no I/O, so the API may compute a ticker file during a request (spec §6.9).
PURE = (
    "schemas",
    "metrics",
    "scores",
    "gates",
    "valuation",
    "timing",
    "scorecard",
    "rank",
    "funnel",
    "ruleset",
)

FORBIDDEN_FOR_VALUE = (
    "src.claude",
    "src.news",
    "src.value_ai",
    "src.spreads",
    "src.spreads_ai",
    "src.notify",
    "src.api",
    "src.engine",
    "src.execution",
    "src.strategies",
    "src.orchestrator",
    "src.monitor",
    "src.ledger",
    "src.reporting",
    "src.analytics.sentiment",
    "src.analytics.sector_context",
    "src.analytics.market_conditions",
)
RESEARCH_ALLOWED = ("src.research.ingest.concepts", "src.research.schemas")
ENRICHMENT = (
    "src.claude",
    "src.news",
    "src.value_ai",
    "src.spreads_ai",
    "src.analytics.sentiment",
    "src.analytics.sector_context",
    "src.analytics.market_conditions",
)


def test_the_value_package_exists() -> None:
    assert len(VALUE) >= 12, "the fence must cover the value package"


def test_value_imports_no_enrichment_and_no_other_system() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} -> {m}"
        for p in VALUE
        for m in FORBIDDEN_FOR_VALUE
        if _reaches(imported_modules(p), m)
    ]
    assert offenders == []


def test_value_reads_research_only_through_concepts_and_schemas() -> None:
    offenders = []
    for p in VALUE:
        for m in imported_modules(p):
            if (m == "src.research" or m.startswith("src.research.")) and not any(
                m == ok or m.startswith(ok + ".") for ok in RESEARCH_ALLOWED
            ):
                offenders.append(f"{p.relative_to(ROOT)} -> {m}")
    assert offenders == []


def test_the_pure_modules_do_no_io() -> None:
    io_modules = (
        "sqlalchemy",
        "httpx",
        "requests",
        "yfinance",
        "src.data",
        "src.storage",
        "src.common.value_inputs",
        "src.value.store",
        "src.value.ticker_file",
    )
    offenders = []
    for name in PURE:
        p = ROOT / "src" / "value" / f"{name}.py"
        mods = imported_modules(p)
        offenders += [f"{name} -> {m}" for m in io_modules if _reaches(mods, m)]
        tree = ast.parse(p.read_text(encoding="utf-8"))
        offenders += [
            f"{name}:{n.lineno} open()"
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"
        ]
    assert offenders == []


def test_the_input_loader_imports_no_enrichment_and_no_value_code() -> None:
    for rel in (
        "src/common/value_inputs.py",
        "src/common/value_types.py",
        "src/common/value_universe.py",
    ):
        mods = imported_modules(ROOT / rel)
        bad = [m for m in (*ENRICHMENT, "src.value") if _reaches(mods, m)]
        assert bad == [], rel


def test_value_types_is_plain_pydantic() -> None:
    mods = imported_modules(ROOT / "src" / "common" / "value_types.py")
    assert {m.split(".")[0] for m in mods} <= {"__future__", "datetime", "typing", "pydantic"}


def test_value_opens_no_sec_client() -> None:
    """The research worker owns every SEC fetch (spec §6.9): src/value reaches no data provider
    and no HTTP client."""
    offenders = [
        f"{p.relative_to(ROOT)} -> {m}"
        for p in VALUE
        for m in ("src.data", "httpx", "requests")
        if _reaches(imported_modules(p), m)
    ]
    assert offenders == []


def test_the_trading_path_never_imports_the_value_book() -> None:
    offenders = [
        f"{p.relative_to(ROOT)}"
        for pkg in (
            "engine",
            "execution",
            "strategies",
            "orchestrator",
            "monitor",
            "notify",
            "spreads",
            "news",
            "claude",
        )
        for p in sorted((ROOT / "src" / pkg).rglob("*.py"))
        if _reaches(imported_modules(p), "src.value")
    ]
    assert offenders == []


def test_only_src_value_constructs_value_rows() -> None:
    rows = ("ValueTickerFileRow(", "ValueTickerHistoryRow(", "ValueRunRow(")
    offenders = []
    for p in (ROOT / "src").rglob("*.py"):
        if (ROOT / "src" / "value") in p.parents:
            continue
        text = p.read_text(encoding="utf-8")
        offenders += [f"{p.relative_to(ROOT)}: {r[:-1]}" for r in rows if r in text]
    assert offenders == []


def test_the_value_scorecard_loads_no_wheel_layer_even_transitively() -> None:
    probe = (
        "import json, sys\n"
        "import src.value.scorecard, src.value.store, src.value.ticker_file, src.value.funnel\n"
        "import src.common.value_inputs, src.common.value_universe\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('src.'))))\n"
    )
    env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
    out = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    )
    loaded = json.loads(out.stdout)
    bad = [
        m
        for m in loaded
        for f in (
            *FORBIDDEN_FOR_VALUE,
            "src.research.store.session",
            "src.research.ingest.fundamentals",
        )
        if m == f or m.startswith(f + ".")
    ]
    assert bad == []
```

- [x] **Step 2: Run them to see them fail** — the funnel tests fail with `ModuleNotFoundError: No
  module named 'src.value.funnel'`; of the fence tests only `test_the_pure_modules_do_no_io` and
  `test_the_value_scorecard_loads_no_wheel_layer_even_transitively` fail (both read
  `src/value/funnel.py`). Every other fence test passes already, because Tasks 1–11 were written
  inside the fence: record that in the Progress log.

- [x] **Step 3: Create `src/value/funnel.py`**

```python
"""The calibration dry run's pass funnel (spec §17). Pure: no I/O.

How many names fall at each step: data quality, not applicable, each health gate, each list's
entry rule, fair value, margin of safety and timing, and the verdicts that come out.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from src.value.schemas import LISTS, Check, ValueScorecard


class GateTally(BaseModel):
    passed: int = 0
    failed: int = 0
    unknown: int = 0
    not_applicable: int = 0

    def add(self, check: Check) -> None:
        if check.state == "pass":
            self.passed += 1
        elif check.state == "fail":
            self.failed += 1
        elif check.state == "unknown":
            self.unknown += 1
        else:
            self.not_applicable += 1


class ListFunnel(BaseModel):
    scored: int = 0  # healthy names evaluated on the list
    entry: dict[str, GateTally] = Field(default_factory=dict)
    entry_pass: int = 0
    fair_value: int = 0
    mos_pass: int = 0
    timing: dict[str, GateTally] = Field(default_factory=dict)
    timing_pass: int = 0
    verdicts: Counter[str] = Field(default_factory=Counter)


class Funnel(BaseModel):
    names: int = 0
    classes: Counter[str] = Field(default_factory=Counter)
    etf: int = 0
    data_quality_pass: int = 0
    data_quality: dict[str, GateTally] = Field(default_factory=dict)
    not_applicable: Counter[str] = Field(default_factory=Counter)
    health: dict[str, dict[str, GateTally]] = Field(default_factory=dict)  # class -> gate -> tally
    health_states: Counter[str] = Field(default_factory=Counter)
    lists: dict[str, ListFunnel] = Field(default_factory=dict)


def build_funnel(cards: list[ValueScorecard]) -> Funnel:
    f = Funnel(names=len(cards), lists={name: ListFunnel() for name in LISTS})
    for card in cards:
        f.classes[card.company_class] += 1
        if card.company_class == "etf":
            f.etf += 1
            continue
        for c in card.data_quality_checks:
            f.data_quality.setdefault(c.id, GateTally()).add(c)
        if card.data_quality != "pass":
            continue
        f.data_quality_pass += 1
        if card.not_applicable_reason is not None:
            f.not_applicable[card.not_applicable_reason] += 1
            continue
        group = "bank/insurer" if card.company_class in ("bank", "insurer") else card.company_class
        gates = f.health.setdefault(group, {})
        for c in card.health_checks:
            gates.setdefault(c.id, GateTally()).add(c)
        f.health_states[card.health] += 1
        for name, ev in card.lists.items():
            lf = f.lists[name]
            lf.verdicts[ev.verdict] += 1
            if card.health != "pass":
                continue
            lf.scored += 1
            for c in ev.entry_checks:
                lf.entry.setdefault(c.id, GateTally()).add(c)
            if ev.entry != "pass":
                continue
            lf.entry_pass += 1
            if ev.fair_value is None:
                continue
            lf.fair_value += 1
            if ev.verdict == "WAIT":
                continue
            lf.mos_pass += 1
            for c in ev.timing_checks:
                lf.timing.setdefault(c.id, GateTally()).add(c)
            if ev.timing == "pass":
                lf.timing_pass += 1
    return f


def _tally(t: GateTally) -> str:
    return f"pass {t.passed:>4}  fail {t.failed:>4}  unknown {t.unknown:>4}"


def render_funnel(f: Funnel, title: str) -> str:
    lines = [f"== {title}: {f.names} names ==", f"classes: {dict(f.classes)}"]
    lines.append(f"ETFs (not applicable): {f.etf}")
    lines.append(f"data quality pass: {f.data_quality_pass}")
    for gate, t in sorted(f.data_quality.items()):
        lines.append(f"  {gate:<28} {_tally(t)}")
    lines.append(f"not applicable: {dict(f.not_applicable)}")
    lines.append(f"health: {dict(f.health_states)}")
    for group, gates in sorted(f.health.items()):
        lines.append(f"  [{group}]")
        for gate, t in sorted(gates.items()):
            lines.append(f"    {gate:<28} {_tally(t)}")
    for name, lf in f.lists.items():
        lines.append(f"-- {name} --")
        lines.append(f"  healthy and scored: {lf.scored}")
        for gate, t in sorted(lf.entry.items()):
            lines.append(f"    entry {gate:<22} {_tally(t)}")
        lines.append(f"  entry rule pass: {lf.entry_pass}")
        lines.append(f"  fair value present: {lf.fair_value}")
        lines.append(f"  margin of safety met: {lf.mos_pass}")
        for gate, t in sorted(lf.timing.items()):
            lines.append(f"    {gate:<28} {_tally(t)}")
        lines.append(f"  timing pass (READY): {lf.timing_pass}")
        lines.append(f"  verdicts: {dict(lf.verdicts)}")
    return "\n".join(lines)


def _num(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct else f"{v:,.2f}"


def render_name(card: ValueScorecard) -> str:
    """Every number for one name (spec §17: GOOGL, META, BAC and MU by name)."""
    lines = [
        f"## {card.symbol}  class={card.company_class}  price={_num(card.price)}  "
        f"data_quality={card.data_quality}  health={card.health}",
    ]
    if card.not_applicable_reason:
        lines.append(f"  not applicable: {card.not_applicable_reason}")
    for c in [*card.data_quality_checks, *card.health_checks]:
        lines.append(
            f"  {c.id:<28} {c.state:<8} actual={_num(c.actual)} bar={_num(c.threshold)} {c.detail}"
        )
    for k, v in card.metrics.items():
        lines.append(f"  {k:<28} {_num(v)}")
    lines.append(
        f"  realised FCF/share CAGR {_num(card.realised_fcf_ps_cagr, True)}; "
        f"price implies {_num(card.reverse_dcf_implied_growth, True)}/yr (reverse DCF)"
    )
    if card.adjustments:
        lines.append(f"  adjustments: {'; '.join(card.adjustments)}")
    for name, ev in card.lists.items():
        methods = ", ".join(f"{m.method}={_num(m.value)}({m.state})" for m in ev.methods)
        lines.append(
            f"  [{name}] {ev.verdict}: fair value {_num(ev.fair_value)} ({methods}); "
            f"MoS {_num(ev.margin_of_safety, True)} vs {ev.required_mos_pct:.0f}% required; "
            f"ceiling {_num(ev.entry_ceiling)}; entry {ev.entry}; timing {ev.timing}"
        )
        for c in [*ev.entry_checks, *ev.timing_checks]:
            lines.append(
                f"      {c.id:<26} {c.state:<8} actual={_num(c.actual)} bar={_num(c.threshold)} {c.detail}"
            )
        lines.append(f"      why: {'; '.join(ev.reasons)}")
    return "\n".join(lines)
```

- [x] **Step 4: Run the tests** — `.venv/bin/python -m pytest -q tests/test_value_funnel.py
  tests/test_value_fence.py tests/test_spreads_fence.py tests/test_regime_fence.py
  tests/test_news_fence.py tests/test_web_fence.py tests/test_eval_skills.py` → all pass
  (funnel 2, fence 10).

- [x] **Step 5: Gates** — `ruff check`, `ruff format --check`, `mypy` on `src/value/funnel.py
  tests/test_value_funnel.py tests/test_value_fence.py`.

- [x] **Step 6: Commit**

  ```bash
  git add src/value/funnel.py tests/test_value_funnel.py tests/test_value_fence.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): the dry run's pass funnel and the value fence tests"
  ```

---

### Task 13: The dry-run script

**Files:** Create `scripts/value_dry_run.py`, `tests/test_value_dry_run.py`; modify
`tests/value_fixtures.py` (append `companyfacts`)

**Interfaces:**
- Consumes: Tasks 3, 4, 9, 10, 11, 12; `drain_ingest_jobs`, `refresh_symbol_directory`,
  `init_research_db`, `research_session`; `read_only_session`, `earnings_between`.
- Produces: `python -m scripts.value_dry_run backfill [--env-file] [--universe-file]` and
  `run [--env-file] [--universe-file] [--as-of] [--names] [--limit] [--no-persist] [--out]
  [--report]`; module-level `NAMED = ("GOOGL", "META", "BAC", "MU")`, `main(argv)`, `backfill`,
  `run`, `_universe(path)`, `_earnings(as_of)`, `_persist(...)`, `_storage_lines()` (the test
  patches `_universe` and `_earnings`).

- [x] **Step 1: Append the payload builder to `tests/value_fixtures.py`**

```python
def companyfacts(table: dict[str, list[float | None]] | None = None) -> dict:
    """A companyfacts payload carrying *table* (default Steady Co) in dollars and shares, one
    10-K per fiscal year filed the next 10 February, under each line item's first concept."""
    from src.research.ingest.concepts import load_concept_map

    concept_map = load_concept_map()
    us_gaap: dict[str, dict] = {}
    for item, values in (table or STEADY).items():
        spec = concept_map[item]
        unit = spec.units[0]
        entries = []
        for i, v in enumerate(values):
            if v is None:
                continue
            end = YEAR_ENDS[i]
            entry = {
                "val": v * 1e6,
                "end": end.isoformat(),
                "filed": date(end.year + 1, 2, 10).isoformat(),
                "form": "10-K",
                "accn": f"0000000001-{(end.year + 1) % 100:02d}-000001",
                "fy": end.year,
                "fp": "FY",
            }
            if spec.kind == "duration":
                entry["start"] = date(end.year, 1, 1).isoformat()
            entries.append(entry)
        us_gaap[spec.concepts[0]] = {"units": {unit: entries}}
    return {"cik": 1, "entityName": "Steady Co", "facts": {"us-gaap": us_gaap, "dei": {}}}
```

- [x] **Step 2: Write the failing tests** — `tests/test_value_dry_run.py`

```python
"""scripts/value_dry_run.py end to end on temporary databases (value book spec §17).

Importing the script is safe: it has a ``__main__`` guard and starts nothing at import.
"""

from __future__ import annotations

import json
import py_compile
from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import src.common.value_inputs as vi
import src.common.value_universe as vu
import src.value.store as store
from scripts import value_dry_run
from src.common.value_types import MarketFacts
from src.research.store.models import Base, CompanyFactsRawRow, DailyBarRow, SymbolRow
from src.value.store import ValueRunRow, ValueTickerFileRow, value_session
from tests.value_fixtures import AS_OF, companyfacts, price


def test_the_script_compiles() -> None:
    py_compile.compile("scripts/value_dry_run.py", doraise=True)
    py_compile.compile("scripts/value_universe_snapshot.py", doraise=True)


@pytest.fixture()
def dbs(tmp_path, monkeypatch):
    research = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{research}")
    Base.metadata.create_all(engine)
    closes = price(30.0).closes
    days = pd.bdate_range(end=AS_OF, periods=len(closes)).date
    with Session(engine) as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001", name="Steady Co"))
        s.add(
            CompanyFactsRawRow(
                cik="0000000001",
                payload_json=json.dumps(companyfacts()),
                fetched_at=datetime(2026, 3, 30),
            )
        )
        for d, c in zip(days, closes, strict=True):
            s.add(
                DailyBarRow(
                    symbol="STDY", date=d, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=1e6
                )
            )
            s.add(
                DailyBarRow(
                    symbol="SPY", date=d, open=500, high=505, low=495, close=500.0, volume=1e8
                )
            )
        s.commit()
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(research))
    vi.reset_engine()
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    monkeypatch.setattr(
        vi, "fetch_market_facts", lambda symbol: MarketFacts(market_cap=3.0e9, next_earnings=None)
    )
    monkeypatch.setattr(vi, "load_regime", lambda: "normal")
    monkeypatch.setattr(
        vu,
        "build_value_universe",
        lambda cfg, universe: vu.ValueUniverse(
            trading=["STDY"],
            classification={"STDY": ("Information Technology", "Application Software")},
        ),
    )
    monkeypatch.setattr(value_dry_run, "_earnings", lambda as_of: {})
    monkeypatch.setattr(value_dry_run, "_universe", lambda path: {})
    yield
    vi.reset_engine()
    store.reset_engine()


def test_the_dry_run_scores_persists_and_prints_the_funnel(dbs, capsys, tmp_path) -> None:
    report = tmp_path / "report.txt"
    assert (
        value_dry_run.main(
            ["run", "--as-of", AS_OF.isoformat(), "--names", "STDY", "--report", str(report)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert report.read_text() == out
    assert "== Trading universe: 1 names ==" in out
    assert "## STDY  class=operating  price=30.00  data_quality=pass  health=pass" in out
    assert "timing.earnings" in out and "no earnings date" in out
    assert "run time:" in out
    with value_session() as s:
        row = s.get(ValueTickerFileRow, "STDY")
        assert row is not None and row.universe == "trading"
        assert row.verdict_deep == "WATCH"  # cheap enough; no earnings date is unknown timing
        run = s.query(ValueRunRow).one()
        assert (run.kind, run.names, run.ruleset_version) == ("dry_run", 1, "v0-dryrun")


def test_no_persist_leaves_value_db_alone(dbs, tmp_path) -> None:
    assert (
        value_dry_run.main(
            [
                "run",
                "--as-of",
                AS_OF.isoformat(),
                "--no-persist",
                "--out",
                str(tmp_path / "cards.json"),
            ]
        )
        == 0
    )
    assert not (tmp_path / "value.db").exists()
    cards = json.loads((tmp_path / "cards.json").read_text())
    assert [c["symbol"] for c in cards] == ["STDY"]
```

- [x] **Step 3: Run them to see them fail** — `ImportError: cannot import name 'value_dry_run'
  from 'scripts'`.

- [x] **Step 4: Create `scripts/value_dry_run.py`** (it has a `__main__` guard and starts nothing
  on import; check it with `py_compile`, never by running it against `data/` of the main
  checkout)

```python
"""The value book's calibration dry run (spec §17): score every name once and print the funnel.

    python -m scripts.value_dry_run backfill [--env-file PATH] [--universe-file PATH]
    python -m scripts.value_dry_run run [--env-file PATH] [--universe-file PATH]
        [--as-of YYYY-MM-DD] [--names GOOGL,META,BAC,MU] [--limit N] [--no-persist]
        [--out CARDS.json] [--report REPORT.txt]

``backfill`` queues and drains the research worker's own jobs (companyfacts and daily bars for
both value universes) in this process, writing research.db exactly as the worker would.
``run`` reads research.db read-only, fetches each name's yfinance market cap and next earnings
date, scores every name, ranks both lists, writes the ticker files to value.db (unless
``--no-persist``) and prints the pass funnel, the named names with every number, storage and
run time. No IBKR connection, no Telegram, no order path. Run it against copies of the
databases, never the live ones (the plan's Section D says how).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.common.value_universe import ValueUniverse
    from src.value.rank import RankEntry
    from src.value.schemas import ValueScorecard

NAMED = ("GOOGL", "META", "BAC", "MU")


def _load_env(path: str | None) -> None:
    """Before anything reads the config: the worktree has no .env of its own."""
    if path:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)


def _universe(path: str | None) -> dict[str, Any]:
    if path:
        import yaml

        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    from src.common.universe import effective_universe

    return effective_universe()


def backfill(args: argparse.Namespace) -> int:
    from src.common.config import get_config
    from src.common.value_universe import build_value_universe
    from src.research.ingest.materialize import drain_ingest_jobs
    from src.research.ingest.symbols import refresh_symbol_directory
    from src.research.ingest.value_universe import enqueue_value_universe
    from src.research.store.models import IngestJobRow, SymbolRow
    from src.research.store.session import init_research_db, research_session

    init_research_db()
    with research_session() as s:
        if s.query(SymbolRow).count() == 0:
            refresh_symbol_directory()
    names = build_value_universe(get_config().value, _universe(args.universe_file)).all_names()
    counts = enqueue_value_universe(names)
    print(f"queued {counts} for {len(names)} names", flush=True)
    started = time.monotonic()
    while True:
        with research_session() as s:
            pending = s.query(IngestJobRow).filter_by(status="pending").count()
        if pending == 0:
            break
        done = drain_ingest_jobs(max_jobs=25)
        print(
            f"{time.monotonic() - started:7.0f}s  drained {done:3d}  pending {pending}", flush=True
        )
    with research_session() as s:
        failed = [(j.symbol, j.kind) for j in s.query(IngestJobRow).filter_by(status="failed")]
    print(f"backfill finished in {time.monotonic() - started:.0f}s; {len(failed)} jobs failed")
    for symbol, kind in failed:
        print(f"  failed: {symbol} {kind}")
    return 0


def _earnings(as_of: date) -> dict[str, date]:
    """Next earnings dates from news.db (spec §6.6), the earliest on or after *as_of*."""
    import src.news.store.queries as queries
    from src.news.store.readonly import read_only_session

    out: dict[str, date] = {}
    with read_only_session() as s:
        if s is None:
            return out
        for e in queries.earnings_between(s, as_of, as_of + timedelta(days=180)):
            out.setdefault(e.symbol, e.report_date)
    return out


def run(args: argparse.Namespace) -> int:
    from src.common import value_inputs as vi
    from src.common import value_universe as vu
    from src.common.config import get_config
    from src.common.value_types import Classification, MarketFacts, ValueInputs
    from src.research.store.models import SymbolRow
    from src.value.funnel import build_funnel, render_funnel, render_name
    from src.value.rank import filed_lists, rank_list, rs_cutoff
    from src.value.scorecard import build_scorecard

    vcfg = get_config().value
    as_of = args.as_of or date.today()
    t0 = time.monotonic()
    universe = vu.build_value_universe(vcfg, _universe(args.universe_file))
    names = universe.all_names()
    if args.limit:
        keep = set(names[: args.limit]) | set(NAMED)
        names = [n for n in names if n in keep]
    regime = vi.load_regime()
    earnings = _earnings(as_of)
    to_fetch = [n for n in names if n not in universe.etfs]
    with ThreadPoolExecutor(max_workers=4) as pool:
        facts = dict(zip(to_fetch, pool.map(vi.fetch_market_facts, to_fetch), strict=True))
    t_fetch = time.monotonic()

    inputs: list[ValueInputs] = []
    with vi.research_read() as s:
        if s is None:
            print("research.db not found", file=sys.stderr)
            return 1
        spy = vi.read_bars(s, "SPY", as_of)
        for symbol in names:
            cik, payload = vi.read_payload(s, symbol)
            row = s.get(SymbolRow, symbol)
            mf = facts.get(symbol, MarketFacts())
            sector, industry = universe.classification.get(symbol, (None, None))
            classification = Classification(
                sector=sector or mf.sector,
                industry=industry or mf.industry,
                source="snapshot" if industry else ("yfinance" if mf.industry else "none"),
                is_etf=symbol in universe.etfs
                or mf.quote_type == "ETF"
                or bool(row is not None and row.is_etf),
            )
            fin = (
                None
                if payload is None
                else vi.build_value_financials(
                    payload, as_of=as_of, stale_item_days=vcfg.rules.data_quality.stale_item_days
                )
            )
            inputs.append(
                ValueInputs(
                    symbol=symbol,
                    cik=cik,
                    as_of=as_of,
                    financials=fin,
                    price=vi.build_price_series(vi.read_bars(s, symbol, as_of), spy),
                    classification=classification,
                    yf_market_cap=mf.market_cap,
                    next_earnings=earnings.get(symbol, mf.next_earnings),
                    regime=regime,
                )
            )
    cutoff = rs_cutoff([i.price for i in inputs], vcfg.rules.timing.rs_bottom_pct)
    inputs = [i.model_copy(update={"rs_cutoff_6m": cutoff}) for i in inputs]
    t_load = time.monotonic()

    cards = [build_scorecard(i, vcfg) for i in inputs]
    deep, growth = rank_list(cards, "deep_value"), rank_list(cards, "quality_growth")
    filed = filed_lists(cards, deep, growth)
    t_score = time.monotonic()
    if not args.no_persist:
        _persist(cards, universe, deep, growth, dict(filed), as_of, cutoff, t0)
    t_persist = time.monotonic()

    trading = set(universe.trading)
    lines = [
        render_funnel(build_funnel([c for c in cards if c.symbol in trading]), "Trading universe"),
        "",
        render_funnel(build_funnel(cards), "Evidence + trading universe"),
        "",
    ]
    for symbol in args.names.split(",") if args.names else NAMED:
        card = next((c for c in cards if c.symbol == symbol.strip().upper()), None)
        lines += [render_name(card) if card else f"## {symbol}: not scored", ""]
    no_cap = sum(1 for i in inputs if not i.classification.is_etf and i.yf_market_cap is None)
    lines.append(
        f"regime {regime}; relative-strength line {cutoff}; no yfinance market cap: {no_cap}"
    )
    lines += _storage_lines()
    lines.append(
        f"run time: market facts {t_fetch - t0:.0f}s, load {t_load - t_fetch:.0f}s, "
        f"score+rank {t_score - t_load:.1f}s, persist {t_persist - t_score:.1f}s, "
        f"total {t_persist - t0:.0f}s for {len(cards)} names"
    )
    text = "\n".join(lines)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    if args.out:
        Path(args.out).write_text(
            json.dumps([c.model_dump(mode="json") for c in cards]), encoding="utf-8"
        )
    return 0


def _persist(
    cards: list[ValueScorecard],
    universe: ValueUniverse,
    deep: dict[str, RankEntry],
    growth: dict[str, RankEntry],
    filed: dict[str, str],
    as_of: date,
    cutoff: float | None,
    t0: float,
) -> None:
    from src.common.config import get_config
    from src.value.funnel import build_funnel
    from src.value.ruleset import ruleset_id
    from src.value.store import ValueRunRow, init_value_db, value_session
    from src.value.ticker_file import persist

    vcfg = get_config().value
    version, digest = ruleset_id(vcfg)
    now = datetime.now(UTC).replace(tzinfo=None)
    init_value_db()
    with value_session() as s:
        for card in cards:
            d, g = deep.get(card.symbol), growth.get(card.symbol)
            persist(
                s,
                card,
                universe=universe.tag(card.symbol),
                ranks={
                    "deep_value": d.score if d else None,
                    "quality_growth": g.score if g else None,
                },
                filed=filed.get(card.symbol),
                cfg=vcfg.ticker_file,
                session_row=True,
            )
        s.add(
            ValueRunRow(
                kind="dry_run",
                started_at=now - timedelta(seconds=time.monotonic() - t0),
                finished_at=now,
                as_of=as_of,
                ruleset_version=version,
                ruleset_hash=digest,
                names=len(cards),
                rs_cutoff_6m=cutoff,
                summary_json=build_funnel(cards).model_dump_json(),
            )
        )


def _storage_lines() -> list[str]:
    from sqlalchemy import func

    from src.common.config import get_config
    from src.common.value_inputs import research_read
    from src.research.store.models import CompanyFactsRawRow

    cfg = get_config()
    out: list[str] = []
    with research_read() as s:
        if s is not None:
            n, total = s.query(
                func.count(CompanyFactsRawRow.cik),
                func.sum(func.length(CompanyFactsRawRow.payload_json)),
            ).one()
            avg = (total or 0) / n if n else 0
            out.append(
                f"raw companyfacts: {n} payloads, {(total or 0) / 1e6:,.0f} MB, "
                f"{avg / 1e6:.1f} MB average"
            )
    for label, url in (
        ("research.db", cfg.research_db_url_abs()),
        ("value.db", cfg.value_db_url_abs()),
    ):
        path = url[len("sqlite:///") :]
        if os.path.exists(path):
            out.append(f"{label}: {os.path.getsize(path) / 1e6:,.0f} MB")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Value book calibration dry run (spec §17)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("backfill", "run"):
        p = sub.add_parser(name)
        p.add_argument("--env-file", default=None)
        p.add_argument("--universe-file", default=None)
    r = sub.choices["run"]
    r.add_argument("--as-of", type=date.fromisoformat, default=None)
    r.add_argument("--names", default=None)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--no-persist", action="store_true")
    r.add_argument("--out", default=None)
    r.add_argument("--report", default=None)
    args = parser.parse_args(argv)
    _load_env(args.env_file)
    from src.common.logging import setup_logging

    setup_logging()
    return backfill(args) if args.command == "backfill" else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 5: Run the tests** — `.venv/bin/python -m pytest -q tests/test_value_dry_run.py` →
  3 passed; `.venv/bin/python -m py_compile scripts/value_dry_run.py` → silent.

- [x] **Step 6: Gates** — `ruff check`, `ruff format --check` on `scripts/value_dry_run.py
  tests/test_value_dry_run.py tests/value_fixtures.py`; `.venv/bin/mypy src` (the script is
  outside `src`; `mypy scripts/value_dry_run.py` must also print `Success`).

- [x] **Step 7: Commit**

  ```bash
  git add scripts/value_dry_run.py tests/test_value_dry_run.py tests/value_fixtures.py docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): the calibration dry-run script (backfill and run)"
  ```

---

### Task 14: Docs

**Files:** Modify `ARCHITECTURE.md`, `SETUP.md`, `STATUS.md`, `CLAUDE.md` (root). No code.
`README.md`, `docs/web/commands.md`, `docs/web/api.md` stay unchanged (no Telegram command, no
top-level directory, no command kind, no route).

Each step names its anchor; insert the text given, adjusting only line wraps.

- [x] **Step 1: `ARCHITECTURE.md`, `### \`config/\``** (line ~561). In the "Private vs.
  committed" paragraph, "`universe.yaml`, `spreads.yaml` and `news.yaml`" becomes
  "`universe.yaml`, `spreads.yaml`, `news.yaml` and `value.yaml`". Add three rows to the file
  table:

  ```markdown
  | `value.yaml` | The value book (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`). The `rules:` block (data quality, the classification lists, the health thresholds for operating companies, cyclicals, banks and insurers, valuation rates, the quality-growth entry rule, the margin of safety by regime, timing) is hashed into the ruleset fingerprint beside `ruleset_version`; changing a rule after the freeze is a version bump. Also the universe snapshots, the ticker-file history bands and `research_sweep.enabled` (the research worker's nightly value sweep, off until Part 2). Every model forbids unknown keys. |
  | `value_universe.csv` / `value_evidence_universe.csv` | Committed snapshots of the S&P 100 (the value book's trading universe, with `universe.yaml`'s `would_own` + `watchlist`) and the S&P 500 (its evidence universe): symbol, name, GICS sector and sub-industry, CIK, with the as-of date on line 1. Rebuilt by `python -m scripts.value_universe_snapshot`. |
  ```

  and in the `research_concepts.yaml` description (the paragraph ending "…where concept
  resolution breaks)", line ~1005) add: "Since the value book (2026-10-29) it also maps the 23
  line items the value scorecard reads (SBC, interest, D&A, receivables, PP&E, SG&A, retained
  earnings, pre-tax income, tax, current debt, commercial paper, short-term borrowings,
  marketable securities, goodwill, intangibles, preferred equity, net income to common, net
  charge-offs, loans, CET1, earned premiums, total benefits/losses/expenses, shares
  outstanding)."

- [x] **Step 2: `ARCHITECTURE.md`, a new folder-guide section** immediately before `### \`src/ops/\``:

  ```markdown
  ### `src/value/` — The value book (deterministic tier, its own database)

  The value book (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`) scores healthy
  companies against what they are worth. **Part 1 (2026-10-29) is the scorecard only: nothing in
  it can place, size or gate an order.** `src/value/` is deterministic, imports no enrichment and
  no other system, reads `src.research` only through `ingest/concepts.py` and `schemas.py`, and is
  the only writer of `data/value.db` (its own `ValueBase`). Enforced by `tests/test_value_fence.py`.

  | File | What it does |
  |---|---|
  | `scorecard.py` | `build_scorecard(ValueInputs, ValueCfg) -> ValueScorecard`: a pure function (no I/O) — ETF → data quality → REIT / pre-profit → health → each list's fair value, margin of safety, entry ceiling, timing and Python's baseline verdict (READY / WATCH / WAIT / NO / UNKNOWN / NOT_APPLICABLE). |
  | `schemas.py` | `Check` (one gate: actual, bar, state), `combine`, `MethodValue`, `ListEvaluation`, `Fingerprint`, `ValueScorecard`. Pydantic only. |
  | `metrics.py` | Per-year figures (`Year`), split normalisation of share counts, `cagr`, medians, standard deviations, ROIC. |
  | `scores.py` | Piotroski F-score, Altman Z, Beneish M, each reporting what it could not compute. |
  | `gates.py` | Classification (operating, cyclical, bank, insurer, REIT, ETF), the data-quality gate (UNKNOWN, never FAIL), the operating/cyclical health set and the bank/insurer set. |
  | `valuation.py` | The fading DCF, the reverse DCF, methods A (earnings power), B (haircut DCF), C (absent until point-in-time prices exist), D (growth DCF) and justified P/TBV; fair value = median of the list's methods. |
  | `timing.py` | The earnings window, deep value's strict timing, quality growth's soft timing. |
  | `rank.py` | The cross-sectional rank score per list, the filed list, the run's relative-strength line. |
  | `store.py` | `value.db`: `value_ticker_files` (latest), `value_ticker_history` (append-only), `value_runs`. |
  | `ticker_file.py` | Writes the latest row and history (a full row on any verdict, fair value, margin band or gate change; a compact row once a session); `is_fresh` compares fingerprints. |
  | `funnel.py` | The calibration dry run's pass funnel and per-name detail. |
  | `ruleset.py` | The ruleset fingerprint: `ruleset_version` + a hash of the `rules:` block; `FROZEN` pins a frozen version's hash. |

  Inputs come from `src/common/value_inputs.py` (read-only) in the plain shapes of
  `src/common/value_types.py`; the universes from `src/common/value_universe.py`. The research
  worker owns every SEC and price fetch for it.
  ```

- [x] **Step 3: `ARCHITECTURE.md`, `### \`src/common/\``.** In the `config.py` row, "the six
  private files" becomes "the seven private files", and append "**Value book:** `ValueCfg` and
  its sub-models from `config/value.yaml`, `Config.value_db_url_abs()`." Add rows:

  ```markdown
  | `value_types.py` | The value book's plain input shapes (`ValueFinancials`, `PriceSeries`, `Classification`, `MarketFacts`, `ValueInputs`). Imports only pydantic, so the scorecard, the loader and (Part 6) the API share them. |
  | `value_inputs.py` | The value book's one read-only input loader: research.db opened `mode=ro` (the raw companyfacts payload through `select_periods(as_of=)` / `select_ttm`, daily bars), the regime through `load_regime_state`, fixed-window technicals through `src/analytics/technicals.py`, and `fetch_market_facts` (yfinance market cap, industry, next earnings, through `src/data`). Imports no enrichment and no `src.value`. |
  | `value_universe.py` | The value book's trading universe (`would_own` + `watchlist` + the S&P 100 snapshot) and evidence universe (the S&P 500 snapshot), share-class aliases mapped to one ticker. |
  ```

- [x] **Step 4: `ARCHITECTURE.md`, `### \`src/research/\``.** In the `ingest/concepts.py` row,
  append: "`select_periods(..., as_of=)` keeps only facts filed on or before `as_of` (point in
  time, value book §6.2); `select_ttm` gives trailing twelve months as fiscal year + this
  year-to-date − last year's (10-Q cash flows are year-to-date)." After the module table add the
  rows (or a sentence if the section has no table row for them):

  ```markdown
  | `ingest/value_universe.py` | `enqueue_value_universe`: queues `fundamentals` (raw payload missing or a day old) and `prices` (fewer than 260 bars or 4+ days stale) for both value-book universes. Scheduled as the `value_sweep` cron job only when `config/value.yaml → research_sweep.enabled`. |
  ```

  and in the `ingest/materialize.py` description note that `drain_ingest_jobs` runs two job
  kinds, `fundamentals` and `prices`.

- [x] **Step 5: `ARCHITECTURE.md`, `### \`scripts/\`` table.** Add:

  ```markdown
  | `value_dry_run.py` | `python -m scripts.value_dry_run backfill\|run [...]` | The value book's calibration dry run (spec §17). `backfill` drains the research worker's own jobs for both universes in-process; `run` scores every name read-only, ranks both lists, writes the ticker files to `value.db` and prints the pass funnel, GOOGL/META/BAC/MU with every number, storage and run time. No IBKR, no Telegram. Run on database copies (`SETUP.md` §19). |
  | `value_universe_snapshot.py` | `python -m scripts.value_universe_snapshot` | Rebuilds `config/value_universe.csv` (S&P 100) and `config/value_evidence_universe.csv` (S&P 500) from Wikipedia's MediaWiki API. Review the diff before committing. |
  ```

- [x] **Step 6: `ARCHITECTURE.md`, `## Key invariants`.** Add a numbered item after the last:
  "**The value fence.** `src/value/` is deterministic: it imports no enrichment, no other system
  and no trading-path module, nothing on the trading path imports it, and it is the only writer
  of `data/value.db`. Its scorecard is a pure function. Part 1 places no order. Enforced by
  `tests/test_value_fence.py`."

- [x] **Step 7: `SETUP.md`.** In §2b, the template list gains "`value.yaml` (the value book's
  scorecard, Part 1 — §19)" and the `for f in …` line gains `value`. Insert a new section
  immediately before `## Troubleshooting`:

  ```markdown
  ## 19. The value book, Part 1: the scorecard and the calibration dry run

  The value book scores healthy companies against what they are worth
  (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`). Part 1 is the scorecard and
  a one-off **calibration dry run**: it places no order, sends no message and runs no daemon.

  1. `cp config/examples/value.yaml config/value.yaml` (git-ignored; every key has a code default).
  2. The research worker can refresh the value universes nightly (`research_sweep.enabled`), but
     Part 1 ships it **off**: the dry run backfills a database copy itself.
  3. The dry run (normally run for you by the plan's orchestrator, on copies, from the branch's
     worktree): `python -m scripts.value_dry_run backfill --env-file .env` then
     `python -m scripts.value_dry_run run --report value_dry_run.txt`. It prints how many names
     fall at each gate per list, GOOGL, META, BAC and MU with every number, the raw companyfacts
     storage and the run time.
  4. You read the funnel and settle the thresholds; then `ruleset_version` is frozen at `v1` and
     every later rule change is a version bump with a written reason.

  ### Scripts

  | Script | What it does |
  |---|---|
  | `python -m scripts.value_dry_run backfill [--env-file PATH] [--universe-file PATH]` | Queues and drains companyfacts and daily-bar jobs for both value universes (~520 names; a few GB of raw payloads the first time). |
  | `python -m scripts.value_dry_run run [--as-of DATE] [--names A,B] [--limit N] [--no-persist] [--out cards.json] [--report report.txt]` | Scores every name, ranks both lists, writes `data/value.db`, prints the funnel. |
  | `python -m scripts.value_universe_snapshot` | Rebuilds the two committed universe CSVs from Wikipedia. |
  ```

- [x] **Step 8: `STATUS.md`.** Insert immediately before `## Built (2026-10-28 — web overhaul
  Part 3…` (line ~349):

  ```markdown
  ## Built (2026-10-29 — value book Part 1: the scorecard and the calibration dry run)

  Plan: `docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md`; spec:
  `docs/superpowers/specs/2026-10-28-value-swing-book-design.md`. Deterministic only: no order, no
  Claude, no Telegram, no web, no daemon.

  - `src/value/`: the pure scorecard (data quality, the operating/cyclical and bank/insurer health
    sets, methods A/B/D and justified P/TBV, the two lists' entry rules, timing, Python's baseline
    verdict), the rank score, `value.db` with the ticker file's latest rows and history, the
    funnel, the ruleset fingerprint.
  - `src/common/value_inputs.py` / `value_types.py` / `value_universe.py`; `select_periods(as_of=)`
    and `select_ttm`; 23 value line items in `config/research_concepts.yaml`; the research
    worker's `prices` job kind and `value_sweep` (off).
  - `scripts/value_dry_run.py`, `scripts/value_universe_snapshot.py`, the two snapshot CSVs.
  - Known limitations: CET1 is not tagged in companyfacts for BAC/JPM (`banks.require_cet1`
    decides, Task 15); method C is absent until point-in-time prices exist; the combined ratio is
    approximated from total benefits, losses and expenses; holidays are not known to the earnings
    window; prices carry yfinance's survivorship bias.
  ```

  and in `## Not built (deliberately deferred)` add a row: `| **Value book Parts 2–6** | The
  value process and shadow record, re-evaluation and Stage 1b, Claude as the analyst, Stage 3
  money (paper), web and Telegram — the roadmap in the Part 1 plan; each part is planned after
  the previous one merges. |`

- [x] **Step 9: Root `CLAUDE.md`.** In the doc-update table, after the `src/spreads/` row, add:

  ```markdown
  | **New module under `src/value/`** or a new key in `config/examples/value.yaml` | `ARCHITECTURE.md` `src/value/` section · `SETUP.md` §19 if operator-facing · root `CLAUDE.md` value-fence section if it changes what the package may import · a `rules:` key also bumps `ruleset_version` once v1 is frozen |
  ```

  Insert immediately before `## Reference documentation`:

  ```markdown
  ### The value fence — `src/value/` is deterministic and its own database

  `src/value/` (docs/superpowers/specs/2026-10-28-value-swing-book-design.md) scores companies for
  the value book. It is **deterministic tier**:

  - It imports nothing from `src.claude`, `src.news`, `src.value_ai`, `src.spreads*`, `src.notify`,
    `src.api`, `src.engine`, `src.execution`, `src.strategies`, `src.orchestrator`, `src.monitor`,
    `src.ledger`, `src.reporting` or the enrichment analytics, and from `src.research` only
    `src.research.ingest.concepts` and `src.research.schemas`.
  - Nothing on the trading path (engine, execution, strategies, orchestrator, monitor, notify) and
    nothing in spreads, news or claude imports `src.value`.
  - Its scorecard modules are pure (no I/O): Part 6's API may import `src.value.scorecard` and
    `src.value.schemas` and nothing else from `src.value`.
  - Inputs come from the neutral read-only `src/common/value_inputs.py` (plain shapes in
    `value_types.py`), which imports no enrichment and no `src.value`. The research worker owns
    every SEC and price fetch; `src/value/` opens no SEC client.
  - Only `src/value/` constructs `data/value.db` rows (`ValueBase`).
  - Part 1 places, sizes and gates nothing. The written exception for Claude's value verdict
    (spec §8.2, §18) is added with Part 4.

  Enforced by `tests/test_value_fence.py` — keep it green.
  ```

- [x] **Step 10: Check and commit**

  ```bash
  .venv/bin/python -m pytest -q
  .venv/bin/ruff check .
  .venv/bin/mypy src
  git add ARCHITECTURE.md SETUP.md STATUS.md CLAUDE.md docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "docs: value book Part 1 (the scorecard, the dry run, the value fence)"
  ```

**Section C exit (orchestrator):** `git log --oneline main..HEAD | wc -l` → `14`; full gate green,
pytest = baseline + 141; `py_compile` of both scripts silent; protected-file diff empty. Then
ask the operator, and on a yes run the whole-branch review below.

---

## Whole-branch review · model: opus, then one sonnet fix pass

- [ ] **R1.** Spawn one **opus** subagent: "Review branch `feat/value-book-1` against `main` for
  correctness, using superpowers:requesting-code-review. Read the plan's Rulings, Global
  Constraints and Review Focus, the spec §§6.0–6.9, 16, 17, and `git diff main...HEAD`. Check the
  formulas against the spec (and the rulings where the spec was overridden), the fence, the
  read-only and no-I/O guarantees, unknown-never-zero, the point-in-time reads, and the tests'
  pinned numbers. Report Critical / Important / Minor findings with file:line. Do not edit."
- [ ] **R2.** Record the findings in the Progress log. Spawn one **sonnet** subagent to fix every
  Critical and Important finding in **one** commit (`fix(value): whole-branch review fixes`),
  TDD where a finding is a behaviour, with the full gate green; Minor findings are listed as
  deferred in the Progress log unless trivial.
- [ ] **R3.** Verify the fix commit yourself (log, status, full gate, protected diff), then ask the
  operator before Section D.

---

## Section D — The calibration dry run and the freeze (Tasks 15–16) · the orchestrator, with the operator

Spec §17: "Build Stage 1's scorecard, run it once over the S&P 500 and the operator's lists, and
print a pass funnel … List GOOGL, META, BAC and MU by name with every number. Also print
raw-payload storage and run time. The operator reads it, settles the growth valuation (§6.5) and
any threshold that refuses everything or nothing, and only then is `value_rules: v1` frozen."
The orchestrator runs this section itself (ruling 35): it is two scripts on database copies and a
conversation. Every write lands in the worktree's own `data/` (git-ignored), never the main
checkout's.

**Spec to read:** §6.5 (the growth valuation and its GOOGL example), §17, §20 (the operator's
answers on the growth valuation).

**Entry checks:**

- [ ] **D1. Code complete and reviewed.** `git log --oneline main..HEAD | wc -l` prints `15` (14
  tasks + the review fix pass; `14` if the review found nothing to fix — record which). The
  review's findings are in the Progress log.
- [ ] **D2. Green.** `.venv/bin/python -m pytest -q` (baseline + 141), `.venv/bin/ruff check .`,
  `.venv/bin/mypy src`; `.venv/bin/python -m py_compile scripts/value_dry_run.py` silent.
- [ ] **D3. Room for the raw payloads.** `df -h .` shows at least 10 GB available (≈ 520
  companyfacts payloads of 2–9 MB each, plus the copies).
- [ ] **D4. The sources exist.** Each lists one file:

  ```bash
  ls -la "/Users/ianlim/Desktop/IBKR Investments/data/research.db"
  ls -la "/Users/ianlim/Desktop/IBKR Investments/data/income_system.db"
  ls -la "/Users/ianlim/Desktop/IBKR Investments/data/news.db"
  ls -la "/Users/ianlim/Desktop/IBKR Investments/.env"
  ls -la "/Users/ianlim/Desktop/IBKR Investments/config/universe.yaml"
  ```

---

### Task 15: The calibration dry run

- [ ] **Step 1: Copy the three databases into the worktree** (online `.backup`: safe while the
  daemons run; the copies are git-ignored by `data/*.db`). From the worktree root, one command
  each:

  ```bash
  sqlite3 "/Users/ianlim/Desktop/IBKR Investments/data/research.db" ".backup '/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/value-book-1/data/research.db'"
  sqlite3 "/Users/ianlim/Desktop/IBKR Investments/data/income_system.db" ".backup '/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/value-book-1/data/income_system.db'"
  sqlite3 "/Users/ianlim/Desktop/IBKR Investments/data/news.db" ".backup '/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/value-book-1/data/news.db'"
  ```

  The worktree has no private config, so every process there reads `config/examples/*` (a
  "not found; using the shipped defaults" warning per file is expected) — which is why the
  operator's own universe is passed with `--universe-file` below.

- [ ] **Step 2: Backfill the copy** (run in the background; it takes roughly half an hour to an
  hour — EDGAR is limited to 10 requests a second and each payload is several MB):

  ```bash
  .venv/bin/python -m scripts.value_dry_run backfill --env-file "/Users/ianlim/Desktop/IBKR Investments/.env" --universe-file "/Users/ianlim/Desktop/IBKR Investments/config/universe.yaml"
  ```

  Expected: `queued {'fundamentals': ~500, 'prices': ~500, 'no_cik': ~0} for ~519 names`,
  progress lines, then `backfill finished in Ns; K jobs failed` followed by the failed jobs.
  Record N and K in the Progress log. A handful of failures (a filer with no XBRL, a ticker
  yfinance does not know) is expected; more than ~5% → stop and report before running.

- [ ] **Step 3: Run the scorecard.** `<scratch>` is the session's scratchpad directory:

  ```bash
  .venv/bin/python -m scripts.value_dry_run run --env-file "/Users/ianlim/Desktop/IBKR Investments/.env" --universe-file "/Users/ianlim/Desktop/IBKR Investments/config/universe.yaml" --report "<scratch>/value_dry_run_v0.txt" --out "<scratch>/value_dry_run_v0_cards.json"
  ```

  Expected: two funnels ("Trading universe", "Evidence + trading universe"), GOOGL, META, BAC and
  MU with every number, then `regime …; relative-strength line …; no yfinance market cap: N`,
  storage lines and `run time: …`. If `N` is more than 5% of the non-ETF names, yfinance was
  throttling: run the same command once more and keep the better run (record both).

- [ ] **Step 4: Put it in front of the operator.** Show, in this order and without
  summarising the numbers away: the two funnels; the four named names (paste their blocks
  verbatim); raw companyfacts storage and `research.db` size; the run times. Then ask, one
  question at a time, recording each answer verbatim in the Progress log:
  1. **The growth valuation (§6.5, §20).** Show GOOGL's and META's D and the price beside it.
     Keep `discount_rate_growth` 0.08, `growth_sbc_share` 0.5, `realised_cap_growth` 0.20 — or
     which values?
  2. **Gates that refuse everything or nothing.** For each health gate, entry rule and timing
     check whose tally in the evidence funnel is ≥ 90% fail or ≥ 99% pass, ask: keep, or what
     value? (Name the gate, its bar and its tally.)
  3. **CET1 (ruling 3).** Every bank reads UNKNOWN while `banks.require_cet1` is true, because
     no bank tags CET1 in companyfacts. Keep (banks never qualify until Part 4's grounded facts
     could supply it), or set `false`?
  4. **Classification.** Anything mis-classed in the named names or the class counts (a broker
     wanting bank rules, a name that should be cyclical)?
  5. **The margin-of-safety bars and the 60% review line** — keep?
  6. **Storage.** The measured raw-payload size is what the research worker will hold once Part 2
     turns `research_sweep.enabled` on. Acceptable?

  The operator may ask for a rerun after any change: apply it to the worktree's code defaults
  and `config/examples/value.yaml` together (Task 16 Step 1), rerun Step 3 with a new report
  name, show the diff of the funnels. Rules changed now are not "tweaking after a loss" (§17).

- [ ] **Step 5: Record and commit the evidence.** The Progress log row for Task 15 carries:
  backfill time and failures, the run time, the market-cap misses, storage, the regime and the
  relative-strength line, each funnel's headline counts per list (READY / WATCH / WAIT / NO /
  UNKNOWN), the four named verdicts with fair value and margin of safety, and the operator's
  six answers. Commit the plan file only:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "docs(plan): value book Part 1 calibration dry run and the operator's answers"
  ```

---

### Task 16: The freeze — `value_rules: v1`

**Files:** `src/common/config.py` (the value block's defaults), `config/examples/value.yaml`,
`src/value/ruleset.py`, `tests/test_value_config.py`, `tests/test_value_dry_run.py`,
`STATUS.md`, `SETUP.md`.

- [ ] **Step 1: Apply the operator's answers.** For every changed key, edit the default in its
  `Value*Cfg` model **and** the same key in `config/examples/value.yaml`
  (`test_the_example_spells_out_exactly_the_model_defaults` keeps them equal). If an answer
  changes a test's pinned expectation (e.g. a fixture now fails a moved bar), update that
  expectation with the operator's value and say so in the ruling column. Run
  `.venv/bin/python -m pytest -q tests/test_value_*.py` → green.
- [ ] **Step 2: Name the version.** `ruleset_version: str = "v0-dryrun"` becomes `"v1"` in
  `ValueCfg`, and `ruleset_version: v0-dryrun` becomes `ruleset_version: v1` in the example.
- [ ] **Step 3: Compute the hash** —

  ```bash
  .venv/bin/python -c "from src.common.config import ValueCfg; from src.value.ruleset import ruleset_hash; print(ruleset_hash(ValueCfg().rules))"
  ```

  prints 12 hex characters, `<H>`. (With no threshold changed it is `147897fdbbdb` plus whatever
  the review fixes moved; trust the command, not this number.)
- [ ] **Step 4: Pin it.** In `src/value/ruleset.py`, `FROZEN: dict[str, str] = {}` becomes:

  ```python
  # value_rules v1, frozen <YYYY-MM-DD> by the operator after the calibration dry run (Part 1,
  # Task 16). A rule change is a new version with a written reason, at most quarterly (spec §6.8).
  FROZEN: dict[str, str] = {"v1": "<H>"}
  ```

- [ ] **Step 5: Tests.** In `tests/test_value_config.py` and `tests/test_value_dry_run.py`
  replace every `"v0-dryrun"` with `"v1"` (three places), and append to
  `tests/test_value_config.py`:

  ```python
  def test_v1_is_frozen() -> None:
      """Part 1, Task 16: the operator froze value_rules v1 after the calibration dry run."""
      assert FROZEN["v1"] == ruleset_hash(ValueCfg().rules)
      assert ruleset_id(get_config().value) == ("v1", FROZEN["v1"])
  ```

  Run `.venv/bin/python -m pytest -q tests/test_value_*.py` → green (one more test than before).
- [ ] **Step 6: The v1 record.** Rerun Task 15 Step 3 with `--report "<scratch>/value_dry_run_v1.txt"
  --out "<scratch>/value_dry_run_v1_cards.json"`; record the v1 funnel's headline counts in the
  Progress log. (The worktree's `value.db` is a copy and is discarded with the worktree; the live
  ticker files start with Part 2.)
- [ ] **Step 7: Docs.** `STATUS.md`'s Part 1 entry gains a line: "**Frozen:** `value_rules: v1`
  = `<H>` on <date>; the operator's calibration decisions: <one line each>." `SETUP.md` §19 step 4
  becomes "`ruleset_version` is frozen at `v1` (`src/value/ruleset.py::FROZEN`); a rule change is
  a version bump with a written reason."
- [ ] **Step 8: Full gate and commit**

  ```bash
  .venv/bin/python -m pytest -q
  .venv/bin/ruff check .
  .venv/bin/mypy src
  git add src/common/config.py config/examples/value.yaml src/value/ruleset.py tests/test_value_config.py tests/test_value_dry_run.py STATUS.md SETUP.md docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md
  git commit -m "feat(value): freeze value_rules v1 after the calibration dry run"
  ```

- [ ] **Step 9: Ask the operator** whether to merge `feat/value-book-1` into `main` and whether
  to push. Do neither without a yes.

**Section D exit:** two more commits; pytest = baseline + 142; the Progress log carries the dry
run's evidence, the operator's answers and the frozen hash.

---

## Operator to-dos after the merge

1. `cp config/examples/value.yaml config/value.yaml` — the private copy (git-ignored). Without it
   every process logs "config/value.yaml not found; using the shipped defaults".
2. Restart the research worker (`./ibkr restart`, or the `research` service alone) so it runs the
   code with the `prices` job kind. Nothing else needs a restart: Part 1 adds no daemon, and
   `research_sweep.enabled` stays `false` until Part 2.
3. The Research page's statements are unchanged; the extra line items land in `research.db` as
   each name is re-ingested.
4. Remove the worktree when done (`git worktree remove .claude/worktrees/value-book-1`); its
   database copies go with it.

---

## Self-review (run by the plan's author, 2026-10-29)

- **Spec coverage (Part 1's scope).** §6.0 two lists, entry rules, required margins → Tasks 1, 9;
  size tiers are Part 5. §6.1 universes → Task 4. §6.2 `as_of`, cross-checked market cap,
  survivorship caveat → Tasks 2, 3, 7, STATUS (Task 14). §6.3 data quality → Task 7. §6.4 health
  (operating, earnings quality, dilution, banks and insurers, cyclicals; the moat proxy as rank
  and entry input, not a gate) → Tasks 6, 7, 9, 10. §6.5 A/B/C/D, P/TBV, median, terminal-value
  check, sector rules (banks, REITs, pre-profit with the reverse-DCF line) → Tasks 8, 9. §6.6 →
  Task 9 (earnings dates as plain data: Task 13 reads `news.db` in the script, never in
  `src/value`). §6.7 Python's baseline per list → Task 9; Claude's verdict is Part 4. §6.8 rank
  score and ruleset fingerprint → Tasks 1, 10; the shadow ledger and ranked portfolios are
  Part 2. §6.9 ticker file Part 1, history, fingerprint, the neutral loader, research worker owns
  fetches, `not_applicable` files → Tasks 3, 4, 9, 11; the API path and follow window are
  Parts 6 and 2. §16 Part-1 fences and tests → Task 12 and every task's tests. §17 → Tasks 13,
  15, 16. §18 Part-1 docs → Task 14.
- **Placeholders.** None in Tasks 1–14: every module and test is given whole and was run green
  (141 tests, `ruff check`, `ruff format --check`, `mypy src`) on a scratch copy of `main` at
  `e2bf506` before this plan was written. Task 15–16 values that only the run or the operator
  can supply are marked `<H>`, `<date>`, `<scratch>`.
- **Type consistency.** `ValueInputs`/`ValueFinancials`/`PriceSeries` (Task 3) are what Tasks 5–13
  consume; `Check`, `combine`, `ListEvaluation`, `ValueScorecard.verdict_for` (Task 5) are what
  Tasks 9–13 use; `check_at_least`/`check_at_most` (Task 7) are used by Task 9; `RankEntry.score`
  (Task 10) feeds `persist(ranks=…)` (Tasks 11, 13); `build_value_universe`, `ValueUniverse.tag`
  (Task 4) are what the script uses; the fixture's `inputs()` signature is the one every test
  calls.
- **Review Focus.** Each of the five lines names the test that pins it, in the task that owns the
  code.
- **Proportion.** The plan carries complete code by the operator's brief (a Sonnet executor with
  no room for doubt); the spec's Part-1 sections are cited, not restated.
