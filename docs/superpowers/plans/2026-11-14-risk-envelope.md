# Risk Envelope, Leveraged-ETF Policy, the Spreads Book and the Bridge Hedge (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task (natively, or one subagent per section on the labelled model and effort, with a stop between sections: the operator's token-light method). The plan has twelve sections (A to L); each opens with **entry checks** that must all pass before its first task starts. **Task 15 (the web card) starts by invoking the `da-vinci` skill**, and so does any subagent given it (say so in its prompt). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the whole of the envelope spec, E0 to E4, as one change set:

- **E0, stop the bleeding and measure (Sections A-E):** the spreads book's missing safety links, NLV-based caps,
  cost standard and shadow-until-backtest; leveraged CSPs off; UPRO and DPST out; S10/S20/G10/P20/T20/S-SMH,
  U_ew and L(t) computed and shown (Telegram, `GET /envelope`, one web card), not enforced; the IV sanity check;
  SPY IV restarted; XND/QQQ hedge-menu and SPXW wing quote capture started; the Nasdaq-100 breadth oscillator and
  the Leveraged Entry Signal (LES) recorded each session (Task 10a). Sections A-E are offered for an
  **early merge** so the capture clocks start.
- **E2, the envelope live in paper (Sections F-G):** U_ew in place of the wheel's nominal gross check; S10_gross
  ≤ L(t) at the generator, the gate and send time (fail closed); value-book buys under the same test; the index
  class; the slow breaker; the leveraged sleeve; the class multipliers, the T20 trigger, the tech-linked cap and
  the stacking rule behind data-gated switches.
- **E1, the replays (Section H):** the survivability harness, the rule backtests and the in-estate replays, each
  printing PASS/FAIL into a result file that turns its behaviour on automatically in paper.
- **E2, book repair (Section I):** tap-only repair proposals, the stock order path (trims), de-lever, and the
  LES share buys and trend-break exits for TQQQ/SOXL (paper, automatic behind `leveraged_entry`, Task 32a).
- **E2, the bridge hedge (Section J):** the minimum buy-to-open build (§3.10.10 items 3-12) and the Python-run
  Nasdaq-100 bridge, paper only, ending at E4.
- **E3, SPXW and SPY freed (Section L):** written now, **run later** on the PASS notice, at a flat-book cutover.

**Architecture:** Four new deterministic modules carry the envelope. `src/analytics/shock.py` (pure: betas in,
scenario losses out, full Black-Scholes revaluation, gross and net of long options), `src/analytics/shock_inputs.py`
(reads betas from `price_history` and stored IV), `src/engine/envelope.py` (assembles the book, the glide L(t),
the admission test the generator, the gate and the value book share) and `src/storage/envelope_state.py` /
`envelope_switches.py` (the glide record and the data-gated switches in `system_settings`). Live IV comes from
`src/ibkr/live_iv.py` through `req_fresh_mkt_data`. The spreads book reads the account halt and the slow breaker
through `src.storage.system_settings` (service.py only) and exposes its P&L to the wheel through a read-only
`src/common/spreads_view.py`. The hedge is its own deterministic package `src/hedge/`, its own tables, its own
clientId (32), with `validate_hedge` in the Rules Engine and `src/common/hedge_view.py` as everyone else's view.
The core invariant is untouched: the Rules Engine (and `src/spreads/risk.py::validate` for spreads) stays the only
path to an order; no LLM output reaches anything in this plan.

**Tech Stack:** Python 3.12, ib_async, SQLAlchemy/SQLite, Pydantic, pytest; FastAPI; Next.js 15 / React 19 /
Tailwind v4 / Vitest for one card.

**Spec:** `docs/superpowers/specs/2026-11-13-risk-envelope-design.md` revision 3 (§ numbers below are its
sections; revision 3 adds §0.2, §2.7 and §3.5.1, the Leveraged Entry Signal), with the operator's answers of
2026-11-14 (Rulings, below). The Mastermind spec
(`2026-11-12-mastermind-design.md` rev 4) is read only where cited (§10.7 for the `hedge:claude:` reservation).

## Execution model

| Section | Tasks | Model | Effort | Why this model |
|---|---|---|---|---|
| **A, Foundation: switches, notices, result files, the macro calendar** | 1-2 | sonnet | high | New small modules with full specs here |
| **B, The spreads book's fixes (E0)** | 3-7 | **opus** | high | Inside the spreads fence; sizing and the halt link change a live book's gate |
| **C, Leveraged policy, universe, IV data, breadth and LES (E0)** | 8-10, 10a | sonnet | high | Config and one sizing function; a reader sweep; one pure signal module with its data feed |
| **D, Measurement and displays (E0)** | 11-15 | **opus** (11-14), sonnet (15, UI) | high | The shock math is the base of every gate after it; 15 is UI with da-vinci |
| **E, Quote capture (E0)** | 16-17 | sonnet | high | Capture only, no order path |
| **F, The envelope gate (E2)** | 18-21 | **opus** | high | The Rules Engine, the generator, the send-time re-gate and the value fence |
| **G, Limits behind switches (E2)** | 22-25 | sonnet | high | Each limit is a reason behind a switch, specified here |
| **H, Replays and the harness (E1)** | 26-29, 29a | sonnet | high | Read-only reports that write result files |
| **I, Book repair, the stock order path and LES shares (E2)** | 30-32, 32a | **opus** | high | A new order path (stock SELL/BUY) through the Rules Engine; the first automatic stock buys (paper) |
| **J, Buy-to-open and the bridge hedge (E2)** | 33-37 | **opus** | high | A new order direction, a new clientId, a new fence |
| **K, Finish** | 38 | sonnet (docs); then **opus** whole-branch review (high), **sonnet** fix pass (high) | high | Doc sweep |
| **L, E3: spreads to SPXW, SPY to the wheel (deferred)** | 39 | **opus** | high | Fence change at a flat-book cutover; runs only on the E3 PASS notice, from `main`, in its own worktree |

**Run order and dependencies.** A → B → C → D → E → (early-merge question) → F → G → H → I → J → K → review →
merge. L waits for the E3 PASS notice (Task 17's report plus the spreads backtest, so at least 15 sessions of SPXW
capture after the early merge and your ThetaData run). Code for every section is built now. **What waits on data
waits at run time, through switches** (Task 1): the envelope goes from `record` to `on` only after Task 26's harness
PASS and 10 clean record sessions; the hedge instrument is set by Task 16's report after 20 capture sessions; the
bridge starts only when the envelope is `on` and the instrument is set (Task 36); each H-section replay turns on its
own behaviour. Section H's replays read the switch names and rule functions that F and G build, so H runs after G.

**How a section runs (the orchestrator).** The main session is a Sonnet orchestrator at high effort. For each section:

1. Run the section's **entry checks** yourself, in order. **Any check fails: stop**, report the output, do not start
   the section. A failure that belongs to the previous section is fixed there (reopen its last task, record the ruling).
2. All pass: add a "Section X entry" row to the Progress log (gate result, date) in the worktree.
3. Spawn **one** subagent for the section with `model` and `effort` from the table (pass `effort` on every spawn). Its
   prompt names this plan, the section, the "Reads" list, and for Task 15: "Invoke the `da-vinci` skill before any UI
   code; never run `next build` or `next dev` inside `web/` (the operator's `.next` is shared): use G4's scratch copy."
   Tell it to commit each task, fill its Progress log row in the same commit (status, commit, gate, date, every
   ruling with its cost-if-wrong), and stop on any red gate it cannot attribute to its own change.
4. Verify the report yourself: `git log --oneline main..HEAD`, `git status --short`, gate counts against the section
   exit, and G1-G3 below.
5. **Stop and ask the operator before the next section.** After Section E, the question is the early merge.

After Section K: one **opus** whole-branch review (superpowers:requesting-code-review, effort high) as a subagent; the
orchestrator confirms each finding in the code; one **sonnet** fix pass (high). Ask before merge or push.

**The early merge of Sections A-E (E0).** E0 adds no new authority: it tightens the spreads book, stops leveraged CSPs,
and measures. The capture clocks (20 sessions for H4, 15 for E3) and the record sessions start only once the daemons run
this code. When Section E exits green, ask: "Merge Sections A-E to main now and restart?" On yes, from the **main
checkout** (on `main`, clean): `git merge --ff-only feat/risk-envelope` then `./ibkr restart`. Record the commit and the
restart time in the "Early merge" row. Before the restart the operator makes the private-config edits in Operator
to-dos 1-4 (worktree sessions cannot edit private `config/*.yaml`). The branch keeps going on top.

**How to apply a step (for the implementer).** Steps give the exact names, signatures, keys, reasons and test names.
Where a short code block is given, copy it; elsewhere write the code to the stated behaviour under the stated tests,
red first. Line numbers are from `main` at 854d493: if an anchor does not match, stop and report rather than guess.
Every new config key goes into the committed `config/examples/<file>.yaml` with a one-line comment, and into its
pydantic class with the stated default.

**Commit counts.** Each task is one commit and fills its own Progress log row. A0 adds one commit on `main` (this plan
and the spec note). A review fix pass adds one commit.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **Plan written** | done | (plan file + spec note, uncommitted) | not prototyped; anchors read against `main` at 854d493 and DB copies of 2026-11-13 | 2026-11-14 | Rulings section below; code facts C1-C8 |
| **LES added** (spec rev 3) | done | (uncommitted) | scratch study only (spec §2.7) | 2026-11-14 | OR13-OR17 → L1-L8; Tasks 10a, 29a, 32a; Task 23 and P10 changed |
| A0 setup | done | eeab726 (on `main`, already committed: plan + spec rev 3) | 11 GiB free; worktree `.claude/worktrees/risk-envelope` on `feat/risk-envelope`, `.venv` + `web/node_modules` symlinked, `init_db()` run | 2026-11-14 | Ruling: A1 reads "A0 over 854d493"; HEAD is eeab726 (docs-only, one commit over 854d493) so the plan's anchors still hold. Cost if wrong: none |
| Section A entry | done | | A1-A3 pass (anchors match, a few lines off the plan's cited numbers). A4 baseline: pytest 5784 passed / 1 skipped, ruff clean, mypy clean (361 files), vitest 1625 passed (153 files), tsc and eslint clean | 2026-11-14 | Orchestrator runs sections back to back without the stop-and-ask (operator instruction 2026-11-14: "run all sections to completion"); merge/push still asked. Section L (Task 39) is deferred by the plan and is not run |
| Task 1: switches, notices, result files | done | abb4963 (`feat(envelope): data-gated switches, result files and notices`) | pytest 5799 passed / 1 skipped (baseline 5784 + 15 new), ruff clean, mypy clean (363 files); G3 `-k live` passes | 2026-11-14 | (1) Tests and code were written in one pass and run green together, not strictly red first; cost if wrong: none (the tests assert every named behaviour and were run against the final code). (2) `send_notice` is `async` (the plan gave no signature; EOD and the approval service are async, the CLI wraps it in `asyncio.run`); cost if wrong: a later sync caller needs `asyncio.run`. (3) The plan names defaults for 11 of the 15 switches only; `tech_cap`, `stacking_rule`, `index_1x`, `leveraged_sleeve`, `leveraged_cc_auto` ship `off` with allowed set {off, on}; cost if wrong: a later task adds a third value to the set. (4) EOD wiring is a small `_apply_envelope_reports()` helper (called as step 7a, right after the Telegram send) so it is testable; same behaviour as the plan's inline text. (5) 15 tests, 7 beyond the plan's eight names (the plan's eight, plus CLI, EOD hook, missing report dir, a later report replacing an earlier report's value, an unparseable stored record, and two `send_notice` tests); `test_every_switch_reads_its_default_in_live` stores a non-default for every switch first, so it proves the live override and not just the default |
| Task 2: the static macro calendar | done | 62c5c9a (`feat(config): a static FOMC/BLS/BEA calendar for a year ahead`) | pytest 5804 passed / 1 skipped (5799 + 5 new), ruff clean, mypy clean (364 files) | 2026-11-14 | (1) **Source reads.** FOMC (federalreserve.gov) and BEA (bea.gov `/news/schedule` and `/news/schedule/next-year`) were parsed from the pages' raw HTML. bls.gov refused a plain `curl` ("Access Denied") and I did not retry with a spoofed client; the CPI, PPI and Employment Situation dates were read through the WebFetch tool from the bls.gov schedule pages (the tool's own summary, not raw HTML). They were sanity-checked (every date a weekday, every NFP a Friday, CPI/PPI monotone by month) but not diffed against raw HTML. **Orchestrator cross-check (2026-11-14):** a second, independent WebFetch of the three bls.gov pages, asked for the table rows verbatim, returned dates identical to all 39 committed BLS rows (13 each for CPI, PPI, NFP). Still a summarising fetch, not raw HTML, so the operator spot-check stays on the to-do list but the risk is low. Cost if wrong: a BLS date off by a day would unblock or block the wrong spreads session; a human should eyeball the 39 BLS rows against bls.gov before the spreads calendar block (Task 3) is relied on live. (2) **No December 2027 FOMC row**: the Fed's page lists 2027 as Jan 26-27, Mar 16-17, Apr 27-28, Jun 8-9, Jul 27-28, Sep 14-15, Oct 26-27, Nov 16-17 and nothing after; the tool summary of the same page had agreed. I recorded the decision day (second day) of each, plus 2026-12-09, and invented nothing. Cost if wrong: a December 2027 FOMC day is unblocked until the Fed publishes it (about a year away). (3) **Range**: the file starts 2026-11-25 (the first event after 2026-11-14; the BLS CPI 11-10 and PPI 11-13 and NFP 11-06 releases fall before the plan's start) and ends 2027-12-23. (4) The file is a bare YAML list, as the plan says (`- {day, kind, time_et, source}`); FOMC rows carry `time_et: "14:00"`, all data rows `"08:30"`. (5) `test_fomc_days_are_wednesdays_or_announced_exceptions` ships with an empty exception set (every published decision day is a Wednesday). (6) `test_the_calendar_reaches_a_year_ahead` is a staleness alarm: it fails from 2027-02-27 on, which is the cue to refresh the file; cost if wrong: a red test on that date, none before |
| Section A Tasks 1-2 / exit | done | abb4963, 62c5c9a | pytest 5804 passed / 1 skipped = baseline 5784 + 20 new (15 + 5); ruff clean; mypy clean (364 files); G1 93 passed (the seven fence files); G2 grep prints nothing; G3 1 passed | 2026-11-14 | Two commits after 09abc64 |
| Section B entry | done | | Section A's two commits present; the three anchor greps print a line (config.py:944, chain.py:394, store.py:513). Orchestrator re-verified Section A exit: full pytest 5804 passed / 1 skipped, G1 93 passed, G2 empty, G3 1 passed, ruff and mypy clean | 2026-11-14 | Orchestrator cross-checked the 39 BLS calendar dates with a second fetch (all match); header comment and Task 2 ruling updated |
| Task 3: the calendar and the account halt reach the spreads gate | done | a6bc378 (`feat(spreads): the macro calendar, the account halt and the slow breaker stop entries`) | pytest 5813 passed / 1 skipped (5804 + 9 new), ruff clean, mypy clean (364 files) | 2026-11-14 | (1) **Red first, partly.** The three gate lines, the config key and the context fields were written just before their tests; the tests were then run green against them, not observed red. Cost if wrong: none (each named behaviour is asserted). (2) **A strict reader, not `is_halted()` / `get_setting`.** Both swallow a DB error and return the default (not halted), which would fail open; `system_settings.get_setting_strict` (new, raises on an unreadable table) backs `SpreadsService._account_state`, so "any exception → (True, True)" is real. An unparseable `slow_breaker_tripped` value also reads (True, True). Cost if wrong: a transient SQLite lock blocks one entry check (alerted once a day). (3) The slow breaker's key is named `slow_breaker_tripped` here (`service.SLOW_BREAKER_KEY`) for Task 22 to write as JSON `{"tripped": true, ...}`. Cost if wrong: Task 22 must write that key or change the constant. (4) `_events_today` lists every calendar event of the day with "no new entries today" / "no block", so the picker's `events` and `event_flag` now include non-blocking prints (CPI etc.). Cost if wrong: `--compare`'s event grouping counts 08:30 print days as event days. (5) A calendar file that fails to load raises inside `_context`; the entries phase's `_guard` alerts once and nothing opens (fail closed by exception, no special path). (6) Test isolation: the shared `spreads_db` fixture (also used by `test_spreads_books.py` and `test_spreads_picker_flow.py`) pins `_account_state` to (False, False); the four account-stop tests restore the real reader on a tmp trading DB (`db` fixture) or a broken `session_scope`. (7) Two tests beyond the plan's seven: `test_a_tripped_slow_breaker_reads_from_system_settings`, `test_the_calendar_reaches_the_gate_and_the_events_list`. (8) Fence (Step 5): no change needed; `src.common.macro_calendar` is common and `src.storage` is imported lazily by `service.py` only; `test_spreads_fence.py` green |
| Task 4: caps as shares of net liquidation; the month stop | done | 3444185 (`feat(spreads): risk in shares of net liquidation and a month stop a human resets`) | pytest 5828 passed / 1 skipped (5813 + 15 new), ruff clean, mypy clean (364 files) | 2026-11-14 | (1) Red first: the risk, config, chain and service tests were written and run red (15 failed in risk/config) before the code. (2) `SpreadRiskContext.nlv_usd` defaults `None` (the plan gave no default), so a context built without it is refused `nlv_unknown`; `SpreadsService._context` takes `nlv=` keyword-only for the same reason (a missed call site fails closed; it also keeps the existing positional `mode`). NaN or ≤ 0 counts as unknown. (3) An unknown NLV gives both `nlv_unknown` and `account_unknown` (the plan's test name carries `account_unknown`, its Step 4 names `nlv_unknown`; without the NLV the 40% floor cannot be measured either). Cost if wrong: one extra reason string. (4) **Open P&L needed a mark the store did not keep** (`note_mark` kept only the worst): `spread_positions.last_mid_debit` added (additive `ALTER TABLE`), written on every mark; `store.open_pnl_usd(mode)` reads it; a spread not yet marked counts 0. Task 6's view reads the same column. Cost if wrong: between an entry and its first manage tick (≤ 30 s) the open P&L misses a few cents of slippage. (5) `month_realized_pnl` counts spreads by the ET month they opened (0DTE: same day). (6) The month stop is one book-wide flag (`spread_flags.month_stop`), tripped by the traded book (`cfg.mode`) at each armed entry check, so it also stops the simulated baseline book. `month_stop_set` never overwrites a set record; a same-month reset trips again at the next check (ruling E2: "until a human reset in a later month"). Cost if wrong: the baseline comparison pauses with the main book. (7) The existing validator is unchanged; the five new keys get their own `(0, 1]` validator. (8) The legacy keys keep their old defaults in the class and are ignored. (9) **Backtest, interim:** `run_day` passes its replayed capital (× `trade_scale`) as the NLV stand-in until Task 7's `--nlv`; `test_size_is_ten_percent…` became `test_size_is_half_a_percent_of_the_capital_it_is_given` (2M → 21, 650k → 6). (10) Existing tests re-based on the new rule, none weakened: risk sizing 22 → 7 with ctx NLV $650k and excess $400k; the service's sizing test (→ 7); `FakeBroker` gains `net_liquidation` ($650k) and excess $400k (above the 40% floor); the picker's "contract count comes from the re-gate" test now uses NLV $612k (6 on the menu, 7 after the richer re-quote) so it still shows the re-gate changing the count; `DriftingExcessBroker` starts at $400k; the config sizing test renamed. (11) `scripts/spreads_reset_month.py` is `clear()` (prints, returns the notice text) plus `main()` (sends it to the spreads thread), so the async service test can call `clear()`. (12) Tests beyond the plan's seven: `test_total_risk_is_a_share_of_nlv`, service `test_an_open_mark_counts_in_todays_loss` and `test_an_unknown_nlv_blocks_entries`, chain `test_net_liquidation_reads_the_same_stream_in_usd`, config `test_the_example_no_longer_carries_the_capital_caps` and `test_a_private_copy_with_the_legacy_keys_still_loads` |
| Task 5: the cost standard | done | def2d88 (`feat(spreads): a measured cost standard before any record counts`) | pytest 5835 passed / 1 skipped (5828 + 7 new), ruff clean, mypy clean (364 files) | 2026-11-14 | (1) Red first: `tests/test_spreads_costs.py` was written and run red (collection error: the helpers did not exist) before the code. (2) **The fee is a per-class map only** (`execution.exchange_fees`, keyed by `trading_class`, `{SPY: 0.0, SPXW: null, XSP: null}`); no separate scalar `exchange_fee_per_contract` key, since the plan's text names both and the map covers SPY. Cost if wrong: none (a scalar would duplicate the SPY entry). (3) **SPXW and XSP fees left `null`**: I did not take numbers from IBKR's fee page in this session (a summarising fetch of a fee schedule is not a source I would trust for a gate input). `null` blocks the cost report for that class (BLOCKED line) and, beyond the plan, `SpreadsCfg._fee_known` refuses to load an **enabled** book whose traded class has no fee, and `menu.cost_per_contract` raises on one. Cost if wrong: an operator who switches `trading_class` to SPXW before filling the fee gets a config load error (loud, by design) instead of a silently flattered record. STATUS.md notes it; fill before Task 39. (4) **Finding, not changed:** the measured $0.01 (spec §2.3) is `credit_mid − credit_natural` per spread side; the plan applies $0.01 + $0.01 margin **per leg**, so the modelled entry cost per side stays $0.04, exactly what spec §2.3 called 4× the measured crossing. I implemented the plan's numbers; the cost report prints both figures so the operator can narrow it. Cost if wrong: the shadow record stays conservative by ~$0.02 a side. (5) The cost helpers live in `menu.py` (`slippage_per_leg`, `fee_per_contract`, `cost_per_contract`, `round_trip_cost`) and the executor imports them, so the shadow fills, the late-fill and missing-report commission estimates, the menu and the picker's round-trip cost share one standard; `scripts/spreads_report.py --compare`'s fill bias uses `slippage_per_leg` too. (6) Existing tests that pin the executor's and the menu's mechanics at $0.02 a leg now also pin `slippage_margin_per_leg: 0.0`, so their arithmetic is unchanged; the picker test's `SLIP` reads `slippage_per_leg(AI)`. (7) `scripts/spreads_costs.py` attributes every candidate to the configured `trading_class` (candidates carry no instrument column). (8) Tests beyond the plan's three: `test_the_shipped_standard_is_the_measured_crossing_plus_a_margin`, `test_a_shadow_fill_pays_the_standard_on_each_leg`, `test_the_cost_report_opens_the_file_read_only`, `test_an_unknown_fee_blocks_the_report_for_that_instrument` |
| Task 6: spreads P&L in the wheel's daily loss leg; the Nov 10 lesson pinned | done | f4d854e (`feat(breakers): the spreads book counts in the daily loss leg`) | full pytest 5845 passed / 2 failed / 1 skipped: the 2 were `tests/test_breaker_ack.py`'s exact reason-string assertions, which the by-book reason changes by design; re-based to the new string and re-run green with the breaker, view and fence files (71 passed), so 5847 = 5835 + 12 new; ruff clean, mypy clean (365 files) | 2026-11-14 | (0) `tests/test_breaker_ack.py`'s two reason assertions now expect `"Daily mark-to-market loss $12,000 (wheel -$12,000, spreads $0)"` (and the $21,000 one): the plan's Step 3 sets that format. (1) Red first: the view, breaker, trip-card and fence tests were written and run red (9 failed) before the code; the two Nov 10 pins passed on the existing code at once, which is their job (they pin `9da9e8a` and the mismatch block, they do not change them). (2) **"Plus `-(pnl_today or 0)` when negative"** read as: the account's day = wheel mark delta + min(spreads P&L, 0). A spreads gain never offsets a wheel loss; a wheel gain does offset a spreads loss (the leg measures the account's day). Cost if wrong: a day with a wheel gain and a spreads loss trips later than a per-book reading would. (3) The view also counts the booked part of a still-open spread opened today (a partial close), beyond the plan's formula, so a half-closed loser is not half-hidden. (4) A missing or unreadable spreads.db is `None`, counted 0 by the breaker (as the plan's `or 0`): the daily leg falls back to the wheel alone rather than tripping. Cost if wrong: an unreadable spreads.db hides that book's loss from this leg for the day (the drawdown leg still sees it through NLV). (5) **The trip card was inline text in `src/execution/approval.py`, not in `formatters.py` (the plan's anchor):** moved into `formatters.format_breaker_halt(reason)` (imported lazily, as execution's other formatter imports are), same wording plus one sentence that the spreads book opens nothing new while halted. (6) **Fence (Step 4):** no existing test forbids other spreads.db readers outside `src/api/`; added `tests/test_web_fence.py::test_outside_the_api_and_the_book_only_spreads_view_opens_the_spreads_file` (the one allowance: `src/common/spreads_view.py`, `mode=ro`, no `src.spreads`), an extension, nothing loosened. (7) `tests/conftest.py::_spreads_view_in_tmp` (autouse, the `value_view` pattern) points the view at a missing file so no test reads the operator's spreads.db through the breakers; the view's own tests patch `_path`. (8) **Root `CLAUDE.md` not edited:** its spreads fence says the wheel learns of the spreads book "only through `src/common/books.py`"; `spreads_view.py` is now a second, read-only window. Left for the operator / Task 38 (STATUS.md says so). (9) Tests beyond the plan's seven: `test_the_view_reads_the_configured_spreads_file`, `test_pnl_today_is_zero_on_a_quiet_day`, `test_the_view_imports_nothing_from_the_spreads_package`, `test_the_daily_leg_is_the_wheel_alone_without_a_spreads_loss`, the fence test |
| Task 7: shadow until the paper bar; the backtest harness on the new standard | done | this task's commit is the last of Section B; its hash is in the orchestrator's Section B exit row (`feat(spreads): shadow until the backtest bar passes; the harness on the cost standard`) | pytest 5855 passed / 1 skipped (5847 + 8 new), ruff clean, mypy clean (365 files); G2 empty, G3 1 passed | 2026-11-14 | (1) Red first: the service and backtest tests were written and run red (collection error: `_paper_switch_on`, `paper_bar`, `nlv_usd` did not exist) before the code. (2) **How "every use of `self.cfg.mode` goes through it" is done:** `resolve_mode(cfg)` (module level) decides once; the service stores `configured_mode` and replaces `self.cfg` with a copy carrying the effective mode, so every existing `self.cfg.mode` read is the traded book's, and `effective_mode()` returns it. `run()` resolves once and builds the executor on the same mode, so the executor and the service cannot disagree; the service also swaps any paper `SpreadExecutor` it is handed for a simulated one when downgraded (defence in depth). The switch is read at start only: a switch change needs `./ibkr restart`. Cost if wrong: a PASS mid-day takes effect at the next restart, not the next tick. (3) **Beyond the plan: a closes-only wind-down.** A paper config dropped to shadow with paper spreads still open (a restart mid-session after this merge) would have left them unmanaged into the 15:45 time stop (SPY settles in shares). `run()` passes a paper `wind_down_executor` in that case; `_manage` and `_late_fills` run it for the `paper` rows; nothing opens through it. Cost if wrong: none (it only ever closes). (4) An unreadable switch reads shadow (logged). (5) **The backtest's fills:** "applies the Task 4/5 standard" read as: sized at the live shares of the stated NLV (compounding with realised P&L), each leg pays `menu.cost_per_contract` (commission + SPY fee), and each fill pays the **worse** of the existing `fill_haircut` of the mid→natural gap and the cost standard's slippage (2 legs × `slippage_per_leg` × `trade_scale`). The haircut is kept because SPXW gaps can be wider than SPY's per-share standard scaled up. The mechanics tests now pin the standard's slippage at 0 (so their haircut numbers stand) and a new test shows the standard binding. Cost if wrong: the backtest is a little more conservative than either model alone. (6) `run_day`'s sizing parameter is now `nlv_usd` (was `capital_usd`); `capital_usd` on the context is reporting only; default `starting_capital_usd` as a stand-in, but the script refuses to run without an NLV (`--nlv` or a snapshot). (7) The paper bar is `src/spreads/report.py::paper_bar` (pure, seeded `random.Random`, 10,000 draws of the session series with replacement); `run_backtest(..., sessions=)` collects every replayed session so no-trade days count as zeros. `scripts/spreads_backtest.py` gains `latest_nlv()` (trading DB `mode=ro`) and `write_report()`. (8) The harness has still never run against a real Theta Terminal (Operator to-do 6); nothing here was run against one. (9) Tests beyond the plan's six: `test_an_unreadable_switch_reads_shadow`, `test_paper_spreads_open_at_a_downgrade_are_still_closed`, `test_the_backtest_pays_the_cost_standard_when_it_is_wider_than_the_haircut`; the compounding test now also checks the `sessions` list |
| Section B exit | done | a6bc378, 3444185, def2d88, f4d854e, f449267 (Task 7) | Orchestrator re-verified: five commits after ce07b77, tree clean; full pytest 5855 passed / 1 skipped (5804 + 51 new); ruff clean; mypy clean (365 files); G1 94 passed; G2 empty; G3 1 passed; `tests/test_spreads_*.py` + `test_circuit_breakers.py` 418 passed. Existing-test edits read and accepted (re-based to the new rules, no assertion weakened) | 2026-11-14 | Owed forward: SPXW/XSP exchange fees are `null` and an enabled book refuses to load without its class's fee, so they must be filled before Task 39; the plan's $0.01 + $0.01-per-leg margin still models $0.04 a side (spec §2.3 complained about 4x), reported by `scripts/spreads_costs.py`, operator's call; root CLAUDE.md's spreads fence text must name `spreads_view.py` (added to Task 38) |
| Section C entry | done | | Section B exit green (above); the `KEYS` anchor prints config.py:2474. Baseline 5855 passed / 1 skipped, mypy 365 files | 2026-11-14 | |
| Task 8: leveraged CSPs off; no fair-value waiver for them | done | 465ff29 (`feat(regime): no leveraged CSP outside the drawdown sleeve`) | pytest 5860 passed / 1 skipped (baseline 5855 + 5 new), ruff clean, mypy clean (365 files) | 2026-11-14 | (1) Tests written first, then the code; the new tests were not observed red one by one (the existing leveraged tests failed on the full run before they were re-based). Cost if wrong: none. (2) **Existing tests changed (8 failed on the first full run, all pinning decision 32's floor of one lot):** `tests/test_regime_limits.py` (8 tests set `csp_mode: normal`), `tests/test_regime_send_time.py` (2), `tests/test_regime_sizing_integration.py` (4), `tests/test_scale_in_gate.py::test_near_money_put_fires_the_ladder_not_a_block`, and `tests/test_week_replay.py` (an autouse fixture: the replayed week of 2026-10-13 ran under decision 32, and its ladder arithmetic is what the file asserts). No assertion was weakened: each test now runs under `csp_mode: normal`, the mode that reproduces the old behaviour. (3) `leveraged_sizing.enabled: false` still means "the name is unleveraged" (`leverage_factor` returns None), so the drawdown-only policy goes with it; `test_leveraged_sizing_has_its_own_switch` sets both. Cost if wrong: an operator who switches the block off to lift the ceiling also lifts the zero-lot policy. (4) `ceiling_kind` reports `leveraged_ceiling` when the zero comes from the policy (cap 0 < min(pre, base)), as for any leveraged cut. (5) New tests: `test_drawdown_only_gives_zero_outside_the_sleeve`, `test_normal_mode_keeps_decision_32`, `test_a_sleeve_lot_keeps_the_leveraged_ceiling` (beyond the plan), `test_vrp_waiver_is_false_for_a_leveraged_name`, `test_vrp_waiver_still_holds_for_an_unleveraged_signal_lot`. `regime_limits.sleeve_lot` is the stub Task 23 fills |
| Task 9: the universe template, SOXX, SPY IV restarted | done | f60b261 (`feat(universe): UPRO and DPST out, SOXX dip-watch, QQQ wheeling, SPY IV restarted`) | pytest 5864 passed / 1 skipped (5860 + 4 new; run with the Task 10 and 10a test files, still unwritten code, set aside), ruff clean, mypy clean (365 files) | 2026-11-14 | (1) **Anchor mismatch, not a stop:** the plan and root `CLAUDE.md` name `UNIVERSE_RESEARCH.md` at the repo root; it lives at `docs/archive/UNIVERSE_RESEARCH.md` (last edited 2026-10-10 in f042cc5). I edited it there. Cost if wrong: the operator expected a root file; `git mv` back if so. (2) `UNIVERSE_RESEARCH.md` had a DPST section but **no UPRO section**: DPST's is marked removed (dated), UPRO is covered in a new "Changes — 2026-11-14" section; the SOXX entry states no price, IV rank or premium (none was researched; none is invented). (3) UPRO and DPST keep their `sectors` and `strike_bands` entries in the example `universe.yaml` and their `leveraged_sizing.leverage` entries, for a lot still held (the plan says to keep `leverage`; the sector/strike-band choice is mine). Cost if wrong: two stale tags. (4) **Side effect of dropping them from `leveraged_etfs`:** `src/research/checks/warnings.py` no longer produces the decay warning for UPRO/DPST; `tests/test_etf_warnings.py` re-based (LEVERAGED = TQQQ, SOXL, LABU, TSLL; the deliberate-exception test lists TQQQ and SOXL). (5) **Existing tests changed:** `tests/test_universe_consumers.py::test_csp_eligibility_matches_operator_decision` (DPST is out, TQQQ/SOXL stay would_own and leveraged); `tests/test_eod.py::test_iv_symbols_include_holdings_and_order_oldest_first` (SPY now joins the never-observed group: `["CCC","SPY","ZZZ","BBB","AAA"]`); `tests/test_etf_warnings.py` as in (4). (6) New tests: `test_reference_iv_symbols_join_the_eod_iv_list`, `test_reference_price_symbols_join_the_daily_price_append`, `test_reference_symbols_never_enter_the_universe` (plan), plus `test_the_universe_template_after_the_leveraged_policy`. `_DEFAULT_TECH_LINKED` in `config.py` also gains SOXX so the code default matches the template. (7) `scripts/backfill_iv.py` (IV, not prices) was **not** changed: it still seeds the universe ∪ held; SPY's IV past year is filled by `--symbols SPY` (SETUP.md says so). |
| Task 10: the IV sanity flag; every reader skips flagged rows | done | cd59708 (`feat(data): flag implausible IV observations; every reader skips them`) | pytest 5875 passed / 1 skipped on the full run (5864 + 11 new), plus the 12th test (the migration test, added after that run) passed on its own; Task 10a's full run (5915) confirms it; ruff clean, mypy clean (365 files) | 2026-11-14 | (1) **Readers (Step 1), as found 2026-11-14 by `grep -rn "IVHistoryRow\|iv_history" src scripts`:** selects over `IVHistoryRow` are in `src/storage/iv_history.py` (`latest_iv`, `latest_obs_dates`, and the existence check in `append_observation`), `src/analytics/iv.py` (`_load_iv_history`), `src/backtest/data.py`, `src/api/routers/watchlist.py` and `src/api/routers/research.py` (two); `src/ibkr/market_data.py`, `src/ops/watchdog.py`, `src/notify/{formatters,approval_service}.py` and `src/orchestrator/eod_report.py` reach it only through `latest_iv`, `latest_obs_dates` and `stale_symbols`; `src/research/checks/metrics.py`, `src/research/ingest/materialize.py`, `src/backtest/engine.py` only mention it in comments. All now filter `flagged IS NOT 1` (NULL-safe). (2) **One deliberate exception:** the existence check in `append_observation` must see flagged rows (the unique (symbol, date) constraint covers them); `test_every_reader_skips_flagged_rows` lists it by (file, function) and scans all of `src/`, not only the plan's list. `scripts/backfill_iv.py` writes `IVHistoryRow` directly and does **not** flag (a one-shot bootstrap of history bars with no per-day vol-index alignment; cost if wrong: a bad history bar in a bootstrap is not flagged). (3) **Which close the check uses:** the VIX-family close on the observation day, else the latest within five days; `src/orchestrator/eod_report.py` now appends the reference closes just **before** the IV capture (the price append otherwise runs after it), so today's IV meets today's index close. Cost if wrong: with no yfinance bar yet, yesterday's close is used and a big VXN jump could mis-flag by up to the band's slack. (4) A vol-index symbol with no VIX/VXN history is never flagged (cannot measure), not flagged-by-default; the first sessions after the merge are unflagged until `backfill_prices` has run. (5) The data alert is sent from sync code: `asyncio.run` when no loop is running, a tracked task when one is (the EOD path); dedupe is a process-local set per (symbol, ET day), so a restart can alert twice in a day. (6) `src/storage/iv_history.py` imports `src.notify.notices` lazily inside `_announce`, an upward import from storage that no fence forbids (G1 green); cost if wrong: none at import time. (7) New config: `risk_limits.yaml -> iv_sanity` (`IvSanityCfg`, `get_iv_sanity_cfg`). (8) Tests: the plan's six plus config, single-name, missing-vol-close, flagged-row-blocks-second-write, storage-reader and old-database-migration tests (12 in total). (9) The API reads `iv_history.flagged` through its read-only session, so the trading service (which adds the column at `init_db`) must restart before the API; STATUS.md and SETUP.md say so |
| Task 10a: the Nasdaq-100 breadth oscillator and the Leveraged Entry Signal (record only) | **done except Step 1's data** (see ruling 1) | c434d5d `feat(regime): Nasdaq-100 breadth oscillator and the Leveraged Entry Signal, recorded` | pytest 5915 passed / 1 skipped (5876 + 39 new), ruff clean, mypy clean (369 files); G1 96 passed, G2 empty, G3 1 passed; `tests/test_regime_limits.py tests/test_breadth.py tests/test_leveraged_entry.py` 71 passed | 2026-11-14 | (1) **Step 1 could not be done as written; per its own text I stopped on it and did the rest.** The Wikipedia Nasdaq-100 article (`https://en.wikipedia.org/wiki/Nasdaq-100`, fetched 2026-11-14, HTTP 200) has **no components table** (sections: History, Methodology, Performance, Closing milestones, Related indices, See also, References, External links; one mention of Nvidia, none of NVDA) and `List_of_Nasdaq-100_companies` does not exist. A fetch of Nasdaq's own constituents API with a browser User-Agent was declined by the permission system and **not retried or worked around**. So `config/breadth_constituents.yaml` is **not in the repo** and no list was invented. Everything that reads it degrades to "no list": `les_state.load_constituents()` returns `[]`, the nightly run then skips the own count (the oscillator runs on the thetrading.tools history alone, and a session that history lacks leaves the washout stale, so the tier stays at the 3% pullback), and `python -m scripts.breadth refresh-constituents` refuses to write unless a page yields 100-102 tickers (tested). **The operator must write the file** (`as_of`, `source`, `ndx: [...]`, 100-102 tickers; Operator to-do 11). Cost if wrong: no forward own-count and no source cross-check until then; the LES still records. (2) `les_signal(bars, osc_recent, cfg)` gained a keyword-only `index: str = ""` (the plan's `LesSignal` carries an `index` the function otherwise cannot know); `LesSignal.asof` is `date | None` (a no-bars result has no date). (3) **Fail closed at 201 bars, not 200:** `sma_trend + break_closes - 1`, so the 200-day average and the 2-close break test are both computable; a series of exactly 200 bars is no signal. Cost if wrong: one session of delay on a brand-new ETF history. (4) **Stale breadth reads as the task's test says, not as L1's prose:** washout needs an oscillator reading **dated the last bar's session**; an older one gives `washout False` and the pullback tier (3.0), not "no signal" (L1 says a count older than one session gives no signal; the task's test, `test_stale_breadth_means_pullback_tier_only`, is explicit). The trend, pullback and trend-break parts never depend on breadth. (5) **The 10-point source gap is measured on RANA (the per-day count level), not on the smoothed oscillator** (L2 says "points" without a scale; with ~100 names one stock moving advancing->declining is 20 RANA points, so 10 flags a real disagreement and tolerates an advancing/unchanged one). Where both sources have a day and differ by more, the day is flagged and our own count is used; otherwise the history (tt) row is kept. (6) `record_signal` updates the row of a re-run for the same (asof, index) instead of keeping the first write, so a later EOD run with fresher breadth wins. (7) The nightly own count needs >= 90% of the constituents to have a close on both of the last two sessions, else it is skipped with a warning; it records only the latest session (idempotent). (8) New provider seams beyond the plan's `BreadthProvider`: a `ClosesProvider` protocol, `factory.get_closes_provider()` and `yfinance_backend.closes()`/`YFinanceClosesProvider` (the plan's `closes(symbols, days=3)`), with `_download_closes` as the one yfinance call, and `get_breadth_provider()`. `tests/conftest.py` gains an autouse `_no_network_for_breadth` (stubs the backend module's `httpx` name and `_download_closes`), so the EOD tests and every other test stay off the network. (9) `load_constituents` lives in `les_state.py` (no new module); the Wikipedia fetch in `scripts/breadth.py` calls `httpx` directly (an operator-run script; the factory rule covers the history feed, and `tests/test_regime_fence.py` asserts no script imports `breadth_backend`). (10) **thetrading.tools:** the feed's shape was checked once by hand on 2026-11-14 (it is `{"data": [{"date", "ndx_advancing", "ndx_declining", ...}, ...], "methodology", "index_members", ...}`, 2,523 rows, 2016-11-01..2026-11-13), which is what the parser reads (a bare list is accepted too). Its own caveat is survivorship: today's members carried back through the history, 98 of 101 listed names with data; recorded in STATUS.md. The personal-use licence is the plan's statement (L2), not something I re-read; attribution is in ARCHITECTURE.md. (11) The Telegram LES line is not built here (Task 14 adds the builder). (12) Tests: `test_breadth.py` 24 and `test_leveraged_entry.py` 13 collected tests (the plan's names plus the feed, constituent, nightly-run and storage tests), and two fence tests in `tests/test_regime_fence.py` (the modules are on the deterministic list; `breadth_backend` is reachable only through the factory), an extension, nothing loosened. (13) `ARCHITECTURE.md`, `SETUP.md` §8, `STATUS.md`, and root `CLAUDE.md`'s regime-family list (breadth, leveraged_entry, les_state, breadth_backend) updated |
| Section C Tasks 8-10, 10a / exit | done (with the Task 10a constituents ruling open) | 465ff29, f60b261, cd59708 and Task 10a's commit (four commits after c8cc0de) | full pytest 5915 passed / 1 skipped = baseline 5855 + 60 new (5 + 4 + 12 + 39); ruff clean; mypy clean (369 files); G1 96 passed; G2 empty; G3 1 passed; `tests/test_regime_limits.py tests/test_breadth.py tests/test_leveraged_entry.py` 71 passed | 2026-11-14 | Open for the operator: `config/breadth_constituents.yaml` (ruling 1 above); the private universe, risk_limits and settings copies (Operator to-dos 2-4, 11); `UNIVERSE_RESEARCH.md` is `docs/archive/UNIVERSE_RESEARCH.md`; the research page's decay warning no longer covers UPRO/DPST (Task 9 ruling 4) |
| Section D entry | done | | Section C exit re-verified by the orchestrator: four commits after c8cc0de, tree clean, full pytest 5915 passed / 1 skipped, G1 96, G2 empty, G3 1, section tests 71, ruff and mypy clean (369 files); `bs_price` anchor at black_scholes.py:48. Baseline for D: 5915 / 369 files | 2026-11-14 | Task 10a's constituents list is missing (Operator to-do 12); the rest degrades as designed. Section D runs as two subagents because the plan's table splits models: Opus for Tasks 11-14, Sonnet (with da-vinci) for Task 15 |
| Task 11: `src/analytics/shock.py`, the pure scenario engine | done | 2f4fd33 (`feat(analytics): the shock engine, gross and net of long options`) | pytest 5931 passed / 1 skipped (5915 + 16 new: 15 in `tests/test_shock.py`, 1 fence test), ruff clean, mypy clean (371 files) | 2026-11-14 | (1) **Not strictly red first:** the engine and its tests were written in one pass and run green together; every named test asserts its behaviour against the final code. Cost if wrong: none. (2) **`BookLine` gained `con_id: int | None = None`** (beyond Step 1's field list) so a line built from live IV can be traced to its contract, and every field after `spot` has a default. Cost if wrong: none. (3) **`ShockResult` gained `unmeasured_net`** beside `unmeasured`: `unmeasured` names what the *gross* measures could not value (gates read it); a long option's missing IV cannot change a gross number, so it is named only in `unmeasured_net`. Cost if wrong: none for gating (H1: long options never enter gross). (4) **Unmeasured lines are left out of the partial sum and named**, not valued at zero and not given an invented worst case; `ShockResult.measured` is False whenever `unmeasured` is non-empty, and every gate (Task 13 `admits`) refuses `envelope_unmeasured`. A missing beta raises `KeyError` inside `name_move` and is caught as unmeasured; NLV <= 0 is unmeasured as `NLV`. (5) **Option sign:** `qty` for an option is read as `|qty|`, the `kind` deciding the sign (stock keeps the broker's sign). At or past expiry, or at a zero spot (a -100% move), an option is valued at intrinsic. (6) **Scenario readings (P5/P6 as I read them):** G10 moves a leveraged ETF by leverage x -10% of its governing index (no beta), non-leveraged names by beta x -10%; P20 compounds `(1 + factor x s)^10 - 1` with `s` the index's equal daily simple step to -20%, factor = beta for a plain name and leverage for a leveraged ETF; T20 moves a plain tech-linked name -20% flat and a leveraged ETF whose own symbol or governing index is tech-linked by leverage x -20%; S-SMH moves a leveraged ETF whose symbol or governing index is in `semis` by leverage x beta_SMH(governing) x -30%, else leverage x beta(governing) x -8%. (7) **A leveraged ETF with no governing index on record** (LABU, TSLL: `envelope.governing` ships only TQQQ and SOXL) moves by the larger loss of its own measured beta x move and leverage x move. Cost if wrong: a slightly larger S10 on those two names if held. |
| Task 12: inputs: betas, stored IV, live IV | done | 4eb4559 (`feat(analytics): shock inputs, betas and live IV`) | pytest 5945 passed / 1 skipped (5931 + 14 new: 8 in `tests/test_shock_inputs.py`, 6 in `tests/test_live_iv.py`), ruff clean, mypy clean (373 files) | 2026-11-14 | (1) **Not strictly red first:** code and tests written in one pass, all green on the first run against the final code. Cost if wrong: none. (2) **`build_inputs` gained keyword-only `spots=`, `beta_map=`, `beta_smh_map=` and `today=`** beyond the plan's signature. An option position's `market_price` is the option's, not the underlying's, so the builder needs a spot: the scan's probes, else the held stock's mark, else the latest stored close; none means the line is unmeasured. The two beta maps let tests and replays skip the price-history read. Cost if wrong: none. (3) **A live IV map never falls back to stored IV** (H7/Q4): the lookup is by `con_id` when the key is present, else by underlying, so a live map (int keys) yields None for a missing contract and the line is unmeasured. (4) **The value book's line** carries `qty = market value / spot`; with no spot on record it is one unit at its market value (stock is linear, so S10 and U_ew are exact either way). (5) **`leverage_map()`** (beyond the plan) is the operator's `leveraged_sizing.leverage` plus any unmapped `universe.leveraged_etfs` name at 3x, independent of `leveraged_sizing.enabled`: physical leverage, so a still-held UPRO lot (out of the universe since Task 9) counts at 3x. Cost if wrong: none. (6) **Betas** use the dates both series share, the last `beta_sessions` of them; the SMH betas (`betas(..., vs="SMH")`) apply the same SOXX proxy (so SOXX's beta to SMH is 1.0 until it has history). A proxied SOXX is not flagged (the fallback is). (7) **`live_iv.py` reads `modelGreeks.impliedVol` only** (no last/bid/ask greeks fallback, as the plan says); a NaN or non-positive IV is None. The chunk size is clamped to at most 10 even if the config allowed more (the config also refuses > 10). Subscriptions are cancelled in a `finally` per chunk. The read writes nothing to `iv_history` (tested). (8) **Config:** `envelope:` block in `config/examples/risk_limits.yaml` with a one-line comment per key; `RiskEnvelopeCfg` validators upper-case `semis_names` and `governing`; `live_iv_batch` is bounded 1-10. (9) `src/analytics/shock_inputs.py` added to `tests/test_regime_fence.py`'s deterministic list (plan Step 4); `src/ibkr/live_iv.py` is not on it (an IBKR module, not analytics; it imports no enrichment). |
| Task 13: `src/engine/envelope.py`, the glide and the measurement record | done | 4ed7255 (`feat(engine): the envelope, its glide and its daily record`) | pytest 5958 passed / 1 skipped (5945 + 13 new in `tests/test_envelope.py`: the plan's ten plus `test_cash_after_every_itm_put_is_assigned`, `test_the_cli_shows_the_snapshot_and_the_glide`, `test_stabilisation_prints_the_three_conditions_and_changes_nothing`; the fence test extended), ruff clean, mypy clean (375 files) | 2026-11-14 | (1) **Not strictly red first:** code and tests written together; one test (`test_max_contracts_under_room_trims`) failed on its own arithmetic (a 590 put at -10% costs 4.5 S10 points, and U_ew bound first) and was re-based to a 520 put and a loose U_ew limit, plus a separate gross-binding assertion. Cost if wrong: none. (2) **`admits` blocks only an opening that raises the measure:** `shock_budget` needs S10_gross after > L(t) **and** after > before (spec §3.4.1: while the book is above L(t) only openings that do not raise S10 pass; without it `test_admits_passes_a_covered_call` cannot pass on a book above its limit). Same rule for `gross_budget` and `t20_budget`. Cost if wrong: none, a non-raising trade adds no risk. (3) **`room` gained keyword-only `may_start` and `result`.** The stored-IV display snapshot passes `may_start=False`, so only the live (gate) measurement ever starts the glide (H7); `result` avoids measuring twice. (4) **Fail closed:** the glide starts only on a fully measured result; `load_glide` uses `get_setting_strict` and raises on an unreadable table or row, and `room` then reports `glide_unreadable` (never restarts the glide over an unreadable record); `on` with no record and an unmeasured book reports `no_glide_record`; reasons carry `unmeasured:<symbol>`. (5) **Start levels never below the targets** (`max(ceil(S10), 15)`, `max(ceil_0.01(U_ew), 1.25)`), and rounding is float-safe (1.36 stays 1.36). Cost if wrong: a book already under target glides at the target from day one. (6) **New key `envelope.t20_trigger_points: 3.0`** (H8's 3.0 points as config, not a literal). `check_t20_trigger` fires on a measured, non-live result only, once: any existing `t20_limit` record (the trigger's or the CLI's) stops it (P11); it reads the **live** measurement only (stored IV is not trusted for a switch). (7) **`t20_limit` on means T20 is tested against the same L(t) as S10** (`EnvelopeRoom.t20_limit = s10_limit`), as H8 says. (8) **Types added in this task:** `EnvelopeSnapshot` (one stored measurement as plain data, for the formatters and the API) and `GlideSpan` in `src/common/envelope_types.py`; the snapshot readers/writer live in `src/storage/envelope_state.py` (`save_snapshot`, `latest_snapshot`, `snapshot_from_row`), `envelope.record_snapshot` calls them. `EnvelopeSnapshotRow` also stores `unmeasured_net`, `nlv`, `cash_after_itm` (E11, computed by `envelope.cash_after_itm_assignment` from `account.total_cash`) and `reasons`. (9) **Wiring (scan step 3d):** after the materiality gate and before the per-symbol pipeline, `_measure_envelope` runs live first (when the switch is not `off`) then stored; it runs on manual `/scan` too, not only the 15-minute loop (Task 19 gates both). Live and stored inputs share the cycle's probed spots. The result is on `ScanResult.envelope_inputs` / `envelope_room` (None when off or on failure: Task 19 must read None as unmeasured while `on`). The hedge book's lines are not passed yet (no `hedge_view` until Task 33). (10) **Scan tests:** no conftest stub was added; every existing scan test runs the step against its mock IB, where the live read fails inside `live_option_ivs` and returns all-None (caught), so the step costs nothing measurable (the 14 scan-path files: 429 passed in 26 s). Cost if wrong: a scan test that does not isolate its DB gets envelope rows wherever it already writes candidates. (11) **`scripts/envelope.py`**: `show` now also prints both latest snapshots and the glide; `stabilisation` reads the regime record's `eased_by_bottoming` per index as the market-level bottoming signal and the newest result file whose id contains `harness` (Task 26 writes `harness.json`), and changes nothing. (12) **Root `CLAUDE.md` not edited:** its regime-family list does not yet name `shock*.py`, `envelope.py`, `envelope_state.py`, `envelope_types.py`; they are on `tests/test_regime_fence.py`'s deterministic list. Left for Task 38's doc sweep. |
| Task 14: Telegram lines and `GET /envelope` | done | 75af220 (`feat(envelope): the daily line, the manual-buy line and GET /envelope`) | pytest 5970 passed / 1 skipped (5958 + 12 new: 5 in tests/test_api_envelope.py, 7 in tests/test_envelope_lines.py), ruff clean, mypy clean (377 files), tsc --noEmit clean, test_openapi_current green; G1 97 passed, G2 empty, G3 1 passed | 2026-11-14 | (1) **Not strictly red first:** code and tests written together; run green against the final code. Cost if wrong: none. (2) **The manual-buy check runs as its own loop in `approval_service`, not inside the ledger sweep.** The first draft added an `after_sweep` callback to `src/ledger/live.py::live_sweep_loop` (and re-based `tests/test_ledger_live.py::test_approval_service_wires_the_ledger_tasks` to the new call); on review that was not required by the task, so both were reverted and `src/ledger/` is untouched. Instead `envelope_manual_buy_loop(ib)` (started and cancelled beside the ledger sweep task) runs every `ledger.live_sweep_minutes` during RTH with the exec connection up and calls `envelope_manual_buy_check(ib)`, which reads the `broker_executions` rows the sweep and the commission hook ingested. Cost if wrong: the line can arrive up to one sweep interval after the sweep that ingested the fill (minutes), never twice. (3) **What counts as a manual buy:** `book="manual"`, `sec_type="STK"`, quantity > 0, `trade_date` = today (ET), an exec id, not superseded; once per exec id (`system_settings` key `envelope_manual_buy_seen`, a JSON list, newest 500 kept). Old rows from a CSV/Flex import are never reported (today only). It needs the ledger to track the account (an import has locked it), as all live ingest does. (4) **Before and after on stored IV** (display, §3.4.1 allows labelled stored IV): after = the book as `get_positions()` shows it now; before = the same inputs with the bought shares taken out of the symbol's non-value stock lines (`envelope.without_shares`, new). Headroom is against the next session's L(t) from the glide, or against the targets (15% / 1.25, labelled "no glide yet") while no glide has started: in `record` mode the would-be limit is the book's own level rounded up, which is not a meaningful headroom. (5) **`format_manual_buy_line` gained keyword-only `s10_limit`, `uew_limit`, `limit_label`** (the plan's signature has no way to state the headroom); `format_les_line(signal, *, index, osc=None)` gained `index` (for the no-signal line) and the breadth reading `osc` (a `LesSignal` carries none); `format_envelope_section(snapshot, les_lines)` is new: the EOD message is MarkdownV2, so the plain-text lines go in one code block (only a backtick and a backslash need escaping there). (6) **Which snapshot the EOD line and `GET /envelope` show:** the latest live-IV one when it is from the same ET day as (or newer than) the latest stored-IV one, else the stored one, labelled. The API also returns both (`live`, `stored`). (7) **`GET /envelope` shape (`RiskEnvelopeResponse`):** `snapshot`, `live`, `stored` (`RiskEnvelopeSnapshot`, every measure gross and net), `limits` (the shown snapshot's limits plus the targets), `enforce`, `glide` (`RiskEnvelopeGlide`: start, end, week, weeks, start levels, today's limits), `switches` (`RiskEnvelopeSwitch`: name, value, default, source, set_at), `cash_after_itm_assignment`, `les` (`RiskEnvelopeLes`, with the newest breadth reading). Unknown is `null`, never 0. Read through the API's trading-DB session only; the switch values use a new pure `envelope_switches.resolve_switch(name, record, *, live)` (and `parse_record`), which `get_switch` now also uses, so the API and the trading process cannot disagree (live reads defaults). (8) **openapi and api-types:** `docs/web/openapi.json` regenerated with the command in `tests/test_openapi_current.py` (there is no command in `docs/web/api.md`, contrary to the brief); `web/lib/api-types.ts` generated with `npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts` from the file, not from a running server (`npm run gen:api` fetches from `127.0.0.1:8787`, the operator's API port). Checked first: generating from the committed openapi.json reproduced the committed api-types.ts byte for byte. `tsc --noEmit` clean. (9) No Telegram command is added, so no command tables change. `docs/web/api.md` gains a Risk envelope section. |
| Section D Tasks 11-14 (Opus) | done | 2f4fd33, 4eb4559, 4ed7255, 75af220 | Orchestrator re-verified: four commits after d935134, tree clean; full pytest 5970 passed / 1 skipped (5915 + 55); ruff clean; mypy clean (377 files); G1 97; G2 empty; G3 1; `test_openapi_current` green; `tsc --noEmit` 0; `src/ledger/`, `src/value/`, `src/spreads/`, `src/execution/` untouched since D entry; shock.py gross paths skip every long option (H1/H10) | 2026-11-14 | The agent hit a rate limit mid-Task 14 and was resumed from its saved state. It reverted an unneeded `src/ledger/live.py` edit and ran the manual-buy check from its own `approval_service` loop instead. `admits` blocks only an opening that raises the measure above L(t) (spec §3.4.1); the Opus whole-branch review should read that against Review Focus 1. Root CLAUDE.md regime-family text for `shock*`/`envelope*` is left to Task 38 |
| Task 15: the envelope card (web; da-vinci) | done | 05588a3 (`feat(web): the risk envelope card on Portfolio`) | vitest 1639 passed across 154 files (baseline 1625 / 153 before this task: +13 in `EnvelopeCard.test.tsx`, +1 in `PortfolioPage.test.tsx`), `tsc --noEmit` exit 0, `npm run lint` no warnings or errors; G4 scratch build passed (16 static pages, `/portfolio` 13.5 kB) and the scratch copy and its `node_modules` symlink were removed; `design_md_check.py web/DESIGN.md` exit 0; `tests/test_web_fence.py` + `tests/test_openapi_current.py` 25 passed; no Python changed | 2026-11-14 | (1) **Not strictly red first:** the tests were written before the component, but the component was written in one pass and the suite ran green on the first run, so red was never observed. Cost if wrong: none (each named behaviour is asserted against the final code). (2) **Hero figures in the display face, not mono.** The two headline readings (S10 gross, U_ew) use Hanken 800 with `.tabular`, as the Account card's hero does (DESIGN.md Typography: the hero number is 800 at every size; Red Hat Mono has no 800); every figure line, the scenario list and the switch list are mono with `.tabular`. Cost if wrong: a one-class change to `font-mono` on `Measure`'s reading. (3) **Limit today is `limits.s10` / `limits.uew` (the snapshot's), with no fallback to `glide.s10_today`.** With no snapshot the limit reads a hatched n/a rather than a glide figure the gate never compared with; target is `limits.*_target`. Cost if wrong: an empty book shows n/a for the limit instead of the glide's value. (4) **"Over limit" is a flag word** when gross S10 or U_ew is strictly above its limit (also while `record`, where the limit is the would-be start-of-glide value); not in the plan text. Cost if wrong: remove two props. (5) **Words the plan left open:** switch labels and value words are a table in `EnvelopeCard.tsx` (`SWITCH_WORDS`); the slow breaker's value is read as a drawdown percent ("Trips at 10% drawdown", per Task 22's "threshold") and `cc_basis_floor` as a share of cost basis; an unknown switch name falls back to its raw name and value. The switches sit in a closed Disclosure ("N of 15 changed from the default"), so they are in the DOM but not on screen until opened. Cost if wrong: a label or word to reword. (6) **The `les` block of `GET /envelope` is not shown** (Task 15 does not ask for it; the Telegram lines carry it). Cost if wrong: a later card or row. (7) **"Unmeasured" flag word and the unvalued symbols** are shown when `measured` is false (beyond the plan), because a gate refuses on it and a card that shows figures without saying they are incomplete would mislead. (8) **Docs:** DESIGN.md gained the Envelope card (Components), a Portfolio Surfaces bullet and a Decision Log entry; `web/CLAUDE.md` names the card in the Portfolio layout entries. No new token, colour, font, radius or elevation; no em dash or banned word in the copy. (9) `PortfolioPage.test.tsx`'s `/envelope` mock was added and one test pins the card's place (after Account, before the view chips); the existing four tests are unchanged. |
| Section D exit | done | 2f4fd33, 4eb4559, 4ed7255, 75af220, 05588a3 | Orchestrator re-verified Task 15: tree clean, no scratch copy or stray symlink left; vitest 1639 passed (154 files, baseline 1625 / 153); tsc 0; eslint clean; `design_md_check` 0; `test_web_fence` + `test_openapi_current` 25 passed; Python unchanged since Task 14's full run (5970 passed / 1 skipped, mypy 377 files) | 2026-11-14 | The card was never looked at in a browser by the agent or by the orchestrator: layout, light/dark and the 390px phone width are unreviewed by eye (operator check after the early merge) |
| Section E entry | done | | Section D exit green (above); `run_capital_release(ib_scan, ib_exec, bot, chat_id)` anchor at approval_service.py:1927. Baseline for E: pytest 5970 / 1 skipped, mypy 377 files | 2026-11-14 | Per the operator's "run all sections to completion" the orchestrator does not stop here, but the plan's early-merge question after Section E is a merge, so it is NOT taken: merge and push are the operator's call and are asked at the end |
| Task 16: `src/hedge/` begins: XND and QQQ menu capture | done | 94bd404 (`feat(hedge): capture XND and QQQ hedge-menu quotes twice a session`) | pytest 6000 passed / 1 skipped (baseline 5970 + 30 new: 25 in `tests/test_hedge_capture.py`, 4 in `tests/test_hedge_fence.py`, 1 in `tests/test_regime_fence.py`), ruff check clean, mypy clean (381 files; ruff format drift in six files I did not touch is pre-existing) | 2026-11-14 | (1) **Not strictly red first:** the code and the tests were written in one pass and run green together; each named behaviour is asserted against the final code. Cost if wrong: none. (2) **The XND `--probe` was NOT run.** `scripts/hedge_capture_report.py --probe` is built (it connects with the healthcheck clientId, qualifies each configured underlying, prints the option chains and contract details, writes nothing) but this session may not connect to IBKR, so XND's fields (`IND` on `NASDAQ`, class `XND`, multiplier 100: the plan's, unverified) are unchecked. This is not a failed probe, so I did not stop. Cost if wrong: a capture that cannot qualify XND logs a warning and records QQQ only, and after 20 sessions H4 falls back to QQQ; the operator should run the probe before the first capture (SETUP.md §20 says so). (3) **Menu mechanics the plan left open.** `build_menu(chain, spot, cfg, *, today)` takes `today` (the plan's signature had none; the DTE needs it). Two steps because the long leg's delta arrives only with its quote: `candidate_strikes` picks up to two expiries in the DTE window nearest 90 days, the listed strikes nearest six long grid points (0.87-0.97 of spot) and below each the listed strike at or beyond 10% and 15% of spot (about 17 contracts per expiry, four or five chunks of ten); `build_menu` then keeps a put with |delta| in `long_delta` and at least 0.15, as an outright and as verticals to every lower same-expiry put at least 10% of spot below. An item with no two-sided price stays on the menu (so the capture records the thin market) with `debit=None` and can never be the default. Cost if wrong: a delta band that the grid misses at very low or very high IV returns a thinner menu. (4) **The default item is a proxy.** `default_item` ranks by the minimum, over the five scenarios, of intrinsic payoff at the scenario's index move per mid-debit dollar (S10 and G10 -10%, S20, T20 and P20 -20%: `menu.SCENARIO_MOVES`); Task 36's size rule replaces it. It is marked at capture (`is_default`), so the report does not re-derive it. Cost if wrong: H4's cost per protected point is measured on a slightly different item than the bridge will buy. (5) **`HedgeQuoteRow` has four columns beyond the plan's list** (`session_date`, `spot`, `leg`, `is_default`) and one row per (item, leg), so a long put shared by several verticals is stored once per item. Cost if wrong: duplicated quote rows (about 30 per instrument per capture). (6) **Where and when the capture runs.** An inline `await run_due_capture(ib_scan, scan_running=...)` in `_intraday_scan_loop` as step 1a'' (after the capital release, before the reconciliation), not a spawned task: the scan is spawned later in the same cycle and a spawned capture would have made that cycle's scan read `scan_running` and be skipped. It is skipped while a scan is running (the capture takes a chain batch's lines), runs while execution is halted (measurement, not an entry), and is bounded by a 240 s timeout (capture of both instruments is about 25-60 s). The slot (`system_settings` key `hedge_capture_last`, `YYYY-MM-DD HH:MM` ET) is marked when the capture starts, so a failure is not retried every cycle; a late restart runs the newest passed slot once. Cost if wrong: one lost sample per failed capture; the first cycle after each slot is about a minute late scanning. The plan's anchor lines (approval_service 1757-1840) are the scan runner; the loop is at 1858-2046 and the entry-check grep matched at 1927. (7) **Config.** `HedgeCfg` has one key beyond the plan's list, `commission_per_contract` (0.65, the IBKR commission the H4 cost comparison adds); every key is in `config/examples/risk_limits.yaml` with its default. The market-data budget check (`Config._spreads_isolated`) now uses `max(chain_batch_size, hedge.capture_max_lines)`, since the capture takes a chain batch's place and never runs beside one. Cost if wrong: none at the shipped defaults. (8) **H4 as computed.** Sessions are the distinct ET dates with any capture row. A leg with no bid or no ask counts as an infinite spread; displayed size is the long leg's ask size (and the short leg's bid size) against `max(needed_contracts, 1)` (the bridge size is 0 until Task 36, so a missing size fails rather than passes); cost per protected point is (mid debit + round-trip half-spreads and commissions) over the intrinsic payoff at S10, a dimensionless ratio with no exchange fees. XND with a passing spread and size but no QQQ cost to compare reads `passed: null`, not a pass. A FAIL with 20 sessions writes `H4_fallback.json`; any later run that does not fail deletes a stale one, because `apply_reports` would otherwise flip a later XND PASS back to QQQ at the next EOD. The report is run by the operator (SETUP.md §20), not from the EOD run. Cost if wrong: the switch waits for a human to run it. (9) **Fence.** `tests/test_hedge_fence.py` (first version: no enrichment import, only `src/hedge/` constructs `HedgeQuoteRow`, no order path or direct market-data call in the package) and `*(SRC / "hedge").glob("*.py")` plus a test on `tests/test_regime_fence.py`'s deterministic list, both extensions. Root `CLAUDE.md` gained the hedge-fence stub (completed in Task 37); ARCHITECTURE.md (config row, `hedge_quotes` row, `approval_service` row, a `src/hedge/` section, the script), SETUP.md §20 and STATUS.md updated. |
| Task 17: SPXW wing capture in shadow, and the E3 cost report | done | a786404 (`feat(spreads): capture SPXW wing quotes in shadow for the E3 cost test`) | pytest 6021 passed / 1 skipped (Task 16's 6000 + 21 new: 20 in `tests/test_spxw_capture.py`, 1 wiring test added to `tests/test_hedge_capture.py`), ruff check clean, mypy clean (382 files), G1 102 passed, G2 empty, G3 1 passed | 2026-11-14 | (1) **Not strictly red first:** code and tests were written in one pass and run green together (one test, the E3 notice, failed on the first run and drove the `apply_reports` change); each named behaviour is asserted against the final code. Cost if wrong: none. (2) **One module the plan's file list lacks:** `src/spreads/wings.py` (pure planner: `plan_leg`, `WingPlan`, `WingCapture`, the CBOE / XSP constants); `service.py` and `store.py` stay thin. Cost if wrong: none (ARCHITECTURE.md names it). (3) **The wing's distance:** short strike = the SPY candidate's short strike divided by the SPY/index ratio (`levels.scale` for SPXW, `scale x 10` for XSP), snapped to a listed strike **at or beyond** it (never closer to spot than the SPY leg), long strike exactly `width` index points further out and it must be listed, else no wing for that width. That equals the same distance in expected moves to within one strike step, because the expected move scales the same way; `scale` is the map's, refreshed hourly, so no extra index subscription is spent on a live SPX spot. Cost if wrong: a wing up to one strike step (5 SPX points) further out than the SPY leg. (4) **When it runs.** After the entry decision, never before (the picker path mirrors its baseline item, the non-picker path the first candidate per side), on every entry check that builds one (not once per episode), bounded by a 25 s timeout, log-only on failure; the service calls `broker.wing_strikes` / `broker.wing_quotes` only when the broker has them (`hasattr`), so the `Broker` Protocol and every existing fake are unchanged. SPX/XSP strike lists are cached per (symbol, expiry) for the process. Cost if wrong: a few seconds of manage-tick delay per capture (about 3-8 s for six lines). (5) **XSP's symbol, class and the CBOE exchange are constants** in `wings.py`, not config keys (the plan's key lists only `xsp_width`); `wing_strikes` falls back to any class of the symbol that lists the expiry if the configured class does not, which covers XSP's dailies sitting under a weekly class. Cost if wrong: XSP wings not captured until the class is known (SPXW unaffected). (6) **Line budget:** six leg quotes per capture (4 SPXW, 2 XSP) go through the broker's existing `quote`, which opens at most `max_market_data_lines` (30) at once and cancels each batch (tested with 70 strikes and with a real six-leg capture). (7) **Row and sizes:** `SpreadWingQuoteRow` is one row per wing spread (both legs) and carries the SPY candidate's width, `credit_mid`, `credit_natural` and the GEX `scale`, so the report needs no join; displayed sizes are not captured (`ChainOption` carries none and the E3 test needs crossing only). (8) **The cost model:** all-in round trip per spread = 2 x (full mid-to-natural crossing) x 100 + 4 x (commission + exchange fee) per contract, over max loss (width - credit_mid) x 100, times 1,000; SPY's is computed from the same captures' denormalised candidate. The full crossing (not the shadow haircut) in and out is charged to every instrument alike, conservative and like-for-like. A leg with no bid or ask is an infinite cost (cannot trade); an unknown exchange fee blocks that instrument (the SPXW and XSP fees ship `null`, so the report cannot pass until the operator fills them). The SPXW test is the widest configured width (25). Cost if wrong: a wing looks dearer than it would fill. (9) **Verdicts:** PASS (SPXW, else XSP) needs cost <= SPY over >= 15 sessions **and** `spreads_paper.json` passed (`passed: null`, not a fail, while the paper bar is pending or sessions or fees are missing); `passed: false` / `value_on_pass: "stay"` only when both candidates are measurable and both fail. XSP is considered only when SPXW does not pass. (10) **`scripts/spxw_cost_report.py` inlines the one-line exchange-fee lookup** instead of importing `src.spreads.menu`, because `tests/test_spreads_fence.py` lets only the spreads scripts import `src.spreads` and a fence is only ever extended by an allowance the task names. (11) **Task 1 code changed:** `envelope_switches.apply_reports` words the `spxw_ready` notice as "E3 PASS: spxw_ready -> spxw. Run Task 39 of the risk-envelope plan at a flat-book cutover. Nothing else changes." (the generic "(paper; record-only in live)" text would be wrong for the live-exempt verdict). (12) Docs: ARCHITECTURE.md (spreads config, store, chain, service, `wings.py`, `envelope_switches`, the script), SETUP.md §20 (and the fee to-do), STATUS.md. 20 tests in `tests/test_spxw_capture.py` (the plan's seven names plus config, planner, failure-never-blocks, no-hooks, strike-fallback and report-reads-the-db tests). (13) Beyond Task 17, one test was added to Task 16's `tests/test_hedge_capture.py` (`test_the_intraday_loop_calls_the_capture_after_the_capital_release_and_before_the_scan`, a source-order check of the loop wiring that the first commit lacked); Task 16's file therefore holds 26 tests. |
| Section E exit | done | 94bd404, a786404 | pytest 6021 passed / 1 skipped = baseline 5970 + 51 new (30 in Task 16, 21 in Task 17); ruff check clean; mypy clean (382 files); G1 102 passed (the seven fence files plus `tests/test_hedge_fence.py`; baseline 97); G2 grep prints nothing; G3 1 passed | 2026-11-14 | Two commits after fbf32fd. Owed to the operator: run `python -m scripts.hedge_capture_report --probe` on the paper Gateway before the first capture (XND's contract fields are the plan's, unverified); fill `execution.exchange_fees.SPXW` and `.XSP` in the private `spreads.yaml` before the E3 report can decide; run `scripts.hedge_capture_report` after 20 capture sessions and `scripts.spxw_cost_report` after 15. The early-merge question is the orchestrator's Orchestrator re-verified (2026-11-15): two commits after fbf32fd, tree clean; full pytest 6021 passed / 1 skipped on a second run; ruff clean; mypy clean (382 files); G1 102 passed (incl. test_hedge_fence); G2 empty; G3 1 passed; no order path in `src/hedge`, `src/spreads/wings.py` or the two report scripts. |
| Early merge (A-E) | not taken | | The operator's instruction was "run all sections to completion", which does not include a merge; merge and push are asked at the end (memory: ask before merging or pushing) | 2026-11-15 | The capture clocks (20 sessions H4, 15 sessions E3) and the record sessions start only once the daemons run this code, so every day before the merge delays them. Operator to-dos 1-4, 11, 12 and the XND `--probe` come first |
| Section F entry | done | | Early-merge row filled (not taken); Section E exit green; the A2 anchors print (risk_engine.py:527, :542; regime_limits.py:188; spreads/service.py:830; reconciliation.py:482). Baseline for F: pytest 6021 / 1 skipped, mypy 382 files | 2026-11-15 | A first full run at Section E exit showed 2 failures in `tests/test_write_path_invariants.py` (the promote-drain tests): `tests/test_drain_promote.py:38` fixes `_EXPIRY = date.today() + 24 days` at import while the fake chain recomputes `date.today()` at call time, so a run that collects before midnight and executes after it gets `contract_not_priced`. Pre-existing midnight-crossing test flake, not Section E; both pass alone and in the post-midnight full run. Cost if wrong: none; a fix (a frozen date) is a later hygiene item |
| Task 18: the erasure fix, U_ew in place of the nominal check, leverage weighting | done | cb55ddd (`fix(engine): no reason erased by a floor lot; U_ew replaces the nominal gross check`) | full pytest 6032 passed / 1 skipped = baseline 6021 + 11 new (10 in `tests/test_regime_sizing_integration.py`, 1 in `tests/test_capital.py`); the first full run had 2 failures, both tests pinning the wheel's old nominal gross cap, re-based (ruling 7) and re-run green with their files (78 passed); ruff clean; mypy clean (382 files) | 2026-11-15 | (1) **Red first, partly:** the code was written first and the named tests run against it; the C1 test (`test_combined_name_cap_survives_the_regime_rewrite`) reproduces the erasure path (combined cap -> `regime_budget` -> floor clear) that the old code took. Cost if wrong: none. (2) **What Task 18 wires vs Task 19:** `validate_candidates(..., envelope=(room, inputs))` passes every reason `envelope.admits` returns (`gross_budget`, `shock_budget`, `t20_budget`, `envelope_unmeasured`); Task 18's tests drive `gross_budget`, and Task 19 supplies the live-IV room and inputs from the callers (read of "Task 19 supplies S10; this task wires `gross_budget`"). Cost if wrong: none (the gate code is the same). (3) **The candidate's line** needs the option's own IV and the spot, which `TradeCandidate` did not carry: two new optional fields, `quote_iv` (decimal, the quote's IBKR IV, `OptionQuote.iv`) and `underlying_price` (the scan's spot, else the quote's `undPrice`), set by the CSP generator; `envelope.candidate_line` builds the short-put `BookLine` and `envelope.with_added` adds an accepted lot to the batch's book. `OptionQuote.iv` can be Yahoo's IV on the rare path where IBKR valued nothing (delayed-data paper account): the candidate's own increment then uses it. Cost if wrong: on that path a candidate's S10 increment is priced at Yahoo's IV; the book's lines stay on live IBKR IV. (4) **Envelope modes in the gate:** `on` appends; `record` writes `sizing_actions` kind `envelope_record` (key = candidate id, one row per card per day, reason names the measures and the limits) and admits; `off` nothing. With **no envelope** the switch is read once (only when a CSP reaches the shared budgets): `on` refuses `envelope_unmeasured`; `record` records nothing (no measurement to record; the scan's measurement failure is logged). Cost if wrong: a total measurement failure in `record` mode is not in the P1 defect count (an unmeasured *room* is: `admits` returns `envelope_unmeasured` and that is recorded). (5) **In `record`, a lot the envelope would refuse is not added to the batch's book**, so later lots are measured as `on` would measure them. Cost if wrong: none for orders (record never refuses). (6) **Leverage weighting is narrower than "scale `unit_collateral`":** the lot's exposure is weighted in the per-ticker collateral tally (so the large slot), and the CSP budget; the cash it uses (`deployable_cash`, `cash_used`) and its risk units are at face (spec §3.5: "Risk units already scale through IV"; cash is real dollars). `leverage_of` is `leverage_factor(sizing, name) or 1` (so it follows `leveraged_sizing.enabled` and is 1 without a sizing context), passed by the gate, the generator and `regime_limits.scaled_budget_fit`; `scripts/capacity_report.py` is unchanged (no context). A held leveraged position above a third of the per-ticker cap now occupies a large slot. Cost if wrong: one fewer large slot while a leveraged name is held big. (7) **Existing tests re-based, none weakened:** `test_regime_sizing_integration.py`'s four TQQQ generator tests use a $40 strike (`TQQQ_STRIKE`, ten lots fit at 3x), so they still test only the leveraged ceiling (at $50, ten 3x lots are $150k against the $125k large ceiling and capital allows 8); `test_regime_send_time.py::test_leveraged_tier_never_loosens_at_send_time` runs on a $2M account (five $185 lots at 3x need it); `test_value_capital_release.py::test_the_gross_cap_counts_both_books_and_approved_buys` became `test_the_wheel_gate_no_longer_applies_the_nominal_gross_cap` (it pinned the removed check; U_ew's both-books count is tested in the integration file); `test_reason_labels_value.py` no longer requires the wheel's engine to raise `gross_notional_cap` (asserts it does not; the words stay in both maps for the value book). (8) The removed wheel check took its `wheel_stock`/`gross_cap` locals with it; the reason words for `gross_notional_cap` stay (the value book's cards). Four new reason words in both maps. (9) Tests beyond the plan's eight: `test_an_accepted_lot_joins_the_book_for_the_next_candidate`, `test_no_envelope_while_enforce_is_on_fails_closed`, `test_an_unmeasured_candidate_line_is_refused` |
| Task 19: S10_gross <= L(t) at the generator, the gate and send time | done | 59d2914 (`feat(engine): the shock budget gates every risk-adding open, twice`) | full pytest 6049 passed / 1 skipped = 6032 + 17 new (14 in `tests/test_envelope_gate.py`, 3 in `tests/test_regime_send_time.py`); ruff check clean; mypy clean (382 files); `ruff format` touched files only (four files I did not touch carry pre-existing format drift; two `src/api/routers` files a broad `ruff format src` reformatted were reverted) | 2026-11-15 | (1) **Not strictly red first:** the plan's nine tests were drafted before the wiring and run against it; they passed on their first run. Cost if wrong: none (each asserts its behaviour). (2) **The Rules Engine writes nothing (changes Task 18's record path).** Task 18's gate wrote `envelope_record` rows itself; inside the order poll's write session that second session deadlocked on SQLite's write lock (a 30 s test timeout showed it). The gate now returns the would-block reasons on `RiskVerdict.envelope_would` (new field) and the callers write them with `regime.actions.record_envelope_verdicts(..., where=, session=)`: the scan (`:scan`, `:ticker_scan`) and the poll inside its own session (`:send_gate`). The generator (`:generator`) and the executor (`:send`) write directly (no outer session). Rows are keyed `<candidate>:<where>`, so the five places never overwrite each other; the gate's rows carry `sent_contracts = 0` (what `on` would send). Cost if wrong: none; Task 18's path could not deadlock in production (the poll passed no envelope until this task). (3) **Fail closed on unreadable state (Review Focus 3), beyond the plan:** `envelope_switches.enforce_mode()` reads `envelope_enforce` with the strict settings reader; an unreadable table or an unparseable record reads `on` in paper (the plain `get_switch` would read the `record` default and admit); live reads the default. `envelope.room`, the gate, the executor, the order poll and the scan use it. Cost if wrong: a settings-table outage refuses every new put in paper until it reads again. (4) **`max_contracts_under` is a binary search** (Task 13 counted up): admission of a short line is monotone in its size, so the result is identical and the generator's per-strike trim costs about four measurements instead of up to ten. Task 13's test passes unchanged. (5) **Generator:** the trim runs only for a strike with no other reason (a rejected strike is not measured), after the regime ceiling; a lower count goes on the `SizingNote` (`envelope_from`, `envelope_binding`, new fields) and the card says "risk envelope: S10" / "U_ew"; zero lots rejects with the binding reason (the displayed count stays the pre-trim size, which the gate also refuses). With no `SizingNote` (no sizing context) the trim still applies but is not noted. (6) **Callers:** the full scan passes the cycle's live room to `scan_symbol` (new `envelope=`) and its gate; the `/scan TICKER` deep-dive and its promote measure with `_measure_envelope` (the ticker's spot) and pass it to their screen and gate; the roll pipeline passes `envelope=None` explicitly (rolls are never tested). `test_every_production_caller_passes_the_envelope` makes the keyword mandatory at every call of `validate_candidates`, `screen_csp_candidates`, `screen_csp` and `scan_symbol` (like the sizing test). (7) **Send time:** `approval._send_envelope` measures only when a CSP is queued, before the write session (live IV on the poll's `ib`; value holdings via `books.value_exposure`; may start the glide when `on`, as the scan's live measurement may); each put handed to the executor carries the puts sent before it in the book (`envelope.with_added` at the card's IV). The executor re-prices the put's own line at the fresh quote's IV and `undPrice` (never the card's IV) and folds the reasons into the live re-gate verdict, so the refusal path, Telegram text and order detail are the existing ones plus S10/U_ew against their limits. (8) **Existing tests changed (signatures and one harness stub, nothing weakened):** `tests/test_execution.py` mocks of `validate_candidates` / `execute_candidate` accept `envelope=None`; `tests/test_regime_send_time.py`'s `fake_execute` accepts it and its autouse fixture stubs `approval._send_envelope` to None (that file tests the regime; without the stub its MagicMock IB yields an unmeasured room and record-mode rows that its exact `sizing_actions` assertions would count); `tests/test_regime_sizing_integration.py`'s record-mode test now asserts the verdict carries the reasons and the gate writes nothing, then records through `record_envelope_verdicts`; its fail-closed test patches `enforce_mode`. (9) Tests beyond the plan's nine: generator zero-lot rejection, generator record mode, the line the gate builds, every caller passes `envelope=`, unreadable switch fails closed, and three order-poll tests (gate on the send-time envelope, the executor sees earlier puts, record mode writes in the poll's session) |
| Task 20: value-book buys under the envelope | done | a60d41a (`feat(value): value-book buys pass the shock budget and U_ew`) | full pytest 6063 passed / 1 skipped = 6049 + 14 new (7 in `tests/test_value_risk.py`, 3 in `tests/test_value_capital_release.py`, 2 in `tests/test_value_fence.py`, 2 in `tests/test_value_stage3.py`); ruff clean; mypy clean (382 files); `tests/test_value_fence.py` 28 passed (the `sys.modules` probe unchanged) | 2026-11-15 | (1) **Not strictly red first:** code and tests were written together; every named test asserts its behaviour against the final code. Cost if wrong: none. (2) **The room arithmetic moved, not copied:** the body of `engine.envelope.room` is now `storage.envelope_state.room_for(result, *, enforce, t20_on, today, may_start)`; `room` calls it, and `stage3` calls it without importing `src.engine` (C8). Task 13's tests pass unchanged. Cost if wrong: none. (3) **`uew_per_dollar` beside `s10_per_dollar`** (the plan names only the latter): U_ew needs the name's leverage / NLV, which the pure gate cannot look up. Both rates are per symbol on a `risk.ValueEnvelope` (new: the room plus the rates; `after_buy` adds a filled buy so the next buy in the cycle sees it), built in `stage3.value_envelope` from `shock.name_move` (S10 scenario, so a leveraged name is leverage-capped as the wheel's engine moves it) and `shock_inputs.leverage_map` via the inputs. A pending buy symbol with no beta is given the Blume fallback by `betas()` (flagged), never zero. (4) **Comparison rule = `admits`'s:** refused only when the measure ends above its limit and the buy raises it (a buy always raises both). **T20 is not tested** for a value buy (the plan's three reasons); cost if wrong: once `t20_limit` is on, a tech-heavy value buy could raise T20 above L(t) while S10 and U_ew pass. (5) **Record mode records in value.db, not `sizing_actions`:** the value fence keeps `src/value/` off the wheel's tables (CLAUDE.md: it may read `src.common.books` and nothing else of the wheel; P1 says `sizing_actions`). The would-be refusals are kept on the proposal's `gate_json` with an `envelope_record:` prefix (only `live._buy` and `book.propose` write that column; nothing reads it back as a refusal) and logged. Cost if wrong: the P1 review reads value buys from `value_proposals.gate_json`. (6) **Fail closed:** `on` with no glide record is unmeasured for the value book (it never starts the glide; the wheel's live measurement does), so value buys wait until the wheel's first live scan after the switch turns on; any measurement failure while not `off` is an unmeasured room (refuses in `on`, recorded in `record`). The switch is read with `enforce_mode()` (Task 19). The night's decision-time gate has no envelope (no live IV at night); the RTH cycle's send-time gate is where it applies (the plan's "same room at send time": the value book's only send is inside `cycle`). (7) **The envelope is measured only when a buy is pending** (`pending_buy_symbols`, approved or funding), so a quiet cycle opens no market-data lines; the live IV read is `live_option_ivs` on clientId 31 (at most ten lines at a time). (8) **Fence (Step 3):** `tests/test_value_fence.py` gains `test_stage3_may_import_the_shock_engine` (the five modules are imported by `stage3.py` only, inside functions; no other value module imports them; `risk.py` imports only `src.common.*`, including the plain `envelope_types`) and `test_value_still_imports_no_engine` (no value module and none of the five allowed modules imports `src.engine`). An extension; nothing loosened. **Root `CLAUDE.md`'s value-fence bullet was not edited** (the section-F brief: do not rewrite fence sections, Task 38 sweeps them); it must name the allowance: `stage3.py` may import `src.analytics.shock`, `src.analytics.shock_inputs`, `src.storage.envelope_state`, `src.storage.envelope_switches` and `src.ibkr.live_iv` lazily, and `risk.py` `src.common.envelope_types`. Owed to Task 38. (9) `src/value/cards.py` gains words for the three reasons. Tests beyond the plan's seven: a buy inside the envelope passes (pure and in a cycle), the record-mode cycle funds as before, `after_buy`, and two `value_envelope` tests (whole-book measurement, off / no buys / failure) |
| Task 21: the index collateral class | done | 55c9719 (`feat(engine): one broad-index lot up to 15% of NLV without a large slot`), the last of Section F: its hash is in the orchestrator's Section F exit row | full pytest 6068 passed / 1 skipped = 6063 + 5 new (4 in `tests/test_capital.py`, 1 in `tests/test_regime_sizing_integration.py`); ruff clean; mypy clean (382 files); G1 104 passed; G2 empty; G3 1 passed; sizing suites (`test_engine`, `test_regime_sizing_integration`, `test_capital`, `test_regime_limits`, `test_regime_send_time`) 262 passed | 2026-11-15 | (1) **Not strictly red first:** the four named tests were drafted before the code and run against it. Cost if wrong: none. (2) **"Holds no position yet"** is read as the name's cumulative collateral tally before the lot being 0 (no stock, no short put, no value-book holding of it, no lot accepted earlier in the batch); `index_lot` is the one predicate `_fits`, `charge`, `seed_budgets` and the gate's `_cumulative_reasons` share. A held index-class lot within the cap is **not seeded as a slot** (so it takes no slot while held, and a second lot must find a free one, which `charge` then marks). Cost if wrong: a held QQQ lot over 10% used to occupy a slot; now it frees one for another name. (3) **The no-IV raw-collateral fallback** (`ticker_collateral` / `concentration_limit` at `max_collateral_per_ticker_pct`) also yields to the index cap for that first lot; otherwise the class could not reach 11% whenever IV is missing (the order-approval re-gate seeds no IV). Cost if wrong: one index lot between 10% and 15% passes the fallback with no risk-unit check (the CSP budget, cash, sector and the envelope still apply). (4) **Config:** the portfolio block is a raw dict (no pydantic class), so the defaults live in `resolve_caps` (`broad_index_etfs` absent = no class, `broad_index_etf_collateral_pct` 15.0); the example ships `[QQQ]` and 15.0 with comments. The operator's private `risk_limits.yaml` needs both keys (STATUS, SETUP's portfolio table). (5) Beyond the plan's four tests: `test_the_gate_grants_the_index_lot_as_the_sizer_does` (gate and sizer agree; SMH needs a slot at the gate too) |
| Section F exit | done | cb55ddd, 59d2914, a60d41a, 55c9719 | Orchestrator re-verified (2026-11-15): four commits after 0ed76c6, tree clean; full pytest 6068 passed / 1 skipped (6021 + 47); ruff clean; mypy clean (382 files); G1 104 passed; G2 empty; G3 1; sizing suites (`test_engine`, `test_regime_sizing_integration`, `test_capital`, `test_regime_limits`, `test_regime_send_time`) 262 passed. Read the `risk_engine.py` diff: `hard_reasons` (envelope reasons and `combined_name_cap`) are appended after the `regime_budget` rewrite and after the floor-lot clear (P4/C1); an absent envelope with the switch `on` refuses `envelope_unmeasured`; the gate writes nothing, callers record `envelope_would`. Fence extension (`test_value_fence.py`: stage3 may lazily import the five envelope modules, risk.py the plain types, `src.engine` still forbidden) read and accepted: additions only | 2026-11-15 | Existing tests re-based (TQQQ strikes/account size for the leverage weighting, the removed nominal gross check, mock signatures) and none weakened; the Opus whole-branch review should re-read `max_contracts_under`'s binary search, the poll-gate live-IV measurement and `enforce_mode`'s strict read. Root CLAUDE.md's value-fence bullet (Task 20 Step 3) is left to Task 38 |
| Section G entry | done | | Section F exit green (above); `def admits` anchor present in `src/engine/envelope.py`. Baseline for G: pytest 6068 / 1 skipped, mypy 382 files | 2026-11-15 | |
| Task 22: the slow drawdown breaker spanning books | done | 203ed92 (`feat(breakers): a 20-session drawdown breaker across books`) | full pytest 6074 passed / 1 skipped (baseline 6068 + 6 new in `tests/test_circuit_breakers.py`); ruff check clean; mypy clean (383 files); ruff format on touched files only | 2026-11-15 | (1) **Not strictly red first:** code and tests were written in one pass and run green together (the six tests assert every named behaviour); cost if wrong: none. (2) **`resolve_caps` stays pure:** the plan says `resolve_caps` multiplies the CSP budget while tripped, but the module is documented as no-I/O, so it takes `csp_fraction: float = 1.0` and the three sizing callers (the generator, `validate_candidates`, `regime_limits.scaled_budget_fit`) pass `storage.slow_breaker.csp_budget_fraction()`; `scripts/capacity_report.py` does not pass it, so that report shows the unscaled budget. Cost if wrong: the report overstates the budget while tripped. (3) **The fraction reads 1.0 when the `slow_breaker` switch is off** even if the key says tripped (so turning the switch off frees the wheel), while the spreads service reads the key regardless of the switch (Task 3's reader, unchanged) and stays stopped until a human resets. Cost if wrong: spreads stay blocked after the switch is turned off until `reset-slow-breaker`. (4) **Window restarts at a human reset** (not in the plan): the high is taken over the sessions since the reset (at least one), otherwise a book still under its old 20-session high would re-trip within one cycle of the reset and the reset would do nothing. Cost if wrong: a drawdown that continues from before the reset is measured from the reset day's high, not the old one. (5) **A second evaluation site:** besides the order poll (`approval.process_queued_orders`, where `evaluate_breakers` runs, and which only runs with a queued order and not while halted) the scan evaluates it right after it fetches the account, so a trip reaches the spreads book without a queued wheel order. Whichever call trips it notifies; the other returns None. Cost if wrong: one extra DB read per scan. (6) **Fail closed:** an unreadable or unparseable state with the switch on reads as tripped for the wheel's budget (`is_tripped`), while `trip()` refuses to write over state it could not read. (7) **Not built:** spec §3.4.5's 'demotes every risk-changing Claude rung to record-only' (the Mastermind rungs do not exist yet); the plan's text names only the CSP budget and the spreads entries. |
| Task 23: the leveraged sleeve | done | 376bd07 (`feat(regime): the leveraged sleeve, LES-tiered, behind its switch`) | full pytest 6094 passed / 1 skipped (6074 + 20 new in `tests/test_leveraged_sleeve.py`); ruff check clean; mypy clean (383 files) | 2026-11-15 | (1) **Switches and LES facts ride on `SizingContext`** (new fields `switches`, `les`, `sleeve_below_trend`, `sleeve_recent`, `csp_fills_by_name`, filled once by `build_sizing_context`, scan and send time) so `regime_limits` stays pure and the generator, gate and send-time re-gate read the same values; the plan's `sleeve_tier(ctx, symbol)` reading `les_signals` directly would have put a DB read in every quote. Cost if wrong: none; a context built by hand needs the fields. (2) **`sleeve_lot` and `per_trade_cap` take the card's note** (`frozen`) so the below-trend path at send time (no bars) reads the tag frozen on the card (`SizingNote.sleeve`), like `vrp_waiver`; `tests/test_regime_limits.py::test_a_sleeve_lot_keeps_the_leveraged_ceiling` re-based: its `sleeve_lot` stub lambda gains the `frozen=None` parameter (signature only, same assertions). A sleeve lot keeps the legacy leveraged ceiling (calm 6) as a ceiling; the size is the room. (3) **Bottoming condition:** 'the name's or the governing index's bottoming signal' is the name's ladder signal (`ctx.name_bottoming`) or its bucket's market-level flag (`market_bottoming`): the governing index has no signal of its own, and a name with no position has no zone. Cost if wrong: the below-trend path rarely opens for a name the account does not hold. (4) **IV rank (condition 3) is the candidate's own** (`iv_rank`), unknown fails closed, below-trend path only. (5) **A signal older than 5 calendar days is dropped** (a constant in `regime/context.py`, not in the plan): fail closed on a stale signal. (6) **Pace** counts any CSP order on a leveraged name (sent, working, and queued at decision time) inside 3 sessions, and 'open' counts distinct short-put contracts; **cap** is not accumulated across the generator's symbols (only the gate accumulates a batch). Cost if wrong: two names could each be sized to the whole room by the generator; the gate refuses the second. (7) `books.les_exposure()` is a stub returning nothing until Task 32a. (8) Tests were written after the code and ran green together, not red first. |
| Task 24: `index_1x` multipliers and the T20 limit | done | 80d6985 (`feat(regime): the index-class multipliers and the T20 limit behind their switches`) | full pytest 6101 passed / 1 skipped (6094 + 7 new in `tests/test_index_1x_and_t20.py`); ruff check clean; mypy clean (383 files) | 2026-11-15 | (1) **Both multipliers follow the class table** for an index name (the name's `ticker` multiplier and the `book` one, the total CSP allocation): the plan says only 'multipliers() uses it'; leaving `book` on the old SPY table would keep throttling the index put through the CSP budget in exactly the stress it is meant to lean into. Cost if wrong: the book multiplier eases for an index put only, which can let one QQQ lot past a shrunk total budget. (2) **The record is written by the generator only** (kind `index_1x_record`, `deterministic_contracts` = proposed size, `sent_contracts` = the would-be size, as `envelope_record` does), not by the gate. (3) **Class table validated:** only the class `index_1x` is accepted, values in [0, 1]. (4) **T20:** no code change, as the plan says; `test_t20_limit_gates_only_when_on` drives `envelope.room` with the real switch through the gate and the generator. (5) Tests written after the code, green together. |
| Task 25: the tech-linked cap and the stacking rule | done | 5849bf8 (`feat(engine): the tech-linked cap and the stacking rule, behind their switches`) | full pytest 6111 passed / 1 skipped (6101 + 10 new in `tests/test_tech_cap_stacking.py`); ruff check clean; mypy clean (383 files) | 2026-11-15 | (1) **Tech exposure reads the budgets' own per-name tally** (`Budgets.ticker_collateral`: stock market value plus short-put strike x 100, leverage-weighted, the value book's stock added), summed over `regime.tech_linked`, so a lot accepted earlier in a gate batch counts; the plan's 'stock MV + short-put strike x 100' is the same measure. It also carries any other position the tally measures at market value (a long option, a short call's small value). Cost if wrong: a few dollars of option value in the tally. (2) **Halving is rounded down and a one-lot size is refused** (`stacking_halve`), never rounded up; the plan says 'halve or block'. The gate cannot know the generator's pre-halving size, so it refuses a card above half of `min(card's pre_regime_contracts, per-trade ceiling)`; the generator halves its own (never larger) size, so what it proposes always passes. Cost if wrong: a card made before the switch was turned on, bigger than half, is refused `stacking_halve` at send time. (3) **Short puts only** count as 'an open short' (a covered call is not stacking); an ITM short is a put with strike above the spot (the card's `underlying_price`, else the zone's; unknown spot judges none). Same-day fills count only sent (submitted, partial, filled) CSP orders, not queued cards. (4) **Off-mode records:** the gate's `RiskVerdict.limits_would` (new field) is written by `record_envelope_verdicts` as `tech_cap_record` / `stacking_record` rows (key `<card>:<where>`), the generator's as the same kinds keyed `<card>:generator`. (5) **Reasons go on the card as `limit_from` / `limit_binding`** (new `SizingNote` fields, also used by `sleeve_cap`). (6) Tests written after the code; the first run's four failures were fixture arithmetic (the test card had no IV, so the raw-collateral fallback refused it; the stacking baseline ignored the existing short's collateral), fixed in the tests, not the code. |
| Section G exit | done | 203ed92, 376bd07, 80d6985, 5849bf8 | full pytest 6111 passed / 1 skipped = baseline 6068 + 43 new (6 + 20 + 7 + 10); ruff check clean; mypy clean (383 files); G1 104 passed (the eight fence files); G2 grep prints nothing; G3 1 passed; sizing suites (`test_engine`, `test_regime_sizing_integration`, `test_capital`, `test_regime_limits`, `test_regime_send_time`, `test_circuit_breakers`) 289 passed | 2026-11-15 | Existing tests re-based: `tests/test_regime_limits.py::test_a_sleeve_lot_keeps_the_leveraged_ceiling` (its `sleeve_lot` stub lambda gains `frozen=None`, signature only). Four commits after 44bdd93. Owed to the operator: the private `risk_limits.yaml` needs the new keys added by hand (`envelope.slow_breaker`, `envelope.tech_cap_pct`, `envelope.stacking`, `leveraged_sizing.sleeve`, `regime.csp.budget_multiplier_by_class`); the code defaults match the example, so nothing changes until a switch is turned on. Orchestrator re-verified (2026-11-15): four commits after 44bdd93, tree clean; full pytest 6111 passed / 1 skipped on my own run; ruff clean; mypy clean (383 files); G1 104; G2 empty; G3 1; sizing suites (incl. `test_circuit_breakers`) 289 passed; `slow_breaker_tripped` is written by `src/storage/slow_breaker.py` and read by `src/spreads/service.py` under the same key, and an unreadable row reads tripped. |
| Section H entry | done | | Section G exit green (above). Baseline for H: pytest 6111 / 1 skipped, mypy 383 files | 2026-11-15 | Section G ran across a rate-limit stop; the agent was resumed from its saved state with Task 22 committed and Task 23 mid-edit. Owed to the Opus review: the `scan.py` second evaluation site for the slow breaker, the window restart after a reset, and `resolve_caps(csp_fraction=...)` (`scripts/capacity_report.py` shows the unscaled budget while tripped) |
| Task 26: the survivability harness | done | (this task's hash is filled in Task 27's commit) `feat(reporting): the survivability harness` | full pytest 6125 passed / 1 skipped (baseline 6111 + 14 new in `tests/test_survivability.py`), ruff clean, mypy clean (385 files); the 14 include the plan's six names, the P1 defect rules, the reader on a synthetic DB (hash-checked read-only) and the script end to end | 2026-11-15 | (1) **Not strictly red first:** tests and code were written in one pass and run green together (one test data fix after the first run); each named behaviour asserts against the final code. Cost if wrong: none. (2) **One module beyond the plan's file list:** `src/reporting/replay.py` (read-only SQL readers, `strike_for_delta`, `worst_drawdown`, the result writers) is shared by Tasks 26-29a so no replay carries its own copy; ARCHITECTURE.md lists it. Cost if wrong: none (root CLAUDE.md's `src/reporting/` mention is Task 38's). (3) **What the two paths are (the plan names "today's book revalued daily (the unenveloped path)" and an "always-most-aggressive path" without defining either):** both start from today's book (the newest `portfolio_snapshots` row) facing the panel's real daily returns from the panel start, options valued by Black-Scholes at the latest stored IV held constant, a day's P&L being `shock.line_pnl` over the actual return and elapsed days. *Status quo* holds the composition (every option rolled each day at today's moneyness and DTE); *aggressive* lets today's options run to expiry and each day tries a 0.25-delta 30-DTE CSP on every `actively_wheeling` name at the largest size `max_contracts_under` admits, the limits gliding from the day-0 measurement as `limits_on` says. P2's drawdown clause reads: aggressive-under-envelope worst 20-session drawdown <= status quo's. Cost if wrong: a different reading of the unenveloped path moves the drawdown comparison, and the replay is a stress path, not a forecast. (4) **The independent breach check** counts an admission that leaves S10 (or U_ew) above its limit of that day *and* higher than before; a sizer that admits everything is caught (`test_admissions_above_the_limit_fail_the_harness`). (5) **The spreads book** counts as -2% of the starting NLV every 21 sessions on both paths, and 2% on top of the worst scenario in the analytic line; the value book's stock and any hedge are not in the replayed book (the script prints the latest stored `envelope_snapshots` S10 and U_ew beside, so a gap shows). Cost if wrong: the replay understates today's S10 by the value book's share. (6) **P1 defects, my reading:** a record session is an ET day with an `envelope_snapshots` row in `record`; `envelope_unmeasured` is a defect on a day when more than 20% of that day's CSP `candidates` rows have it as an `envelope_record` reason in `sizing_actions`; the generator and the gate disagree when the set of candidates with a `:generator` row differs from the set with a `:scan`/`:ticker_scan` row. `risk_verdicts` (pruned to 14 days) is not used. Cost if wrong: a false defect holds the harness at "no result". (7) **A P2 failure is a FAIL whatever the record says; a P2 pass with under 10 clean record sessions is `passed=None`** (the plan: `passed` is P2 and the 10 sessions). (8) The script defaults to a weekly attempt (`--attempt-every 5`) because each attempt re-measures the whole book. (9) **Not run on real data:** the operator's databases were not read; run `python -m scripts.envelope_harness` after 10 `record` sessions |
| Task 27: the tech-cap and stacking backtest (E15) | todo | | | | |
| Task 28: the slow-breaker threshold replay (E14) | todo | | | | |
| Task 29: the sleeve replay (E7) and the covered-call floor replay (E12) | todo | | | | |
| Task 29a: the LES replay (L8) | todo | | | | |
| Section H exit | todo | | | | |
| Section I entry / Tasks 30-32, 32a / exit | todo | | | | |
| Section J entry / Tasks 33-37 / exit | todo | | | | |
| Section K / Task 38 | todo | | | | |
| Whole-branch review (opus) / fix pass | todo | | | | |
| Section L / Task 39 (deferred, on the E3 PASS notice) | todo | | | | |

*(One row per task is added as each lands; a ruling is any deviation from the task text, and why, with its cost if wrong.)*

## Roadmap (the spec's phases against this plan)

| Phase | Built in | Goes live when |
|---|---|---|
| E0 | A-E | The early merge and restart |
| E1 | H (committed replays); research sessions (Operator to-do 8) | Each report's PASS, automatically, paper only |
| E2 | F, G, I, J | Envelope `record` at merge; `on` after the harness PASS and 10 clean record sessions; the bridge when `on` and the instrument is set |
| E3 | L | Your run of Task 39 after the E3 PASS notice |
| E4 | J (bridge end, review record), D (stabilisation check) | The glide's last week; the bridge's review record is posted; default off |

## Rulings

**Operator, 2026-11-14 (binding).** Every recommendation in the spec's E1-E15 and H1-H10 tables is adopted as ruled.
Confirmed explicitly: E4 as written (no new CSP until trims or call-aways make room); E7 = 3% of NLV aggregate; H6
includes the VXN ≥ 1-year 90th percentile block. Phase-1 answers: one plan for E0-E4 (Q1); value-book buys must pass
S10_gross ≤ L(t) and U_ew, and an envelope-blocked buy opens no funding request (Q2); U_ew replaces the wheel's
nominal check and `max_gross_notional_pct` stays for the value book's fundable gate, with the floor-lot erasure fixed
in the same task (Q3); live IV unavailable means fail closed, `envelope_unmeasured` (Q4); in-estate replays are
committed, long-history studies are research sessions (Q5); Telegram daily line, manual-buy line, `GET /envelope` and
one web card (Q6); every reader skips flagged IV rows (Q7). Data-gated rulings: a PASS turns the behaviour on
automatically in paper only, record-only/off in live, logged in `system_settings` with a Telegram notice, reversible by
CLI; the E3 PASS only notifies.

**Each ruling, one line (spec value or criterion; "plan" = set by plan, 2026-11-14):**

| Id | Ruling |
|---|---|
| E1 | Spreads `mode: shadow` until the spreads paper bar passes; enforced by switch `spreads_paper` (Task 7) |
| E2 | Per trade max loss ≤ 0.5% of NLV; today's realised+open loss ≥ 1% NLV → no entries today; month to date ≤ −2% NLV → no entries until a human reset in a later month; EL floor 40% of NLV; FOMC decision days blocked; 08:30 prints unblocked |
| E3 | SPXW 25-wide 1 lot if its median all-in round-trip cost per $1k max loss ≤ SPY's over ≥ 15 shadow capture sessions **and** the spreads paper bar passed; else XSP 5-wide if it passes the same test (settlement only, your call); else stay on SPY. PASS notifies only |
| E4 | S10 by full revaluation, Blume betas, leveraged at leverage × governing index β, capped at −100%; target 15%; start = measured S10_gross on the first `on` session rounded up to a whole percent; 13 weekly linear steps; S20 reported |
| E5 | U_ew unconditional for risk-adding opens; start = measured U_ew on the first `on` session rounded up to 0.01 (≈ 1.36 today); target 1.25; same 13 weeks; existing positions above it untouched; ITM puts at strike |
| E6 | G10 and P20 are display and classification measures, not limits |
| E7 | Sleeve: §3.5 conditions 1-9 as revised by spec rev 3; σ₆₀ drawdown trigger 1.0 (the below-200-day path only); delta window 0.15-0.20; cap = the LES tier (L4), leverage-weighted, CSPs and LES shares together |
| E8 | UPRO, DPST out; TQQQ, SOXL out of `actively_wheeling` (stay `would_own`); QQQ into `actively_wheeling`; SOXX `would_own` dip-watch and `regime.tech_linked`; SPY at E3 |
| E9 | `broad_index_etf_collateral_pct: 15` for `broad_index_etfs: [QQQ]` (SPY added at E3); VOO/IVV only as the SPY fallback |
| E10 | `index_1x` multipliers {normal 1.0, cautious 1.0, stressed 0.8, crisis 0.5}, recorded only until the research report PASSes: mean return of stressed+crisis entries ≥ calm entries under both valuations (hold; roll-or-assign at the 2× line) on S&P 1991-2026 **and** the same sign on the 17-month panel |
| E11 | `cash_reserve_pct` stays a margin buffer; no Portfolio Margin; "cash after every ITM put is assigned" shown as a fact |
| E12 | Floors tried {1.00, 0.95, 0.90 with call delta ≤ 0.20}. PASS for a floor below 1.00 (plan): extra premium vs 1.00 − upside forgone on call-aways ≥ 0 over the panel **and** mean S10 not higher than at 1.00; the lowest passing floor is applied. Leveraged class floor none at delta ≤ 0.25 is tap-only until its own replay nets ≥ 0, then auto in paper (plan) |
| E13 | Show S10, U_ew and headroom before and after every manual buy; never gate TWS |
| E14 | Slow breaker window 20 sessions (plan: the spec's 20-30, lower end). Threshold (plan): the lowest of {8, 10, 12, 15}% drawdown from the 20-session NLV high that trips in the Oct-Nov 2026 slide and has ≤ 2 trip episodes in the panel's first 12 months; if none qualifies, 15%. On a trip: CSP budget × 0.5 (plan), spreads entries stop, human reset |
| E15 | Tech-linked cap (plan): leverage-weighted tech-linked exposure (stock MV + short-put strike × 100) ≤ 60% of NLV for a new tech-linked CSP. Stacking rule (plan): halve when the name has an open short within ±7 days of the new expiry; block on an ITM short or ≥ 2 same-day fills. PASS for each rule separately (plan): it blocks or halves ≥ 6 of the 10 `claude_cut` rows and blocks ≤ 25% of the uncut system CSP opens Oct 13-Nov 12 that closed at a profit |
| H1 | Every admission test reads S10_gross (no long option from any source); S10_net is display and harness only; built in E0 |
| H2 | Bridge yes: Python-run from the envelope's first `on` session to the glide end; conditional sunset by the size rule; review record at E4 or after 20 sessions of zero size, default off; renewal ≤ 2% NLV a year needs a fresh ruling |
| H3 | Net premium ≤ 1.0% NLV₀ over the bridge; pace ≤ 0.25% NLV₀ × (months elapsed + 2); open premium at cost ≤ 0.6% NLV₀; its own line |
| H4 | XND if, over ≥ 20 capture sessions: median quoted spread ≤ 8% of mid on the default item's legs, displayed size ≥ the bridge's contract count on ≥ 80% of captures, and all-in cost per protected point ≤ 1.5× QQQ's; else QQQ under the §3.10.0 rule |
| H5 | Outright or ≥ 10%-wide vertical; 60-120 DTE (90 targeted); long delta 0.15-0.30; floors DTE ≥ 45, delta ≥ 0.15; default = best minimum protection per dollar over {S10, S20, T20, G10, P20}; size = min(budget points, 0.5 × max(0, S10_gross − 15)); hedge delta ≤ 50% of book beta-delta; roll at ≤ 30 DTE; monetisation (plan): 2× take-profit is applied only when the research report shows it lowers annual net carry by ≥ 0.5 points of notional vs hold-to-roll on both NDX 2002-2026 and S&P 1991-2026 with a down-leg cover ratio ≥ 90% of hold's |
| H6 | No new hedge size after a VIX close ≥ 25 or a VXN close ≥ its 1-year 90th percentile; self-funding roll = net debit ≤ 0 and no added contracts; halt and slow breaker also block new size |
| H7 | Gates on live IBKR IV at decision and send time; IV sanity flag on `iv_history` writes; leg-quote capture from E0; SPY IV capture restarted; shadow valuation on captured mids |
| H8 | T20 and S-SMH are display/harness/credit-grid measures. Trigger (plan): the first session T20_gross − S10_gross > 3.0 points turns on switch `t20_limit` (T20_gross ≤ L(t) becomes an admission test, paper) with a notice |
| H9 | `book="hedge"`, `hedge:<id>` and the reserved `hedge:claude:<id>` refs; underlying and contract disjointness; `hedge_view`; `src/hedge/`; own tables; the reconciliation skip; `tests/test_hedge_fence.py`; CLAUDE.md hedge-fence section |
| H10 | No headroom credit for any hedge |

**The Leveraged Entry Signal (operator, 2026-11-14, spec rev 3 OR13-OR17; "plan" = set by plan):**

| Id | Ruling |
|---|---|
| L1 | LES per governing index G (QQQ→TQQQ, SOXX→SOXL) on each completed daily close: **trend** = close > SMA200; **pullback** = trend and (RSI(2) < 5 or close < SMA50); **washout** = pullback and the Nasdaq-100 breadth oscillator ≤ −40 on any of the last 5 sessions; **trend break** = 2 consecutive closes < SMA200. Fail closed (< 200 bars, a missing close, a breadth count older than 1 session → no signal) |
| L2 | Breadth oscillator: RANA = (adv − dec)/(adv + dec) × 1000 over the Nasdaq-100 constituents; osc = EMA(α 0.10) − EMA(α 0.05), `adjust=False`, 60-session warm-up. History: thetrading.tools `ad_line.json` (`ndx_advancing/ndx_declining`, from 2016-11; personal-use licence, attribution in ARCHITECTURE.md). Forward: own nightly count from the committed constituent list's closes; where both exist and differ by > 10 points, flag and use our own |
| L3 | The trend gate governs the CSP sleeve: above SMA200 the LES pullback is the sleeve signal (§3.5 conditions 2-3 do not apply); below it only the bottoming + σ₆₀ path may open a sleeve CSP, at half the tier; no LES share is bought below SMA200 |
| L4 | Tier (leverage-weighted % of NLV, CSP collateral and LES shares together): 3.0 on a pullback, 6.0 with the washout, 1.5 on the below-200-day path, else 0. Lots and shares round down; never a minimum of one |
| L5 | LES shares: whole shares at mid for the tier's room ÷ leverage; one buy per ETF per 3 sessions; S10_gross ≤ L(t) and U_ew ≤ L_ew(t) after the buy; orderRef `les:<id>`, ledger `book="les"`, outside the wheel's share count (no covered call, no trim, no value count) |
| L6 | Exit: on a trend break, sell every LES share of that ETF at the next session's first intraday cycle (risk-reducing, so no envelope block). No time stop, no price stop. Open sleeve CSPs stay under the roll rules |
| L7 | Switch `leveraged_entry` ships `record` (every would-be buy/sell written to `sizing_actions` kind `les_record` with its envelope result); turns `on` in paper on the LES replay PASS; refused in live always |
| L8 | LES replay PASS (plan): over four cells {QQQ→TQQQ, SOXX→SOXL} × {synthetic 3x (3 × daily index return − 3%/yr) 2000-06-01..2016-12-31, real ETF 2017-01-01..}, the LES strategy (enter on pullback, hold to trend break, full position) has Sharpe ≥ the 200-day filter's in ≥ 3 of 4 cells **and** max drawdown ≤ buy-and-hold's in all 4. Scratch result 2026-11-14: Sharpe 3 of 4 (TQQQ 2017-26 fails: 0.71 vs 0.85), drawdown 4 of 4, so PASS. **The criterion was set after seeing these numbers: the replay is a reproduction check; the forward `record` period is the clean evidence.** Cost if wrong: at most the 6% tier, ≈ 2% of NLV in shares |

**Set by plan, 2026-11-14 (beyond the table):**

| # | Ruling | Cost if wrong |
|---|---|---|
| P1 | The envelope ships at `envelope_enforce = record`: every test runs, would-block reasons are recorded in `sizing_actions` (kind `envelope_record`), nothing is refused. It turns `on` (paper) when the survivability harness PASSes **and** ≥ 10 record sessions show no defect (a defect: `envelope_unmeasured` on > 20% of a session's evaluated CSPs, or the generator and the gate disagreeing on any candidate) | A late start of the glide |
| P2 | Harness PASS: zero admissions while S10_gross > L(t) or U_ew > L_ew(t) across the replay, **and** the always-most-aggressive replay's worst 20-session drawdown ≤ the unenveloped path's | Enforcement waits for a human |
| P3 | The generator trims contracts to the largest count that keeps S10_gross ≤ L(t) and U_ew ≤ L_ew(t) (binding `shock_budget` / `gross_budget`); the gate rejects if still above | One lot where none would do |
| P4 | Envelope reasons are appended **after** the regime rewrite and are never replaced by `regime_budget` or cleared by a floor lot | none |
| P5 | Betas: Blume (0.67 β + 0.33) of 250 daily log returns vs SPY; fewer than 120 sessions → β = 1.5, flagged. G10 moves each name by β × −10% but a leveraged ETF by leverage × −10% of its governing index; S-SMH moves `envelope.semis_names` by β_SMH × −30% and every other name by β × −8% | Small scenario differences |
| P6 | P20 path: ten equal daily log steps to −20%; a leveraged ETF compounds leverage × each step; options repriced at T − 10 days | none |
| P7 | IV sanity band: SPY vs ^VIX, QQQ/TQQQ vs ^VXN, ratio outside [0.6, 1.4] × its 60-session median ratio → flagged; every other symbol outside [0.5, 2.0] × its own 20-session median → flagged; fewer than 10 prior rows → never flagged | A real collapse unflagged, or a real spike skipped |
| P8 | Spreads paper bar (E1): the 5th percentile of 10,000 session-clustered bootstrap means of per-session P&L after measured costs > 0, and the worst 20-session loss ≤ 2% of the stated NLV | none |
| P9 | The hedge runs in the trading process (`approval_service`) on clientId 32, connected for one hedge cycle and disconnected, like the value book's Stage 3 | none |
| P10 | Repair proposals, trims and de-lever are tap-only always; they are never auto-sent at any autonomy level. **The one automatic stock path is LES (L5-L7):** paper only, behind `leveraged_entry`, refused in live even with a tap | none |
| P11 | A result file's FAIL never turns a switch off; only the CLI does. A switch set by CLI is never overwritten by a later report | none |
| P12 | The spreads book counts in the wheel's daily loss leg only for its real mode (`paper` or `live`), never `shadow` or `baseline` | none |

**Code facts the spec gets wrong or leaves open (read 2026-11-14):**

- **C1.** The gross cap did not only go unreached. When the risk gate's budget pass runs with the regime active,
  `risk_engine.py:536-538` replaces every reason with `["regime_budget"]` if the unscaled caps pass. That drops
  `gross_notional_cap` and `combined_name_cap`, and the floor lot then clears the reasons altogether. Example: HOOD 75P
  passed as a floor lot on 2026-11-09 at 14:36, at a nominal gross of 1.40. It is the only `regime_floor_lot` row in
  `sizing_actions`. Separately, the generator's `no_headroom` rejects first, so few CSPs reach that pass at all (20.7k
  generator rejects since Nov 6, against 507 risk-gate verdicts). Task 18 fixes it (P4).
- **C2.** §3.4.2's "remove `vx.active`" alone would leave a nominal 1.00 cap. It is rewritten as U_ew. `max_gross_notional_pct` is
  also the value book's fundable gate (`src/value/risk.py:105`, `src/value/live.py:218,809`), which stays.
- **C3.** `risk.events` exists (`SpreadsEventCfg`, enforced in `src/spreads/risk.py`); Task 3 fills it from the calendar.
- **C4.** The spreads backtest proxies SPY with SPXW quotes scaled by `backtest.trade_scale: 10`; "SPY and SPXW" in §3.2g
  is one source.
- **C5.** SPY's IV stops on 2026-10-05 because EOD IV capture covers universe ∪ held only (`eod_report._iv_symbols`) and
  SPY left the universe for the spreads book; `_spreads_isolated` forbids it there, hence `market_data.reference_iv_symbols`.
- **C6.** `src.api.models.common.Envelope` is the API's response wrapper: the new models are named `RiskEnvelope*`.
- **C7.** `get_positions()` drops value stock and spreads legs by default; the envelope adds value holdings from
  `books.value_exposure().by_name` and hedge marks from `hedge_view`, so nothing is counted twice or missed.
- **C8.** The value fence forbids `src.engine`, so the value book reaches the envelope only through the pure
  `src/analytics/shock.py` and plain `src/common/envelope_types.py` (Task 20's allowance).

## Global Constraints

- The core invariant, the fences and the two written exceptions in root `CLAUDE.md` stay. No LLM output reaches anything
  built here. `tests/test_web_fence.py`, `test_eval_skills.py`, `test_regime_fence.py`, `test_news_fence.py`,
  `test_spreads_fence.py`, `test_value_fence.py`, `test_wheel_spreads_isolation.py` stay green; a fence test is only ever
  **extended** (a new allowance named in the task), never weakened.
- New deterministic modules (`src/analytics/shock*.py`, `src/engine/envelope.py`, `src/hedge/`) import no enrichment:
  add each to `tests/test_regime_fence.py`'s deterministic list (no `src.claude`, `src.news`, `src.spreads_ai`,
  `src.value_ai`, `src.analytics.{market_conditions,sentiment,sector_context}`).
- Every switch reads its default (off) in live (`Config.is_live`); `validate_hedge` and the hedge manager refuse/idle in
  live; the spreads service already idles in live.
- `req_fresh_mkt_data` only (never `ib.reqMktData`); `LimitOrder` only; `qualifyContractsAsync` before every order; the
  market-data line budget holds (`chain_batch_size + spreads.max_market_data_lines + reserved_monitor_lines ≤
  max_concurrent_lines`): every new quote fetch runs in chunks of ≤ 10 lines, cancelled between chunks, between the
  scan's chain batches.
- Never import or run anything under `scripts/run_*`; use `python -m py_compile`. Never touch private `config/*.yaml`,
  `data/value_filing_reads.json` or account data; DB inspection only on copies in the session scratchpad.
- Gates (from the worktree root): Python tasks `ruff format <touched files> && python -m pytest -q && ruff check . && mypy src`;
  web task `cd web && npx vitest run && npx tsc --noEmit && npm run lint`. `tests/test_scan_timeout.py` is a known
  flake: if it is the only failure, re-run it alone; green means "scan timeout flake" in the log. After an API change
  regenerate `docs/web/openapi.json` and `web/lib/api-types.ts` (the command in `docs/web/api.md`); `tests/test_openapi_current.py`
  stays green.

**Shared checks (every section exit):**

- **G1, fences:** `python -m pytest -q tests/test_web_fence.py tests/test_eval_skills.py tests/test_regime_fence.py tests/test_news_fence.py tests/test_spreads_fence.py tests/test_value_fence.py tests/test_wheel_spreads_isolation.py` (and `tests/test_hedge_fence.py` from Task 33) all pass.
- **G2, no direct market data:** `grep -rn "\.reqMktData(" src | grep -v "src/ibkr/market_data.py"` prints nothing.
- **G3, live-off:** `python -m pytest -q tests/test_envelope_switches.py -k live` passes (Task 1 adds it).
- **G4, scratch web build (Task 15 only):** `S="$SCRATCH/g4/web" && mkdir -p "$S" && rsync -a --exclude node_modules --exclude .next web/ "$S/" && ln -s "$PWD/web/node_modules" "$S/node_modules" && (cd "$S" && npm run build); rm "$S/node_modules"; rm -rf "$SCRATCH/g4"` with `SCRATCH` the session scratchpad (literal path).

## Review Focus

1. **Nothing raises risk without passing S10_gross and U_ew**, and no reason is erased (P4) → Tasks 18-20 tests.
2. **No long option creates headroom** (H1, H10): S10_gross excludes every long option from any source → Task 11.
3. **Fail closed** on missing live IV, unreadable state, or a missing glide record when `on` → Tasks 13, 19.
4. **Paper only**: every switch, the hedge and `hedge:claude:` are off/refused in live → G3, Tasks 1, 34.
5. **The spreads book stops when the account stops** (halt, slow breaker, daily leg) → Tasks 3, 6, 22.
6. **Hedge isolation**: no wheel table row, no reconciler misbooking, no same-contract netting, no exercise into shares
   → Tasks 33-36.
7. **The stock order path can never sell value-book shares or uncover a short call** → Task 31.
8. **LES shares stay their own book**: never in the wheel's share count, never under a covered call or a trim, always
   in S10/U_ew; the automatic path is paper only → Tasks 10a, 32a.

---

## File structure

```
config/macro_calendar.yaml                     CREATE  (Task 2; committed reference data)
config/examples/{risk_limits,settings,spreads,universe}.yaml   MODIFY (Tasks 3-9, 16-25, 33)
src/common/macro_calendar.py                   CREATE  (Task 2)
src/common/envelope_types.py                   CREATE  (Task 11) plain dataclasses, no I/O
src/common/spreads_view.py                     CREATE  (Task 6)  mode=ro, plain SQL
src/common/hedge_view.py                       CREATE  (Task 33) mode=ro, plain SQL
src/common/{schemas,config,books}.py           MODIFY
src/storage/envelope_switches.py, envelope_state.py   CREATE (Tasks 1, 13)
src/storage/models.py, db.py                   MODIFY  (iv flag, envelope_snapshots, repair_proposals, hedge_* rows)
src/notify/notices.py                          CREATE  (Task 1)
src/notify/{formatters,approval_service,sender}.py   MODIFY (Tasks 14, 30, 36)
src/analytics/shock.py, shock_inputs.py        CREATE  (Tasks 11-12)
src/analytics/breadth.py, leveraged_entry.py   CREATE  (Task 10a) pure: breadth oscillator; the LES signal
src/data/breadth_backend.py                    CREATE  (Task 10a) thetrading.tools fetch + constituent closes, via src/data/factory.py
config/breadth_constituents.yaml               CREATE  (Task 10a; committed reference data, Nasdaq-100 list)
src/storage/les_state.py                       CREATE  (Task 10a) breadth_counts + les_signals rows, readers
src/execution/les.py                           CREATE  (Task 32a) LES buys and trend-break sells through stock_orders.py
src/ibkr/live_iv.py                            CREATE  (Task 12)
src/engine/envelope.py                         CREATE  (Task 13)
src/engine/{risk_engine,capital,regime_limits}.py    MODIFY (Tasks 8, 18-25, 31, 34)
src/strategies/cash_secured_put.py, covered_call.py  MODIFY (Tasks 19, 30)
src/execution/{circuit_breakers,approval,reconciliation,order_builder}.py, stock_orders.py (CREATE)   (6, 19, 22, 31, 33)
src/orchestrator/{scan,eod_report}.py          MODIFY  (Tasks 9, 13, 14)
src/spreads/{risk,service,chain,menu,executor,store}.py, backtest/engine.py   MODIFY (Tasks 3-7, 17)
src/value/{risk,live,stage3}.py                MODIFY  (Task 20)
src/hedge/{__init__,capture,menu,sizing,orders,executor,manager,store}.py   CREATE (Tasks 16, 33-36)
src/reporting/{survivability,hedge}.py         CREATE  (Tasks 26, 37)
src/api/routers/envelope.py, models/envelope.py   CREATE (Task 14)
src/ledger/ingest.py                           MODIFY  (Task 33)
scripts/{envelope,spreads_costs,spxw_cost_report,hedge_capture_report,envelope_harness,envelope_rules_backtest,
  slow_breaker_replay,sleeve_replay,cc_floor_replay,hedge_report,spreads_reset_month,breadth,les_replay}.py   CREATE
scripts/{spreads_backtest,backfill_prices}.py  MODIFY
web/features/portfolio/EnvelopeCard.tsx (+ test), PortfolioPage.tsx   (Task 15)
tests/test_*.py                                CREATE/MODIFY per task
CLAUDE.md, ARCHITECTURE.md, SETUP.md, STATUS.md, UNIVERSE_RESEARCH.md, src/claude/prompts/strategist.py, docs/web/*   (docs steps)
```

---

## Section A: Foundation (Tasks 1-2) · model: sonnet (effort high)

**Reads:** this plan's Rulings; `src/storage/system_settings.py` (lines 56-85, 317-395); `src/orchestrator/eod_report.py`
(lines 416-440, 495-520); `src/notify/sender.py` (lines 92-96); `src/common/config.py` (lines 2570-2590).

**A0. Setup (orchestrator, before the entry checks).**

- [ ] On `main` in the main checkout, commit this plan and the spec note:
  `git add docs/superpowers/plans/2026-11-14-risk-envelope.md docs/superpowers/specs/2026-11-13-risk-envelope-design.md && git commit -m "docs(plan): risk envelope implementation plan; spec rulings note"` (attribution lines). `data/value_filing_reads.json` stays untracked and unstaged.
- [ ] `df -h .` shows ≥ 10 GiB free, else stop and ask.
- [ ] `git worktree add .claude/worktrees/risk-envelope -b feat/risk-envelope main`; in it symlink the main checkout's
  `.venv` and `web/node_modules`, then `IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"`.
  Every later command runs from the worktree root; never `cd web` to build.

**Entry checks:**

- [ ] **A1.** `git log --oneline -2` shows A0 over 854d493; `git status --short` empty (symlinks ignored).
- [ ] **A2.** Each prints a line: `grep -n "if vx.active and is_csp:" src/engine/risk_engine.py`;
  `grep -n 'reasons = \["regime_budget"\]' src/engine/risk_engine.py`; `grep -n "return max(1, _floor(hard_max \* rf \* lf))" src/engine/regime_limits.py`;
  `grep -n "if self.halt_path.exists():" src/spreads/service.py`; `grep -n "async def reconcile_external_closes" src/execution/reconciliation.py`.
- [ ] **A3.** Nothing already exists: `ls src/hedge src/analytics/shock.py src/engine/envelope.py 2>&1 | grep -c "No such"` prints 3;
  `grep -rn "envelope_switch\|envelope_glide" src` prints nothing.
- [ ] **A4.** Baseline green: the Python gate and the web gate. Record pytest/mypy/vitest counts in the Section A entry row.

**Section exit:** two commits after A0; pytest = baseline + Task 1-2 tests; G1, G3 pass.

### Task 1: Switches, notices and result files

**Files:** Create `src/storage/envelope_switches.py`, `src/notify/notices.py`, `scripts/envelope.py`,
`tests/test_envelope_switches.py`; modify `src/common/schemas.py`, `src/orchestrator/eod_report.py`, `ARCHITECTURE.md`,
`SETUP.md` (scripts table), this plan.

- [ ] **Step 1: Tests (red).** `tests/test_envelope_switches.py`:
  `test_a_missing_switch_reads_its_default`, `test_set_switch_rejects_a_value_outside_its_set`,
  `test_every_switch_reads_its_default_in_live` (monkeypatch `Config.is_live` True; `spxw_ready` is the one exception, it
  reads its stored value), `test_a_passed_report_turns_its_switch_on_once`, `test_a_failed_report_changes_nothing`,
  `test_a_cli_set_switch_is_never_overwritten_by_a_report` (P11), `test_apply_reports_returns_one_notice_per_change`,
  `test_an_unreadable_result_file_is_skipped_and_logged`.
- [ ] **Step 2: Schema.** In `src/common/schemas.py` add
  ```python
  class EnvelopeReportResult(BaseModel):
      id: str                      # e.g. "E14", "H4", "spreads_paper", "harness"
      passed: bool | None          # None = insufficient data (changes nothing)
      criterion: str               # the plan's one-line rule, copied
      metrics: dict[str, float | str | None] = Field(default_factory=dict)
      switch: str                  # the switch a PASS sets
      value_on_pass: str           # the value it sets
      written_at: datetime
  ```
- [ ] **Step 3: Switches.** `src/storage/envelope_switches.py`: `SWITCHES: dict[str, tuple[str, frozenset[str]]]`
  (name → default, allowed values): `envelope_enforce` (`record`; off/record/on), `spreads_paper` (off; off/on),
  `spxw_ready` (off; off/spxw/xsp/stay), `hedge_instrument` (none; none/XND/QQQ), `bridge` (off; off/on/ended),
  `tech_cap`, `stacking_rule`, `index_1x`, `leveraged_sleeve`, `leveraged_cc_auto`, `t20_limit` (off; off/on),
  `slow_breaker` (off; off/8/10/12/15), `cc_basis_floor` (1.00; 1.00/0.95/0.90), `hedge_monetisation` (none; none/2x),
  `leveraged_entry` (`record`; off/record/on; L7).
  Stored in `system_settings` key `envelope_switch:<name>` as JSON `{value, source, report, set_at}`.
  `get_switch(name) -> str` (default in live except `spxw_ready`; default when missing or unparseable);
  `set_switch(name, value, *, source: str, report: str | None = None) -> None` (raises on an unknown name or value);
  `switch_record(name) -> dict | None`; `apply_reports(dir: Path = ROOT / "data/envelope_reports") -> list[str]`: for
  each `<id>.json` parsed as `EnvelopeReportResult` with `passed is True`, when the switch's record is absent or its
  `source` starts `report:` with a different value, set it (`source=f"report:{id}"`) and return
  `"<id> PASS: <switch> -> <value> (paper; record-only in live). Reverse: python -m scripts.envelope switch <switch> <default>"`.
- [ ] **Step 4: Notices.** `src/notify/notices.py::send_notice(text: str, *, thread: str = "account") -> bool`: one
  plain message through `telegram.Bot` to `TELEGRAM_CHAT_ID` on `thread_id(cfg.secrets.telegram_thread_<thread>)`, as
  `_send_eod_telegram` does; False (logged) on any error, never raises.
- [ ] **Step 5: Wire.** At the end of the EOD run (after the Telegram summary, `eod_report.py` ~line 520), call
  `apply_reports()` and `send_notice` each message, inside `try/except` (logged).
- [ ] **Step 6: CLI.** `scripts/envelope.py` (argparse): `show` (every switch, value, source, set_at; the glide record
  once Task 13 adds it), `switch NAME VALUE` (`source="cli"`, prints the old and new value and sends a notice),
  `apply-reports`. Later tasks add subcommands.
- [ ] **Step 7: Gate, docs, commit.** ARCHITECTURE.md (`src/storage/` and `src/notify/` rows, `scripts/` entry), SETUP.md
  scripts table (`python -m scripts.envelope`). Commit `feat(envelope): data-gated switches, result files and notices`.

### Task 2: The static macro calendar

**Files:** Create `config/macro_calendar.yaml`, `src/common/macro_calendar.py`, `tests/test_macro_calendar.py`; modify
`ARCHITECTURE.md` (config section), this plan.

- [ ] **Step 1: The file.** `config/macro_calendar.yaml` (committed reference data, like `news_playbook.yaml`): a list of
  `{day: YYYY-MM-DD, kind: FOMC|CPI|PPI|NFP|PCE, time_et: "14:00"|"08:30", source: <url>}` for 2026-11-14 to 2027-12-31.
  Fetch the dates from federalreserve.gov (FOMC calendar: the **decision day**, the second day of each meeting),
  bls.gov (CPI, PPI, Employment Situation release schedules) and bea.gov (Personal Income and Outlays). Record each
  source URL in the file header. **If any fetch fails or a schedule is not yet published, stop and report**; never
  copy dates from an aggregator.
- [ ] **Step 2: Tests (red).** `test_the_calendar_loads_and_is_sorted`, `test_every_row_names_a_source`,
  `test_events_on_returns_the_days_rows`, `test_fomc_days_are_wednesdays_or_announced_exceptions` (the test lists any
  exception the Fed published), `test_the_calendar_reaches_a_year_ahead` (max day ≥ today + 300 days).
- [ ] **Step 3: Loader.** `src/common/macro_calendar.py` (imports only stdlib, yaml, pydantic, `src.common.config.ROOT`):
  `MacroEvent(day, kind, time_et, source)`, `load_calendar(path=ROOT/"config/macro_calendar.yaml") -> tuple[MacroEvent, ...]`
  (cached), `events_on(day) -> list[MacroEvent]`, `events_between(start, end)`. It is also the Mastermind's D19 source.
- [ ] **Step 4: Gate, docs, commit.** `feat(config): a static FOMC/BLS/BEA calendar for a year ahead`.

---

## Section B: The spreads book's fixes, E0 (Tasks 3-7) · model: opus (effort high)

**Reads:** spec §3.2, §2.3; `src/spreads/risk.py`; `src/spreads/service.py` (lines 600-735, 1140-1220, 1395-1420);
`src/spreads/chain.py` (lines 380-420); `src/spreads/menu.py`; `src/spreads/executor.py` (lines 150-300);
`src/spreads/store.py` (lines 500-570); `src/common/config.py` (lines 893-1082); `src/execution/circuit_breakers.py`;
`tests/test_spreads_fence.py` (lines 1-160); `tests/test_spreads_risk.py`; `tests/test_spreads_service.py` (fixtures).

**Entry checks:** Section A's two commits; `grep -n "events: list\[SpreadsEventCfg\]" src/common/config.py`,
`grep -n "async def excess_liquidity" src/spreads/chain.py`, `grep -n "def day_stats" src/spreads/store.py` each print a line.

**Section exit:** five commits; G1-G3; `python -m pytest -q tests/test_spreads_*.py tests/test_circuit_breakers.py` green.

### Task 3: The calendar and the account halt reach the spreads gate

**Files:** Modify `src/common/config.py` (`SpreadsRiskCfg`), `src/common/schemas.py` (`SpreadRiskContext`),
`src/spreads/risk.py`, `src/spreads/service.py`, `config/examples/spreads.yaml`, `tests/test_spreads_risk.py`,
`tests/test_spreads_service.py`, `ARCHITECTURE.md` (`src/spreads/`), `SETUP.md` §16.

- [x] **Step 1: Tests (red).** `test_spreads_risk.py`: `test_an_fomc_decision_day_blocks_entries_from_the_calendar`,
  `test_an_0830_print_does_not_block_by_default`, `test_an_operator_event_still_blocks`, `test_account_halted_blocks_entries`,
  `test_slow_breaker_blocks_entries`. `test_spreads_service.py`: `test_a_halt_blocks_entries_but_exits_run`
  (halt set → `_entries` opens nothing, `_manage` still closes), `test_unreadable_halt_state_blocks_entries` (fail closed).
- [x] **Step 2: Config.** `SpreadsRiskCfg.calendar_block: list[Literal["FOMC","CPI","PPI","NFP","PCE"]] = ["FOMC"]`.
  `SpreadRiskContext` gains `account_halted: bool = False`, `slow_breaker: bool = False`, `macro_events: list[str] = []`
  (kinds today).
- [x] **Step 3: Gate.** In `validate`, after the `r.events` loop: any `ctx.macro_events` kind in `r.calendar_block` →
  `macro_event_day`; `ctx.account_halted` → `account_halted`; `ctx.slow_breaker` → `slow_breaker`.
- [x] **Step 4: Service.** `_context()` fills `macro_events` from `src.common.macro_calendar.events_on(today)` and the two
  flags from a new `SpreadsService._account_state() -> tuple[bool, bool]` that imports lazily
  `src.storage.system_settings.is_halted` and `get_setting("slow_breaker_tripped")` (truthy JSON with `"tripped": true`);
  any exception → `(True, True)` and one `alert_once("account_state", ...)`. `_entries` also skips early with a watch
  note when halted. `_events_today` lists calendar kinds beside operator events.
- [x] **Step 5: Fence.** `src/spreads/` may import `src.common.macro_calendar` (common); `src.storage` stays service-only
  (`test_only_the_service_reaches_the_ledger_or_the_trading_db` unchanged and green).
- [x] **Step 6: Gate, docs, commit.** `feat(spreads): the macro calendar, the account halt and the slow breaker stop entries`.

### Task 4: Caps as shares of net liquidation; the month stop

**Files:** Modify `src/common/config.py`, `src/spreads/risk.py`, `src/spreads/chain.py`, `src/spreads/service.py`,
`src/spreads/store.py`, `config/examples/spreads.yaml`; create `scripts/spreads_reset_month.py`; tests in
`tests/test_spreads_risk.py`, `tests/test_spreads_service.py`, `tests/test_spreads_config.py`; docs.

- [x] **Step 1: Tests (red).** `test_size_is_half_a_percent_of_nlv` (NLV 650k, 5-wide $430 max loss/contract → 7),
  `test_todays_loss_of_one_percent_stops_entries` (realised + open), `test_a_two_percent_month_stops_entries_until_reset`,
  `test_the_month_stop_survives_a_new_month_until_a_human_resets`, `test_el_floor_is_forty_percent_of_nlv`,
  `test_unknown_nlv_blocks_entries` (`account_unknown`), `test_starting_capital_no_longer_sizes`.
- [x] **Step 2: Config keys** (`SpreadsRiskCfg`, examples with comments): `max_loss_pct_of_nlv: 0.005`,
  `max_daily_loss_pct_of_nlv: 0.01`, `max_monthly_loss_pct_of_nlv: 0.02`, `min_excess_liquidity_pct_of_nlv: 0.40`,
  `max_total_risk_pct_of_nlv: 0.005`. `starting_capital_usd` stays for the P&L report only (comment says so);
  `max_loss_pct_of_capital`, `max_total_risk_pct_of_capital`, `max_daily_loss_pct_of_capital` and
  `min_excess_liquidity_usd` are removed from the example and kept in the class as ignored legacy fields (validator
  unchanged) so a private copy still loads.
- [x] **Step 3: Broker.** `chain.py`: `async def net_liquidation(self) -> float | None` beside `excess_liquidity`
  (tag `NetLiquidation`, USD); the `Broker` Protocol in `service.py` gains it.
- [x] **Step 4: Gate.** `size(c, cfg, nlv_usd)`: `floor(max_loss_pct_of_nlv × nlv / max_loss_per_contract)`, capped by
  `max_contracts`. `SpreadRiskContext` gains `nlv_usd: float | None`, `open_pnl_today_usd: float = 0.0`,
  `month_stop: bool = False`; `capital_usd` stays for reporting. Reasons: `nlv_unknown`, `daily_loss_limit`
  (realised + open ≤ −1% NLV), `month_stop`, `max_total_risk` (vs NLV), `excess_liquidity_floor` (< 40% NLV).
- [x] **Step 5: Month stop.** `store.py`: `month_realized_pnl(year, month, mode)`; a `spread_flags` table (`SpreadsBase`;
  `key`, `value` JSON, `updated_at`) with `month_stop_get()` / `month_stop_set(month: str)` / `month_stop_clear()`. The
  service sets it when month-to-date realised + open ≤ −2% NLV and alerts once; `validate` blocks while it is set.
  `scripts/spreads_reset_month.py` clears it (prints what it cleared) and sends a notice.
- [x] **Step 6: Gate, docs, commit.** SETUP.md §16 and STATUS.md say the caps moved to NLV. Commit
  `feat(spreads): risk in shares of net liquidation and a month stop a human resets`.

### Task 5: The cost standard

**Files:** Modify `src/common/config.py` (`SpreadsExecutionCfg`), `src/spreads/menu.py`, `src/spreads/executor.py`,
`config/examples/spreads.yaml`; create `scripts/spreads_costs.py`, `tests/test_spreads_costs.py`; docs.

- [x] **Step 1: Tests (red).** `test_round_trip_cost_uses_crossing_and_fees`, `test_breakeven_is_recomputed_from_the_cost_standard`,
  `test_the_cost_report_measures_the_median_crossing` (fixture `spread_candidates` rows).
- [x] **Step 2: Keys.** `shadow_slippage_per_leg: 0.01` (measured median crossing, $0.01 on 165 candidates, spec §2.3,
  plus a margin key `slippage_margin_per_leg: 0.01`), `commission_per_contract: 0.65` stays the IBKR schedule,
  `exchange_fee_per_contract: 0.0` for SPY (a per-instrument map `exchange_fees: {SPY: 0.0, SPXW: <from IBKR's schedule>, XSP: ...}`;
  the implementer fills SPXW/XSP from IBKR's published fee page or leaves `null` with a STATUS note; `null` blocks the
  cost report for that instrument). `round_trip_cost` = 4 × (slippage + margin) + 4 × (commission + fee) / 100.
  `be_nominal_exits` in `menu.py` uses it.
- [x] **Step 3: Report.** `scripts/spreads_costs.py`: reads `data/spreads.db` read-only, prints median and p90 of
  `credit_mid − credit_natural` per instrument and the modelled vs paper commission per leg.
- [x] **Step 4: Gate, docs, commit.** `feat(spreads): a measured cost standard before any record counts`.

### Task 6: Spreads P&L in the wheel's daily loss leg; the Nov 10 lesson pinned

**Files:** Create `src/common/spreads_view.py`, `tests/test_spreads_view.py`; modify `src/execution/circuit_breakers.py`,
`src/notify/formatters.py` (trip card), `tests/test_circuit_breakers.py`, `tests/test_spreads_service.py`,
`tests/test_web_fence.py` (allowance), docs.

- [x] **Step 1: Tests (red).** `test_spreads_view_opens_read_only` (a write raises), `test_pnl_today_counts_only_the_real_mode`
  (P12: shadow/baseline rows excluded), `test_pnl_today_is_none_when_the_file_is_missing`, `test_the_daily_leg_adds_spreads_pnl`,
  `test_a_trip_card_shows_the_loss_by_book`, `test_a_late_fill_after_an_unconfirmed_cancel_is_booked` (the `9da9e8a`
  path in `service._late_fills`, as a regression pin), `test_a_broker_db_mismatch_blocks_entries` (pin).
- [x] **Step 2: View.** `src/common/spreads_view.py` (imports `sqlite3`, `src.common.config` only; `mode=ro` URI from
  `get_config().spreads.db_url`): `pnl_today(day: date) -> float | None` = realised P&L of the real mode's positions
  closed today + (credit − last `mid_debit`) × 100 × contracts of the open ones.
- [x] **Step 3: Breaker.** `mark_based_loss` / `evaluate_breakers`: the loss compared with the threshold is the wheel's
  mark delta plus `-(pnl_today or 0)` when negative; the reason string names both books
  (`"Daily mark-to-market loss $X (wheel $W, spreads $S)"`).
- [x] **Step 4: Fence.** `tests/test_web_fence.py` (or `test_spreads_fence.py`, wherever the "who opens spreads.db" rule
  lives): allow `src/common/spreads_view.py` as the one non-API, non-spreads reader; it imports no `src.spreads`.
- [x] **Step 5: Gate, docs, commit.** ARCHITECTURE.md `src/common/`. Commit `feat(breakers): the spreads book counts in the daily loss leg`.

### Task 7: Shadow until the paper bar; the backtest harness on the new standard

**Files:** Modify `src/spreads/service.py`, `src/spreads/backtest/engine.py`, `scripts/spreads_backtest.py`,
`tests/test_spreads_service.py`, `tests/test_spreads_backtest.py` (create if absent), docs.

- [x] **Step 1: Tests (red).** `test_paper_config_trades_shadow_until_the_switch` (cfg `mode: paper`, switch off →
  effective `shadow`), `test_the_switch_on_lets_paper_trade`, `test_shadow_config_never_trades_paper`,
  `test_the_backtest_sizes_at_half_a_percent_of_the_stated_nlv`, `test_the_report_writes_a_result_file` (P8 metrics,
  `passed`), `test_too_few_sessions_is_insufficient` (< 60 sessions → `passed: None`).
- [x] **Step 2: Effective mode.** `SpreadsService.effective_mode() -> str`: `paper` only when `cfg.mode == "paper"` and
  `get_switch("spreads_paper") == "on"` (lazy import, service only); else `shadow`. Every use of `self.cfg.mode` for the
  traded book goes through it; the day card says "shadow until the backtest passes" when it downgrades.
- [x] **Step 3: Harness.** `backtest_cfg` applies the Task 4/5 standard; `run_backtest` takes `nlv_usd`; the script
  gains `--nlv` (default: the latest `portfolio_snapshots` NLV, read-only) and `--report`, which writes
  `data/envelope_reports/spreads_paper.json` (`switch="spreads_paper"`, `value_on_pass="on"`) with: sessions, trades,
  mean P&L per session after costs, the bootstrap 5th percentile, break-even win rate, worst day, worst 20 sessions,
  tag breakdowns; `passed` per P8. Expect harness fixes on first contact with a real terminal (Operator to-do 6).
- [x] **Step 4: Gate, docs, commit.** SETUP.md §16 (how to run the backtest and read the bar). Commit
  `feat(spreads): shadow until the backtest bar passes; the harness on the cost standard`.

---

## Section C: Leveraged policy, universe, IV data, breadth and LES, E0 (Tasks 8-10, 10a) · model: sonnet (effort high)

**Reads:** spec §3.5, §3.6, §3.10.8; `src/engine/regime_limits.py` (lines 130-310); `src/common/config.py` (lines
2280-2460, 2761-2780); `config/examples/risk_limits.yaml` (lines 176-270); `config/examples/universe.yaml`;
`src/orchestrator/eod_report.py` (lines 130-215, 270-290); `src/storage/iv_history.py`; `tests/test_regime_limits.py`.
Task 10a also reads spec §2.7 and §3.5.1, Rulings L1-L8, `src/data/factory.py`, `src/data/protocols.py`,
`src/data/yfinance_backend.py`, `src/storage/price_history.py` (`load_bars`, `append_bars`),
`src/analytics/technicals.py` (`rsi14_series`, the pattern for `rsi_series`), `src/analytics/bottoming.py` (the
pure fail-closed pattern).

**Entry checks:** Section B exit green; `grep -n "KEYS: ClassVar\[tuple\[str, ...\]\] = (\"enabled\", \"per_trade_fraction\", \"leverage\")" src/common/config.py` prints a line.

**Section exit:** four commits; G1-G3; `tests/test_regime_limits.py`, `tests/test_breadth.py`, `tests/test_leveraged_entry.py` green.

### Task 8: Leveraged CSPs off; no fair-value waiver for them

**Files:** Modify `src/common/config.py` (`LeveragedSizingCfg`), `src/engine/regime_limits.py`,
`config/examples/risk_limits.yaml`, `tests/test_regime_limits.py`, `tests/test_bottoming.py`, docs.

- [ ] **Step 1: Tests (red).** `test_drawdown_only_gives_zero_outside_the_sleeve`, `test_normal_mode_keeps_decision_32`
  (`csp_mode: normal` reproduces today's `max(1, ...)`), `test_vrp_waiver_is_false_for_a_leveraged_name`,
  `test_vrp_waiver_still_holds_for_an_unleveraged_signal_lot`. Existing tests pinning the leveraged floor of 1 change to
  set `csp_mode: normal` (an existing test changes; record it).
- [ ] **Step 2: Config.** `LeveragedSizingCfg` KEYS gain `csp_mode` (`Literal["drawdown_only","normal"] = "drawdown_only"`);
  the `sleeve` key is Task 23's.
- [ ] **Step 3: Code.** `per_trade_cap`: for a leveraged name with `csp_mode == "drawdown_only"` return 0 unless
  `regime_limits.sleeve_lot(ctx, symbol)` is True (a stub returning False here; Task 23 fills it). `vrp_waiver` returns
  False when `leverage_factor(ctx, symbol) is not None`.
- [ ] **Step 4: Gate, docs, commit.** STATUS.md (decision 32 / ruling 35 changed). Commit `feat(regime): no leveraged CSP outside the drawdown sleeve`.

### Task 9: The universe template, SOXX, and SPY IV restarted

**Files:** Modify `config/examples/universe.yaml`, `config/examples/risk_limits.yaml` (`regime.tech_linked` + SOXX),
`config/examples/settings.yaml`, `src/common/config.py` (`MarketDataCfg`), `src/orchestrator/eod_report.py`,
`scripts/backfill_prices.py`, `UNIVERSE_RESEARCH.md`, `src/claude/prompts/strategist.py` (`_UNIVERSE_CONTEXT`),
`tests/test_eod.py`, `tests/test_universe_consumers.py`.

- [ ] **Step 1: Tests (red).** `test_reference_iv_symbols_join_the_eod_iv_list` (SPY in `_iv_symbols` though not in the
  universe), `test_reference_price_symbols_join_the_daily_price_append`, `test_reference_symbols_never_enter_the_universe`
  (`effective_universe()` unchanged).
- [ ] **Step 2: Keys.** `market_data.reference_iv_symbols: [SPY]`, `market_data.reference_price_symbols: [SPY, "^VIX", "^VXN"]`;
  `_iv_symbols` and `_append_daily_prices` (and `backfill_prices._universe_symbols`) union them.
- [ ] **Step 3: Template.** `universe.yaml`: UPRO and DPST out of `indexes`, `would_own`, `actively_wheeling`,
  `leveraged_etfs` (keep `leverage` entries in risk_limits for any held lots), the header's exception paragraph
  rewritten ("TQQQ/SOXL: would_own, CSPs only through the drawdown sleeve, 2026-11-14; UPRO/DPST dropped"); TQQQ and
  SOXL out of `actively_wheeling`; QQQ into `actively_wheeling`; SOXX into `indexes` and `would_own` (dip-watch) with
  `sectors: SOXX: semiconductors` (the sector key SMH uses); `regime.tech_linked` gains SOXX.
- [ ] **Step 4: Docs.** UNIVERSE_RESEARCH.md: UPRO and DPST sections marked removed (dated), SOXX section (SOXL's twin,
  β 2.96 / R² 0.998, no option history yet), QQQ tier note; `_UNIVERSE_CONTEXT` rows to match. Operator to-do 2 covers
  the private copy and the SOXX/SPY backfills.
- [ ] **Step 5: Gate, commit.** `feat(universe): UPRO and DPST out, SOXX dip-watch, QQQ wheeling, SPY IV restarted`.

### Task 10: The IV sanity flag; every reader skips flagged rows

**Files:** Modify `src/storage/models.py` (`IVHistoryRow.flagged`), `src/storage/db.py` (`_ADDED_COLUMNS`),
`src/storage/iv_history.py`, every `iv_history` reader (grep below), `src/common/config.py`, `config/examples/risk_limits.yaml`;
create `tests/test_iv_sanity.py`; docs.

- [ ] **Step 1: Readers.** `grep -rln "IVHistoryRow\|iv_history" src` lists the readers (2026-11-14: `src/analytics/iv.py`,
  `src/storage/iv_history.py`, `src/ibkr/market_data.py`, `src/orchestrator/eod_report.py`, `src/backtest/{data,engine}.py`,
  `src/research/checks/metrics.py`, `src/research/ingest/materialize.py`, `src/api/routers/{research,watchlist}.py`,
  `src/notify/{formatters,approval_service}.py`, `src/ops/watchdog.py`). Record the list in the log.
- [ ] **Step 2: Tests (red).** `test_a_collapsed_qqq_iv_is_flagged` (QQQ 14.6 vs VXN 38.3 with a 0.87 median ratio),
  `test_a_normal_row_is_not_flagged`, `test_too_little_history_never_flags`, `test_a_flag_raises_one_data_alert`,
  `test_every_reader_skips_flagged_rows` (structural: every file in Step 1's list that selects from `iv_history`
  contains `flagged` in the same query, by `ast`/text scan), `test_iv_rank_ignores_a_flagged_row`.
- [ ] **Step 3: Flag.** `flagged INTEGER DEFAULT 0` (`_ADDED_COLUMNS["iv_history"]`); `append_observation` computes it per
  P7 (keys `iv_sanity.index_ratio_band: [0.6, 1.4]`, `iv_sanity.single_band: [0.5, 2.0]`,
  `iv_sanity.vol_index: {SPY: "^VIX", QQQ: "^VXN", TQQQ: "^VXN"}`, `iv_sanity.min_history: 10`; VIX-family closes from
  `price_history`, Task 9). A flagged write logs a warning and calls `send_notice` once per symbol per day.
- [ ] **Step 4: Readers.** Each reader adds `flagged = 0` (or `IVHistoryRow.flagged.is_(False)`).
- [ ] **Step 5: Gate, docs, commit.** STATUS.md (flagged rows are excluded everywhere, Q7). Commit `feat(data): flag implausible IV observations; every reader skips them`.

### Task 10a: The Nasdaq-100 breadth oscillator and the Leveraged Entry Signal (record only)

**Files:** Create `src/analytics/breadth.py`, `src/analytics/leveraged_entry.py`, `src/data/breadth_backend.py`,
`src/storage/les_state.py`, `config/breadth_constituents.yaml`, `scripts/breadth.py`, `tests/test_breadth.py`,
`tests/test_leveraged_entry.py`; modify `src/data/protocols.py`, `src/data/factory.py`, `src/storage/models.py`,
`src/common/config.py`, `config/examples/risk_limits.yaml`, `src/orchestrator/eod_report.py`, `tests/test_regime_fence.py`; docs.

- [ ] **Step 1: Constituents.** Fetch the current Nasdaq-100 list from `https://en.wikipedia.org/wiki/Nasdaq-100`
  (the components table) and write `config/breadth_constituents.yaml`: `{as_of: <date>, source: <url>, ndx: [..]}`.
  If the fetch fails or the count is not 100-102, stop and report. `scripts/breadth.py refresh-constituents` repeats
  this (quarterly, Operator to-do 9).
- [ ] **Step 2: Tests (red).** `tests/test_breadth.py`: `test_rana_and_ema_match_a_hand_computed_series`
  (5 rows, α 0.10/0.05, `adjust=False`), `test_warm_up_rows_are_none`, `test_own_count_from_closes` (adv/dec/unch from
  two days of closes; a missing close counts in neither), `test_sources_disagreeing_by_more_than_10_flags_and_uses_own`.
  `tests/test_leveraged_entry.py`: `test_no_signal_under_200_bars`, `test_trend_gate`, `test_pullback_on_rsi2_under_5`,
  `test_pullback_on_close_under_sma50`, `test_washout_lifts_the_tier_to_6`, `test_below_200_tier_is_half_of_3`
  (`below_trend_tier` 1.5, only meaningful with the bottoming path), `test_trend_break_needs_two_closes`,
  `test_stale_breadth_means_pullback_tier_only` (washout needs a count dated the last session; otherwise tier 3),
  `test_reasons_name_each_part`. `tests/test_regime_fence.py` lists the two new analytics modules and `src/data/breadth_backend.py`
  is reachable only through `src/data/factory.py`.
- [ ] **Step 3: Pure code.** `src/analytics/breadth.py`: `rana(adv: int, dec: int) -> float | None`;
  `oscillator(counts: list[BreadthCount], *, fast: float = 0.10, slow: float = 0.05, warm_up: int = 60) -> list[float | None]`;
  `count_from_closes(prev: dict[str, float], today: dict[str, float]) -> tuple[int, int, int]`.
  `src/analytics/leveraged_entry.py`: `rsi_series(close, n)` (Wilder, as `rsi14_series`) and
  `les_signal(bars: pd.DataFrame, osc_recent: list[tuple[date, float]], cfg: LesCfg) -> LesSignal` with
  `LesSignal(asof, index, trend_up, pullback, washout, trend_break, tier_pct, reasons)` in `src/common/schemas.py`
  (L1, L4; `tier_pct` 6.0/3.0/0.0 here; the 1.5 below-trend tier is applied by `regime_limits` only on the bottoming
  path, Task 23). Keys `regime.leveraged_entry: {governing: {TQQQ: QQQ, SOXL: SOXX}, sma_trend: 200, sma_pullback: 50,
  rsi_n: 2, rsi_max: 5, washout_osc: -40, washout_sessions: 5, tiers: {pullback: 3.0, washout: 6.0, below_trend: 1.5},
  break_closes: 2, pace_sessions: 3, source_gap_flag: 10}` (`LesCfg`).
- [ ] **Step 4: Data and storage.** `BreadthProvider` protocol (`history() -> list[BreadthCount]`) and
  `src/data/breadth_backend.py::TheTradingToolsBreadth` (GET `https://www.thetrading.tools/data/market_breadth/ad_line.json`,
  timeout 30 s, fields `date, ndx_advancing, ndx_declining`; any error → empty list and a warning); factory
  `get_breadth_provider()`. Own count: `src/data/yfinance_backend.py` gains `closes(symbols, days=3) -> dict[date, dict[str, float]]`
  (one batched download). `src/storage/les_state.py`: `BreadthCountRow` (`breadth_counts`: date, source `tt|own`, adv, dec,
  unch, osc, flagged) and `LesSignalRow` (`les_signals`: asof, index, the `LesSignal` fields, reasons JSON), both in
  `src/storage/models.py` and `init_db`; `record_counts`, `latest_osc(n)`, `record_signal`, `latest_signal(index)`.
  `scripts/breadth.py backfill` loads the thetrading.tools history once (idempotent).
- [ ] **Step 5: Nightly.** In the EOD run after `_append_daily_prices` (QQQ and SOXX are already in the price store,
  Task 9): fetch both sources, store the counts (own wins on a > 10-point gap, flagged), recompute the oscillator,
  compute `les_signal` for QQQ and SOXX, store it. One line in the daily envelope Telegram message (Task 14 adds the
  line builder; here only the data): `LES QQQ: trend ✓ · pullback ✓ · breadth −43 (washout) → tier 6%`. Nothing reads
  the signal for sizing yet (Task 23).
- [ ] **Step 6: Gate, docs, commit.** ARCHITECTURE.md (the modules; the data source with its personal-use licence and
  attribution), STATUS.md (LES recorded, not acting). Commit `feat(regime): Nasdaq-100 breadth oscillator and the Leveraged Entry Signal, recorded`.

---

## Section D: Measurement and displays, E0 (Tasks 11-15) · model: opus (11-14), sonnet (15) (effort high)

**Reads:** spec §3.4.1-3.4.3, §3.4.7, §3.7.4, §2.4 (covered calls and S10), §3.10.8; `src/analytics/black_scholes.py`;
`src/common/books.py`; `src/engine/capital.py` (lines 36-210); `src/storage/price_history.py`; `src/ibkr/market_data.py`
(lines 90-135, 860-905); `src/orchestrator/scan.py` (around lines 1690-1720, 2180-2200); `src/api/routers/system.py`
(lines 1-60); `src/api/settings_read.py`; `web/DESIGN.md`; `web/features/portfolio/PortfolioPage.tsx`, `SummaryCard.tsx`.

**Entry checks:** Section C exit green; `grep -n "^def bs_price" src/analytics/black_scholes.py` prints a line.

**Section exit:** five commits; G1-G4; `test_openapi_current` green.

### Task 11: `src/analytics/shock.py`, the pure scenario engine

**Files:** Create `src/common/envelope_types.py`, `src/analytics/shock.py`, `tests/test_shock.py`; modify
`tests/test_regime_fence.py` (deterministic list), `ARCHITECTURE.md`.

- [ ] **Step 1: Types.** `src/common/envelope_types.py` (stdlib dataclasses, frozen, no I/O):
  `BookLine(symbol, kind: Literal["stock","short_put","short_call","long_put","long_call"], qty: float, spot: float,
  strike: float | None, dte: int | None, iv: float | None, book: str)` (qty in shares for stock, contracts for options;
  iv decimal), `ShockInputs(lines, betas: dict[str,float], betas_smh: dict[str,float], leverage: dict[str,int],
  governing: dict[str,str], tech_linked: frozenset[str], semis: frozenset[str], nlv: float)`,
  `ShockResult(s10, s20, g10, p20, t20, s_smh, s10_vol10: float  # all % of NLV, gross; and the same *_net; uew: float;
  unmeasured: tuple[str, ...])`, `EnvelopeRoom(s10_gross, s10_limit, uew, uew_limit, t20_gross, t20_limit | None,
  enforce: str, measured: bool, reasons_if_unmeasured: tuple[str, ...])`.
- [ ] **Step 2: Tests (red).** `test_stock_loses_beta_times_ten_percent`, `test_a_leveraged_etf_moves_at_leverage_times_its_index_beta`,
  `test_a_leveraged_move_is_capped_at_minus_100`, `test_a_short_put_is_fully_revalued` (matches `bs_price` at the shocked
  spot), `test_a_covered_call_protects_only_its_premium` (spec §2.4: full revaluation gives far less than delta-linear),
  `test_gross_ignores_every_long_option` and `test_net_counts_long_options` (H1), `test_t20_moves_tech_linked_twenty_percent`,
  `test_s_smh_uses_smh_betas_for_semis`, `test_p20_compounds_leveraged_daily`, `test_vol_plus_ten_raises_short_put_loss`,
  `test_uew_counts_stock_and_put_strike_at_leverage`, `test_uew_ignores_long_options`, `test_a_missing_iv_is_unmeasured_not_zero`,
  `test_no_io` (structural: imports only stdlib, `src.common.envelope_types`, `src.analytics.black_scholes`).
- [ ] **Step 3: Code.** `shock.py`: `name_move(symbol, index_move, inputs, *, scenario) -> float` (P5); `line_pnl(line,
  move, *, days=0, vol_bump=0.0) -> float | None` (stock: qty × spot × move; options: (BS(new) − BS(now)) × 100 × signed
  qty, BS at `dte − days`, None when iv is None); `scenario_loss(inputs, scenario: Literal["S10","S20","G10","P20","T20",
  "S_SMH"], *, include_long: bool, vol_bump=0.0) -> tuple[float, tuple[str,...]]` (loss % of NLV, unmeasured symbols);
  `uew(inputs) -> float` (Σ |stock MV| × leverage + Σ short-put strike × 100 × |qty| × leverage, over NLV; value-book
  lines included by their `book`); `measure(inputs) -> ShockResult`. Scenario constants in one dict at the top with the
  spec section cited.
- [ ] **Step 4: Gate, docs, commit.** `feat(analytics): the shock engine, gross and net of long options`.

### Task 12: Inputs: betas, stored IV, live IV

**Files:** Create `src/analytics/shock_inputs.py`, `src/ibkr/live_iv.py`, `tests/test_shock_inputs.py`, `tests/test_live_iv.py`;
modify `src/common/config.py` (`RiskEnvelopeCfg`, `get_envelope_cfg()`), `config/examples/risk_limits.yaml`, docs.

- [ ] **Step 1: Config.** New block `envelope:` in `risk_limits.yaml`, class `RiskEnvelopeCfg(_KeyedCfg)`:
  `s10_target_pct: 15.0`, `uew_target: 1.25`, `glide_weeks: 13`, `beta_sessions: 250`, `beta_min_sessions: 120`,
  `beta_fallback: 1.5`, `semis_names: [SMH, SOXX, SOXL, NVDA, AMD, AVGO]`, `governing: {TQQQ: QQQ, SOXL: SOXX}`,
  `soxx_proxy: SMH`, `live_iv_batch: 10`, `live_iv_timeout_seconds: 8`. Later tasks add keys to this block.
- [ ] **Step 2: Tests (red).** `test_blume_beta_from_price_history`, `test_short_history_falls_back_and_flags`,
  `test_soxx_uses_smh_until_it_has_history`, `test_build_inputs_adds_value_holdings_once` (C7),
  `test_stored_iv_skips_flagged_rows`, `test_live_iv_reads_model_greeks` (mocked ib, `req_fresh_mkt_data`),
  `test_live_iv_missing_is_none_not_stored` (H7/Q4), `test_live_iv_chunks_and_cancels_lines`.
- [ ] **Step 3: Code.** `shock_inputs.py`: `betas(symbols, *, vs="SPY") -> tuple[dict, set[str]]` (P5; returns flagged);
  `stored_ivs(symbols) -> dict[str, float]` (latest unflagged, decimal); `build_inputs(positions, *, nlv, value_by_name,
  ivs: dict[tuple, float] | dict[str, float], hedge_lines=()) -> ShockInputs` (positions → `BookLine`s; options keyed by
  `con_id` when live IV is supplied, by underlying when stored). `live_iv.py`: `async def live_option_ivs(ib, positions)
  -> dict[int, float | None]` by `con_id` (qualify, `req_fresh_mkt_data`, read `modelGreeks.impliedVol`, chunk of
  `live_iv_batch`, cancel each chunk, timeout per chunk), and `async def live_iv_for(ib, contract) -> float | None`.
- [ ] **Step 4: Gate, docs, commit.** Add `shock_inputs` to the deterministic fence list. Commit `feat(analytics): shock inputs, betas and live IV`.

### Task 13: `src/engine/envelope.py`, the glide and the measurement record

**Files:** Create `src/engine/envelope.py`, `src/storage/envelope_state.py`, `tests/test_envelope.py`; modify
`src/storage/models.py` (`EnvelopeSnapshotRow`), `src/orchestrator/scan.py`, `scripts/envelope.py`, docs.

- [ ] **Step 1: Tests (red).** `test_the_glide_steps_weekly_to_the_target`, `test_the_glide_starts_on_the_first_on_session_rounded_up`
  (S10 22.3 → 23.0; U_ew 1.361 → 1.37), `test_no_glide_record_while_record_mode`, `test_after_thirteen_weeks_the_limit_is_the_target`,
  `test_room_is_unmeasured_when_any_book_option_lacks_live_iv`, `test_t20_trigger_turns_the_switch_on_once` (H8),
  `test_a_snapshot_is_written_each_cycle`, `test_admits_rejects_a_put_that_breaches_l_of_t`, `test_admits_passes_a_covered_call`,
  `test_max_contracts_under_room_trims` (P3).
- [ ] **Step 2: State.** `envelope_state.py`: `GlideRecord(start_date, s10_start, uew_start, weeks, s10_target, uew_target)`
  JSON in `system_settings` key `envelope_glide`; `load_glide()`, `start_glide(result: ShockResult, today)` (idempotent),
  `limits_on(record, day) -> tuple[float, float]` (k = min(weeks, days//7); L = start − (start − target) × k / weeks),
  `glide_end(record) -> date`.
- [ ] **Step 3: Engine.** `envelope.py`: `room(inputs: ShockInputs, *, today) -> EnvelopeRoom` (enforce from
  `get_switch("envelope_enforce")`; when `on` and no glide record, `start_glide` first; limits from the record; in
  `record`, limits computed as if starting today, for the would-block record); `admits(room, inputs, add: list[BookLine])
  -> list[str]` returning any of `shock_budget` (S10_gross after > limit), `gross_budget` (U_ew after > limit),
  `t20_budget` (when `t20_limit` is on), `envelope_unmeasured`; `max_contracts_under(room, inputs, line_for_one, hard_max)
  -> tuple[int, str]`; `record_snapshot(result, room, source: Literal["stored","live"])` → `EnvelopeSnapshotRow`
  (`captured_at`, the `ShockResult` fields, limits, enforce, source); `check_t20_trigger(result)` (H8).
- [ ] **Step 4: Wire.** Each intraday scan cycle (`scan.py`, before the CSP generator runs) builds inputs from stored IV
  for the display snapshot (`source="stored"`) and, when enforce is not `off`, live IV for the gate (`source="live"`,
  Task 19 consumes it). `scripts/envelope.py show` prints the latest snapshot and glide; `envelope.py stabilisation`
  prints the three §3.8 conditions (bottoming signal from `src/regime`, the latest harness result file, "operator
  ruling required") and changes nothing.
- [ ] **Step 5: Gate, docs, commit.** ARCHITECTURE.md (`src/engine/`, `src/storage/` models). Commit `feat(engine): the envelope, its glide and its daily record`.

### Task 14: Telegram lines and `GET /envelope`

**Files:** Modify `src/notify/formatters.py`, `src/orchestrator/eod_report.py`, `src/ledger/ingest.py` (manual-buy hook)
or `src/notify/approval_service.py` (where new broker executions are seen); create `src/api/routers/envelope.py`,
`src/api/models/envelope.py`, `tests/test_api_envelope.py`, `tests/test_envelope_lines.py`; modify `src/api/main.py`,
`docs/web/openapi.json`, `web/lib/api-types.ts`, `docs/web/api.md`, ARCHITECTURE.md (commands/routes), SETUP.md.

- [ ] **Step 1: Tests (red).** `test_the_daily_line_names_every_measure_and_the_limits` (S10 gross/net, S20, G10, P20,
  T20, S-SMH, U_ew, L(t), "cash after every ITM put is assigned"), `test_the_line_labels_stored_iv`,
  `test_a_manual_buy_posts_before_and_after` (E13: a new `book="manual"` STK BOT execution → one line with S10/U_ew
  before and after and tomorrow's headroom), `test_get_envelope_reads_the_latest_snapshot`, `test_get_envelope_needs_the_owner_token`,
  `test_get_envelope_is_unknown_not_zero_with_no_snapshot`.
- [ ] **Step 2: Lines.** `formatters.format_envelope_line(snapshot) -> str` appended to the EOD Telegram message,
  followed by `format_les_line(signal)` for QQQ and SOXX from `les_state.latest_signal` (Task 10a; test
  `test_the_les_line_shows_trend_pullback_breadth_and_tier`), and `GET /envelope` carries the same two signals as `les`;
  `format_manual_buy_line(before, after, symbol, qty)`; the manual-buy check runs where the RTH ledger sweep ingests live
  executions in `approval_service` (after `ingest`), on rows tagged `manual` with `sec_type == "STK"` and side BOT,
  once per execId (`system_settings` key `envelope_manual_buy_seen`).
- [ ] **Step 3: API.** `GET /envelope` (owner token) returns `RiskEnvelopeResponse`: latest snapshot (all measures,
  gross and net, source, captured_at), limits, enforce, glide (start, end, week), switches (name, value, source), and
  `cash_after_itm_assignment`; read-only through the API's trading-DB session. Regenerate openapi and api-types.
- [ ] **Step 4: Gate, docs, commit.** Commit `feat(envelope): the daily line, the manual-buy line and GET /envelope`.

### Task 15: The envelope card (web; da-vinci)

**Files:** Create `web/features/portfolio/EnvelopeCard.tsx` (+ `.test.tsx`); modify `web/features/portfolio/PortfolioPage.tsx`,
`web/DESIGN.md`, `web/CLAUDE.md`.

- [ ] **Step 1: da-vinci.** Invoke the `da-vinci` skill first and read `web/DESIGN.md`. Never run `next build` or
  `next dev` inside `web/`; the build check is G4's scratch copy.
- [ ] **Step 2: Tests (red).** Renders S10 gross beside its limit and target, U_ew beside its limit, the other measures
  as one compact list with net beside gross, the glide week ("week 3 of 13"), "Not enforced yet" while `record`,
  unknown as a hatched n/a (never 0), the stored-IV label, and each switch's state in words.
- [ ] **Step 3: Code.** One `Card` on Portfolio after `SummaryCard`, reading `GET /envelope` with react-query; tokens
  only, figures in the mono face with `.tabular`, no new token/colour/radius.
- [ ] **Step 4: Gate, docs, commit.** Web gate, G4, `python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md`
  exits 0; DESIGN.md Surfaces > Portfolio bullet. Commit `feat(web): the risk envelope card on Portfolio`.

---

## Section E: Quote capture, E0 (Tasks 16-17) · model: sonnet (effort high)

**Reads:** spec §3.3, §3.10.4, §3.10.8.3, §3.10.0 (instrument row); `src/notify/approval_service.py` (lines 1757-1840);
`src/spreads/service.py` (lines 545-610); `src/spreads/chain.py`; `src/spreads/store.py` (lines 57-160);
`ib_async_documentation.md` (contract qualification, `reqSecDefOptParams`).

**Entry checks:** Section D exit green; `grep -n "run_capital_release(ib_scan, ib_exec, bot, chat_id)" src/notify/approval_service.py` prints a line.

**Section exit:** two commits; G1-G3. Then the early-merge question.

### Task 16: `src/hedge/` begins: XND and QQQ menu capture

**Files:** Create `src/hedge/__init__.py`, `src/hedge/capture.py`, `src/hedge/menu.py`, `src/hedge/store.py`,
`scripts/hedge_capture_report.py`, `tests/test_hedge_capture.py`, `tests/test_hedge_fence.py` (first version); modify
`src/storage/models.py` (`HedgeQuoteRow`), `src/notify/approval_service.py`, `src/common/config.py` (`HedgeCfg`),
`config/examples/risk_limits.yaml`, docs.

- [x] **Step 1: Config.** `hedge:` block, `HedgeCfg(_KeyedCfg)`: `instruments: {XND: {sec_type: IND, exchange: NASDAQ,
  trading_class: XND, multiplier: 100}, QQQ: {sec_type: STK, exchange: SMART, trading_class: QQQ, multiplier: 100}}`
  (the implementer verifies XND's contract fields with a one-off `reqContractDetails` probe through
  `scripts/hedge_capture_report.py --probe` on the paper Gateway and records the result; on failure stop and report),
  `capture_times_et: ["10:30", "14:30"]`, `capture_max_lines: 10`, `dte_window: [60, 120]`, `dte_floor: 45`,
  `long_delta: [0.15, 0.30]`, `vertical_min_width_pct: 10.0`, `quote_max_spread_pct: 8.0`. Task 33 adds the rest.
- [x] **Step 2: Tests (red).** `test_the_menu_holds_only_allowed_shapes` (outright, vertical ≥ 10% wide; no ratio,
  calendar, short-only), `test_capture_writes_bid_ask_size_per_leg`, `test_capture_stays_inside_its_line_budget`,
  `test_capture_runs_twice_a_session_at_fixed_times`, `test_the_report_picks_xnd_on_the_h4_bar`,
  `test_the_report_picks_qqq_when_xnd_fails`, `test_fewer_than_20_sessions_is_insufficient`,
  `test_hedge_imports_no_enrichment` and `test_only_src_hedge_writes_hedge_rows` (fence).
- [x] **Step 3: Code.** `menu.py::build_menu(chain, spot, cfg) -> list[HedgeMenuItem]` (pure; legs, mid debit, delta);
  `capture.py::async capture_once(ib, now)` (each instrument: chain via `reqSecDefOptParams`, the menu's legs quoted with
  `req_fresh_mkt_data`, chunked, cancelled; writes `HedgeQuoteRow(captured_at, instrument, item_key, leg con_id, strike,
  right, expiry, bid, ask, bid_size, ask_size, mid, delta, needed_contracts)` where `needed_contracts` is the bridge size
  of Task 36's rule at the latest snapshot, 0 before it exists). Called from `_intraday_scan_loop` on `ib_scan` when a
  capture time has passed and not yet run today (`system_settings` key `hedge_capture_last`). The report computes H4 and
  writes `data/envelope_reports/H4.json` (`switch="hedge_instrument"`, `value_on_pass="XND"`; a FAIL with ≥ 20 sessions
  writes a second result `H4_fallback.json` with `passed: true`, `value_on_pass: "QQQ"`).
- [x] **Step 4: Gate, docs, commit.** CLAUDE.md gains a short "hedge fence" stub (completed in Task 37). Commit
  `feat(hedge): capture XND and QQQ hedge-menu quotes twice a session`.

### Task 17: SPXW wing capture in shadow, and the E3 cost report

**Files:** Modify `src/spreads/service.py`, `src/spreads/store.py` (`SpreadWingQuoteRow`), `src/common/config.py`,
`config/examples/spreads.yaml`; create `scripts/spxw_cost_report.py`, `tests/test_spxw_capture.py`; docs.

- [x] **Step 1: Tests (red).** `test_wing_capture_quotes_spxw_25_wide_legs_beside_the_spy_candidate`,
  `test_wing_capture_never_orders`, `test_wing_capture_fits_the_spreads_line_budget`, `test_the_report_compares_cost_per_1k_of_max_loss`,
  `test_the_report_needs_15_sessions`, `test_e3_pass_needs_the_spreads_paper_bar_too`, `test_e3_pass_only_notifies` (sets
  `spxw_ready`, nothing else).
- [x] **Step 2: Code.** Key `spreads.wing_capture: {enabled: true, symbol: SPX, trading_class: SPXW, widths: [25, 10],
  xsp_width: 5}`. When the SPY baseline candidate is built, the service quotes the SPXW legs at the same distance in
  expected moves (and XSP 5-wide when its chain qualifies), within `max_market_data_lines`, and writes
  `SpreadWingQuoteRow` (spreads.db). `scripts/spxw_cost_report.py`: all-in round-trip cost (commission + Task 5 fees +
  measured crossing) per $1,000 of max loss for SPY 5-wide (6 lots), SPXW 10/25-wide, XSP 5-wide; E3 PASS per the
  Rulings; writes `data/envelope_reports/E3.json` (`switch="spxw_ready"`, `value_on_pass` `spxw` or `xsp`, or a
  `passed: false` result) and the notice says "Run Task 39 of the risk-envelope plan at a flat-book cutover".
- [x] **Step 3: Gate, docs, commit.** Commit `feat(spreads): capture SPXW wing quotes in shadow for the E3 cost test`.

**Early merge (orchestrator).** See Execution model.

---

## Section F: The envelope gate, E2 (Tasks 18-21) · model: opus (effort high)

**Reads:** spec §3.4.1-3.4.2, §3.6, §3.10.7; `src/engine/risk_engine.py` (lines 162-640); `src/engine/capital.py`;
`src/strategies/cash_secured_put.py` (lines 99-260); `src/execution/approval.py` (lines 173-320, 590-640);
`src/execution/executor.py` (lines 225-320); `src/orchestrator/scan.py` (the two `validate_candidates` calls);
`src/value/{risk,live,stage3}.py`; `tests/test_value_fence.py` (lines 45-125, 279-375); `tests/test_engine.py`,
`tests/test_regime_sizing_integration.py`, `tests/test_capital.py`.

**Entry checks:** early-merge row filled (merged or not); Section E exit green; the A2 anchors still print.

**Section exit:** four commits; G1-G3; the sizing integration suites green.

### Task 18: The erasure fix, U_ew in place of the nominal check, leverage weighting

**Files:** Modify `src/engine/risk_engine.py`, `src/engine/capital.py`, `src/strategies/cash_secured_put.py`,
`src/notify/formatters.py`, `src/api/routers/options.py` (reason words), `tests/test_engine.py`,
`tests/test_regime_sizing_integration.py`, `tests/test_capital.py`, docs.

- [ ] **Step 1: Tests (red).** `test_a_floor_lot_cannot_clear_the_gross_budget` (the HOOD case: regime stressed, unscaled
  caps pass, U_ew over its limit → rejected with `gross_budget` beside `regime_budget`), `test_combined_name_cap_survives_the_regime_rewrite`,
  `test_gross_budget_runs_without_the_value_book`, `test_gross_budget_counts_leveraged_at_leverage`,
  `test_the_wheel_no_longer_reads_max_gross_notional_pct`, `test_the_value_book_still_reads_it` (value risk unchanged),
  `test_record_mode_records_and_admits`, `test_leveraged_collateral_counts_at_leverage_in_ticker_and_csp_budgets`.
- [ ] **Step 2: Erasure (P4).** In `validate_candidates`, compute value-book reasons (`combined_name_cap`) and envelope
  reasons into a separate list `hard_reasons` and append them to `reasons` **after** the regime block and the floor-lot
  clear (after the `if reasons == ["regime_budget"]` branch). Remove the wheel's `gross_notional_cap` check and the
  `gross_cap` variable; `max_gross_notional_pct` stays in config for `src/value/` only (example comment says so).
- [ ] **Step 3: U_ew.** `validate_candidates` gains keyword `envelope: tuple[EnvelopeRoom, ShockInputs] | None = None`.
  For each opening CSP: `envelope.admits(room, inputs, [line])` → reasons `gross_budget`, `shock_budget`, `t20_budget`,
  `envelope_unmeasured` (Task 19 supplies S10; this task wires `gross_budget`); in `record` mode the reasons are written
  as `sizing_actions` kind `envelope_record` (through `src/regime/actions.py::record_action`) and not appended; `envelope`
  None with enforce `on` → `envelope_unmeasured`. Accepted lots in the batch are added to `inputs` so later candidates
  see them.
- [ ] **Step 4: Leverage weighting (§3.5).** `seed_budgets(..., leverage_of: Callable[[str], int] | None = None)` scales
  `ticker_collateral` and `csp_collateral` of a leveraged name; `max_contracts`/`_fits`/`charge` take `leverage: int = 1`
  and scale `unit_collateral`. Both callers (gate and generator) pass `leverage_factor`.
- [ ] **Step 5: Gate, docs, commit.** Reason words for `gross_budget`, `shock_budget`, `t20_budget`, `envelope_unmeasured`
  in both reason maps. STATUS.md. Commit `fix(engine): no reason erased by a floor lot; U_ew replaces the nominal gross check`.

### Task 19: S10_gross ≤ L(t) at the generator, the gate and send time

**Files:** Modify `src/strategies/cash_secured_put.py`, `src/engine/risk_engine.py`, `src/orchestrator/scan.py`,
`src/execution/approval.py`, `src/execution/executor.py`, tests (`tests/test_envelope_gate.py` new), docs.

- [ ] **Step 1: Tests (red).** `test_generator_trims_to_the_room` (P3), `test_generator_and_gate_agree` (same inputs →
  same verdict), `test_gate_rejects_above_l_of_t`, `test_above_l_of_t_no_risk_adding_open_passes`, `test_covered_calls_and_rolls_are_not_tested`,
  `test_missing_live_iv_fails_closed` (Q4), `test_send_time_regate_reprices_at_fresh_live_iv`, `test_a_long_put_creates_no_room` (H1),
  `test_off_mode_changes_nothing`.
- [ ] **Step 2: Generator.** `screen_csp_candidates(..., envelope=None)`: after `max_contracts`, call
  `max_contracts_under(room, inputs, line_for_one, contracts)`; a lower count is recorded on the `SizingNote` (binding
  `shock_budget` or `gross_budget`); zero → rejected with that reason (in `record` mode: unchanged size, recorded).
- [ ] **Step 3: Callers.** `scan.py` builds `(room, inputs)` once per cycle from live IV (Task 13) and passes it to the
  generator and both `validate_candidates` calls. `approval.process_queued_orders` builds it at send time (fresh
  positions, `live_option_ivs` on its `ib`) and passes it to its `validate_candidates`; `executor.execute_candidate`
  re-checks the candidate's own line at its fresh quote's IV with `admits` before `placeOrder` (reason recorded on the
  order detail like the live-quote re-gate).
- [ ] **Step 4: Gate, docs, commit.** Commit `feat(engine): the shock budget gates every risk-adding open, twice`.

### Task 20: Value-book buys under the envelope

**Files:** Modify `src/value/risk.py`, `src/value/live.py`, `src/value/stage3.py`, `tests/test_value_risk.py`,
`tests/test_value_fence.py`, `tests/test_value_capital_release.py`, CLAUDE.md (value fence), docs.

- [ ] **Step 1: Tests (red).** `test_a_buy_that_breaches_l_of_t_is_refused`, `test_a_buy_over_the_uew_limit_is_refused`,
  `test_envelope_reasons_are_not_fundable` (no funding request opens; `FUNDABLE` stays `{"gross_notional_cap"}`),
  `test_unmeasured_envelope_refuses_the_buy`, `test_record_mode_records_only`, fence: `test_stage3_may_import_the_shock_engine`
  and `test_value_still_imports_no_engine`.
- [ ] **Step 2: Code.** `src/value/risk.py` ctx gains `envelope: EnvelopeRoom | None` and `s10_per_dollar: float | None`
  (β × 0.10 / NLV, stock is linear); reasons `envelope_shock_budget`, `envelope_gross_budget`, `envelope_unmeasured`
  (enforce `on` only). `stage3.run_cycle` builds the room lazily: `src.analytics.shock`, `src.analytics.shock_inputs`,
  `src.storage.envelope_state`, `src.storage.envelope_switches`, `src.ibkr.live_iv` (positions with `include_value=True`;
  NLV from the account snapshot) and passes it into `live.cycle`. Same room at send time in `executor` through the
  same ctx (the value book re-validates at send).
- [ ] **Step 3: Fence.** `tests/test_value_fence.py`: stage3's lazy allowance gains those five modules; the
  `sys.modules` probe for the value process at import stays unchanged (they load only inside `run_cycle`). CLAUDE.md's
  value-fence bullet names the allowance.
- [ ] **Step 4: Gate, docs, commit.** Commit `feat(value): value-book buys pass the shock budget and U_ew`.

### Task 21: The index collateral class

**Files:** Modify `src/engine/capital.py`, `config/examples/risk_limits.yaml`, `tests/test_capital.py`, docs.

- [ ] **Step 1: Tests (red).** `test_one_qqq_lot_at_eleven_percent_needs_no_slot`, `test_a_second_lot_needs_a_slot`,
  `test_the_index_lot_still_counts_in_sector_and_envelope`, `test_smh_is_not_in_the_class`.
- [ ] **Step 2: Code.** `portfolio.broad_index_etfs: [QQQ]`, `portfolio.broad_index_etf_collateral_pct: 15.0`;
  `Caps.index_ticker_collateral` and `Caps.index_names`; in `_fits`, a listed name whose cumulative collateral is
  ≤ the index cap and that holds no position yet passes the slot test without a slot.
- [ ] **Step 3: Gate, docs, commit.** Commit `feat(engine): one broad-index lot up to 15% of NLV without a large slot`.

---

## Section G: Limits behind switches, E2 (Tasks 22-25) · model: sonnet (effort high)

**Reads:** spec §3.4.3-3.4.5, §3.5, §3.8; `src/execution/circuit_breakers.py`; `src/engine/regime_limits.py`;
`src/engine/risk_engine.py` (as changed by F); `src/storage/portfolio_snapshots.py` (lines 95-120); `src/regime/` (the
bottoming signal entry points); `src/storage/les_state.py` and Rulings L1-L4 (Task 23); `tests/test_circuit_breakers.py`, `tests/test_regime_limits.py`.

**Entry checks:** Section F exit green; `grep -n "def admits" src/engine/envelope.py` prints a line.

**Section exit:** four commits; G1-G3.

### Task 22: The slow drawdown breaker spanning books

- [ ] **Step 1: Tests (red)** in `tests/test_circuit_breakers.py`: `test_slow_leg_trips_at_the_switch_threshold`,
  `test_slow_leg_off_never_trips`, `test_a_trip_scales_the_csp_budget`, `test_a_trip_stops_spreads_entries` (the setting
  Task 3 reads), `test_only_a_human_resets_it`, `test_a_trip_is_not_a_halt`.
- [ ] **Step 2: Code.** Keys `envelope.slow_breaker: {window_sessions: 20, csp_budget_fraction: 0.5}`;
  `slow_drawdown(net_liq) -> float | None` against `window_high_net_liq(20)`; `evaluate_slow_breaker(net_liq)` sets
  `system_settings` `slow_breaker_tripped` `{tripped: true, at, drawdown_pct}` when the drawdown ≥ the switch's
  threshold, notifies once. `resolve_caps` multiplies `max_csp_collateral` by the fraction while tripped.
  `scripts/envelope.py reset-slow-breaker`. Called where `evaluate_breakers` runs.
- [ ] **Step 3: Commit.** `feat(breakers): a 20-session drawdown breaker across books`.

### Task 23: The leveraged sleeve

- [ ] **Step 1: Tests (red)** in `tests/test_leveraged_sleeve.py`: one test per §3.5 condition as revised (spec rev 3:
  above SMA200 the LES pullback is the signal and conditions 2-3 do not apply; below SMA200 the bottoming signal, σ₆₀
  drawdown and IV rank ≥ 50; DTE 7-14, delta 0.15-0.20, the fair-value floor applies, one lot per name per 3 sessions
  and ≤ 2 open, envelope pass), `test_tier_caps_csp_and_les_shares_together` (leverage-weighted CSP collateral + LES
  share value ≤ tier % of NLV), `test_washout_tier_allows_a_second_lot`, `test_below_trend_half_tier_rounds_to_zero_lots_at_todays_prices`
  (TQQQ lot ≈ 2.8% NLV at leverage > 1.5%), `test_lots_never_round_up`, `test_the_sleeve_switch_off_closes_it`,
  `test_the_load_check_accepts_the_sleeve_window`.
- [ ] **Step 2: Code.** `LeveragedSizingCfg.sleeve: {sigma_drawdown: 1.0, iv_rank_min: 50, dte: [7, 14], delta: [0.15, 0.20],
  every_sessions: 3, max_open_lots: 2}` (the cap is now the LES tier, L4; there is no `max_pct_of_nlv`); the load check
  that keeps `signal_delta_max` above `delta_min` exempts sleeve lots (sleeve delta bounds checked on their own,
  `0 < lo < hi < 1`). `regime_limits.sleeve_tier(ctx, symbol) -> float`: 0.0 unless the switch `leveraged_sleeve` is
  on; else the latest `les_signals` row of the governing index (Task 10a) gives `tier_pct` when `trend_up`, and when not
  `trend_up` the tier is `tiers.below_trend` only if the bottoming signal, the σ₆₀ drawdown (σ₆₀ = 1-year realised vol ×
  √(60/252) of the governing index, SOXX via `soxx_proxy`) and IV rank ≥ 50 all hold. `sleeve_lot(ctx, symbol)` (Task 8's
  stub) becomes `sleeve_tier(...) > 0`. `sleeve_room_usd(ctx, account, positions) = tier/100 × NLV − leverage-weighted
  (sleeve CSP collateral + LES share value from `books.les_exposure()`, Task 32a; 0 until then)`. The generator applies
  the DTE and delta window to sleeve candidates; per-trade contracts = floor(room ÷ (strike × 100 × leverage)), never a
  minimum of 1; the gate adds `sleeve_cap`, `sleeve_pace`, `sleeve_window` reasons.
- [ ] **Step 3: Commit.** `feat(regime): the leveraged sleeve, LES-tiered, behind its switch`.

### Task 24: `index_1x` multipliers and the T20 limit

- [ ] **Step 1: Tests (red):** `test_index_1x_multipliers_apply_only_when_switched_on`, `test_index_1x_records_while_off`
  (sizing_actions kind `index_1x_record`), `test_single_names_keep_the_old_multipliers`, `test_t20_limit_gates_only_when_on`.
- [ ] **Step 2: Code.** `regime.csp.budget_multiplier_by_class: {index_1x: {normal: 1.0, cautious: 1.0, stressed: 0.8, crisis: 0.5}}`
  with `index_1x` = `portfolio.broad_index_etfs`; `multipliers()` uses it when `get_switch("index_1x") == "on"`, else
  records the difference. `t20_budget` is already in `admits` (Task 13); this task adds its tests end to end.
- [ ] **Step 3: Commit.** `feat(regime): the index-class multipliers and the T20 limit behind their switches`.

### Task 25: The tech-linked cap and the stacking rule

- [ ] **Step 1: Tests (red):** `test_tech_cap_blocks_above_sixty_percent_leverage_weighted`, `test_tech_cap_off_records_only`,
  `test_stacking_halves_on_an_overlapping_expiry`, `test_stacking_blocks_on_an_itm_short`, `test_stacking_blocks_on_two_same_day_fills`,
  `test_stacking_off_records_only`.
- [ ] **Step 2: Code.** Pure `src/engine/regime_limits.py::tech_cap_reason(...)` and `stacking_action(...) -> Literal["none","halve","block"]`
  (keys `envelope.tech_cap_pct: 60.0`, `envelope.stacking: {overlap_days: 7, same_day_fills: 2}`), called by the
  generator and the gate; reasons `tech_linked_cap`, `stacking_block`; halving recorded as `stacking_halve`.
- [ ] **Step 3: Commit.** `feat(engine): the tech-linked cap and the stacking rule, behind their switches`.

---

## Section H: Replays and the harness, E1 (Tasks 26-29, 29a) · model: sonnet (effort high)

**Reads:** spec §3.4.4, §3.4.6, §3.5 (record), §3.7.1, §2.4; `src/claude/eval/sizing_counterfactual.py` (structure
only: the harness reuses its valuation pattern but does not import `src.claude`); `src/analytics/shock.py`;
`src/engine/envelope.py`; `src/engine/regime_limits.py` (Task 23-25 functions); `src/storage/price_history.py`.

**Entry checks:** Section G exit green. Each script reads DBs read-only and writes only its result file and a report
under `data/envelope_reports/`.

**Section exit:** five commits; G1-G3; `tests/test_reporting_*` and the new script tests green; `tests/test_web_fence.py::test_reporting_never_writes_anything` green.

### Task 26: The survivability harness

- [ ] **Step 1: Tests (red)** `tests/test_survivability.py`: `test_the_analytic_worst_case_uses_every_scenario`,
  `test_the_aggressive_replay_takes_every_admitted_open_at_max_size`, `test_admissions_above_the_limit_fail_the_harness`,
  `test_the_spreads_book_counts_at_two_percent_a_month`, `test_gross_and_net_are_both_reported`, `test_pass_writes_the_enforce_result` (P1/P2).
- [ ] **Step 2: Code.** `src/reporting/survivability.py` (read-only; imports `src.analytics.shock`, `src.engine.envelope`'s
  pure functions, storage readers; never `src.claude`): over the 17-month `price_history` panel, today's book revalued
  daily (the unenveloped path) and an always-most-aggressive path (every CSP the envelope admits at max size, entries at
  0.25 delta 30 DTE on `actively_wheeling` names, BS from stored IV). `scripts/envelope_harness.py` prints the table and
  writes `data/envelope_reports/harness.json` (`switch="envelope_enforce"`, `value_on_pass="on"`); `passed` is P2 **and**
  ≥ 10 `EnvelopeSnapshotRow` sessions in `record` with no P1 defect (the script counts them).
- [ ] **Step 3: Commit.** `feat(reporting): the survivability harness`.

### Task 27: The tech-cap and stacking backtest (E15)

- [ ] **Steps.** Tests `test_the_backtest_replays_the_ten_claude_cut_rows`, `test_the_false_block_rate_uses_profitable_uncut_opens`,
  `test_each_rule_writes_its_own_result`. `scripts/envelope_rules_backtest.py`: the 10 `sizing_actions` `claude_cut`
  rows and the system CSP opens 2026-10-13..2026-11-12 (orders + fills), each rule's action at that time; E15 criterion;
  writes `E15_tech_cap.json` (`tech_cap`) and `E15_stacking.json` (`stacking_rule`). Commit `feat(scripts): backtest the tech-linked cap and the stacking rule`.

### Task 28: The slow-breaker threshold replay (E14)

- [ ] **Steps.** Tests `test_threshold_choice_follows_the_rule`, `test_no_qualifying_threshold_falls_back_to_15`.
  `scripts/slow_breaker_replay.py`: the synthetic NLV of the 2026-11-12 book on the panel plus the real NLV series from
  `portfolio_snapshots`; picks per E14; writes `E14.json` (`switch="slow_breaker"`, `value_on_pass` the threshold).
  Commit `feat(scripts): pick the slow breaker's threshold by replay`.

### Task 29: The sleeve replay (E7) and the covered-call floor replay (E12)

- [ ] **Steps.** Tests `test_the_sleeve_replay_finds_the_jul_and_nov_windows`, `test_no_lots_is_insufficient`,
  `test_the_floor_replay_picks_the_lowest_passing_floor`, `test_the_leveraged_carve_out_has_its_own_result`.
  `scripts/sleeve_replay.py`: the lots `sleeve_lot` would have opened on the panel, valued under the wheel's leveraged
  rules (roll first; buy back at the 2× line if no roll), BS at stored IV; E7 criterion (plan): total P&L ≥ 0, no lot
  loss > 1% of the 2026-11-12 NLV, ≤ 2 open at once; writes `E7.json` (`leveraged_sleeve`). `scripts/cc_floor_replay.py`:
  per floor on the held names, 0.25-delta 30-day calls monthly; premium, call-aways, upside forgone, mean S10; E12;
  writes `E12.json` (`cc_basis_floor`, value the chosen floor) and `E12_leveraged.json` (`leveraged_cc_auto`). Commit
  `feat(scripts): the sleeve and covered-call floor replays`. The sleeve replay values both paths of revised §3.5
  (LES-tiered above SMA200, half tier on the bottoming path below it) from the `les_signals` logic recomputed on the panel.

### Task 29a: The LES replay (L8)

- [ ] **Steps.** Tests (`tests/test_les_replay.py`): `test_synthetic_3x_applies_the_daily_formula`,
  `test_entry_on_the_next_close_after_a_pullback`, `test_exit_on_the_second_close_under_sma200`,
  `test_pass_needs_three_sharpe_cells_and_four_drawdown_cells`, `test_writes_the_les_result_file` (`switch="leveraged_entry"`,
  `value_on_pass="on"`). `scripts/les_replay.py`: daily closes of QQQ, SOXX, TQQQ, SOXL from 1999 through
  `src/data/factory.py`'s price provider (never `yfinance` directly), cached under `data/envelope_reports/les_cache/`;
  uses `src/analytics/leveraged_entry.py` itself (no second implementation); the four cells of L8 for buy-and-hold, the
  200-day filter and LES; prints CAGR, max drawdown, Sharpe and time in market per cell (the spec §2.7 table is the
  expected output, to ±0.5 points: a bigger gap is a stop-and-report), plus the 2016-11..now breadth-tier split
  (pullback-only vs washout entries) for the record; writes `data/envelope_reports/LES.json`. Commit
  `feat(scripts): the Leveraged Entry Signal replay`.

---

## Section I: Book repair, the stock order path and LES shares, E2 (Tasks 30-32, 32a) · model: opus (effort high)

**Reads:** spec §3.7; `src/strategies/covered_call.py`; `src/notify/sender.py` (lines 174-330); `src/notify/approval_service.py`
(`handle_button`, `_process_button`, `handle_value_button`); `src/execution/order_builder.py`; `src/execution/position_manager.py`
(lines 84-140); `src/common/books.py`; `src/storage/wheel_shares.py`; `src/value/executor.py` (pattern only, not imported).
Task 32a also reads Rulings L4-L7, spec §3.5.1, `src/storage/les_state.py`, `src/execution/capital_release.py` (its
per-cycle hook) and `src/ledger/ingest.py` (the `value:` tagging it mirrors).

**Entry checks:** Section H exit green; `grep -n "def handle_button" src/notify/approval_service.py` prints a line.

**Section exit:** four commits; G1-G3; `tests/test_les_orders.py`, `tests/test_wheel_shares*.py` and the ledger suites green.

### Task 30: Tap-only repair proposals

- [ ] **Step 1: Tests (red)** `tests/test_repair_proposals.py`: `test_a_cc_overlay_at_the_floor_is_proposed_with_before_and_after`
  (S10, U_ew, L(t)), `test_the_floor_reads_the_cc_basis_floor_switch`, `test_leveraged_cc_below_basis_is_tap_only_at_delta_025`,
  `test_leveraged_cc_auto_switch_lets_it_auto_open`, `test_stop_adding_proposal_sets_a_universe_override`,
  `test_every_proposal_is_shadow_valued_tapped_or_not`, `test_a_tap_only_candidate_never_auto_queues` (sender, P10).
- [ ] **Step 2: Code.** `TradeCandidate.tap_only: bool = False`; `sender.send_candidates` puts `tap_only` candidates on
  the manual path at every autonomy level. `covered_call.screen_cc_candidates` reads `get_switch("cc_basis_floor")` for
  `min_strike_vs_basis` (the config value is the ceiling); for leveraged names with no basis floor it admits calls at
  delta ≤ 0.25, tagged `tap_only` unless `leveraged_cc_auto` is on. `RepairProposal` schema (kind
  `cc_overlay|stop_adding|trim|delever`, symbol, detail, s10/uew before-after, created_at) and `RepairProposalRow`
  (`repair_proposals`, with `shadow_value` filled daily from captured or stored marks); a daily builder
  `src/engine/repair.py::build_proposals(...)` (pure) run by the EOD; cards with `repair:<id>:approve|reject` buttons
  handled in `approval_service.handle_button` (a new prefix branch calling the existing approval path for CC overlays,
  `universe_overrides` for stop-adding, Task 31/32 executors for trims and de-lever).
- [ ] **Step 3: Docs, commit.** ARCHITECTURE.md (`src/engine/repair.py`, the model, the callback prefix), SETUP.md
  Telegram section. Commit `feat(repair): tap-only book-repair proposals with the envelope before and after`.

### Task 31: The stock order path; trims

- [ ] **Step 1: Tests (red)** `tests/test_stock_orders.py`: `test_validate_stock_order_refuses_value_shares`
  (`wheel_view` from `books.attribute`), `test_it_refuses_to_uncover_a_short_call`, `test_a_sell_lowers_s10`,
  `test_a_buy_must_pass_the_envelope`, `test_limit_at_mid_and_qualified`, `test_the_send_time_regate_uses_a_fresh_quote`,
  `test_refused_in_live_unless_tapped` (stock orders only ever from a tap, P10), `test_reconciler_ignores_stock`.
- [ ] **Step 2: Code.** `Strategy.STOCK_SELL`, `Strategy.STOCK_BUY` (excluded from `_INCOME_STRATEGIES` and every
  option monitor); `StockOrderIntent(side, symbol, qty, source: Literal["repair","les"], ref_id)` in `src/common/schemas.py`;
  `risk_engine.validate_stock_order(order: StockOrderIntent, account, positions, *, envelope) -> RiskVerdict`
  (pure, twice); `src/execution/stock_orders.py`: `build_stock_order(intent, quote) -> LimitOrder` at mid, rounded to
  the tick; `async execute_stock_order(ib, intent)` (qualify, `req_fresh_mkt_data`, re-validate, `orderRef="<source>:<ref_id>"`
  written to `OrderRow` before `placeOrder`, partial fills and unconfirmed cancels handled as the roll executor does).
  A trim proposal sizes to the shares that remove a stated number of S10 points (default 1 point) and is tapped.
- [ ] **Step 3: Commit.** `feat(execution): a gated stock order path for tapped trims`.

### Task 32: De-lever

- [ ] **Steps.** Tests `test_delever_sells_the_three_x_shares_and_buys_the_twin_up_to_equal_beta_dollars`,
  `test_the_buy_leg_waits_for_the_sell_fill`, `test_the_buy_leg_passes_the_envelope`. A `delever` proposal for every
  held leveraged ETF: SELL all (or the tapped share) through Task 31, then optionally BUY the governing twin (QQQ for TQQQ,
  SOXX for SOXL) at up to the same beta-dollars, each leg its own gated order. Commit `feat(repair): de-lever proposals`.

### Task 32a: LES share buys and trend-break sells (paper, automatic)

**Files:** Create `src/execution/les.py`, `tests/test_les_orders.py`; modify `src/common/books.py`, `src/ledger/ingest.py`,
`src/storage/wheel_shares.py`, `src/engine/envelope.py` (book assembly), `src/engine/risk_engine.py`
(`validate_stock_order`), the intraday cycle in `src/orchestrator/scan.py` (or wherever `capital_release` runs each
cycle, same hook), `tests/test_web_fence.py`/`test_value_fence.py` only if an allowance is needed (name it); docs.

- [ ] **Step 1: Tests (red).** `test_les_ref_is_its_own_book` (`les:` → `book="les"` at ingest, like `value:`),
  `test_wheel_share_count_excludes_les_shares`, `test_no_covered_call_against_les_shares`, `test_trim_never_sells_les_shares`,
  `test_envelope_counts_les_shares_at_leverage`, `test_buy_sizes_to_the_tier_room_in_whole_shares` (room ÷ (price × leverage),
  floor), `test_no_buy_below_sma200`, `test_one_buy_per_etf_per_three_sessions`, `test_buy_blocked_by_s10_or_uew_records_the_reason`,
  `test_record_mode_writes_les_record_and_sends_nothing`, `test_refused_in_live_even_with_a_tap`,
  `test_trend_break_sells_all_les_shares_next_session`, `test_a_sell_needs_no_envelope_pass`,
  `test_partial_fill_and_unconfirmed_cancel_handled_like_task_31`.
- [ ] **Step 2: Book.** `books.LES_ORDER_PREFIX = "les:"`; `attribute` and ingest tag `book="les"`; `books.les_exposure()`
  (shares and value per ETF, from the ledger rows tagged `les`); `wheel_shares` excludes `les` as it excludes `value`;
  `get_positions()` drops LES shares from the wheel's view by the same rule it uses for value shares (C7), and the
  envelope's book assembly adds them back from `les_exposure()` at leverage × the governing index β.
- [ ] **Step 3: Orders.** `src/execution/les.py::run_les_cycle(ib, account, positions)`, called once per intraday cycle
  after 10:00 ET: reads `get_switch("leveraged_entry")` (`off` → nothing; `record` → `sizing_actions` kind `les_record`
  only; `on` and paper → send). For each governing index, from `les_state.latest_signal`: a `trend_break` with LES shares
  held → one `StockOrderIntent(SELL, all LES shares, source="les")`; else a signal with `tier_pct > 0` and `trend_up`,
  pace clear, room from `regime_limits.sleeve_room_usd` > one share → one `StockOrderIntent(BUY, floor(room ÷ (mid ×
  leverage)), source="les")`. Each goes through `risk_engine.validate_stock_order` (BUY: envelope admits after the
  buy; SELL: never above the LES shares held) at decision time and again at send time on a fresh quote, then Task 31's
  `execute_stock_order` with `orderRef="les:<id>"`. `source="les"` is refused when `Config.is_live` (reason
  `les_paper_only`). One Telegram notice per order (`send_notice`), naming the signal's reasons and the tier.
- [ ] **Step 4: Gate, docs, commit.** CLAUDE.md (the `les:` book beside `value:` in the books paragraph; LES as the
  one automatic stock path, paper only), ARCHITECTURE.md (`src/execution/les.py`, the book tag), STATUS.md, SETUP.md
  (what the LES notices mean). Commit `feat(execution): LES share buys and trend-break sells, paper only`.

---

## Section J: Buy-to-open and the bridge hedge, E2 (Tasks 33-37) · model: opus (effort high)

**Reads:** spec §3.10 in full, §2.6 (the code rows); Mastermind §10.7 (the `hedge:claude:` reservation only);
`src/execution/{order_builder,roll_executor,reconciliation,capital_release}.py`; `src/ledger/ingest.py` (lines 250-320);
`src/common/books.py`; `src/ibkr/portfolio.py` (`get_positions`); `src/reporting/trade_ledger.py` (around line 834);
`src/value/stage3.py` (connect-per-cycle pattern); `tests/test_web_fence.py`, `tests/test_spreads_fence.py` (patterns).

**Entry checks:** Section I exit green; `ls src/hedge/capture.py` exists; `grep -n "hedge_quotes" src/storage/models.py` prints.

**Section exit:** five commits; G1-G3 and `tests/test_hedge_fence.py`; the reconciliation, ledger and capital suites green.

### Task 33: Schemas, tables, the book, attribution and the reconciler skip (§3.10.10 items 3, 7, 9, 10)

- [ ] **Step 1: Tests (red):** `test_reconcile_external_closes_skips_hedge_refs` (one line and a test, item 9),
  `test_get_positions_drops_hedge_positions_by_default` (by underlying for XND, by `con_id` through `hedge_view` for QQQ),
  `test_ledger_tags_book_hedge_by_ref_and_underlying`, `test_wheel_shares_ignore_hedge_rows`,
  `test_config_refuses_xnd_in_the_universe_or_spreads_book`, `test_hedge_view_opens_read_only`,
  `test_the_wheels_orders_and_fills_never_hold_a_hedge_row`, `test_trade_ledger_pairs_a_long_open_and_close` (the [U]
  of §3.10.10, written as a test; fix the FIFO if it fails), fence additions.
- [ ] **Step 2: Code.** `Strategy.HEDGE`; `HedgeCandidate` (legs, debit, max_loss = debit, scenario credits per
  {S10,S20,T20,G10,P20}, `order_ref`); tables `hedge_programme`, `hedge_orders`, `hedge_fills`, `hedge_marks` (+
  `hedge_quotes` from Task 16) written only by `src/hedge/store.py`; `src/common/hedge_view.py` (`mode=ro` on the trading
  DB file, plain SQL, imports only config): `open_hedges()`, `hedge_con_ids()`, `marks_today()`, `pnl_today()`;
  `books.is_hedge_underlying`, `books.is_hedge_order_ref` (`hedge:` prefix; `hedge:claude:` included);
  `get_positions(..., include_hedge=False)`; `ingest._tag_hedge_book` before `_tag_books`; `Config._hedge_isolated`
  (XND not in universe or `book_underlyings`); `reconcile_external_closes`: `if str(getattr(ex, "orderRef", "") or "").startswith("hedge:"): continue`.
- [ ] **Step 3: Commit.** `feat(hedge): its own book, tables, view and attribution`.

### Task 34: `validate_hedge` and the clash rules (item 4)

- [ ] **Step 1: Tests (red)** one per check: budget caps (H3), max loss = debit, no naked short leg, underlying in
  `hedge.underlyings`, contract clash both ways (`hedge_contract_clash` in `validate_candidates`), the QQQ-route rule both
  ways (`hedge_qqq_route` refuses a wheel QQQ open while a QQQ hedge is open; the hedge refuses while the wheel holds a
  QQQ short or share), DTE and delta windows, quote ≤ 8% of mid, two-sided and fresh, the stress block with the
  self-funding carve-out (H6), halt and slow breaker, hedge delta ≤ 50% of book beta-delta, `hedge:claude:` refused under
  `LIVE_TRADING=true`, every `hedge:` order refused in live, scoped out of the income gates.
- [ ] **Step 2: Code.** `risk_engine.validate_hedge(cand: HedgeCandidate, ctx: HedgeContext) -> RiskVerdict` (pure; run
  at decision and again at send on a fresh quote). Keys in `hedge:`: `underlyings: [XND, QQQ]`, `budget: {net_pct_nlv0: 1.0,
  pace_pct_per_month: 0.25, pace_months_allowance: 2, open_at_cost_pct_nlv0: 0.6}`, `stress: {vix_close: 25.0,
  vxn_percentile: 90, vxn_window_sessions: 252}`, `max_hedge_delta_share: 0.5`, `t_minus_close_sessions: 2`.
- [ ] **Step 3: Commit.** `feat(engine): validate_hedge, the only gate in front of a hedge order`.

### Task 35: The order builder and the executor (items 5, 6)

- [ ] **Steps.** Tests: `test_build_hedge_order_is_a_buy_limit_at_mid`, `test_a_vertical_is_a_bag`, `test_the_chase_never_exceeds_debit_times_1_05`,
  `test_every_leg_is_qualified`, `test_the_ref_is_written_before_place_order`, `test_partial_fill_and_unconfirmed_cancel` (the Nov 10 case).
  `order_builder.build_hedge_order(cand, quotes) -> LimitOrder` (BUY; a BAG combo for a vertical as a neutral copy of
  `build_combo_roll_order`'s shape, nothing imported from `src/spreads/`); `reprice_limit("BUY", ceiling=debit × 1.05)`;
  `src/hedge/executor.py::execute_hedge(ib, cand)` on clientId 32 (`ibkr.client_ids.hedge: 32`, P9). Commit
  `feat(hedge): buy-to-open orders and their executor`.

### Task 36: The manager and the bridge (items 8, 11)

- [ ] **Step 1: Tests (red):** `test_the_bridge_starts_when_enforce_is_on_and_the_instrument_is_set`, `test_nlv0_is_fixed_on_day_one`,
  `test_size_is_min_of_budget_and_half_the_gap_to_fifteen` (H5), `test_default_item_maximises_minimum_protection_per_dollar`,
  `test_roll_at_30_dte_sells_old_buys_new`, `test_the_stress_block_allows_only_a_self_funding_roll`,
  `test_qqq_route_closes_by_t_minus_2_and_sends_a_lapse_instruction`, `test_xnd_cash_settlement_is_booked`,
  `test_monetisation_applies_only_when_switched`, `test_the_bridge_ends_at_the_glide_end` (no new buy or roll; the open
  position sold at its roll date), `test_zero_size_for_20_sessions_posts_the_review_record`,
  `test_hedge_marks_enter_the_daily_leg_net`, `test_capital_counts_no_hedge_collateral`, `test_the_manager_idles_in_live`,
  `test_every_existing_monitor_still_skips_long_options`.
- [ ] **Step 2: Code.** `src/hedge/sizing.py` (pure: points needed, budget points, contracts, default item over the grid
  using `shock.scenario_loss` with the item's lines); `src/hedge/manager.py::async run_hedge_cycle(cfg, now)` (connect
  clientId 32, act, disconnect), called once per intraday cycle from `_intraday_scan_loop` after capital release:
  state in `hedge_programme` (`bridge` switch: off → on → ended), schedule (buy on day one, roll at ≤ 30 DTE, one
  position), the T−2 close and `exerciseOptions` lapse (QQQ), XND settlement booking, daily marks from captured quotes
  (BS labelled fallback), the review record (Task 37's report) at the end or after 20 zero-size sessions.
  `circuit_breakers`: the daily leg adds `hedge_view.pnl_today()` net; the trip card names three books.
- [ ] **Step 3: Commit.** `feat(hedge): the bridge, run by Python for the glide only`.

### Task 37: Reporting, the review record, the fence, and docs (items 10, 12)

- [ ] **Steps.** `src/reporting/hedge.py` (read-only: premium spent, value returned per pre-registered down leg, cover
  ratio at trough and exit against no hedge, the equal-S10 trim and always-on at equal spend, execution vs mid, rolling
  60-session R² of NLV on the instrument); `scripts/hedge_report.py` (prints it; `--review` posts the one-page record
  with "default: off"). `tests/test_hedge_fence.py` complete: `ast` imports (no enrichment; `src.spreads`, `src.value`
  never import `src.hedge`), a `sys.modules` probe of `src.hedge`, only `src/hedge/` constructs hedge rows. CLAUDE.md
  hedge-fence section (placement, `validate_hedge`, `hedge_view`, `hedge:`/`hedge:claude:` refs, live refusal, no
  headroom credit). ARCHITECTURE.md (`src/hedge/`, `hedge_view`, `src/reporting/hedge.py`, models, `HedgeCandidate`),
  SETUP.md (the bridge, its notices, the review), STATUS.md. Commit `feat(hedge): the record, the review and the fence`.

---

## Section K: Finish (Task 38) · sonnet (high); then opus review, sonnet fix pass

**Entry checks:** Sections A-J landed; full gates green.

### Task 38: The doc sweep

- [ ] Walk CLAUDE.md's doc-update table for every task: ARCHITECTURE.md (every new module, model, schema, route,
  config key; the `scripts/` entries), SETUP.md (scripts table, §16, the Telegram lines, the envelope and switch CLI,
  the bridge), STATUS.md (built; deferred: E3 cutover until its PASS; the research sessions; live plans for spreads and
  the hedge; the stock path's tap-only rule), UNIVERSE_RESEARCH.md, `How the scan works.md` (if `actively_wheeling`
  changes alter its worked example), CLAUDE.md (value-fence allowance, hedge-fence section, the regime-family list with
  `shock*`/`envelope`, the spreads text "risk in shares of NLV"; **and, from Section B's Task 6, the spreads fence's "the wheel learns about the spreads book only through `src/common/books.py`" must also name `src/common/spreads_view.py`, the second read-only window the breakers read, and its `tests/test_web_fence.py` rule; and, from Section F's Task 20, the value fence's bullet must name the allowance in `tests/test_value_fence.py::test_stage3_may_import_the_shock_engine`: `stage3.py` may import `src.analytics.shock`, `shock_inputs`, `src.storage.envelope_state`, `envelope_switches` and `src.ibkr.live_iv` lazily, `risk.py` the plain `src.common.envelope_types`, never `src.engine`**). Every file name written into a doc exists. Commit `docs: the risk envelope`.

Then the whole-branch review (opus), the orchestrator's confirmation of each finding, one sonnet fix pass. Ask before
merge or push.

---

## Section L: E3, spreads to SPXW and SPY to the wheel (Task 39) · model: opus (effort high) · **deferred**

**Runs only** after the E3 PASS notice (Task 17's report with `spxw_ready` set), from a fresh worktree off `main`,
with the spreads book flat in SPY, between sessions.

**Reads:** spec §3.3; `config/examples/{spreads,universe}.yaml`; `src/common/config.py::_spreads_isolated`;
`src/common/books.py`; `src/ledger/ingest.py` (`_tag_spreads`); the three spreads test files.

### Task 39: The cutover

- [ ] **Step 1: Tests (red/changed):** `test_spy_is_allowed_in_the_universe_after_the_move` (`book_underlyings: [SPX, XSP]`),
  `test_retired_spy_executions_before_the_date_tag_as_spreads` (`spreads.retired_underlyings: {SPY: <last spreads session>}`),
  `test_a_wheel_spy_order_after_the_date_is_wheel`, the isolation and fence fixtures updated (record each changed test).
- [ ] **Step 2: Config and code.** Spreads example: `underlying: SPX`, `underlying_sec_type: IND`, `trading_class: SPXW`
  (or the XSP values when `spxw_ready == xsp`), `exchange: CBOE`, `selection.width: 25.0`, `exits.let_expire: true`,
  `gex.scale_to_underlying: 1.0`, `book_underlyings: [SPX, XSP]`, `retired_underlyings`; `_tag_spreads` honours the
  dated rule; `portfolio.broad_index_etfs: [QQQ, SPY]`; universe example: SPY into `indexes`, `would_own`,
  `actively_wheeling`, `sectors: SPY: index`, the reservation comment removed; `market_data.reference_iv_symbols: []`.
- [ ] **Step 3: Docs.** CLAUDE.md spreads fence ("SPX, XSP"), ARCHITECTURE.md, SETUP.md §16, UNIVERSE_RESEARCH.md,
  `_UNIVERSE_CONTEXT`. Commit `feat(spreads): move the book to SPXW and free SPY for the wheel`.
- [ ] **Step 4: Cutover (operator).** Private configs edited to match; `./ibkr restart` (both processes; daemons do not
  hot-reload); first session watched.

---

## Operator to-dos

1. **Private `config/spreads.yaml`:** leave `mode: paper` (the `spreads_paper` switch holds it in shadow until the bar,
   E1) and add the Task 3-5 keys, or copy them from the example.
2. **Private `config/universe.yaml`:** the Task 9 edits (E8). Then `python -m scripts.backfill_prices` and
   `python -m scripts.backfill_iv --symbols SPY,SOXX`.
3. **Private `config/risk_limits.yaml`:** the `envelope:`, `hedge:`, `iv_sanity:`, `leveraged_sizing.csp_mode` and
   `portfolio.broad_index_*` keys (code defaults match the example if a key is absent).
4. **Private `config/settings.yaml`:** `market_data.reference_*_symbols`, `ibkr.client_ids.hedge: 32`.
5. `./ibkr restart` after the early merge and after the final merge (trading service first, then the API).
6. **The spreads backtest:** subscribe to ThetaData Options Standard, run Theta Terminal, then
   `python -m scripts.spreads_backtest --start <earliest> --end <latest> --report`. Expect harness fixes; record them.
7. **Read** each PASS/FAIL notice; reverse any switch with `python -m scripts.envelope switch <name> <value>`.
8. **Research sessions (E1, Q5):** the wheel-faithful index-class replay (E10) and the hedge monetisation replay (H5)
   on S&P 1991-2026 and NDX 2002-2026, run as Claude Code research sessions in the scratchpad, each writing its
   `EnvelopeReportResult` to `data/envelope_reports/E10.json` / `H5.json` (`switch` `index_1x` / `hedge_monetisation`).
9. **E3:** on the PASS notice, run Section L at a flat-book cutover.
10. **E4:** read the bridge review record. Continuing the bridge needs a fresh ruling.
11. **LES (spec rev 3):** after the early merge, run `python -m scripts.breadth backfill` once; private
    `config/risk_limits.yaml` gains `regime.leveraged_entry` (Task 10a; defaults match the example). Each quarter
    (the Nasdaq-100 rebalances in March, June, September and December), run `python -m scripts.breadth refresh-constituents`
    and commit the list. `leveraged_entry` turns `on` from Task 29a's PASS, and sells as well as buys, in paper only;
    reverse it with `python -m scripts.envelope switch leveraged_entry record`.
12. **Nasdaq-100 constituent list (Task 10a Step 1, not built):** `config/breadth_constituents.yaml` does not exist.
    No source the build could reach gave a verified list (the Wikipedia article carries no components table; Nasdaq's
    API was refused), and the plan forbids inventing one. Write it by hand from Nasdaq's own list (`as_of`, `source`,
    `ndx: [...]`, 100-102 tickers) and commit it. Until it exists the nightly own count is skipped and the oscillator runs on
    the thetrading.tools history alone, so a session the history lacks leaves the washout stale and the LES tier at the 3% pullback.
13. **BLS dates (Task 2):** spot-check the 39 CPI/PPI/NFP rows in `config/macro_calendar.yaml` against bls.gov (read twice
    through a summarising fetch, never raw HTML); fill the SPXW/XSP exchange fees in the private `config/spreads.yaml`
    before Task 39 (Task 5).

## Self-review (run by the plan's author, 2026-11-14)

- **Spec coverage.** §3.2 a-h → Tasks 2-7 (d's `let_expire` → Task 39); §3.3 → Tasks 17, 39; §3.4.1-3.4.3 → Tasks 11-13,
  18-19, 24; §3.4.4 → Tasks 25, 27; §3.4.5 → Tasks 22, 28; §3.4.6 → Task 26; §3.4.7 → Task 14 (the cash fact; PM and
  `cash_reserve_pct` need no code); §3.5 → Tasks 8, 18, 23, 29; §3.6 → Tasks 9, 21; §3.7 → Tasks 29-32; §3.8 → Tasks 13
  (stabilisation check), 24; §3.10 → Tasks 10, 12, 16, 33-37; §4 E0-E4 → Roadmap. Left to the Mastermind: HP, Track D,
  Claude's hedge roles, R-rungs, brief surfaces (the `hedge:claude:` reservation and its live refusal are built).
- **Not grounded in code (checked by the implementer):** XND's IBKR contract fields and paper quotes (Task 16 probe);
  SPXW/XSP exchange fees (Task 5, `null` until filled); the exact FOMC/BLS/BEA dates (Task 2 fetches); IBKR's paper
  behaviour for `exerciseOptions` lapse (Task 36 tests mock it; the first live use is watched); whether the trade
  ledger's FIFO pairs a long option (Task 33 writes the test).
- **Not prototyped.** Line anchors were read at 854d493; no step was run.
