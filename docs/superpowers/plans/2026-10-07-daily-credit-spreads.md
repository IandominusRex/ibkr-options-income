# Daily Credit Spreads (SPY 0DTE) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Keep the Progress log below current without being asked** (see its first paragraph).

## Progress log

**For agentic workers: update this after every task, unprompted.** When a task is done, tick its
step checkboxes (`- [x]`), set its row to ✅ with the commits, the gate result and the date, list
every ruling you made (any deviation from the task text, and why), and commit this file with the
task or right after it. If you stop part-way through a task, mark it 🟡 and name the next step.
Resume at the first row that is not ✅, and check it against `git log --oneline main..feat/daily-credit-spreads`.

**Where the work lives:** branch `feat/daily-credit-spreads`, in the git-ignored worktree
`.claude/worktrees/daily-credit-spreads`. This copy of the plan, on that branch, is the live
tracker; the copy on `main` stays unticked until the branch merges.

**Setting up a fresh worktree** (otherwise 4 tests in `tests/test_monitor*.py` fail with
`no such table: fills`, because they read the real `data/income_system.db`, which is git-ignored):
- `ln -s "<main checkout>/.venv" .venv`, since the venv lives in the main checkout.
- `IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"`
- `ln -s "<main checkout>/web/node_modules" web/node_modules`, for the web tests (Task 3 on).

| Task | Status | Commits | Date | Gate |
|---|---|---|---|---|
| 1 Spreads config, book helpers, wheel-side guards | ✅ done | `8baac24` (code), then docs + this log | 2026-10-08 | pytest 2744 passed, 1 skipped; ruff and mypy clean |
| 2 `get_positions` filter | ✅ done | `f7127f1` (code), then docs + this log | 2026-10-08 | pytest 2749 passed, 1 skipped; ruff and mypy clean |
| 3 Ledger `spreads` book | ✅ done | `dd471f8` (code), then docs + this log | 2026-10-08 | pytest 2752 passed, 1 skipped; ruff and mypy clean; web 487/487 |
| 4 Schemas and same-day pricing | ✅ done | `1875ffc` (code), then docs + this log | 2026-10-08 | pytest 2761 passed, 1 skipped; ruff and mypy clean |
| 5 GEX levels | ✅ done | `44ede26` (code), then docs + this log | 2026-10-08 | pytest 2771 passed, 1 skipped; ruff and mypy clean |
| 6 Candidate selection | ⬜ | | | |
| 6A Session tape and entry trigger | ⬜ | | | |
| 7 Deterministic spreads gate | ⬜ | | | |
| 8 Exit manager and reconciliation | ⬜ | | | |
| 9 Spreads database | ⬜ | | | |
| 10 IBKR I/O | ⬜ | | | |
| 11 Combo orders and executor | ⬜ | | | |
| 12 Telegram notifier | ⬜ | | | |
| 13 Service, entrypoint, supervisor | ⬜ | | | |
| 14 Performance report | ⬜ | | | |
| 15 ThetaData client | ⬜ | | | |
| 16 Minute replay and backtest script | ⬜ | | | |
| 17 Fences, docs, full gate | ⬜ | | | |

**Rulings (Task 1):**
- **Docs moved forward from Task 17.** `CLAUDE.md` requires the docs to match the code at every
  stopping point, so the Task 1 share of Task 17's doc work landed with Task 1. When you reach
  Task 17:
  - **Step 3.2:** skip it. The `books.py` row is already in ARCHITECTURE's `src/common/` table,
    verbatim.
  - **Step 3.1:** replace the interim "in progress" `spreads.yaml` row in ARCHITECTURE's
    `config/` table. Don't add a second row.
  - **Step 4:** skip the `book_underlyings` troubleshooting row, which is already in SETUP.
    SETUP §2b's copy loop also already includes `spreads`.
  - **Step 5:** delete STATUS's "In progress (2026-10-08 — daily credit spreads…)" section when
    you add the "Built" section.
- **Left as is:** `config/universe.example.yaml` line 31, a tier comment that still names SPY as a
  `safe_bets` example. It isn't one of the three edits Step 4 lists, and the isolation validator
  reads lists only.
- **Private `config/settings.yaml` not edited.** The worktree-isolated session can't write the
  main checkout, so this moved to the operator to-dos below.

**Rulings (Task 2):**
- **Docs moved forward again** (same reason as Task 1): ARCHITECTURE's `src/ibkr/` `portfolio.py`
  row and `scripts/` `healthcheck.py` row now describe `include_spreads`, and STATUS's "In progress"
  section gained a bullet. Task 17 lists neither row, so it has nothing to skip; its Step 5 deletes
  the STATUS section as already noted.

**Rulings (Task 3):**
- **`docs/web/openapi.json` regenerated and committed with the code.** The plan doesn't list it,
  but `tests/test_openapi_current.py` fails until the checked-in schema matches the app. The diff
  is only `"spreads"` added to the four `book` enums.
- **`web/lib/api-types.ts` generated from that file** (`npx openapi-typescript
  ../docs/web/openapi.json`) instead of starting the API. The output differs from the old file in
  exactly the four unions the plan predicted.
- **Step 3's failure message differed from the plan:** the builder test failed with
  `{'manual'} != {'spreads'}`, not a pydantic `literal_error`, because the builder collapsed every
  non-`system` book to `manual` before `LedgerTrade` saw it. Same root cause; nothing changed.
- **Docs moved forward again:** ARCHITECTURE's `ingest.py`, `trade_ledger.py`,
  `routers/ledger.py`, ledger-schemas and web-ledger rows, plus STATUS's ledger line and
  "In progress" bullet. Task 17 lists none of these rows.

**Rulings (Task 4):**
- **Docs moved forward again.** ARCHITECTURE's `src/common/` `schemas.py` row and Data-flow table
  now describe the spreads types, and a new interim `src/spreads/` section sits above `src/ops/`
  listing only `__init__.py` and `pricing.py`. Each later task adds its own rows to it. When you
  reach Task 17 **Step 3.3:** don't insert a second section; replace the interim one (its heading
  carries "IN PROGRESS") with the plan's full file table. STATUS's "In progress" section gained a
  bullet.
- **No deviation in code.** The tests, schemas and `pricing.py` are the plan's text verbatim; Step 2's
  failure was the expected `ImportError: cannot import name 'ChainOption'`.

**Rulings (Task 5):**
- **Docs moved forward again:** ARCHITECTURE's interim `src/spreads/` section gained the `gex.py`
  row, and STATUS's "In progress" section a bullet. Task 17 Step 3.3's full table replaces them.
- **No deviation in code.** Tests and `gex.py` are the plan's text verbatim (`ruff format` only
  re-wrapped one line). Step 2's failure was the expected `ModuleNotFoundError: No module named
  'src.spreads.gex'`.
- **Pre-flight:** the three config fields Task 5 reads (`gex.scale_to_underlying`,
  `gex.flip_search_pct`, `selection.em_straddle_factor`) all exist in Task 1's `SpreadsCfg` and in
  `config/spreads.example.yaml`.

**Notes for later tasks:**
- **Task 17 Step 4:** SETUP's Troubleshooting table has three columns (Symptom | Likely cause |
  Fix), but the plan's rows have two. Split each row into cause and fix.
- **Pre-flight (2026-10-08):** every spreads config field that Tasks 2–17 consume (31 of them)
  exists in Task 1's models.
- **Existing ledger rows are not retagged** (STATUS lists it as not handled). A re-import retags
  a row only when it backfills the order id. The operator's ledger had no SPY/SPX/XSP rows on
  2026-10-08 (checked read-only), so nothing is mis-booked today.
- **`npx tsc --noEmit` in `web/`** reports 9 errors, all in test files under `components/options/` and
  `app/api/`, none touched by this branch. Vitest doesn't type-check, so `npm test` stays green.
- **For Task 13 and the final review: a separation gap the Design table doesn't list.** The
  wheel's `src/execution/reconciliation.py` matches a recovered fill to a stuck wheel `OrderRow`
  by `orderId` alone (`_exec_matches_candidate`), and the ledger's live sweep also reads
  `reqExecutions`. If the wheel's `reqExecutions` also returns clientId 30's executions, a spreads
  fill whose order id equals a stuck wheel order's `ib_order_id` could be recovered as that wheel
  order's fill. The ledger side is already safe, because Task 3 tags by underlying. During the
  Task 11 Step 9 paper check, see whether the wheel process receives the spreads fill. If it
  does, gate the reconciliation's order-id match on the contract too.
- **Self-review of Tasks 2–3 (2026-10-08), two minors deferred:**
  - The portfolio snapshot excludes spreads legs, so an open spread has no ledger mark. The summary's
    `unrealized_usd` reads n/a while one is open, but only once the snapshot account matches the
    ledger account (live).
  - `test_only_the_healthcheck_asks_for_spreads_positions` greps the literal
    `include_spreads=True`, so a caller that passes a variable would slip past it.

- **Self-review of Tasks 4–5 (2026-10-08), no Critical/Important; one note for Task 13.**
  `gamma_flip` evaluates net GEX at 121 spots, and every evaluation recomputes gamma for every
  option with scipy scalar calls. Measured: 0.62 s for a 320-option SPX snapshot (two expiries, ±3%
  on a 5-point grid); a full chain could take a few seconds. It runs about once an hour (the map
  refresh), but it is synchronous, so **Task 13 should call `build_levels` through
  `asyncio.to_thread`** (or otherwise off the event loop) so a map refresh cannot stall the
  ib_async heartbeat. `regime_at` is a single pass and is cheap.

**Operator to-dos:**
- [ ] Add `spreads: 30` under `ibkr.client_ids` in your private `config/settings.yaml`. It is
  needed before Task 13's service runs, and harmless now.
- [ ] After the merge, `cp config/spreads.example.yaml config/spreads.yaml`. Until then, every
  process logs the usual "config/spreads.yaml not found; using the shipped defaults" warning.

**Goal:** Add a second trading system for same-day (0DTE) SPY credit spreads. It shares the wheel's IBKR paper account and IB Gateway but never touches the wheel's positions, budget or decisions. It places short strikes outside dealer-gamma "action zones", is gated by its own deterministic rules engine, and shows up in the trade ledger as a separate `spreads` book.

**Architecture:**
- **New package:** `src/spreads/`, a self-contained package with its own process (`scripts/run_spreads.py`), clientId 30, SQLite file (`data/spreads.db`), config file (private `config/spreads.yaml`, committed template `config/spreads.example.yaml`) and Telegram thread.
- **Pure pipeline:** chain snapshot, then GEX levels, then candidate verticals, then a deterministic gate, then an executor, then the exit manager.
- **Separation by underlying:** the wheel and the spreads book never share an underlying. The wheel trades UPRO for S&P 500 exposure (never SPY); the spreads book trades SPY (see "Underlying decision") and reads SPX for gamma.
- **Wheel side:** gains a single default filter in `get_positions` plus a rules-engine reject.
- **Ledger:** tags spreads executions by underlying.
- **Rollout:** ships in `shadow` mode, which records would-be trades with simulated, cost-realistic fills. `paper` mode places real orders on the paper account.

**Tech Stack:** Python 3.12, ib_async (combo/BAG orders, `reqSecDefOptParamsAsync`), SQLAlchemy 2 / SQLite (separate engine), Pydantic v2, scipy (Black-Scholes), httpx (ThetaData v3 REST), python-telegram-bot, pytest, Next.js (one ledger filter option).

**Spec:** No separate spec file. The design was settled in the 2026-10-07 feasibility conversation and is written out in full under **Design** below. Executors treat that section as the spec.

**Amendment (2026-10-07, after comparing the plan with OPG's published journal):** the operator chose to adopt OPG's entry logic and keep this plan's risk and exit rules. What changed, and where:

| Change | Tasks |
|---|---|
| **Entry trigger:** sell only after a move of at least `entry.min_move_em` × the day's expected move (gap included), once it has **stalled** for `entry.stall_minutes`, and never against a move beyond `entry.max_move_em` (a trend day). `entry.trigger: always` keeps the original rule for comparison | 1, 4, **6A** (new `src/spreads/tape.py`), 6, 10, 13, 16 |
| **One side per day:** the trigger picks one side, and the gate refuses the other side once a spread has opened | 4, 6A, 7 |
| **Opening window:** map at 09:31, entries from 09:35 (still only when the trigger fires) | 1, 7 |
| **Negative gamma is traded**, not skipped (`gex.negative_gamma_action: allow`), and tagged on every trade so it can be analysed later. Operator decision: paper account, gather data | 1, 7, 9, 12, 14 |
| **Event blocks with a time:** `risk.events` blocks the whole day, or only until `until` ET | 1, 7 |
| **Maximum hold time:** `exits.max_hold_minutes` closes a spread held too long | 1, 4, 8, 13 |
| **Every trade logged with analysis tags:** side, trigger and move size, gap day, gamma regime and levels at entry, minutes after the open, holding time, worst mark (MAE). Report breakdowns and a CSV export | 4, 9, 13, 14, 16 |
| **50% vs 80% profit-take (and the other switches) comparable in one command each:** backtest `--profit-take`, `--trigger`, `--negative-gamma` | 16, 17 |
| **Config follows the repo's private/example split** (commit `bc8e9ae`): the plan ships `config/spreads.example.yaml` and edits `config/settings.example.yaml`; the operator's own `config/spreads.yaml` is git-ignored | 1, 17 |

## Before you start

- Execute in an isolated worktree (`superpowers:using-git-worktrees`), branch `feat/daily-credit-spreads`.
- Edits to existing files are located by **anchor strings**, never line numbers. Re-read the anchor before editing, because line numbers in this plan are for orientation only.
- Read `CLAUDE.md` sections "Core invariant", "The fence", "Analytics tiers" and "The `src/ledger/` fence" first. This plan adds a parallel fence for `src/spreads/` and must not weaken any existing one.
- `ib_async_documentation.md` (repo root) is the reference for every IBKR call used here: `Index`, `Option`, `ComboLeg`, `reqSecDefOptParamsAsync`, `placeOrder`, `cancelOrder`, `Trade.orderStatus`, `commissionReportEvent`, `positions()`, `accountSummaryAsync`.

## Design

### Why SPY, and why separation by underlying works

| Decision | Reason |
|---|---|
| Trade **SPY** 0DTE (operator decision, 2026-10-07) | The tightest quotes of the three ($0.01–0.03 near the money) and the deepest 0DTE volume. It is American-style and settles in shares, so the plan never holds a SPY spread into the close (`exits.let_expire: false`, everything closed by the 15:45 time stop) and alerts if one is still open after that. A 5-point spread risks $500 per contract. |
| Read **SPX (SPXW dailies)** for GEX | The dealer gamma that matters sits in SPX. SPX levels × the live SPY/SPX ratio give SPY levels (SPY trails SPX/10 as dividends accrue, by more than the 0.1% wall buffer). |
| **Book = underlying** | IBKR positions carry no order tag, and IBKR nets same-contract positions across systems. The wheel's `config/universe.yaml` and `spreads.book_underlyings` are disjoint, which is enforced at config load. So the underlying alone decides the book for positions, fills and statement rows. Order IDs are *not* used, because they are only unique per clientId and the two systems place orders from different clientIds. |

### Underlying decision: SPY vs SPX vs XSP (researched 2026-10-07, status: **SPY, confirmed by the operator 2026-10-07**)

Facts that frame it. The wheel's `config/universe.yaml` no longer lists `SPY` (the operator wheels UPRO
for S&P 500 exposure and never wheels SPY), so SPY is free to be reserved by this book. The operator's
buy-and-hold lines are CSPX and QQQM (shares), which do not constrain the choice. The system runs
unattended at the US close (the operator is in SGT). At research time the per-trade risk cap was $500;
it is now 10% of the book's own capital (Design → "Position sizing"), about 20 SPY spreads at the
starting $100,000. The private `config/universe.yaml` already leaves SPY out, but the committed
`config/universe.example.yaml` still listed it and must drop it (Task 1).

| | SPY | SPX (SPXW) | XSP |
|---|---|---|---|
| Exercise / settlement | American, **physical shares** | European, cash | European, cash |
| Typical near-the-money bid/ask | $0.01–0.03 | $0.10–0.50 (sources range to $0.50–2.00 ATM) | $0.05–0.15 |
| Average 0DTE volume (late 2025, per a blog) | >3M contracts/day | >1.5M/day | 50k–150k/day |
| Width that risks $500 per contract | **$5 wide** | **5 SPX pts** (a much tighter structure) | **5 XSP pts** |
| Structure equal to the other two | = XSP 5-wide = SPX 50-wide ÷ 10 | needs ≈ $5,000 risk to equal them | = SPY 5-wide |
| Tax / exercise nuance | Early assignment, ex-dividend risk | None | None |

Findings:
1. **The operator's premise holds: XSP's spreads are wider.** The same sources put XSP at about
   $0.05–0.15 against SPY's $0.01–0.03. SPY and XSP are the same $500-risk structure, so XSP buys
   cash settlement at a measurable execution cost. Illustration (author's arithmetic on those blog
   ranges, not a measurement): paying half the quoted spread on four legs of one contract costs about
   $4 on SPY and about $20 on XSP, against a credit near $100 and $2.60 of commission (IBKR flat $0.65
   per contract, per leg). That is roughly 4% versus 20% of the credit.
2. **SPX is the best instrument but the wrong size for a $500 cap.** Dollar spreads look wide, but per
   unit of notional they are comparable or tighter (a $1 SPX spread is ~0.013% of notional against
   ~0.027% for a $0.02 SPY spread). But at $500 risk it only buys a 5-point spread, whose credit is a
   fraction of the SPY/XSP structure while commission and slippage stay about the same. SPX is the
   right choice if the per-trade cap rises to roughly $5,000. It is also the GEX source, so it needs no
   index-to-ETF scaling.
3. **SPY's real cost is physical settlement, and it is manageable but not zero.** A 0DTE SPY option
   that is $0.01 or more in the money at expiry is exercised automatically. A spread that finishes
   *fully* in the money nets out (the long leg's exercise offsets the short leg's assignment). The
   dangerous case is **partial in-the-money**: price between the two strikes at the close, which leaves
   100 shares per contract (about $69,000 at SPY 690) to be held overnight with nobody awake. Early
   assignment of a short in-the-money leg is also possible, and short calls near an ex-dividend date
   carry extra risk.

**Decision: trade SPY, with these guardrails (applied in the task bodies below).** Switch to SPX only
if per-trade size grows to where SPX's larger contract is the better fit.
- `config/spreads.example.yaml`: `underlying: SPY`, `underlying_sec_type: STK`, `trading_class: SPY`,
  `exchange: SMART`; `book_underlyings: [SPY, SPX, XSP]` (all three reserved; none may appear in
  `universe.yaml`, so SPY also leaves the committed example universe); `selection.width: 5.0`
  ($500 gross risk per contract). Task 1.
- **Never leave a SPY spread to expire.** `exits.let_expire: false`: the time stop (15:45 ET)
  closes every position, because the "cash-settled, no assignment to avoid" assumption behind
  letting a far-OTM spread expire does not hold for SPY. Task 8.
- **Alert if anything is still open after the time stop** (a close that did not fill): the operator
  must close it by hand before 16:00 or risk assignment. Task 13. (A short leg going in the money
  earlier in the day is already closed by the short-strike-touch exit.)
- **Live SPY/SPX ratio, not a constant.** XSP is exactly SPX/10, but SPY drifts from SPX/10 as
  dividends accrue (a few tenths of a percent), which is larger than `wall_buffer_pct` (0.1%) and
  `flip_buffer_pct` (0.2%). `gex.scale_to_underlying: null` means "SPY spot ÷ SPX spot, recomputed
  with every map", stored on the levels as `GexLevels.scale`. Task 5.
- **No new call spreads on the day before or the day of an SPY ex-dividend date**
  (`risk.ex_dividend_dates`, operator-maintained; SPY goes ex quarterly). Task 7.
- Spot and session stats come from a SPY **stock** contract (`underlying_sec_type: STK`), not an
  index. Task 10.
- Confirm the live account can carry about $70,000 of residual shares per contract overnight
  before ever going live (assignment if a close fails).
- **Measure before trusting the blogs:** the sources are retail trading blogs and they disagree on
  SPX spreads. Shadow mode should log the real quoted spread of the legs it would trade (and a few
  SPX and XSP comparison legs) for a week before `mode: paper`.

Switching the traded leg to SPX later is configuration, not code: `underlying: SPX`, `underlying_sec_type: IND`,
`trading_class: SPXW`, `exchange: CBOE`, `gex.scale_to_underlying: 1.0`, `backtest.trade_scale: 1.0`,
`exits.let_expire: true` (cash-settled), and re-derive `selection.width` in SPX points. The
percentage risk caps carry over unchanged.

Tax and holding notes (general information from public articles, not advice): the Section 1256 60/40
treatment attached to SPX options is a US-taxpayer rule and is unlikely to matter to a Singapore
resident. The US non-resident estate-tax exposure (USD 60,000 exemption) and 30% dividend withholding
apply to *shares* such as SPY, which matters only if an assignment ever leaves the account holding
some.

Sources: [Trading Block: 0DTE SPY vs SPX](https://www.tradingblock.com/blog/0dte-spy-vs-spx-options),
[TradeStation: SPY vs SPX](https://www.tradestation.com/insights/2025/05/28/spy-vs-spx-options-explained/),
[Option Alpha: SPX vs SPY for 0DTE](https://optionalpha.com/blog/spx-vs-spy-for-0dte-options-trading-key-differences-day-traders-should-know),
[Option Alpha: 0DTE partial in-the-money assignment](https://optionalpha.com/learn/0dte-partial-in-the-money-assignment),
[SPXY Trader: XSP vs SPX](https://spxytrader.com/content/intro/xsp-vs-spx-options),
[Cboe: dividend risk on short American-style options](https://www.cboe.com/insights/posts/dont-get-stuck-paying-the-dividend-on-your-short-trade),
[Cboe: Mini-SPX (XSP)](https://www.cboe.com/tradable_products/sp_500/mini_spx_options/european_style),
[StashAway: SG investor dividend and estate tax on US equities](https://stashaway.sg/r/dividend-withholding-tax-estate-tax-us-equities-singapore).

### Data flow (one trading day, all times ET)

```
09:31  map:     SPX chain (today + next expiry, ±3%) → OI + IV per strike → per-strike dealer GEX
                → net GEX, gamma flip, call wall, put wall  (× live SPY/SPX ratio → SPY units)
                SPY chain (today, ±3%) → ATM straddle → expected move
                the day's FIRST expected move is the trigger's yardstick (day_em, kept in spreads.db)
                map refreshes every 60 min (gamma recomputed at the new spot; OI is daily)
every 30 s (09:31–15:45):  SPY → last, open, high, low, prior close → session tape
09:35–13:30  entry trigger (pure, no I/O): has price moved ≥ 0.5 × day_em away from the prior
                close / today's high (puts) or low (calls), stalled ≥ 10 min, and stayed ≤ 1.5 × day_em?
                → one side, against the stalled move (or both sides when entry.trigger = always)
             only when armed (at most every 5 min): SPY chain → that side's candidate beyond
                max(expected move, wall) → rules gate (incl. one side per day, event windows,
                no calls around ex-dividend) → size = 10% of the book's capital ÷ max loss per contract
                → executor (shadow: simulated fill | paper: BAG combo order, re-gated on a fresh quote)
                → position stored with its entry tags (trigger, move size, gap, regime, levels)
every 30 s:  open spreads → fresh leg quotes → worst mark (MAE) → exit manager
                (profit take 50% / stop at 2× credit / short-strike touch / max hold 150 min
                 / 15:45 time stop closes everything: SPY is never left to expire)
                anything still open after 15:45 → alert: close it by hand before 16:00
16:10  Telegram daily summary
```

### Separation guarantees (the wheel side)

| Coupling found in the 2026-10-07 investigation | Fix in this plan |
|---|---|
| `IntradayMonitor` subscribes to and alerts on every short option | `get_positions()` drops spreads-book contracts by default (Task 2) |
| `seed_budgets` charges a short put `strike × 100` as CSP collateral, so a SPY short put would consume ~$69k of wheel budget | Same filter (Task 2) |
| Profit-take, rolls, approval re-gate, scan, EOD all read `get_positions` | Same filter (Task 2) |
| A web universe override could add `SPY` (or `XSP`/`SPX`) to the wheel | Rules engine rejects with `reserved_for_spreads_book` (Task 1), and config load refuses the overlap in YAML |
| Ledger `_tag_books` matches by `ib_order_id`, which can collide across clientIds | `_tag_spreads` runs first, and `_tag_books` never retags a spreads row (Task 3) |
| Market-data lines are shared per login (~100) | Spreads holds at most `max_market_data_lines` (30) at once. Config load refuses `chain_batch_size + 30 > 95` (Task 1) |
| Gateway restarts (`src/ops/gateway_control.py`) drop every connection | The spreads service reconnects, re-reconciles against the broker, and blocks entries until consistent (Task 13) |
| Account margin is shared | Not separated. Spread margin reduces the wheel's `ExcessLiquidity` budget, and spreads stop entering below `min_excess_liquidity_usd`. Both directions are conservative, and this is documented in `STATUS.md` |

### GEX model (standard retail model, documented limits)

- Per-strike GEX = `Γ(S, K, T, σ) × OI × 100 × S² × 0.01`, calls `+`, puts `−` (dealers assumed long calls, short puts).
- Γ is recomputed locally from Black-Scholes with **fractional-day** `T`, because the existing `analytics.black_scholes.bs_gamma` takes integer DTE and returns `None` at 0 DTE.
- **Limits:**
  - Open interest is the prior close's figure (OPRA publishes ~06:30 ET).
  - Intraday 0DTE flow is invisible.
  - Cboe's own data shows 0DTE customer flow is balanced.

  So GEX is used as a **strike-placement guide and a tag**, never as a price target. Spot within `flip_buffer_pct` of the flip means **no new entries**. **Negative gamma is traded by default** (`negative_gamma_action: allow`, operator decision 2026-10-07) and every such trade carries `regime = "negative"` in the trade log, so shadow/paper/backtest results can be split by regime before anyone decides to skip it. `skip` restores the stricter rule.

### Entry rules borrowed from OPG (amendment, 2026-10-07)

OPG's journal (Jul 14 – Oct 5, 2026) shows the *when* and *which side* of his trades are worth copying, and his size (68–131% of the account at risk per trade) and discretionary stops are not. So this plan keeps its own risk caps and mechanical exits and adds:

| Rule | Why (from his journal) | Config |
|---|---|---|
| Sell only **after a move** of at least `min_move_em` × the day's expected move. A put spread needs a drop from the higher of the prior close and today's high; a call spread needs a rise from the lower of the prior close and today's low (so a gap counts) | "Play the tips": after a fast move premiums are inflated and part of the move is done; mean reversion, IV contraction and decay help | `entry.trigger: move`, `entry.min_move_em: 0.5` |
| Only once the move has **stalled**: no new low (puts) or new high (calls) for `stall_minutes` | His first loss: selling calls into a market that kept making new highs | `entry.stall_minutes: 10` |
| Never against a move beyond `max_move_em` × the expected move | "Respect the trend on strong days" | `entry.max_move_em: 1.5` |
| **One side per day**: the trigger picks the side against the most recent stalled move; once a spread opens, the gate refuses the other side | Selling both sides means one side always loses on a trend day | `risk.one_side_per_day: true` |
| Entries from **09:35**, first map at **09:31** | Premiums are highest in the first minutes; the quote-width gate still rejects a too-wide opening market | `schedule.map_time`, `schedule.entry_start` |
| **Event blocks with a time** (whole day, or until HH:MM ET) | He skips FOMC days and waits out scheduled speeches but trades CPI days (released before the open) | `risk.events` |
| **Maximum hold time** | He is usually out within 30 minutes to 2 hours; same-day options get riskier into the close | `exits.max_hold_minutes: 150` |
| **Every trade tagged**: side, trigger and move size, gap day, regime and levels at entry, minutes after the open, holding time, MAE | His own "100 days" study list | `entry.gap_day_pct: 0.003` (tag only) |

The expected-move yardstick (`day_em`) is the day's **first** map's ATM straddle, read back from `spreads.db` after a restart, so a restart cannot shrink the yardstick and arm the trigger early. A restart also loses *when* the current high/low was made; the stall clock then starts at the first observation, so a restart can only delay an entry. `entry.trigger: always` restores the original rule (any 5-minute check, both sides) for backtest comparison.

### Position sizing (operator decision, 2026-10-07)

The book has its own capital: `risk.starting_capital_usd` ($100,000) plus the realized P&L of every spread it has closed in the current `mode` (shadow and paper are tracked separately). It grows with wins and shrinks with losses, so position size compounds both ways. Unrealized P&L does not count.

- **Per trade:** contracts = ⌊10% × capital ÷ max loss per contract⌋, capped by `risk.max_contracts` (100, a ceiling against a bad quote sizing to an absurd count). At $100,000 and a $0.25 credit on a 5-wide spread that is 21 contracts: a full loss ≈ $10,000 (10%), a 2×-credit stop ≈ $580, a 50% profit-take ≈ $210.
- **All open spreads together:** at most 10% of capital at risk, so one full-size spread at a time.
- **Per day:** no new entries once the day's realized loss reaches 10% of capital.
- The account's own net liquidation (~$1.04M on paper) is **not** the basis: the book trades as if it had only its own capital, so paper results translate to a live account of that size. `min_excess_liquidity_usd` still guards the whole account.
- The backtest compounds the same way across days, starting from `starting_capital_usd`.

### Execution conventions

- Combo order: legs `SELL short (openClose=0)`, `BUY long`. The order action is `BUY`, and `lmtPrice = −credit` (negative means credit received). This matches `execution/order_builder.build_combo_roll_order`. Closing reverses the legs and uses `lmtPrice = +debit`.
- **This sign convention is unverified on a live paper session.** Task 11 Step 9 is an operator verification step, and it stays on `STATUS.md`'s needs-live-verification list until it's done.
- `orderRef = "CS:<spread_id>"` on every spreads order. It's for audit only; nothing gates on it.
- Price ladder:
  - Opens start at the mid credit and step down one tick per step, never below `max(natural credit, min credit)`.
  - Closes start at the mid debit and step up, never above `natural + close_max_concession`.
  - The 15:45 time stop finally pays the natural price.
- `LimitOrder` only. Never `MarketOrder`.
- Every option contract is qualified before an order is sent.

### Rollout (operator, after the code lands)

1. **Shadow, 2–3 months:** `enabled: true`, `mode: shadow`. Run `python -m scripts.spreads_report --mode shadow` weekly.
2. **Backtest:** buy one month of ThetaData Options Standard ($80) and run `python -m scripts.spreads_backtest --start ... --end ...`. Run it once per comparison: `--profit-take 50` vs `--profit-take 80`, `--trigger move` vs `--trigger always`, `--negative-gamma allow` vs `--negative-gamma skip`. Every run prints the per-tag breakdowns (regime, side, trigger, gap day, exit reason) beside the totals.
3. **Paper:** switch to `mode: paper` only if shadow and backtest both show positive expectancy after costs. Then run Task 11 Step 9, the one-lot sign verification, first.
4. **Live is out of scope.** The service refuses to start when `LIVE_TRADING=true`.

## Global Constraints

- **Core invariant (extended):**
  - `src/spreads/risk.py::validate` is the only gate in front of a spreads order. It is deterministic Python with no LLM, and it runs twice: at decision time, and at send time against a fresh quote.
  - `src/spreads/` imports nothing from `src.claude`, `src.engine`, `src.execution`, `src.strategies`, `src.orchestrator`, `src.monitor`, `src.notify`, `src.reporting`, `src.api` or `src.research`.
  - Only `src/spreads/service.py` may import `src.ledger` or `src.storage`.
- **No reverse imports:** `src/engine/`, `src/execution/`, `src/strategies/`, `src/orchestrator/`, `src/monitor/` and `src/notify/` never import `src.spreads`. Wheel code learns about the spreads book only through `src.common.books` and `config.spreads`.
- **Market data:** never call `ib.reqMktData` directly in `src/spreads/`. Use `src.ibkr.market_data.req_fresh_mkt_data`. Never hold more than `spreads.max_market_data_lines` open lines.
- **Orders:** `LimitOrder` only. Every option is qualified before an order is sent.
- **Paper/shadow only:** `run()` idles when `cfg.is_live` is true.
- **Config files:** the repo commits `config/spreads.example.yaml`; the operator's own `config/spreads.yaml` is private and git-ignored, like `settings.yaml` (`src/common/config.py → PRIVATE_CONFIG_FILES`; tests read the examples via `IBKR_CONFIG_USE_EXAMPLES=1`). Never `git add` a private config file. Shipped defaults:
  - `enabled: false`
  - `mode: shadow`
  - `underlying: SPY` (`underlying_sec_type: STK`, `exchange: SMART`)
  - `book_underlyings: [SPY, SPX, XSP]`
  - `max_market_data_lines: 30`
  - `entry.trigger: move`, `gex.negative_gamma_action: allow`, `risk.one_side_per_day: true`
  - `risk.starting_capital_usd: 100000`, `risk.max_loss_pct_of_capital: 0.10` (sizing; see Design → "Position sizing")
  - `exits.let_expire: false` (SPY is never held to expiry)
  - `ibkr.client_ids.spreads: 30` (in `config/settings.example.yaml`; the operator adds the same line to their private `config/settings.yaml`)
- **Secrets:** `TELEGRAM_THREAD_SPREADS` in `.env` (empty means the main chat). No other new secrets.
- **Units:**
  - All prices are per share, so contract value is ×100.
  - IV is a decimal (0.18).
  - Spreads store commissions as **positive costs**. The ledger keeps its own negative-is-cost convention.
- **Times:** ET via `ZoneInfo("America/New_York")`. Every stored timestamp is timezone-aware UTC.
- **Quality gate after every task:**
  - `python -m pytest -q`
  - `ruff check .`
  - `mypy src`
  - Task 3 also runs `cd web && npm test`.
- Run `ruff format <changed .py files>` before every commit.

## Review Focus

These inputs aren't exercised by the happy path but will happen to a real user. Each has a test in the owning task.

1. **Gateway drop or restart while a spread is open**, e.g. the wheel's `GatewayRestarter` firing on Error 10197. The service must not crash. After reconnecting it must re-reconcile against the broker and keep entries blocked until the broker and DB agree. Exits for DB-known positions keep running (Task 13).
2. **A leg with no usable quote at manage time.** A far-OTM 0DTE long often shows `bid = -1` or no ask. Before the time stop: no exit decision and no crash. At or after the time stop: `time_stop` still fires (Tasks 8, 10).
3. **Partial combo fills**: 1 of 2 contracts. The position records the filled quantity. A partial close leaves the remainder open, with pro-rated realized P&L (Tasks 9, 11).
4. **Service restarted mid-session.** It must not exceed `max_trades_per_day`, which is counted from `data/spreads.db` and not from memory. It must reload open spreads, and it rebuilds the day's GEX map once, because gamma state lives in memory only (Task 13).
5. **ET clock correctness across DST, holidays and early closes**, for an operator in SGT. Examples: 10:30 ET is 14:30 UTC in October but 15:30 UTC in December. Thanksgiving is closed. The day after Thanksgiving closes at 13:00 and is skipped by default (Task 7).

Added with the 2026-10-07 amendment:

6. **Service restarted in the middle of a move.** The new process doesn't know when the current low or high was made. It must wait a full `stall_minutes` from its first observation before arming, and it must keep the day's first expected move (from `spreads.db`) as the yardstick instead of the smaller straddle it sees later in the day (Tasks 6A, 13).
7. **A missing or stale price tape** (no Cboe index stats, a sampler that keeps failing, a Gateway drop): the move trigger must report `no_tape` / `stale_tape` and never arm on old data (Tasks 6A, 13).

---

## File Structure

| Path | Responsibility |
|---|---|
| `config/spreads.example.yaml` (create) | Every spreads tunable, committed template; the operator's `config/spreads.yaml` is private (Task 1) |
| `config/settings.example.yaml` (modify) | `ibkr.client_ids.spreads: 30` (Task 1) |
| `.gitignore` (modify) | `config/spreads.yaml` stays local (Task 1) |
| `config/universe.example.yaml` (modify) | SPY leaves the committed example wheel universe: it is reserved for the spreads book (Task 1) |
| `src/common/config.py` (modify) | `SpreadsCfg` + sub-models (incl. `SpreadsEntryCfg`, `SpreadsEventCfg`), `Config.spreads`, isolation validators, `spreads.yaml` in `PRIVATE_CONFIG_FILES`, `spreads_db_url_abs()`, `spreads_halt_path()`, `TELEGRAM_THREAD_SPREADS` (Task 1) |
| `src/common/books.py` (create) | `spreads_underlyings()`, `is_spreads_underlying()`: the one place wheel code learns about the spreads book (Task 1) |
| `src/engine/risk_engine.py` (modify) | Reject `reserved_for_spreads_book` (Task 1) |
| `src/ibkr/portfolio.py` (modify) | `get_positions(ib, *, include_spreads=False)` (Task 2) |
| `scripts/healthcheck.py` (modify) | Account-truth view: `include_spreads=True` (Task 2) |
| `src/common/schemas.py` (modify) | `LedgerBookName` (Task 3); spreads schemas (Task 4) |
| `src/ledger/ingest.py` (modify) | `_tag_spreads` (Task 3) |
| `src/reporting/trade_ledger.py` (modify) | Spreads book propagation + `Spread` strategy label (Task 3) |
| `src/api/routers/ledger.py`, `src/api/models/ledger.py` (modify) | `book` filter accepts `spreads` (Task 3) |
| `web/components/ledger/{types.ts,TradesView.tsx,LedgerOverview.tsx}`, `web/lib/api-types.ts` (modify) | Spreads book in the UI (Task 3) |
| `src/spreads/__init__.py` (create) | Package marker (Task 4) |
| `src/spreads/pricing.py` (create) | ET clock, fractional-year T, BS gamma/delta/price, implied vol (Task 4) |
| `src/spreads/gex.py` (create) | Per-strike GEX, net GEX, flip, walls, expected move, `build_levels`, `regime_at` (Task 5) |
| `src/spreads/selector.py` (create) | Candidate verticals beyond the action zone; `refresh_candidate` (Task 6) |
| `src/spreads/tape.py` (create) | `SessionTape` (open, prior close, running high/low and when each was made) and `trigger()`: the move/stall/side entry rule (Task 6A) |
| `src/spreads/risk.py` (create) | `size`, `validate`: the deterministic gate (Task 7) |
| `src/spreads/manager.py` (create) | `evaluate_exit`, `intrinsic_debit`, `reconcile` (Task 8) |
| `src/spreads/store.py` (create) | Separate SQLite engine, four tables, store helpers, the tagged trade log (Task 9) |
| `src/spreads/chain.py` (create) | `IbkrSpreadsBroker`: chain fetch, requote, spot, session stats, excess liquidity, broker legs, all line-budgeted (Task 10) |
| `src/spreads/orders.py` (create) | BAG open/close builders, credit/debit ladders (Task 11) |
| `src/spreads/executor.py` (create) | `SpreadExecutor`: shadow simulation, paper laddered orders, send-time re-gate (Task 11) |
| `scripts/spreads_combo_check.py` (create) | One-off operator check that a spreads BAG order shows as a credit in TWS (Task 11) |
| `.env.example` (modify) | `TELEGRAM_THREAD_SPREADS=` (Task 12) |
| `src/spreads/notify.py` (create) | `SpreadsNotifier` + message formatters (Task 12) |
| `src/spreads/service.py` (create) | `SpreadsService.tick/start`, `run()` process loop, reconnect, ledger hook (Task 13) |
| `scripts/run_spreads.py` (create) | Process entrypoint (Task 13) |
| `scripts/start.py` (modify) | `spreads` service + `--no-spreads` (Task 13) |
| `src/spreads/report.py`, `scripts/spreads_report.py` (create) | Win rate, expectancy, break-even win rate, drawdown; breakdowns by regime, side, trigger, gap day and exit reason; hold time and MAE; CSV trade log (Task 14) |
| `src/spreads/backtest/{__init__,thetadata,engine}.py`, `scripts/spreads_backtest.py` (create) | ThetaData client with disk cache; minute replay (Tasks 15–16) |
| `tests/test_spreads_*.py` (incl. `tests/test_spreads_tape.py`), `tests/test_books.py`, `tests/test_wheel_spreads_isolation.py` (create) | Per task |
| `tests/test_spreads_fence.py` (create) | Import fences (Task 17) |
| `ARCHITECTURE.md`, `SETUP.md`, `STATUS.md`, `CLAUDE.md` (modify) | Docs (Task 17) |

---

### Task 1: Spreads config, book helpers, and the wheel-side guards

**Files:**
- Create: `config/spreads.example.yaml`, `src/common/books.py`, `tests/test_spreads_config.py`, `tests/test_books.py`
- Modify: `config/settings.example.yaml`, `config/universe.example.yaml`, `.gitignore`, `src/common/config.py`, `src/engine/risk_engine.py`, `tests/test_engine.py`
- Operator's private copy (git-ignored; edit locally, **never `git add`**): add `spreads: 30` under `ibkr.client_ids` in `config/settings.yaml` too, or `run()` cannot find its clientId outside the test suite.

**Interfaces:**
- Produces:
  - `src.common.config.SpreadsCfg` (fields below), with `entry: SpreadsEntryCfg`
  - `src.common.config.SpreadsEntryCfg` (`trigger`, `min_move_em`, `max_move_em`, `stall_minutes`, `max_tape_age_seconds`, `gap_day_pct`)
  - `src.common.config.SpreadsEventCfg` (`day`, `until`, `label`), used by `SpreadsRiskCfg.events`
  - `SpreadsRiskCfg.one_side_per_day: bool`, `SpreadsExitsCfg.max_hold_minutes: int | None`
  - SPY: `SpreadsCfg.underlying_sec_type: Literal["STK", "IND"]`, `SpreadsGexCfg.sec_type`, `SpreadsGexCfg.scale_to_underlying: float | None` (`None` = live ratio), `SpreadsRiskCfg.ex_dividend_dates: list[date]`, `SpreadsExitsCfg.let_expire: bool`
  - Sizing: `SpreadsRiskCfg.starting_capital_usd`, `max_loss_pct_of_capital`, `max_total_risk_pct_of_capital`, `max_daily_loss_pct_of_capital`, `max_contracts` (they replace the `*_usd` caps)
  - `"spreads.yaml"` in `src.common.config.PRIVATE_CONFIG_FILES`
  - `Config.spreads: SpreadsCfg`
  - `Config.spreads_db_url_abs() -> str`
  - `Config.spreads_halt_path() -> Path`
  - `Secrets.telegram_thread_spreads: str`
  - `src.common.books.spreads_underlyings() -> frozenset[str]`
  - `src.common.books.is_spreads_underlying(symbol: str | None) -> bool`
  - Risk-engine reason string `"reserved_for_spreads_book"`.

- [x] **Step 1: Write the failing config tests**

`tests/test_spreads_config.py`:

```python
"""config/spreads.yaml loads, and config load refuses any wheel/spreads overlap."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.common.config import (
    PRIVATE_CONFIG_FILES,
    Config,
    SpreadsCfg,
    SpreadsEntryCfg,
    SpreadsEventCfg,
    SpreadsScheduleCfg,
    get_config,
)


def _config(**overrides):
    base = get_config()
    fields = {name: getattr(base, name) for name in Config.model_fields}
    fields.update(overrides)
    return Config(**fields)


def test_shipped_config_is_disabled_shadow_spy() -> None:
    cfg = get_config()
    assert cfg.spreads.enabled is False
    assert cfg.spreads.mode == "shadow"
    assert (cfg.spreads.underlying, cfg.spreads.underlying_sec_type, cfg.spreads.exchange) == ("SPY", "STK", "SMART")
    assert (cfg.spreads.gex.symbol, cfg.spreads.gex.sec_type) == ("SPX", "IND")
    assert cfg.spreads.gex.scale_to_underlying is None  # live SPY/SPX ratio
    assert cfg.spreads.exits.let_expire is False  # SPY settles in shares: never held to expiry
    assert cfg.ibkr.client_ids["spreads"] == 30


def test_shipped_sizing_is_ten_percent_of_a_100k_book() -> None:
    r = get_config().spreads.risk
    assert r.starting_capital_usd == 100_000.0
    assert (r.max_loss_pct_of_capital, r.max_total_risk_pct_of_capital, r.max_daily_loss_pct_of_capital) == (0.10, 0.10, 0.10)
    assert r.max_contracts == 100 and r.ex_dividend_dates == []


def test_risk_percentages_must_be_fractions() -> None:
    from src.common.config import SpreadsRiskCfg

    with pytest.raises(ValidationError):
        SpreadsRiskCfg(max_loss_pct_of_capital=10)  # 10 means 1000%, not 10%
    with pytest.raises(ValidationError):
        SpreadsRiskCfg(starting_capital_usd=0)


def test_client_ids_stay_unique() -> None:
    ids = list(get_config().ibkr.client_ids.values())
    assert len(ids) == len(set(ids))


def test_schedule_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        SpreadsScheduleCfg(entry_start="14:00", entry_end="13:00")


def test_schedule_rejects_unpadded_times() -> None:
    with pytest.raises(ValidationError):
        SpreadsScheduleCfg(map_time="9:45")


def test_traded_underlying_must_be_in_the_book() -> None:
    with pytest.raises(ValidationError):
        SpreadsCfg(underlying="SPY", book_underlyings=["XSP", "SPX"])


def test_book_underlyings_may_not_appear_in_the_wheel_universe() -> None:
    base = get_config()
    universe = {**base.universe, "watchlist": [*(base.universe.get("watchlist") or []), "XSP"]}
    with pytest.raises(ValidationError, match="XSP"):
        _config(universe=universe)


def test_enabled_spreads_must_fit_the_line_budget() -> None:
    base = get_config()
    spreads = base.spreads.model_copy(update={"enabled": True, "max_market_data_lines": 80})
    with pytest.raises(ValidationError, match="market-data"):
        _config(spreads=spreads)


def test_enabled_spreads_need_a_client_id() -> None:
    base = get_config()
    ids = {k: v for k, v in base.ibkr.client_ids.items() if k != "spreads"}
    ibkr = base.ibkr.model_copy(update={"client_ids": ids})
    spreads = base.spreads.model_copy(update={"enabled": True})
    with pytest.raises(ValidationError, match="client_ids.spreads"):
        _config(ibkr=ibkr, spreads=spreads)


def test_db_url_resolves_under_the_project_root() -> None:
    url = get_config().spreads_db_url_abs()
    assert url.startswith("sqlite:////") and url.endswith("/data/spreads.db")


def test_spreads_yaml_is_a_private_config_file() -> None:
    assert "spreads.yaml" in PRIVATE_CONFIG_FILES


def test_shipped_defaults_carry_the_opg_entry_rules() -> None:
    s = get_config().spreads
    assert (s.schedule.map_time, s.schedule.entry_start) == ("09:31", "09:35")
    assert s.entry.trigger == "move" and s.entry.min_move_em == 0.5 and s.entry.stall_minutes == 10
    assert s.gex.negative_gamma_action == "allow"
    assert s.risk.one_side_per_day is True and s.risk.events == []
    assert s.exits.max_hold_minutes == 150


def test_entry_move_band_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        SpreadsEntryCfg(min_move_em=1.0, max_move_em=0.8)
    assert SpreadsEntryCfg(max_move_em=None).max_move_em is None


def test_event_until_must_be_a_padded_time() -> None:
    assert SpreadsEventCfg(day="2026-10-28", label="FOMC").until is None
    with pytest.raises(ValidationError):
        SpreadsEventCfg(day="2026-08-28", until="9:30", label="Jackson Hole")
```

`tests/test_books.py`:

```python
from src.common.books import is_spreads_underlying, spreads_underlyings


def test_book_underlyings_are_case_insensitive() -> None:
    assert spreads_underlyings() == frozenset({"SPY", "SPX", "XSP"})
    assert is_spreads_underlying("spy") and is_spreads_underlying("xsp") and is_spreads_underlying("SPX")


def test_wheel_names_and_missing_symbols_are_not_spreads() -> None:
    assert not is_spreads_underlying("UPRO")
    assert not is_spreads_underlying(None)
    assert not is_spreads_underlying("")
```

Append to `tests/test_engine.py`:

```python
def test_rules_engine_rejects_a_spreads_book_underlying() -> None:
    from src.common.schemas import Verdict

    cand = _candidate(candidate_id="xsp-1", underlying="XSP")
    (verdict,) = validate_candidates([cand], _account(), [])
    assert verdict.verdict == Verdict.REJECT
    assert "reserved_for_spreads_book" in verdict.reasons
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_spreads_config.py tests/test_books.py tests/test_engine.py::test_rules_engine_rejects_a_spreads_book_underlying -q`
Expected: FAIL with `ImportError: cannot import name 'SpreadsCfg'` and `ModuleNotFoundError: No module named 'src.common.books'`.

- [x] **Step 3: Create `config/spreads.example.yaml`**

This is the committed template. `config/spreads.yaml` is the operator's private copy (git-ignored, Step 5 adds it to `PRIVATE_CONFIG_FILES`); when it is missing, config load falls back to this file and logs a warning, exactly like `settings.yaml`.

```yaml
# Daily credit-spread system — docs/superpowers/plans/2026-10-07-daily-credit-spreads.md.
# Committed template: copy to config/spreads.yaml (git-ignored) to keep your own settings.
# Runs beside the wheel in the same IBKR account. The two never share an underlying:
# book_underlyings must not appear anywhere in config/universe.yaml (enforced at config load).

enabled: false            # master switch; when false the service process idles
mode: shadow              # shadow = record would-be trades with simulated fills | paper = real paper orders
underlying: SPY           # traded: SPY 0DTE options (American, settle in shares: never held to expiry)
underlying_sec_type: STK  # spot and session stats come from the SPY stock contract
trading_class: SPY
exchange: SMART
book_underlyings: [SPY, SPX, XSP]  # all reserved for this book: none may appear in config/universe.yaml
order_ref_prefix: "CS:"   # audit tag on every spreads order; nothing gates on it
db_url: "sqlite:///data/spreads.db"
max_market_data_lines: 30 # wheel chain_batch_size (40) + this must stay <= 95
halt_file: "data/spreads.halt"  # touch this file to stop new entries; exits keep running

schedule:                 # all ET, zero-padded HH:MM
  map_time: "09:31"       # first GEX map: prior-close OI, live quotes; its expected move is the day's yardstick
  map_refresh_minutes: 60
  entry_start: "09:35"    # opening entries allowed, but only when the entry trigger fires
  entry_end: "13:30"
  entry_check_minutes: 5  # at most one traded-chain fetch per 5 min once the trigger is armed
  manage_interval_seconds: 30  # also how often the price tape is sampled
  force_close: "15:45"
  eod_summary: "16:10"
  skip_early_close_days: true

entry:                    # when, and which side (OPG's "sell after the move")
  trigger: move           # move = only after a stalled move, one side | always = every check, both sides (original rule)
  min_move_em: 0.5        # the move must be >= 0.5 x the day's expected move (gap included)
  max_move_em: 1.5        # beyond 1.5 x it is a trend day: never sell against it. null = no cap
  stall_minutes: 10       # no new low (puts) / new high (calls) for this long first
  max_tape_age_seconds: 120  # the price tape must be this fresh, or nothing arms
  gap_day_pct: 0.003      # tag only: |open / prior close - 1| >= 0.3% marks the trade as a gap day

gex:
  symbol: SPX
  sec_type: IND
  trading_class: SPXW
  exchange: CBOE
  scale_to_underlying: null   # null = live SPY spot ÷ SPX spot, recomputed with every map (SPY trails SPX/10 as dividends accrue)
  strike_band_pct: 0.03
  expiries: 2                 # today + the next listed expiry
  flip_search_pct: 0.03
  flip_buffer_pct: 0.002      # no entries when spot is within 0.2% of the gamma flip
  negative_gamma_action: allow  # allow = trade it, tagged regime=negative in the trade log | skip

selection:
  sides: [put, call]
  width: 5.0                  # SPY points = $500 gross risk per contract
  short_delta_max: 0.15
  em_multiple: 1.0            # short strike at least 1.0 × expected move from spot
  em_straddle_factor: 1.0     # expected move = ATM straddle mid × this
  wall_buffer_pct: 0.001      # and beyond the wall by at least 0.1% of spot
  min_credit_pct_of_width: 0.05  # $25 on a 5-wide; far-OTM 0DTE credits are thin — the backtest decides
  max_leg_spread_pct: 0.30    # (ask - bid) / mid, per leg
  strike_band_pct: 0.03

risk:
  starting_capital_usd: 100000      # the book's own capital; grows/shrinks with its realized P&L (per mode)
  max_loss_pct_of_capital: 0.10     # a spread's full max loss <= 10% of current capital: this sets the contract count
  max_total_risk_pct_of_capital: 0.10  # all open spreads together (one full-size spread at a time)
  max_daily_loss_pct_of_capital: 0.10  # no new entries once today's realized loss reaches this
  max_contracts: 100          # sanity ceiling against a bad quote sizing to an absurd count
  max_open_spreads: 2
  max_trades_per_day: 2
  one_side_per_day: true      # after the day's first spread, only that side may be sold again
  min_excess_liquidity_usd: 10000  # whole-account floor (the wheel shares the margin)
  max_quote_age_seconds: 20
  events: []                  # operator-maintained. Whole day: - {day: 2026-10-28, label: FOMC}
                              # Until a time (ET): - {day: 2026-08-28, until: "10:30", label: Fed chair speech}
                              # CPI/PPI print before the open, so they usually need no entry here
  ex_dividend_dates: []       # SPY ex-dividend dates (quarterly), operator-maintained: no new CALL spreads
                              # on the day before or the day of (early-assignment risk on short calls)

exits:
  profit_take_pct: 50         # compare with 80: python -m scripts.spreads_backtest ... --profit-take 80
  stop_debit_multiple: 2.0    # close when the debit to close reaches 2 × the entry credit
  close_on_short_strike_touch: true
  max_hold_minutes: 150       # close a spread held this long. null = off
  let_expire: false           # SPY settles in shares: the 15:45 time stop closes every spread
  let_expire_max_debit: 0.05  # with let_expire: true only (cash-settled XSP/SPX): this cheap at force_close is left to expire

execution:
  order_ttl_seconds: 60
  reprice_steps: 3
  reprice_tick: 0.01
  close_ttl_seconds: 30
  close_max_concession: 0.10
  shadow_slippage_per_leg: 0.02
  commission_per_contract: 0.65   # per leg; shadow + backtest P&L only (paper uses real commissions)

backtest:
  thetadata_url: "http://127.0.0.1:25503"
  cache_dir: "data/spreads_bt"
  option_symbol: "SPXW"
  index_symbol: "SPX"
  trade_scale: 10.0           # SPX points per SPY point (SPX is the proxy; SPY ≈ SPX/10 less accrued dividends)
  fill_haircut: 0.5           # fraction of the mid→natural gap paid on every simulated fill
```

- [x] **Step 4: Add the client id to `config/settings.example.yaml`, and keep `config/spreads.yaml` private**

In `config/settings.example.yaml` (committed), anchor the line `    healthcheck: 19` under `ibkr.client_ids`. Insert above it:

```yaml
    spreads: 30       # daily credit-spread service (scripts.run_spreads) — config/spreads.yaml
```

Make the same one-line edit in the operator's private `config/settings.yaml` if it exists. It is git-ignored: do not stage it.

In `.gitignore`, anchor the line `config/universe.yaml` in the "Operator config" block and add after it:

```gitignore
config/spreads.yaml
```

SPY leaves the committed example universe (the operator's private `config/universe.yaml` already leaves it out; `Config._spreads_isolated` refuses any overlap, and the test suite loads the example). In `config/universe.example.yaml`:
- Under `indexes:`, replace the line `  - SPY          # S&P 500; 0.8–2.5%/mo at 0.30Δ; most liquid` with `  # SPY is reserved for the daily credit-spread book (config/spreads.example.yaml → book_underlyings)`.
- In the dip-watch list (anchor the run `  - SPY` / `  - QQQ` / `  - IWM` / `  - SMH` / `  - HACK`), delete the `  - SPY` line.
- Under `sectors:`, delete the line `  SPY: index`.

Then `grep -n "SPY" config/universe.example.yaml` should show only the comment and the QQQ note ("slightly higher IV than SPY").

- [x] **Step 5: Add the spreads config models to `src/common/config.py`**

1. Change the import line `from pydantic import BaseModel, Field, field_validator, model_validator` so that `Literal` and `date` are available. Add these to the module imports:

```python
from datetime import date
from typing import Any, Literal
```

(`from typing import Any` already exists; extend it. Put `from datetime import date` directly above `from pathlib import Path` so the import block stays sorted, or run `ruff check --fix src/common/config.py`; `ruff format` alone does not sort imports.)

2. In `class Secrets`, after the `ledger_sheet_id` field, add:

```python
    # Daily credit spreads (docs/superpowers/plans/2026-10-07-daily-credit-spreads.md).
    telegram_thread_spreads: str = Field(default="", alias="TELEGRAM_THREAD_SPREADS")
```

3. Directly above `class Config(BaseModel):`, insert:

```python
def _hhmm(v: str) -> str:
    """Zero-padded 'HH:MM' only — the spreads schedule is compared as strings."""
    parts = v.split(":")
    if len(parts) != 2 or not all(len(p) == 2 and p.isdigit() for p in parts):
        raise ValueError(f"time must be zero-padded 'HH:MM', got {v!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"time out of range (00:00–23:59), got {v!r}")
    return v


class SpreadsScheduleCfg(BaseModel):
    map_time: str = "09:31"
    map_refresh_minutes: int = 60
    entry_start: str = "09:35"
    entry_end: str = "13:30"
    entry_check_minutes: int = 5
    manage_interval_seconds: int = 30
    force_close: str = "15:45"
    eod_summary: str = "16:10"
    skip_early_close_days: bool = True

    @field_validator("map_time", "entry_start", "entry_end", "force_close", "eod_summary")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        return _hhmm(v)

    @model_validator(mode="after")
    def _ordered(self) -> SpreadsScheduleCfg:
        if not (self.map_time <= self.entry_start < self.entry_end <= self.force_close):
            raise ValueError(
                "spreads schedule must satisfy map_time <= entry_start < entry_end <= force_close"
            )
        if self.force_close >= self.eod_summary:
            raise ValueError("spreads schedule: eod_summary must be after force_close")
        return self


class SpreadsGexCfg(BaseModel):
    symbol: str = "SPX"
    sec_type: Literal["IND", "STK"] = "IND"
    trading_class: str = "SPXW"
    exchange: str = "CBOE"
    # None = the live ratio (traded spot ÷ GEX-source spot), recomputed with every map: SPY drifts
    # below SPX/10 as dividends accrue. A number pins it (0.1 for XSP, 1.0 for SPX itself).
    scale_to_underlying: float | None = None
    strike_band_pct: float = 0.03
    expiries: int = 2
    flip_search_pct: float = 0.03
    flip_buffer_pct: float = 0.002
    # Traded by default and tagged regime="negative" in the trade log (operator decision,
    # 2026-10-07: paper account, gather the data first). "skip" restores the stricter rule.
    negative_gamma_action: Literal["skip", "allow"] = "allow"


class SpreadsEntryCfg(BaseModel):
    """When, and on which side, a spread may be sold (src/spreads/tape.py::trigger)."""

    trigger: Literal["move", "always"] = "move"
    min_move_em: float = 0.5
    max_move_em: float | None = 1.5
    stall_minutes: int = 10
    max_tape_age_seconds: float = 120.0
    gap_day_pct: float = 0.003  # tag only — never gates

    @model_validator(mode="after")
    def _band(self) -> SpreadsEntryCfg:
        if self.min_move_em < 0 or self.stall_minutes < 0:
            raise ValueError("spreads entry: min_move_em and stall_minutes must be >= 0")
        if self.max_move_em is not None and self.max_move_em <= self.min_move_em:
            raise ValueError("spreads entry: max_move_em must be above min_move_em (or null)")
        return self


class SpreadsEventCfg(BaseModel):
    """A scheduled event: no new entries all ``day``, or only until ``until`` ET when it is set."""

    day: date
    until: str | None = None
    label: str = ""

    @field_validator("until")
    @classmethod
    def _valid_until(cls, v: str | None) -> str | None:
        return None if v is None else _hhmm(v)


class SpreadsSelectionCfg(BaseModel):
    sides: list[Literal["put", "call"]] = ["put", "call"]  # pydantic copies list defaults per instance
    width: float = 5.0
    short_delta_max: float = 0.15
    em_multiple: float = 1.0
    em_straddle_factor: float = 1.0
    wall_buffer_pct: float = 0.001
    min_credit_pct_of_width: float = 0.05
    max_leg_spread_pct: float = 0.30
    strike_band_pct: float = 0.03


class SpreadsRiskCfg(BaseModel):
    # Sizing (Design → "Position sizing"): the book's capital is starting_capital_usd plus the
    # realized P&L of its closed spreads in the current mode, and every cap is a share of it.
    starting_capital_usd: float = 100_000.0
    max_loss_pct_of_capital: float = 0.10
    max_total_risk_pct_of_capital: float = 0.10
    max_daily_loss_pct_of_capital: float = 0.10
    max_contracts: int = 100  # sanity ceiling against a bad quote sizing to an absurd count
    max_open_spreads: int = 2
    max_trades_per_day: int = 2
    one_side_per_day: bool = True
    min_excess_liquidity_usd: float = 10_000.0
    max_quote_age_seconds: float = 20.0
    events: list[SpreadsEventCfg] = Field(default_factory=list)
    ex_dividend_dates: list[date] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fractions(self) -> SpreadsRiskCfg:
        if self.starting_capital_usd <= 0:
            raise ValueError("spreads risk: starting_capital_usd must be positive")
        for name in ("max_loss_pct_of_capital", "max_total_risk_pct_of_capital", "max_daily_loss_pct_of_capital"):
            if not 0 < getattr(self, name) <= 1:
                raise ValueError(f"spreads risk: {name} is a fraction in (0, 1], e.g. 0.10 for 10%")
        return self


class SpreadsExitsCfg(BaseModel):
    profit_take_pct: float = 50.0
    stop_debit_multiple: float = 2.0
    close_on_short_strike_touch: bool = True
    max_hold_minutes: int | None = 150
    let_expire: bool = False  # SPY settles in shares; True only for cash-settled XSP/SPX
    let_expire_max_debit: float = 0.05


class SpreadsExecutionCfg(BaseModel):
    order_ttl_seconds: float = 60.0
    reprice_steps: int = 3
    reprice_tick: float = 0.01
    close_ttl_seconds: float = 30.0
    close_max_concession: float = 0.10
    shadow_slippage_per_leg: float = 0.02
    commission_per_contract: float = 0.65


class SpreadsBacktestCfg(BaseModel):
    thetadata_url: str = "http://127.0.0.1:25503"
    cache_dir: str = "data/spreads_bt"
    option_symbol: str = "SPXW"
    index_symbol: str = "SPX"
    trade_scale: float = 10.0
    fill_haircut: float = 0.5


class SpreadsCfg(BaseModel):
    """Daily credit-spread system (config/spreads.yaml). See the plan's Design section."""

    enabled: bool = False
    mode: Literal["shadow", "paper"] = "shadow"
    underlying: str = "SPY"
    underlying_sec_type: Literal["STK", "IND"] = "STK"
    trading_class: str = "SPY"
    exchange: str = "SMART"
    book_underlyings: list[str] = ["SPY", "SPX", "XSP"]  # pydantic copies list defaults per instance
    order_ref_prefix: str = "CS:"
    db_url: str = "sqlite:///data/spreads.db"
    max_market_data_lines: int = 30
    halt_file: str = "data/spreads.halt"
    schedule: SpreadsScheduleCfg = Field(default_factory=SpreadsScheduleCfg)
    entry: SpreadsEntryCfg = Field(default_factory=SpreadsEntryCfg)
    gex: SpreadsGexCfg = Field(default_factory=SpreadsGexCfg)
    selection: SpreadsSelectionCfg = Field(default_factory=SpreadsSelectionCfg)
    risk: SpreadsRiskCfg = Field(default_factory=SpreadsRiskCfg)
    exits: SpreadsExitsCfg = Field(default_factory=SpreadsExitsCfg)
    execution: SpreadsExecutionCfg = Field(default_factory=SpreadsExecutionCfg)
    backtest: SpreadsBacktestCfg = Field(default_factory=SpreadsBacktestCfg)

    @model_validator(mode="after")
    def _underlying_in_book(self) -> SpreadsCfg:
        book = {s.upper() for s in self.book_underlyings}
        if self.underlying.upper() not in book:
            raise ValueError(
                f"spreads.underlying {self.underlying!r} must be listed in book_underlyings {sorted(book)}"
            )
        return self
```

4. In `class Config`, after `ledger: LedgerCfg = Field(default_factory=LedgerCfg)`, add:

```python
    spreads: SpreadsCfg = Field(default_factory=SpreadsCfg)
```

5. In `class Config`, after the `research_db_url_abs` method, add:

```python
    def spreads_db_url_abs(self) -> str:
        """Resolve the relative spreads sqlite path against the project root."""
        url = self.spreads.db_url
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            return f"sqlite:///{(ROOT / rel).as_posix()}"
        return url

    def spreads_halt_path(self) -> Path:
        return ROOT / self.spreads.halt_file

    @model_validator(mode="after")
    def _spreads_isolated(self) -> Config:
        """The wheel and the spreads book may never share an underlying or overrun the line cap.

        Book membership is decided by underlying alone (positions carry no order tag; IBKR nets
        same-contract positions across clientIds), so an overlap here would silently merge the
        two books. Checked on every load, enabled or not.
        """
        book = {s.upper() for s in self.spreads.book_underlyings}
        wheel = {
            str(sym).upper()
            for value in self.universe.values()
            if isinstance(value, list)
            for sym in value
        }
        clash = sorted(book & wheel)
        if clash:
            raise ValueError(
                f"spreads.book_underlyings {clash} also appear in config/universe.yaml — the "
                "wheel and the spreads book may never share an underlying"
            )
        if self.spreads.enabled:
            budget = self.market_data.chain_batch_size + self.spreads.max_market_data_lines
            if budget > 95:
                raise ValueError(
                    f"market_data.chain_batch_size + spreads.max_market_data_lines = {budget} "
                    "exceeds the 95-line market-data budget shared by every clientId"
                )
            if "spreads" not in self.ibkr.client_ids:
                raise ValueError("ibkr.client_ids.spreads must be set when spreads.enabled is true")
        return self
```

6. Make `spreads.yaml` a private config file. In the `PRIVATE_CONFIG_FILES` tuple, after `"universe.yaml",`, add:

```python
    "spreads.yaml",
```

`config_path()` then reads `config/spreads.yaml` when the operator has one and falls back to `config/spreads.example.yaml` (with the existing warning) when not; the test suite always reads the example.

7. In `get_config()`, after `ledger=LedgerCfg(**settings.get("ledger", {})),`, add:

```python
        spreads=SpreadsCfg(**_load_yaml("spreads.yaml")),
```

- [x] **Step 6: Create `src/common/books.py`**

```python
"""Which book a contract belongs to: the wheel, or the daily credit-spread system.

The two systems share one IBKR account and one Gateway. They never share an underlying —
``config/spreads.yaml → book_underlyings`` is disjoint from ``config/universe.yaml``, enforced
by ``Config._spreads_isolated`` at load — so the underlying alone decides the book for
positions (which carry no order tag), live fills, and statement rows alike. Order ids are not
used: they are unique only per clientId, and the two systems place orders from different ones.

This is the only module through which wheel code (portfolio, rules engine, ledger) learns that
the spreads book exists. It imports nothing from ``src.spreads``.
"""

from __future__ import annotations

from src.common.config import get_config


def spreads_underlyings() -> frozenset[str]:
    return frozenset(s.upper() for s in get_config().spreads.book_underlyings)


def is_spreads_underlying(symbol: str | None) -> bool:
    return symbol is not None and symbol.upper() in spreads_underlyings()
```

- [x] **Step 7: Reject spreads-book underlyings in the wheel's rules engine**

In `src/engine/risk_engine.py`, add the import among the other `src.common` imports, in sorted order (`ruff check --fix src/engine/risk_engine.py` places it):

```python
from src.common.books import is_spreads_underlying
```

Anchor: inside `validate_candidates`, the loop that starts

```python
    for cand in candidates:
        reasons: list[str] = []
        limits = _strategy_limits(cand.strategy)
```

Insert directly after `limits = _strategy_limits(cand.strategy)`:

```python
        # The spreads book owns these underlyings outright (config/spreads.yaml). A web universe
        # override could still put one in front of the wheel; it must never reach an order.
        if is_spreads_underlying(cand.underlying):
            reasons.append("reserved_for_spreads_book")
```

- [x] **Step 7b: Move the three existing wheel tests that used SPY as a wheel ticker onto QQQ**

SPY is now a spreads-book underlying: the rules engine rejects it (`reserved_for_spreads_book`) and the example universe no longer lists it. Exactly three existing tests relied on SPY being a wheel name (found by a dry run of this plan on 2026-10-07):

1. `tests/test_api_universe.py::test_returns_every_list_unmodified_in_file_order` — replace

```python
    # file order is preserved — the first index in universe.yaml is SPY.
    assert _symbols(_list(body, "indexes"))[0] == "SPY"
```

with

```python
    # file order is preserved — the first index in universe.example.yaml is QQQ (SPY is reserved
    # for the daily credit-spread book).
    assert _symbols(_list(body, "indexes"))[0] == "QQQ"
```

2. `tests/test_drain_universe.py::test_indexes_never_carry_override_metadata_even_with_a_stray_row` — change both `"SPY"` literals in that test (`UniverseOverrideRow(symbol="SPY", ...)` and `e["symbol"] == "SPY"`) to `"QQQ"`.

3. `tests/test_engine.py::test_gate_accepts_a_low_iv_name_paying_a_real_edge` — change `symbol="SPY"` in the `IdealZone` and `underlying="SPY"` in `_csp_candidate` to `"QQQ"`, and the docstring to `"""A low-IV index (QQQ standing in for SPY, which the spreads book now reserves) at 13.5% IV was rejected by the flat 1% ROC floor regardless of edge."""`.

The web test `web/components/universe/UniverseList.test.tsx` builds its own SPY fixture and does not read the YAML, so it is unaffected.

- [x] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/test_spreads_config.py tests/test_books.py tests/test_engine.py tests/test_api_universe.py tests/test_drain_universe.py -q`
Expected: PASS.

- [x] **Step 9: Run the full gate**

Run: `python -m pytest -q && ruff check . && mypy src`
Expected: all green. If a test constructs `Config(...)` with a universe that contains `SPX`, the new validator will fail it. Fix that test's fixture (use another symbol) rather than weakening the validator.

`tests/test_private_config.py::test_private_config_files_are_gitignored` now also checks `spreads.yaml`: it must be git-ignored (Step 4) and `config/spreads.example.yaml` must be in the git index. Run `git add config/spreads.example.yaml .gitignore` before this gate, or that test fails until the commit.

- [x] **Step 10: Commit**

```bash
ruff format src/common/config.py src/common/books.py src/engine/risk_engine.py tests/test_spreads_config.py tests/test_books.py tests/test_engine.py tests/test_api_universe.py tests/test_drain_universe.py
git add config/spreads.example.yaml config/settings.example.yaml config/universe.example.yaml .gitignore src/common/config.py src/common/books.py src/engine/risk_engine.py tests/test_spreads_config.py tests/test_books.py tests/test_engine.py tests/test_api_universe.py tests/test_drain_universe.py
git status --short config/   # must show no private file (settings.yaml, spreads.yaml) staged
git commit -m "feat(spreads): config, book helpers, wheel-side isolation guards"
```

---

### Task 2: The wheel never sees a spreads leg (`get_positions` filter)

**Files:**
- Modify: `src/ibkr/portfolio.py`, `scripts/healthcheck.py`
- Create: `tests/test_wheel_spreads_isolation.py`

**Interfaces:**
- Consumes: `src.common.books.is_spreads_underlying` (Task 1).
- Produces: `get_positions(ib: IB, *, include_spreads: bool = False) -> list[PositionSnapshot]`. The default drops spreads-book contracts, so every existing caller keeps working unchanged.

- [x] **Step 1: Write the failing tests**

`tests/test_wheel_spreads_isolation.py`:

```python
"""The wheel's view of the account never contains a spreads-book leg.

Every wheel consumer of broker positions — the intraday monitor, profit-take, rolls, the scan's
budget seeding (`capital.seed_budgets` would charge a SPY short put strike×100 ≈ $69k of CSP
collateral), the approval re-gate, the EOD report — goes through `get_positions`, so one
default-on filter there is the whole separation.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.ibkr.portfolio import get_positions

ROOT = Path(__file__).resolve().parents[1]


def _item(symbol: str, *, strike: float = 690.0, right: str = "P", position: float = -1.0):
    contract = SimpleNamespace(
        symbol=symbol,
        localSymbol=f"{symbol} 261007{right}{strike:g}",
        secType="OPT",
        right=right,
        strike=strike,
        lastTradeDateOrContractMonth="20261007",
    )
    return SimpleNamespace(
        contract=contract,
        position=position,
        averageCost=50.0,
        marketPrice=0.5,
        marketValue=-50.0,
        unrealizedPNL=10.0,
    )


def _ib(*items):
    ib = MagicMock()
    ib.portfolio.return_value = list(items)
    return ib


def test_wheel_view_drops_spreads_book_legs() -> None:
    ib = _ib(_item("SPY"), _item("SPY", strike=685.0, position=1.0), _item("XSP"), _item("AAPL", strike=200.0))
    assert [p.underlying for p in get_positions(ib)] == ["AAPL"]


def test_spx_legs_are_spreads_book_too() -> None:
    assert get_positions(_ib(_item("SPX", strike=6900.0))) == []


def test_account_truth_view_keeps_them() -> None:
    ib = _ib(_item("SPY"), _item("AAPL", strike=200.0))
    got = sorted(p.underlying or "" for p in get_positions(ib, include_spreads=True))
    assert got == ["AAPL", "SPY"]


def test_upro_is_still_a_wheel_position() -> None:
    assert [p.underlying for p in get_positions(_ib(_item("UPRO", strike=600.0)))] == ["UPRO"]


def test_only_the_healthcheck_asks_for_spreads_positions() -> None:
    """A wheel call site passing include_spreads=True would re-open every coupling above."""
    allowed = {"scripts/healthcheck.py", "src/ibkr/portfolio.py"}
    offenders = [
        str(p.relative_to(ROOT))
        for d in ("src", "scripts")
        for p in sorted((ROOT / d).rglob("*.py"))
        if "include_spreads=True" in p.read_text(encoding="utf-8")
        and str(p.relative_to(ROOT)) not in allowed
    ]
    assert offenders == []
```

- [x] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_wheel_spreads_isolation.py -q`
Expected: FAIL. `test_wheel_view_drops_spreads_book_legs` gets `['SPY', 'SPY', 'XSP', 'AAPL']`, and `include_spreads` is an unexpected keyword.

- [x] **Step 3: Implement the filter**

In `src/ibkr/portfolio.py`, add `from src.common.books import is_spreads_underlying` to the imports. Replace the whole `get_positions` function (anchor: `def get_positions(ib: IB) -> list[PositionSnapshot]:`) with:

```python
def get_positions(ib: IB, *, include_spreads: bool = False) -> list[PositionSnapshot]:
    """Snapshot current positions (stocks and options) as typed objects.

    The daily credit-spread system trades in this same account. Its contracts
    (``config/spreads.yaml → book_underlyings``) are dropped by default, so no wheel consumer —
    the intraday monitor, profit-take, rolls, the scan's budget seeding, the approval re-gate,
    the EOD report — ever alerts on, sizes against, or closes a spread leg. Pass
    ``include_spreads=True`` only for an account-truth view (``scripts/healthcheck.py``).
    """
    out: list[PositionSnapshot] = []
    skipped = 0
    for item in ib.portfolio():
        c = item.contract
        if not include_spreads and is_spreads_underlying(c.symbol):
            skipped += 1
            continue
        right = None
        strike = None
        expiry = None
        underlying = c.symbol
        if c.secType == "OPT":
            right = OptionRight.CALL if c.right.upper().startswith("C") else OptionRight.PUT
            strike = c.strike
            expiry = _parse_expiry(c.lastTradeDateOrContractMonth)
        out.append(
            PositionSnapshot(
                symbol=c.localSymbol or c.symbol,
                sec_type=c.secType,
                position=item.position,
                avg_cost=item.averageCost,
                market_price=item.marketPrice or None,
                market_value=item.marketValue or None,
                unrealized_pnl=item.unrealizedPNL or None,
                right=right,
                strike=strike,
                expiry=expiry,
                underlying=underlying,
            )
        )
    log.info("Fetched %d portfolio positions (%d spreads-book skipped)", len(out), skipped)
    return out
```

- [x] **Step 4: Healthcheck shows account truth**

In `scripts/healthcheck.py`, anchor `positions = get_positions(ib)`. Replace with:

```python
        positions = get_positions(ib, include_spreads=True)  # account truth: both books
```

- [x] **Step 5: Run the tests and the gate**

Run: `python -m pytest tests/test_wheel_spreads_isolation.py -q && python -m pytest -q && ruff check . && mypy src`
Expected: PASS. Existing tests mock `ib.portfolio()` with wheel symbols only (none mocks a SPY position; checked in the 2026-10-07 dry run), so they're unaffected.

- [x] **Step 6: Commit**

```bash
ruff format src/ibkr/portfolio.py scripts/healthcheck.py tests/test_wheel_spreads_isolation.py
git add src/ibkr/portfolio.py scripts/healthcheck.py tests/test_wheel_spreads_isolation.py
git commit -m "feat(spreads): wheel position view excludes the spreads book by default"
```

---

### Task 3: Ledger — a `spreads` book (ingest, builder, API, web)

**Files:**
- Modify:
  - `src/common/schemas.py`
  - `src/ledger/ingest.py`
  - `src/reporting/trade_ledger.py`
  - `src/api/routers/ledger.py`
  - `src/api/models/ledger.py`
  - `web/components/ledger/types.ts`
  - `web/components/ledger/TradesView.tsx`
  - `web/components/ledger/LedgerOverview.tsx`
  - `web/lib/api-types.ts`
- Test:
  - `tests/test_ledger_ingest.py`
  - `tests/test_trade_ledger_book.py`
  - `web/components/ledger/TradesView.test.tsx`

**Interfaces:**
- Consumes: `is_spreads_underlying` (Task 1).
- Produces:
  - `src.common.schemas.LedgerBookName = Literal["system", "manual", "spreads"]`
  - `LedgerTrade.book: LedgerBookName`
  - ingest result `counts["spreads"]`
  - `LedgerSummary.by_strategy` gains a `"Spread"` bucket
  - `GET /ledger/trades?book=spreads`

- [x] **Step 1: Write the failing ingest tests**

Append to `tests/test_ledger_ingest.py`:

```python
def test_spreads_underlyings_are_tagged_spreads_without_an_order_id(db) -> None:
    from src.ledger.ingest import ingest

    result = ingest(
        stmt(
            ex("XSP 07OCT26 680 P", "2026-10-07, 10:05:00", -1, 0.60),
            ex("AMZN 10OCT25 215 P", "2025-10-03, 14:45:08", -1, 1.77),
        ),
        source="csv",
        filename="s.csv",
    )
    assert result.counts["spreads"] == 1
    assert {r.underlying: r.book for r in _rows(db)} == {"XSP": "spreads", "AMZN": "manual"}


def test_a_wheel_order_id_collision_never_moves_a_spreads_row_to_system(db) -> None:
    """Order ids are unique per clientId only: the spreads service (30) can reuse the wheel's."""
    from src.ledger.ingest import ingest
    from src.storage.models import OrderRow

    with db() as s:
        s.add(OrderRow(candidate_id="w1", ib_order_id=42, snapshot=None))
    ingest(
        stmt(ex("XSP 07OCT26 680 P", "2026-10-07, 10:05:00", -1, 0.60, exec_id="x1", order_id=42)),
        source="csv",
    )
    (row,) = _rows(db)
    assert row.book == "spreads"
```

- [x] **Step 2: Write the failing builder test**

Append to `tests/test_trade_ledger_book.py`:

```python
def test_spreads_book_flows_through_and_is_labelled_spread() -> None:
    spread = [
        ex("XSP 07OCT26 680 P", "2026-10-07, 10:05:00", -1, 0.60, codes="O", perm=77, book="spreads"),
        ex("XSP 07OCT26 675 P", "2026-10-07, 10:05:00", 1, 0.25, codes="O", perm=77, book="spreads"),
        ex("XSP 07OCT26 680 P", "2026-10-07, 14:00:00", 1, 0.10, codes="C", perm=78, book="spreads"),
        ex("XSP 07OCT26 675 P", "2026-10-07, 14:00:00", -1, 0.02, codes="C", perm=78, book="spreads"),
    ]
    trades, _, _, _, summary = _book([*spread, *WHEEL], date(2026, 10, 8))
    assert {t.book for t in trades if t.underlying == "XSP"} == {"spreads"}
    assert {t.book for t in trades if t.underlying == "AMZN"} == {"manual"}
    assert "Spread" in {b.label for b in summary.by_strategy}
    assert {"spreads", "manual"} <= {b.label for b in summary.by_book}
```

- [x] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_ledger_ingest.py tests/test_trade_ledger_book.py -q -k "spreads"`
Expected: FAIL. `counts` has no `spreads` key, and `LedgerTrade.book` rejects `"spreads"` with a pydantic `literal_error`.

- [x] **Step 4: Add `LedgerBookName` to `src/common/schemas.py`**

Directly above `class LedgerTrade(BaseModel):` (anchor), insert:

```python
LedgerBookName = Literal["system", "manual", "spreads"]
```

In `LedgerTrade`, replace `book: Literal["system", "manual"]` with `book: LedgerBookName`.

- [x] **Step 5: Tag spreads rows in `src/ledger/ingest.py`**

Add `from src.common.books import is_spreads_underlying` to the imports. Directly above `def _tag_books(`, insert:

```python
def _tag_spreads(s: Session, row_ids: set[int]) -> int:
    """Tag ``book="spreads"`` on rows in ``row_ids`` whose underlying belongs to the spreads book.

    Runs before :func:`_tag_books` on every touched row. CSV and Flex rows often carry no order
    id, and the spreads service's order ids come from its own clientId and can equal a wheel
    order's — so the underlying, which the two books never share, decides.
    """
    if not row_ids:
        return 0
    tagged = 0
    for r in s.scalars(select(BrokerExecutionRow).where(BrokerExecutionRow.id.in_(row_ids))):
        if r.book != "spreads" and is_spreads_underlying(r.underlying):
            r.book = "spreads"
            tagged += 1
    return tagged
```

In `_tag_books`, anchor `    for r in rows:`. Make the loop body start with:

```python
    for r in rows:
        if r.book == "spreads":
            continue  # an order-id collision with a wheel order must never retag a spreads row
```

Anchor `        counts["system"] = _tag_books(s, touched_ids)`. Replace with:

```python
        counts["spreads"] = _tag_spreads(s, touched_ids)
        counts["system"] = _tag_books(s, touched_ids)
```

Anchor `        touched = inserted_or_superseded or any_backfill or bool(counts["system"])`. Replace with:

```python
        touched = (
            inserted_or_superseded
            or any_backfill
            or bool(counts["system"])
            or bool(counts["spreads"])
        )
```

- [x] **Step 6: Carry the book through `src/reporting/trade_ledger.py`**

Add `LedgerBookName` to the existing `from src.common.schemas import (...)` block. Add near the top-level helpers (above `def group_orders`):

```python
def _merge_book(books: Iterable[str]) -> str:
    """One order's book from its executions: spreads, then system, else manual."""
    seen = set(books)
    if "spreads" in seen:
        return "spreads"
    return "system" if "system" in seen else "manual"


def _book_name(value: str) -> LedgerBookName:
    if value == "spreads":
        return "spreads"
    return "system" if value == "system" else "manual"
```

Ensure `Iterable` is imported (`from collections.abc import Iterable`), adding it if absent.

Make these replacements:
- Anchor `                book="system" if any(e.book == "system" for e in group) else "manual",` becomes `                book=_merge_book(e.book for e in group),`.
- Anchor `        book="system" if o.book == "system" else "manual",` becomes `        book=_book_name(o.book),`.
- Anchor `        label = "Long" if t.side == "Buy" else "CSP" if t.right == "P" else "CC"` becomes:

```python
        if t.book == "spreads":
            label = "Spread"
        else:
            label = "Long" if t.side == "Buy" else "CSP" if t.right == "P" else "CC"
```

- In `filter_trades`'s signature, anchor `    book: Literal["system", "manual"] | None = None,` becomes `    book: LedgerBookName | None = None,`.

- [x] **Step 7: API accepts `book=spreads`**

In `src/api/routers/ledger.py` and `src/api/models/ledger.py`, import `LedgerBookName` from `src.common.schemas` and replace every `Literal["system", "manual"]` with `LedgerBookName`. There are three occurrences in the router and one in the models. Run `grep -n 'Literal\["system", "manual"\]' src` afterwards; expected output is empty.

- [x] **Step 8: Run the Python tests**

Run: `python -m pytest tests/test_ledger_ingest.py tests/test_trade_ledger_book.py tests/test_api_ledger.py -q`
Expected: PASS.

- [x] **Step 9: Web: write the failing test**

Append inside `describe("TradesView", ...)` in `web/components/ledger/TradesView.test.tsx`:

```tsx
  it("filters by the spreads book", async () => {
    renderWithQuery(<TradesView />, { "/ledger/trades": { as_of: ISO, n: 0, trades: [], filters: {} } });
    fireEvent.change(await screen.findByLabelText("Book"), { target: { value: "spreads" } });
    await waitFor(() => {
      const paths = apiFetchMock.mock.calls.map((c) => String(c[0]));
      expect(paths.some((p) => p.includes("book=spreads"))).toBe(true);
    });
  });
```

Run: `cd web && npx vitest run components/ledger/TradesView.test.tsx`
Expected: FAIL, because the `<select>` has no `spreads` option so the change is ignored.

- [x] **Step 10: Web: implement**

- `web/components/ledger/types.ts`: replace `book: "system" | "manual";` with `book: "system" | "manual" | "spreads";`.
- `web/components/ledger/TradesView.tsx`: anchor `<option value="manual">Manual</option>`. Append right after it: `<option value="spreads">Spreads</option>`.
- `web/components/ledger/LedgerOverview.tsx`: anchor `title="By book (system vs your own trades)"`. Replace the title with `title="By book (wheel system, credit spreads, your own trades)"`.
- `web/lib/api-types.ts`: start the API (`python -m scripts.run_api`, port 8787), then `cd web && npm run gen:api`. If the API can't run in your environment, hand-edit the four `"system" | "manual"` unions in that file to `"system" | "manual" | "spreads"`; the regenerated file will be identical.

- [x] **Step 11: Run the web tests and the full gate**

Run: `cd web && npm test && cd .. && python -m pytest -q && ruff check . && mypy src`
Expected: all green.

- [x] **Step 12: Commit**

```bash
ruff format src/common/schemas.py src/ledger/ingest.py src/reporting/trade_ledger.py src/api/routers/ledger.py src/api/models/ledger.py tests/test_ledger_ingest.py tests/test_trade_ledger_book.py
git add src/common/schemas.py src/ledger/ingest.py src/reporting/trade_ledger.py src/api/routers/ledger.py src/api/models/ledger.py tests/test_ledger_ingest.py tests/test_trade_ledger_book.py web/components/ledger/types.ts web/components/ledger/TradesView.tsx web/components/ledger/LedgerOverview.tsx web/components/ledger/TradesView.test.tsx web/lib/api-types.ts
git commit -m "feat(ledger): spreads book — tagged by underlying, labelled Spread, filterable"
```

---
### Task 4: Spreads schemas and same-day pricing

**Files:**
- Modify: `src/common/schemas.py`
- Create: `src/spreads/__init__.py`, `src/spreads/pricing.py`, `tests/test_spreads_pricing.py`

**Interfaces:**
- Produces, in `src.common.schemas`:
  - `SpreadSide`, `GammaRegime`, `SpreadExitReason` (includes `"max_hold"`), `EntryTrigger` (Literals)
  - `ChainOption`, with `.mid` and `.spread_pct`
  - `ChainSnapshot`, with `.find(strike, right, expiry)`
  - `GexLevels` (with `scale`: the GEX-source → traded multiplier the levels were built with)
  - `SpreadCandidate`, with `.max_loss_per_contract`
  - `SpreadRiskContext` (with `capital_usd: float`, the book's current capital, and `sides_today: list[SpreadSide]`, default empty), `SpreadVerdict`, `SpreadPosition`, `SpreadExit`
  - `SessionSnapshot` (one read of the traded index: `last`, `open`, `high`, `low`, `prior_close`)
  - `SpreadTrigger` (`sides`, `reason`, `move_em`)
  - `SpreadEntryContext` (the tags stored with every position)
  - `SpreadTradeRecord` (one row of the trade log)
- Produces, in `src.spreads.pricing`:
  - `ET`, `MIN_T`
  - `years_to_close(now, expiry, close=time(16, 0)) -> float`
  - `gamma(spot, strike, t, iv, r=0.0) -> float`
  - `delta(spot, strike, t, iv, right, r=0.0) -> float`
  - `price(spot, strike, t, iv, right, r=0.0) -> float`
  - `implied_vol(target, spot, strike, t, right, r=0.0) -> float | None`

- [x] **Step 1: Write the failing tests**

`tests/test_spreads_pricing.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.schemas import ChainOption, ChainSnapshot
from src.spreads.pricing import MIN_T, delta, gamma, implied_vol, price, years_to_close

TODAY = date(2026, 10, 7)
TEN_AM = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)  # 10:00 EDT


def test_years_to_close_counts_calendar_time_to_the_bell() -> None:
    assert years_to_close(TEN_AM, TODAY) == pytest.approx(6 / 8760)


def test_years_to_close_is_zero_after_the_bell() -> None:
    assert years_to_close(datetime(2026, 10, 7, 21, 0, tzinfo=UTC), TODAY) == 0.0


def test_gamma_peaks_at_the_money_and_stays_finite_at_the_bell() -> None:
    t = 6 / 8760
    assert gamma(690, 690, t, 0.18) > gamma(690, 680, t, 0.18) > 0
    assert gamma(690, 690, 0.0, 0.18) == pytest.approx(gamma(690, 690, MIN_T, 0.18))
    assert gamma(690, 690, t, 0.0) == 0.0


def test_put_delta_is_call_delta_minus_one() -> None:
    t = 6 / 8760
    assert delta(690, 685, t, 0.18, "P") == pytest.approx(delta(690, 685, t, 0.18, "C") - 1.0)


def test_implied_vol_round_trips_a_bs_price() -> None:
    t = 6 / 8760
    p = price(690, 685, t, 0.18, "P")
    assert implied_vol(p, 690, 685, t, "P") == pytest.approx(0.18, abs=1e-4)


def test_implied_vol_is_none_below_intrinsic() -> None:
    assert implied_vol(1.0, 690, 700, 6 / 8760, "P") is None


def test_chain_option_mid_and_spread_pct() -> None:
    o = ChainOption(strike=680, right="P", expiry=TODAY, bid=0.80, ask=0.90)
    assert o.mid == pytest.approx(0.85)
    assert o.spread_pct == pytest.approx(0.10 / 0.85)
    assert ChainOption(strike=680, right="P", expiry=TODAY, bid=-1.0, ask=0.9).mid is None
    assert ChainOption(strike=680, right="P", expiry=TODAY, bid=0.0, ask=0.05).mid == 0.025


def test_chain_snapshot_find() -> None:
    o = ChainOption(strike=680, right="P", expiry=TODAY)
    snap = ChainSnapshot(symbol="XSP", spot=690.0, as_of=TEN_AM, options=[o])
    assert snap.find(680.0, "P", TODAY) is o
    assert snap.find(680.0, "C", TODAY) is None


def test_amendment_schemas_default_safely() -> None:
    from src.common.schemas import SessionSnapshot, SpreadExit, SpreadRiskContext, SpreadTrigger

    ctx = SpreadRiskContext(now=TEN_AM, levels=None, open_spreads=0, open_risk_usd=0.0, trades_today=0,
                            realized_pnl_today_usd=0.0, excess_liquidity_usd=None, capital_usd=100_000.0)
    assert ctx.sides_today == []
    assert SpreadTrigger(reason="no_move").sides == []
    assert SessionSnapshot(as_of=TEN_AM, last=690.0).prior_close is None
    assert SpreadExit(spread_id="s1", reason="max_hold", close=True).reason == "max_hold"
```

- [x] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_pricing.py -q`
Expected: FAIL with `ImportError: cannot import name 'ChainOption'`.

- [x] **Step 3: Append the spreads schemas to `src/common/schemas.py`**

Append at the end of the file:

```python
# --------------------------------------------------------------------------- #
# Daily credit spreads (docs/superpowers/plans/2026-10-07-daily-credit-spreads.md)
# --------------------------------------------------------------------------- #

SpreadSide = Literal["put", "call"]
GammaRegime = Literal["positive", "negative", "unknown"]
SpreadExitReason = Literal[
    "profit_take", "stop_loss", "strike_touch", "max_hold", "time_stop", "expire_worthless"
]
EntryTrigger = Literal["move", "always"]


class ChainOption(BaseModel):
    """One option in a spreads chain snapshot (the SPX GEX source or the traded SPY chain)."""

    strike: float
    right: Literal["C", "P"]
    expiry: date
    bid: float | None = None
    ask: float | None = None
    iv: float | None = None  # decimal: 0.18 = 18%
    delta: float | None = None
    open_interest: int | None = None
    con_id: int | None = None

    @property
    def mid(self) -> float | None:
        """None for a missing/negative bid (IBKR's -1 sentinel), a missing ask, or a crossed quote.

        A zero bid is a real quote on a far-OTM 0DTE option and yields ask / 2.
        """
        if self.bid is None or self.ask is None or self.bid < 0 or self.ask <= 0:
            return None
        if self.ask < self.bid:
            return None
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> float | None:
        m = self.mid
        if m is None or m <= 0 or self.bid is None or self.ask is None:
            return None
        return (self.ask - self.bid) / m


class ChainSnapshot(BaseModel):
    symbol: str
    spot: float
    as_of: datetime  # timezone-aware UTC
    options: list[ChainOption] = Field(default_factory=list)

    def find(self, strike: float, right: str, expiry: date) -> ChainOption | None:
        for o in self.options:
            if o.right == right and o.expiry == expiry and abs(o.strike - strike) < 1e-6:
                return o
        return None


class GexLevels(BaseModel):
    """The day's action zones, in traded-underlying (SPY) units except ``net_gex``."""

    as_of: datetime
    spot: float
    net_gex: float  # dealer $-gamma per 1% move, GEX-source units
    regime: GammaRegime
    flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    expected_move: float | None = None  # points
    scale: float = 0.1  # GEX-source level × scale = traded level (live SPY/SPX ratio for SPY)


class SpreadCandidate(BaseModel):
    spread_id: str
    side: SpreadSide
    expiry: date
    short_strike: float
    long_strike: float
    width: float
    short_con_id: int | None = None
    long_con_id: int | None = None
    credit_mid: float  # per share
    credit_natural: float  # short bid - long ask
    short_delta: float | None = None
    short_leg_spread_pct: float | None = None
    long_leg_spread_pct: float | None = None
    spot: float
    quote_time: datetime

    @property
    def max_loss_per_contract(self) -> float:
        return (self.width - self.credit_mid) * 100.0


class SpreadRiskContext(BaseModel):
    now: datetime
    levels: GexLevels | None
    open_spreads: int
    open_risk_usd: float
    trades_today: int
    realized_pnl_today_usd: float
    excess_liquidity_usd: float | None
    capital_usd: float  # the book's capital: starting capital + realized P&L (sizing basis)
    sides_today: list[SpreadSide] = Field(default_factory=list)  # sides opened this ET day


class SpreadVerdict(BaseModel):
    spread_id: str
    approved: bool
    contracts: int = 0
    reasons: list[str] = Field(default_factory=list)


class SpreadPosition(BaseModel):
    spread_id: str
    mode: Literal["shadow", "paper"]
    side: SpreadSide
    expiry: date
    short_strike: float
    long_strike: float
    width: float
    contracts: int  # still open
    entry_credit: float  # per share
    opened_at: datetime
    short_con_id: int | None = None
    long_con_id: int | None = None


class SpreadExit(BaseModel):
    spread_id: str
    reason: SpreadExitReason
    close: bool  # False = leave the cash-settled spread to expire


class SessionSnapshot(BaseModel):
    """One read of the traded index: the price now plus IBKR's session stats (ticks 14/6/7/9)."""

    as_of: datetime
    last: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prior_close: float | None = None


class SpreadTrigger(BaseModel):
    """Which sides the entry trigger allows right now. ``reason`` is "armed" or "always" when it fires."""

    sides: list[SpreadSide] = Field(default_factory=list)
    reason: str
    move_em: float | None = None  # the move that armed it, in units of the day's expected move


class SpreadEntryContext(BaseModel):
    """What the market looked like when a spread opened — stored with the position for analysis."""

    trigger: EntryTrigger
    move_em: float | None = None
    gap_pct: float | None = None  # today's open / prior close − 1
    gap_day: bool = False
    regime: GammaRegime
    net_gex: float
    flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    expected_move: float | None = None
    day_em: float | None = None
    spot: float
    minutes_after_open: int


class SpreadTradeRecord(BaseModel):
    """One spread in the trade log (open or closed), with its entry tags and its outcome so far."""

    spread_id: str
    mode: Literal["shadow", "paper"]
    side: SpreadSide
    status: str  # open | expiring | closed
    opened_at: datetime
    closed_at: datetime | None = None
    short_strike: float
    long_strike: float
    width: float
    contracts: int  # opened
    entry_credit: float
    exit_debit: float | None = None
    exit_reason: str | None = None
    pnl_usd: float  # realized so far, after commissions
    regime: str
    trigger: str
    move_em: float | None = None
    gap_pct: float | None = None
    gap_day: bool = False
    minutes_after_open: int | None = None
    hold_minutes: float | None = None
    mae_usd: float | None = None  # worst mark against the position while open, >= 0
```

(`Literal`, `date`, `datetime`, `BaseModel`, `Field` are already imported in this module. Confirm with `grep -n "^from" src/common/schemas.py`.)

- [x] **Step 4: Create the package and `src/spreads/pricing.py`**

`src/spreads/__init__.py`:

```python
"""Daily (0DTE) SPY credit-spread system — runs beside the wheel, shares nothing with it.

See docs/superpowers/plans/2026-10-07-daily-credit-spreads.md and CLAUDE.md "The spreads fence".
"""
```

`src/spreads/pricing.py`:

```python
"""Black-Scholes with fractional-year time, and the ET clock — for same-day options.

``src.analytics.black_scholes`` takes integer calendar DTE and returns ``None`` at 0 DTE, which
is exactly the regime this system trades, so the spreads package carries its own. Pure math.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from scipy.stats import norm

ET = ZoneInfo("America/New_York")
_YEAR_SECONDS = 365.0 * 24 * 3600
MIN_T = 60.0 / _YEAR_SECONDS  # one minute — keeps gamma finite at the bell


def years_to_close(now: datetime, expiry: date, close: time = time(16, 0)) -> float:
    """Calendar-time years from *now* (aware) to *expiry*'s close, floored at zero."""
    expiry_dt = datetime.combine(expiry, close, tzinfo=ET)
    return max((expiry_dt - now.astimezone(ET)).total_seconds(), 0.0) / _YEAR_SECONDS


def _d1(spot: float, strike: float, t: float, iv: float, r: float) -> float:
    return (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))


def gamma(spot: float, strike: float, t: float, iv: float, r: float = 0.0) -> float:
    if spot <= 0 or strike <= 0 or iv <= 0:
        return 0.0
    t = max(t, MIN_T)
    return float(norm.pdf(_d1(spot, strike, t, iv, r))) / (spot * iv * math.sqrt(t))


def delta(spot: float, strike: float, t: float, iv: float, right: str, r: float = 0.0) -> float:
    if spot <= 0 or strike <= 0 or iv <= 0:
        return 0.0
    t = max(t, MIN_T)
    nd1 = float(norm.cdf(_d1(spot, strike, t, iv, r)))
    return nd1 if right == "C" else nd1 - 1.0


def price(spot: float, strike: float, t: float, iv: float, right: str, r: float = 0.0) -> float:
    intrinsic = max(spot - strike, 0.0) if right == "C" else max(strike - spot, 0.0)
    if t <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return intrinsic
    d1 = _d1(spot, strike, t, iv, r)
    d2 = d1 - iv * math.sqrt(t)
    disc = math.exp(-r * t)
    if right == "C":
        return spot * float(norm.cdf(d1)) - strike * disc * float(norm.cdf(d2))
    return strike * disc * float(norm.cdf(-d2)) - spot * float(norm.cdf(-d1))


def implied_vol(
    target: float | None,
    spot: float,
    strike: float,
    t: float,
    right: str,
    r: float = 0.0,
    *,
    lo: float = 0.01,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 200,
) -> float | None:
    """Bisection IV. None when *target* is outside the [lo, hi]-vol price range."""
    if target is None or t <= 0 or spot <= 0 or strike <= 0:
        return None
    if target < price(spot, strike, t, lo, right, r) - tol:
        return None
    if target > price(spot, strike, t, hi, right, r) + tol:
        return None
    a, b = lo, hi
    for _ in range(max_iter):
        m = (a + b) / 2
        if price(spot, strike, t, m, right, r) < target:
            a = m
        else:
            b = m
        if b - a < tol:
            break
    return (a + b) / 2
```

- [x] **Step 5: Run the tests and the gate**

Run: `python -m pytest tests/test_spreads_pricing.py -q && ruff check . && mypy src`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
ruff format src/common/schemas.py src/spreads/__init__.py src/spreads/pricing.py tests/test_spreads_pricing.py
git add src/common/schemas.py src/spreads/__init__.py src/spreads/pricing.py tests/test_spreads_pricing.py
git commit -m "feat(spreads): schemas and fractional-day Black-Scholes"
```

---

### Task 5: GEX levels — net gamma, flip, walls, expected move

**Files:**
- Create: `src/spreads/gex.py`, `tests/test_spreads_gex.py`

**Interfaces:**
- Consumes:
  - `ChainOption`, `ChainSnapshot`, `GexLevels`, `GammaRegime` (Task 4)
  - `pricing.gamma`, `pricing.years_to_close`, `pricing.ET` (Task 4)
  - `SpreadsCfg` (Task 1)
- Produces:
  - `strike_gex(options, spot, now) -> dict[float, float]`
  - `net_gex(options, spot, now) -> float`
  - `regime_of(net, has_data) -> GammaRegime`
  - `gamma_flip(options, spot, now, search_pct, steps=121) -> float | None`
  - `walls(per_strike, spot) -> tuple[float | None, float | None]`, returning (call_wall, put_wall)
  - `expected_move(options, spot, expiry, factor) -> float | None`
  - `build_levels(gex_chain, traded_chain, cfg, now) -> GexLevels` (scales SPX levels by `cfg.gex.scale_to_underlying`, or by the live traded/GEX spot ratio when it is `None`, and records the multiplier as `GexLevels.scale`)
  - `regime_at(gex_chain, traded_spot, scale, now) -> GammaRegime` (`scale` = the map's `GexLevels.scale`)

- [x] **Step 1: Write the failing tests**

`tests/test_spreads_gex.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, ChainSnapshot
from src.spreads.gex import (
    build_levels,
    expected_move,
    gamma_flip,
    net_gex,
    regime_at,
    strike_gex,
    walls,
)
from src.spreads.pricing import gamma, years_to_close

NOW = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)  # 10:00 EDT
TODAY = date(2026, 10, 7)
TOMORROW = date(2026, 10, 8)


def _o(strike, right, oi, *, iv=0.40, expiry=TOMORROW, bid=None, ask=None) -> ChainOption:
    return ChainOption(
        strike=strike, right=right, expiry=expiry, open_interest=oi, iv=iv, bid=bid, ask=ask
    )


def test_calls_add_and_puts_subtract() -> None:
    per = strike_gex([_o(100, "C", 1000, iv=0.15), _o(100, "P", 400, iv=0.15)], 100.0, NOW)
    g = gamma(100, 100, years_to_close(NOW, TOMORROW), 0.15)
    assert per[100.0] == pytest.approx(g * 600 * 100 * 100 * 100 * 0.01)


def test_options_without_oi_or_iv_are_ignored() -> None:
    no_iv = ChainOption(strike=101, right="C", expiry=TOMORROW, open_interest=50)
    assert strike_gex([_o(100, "C", 0), no_iv], 100.0, NOW) == {}


def test_walls_pick_the_largest_magnitude_on_each_side_of_spot() -> None:
    assert walls({95: -5, 98: -10, 100: 1, 102: 8, 105: 3}, 100.0) == (102, 98)
    assert walls({}, 100.0) == (None, None)


def test_flip_sits_between_a_put_heavy_floor_and_a_call_heavy_ceiling() -> None:
    opts = [_o(97, "P", 5000), _o(103, "C", 5000)]
    assert net_gex(opts, 97.5, NOW) < 0 < net_gex(opts, 102.5, NOW)
    flip = gamma_flip(opts, 100.0, NOW, 0.03)
    assert flip is not None and 97 < flip < 103


def test_flip_is_none_when_gamma_never_changes_sign() -> None:
    assert gamma_flip([_o(100, "C", 5000)], 100.0, NOW, 0.03) is None


def test_expected_move_is_the_atm_straddle_nearest_spot() -> None:
    opts = [
        _o(690, "C", 1, expiry=TODAY, bid=2.9, ask=3.1),
        _o(690, "P", 1, expiry=TODAY, bid=2.7, ask=2.9),
        _o(695, "C", 1, expiry=TODAY, bid=1.0, ask=1.2),
        _o(695, "P", 1, expiry=TODAY, bid=5.0, ask=5.4),
    ]
    assert expected_move(opts, 690.4, TODAY, 1.0) == pytest.approx(5.8)
    assert expected_move(opts, 690.4, TOMORROW, 1.0) is None


def _spx_chain() -> ChainSnapshot:
    return ChainSnapshot(
        symbol="SPX",
        spot=6900.0,
        as_of=NOW,
        options=[_o(6800, "P", 40_000, expiry=TODAY), _o(7000, "C", 40_000, expiry=TODAY)],
    )


def _xsp_chain() -> ChainSnapshot:
    return ChainSnapshot(
        symbol="XSP",
        spot=690.0,
        as_of=NOW,
        options=[
            _o(690, "C", 10, expiry=TODAY, bid=2.9, ask=3.1),
            _o(690, "P", 10, expiry=TODAY, bid=2.7, ask=2.9),
        ],
    )


def test_build_levels_scales_spx_levels_into_xsp_units() -> None:
    levels = build_levels(_spx_chain(), _xsp_chain(), get_config().spreads, NOW)
    assert levels.put_wall == pytest.approx(680.0)
    assert levels.call_wall == pytest.approx(700.0)
    assert levels.flip is not None and 680.0 < levels.flip < 700.0
    assert levels.expected_move == pytest.approx(5.8)
    assert levels.spot == 690.0
    assert levels.regime in ("positive", "negative")


def test_build_levels_with_no_oi_is_unknown_regime() -> None:
    empty = ChainSnapshot(symbol="SPX", spot=6900.0, as_of=NOW, options=[])
    levels = build_levels(empty, _xsp_chain(), get_config().spreads, NOW)
    assert levels.regime == "unknown" and levels.put_wall is None and levels.flip is None


def test_regime_at_follows_spot_between_the_walls() -> None:
    assert regime_at(_spx_chain(), 681.0, 0.1, NOW) == "negative"
    assert regime_at(_spx_chain(), 699.0, 0.1, NOW) == "positive"


def test_build_levels_uses_the_live_spy_spx_ratio() -> None:
    cfg = get_config().spreads  # gex.scale_to_underlying: null → live ratio
    spy = _xsp_chain().model_copy(update={"symbol": "SPY", "spot": 686.55})  # SPY trails SPX/10
    levels = build_levels(_spx_chain(), spy, cfg, NOW)
    assert levels.scale == pytest.approx(686.55 / 6900.0)
    assert levels.put_wall == pytest.approx(6800.0 * 686.55 / 6900.0)
    pinned = cfg.model_copy(update={"gex": cfg.gex.model_copy(update={"scale_to_underlying": 0.1})})
    assert build_levels(_spx_chain(), spy, pinned, NOW).put_wall == pytest.approx(680.0)
```

- [x] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_gex.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.gex'`.

- [x] **Step 3: Implement `src/spreads/gex.py`**

```python
"""Dealer gamma exposure (GEX) levels from a chain snapshot — the day's "action zones".

Standard retail model: dealers are long the calls customers sell and short the puts customers
buy, so per-strike GEX = Γ·OI·100·S²·0.01 (calls +, puts −) — dollars of underlying dealers
must trade per 1% move. Open interest is the prior close's figure (OPRA, ~06:30 ET) and
intraday 0DTE flow is invisible, so these levels are a regime filter and a strike-placement
guide, never a price target. Pure: no IBKR, no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from src.common.config import SpreadsCfg
from src.common.schemas import ChainOption, ChainSnapshot, GammaRegime, GexLevels
from src.spreads.pricing import ET, gamma, years_to_close

CONTRACT_MULTIPLIER = 100.0


def strike_gex(options: list[ChainOption], spot: float, now: datetime) -> dict[float, float]:
    out: dict[float, float] = defaultdict(float)
    for o in options:
        if not o.open_interest or o.iv is None or o.iv <= 0:
            continue
        g = gamma(spot, o.strike, years_to_close(now, o.expiry), o.iv)
        value = g * o.open_interest * CONTRACT_MULTIPLIER * spot * spot * 0.01
        out[o.strike] += value if o.right == "C" else -value
    return dict(out)


def net_gex(options: list[ChainOption], spot: float, now: datetime) -> float:
    return sum(strike_gex(options, spot, now).values())


def regime_of(net: float, has_data: bool) -> GammaRegime:
    if not has_data or net == 0:
        return "unknown"
    return "positive" if net > 0 else "negative"


def gamma_flip(
    options: list[ChainOption], spot: float, now: datetime, search_pct: float, steps: int = 121
) -> float | None:
    """The spot level nearest *spot* where net GEX changes sign (linear interpolation)."""
    if steps < 2 or spot <= 0:
        return None
    lo, hi = spot * (1 - search_pct), spot * (1 + search_pct)
    grid = [lo + (hi - lo) * i / (steps - 1) for i in range(steps)]
    values = [net_gex(options, s, now) for s in grid]
    best: float | None = None
    for i in range(steps - 1):
        s0, s1, v0, v1 = grid[i], grid[i + 1], values[i], values[i + 1]
        if v0 == 0 and v1 == 0:
            continue
        if v0 == 0:
            crossing = s0
        elif v0 * v1 < 0:
            crossing = s0 + (s1 - s0) * (-v0) / (v1 - v0)
        else:
            continue
        if best is None or abs(crossing - spot) < abs(best - spot):
            best = crossing
    return best


def walls(per_strike: dict[float, float], spot: float) -> tuple[float | None, float | None]:
    """(call_wall, put_wall): largest positive GEX at/above spot, most negative at/below."""
    calls = {k: v for k, v in per_strike.items() if k >= spot and v > 0}
    puts = {k: v for k, v in per_strike.items() if k <= spot and v < 0}
    call_wall = max(calls, key=lambda k: calls[k]) if calls else None
    put_wall = min(puts, key=lambda k: puts[k]) if puts else None
    return call_wall, put_wall


def expected_move(
    options: list[ChainOption], spot: float, expiry: date, factor: float
) -> float | None:
    """ATM straddle mid (strike nearest spot with both legs quoted) × *factor*."""
    mids: dict[float, dict[str, float]] = {}
    for o in options:
        m = o.mid
        if o.expiry != expiry or m is None:
            continue
        mids.setdefault(o.strike, {})[o.right] = m
    both = [k for k, v in mids.items() if "C" in v and "P" in v]
    if not both:
        return None
    atm = min(both, key=lambda k: abs(k - spot))
    return (mids[atm]["C"] + mids[atm]["P"]) * factor


def build_levels(
    gex_chain: ChainSnapshot, traded_chain: ChainSnapshot, cfg: SpreadsCfg, now: datetime
) -> GexLevels:
    # SPY trails SPX/10 as dividends accrue (more than the 0.1% wall buffer), so by default the
    # multiplier is the live spot ratio, measured with the same map.
    scale = cfg.gex.scale_to_underlying or traded_chain.spot / gex_chain.spot
    per = strike_gex(gex_chain.options, gex_chain.spot, now)
    net = sum(per.values())
    flip = gamma_flip(gex_chain.options, gex_chain.spot, now, cfg.gex.flip_search_pct) if per else None
    call_wall, put_wall = walls(per, gex_chain.spot)
    today = now.astimezone(ET).date()
    em = expected_move(
        traded_chain.options, traded_chain.spot, today, cfg.selection.em_straddle_factor
    )
    return GexLevels(
        as_of=now,
        spot=traded_chain.spot,
        net_gex=net,
        regime=regime_of(net, bool(per)),
        flip=flip * scale if flip is not None else None,
        call_wall=call_wall * scale if call_wall is not None else None,
        put_wall=put_wall * scale if put_wall is not None else None,
        expected_move=em,
        scale=scale,
    )


def regime_at(
    gex_chain: ChainSnapshot, traded_spot: float, scale: float, now: datetime
) -> GammaRegime:
    """Re-evaluate the regime at the current spot between map refreshes (OI fixed, Γ moves).

    *scale* is the multiplier the map was built with (``GexLevels.scale``).
    """
    spot = traded_spot / scale
    per = strike_gex(gex_chain.options, spot, now)
    return regime_of(sum(per.values()), bool(per))
```

- [x] **Step 4: Run the tests and the gate**

Run: `python -m pytest tests/test_spreads_gex.py -q && ruff check . && mypy src`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
ruff format src/spreads/gex.py tests/test_spreads_gex.py
git add src/spreads/gex.py tests/test_spreads_gex.py
git commit -m "feat(spreads): GEX levels — per-strike gamma, flip, walls, expected move"
```

---

### Task 6: Candidate selection beyond the action zone

**Files:**
- Create: `src/spreads/selector.py`, `tests/test_spreads_selector.py`

**Interfaces:**
- Consumes: `ChainSnapshot`, `ChainOption`, `GexLevels`, `SpreadCandidate` (Task 4); `pricing.ET`; `SpreadsCfg`.
- Produces:
  - `short_boundary(side, levels, cfg) -> float | None`
  - `make_spread_id(side, expiry, short_strike, long_strike, now) -> str`
  - `select_candidates(chain, levels, cfg, now, sides=None) -> list[SpreadCandidate]`, at most one per side; `sides` (from the entry trigger, Task 6A) limits the walk to those sides, `None` = `cfg.selection.sides`
  - `refresh_candidate(c, short_q, long_q, now) -> SpreadCandidate | None`

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_selector.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, ChainSnapshot, GexLevels
from src.spreads.selector import refresh_candidate, select_candidates, short_boundary

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)  # 10:30 EDT
TODAY = date(2026, 10, 7)
_BASE = get_config().spreads
# Pinned explicitly so a YAML retune never silently changes these tests: width 5, delta cap 0.15,
# min credit 10% of width (0.50), wall buffer 0.1%, expected-move multiple 1.0.
CFG = _BASE.model_copy(
    update={
        "selection": _BASE.selection.model_copy(
            update={"width": 5.0, "short_delta_max": 0.15, "min_credit_pct_of_width": 0.10, "wall_buffer_pct": 0.001, "em_multiple": 1.0}
        )
    }
)


def q(strike: float, right: str, bid: float | None, ask: float | None, delta: float | None = None):
    return ChainOption(
        strike=strike,
        right=right,
        expiry=TODAY,
        bid=bid,
        ask=ask,
        delta=delta,
        con_id=int(strike * 10) + (1 if right == "C" else 0),
    )


def levels(**kw) -> GexLevels:
    base = dict(
        as_of=NOW,
        spot=690.0,
        net_gex=1e9,
        regime="positive",
        flip=680.0,
        call_wall=700.0,
        put_wall=680.0,
        expected_move=6.0,
    )
    base.update(kw)
    return GexLevels(**base)


def chain(*opts: ChainOption) -> ChainSnapshot:
    return ChainSnapshot(symbol="XSP", spot=690.0, as_of=NOW, options=list(opts))


def test_put_boundary_is_below_both_the_expected_move_and_the_wall() -> None:
    assert short_boundary("put", levels(), CFG) == pytest.approx(680.0 - 0.69)
    assert short_boundary("put", levels(put_wall=687.0), CFG) == pytest.approx(684.0)
    assert short_boundary("call", levels(), CFG) == pytest.approx(700.0 + 0.69)
    assert short_boundary("put", levels(expected_move=None), CFG) is None


def test_picks_the_closest_put_and_call_beyond_the_zone() -> None:
    got = select_candidates(
        chain(
            q(680, "P", 1.10, 1.20, -0.16),  # inside the boundary — never considered
            q(679, "P", 0.80, 0.86, -0.12),
            q(674, "P", 0.20, 0.24, -0.04),
            q(701, "C", 0.70, 0.76, 0.11),
            q(706, "C", 0.14, 0.18, 0.03),
        ),
        levels(),
        CFG,
        NOW,
    )
    put, call = sorted(got, key=lambda c: c.side, reverse=True)
    assert (put.side, put.short_strike, put.long_strike) == ("put", 679, 674)
    assert put.credit_mid == pytest.approx(0.61)
    assert put.credit_natural == pytest.approx(0.56)
    assert put.short_con_id == 6790 and put.long_con_id == 6740
    assert (call.side, call.short_strike, call.long_strike) == ("call", 701, 706)
    assert call.credit_mid == pytest.approx(0.57)


def test_a_short_over_the_delta_cap_is_skipped_for_the_next_strike() -> None:
    (c,) = select_candidates(
        chain(
            q(679, "P", 0.80, 0.86, -0.20),
            q(674, "P", 0.20, 0.24),
            q(678, "P", 0.70, 0.76, -0.11),
            q(673, "P", 0.18, 0.22),
        ),
        levels(),
        CFG.model_copy(update={"selection": CFG.selection.model_copy(update={"sides": ["put"]})}),
        NOW,
    )
    assert (c.short_strike, c.long_strike) == (678, 673)


def test_a_missing_long_leg_moves_to_the_next_strike() -> None:
    (c,) = select_candidates(
        chain(
            q(679, "P", 0.80, 0.86, -0.12),
            q(678, "P", 0.70, 0.76, -0.11),
            q(673, "P", 0.18, 0.22),
        ),
        levels(),
        CFG,
        NOW,
    )
    assert c.short_strike == 678


def test_walk_stops_once_the_credit_is_too_thin() -> None:
    got = select_candidates(
        chain(
            q(679, "P", 0.40, 0.44, -0.08),
            q(674, "P", 0.10, 0.14),
            q(678, "P", 0.35, 0.39, -0.07),
            q(673, "P", 0.08, 0.12),
        ),
        levels(),
        CFG,
        NOW,
    )
    assert got == []


def test_no_expected_move_means_no_candidates() -> None:
    got = select_candidates(
        chain(q(679, "P", 0.80, 0.86, -0.12), q(674, "P", 0.20, 0.24)),
        levels(expected_move=None),
        CFG,
        NOW,
    )
    assert got == []


def test_the_triggered_side_limits_the_walk() -> None:
    both = chain(
        q(679, "P", 0.80, 0.86, -0.12),
        q(674, "P", 0.20, 0.24, -0.04),
        q(701, "C", 0.70, 0.76, 0.11),
        q(706, "C", 0.14, 0.18, 0.03),
    )
    (c,) = select_candidates(both, levels(), CFG, NOW, sides=["call"])
    assert c.side == "call"
    assert select_candidates(both, levels(), CFG, NOW, sides=[]) == []


def test_refresh_reprices_on_fresh_quotes_and_keeps_the_id() -> None:
    (c,) = select_candidates(
        chain(q(679, "P", 0.80, 0.86, -0.12), q(674, "P", 0.20, 0.24)), levels(), CFG, NOW
    )
    later = datetime(2026, 10, 7, 14, 31, tzinfo=UTC)
    fresh = refresh_candidate(c, q(679, "P", 0.70, 0.74, -0.10), q(674, "P", 0.18, 0.22), later)
    assert fresh is not None
    assert fresh.spread_id == c.spread_id
    assert fresh.credit_mid == pytest.approx(0.52) and fresh.quote_time == later
    assert refresh_candidate(c, q(679, "P", 0.70, 0.74), q(674, "P", 0.18, None), later) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_selector.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.selector'`.

- [ ] **Step 3: Implement `src/spreads/selector.py`**

```python
"""Candidate credit verticals placed beyond the day's action zone.

A put spread's short strike sits below BOTH the expected-move floor (spot − em × em_multiple)
and the put wall less a buffer; a call spread's short strike above both the expected-move
ceiling and the call wall plus a buffer. Per side, the closest strike that clears the delta cap
and the minimum credit wins. Further out of the money only gets cheaper, so the walk stops at
the first strike whose credit is too thin. Pure: no IBKR, no I/O, and no gating — that is
``risk.validate``'s job.
"""

from __future__ import annotations

from datetime import date, datetime

from src.common.config import SpreadsCfg
from src.common.schemas import ChainOption, ChainSnapshot, GexLevels, SpreadCandidate, SpreadSide
from src.spreads.pricing import ET


def short_boundary(side: SpreadSide, levels: GexLevels, cfg: SpreadsCfg) -> float | None:
    """Furthest-in strike a short leg may use. None (no trade) without an expected move."""
    if levels.expected_move is None:
        return None
    s = cfg.selection
    move = levels.expected_move * s.em_multiple
    buffer = levels.spot * s.wall_buffer_pct
    if side == "put":
        floor = levels.spot - move
        if levels.put_wall is not None:
            floor = min(floor, levels.put_wall - buffer)
        return floor
    ceiling = levels.spot + move
    if levels.call_wall is not None:
        ceiling = max(ceiling, levels.call_wall + buffer)
    return ceiling


def make_spread_id(
    side: SpreadSide, expiry: date, short_strike: float, long_strike: float, now: datetime
) -> str:
    return (
        f"{expiry:%Y%m%d}-{side[0].upper()}{short_strike:g}-{long_strike:g}"
        f"-{now.astimezone(ET):%H%M%S}"
    )


def _build(
    spread_id: str,
    side: SpreadSide,
    short_q: ChainOption,
    long_q: ChainOption,
    width: float,
    spot: float,
    now: datetime,
) -> SpreadCandidate | None:
    short_mid, long_mid = short_q.mid, long_q.mid
    if short_mid is None or long_mid is None or short_q.bid is None or long_q.ask is None:
        return None
    return SpreadCandidate(
        spread_id=spread_id,
        side=side,
        expiry=short_q.expiry,
        short_strike=short_q.strike,
        long_strike=long_q.strike,
        width=width,
        short_con_id=short_q.con_id,
        long_con_id=long_q.con_id,
        credit_mid=round(short_mid - long_mid, 4),
        credit_natural=round(short_q.bid - long_q.ask, 4),
        short_delta=short_q.delta,
        short_leg_spread_pct=short_q.spread_pct,
        long_leg_spread_pct=long_q.spread_pct,
        spot=spot,
        quote_time=now,
    )


def select_candidates(
    chain: ChainSnapshot,
    levels: GexLevels,
    cfg: SpreadsCfg,
    now: datetime,
    sides: list[SpreadSide] | None = None,
) -> list[SpreadCandidate]:
    """At most one candidate per side. *sides* (the entry trigger's choice) narrows the walk."""
    s = cfg.selection
    today = now.astimezone(ET).date()
    out: list[SpreadCandidate] = []
    for side in s.sides if sides is None else [x for x in s.sides if x in sides]:
        boundary = short_boundary(side, levels, cfg)
        if boundary is None:
            continue
        right = "P" if side == "put" else "C"
        legs = {round(o.strike, 2): o for o in chain.options if o.right == right and o.expiry == today}
        if side == "put":
            shorts = sorted((k for k in legs if k <= boundary), reverse=True)
        else:
            shorts = sorted(k for k in legs if k >= boundary)
        for k in shorts:
            long_k = round(k - s.width if side == "put" else k + s.width, 2)
            long_q = legs.get(long_k)
            if long_q is None:
                continue
            short_q = legs[k]
            if short_q.delta is not None and abs(short_q.delta) > s.short_delta_max:
                continue
            cand = _build(
                make_spread_id(side, today, k, long_k, now),
                side,
                short_q,
                long_q,
                s.width,
                chain.spot,
                now,
            )
            if cand is None or cand.credit_mid <= 0:
                continue
            if cand.credit_mid < s.min_credit_pct_of_width * s.width:
                break
            out.append(cand)
            break
    return out


def refresh_candidate(
    c: SpreadCandidate, short_q: ChainOption, long_q: ChainOption, now: datetime
) -> SpreadCandidate | None:
    """The same spread repriced on fresh leg quotes (the send-time re-gate's input)."""
    return _build(c.spread_id, c.side, short_q, long_q, c.width, c.spot, now)
```

- [ ] **Step 4: Run the tests and the gate**

Run: `python -m pytest tests/test_spreads_selector.py -q && ruff check . && mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff format src/spreads/selector.py tests/test_spreads_selector.py
git add src/spreads/selector.py tests/test_spreads_selector.py
git commit -m "feat(spreads): candidate verticals beyond the expected move and the walls"
```

---

### Task 6A: The session tape and the entry trigger

Added by the 2026-10-07 amendment. It runs after Task 6 and before Task 7; nothing before it depends on it. See Design → "Entry rules borrowed from OPG".

**Files:**
- Create: `src/spreads/tape.py`, `tests/test_spreads_tape.py`

**Interfaces:**
- Consumes: `SessionSnapshot`, `SpreadSide`, `SpreadTrigger` (Task 4); `SpreadsCfg.entry`, `SpreadsCfg.selection.sides` (Task 1).
- Produces:
  - `SessionTape(day, day_em=None)`, a mutable dataclass, with:
    - attributes `prior_close`, `open`, `high`, `low`, `high_at`, `low_at`, `first_seen`, `last`, `last_at`, `day_em`
    - `observe(snap: SessionSnapshot) -> None`
    - `drop() -> float | None`, `rise() -> float | None` (points, ≥ 0)
    - `move_em(side) -> float | None` (the move that side sells against, in units of `day_em`)
    - `gap_pct() -> float | None`
    - `extreme_at(side) -> datetime | None` (when the low/high was made; the first observation when unknown)
  - `trigger(tape: SessionTape | None, now, cfg) -> SpreadTrigger`, with these reasons: `always`, `armed` (both fire), and `no_tape`, `stale_tape`, `no_expected_move`, `no_move`, `still_moving`, `runaway_move` (no side)

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_tape.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import SessionSnapshot
from src.spreads.tape import SessionTape, trigger

TODAY = date(2026, 10, 7)
_BASE = get_config().spreads
# Pinned explicitly so a YAML retune never silently changes these tests.
CFG = _BASE.model_copy(
    update={
        "selection": _BASE.selection.model_copy(update={"sides": ["put", "call"]}),
        "entry": _BASE.entry.model_copy(
            update={"trigger": "move", "min_move_em": 0.5, "max_move_em": 1.5, "stall_minutes": 10,
                    "max_tape_age_seconds": 120.0}
        ),
    }
)


def et(hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(2026, 10, 7, h + 4, m, tzinfo=UTC)  # EDT = UTC−4


def snap(hhmm: str, last: float, *, high=None, low=None, open_=692.0, prior=693.5) -> SessionSnapshot:
    return SessionSnapshot(as_of=et(hhmm), last=last, open=open_, high=high, low=low, prior_close=prior)


def flush_tape() -> SessionTape:
    """Prior close 693.5, opens 692.0, flushes to 689.8 at 09:36, then holds above it."""
    tape = SessionTape(day=TODAY, day_em=5.8)
    tape.observe(snap("09:31", 692.0, high=692.2, low=691.9))
    tape.observe(snap("09:36", 689.8, high=692.2, low=689.8))
    tape.observe(snap("09:41", 690.4, high=692.2, low=689.8))
    return tape


def test_observe_tracks_the_session_and_when_extremes_were_made() -> None:
    tape = flush_tape()
    assert (tape.prior_close, tape.open, tape.high, tape.low) == (693.5, 692.0, 692.2, 689.8)
    assert tape.high_at is None  # 692.2 printed before the first observation
    assert tape.extreme_at("call") == et("09:31")  # unknown → the first observation
    assert tape.low_at == et("09:36") and tape.extreme_at("put") == et("09:36")
    assert tape.last == 690.4 and tape.last_at == et("09:41")
    assert tape.gap_pct() == pytest.approx(692.0 / 693.5 - 1)


def test_drop_counts_the_gap_from_the_prior_close_and_rise_mirrors_it() -> None:
    tape = flush_tape()
    assert tape.drop() == pytest.approx(693.5 - 690.4)
    assert tape.rise() == pytest.approx(690.4 - 689.8)
    assert tape.move_em("put") == pytest.approx((693.5 - 690.4) / 5.8)


def test_a_missing_session_stat_never_wipes_a_known_one() -> None:
    tape = flush_tape()
    tape.observe(SessionSnapshot(as_of=et("09:42"), last=690.5))
    assert (tape.prior_close, tape.open, tape.low) == (693.5, 692.0, 689.8)


def test_puts_arm_only_after_the_flush_has_stalled() -> None:
    tape = flush_tape()
    early = trigger(tape, et("09:41"), CFG)
    assert early.sides == [] and early.reason == "still_moving"
    tape.observe(snap("09:47", 690.0, high=692.2, low=689.8))
    armed = trigger(tape, et("09:47"), CFG)
    assert armed.sides == ["put"] and armed.reason == "armed"
    assert armed.move_em == pytest.approx((693.5 - 690.0) / 5.8)


def test_a_small_move_never_arms() -> None:
    tape = SessionTape(day=TODAY, day_em=5.8)
    tape.observe(snap("09:31", 693.4, high=693.6, low=693.2, open_=693.5))
    tape.observe(snap("09:50", 693.0, high=693.6, low=692.9, open_=693.5))
    t = trigger(tape, et("09:50"), CFG)
    assert t.sides == [] and t.reason == "no_move"


def test_a_runaway_move_is_a_trend_day_and_never_faded() -> None:
    tape = SessionTape(day=TODAY, day_em=4.0)
    tape.observe(snap("09:31", 690.0, high=690.0, low=690.0, open_=690.0, prior=690.0))
    tape.observe(snap("09:40", 682.0, high=690.0, low=682.0, open_=690.0, prior=690.0))
    tape.observe(snap("09:55", 683.0, high=690.0, low=682.0, open_=690.0, prior=690.0))
    t = trigger(tape, et("09:55"), CFG)
    assert t.sides == [] and t.reason == "runaway_move"  # 7 points = 1.75 × the expected move


def test_both_sides_moved_picks_the_most_recent_stalled_extreme() -> None:
    tape = SessionTape(day=TODAY, day_em=6.0)
    tape.observe(snap("09:31", 689.0, high=689.2, low=688.9, open_=690.0, prior=690.0))
    tape.observe(snap("09:33", 686.0, high=689.2, low=686.0, open_=690.0, prior=690.0))
    tape.observe(snap("09:40", 694.0, high=694.0, low=686.0, open_=690.0, prior=690.0))
    tape.observe(snap("10:00", 690.0, high=694.0, low=686.0, open_=690.0, prior=690.0))
    t = trigger(tape, et("10:00"), CFG)
    assert t.sides == ["call"] and t.reason == "armed"  # the 09:40 high is newer than the 09:33 low


def test_always_mode_offers_every_configured_side() -> None:
    always = CFG.model_copy(update={"entry": CFG.entry.model_copy(update={"trigger": "always"})})
    t = trigger(None, et("10:00"), always)
    assert t.sides == ["put", "call"] and t.reason == "always"


# Review Focus 7 — no tape, a stale tape, or no yardstick never arms.
def test_missing_or_stale_inputs_never_arm() -> None:
    assert trigger(None, et("09:47"), CFG).reason == "no_tape"
    tape = flush_tape()
    tape.observe(snap("09:47", 690.0, high=692.2, low=689.8))
    assert trigger(tape, et("09:50"), CFG).reason == "stale_tape"  # 180 s old
    tape.day_em = None
    assert trigger(tape, et("09:47"), CFG).reason == "no_expected_move"


# Review Focus 6 — a restart mid-move waits a full stall window from its first observation.
def test_a_restart_cannot_hurry_an_entry() -> None:
    tape = SessionTape(day=TODAY, day_em=5.8)
    tape.observe(snap("10:00", 690.0, high=692.2, low=689.8))  # the low was made before we started
    assert tape.low_at is None
    assert trigger(tape, et("10:00"), CFG).reason == "still_moving"
    tape.observe(snap("10:05", 690.1, high=692.2, low=689.8))
    assert trigger(tape, et("10:05"), CFG).reason == "still_moving"
    tape.observe(snap("10:10", 690.2, high=692.2, low=689.8))
    assert trigger(tape, et("10:10"), CFG).sides == ["put"]
```

Check the numbers:
- Flush: the put side sells against a drop from max(high 692.2, prior close 693.5) = 693.5. At 09:47 the drop is 3.5 = 0.60 × the 5.8 expected move, between 0.5 and 1.5. The low was made at 09:36, 11 minutes earlier, so it has stalled. At 09:41 it is only 5 minutes, so `still_moving`.
- The call side in the flush rises only 0.6 above the 689.8 low (0.10×), so it never arms.
- Both sides: drop = 694 − 690 = 4 and rise = 690 − 686 = 4 (0.67× each). Both stalled; the newer extreme (the 09:40 high) wins, so calls.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_tape.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.tape'`.

- [ ] **Step 3: Implement `src/spreads/tape.py`**

```python
"""The session tape and the entry trigger — OPG's "sell after the move", as rules.

The service samples the traded index every tick (``SessionSnapshot``: last price plus IBKR's
open / high / low / prior-close session stats) into a ``SessionTape``. ``trigger`` then decides
which side, if any, may be sold right now:

- a put spread only after price has dropped at least ``entry.min_move_em`` × the day's expected
  move below the higher of the prior close and today's high (so a gap down counts), and has
  made no new low for ``entry.stall_minutes``;
- a call spread only after the mirror-image rise has stalled;
- never against a move beyond ``entry.max_move_em`` × (a trend day: OPG's first loss);
- one side at a time: when both qualify, the side whose extreme is the most recent.

When the tape cannot say when the current high or low was made (the service started after it
printed), the stall clock starts at the first observation, so a restart can only delay an entry.
Pure: no IBKR, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.common.config import SpreadsCfg
from src.common.schemas import SessionSnapshot, SpreadSide, SpreadTrigger

_EPS = 1e-9
# When no side arms, the most informative reason is reported.
_RANK = {"no_move": 0, "still_moving": 1, "runaway_move": 2}


@dataclass
class SessionTape:
    """One ET session of the traded index, as this process has seen it."""

    day: date
    day_em: float | None = None  # the day's first expected move: the trigger's yardstick
    prior_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    high_at: datetime | None = None  # None: made before the first observation
    low_at: datetime | None = None
    first_seen: datetime | None = None
    last: float | None = None
    last_at: datetime | None = None

    def observe(self, snap: SessionSnapshot) -> None:
        first = self.first_seen is None
        if first:
            self.first_seen = snap.as_of
        if snap.prior_close is not None and snap.prior_close > 0:
            self.prior_close = snap.prior_close
        if snap.open is not None and snap.open > 0:
            self.open = snap.open
        hi = snap.last if snap.high is None else max(snap.high, snap.last)
        lo = snap.last if snap.low is None else min(snap.low, snap.last)
        if self.high is None or hi > self.high + _EPS:
            # On the first read, a session high above the last print was made at an unknown
            # earlier time. Any later new high was made since the previous read.
            self.high = hi
            self.high_at = snap.as_of if not first or snap.last >= hi - _EPS else None
        if self.low is None or lo < self.low - _EPS:
            self.low = lo
            self.low_at = snap.as_of if not first or snap.last <= lo + _EPS else None
        self.last, self.last_at = snap.last, snap.as_of

    def drop(self) -> float | None:
        """How far price sits below the higher of the prior close and today's high (≥ 0)."""
        if self.last is None or self.high is None:
            return None
        top = self.high if self.prior_close is None else max(self.high, self.prior_close)
        return max(0.0, top - self.last)

    def rise(self) -> float | None:
        """How far price sits above the lower of the prior close and today's low (≥ 0)."""
        if self.last is None or self.low is None:
            return None
        bottom = self.low if self.prior_close is None else min(self.low, self.prior_close)
        return max(0.0, self.last - bottom)

    def move_em(self, side: SpreadSide) -> float | None:
        """The move a *side* would sell against, in units of the day's expected move."""
        move = self.drop() if side == "put" else self.rise()
        if move is None or not self.day_em or self.day_em <= 0:
            return None
        return move / self.day_em

    def gap_pct(self) -> float | None:
        if self.open is None or not self.prior_close:
            return None
        return self.open / self.prior_close - 1.0

    def extreme_at(self, side: SpreadSide) -> datetime | None:
        """When the low (puts) or high (calls) was made; the first observation when unknown."""
        at = self.low_at if side == "put" else self.high_at
        return at if at is not None else self.first_seen


def trigger(tape: SessionTape | None, now: datetime, cfg: SpreadsCfg) -> SpreadTrigger:
    """Which side may be sold now. ``entry.trigger: always`` offers every configured side."""
    e = cfg.entry
    if e.trigger == "always":
        return SpreadTrigger(sides=list(cfg.selection.sides), reason="always")
    if tape is None or tape.last_at is None:
        return SpreadTrigger(reason="no_tape")
    if (now - tape.last_at).total_seconds() > e.max_tape_age_seconds:
        return SpreadTrigger(reason="stale_tape")
    if not tape.day_em or tape.day_em <= 0:
        return SpreadTrigger(reason="no_expected_move")
    armed: list[tuple[datetime, float, SpreadSide]] = []
    reason = "no_move"
    best: float | None = None
    for side in cfg.selection.sides:
        m = tape.move_em(side)
        if m is None:
            continue
        best = m if best is None else max(best, m)
        if m < e.min_move_em:
            continue
        if e.max_move_em is not None and m > e.max_move_em:
            why = "runaway_move"
        else:
            at = tape.extreme_at(side)
            if at is not None and (now - at).total_seconds() >= e.stall_minutes * 60:
                armed.append((at, m, side))
                continue
            why = "still_moving"
        if _RANK[why] > _RANK[reason]:
            reason = why
    if not armed:
        return SpreadTrigger(reason=reason, move_em=best)
    _, m, side = max(armed, key=lambda a: (a[0], a[1]))
    return SpreadTrigger(sides=[side], reason="armed", move_em=m)
```

- [ ] **Step 4: Run the tests and the gate**

Run: `python -m pytest tests/test_spreads_tape.py -q && ruff check . && mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff format src/spreads/tape.py tests/test_spreads_tape.py
git add src/spreads/tape.py tests/test_spreads_tape.py
git commit -m "feat(spreads): session tape and the move/stall/one-side entry trigger"
```

---

### Task 7: The deterministic spreads gate

**Files:**
- Create: `src/spreads/risk.py`, `tests/test_spreads_risk.py`

**Interfaces:**
- Consumes:
  - `SpreadCandidate`, `SpreadRiskContext`, `SpreadVerdict`, `GexLevels` (Task 4)
  - `src.common.market_hours.is_trading_day`, `is_early_close`, `next_session`
  - `pricing.ET`
  - `SpreadsCfg`
- Produces:
  - `size(c, cfg, capital_usd) -> int`: ⌊`max_loss_pct_of_capital` × capital ÷ max loss per contract⌋, capped by `max_contracts`
  - `validate(c, ctx, cfg) -> SpreadVerdict` (sizes off `ctx.capital_usd`), with these reason strings:
    - `spreads_disabled`
    - `not_trading_day`
    - `early_close_day`
    - `event_day` (a whole-day `risk.events` entry)
    - `event_window` (a timed `risk.events` entry, before its `until`)
    - `ex_dividend_window` (a call spread on, or the session before, a `risk.ex_dividend_dates` entry)
    - `outside_entry_window`
    - `not_0dte`
    - `no_levels`
    - `regime_unknown`
    - `negative_gamma` (only with `negative_gamma_action: skip`; the shipped `allow` trades it)
    - `near_gamma_flip`
    - `stale_quote`
    - `width_mismatch`
    - `credit_below_min`
    - `no_natural_credit`
    - `quote_too_wide`
    - `no_delta`
    - `delta_too_high`
    - `max_open_spreads`
    - `max_trades_per_day`
    - `other_side_traded_today` (`risk.one_side_per_day`)
    - `daily_loss_limit` (today's realized loss ≥ `max_daily_loss_pct_of_capital` × capital)
    - `max_loss_per_trade` (capital too small for one contract at `max_loss_pct_of_capital`)
    - `max_total_risk` (open risk + this spread > `max_total_risk_pct_of_capital` × capital)
    - `account_unknown`
    - `excess_liquidity_floor`

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_risk.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.config import SpreadsEventCfg, get_config
from src.common.schemas import GexLevels, SpreadCandidate, SpreadRiskContext
from src.spreads.risk import size, validate

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)  # Wed 10:30 EDT
_BASE = get_config().spreads
# Pinned explicitly so a YAML retune never silently changes these tests. The gate's own
# negative-gamma rule is tested under "skip"; the shipped "allow" has its own test below.
CFG = _BASE.model_copy(
    update={
        "enabled": True,
        "schedule": _BASE.schedule.model_copy(update={"entry_start": "09:35", "entry_end": "13:30"}),
        "gex": _BASE.gex.model_copy(update={"negative_gamma_action": "skip", "flip_buffer_pct": 0.002}),
        "selection": _BASE.selection.model_copy(
            update={"width": 5.0, "short_delta_max": 0.15, "min_credit_pct_of_width": 0.10, "max_leg_spread_pct": 0.30}
        ),
        "risk": _BASE.risk.model_copy(
            update={"starting_capital_usd": 100_000.0, "max_loss_pct_of_capital": 0.10, "max_total_risk_pct_of_capital": 0.10, "max_daily_loss_pct_of_capital": 0.10, "max_contracts": 100, "max_open_spreads": 2, "max_trades_per_day": 2, "one_side_per_day": True, "min_excess_liquidity_usd": 10_000.0, "max_quote_age_seconds": 20.0, "events": [], "ex_dividend_dates": []}
        ),
    }
)


def cand(now: datetime = NOW, **kw) -> SpreadCandidate:
    base = dict(
        spread_id="s1",
        side="put",
        expiry=now.astimezone(UTC).date() if "expiry" not in kw else kw["expiry"],
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        credit_mid=0.61,
        credit_natural=0.56,
        short_delta=-0.12,
        short_leg_spread_pct=0.07,
        long_leg_spread_pct=0.18,
        spot=690.0,
        quote_time=now,
    )
    base.update(kw)
    return SpreadCandidate(**base)


def lv(**kw) -> GexLevels:
    base = dict(as_of=NOW, spot=690.0, net_gex=1e9, regime="positive", flip=680.0, expected_move=6.0)
    base.update(kw)
    return GexLevels(**base)


def ctx(now: datetime = NOW, **kw) -> SpreadRiskContext:
    base = dict(
        now=now,
        levels=lv(),
        open_spreads=0,
        open_risk_usd=0.0,
        trades_today=0,
        realized_pnl_today_usd=0.0,
        excess_liquidity_usd=50_000.0,
        capital_usd=100_000.0,
    )
    base.update(kw)
    return SpreadRiskContext(**base)


def test_a_clean_candidate_passes_sized_to_ten_percent_of_capital() -> None:
    v = validate(cand(), ctx(), CFG)
    assert v.approved and v.reasons == []
    assert v.contracts == 22  # 10% of $100,000 ÷ (5 − 0.61) × 100 = 22.8


def test_size_follows_the_books_capital_and_the_contract_ceiling() -> None:
    assert size(cand(), CFG, 100_000.0) == 22
    assert size(cand(), CFG, 120_000.0) == 27  # capital grew with realized wins
    assert size(cand(), CFG, 90_000.0) == 20  # and shrank after losses
    assert size(cand(), CFG, 4_000.0) == 0  # 10% = $400 cannot cover one $439 max loss
    capped = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"max_contracts": 5})})
    assert size(cand(), capped, 100_000.0) == 5
    assert size(cand(credit_mid=-0.1), CFG, 100_000.0) == 0


@pytest.mark.parametrize(
    ("c_kw", "ctx_kw", "reason"),
    [
        ({}, {"levels": None}, "no_levels"),
        ({}, {"levels": lv(regime="negative")}, "negative_gamma"),
        ({}, {"levels": lv(regime="unknown")}, "regime_unknown"),
        ({}, {"levels": lv(flip=689.0)}, "near_gamma_flip"),
        ({"quote_time": NOW - timedelta(seconds=60)}, {}, "stale_quote"),
        ({"width": 10.0}, {}, "width_mismatch"),
        ({"credit_mid": 0.40}, {}, "credit_below_min"),
        ({"credit_natural": -0.01}, {}, "no_natural_credit"),
        ({"long_leg_spread_pct": 0.9}, {}, "quote_too_wide"),
        ({"short_delta": None}, {}, "no_delta"),
        ({"short_delta": -0.30}, {}, "delta_too_high"),
        ({"expiry": date(2026, 10, 8)}, {}, "not_0dte"),
        ({}, {"open_spreads": 2}, "max_open_spreads"),
        ({}, {"trades_today": 2}, "max_trades_per_day"),
        ({}, {"realized_pnl_today_usd": -10_000.0}, "daily_loss_limit"),
        ({}, {"open_risk_usd": 700.0}, "max_total_risk"),  # 700 + 22 × 439 > 10% of 100k
        ({}, {"capital_usd": 4_000.0}, "max_loss_per_trade"),
        ({}, {"excess_liquidity_usd": None}, "account_unknown"),
        ({}, {"excess_liquidity_usd": 5_000.0}, "excess_liquidity_floor"),
    ],
)
def test_each_gate_rejects(c_kw, ctx_kw, reason) -> None:
    v = validate(cand(**c_kw), ctx(**ctx_kw), CFG)
    assert not v.approved and v.contracts == 0
    assert reason in v.reasons


def test_disabled_config_rejects() -> None:
    v = validate(cand(), ctx(), CFG.model_copy(update={"enabled": False}))
    assert "spreads_disabled" in v.reasons


def test_negative_gamma_allowed_when_configured() -> None:
    allow = CFG.model_copy(update={"gex": CFG.gex.model_copy(update={"negative_gamma_action": "allow"})})
    assert validate(cand(), ctx(levels=lv(regime="negative")), allow).approved


def test_negative_gamma_is_traded_by_default() -> None:
    assert _BASE.gex.negative_gamma_action == "allow"
    shipped = CFG.model_copy(update={"gex": _BASE.gex})
    assert validate(cand(), ctx(levels=lv(regime="negative")), shipped).approved


def test_whole_day_events_block_entries() -> None:
    fomc = [SpreadsEventCfg(day=date(2026, 10, 7), label="FOMC")]
    ev = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"events": fomc})})
    assert "event_day" in validate(cand(), ctx(), ev).reasons


def test_timed_events_block_only_until_their_time() -> None:
    speech = [SpreadsEventCfg(day=date(2026, 10, 7), until="10:45", label="Fed chair speech")]
    ev = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"events": speech})})
    assert "event_window" in validate(cand(), ctx(), ev).reasons  # NOW is 10:30
    eleven = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
    assert validate(cand(eleven), ctx(eleven), ev).approved
    other_day = [SpreadsEventCfg(day=date(2026, 10, 8), label="FOMC")]
    assert validate(cand(), ctx(), CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"events": other_day})})).approved


def test_no_call_spreads_around_an_ex_dividend_date() -> None:
    call = cand(side="call", short_strike=701.0, long_strike=706.0, short_delta=0.11)
    on_the_day = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"ex_dividend_dates": [date(2026, 10, 7)]})})
    day_before = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"ex_dividend_dates": [date(2026, 10, 8)]})})
    assert "ex_dividend_window" in validate(call, ctx(), on_the_day).reasons
    assert "ex_dividend_window" in validate(call, ctx(), day_before).reasons
    assert validate(cand(), ctx(), day_before).approved  # put spreads are unaffected
    later = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"ex_dividend_dates": [date(2026, 10, 9)]})})
    assert validate(call, ctx(), later).approved


def test_one_side_per_day() -> None:
    assert "other_side_traded_today" in validate(cand(), ctx(sides_today=["call"]), CFG).reasons
    assert validate(cand(), ctx(sides_today=["put"]), CFG).approved
    off = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"one_side_per_day": False})})
    assert validate(cand(), ctx(sides_today=["call"]), off).approved


def test_opening_entries_start_at_0935() -> None:
    t0934 = datetime(2026, 10, 7, 13, 34, tzinfo=UTC)
    t0936 = datetime(2026, 10, 7, 13, 36, tzinfo=UTC)
    assert "outside_entry_window" in validate(cand(t0934), ctx(t0934), CFG).reasons
    assert validate(cand(t0936), ctx(t0936), CFG).approved


# Review Focus 5 — the ET clock for an operator in SGT.
def test_entry_window_tracks_et_across_dst() -> None:
    december_1030 = datetime(2026, 12, 2, 15, 30, tzinfo=UTC)  # EST: 10:30
    december_0930 = datetime(2026, 12, 2, 14, 30, tzinfo=UTC)  # EST: 09:30
    assert validate(cand(december_1030), ctx(december_1030), CFG).approved
    early = validate(cand(december_0930), ctx(december_0930), CFG)
    assert "outside_entry_window" in early.reasons


def test_holiday_and_early_close_days_are_skipped() -> None:
    thanksgiving = datetime(2026, 11, 26, 15, 30, tzinfo=UTC)
    black_friday = datetime(2026, 11, 27, 15, 30, tzinfo=UTC)
    assert "not_trading_day" in validate(cand(thanksgiving), ctx(thanksgiving), CFG).reasons
    assert "early_close_day" in validate(cand(black_friday), ctx(black_friday), CFG).reasons


def test_after_entry_end_is_outside_the_window() -> None:
    late = datetime(2026, 10, 7, 17, 31, tzinfo=UTC)  # 13:31 EDT
    assert "outside_entry_window" in validate(cand(late), ctx(late), CFG).reasons
```

The `cand()` helper's `expiry` default uses `now.astimezone(UTC).date()`. That gives the same date as ET for every timestamp in these tests (all are between 13:34 and 17:31 UTC).

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_risk.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.risk'`.

- [ ] **Step 3: Implement `src/spreads/risk.py`**

```python
"""The spreads rules engine — the only gate in front of a spreads order.

Deterministic Python, no LLM, no I/O. It runs twice per trade: at decision time on the
candidate, and again at send time on the same spread repriced from fresh leg quotes
(``executor.SpreadExecutor.open``). Every rejection names its reason; ``approved`` is simply
"no reasons". Sizing lives here too, so nothing outside this module can change a contract count.
"""

from __future__ import annotations

import math

from src.common.config import SpreadsCfg
from src.common.market_hours import is_early_close, is_trading_day, next_session
from src.common.schemas import SpreadCandidate, SpreadRiskContext, SpreadVerdict
from src.spreads.pricing import ET


def size(c: SpreadCandidate, cfg: SpreadsCfg, capital_usd: float) -> int:
    """Contracts whose combined max loss stays within ``max_loss_pct_of_capital`` of the book."""
    per_contract = c.max_loss_per_contract
    if per_contract <= 0 or c.credit_mid <= 0 or capital_usd <= 0:
        return 0
    n = math.floor(cfg.risk.max_loss_pct_of_capital * capital_usd / per_contract)
    return max(0, min(n, cfg.risk.max_contracts))


def validate(c: SpreadCandidate, ctx: SpreadRiskContext, cfg: SpreadsCfg) -> SpreadVerdict:
    r, s, sched = cfg.risk, cfg.selection, cfg.schedule
    reasons: list[str] = []
    now_et = ctx.now.astimezone(ET)
    today = now_et.date()
    hhmm = now_et.strftime("%H:%M")

    # --- Calendar and clock.
    if not cfg.enabled:
        reasons.append("spreads_disabled")
    if not is_trading_day(today):
        reasons.append("not_trading_day")
    elif sched.skip_early_close_days and is_early_close(today):
        reasons.append("early_close_day")
    for ev in r.events:
        if ev.day == today and (ev.until is None or hhmm < ev.until):
            reasons.append("event_day" if ev.until is None else "event_window")
            break
    if c.side == "call" and r.ex_dividend_dates:
        exdiv = set(r.ex_dividend_dates)
        if today in exdiv or next_session(today) in exdiv:
            reasons.append("ex_dividend_window")  # short American calls get exercised for the dividend
    if not (sched.entry_start <= hhmm < sched.entry_end):
        reasons.append("outside_entry_window")
    if c.expiry != today:
        reasons.append("not_0dte")

    # --- Gamma regime. Negative gamma is traded by default ("allow") and tagged on the
    # position (store.open_position); "skip" turns it back into a rejection.
    lv = ctx.levels
    if lv is None:
        reasons.append("no_levels")
    else:
        if lv.regime == "unknown":
            reasons.append("regime_unknown")
        elif lv.regime == "negative" and cfg.gex.negative_gamma_action == "skip":
            reasons.append("negative_gamma")
        if lv.flip is not None and lv.spot > 0:
            if abs(lv.spot - lv.flip) / lv.spot < cfg.gex.flip_buffer_pct:
                reasons.append("near_gamma_flip")

    # --- Quote quality and economics.
    if (ctx.now - c.quote_time).total_seconds() > r.max_quote_age_seconds:
        reasons.append("stale_quote")
    if abs(c.width - s.width) > 1e-9:
        reasons.append("width_mismatch")
    if c.credit_mid < s.min_credit_pct_of_width * s.width:
        reasons.append("credit_below_min")
    if c.credit_natural <= 0:
        reasons.append("no_natural_credit")
    leg_spreads = [p for p in (c.short_leg_spread_pct, c.long_leg_spread_pct) if p is not None]
    if len(leg_spreads) < 2 or max(leg_spreads) > s.max_leg_spread_pct:
        reasons.append("quote_too_wide")
    if c.short_delta is None:
        reasons.append("no_delta")
    elif abs(c.short_delta) > s.short_delta_max:
        reasons.append("delta_too_high")

    # --- Book-level limits, as shares of the book's capital (starting capital + realized P&L).
    cap = ctx.capital_usd
    if ctx.open_spreads >= r.max_open_spreads:
        reasons.append("max_open_spreads")
    if ctx.trades_today >= r.max_trades_per_day:
        reasons.append("max_trades_per_day")
    if r.one_side_per_day and any(side != c.side for side in ctx.sides_today):
        reasons.append("other_side_traded_today")
    if ctx.realized_pnl_today_usd <= -r.max_daily_loss_pct_of_capital * cap:
        reasons.append("daily_loss_limit")
    n = size(c, cfg, cap)
    if n < 1:
        reasons.append("max_loss_per_trade")
    elif ctx.open_risk_usd + n * c.max_loss_per_contract > r.max_total_risk_pct_of_capital * cap:
        reasons.append("max_total_risk")
    if ctx.excess_liquidity_usd is None:
        reasons.append("account_unknown")
    elif ctx.excess_liquidity_usd < r.min_excess_liquidity_usd:
        reasons.append("excess_liquidity_floor")

    approved = not reasons
    return SpreadVerdict(
        spread_id=c.spread_id, approved=approved, contracts=n if approved else 0, reasons=reasons
    )
```

- [ ] **Step 4: Run the tests and the gate**

Run: `python -m pytest tests/test_spreads_risk.py -q && ruff check . && mypy src`
Expected: PASS. If `test_holiday_and_early_close_days_are_skipped` fails, check `src/common/market_hours._early_closes` for 2026. The day after Thanksgiving is an early close there, so a failure means the test date is wrong, not the gate.

- [ ] **Step 5: Commit**

```bash
ruff format src/spreads/risk.py tests/test_spreads_risk.py
git add src/spreads/risk.py tests/test_spreads_risk.py
git commit -m "feat(spreads): deterministic rules gate and sizing"
```

---

### Task 8: Exit manager and broker reconciliation (pure)

**Files:**
- Create: `src/spreads/manager.py`, `tests/test_spreads_manager.py`

**Interfaces:**
- Consumes: `SpreadPosition`, `ChainOption`, `SpreadExit` (Task 4); `pricing.ET`; `SpreadsCfg`.
- Produces:
  - `debit_to_close(short_q, long_q) -> tuple[float | None, float | None]`, returning (mid, natural)
  - `short_strike_touched(pos, spot) -> bool`
  - `evaluate_exit(pos, short_q, long_q, spot, now, cfg) -> SpreadExit | None`, whose reasons, in priority order, are `time_stop` / `expire_worthless` (at `force_close`), `stop_loss`, `profit_take`, `strike_touch`, `max_hold`
  - `intrinsic_debit(pos, spot) -> float`
  - `reconcile(expected, broker_legs) -> list[str]`

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_manager.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, SpreadPosition
from src.spreads.manager import (
    debit_to_close,
    evaluate_exit,
    intrinsic_debit,
    reconcile,
    short_strike_touched,
)

TODAY = date(2026, 10, 7)
MIDDAY = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)  # 12:00 EDT
CLOSE = datetime(2026, 10, 7, 19, 46, tzinfo=UTC)  # 15:46 EDT, past force_close
_BASE = get_config().spreads
CFG = _BASE.model_copy(
    update={
        "exits": _BASE.exits.model_copy(
            update={"profit_take_pct": 50.0, "stop_debit_multiple": 2.0, "close_on_short_strike_touch": True, "max_hold_minutes": 150, "let_expire": True, "let_expire_max_debit": 0.05}
        )
    }
)


def pos(**kw) -> SpreadPosition:
    base = dict(
        spread_id="s1",
        mode="paper",
        side="put",
        expiry=TODAY,
        short_strike=680.0,
        long_strike=675.0,
        width=5.0,
        contracts=1,
        entry_credit=0.60,
        opened_at=MIDDAY,
        short_con_id=111,
        long_con_id=222,
    )
    base.update(kw)
    return SpreadPosition(**base)


def legs(short_bid, short_ask, long_bid, long_ask):
    s = ChainOption(strike=680, right="P", expiry=TODAY, bid=short_bid, ask=short_ask)
    lg = ChainOption(strike=675, right="P", expiry=TODAY, bid=long_bid, ask=long_ask)
    return s, lg


def test_debit_to_close_mid_and_natural() -> None:
    mid, nat = debit_to_close(*legs(0.40, 0.44, 0.10, 0.14))
    assert mid == pytest.approx(0.30) and nat == pytest.approx(0.34)
    assert debit_to_close(*legs(None, 0.44, 0.10, 0.14)) == (None, pytest.approx(0.34))


def test_profit_take_at_half_the_credit() -> None:
    e = evaluate_exit(pos(), *legs(0.38, 0.42, 0.09, 0.11), 690.0, MIDDAY, CFG)
    assert e is not None and e.reason == "profit_take" and e.close


def test_stop_at_twice_the_credit() -> None:
    e = evaluate_exit(pos(), *legs(1.60, 1.70, 0.40, 0.46), 684.0, MIDDAY, CFG)
    assert e is not None and e.reason == "stop_loss"


def test_short_strike_touch() -> None:
    e = evaluate_exit(pos(), *legs(1.00, 1.10, 0.35, 0.39), 679.5, MIDDAY, CFG)
    assert e is not None and e.reason == "strike_touch"
    assert short_strike_touched(pos(side="call", short_strike=700, long_strike=705), 700.0)


def test_hold_when_nothing_triggers() -> None:
    assert evaluate_exit(pos(), *legs(0.50, 0.54, 0.12, 0.16), 688.0, MIDDAY, CFG) is None


def test_max_hold_closes_a_spread_held_too_long() -> None:
    late = datetime(2026, 10, 7, 18, 31, tzinfo=UTC)  # 14:31 EDT, 151 min after the 12:00 entry
    e = evaluate_exit(pos(), *legs(0.50, 0.54, 0.12, 0.16), 688.0, late, CFG)
    assert e is not None and e.reason == "max_hold" and e.close
    off = CFG.model_copy(update={"exits": CFG.exits.model_copy(update={"max_hold_minutes": None})})
    assert evaluate_exit(pos(), *legs(0.50, 0.54, 0.12, 0.16), 688.0, late, off) is None
    # A losing spread past the hold limit reports the stop, not the hold.
    stop = evaluate_exit(pos(), *legs(1.60, 1.70, 0.40, 0.46), 684.0, late, CFG)
    assert stop is not None and stop.reason == "stop_loss"


# Review Focus 2 — a leg without a usable quote.
def test_no_quote_means_no_decision_before_the_time_stop() -> None:
    assert evaluate_exit(pos(), *legs(-1.0, None, 0.0, 0.05), 688.0, MIDDAY, CFG) is None


def test_time_stop_fires_even_without_a_quote() -> None:
    e = evaluate_exit(pos(), *legs(-1.0, None, 0.0, 0.05), 688.0, CLOSE, CFG)
    assert e is not None and e.reason == "time_stop" and e.close


def test_far_otm_cheap_spread_is_left_to_expire_at_the_time_stop() -> None:
    e = evaluate_exit(pos(), *legs(0.02, 0.05, 0.0, 0.02), 690.0, CLOSE, CFG)
    assert e is not None and e.reason == "expire_worthless" and e.close is False


def test_spy_spreads_are_never_left_to_expire() -> None:
    assert _BASE.exits.let_expire is False  # SPY settles in shares
    spy = CFG.model_copy(update={"exits": CFG.exits.model_copy(update={"let_expire": False})})
    e = evaluate_exit(pos(), *legs(0.02, 0.05, 0.0, 0.02), 690.0, CLOSE, spy)
    assert e is not None and e.reason == "time_stop" and e.close


def test_cheap_but_breached_spread_is_still_closed_at_the_time_stop() -> None:
    e = evaluate_exit(pos(), *legs(0.02, 0.05, 0.0, 0.02), 679.0, CLOSE, CFG)
    assert e is not None and e.reason == "time_stop"


def test_intrinsic_debit_is_capped_at_width() -> None:
    assert intrinsic_debit(pos(), 690.0) == 0.0
    assert intrinsic_debit(pos(), 678.0) == pytest.approx(2.0)
    assert intrinsic_debit(pos(), 600.0) == 5.0
    call = pos(side="call", short_strike=700, long_strike=705)
    assert intrinsic_debit(call, 703.0) == pytest.approx(3.0)


def test_reconcile_agrees_with_a_matching_broker_book() -> None:
    assert reconcile([pos(contracts=2)], {111: -2.0, 222: 2.0}) == []


def test_reconcile_reports_missing_and_unexpected_legs() -> None:
    problems = reconcile([pos()], {111: -1.0, 333: 1.0})
    assert any("222" in p for p in problems) and any("333" in p for p in problems)


def test_reconcile_ignores_shadow_positions() -> None:
    assert reconcile([pos(mode="shadow")], {}) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_manager.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.manager'`.

- [ ] **Step 3: Implement `src/spreads/manager.py`**

```python
"""Exit rules for open spreads, settlement math, and broker reconciliation. Pure.

Exit order: the time stop dominates once ``force_close`` is reached (it must fire even with no
quote); before it, nothing is decided without a usable mid. Then stop-loss, profit-take, a
short-strike touch, and the maximum hold time (OPG is usually out within two hours; same-day
options get riskier into the close). At the time stop every spread is closed, because SPY settles
in shares (``exits.let_expire: false``). Only with ``let_expire: true`` — a cash-settled XSP/SPX
book — is a far-OTM spread costing no more than ``let_expire_max_debit`` left to expire instead.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from src.common.config import SpreadsCfg
from src.common.schemas import ChainOption, SpreadExit, SpreadPosition
from src.spreads.pricing import ET


def debit_to_close(
    short_q: ChainOption | None, long_q: ChainOption | None
) -> tuple[float | None, float | None]:
    """(mid debit, natural debit = short ask − long bid) per share; None where unquoted."""
    mid: float | None = None
    nat: float | None = None
    if short_q is not None and long_q is not None:
        if short_q.mid is not None and long_q.mid is not None:
            mid = round(short_q.mid - long_q.mid, 4)
        if short_q.ask is not None and long_q.bid is not None and long_q.bid >= 0:
            nat = round(short_q.ask - long_q.bid, 4)
    return mid, nat


def short_strike_touched(pos: SpreadPosition, spot: float | None) -> bool:
    if spot is None:
        return False
    return spot <= pos.short_strike if pos.side == "put" else spot >= pos.short_strike


def evaluate_exit(
    pos: SpreadPosition,
    short_q: ChainOption | None,
    long_q: ChainOption | None,
    spot: float | None,
    now: datetime,
    cfg: SpreadsCfg,
) -> SpreadExit | None:
    x = cfg.exits
    mid, _ = debit_to_close(short_q, long_q)
    touched = short_strike_touched(pos, spot)
    if now.astimezone(ET).strftime("%H:%M") >= cfg.schedule.force_close:
        if x.let_expire and mid is not None and mid <= x.let_expire_max_debit and spot is not None and not touched:
            return SpreadExit(spread_id=pos.spread_id, reason="expire_worthless", close=False)
        return SpreadExit(spread_id=pos.spread_id, reason="time_stop", close=True)
    if mid is None:
        return None
    if mid >= pos.entry_credit * x.stop_debit_multiple:
        return SpreadExit(spread_id=pos.spread_id, reason="stop_loss", close=True)
    if mid <= pos.entry_credit * (1 - x.profit_take_pct / 100.0):
        return SpreadExit(spread_id=pos.spread_id, reason="profit_take", close=True)
    if x.close_on_short_strike_touch and touched:
        return SpreadExit(spread_id=pos.spread_id, reason="strike_touch", close=True)
    if x.max_hold_minutes is not None and now - pos.opened_at >= timedelta(minutes=x.max_hold_minutes):
        return SpreadExit(spread_id=pos.spread_id, reason="max_hold", close=True)
    return None


def intrinsic_debit(pos: SpreadPosition, spot: float) -> float:
    """Settlement value per share of a short vertical at *spot*, in [0, width]."""
    if pos.side == "put":
        raw = pos.short_strike - spot
    else:
        raw = spot - pos.short_strike
    return max(0.0, min(pos.width, raw))


def reconcile(expected: list[SpreadPosition], broker_legs: dict[int, float]) -> list[str]:
    """Compare open *paper* spreads with the broker's spreads-book option legs (conId → qty).

    Empty list = consistent. Shadow positions never reach the broker and are ignored.
    """
    want: dict[int, float] = defaultdict(float)
    problems: list[str] = []
    for p in expected:
        if p.mode != "paper":
            continue
        if p.short_con_id is None or p.long_con_id is None:
            problems.append(f"{p.spread_id}: missing leg conIds")
            continue
        want[p.short_con_id] -= p.contracts
        want[p.long_con_id] += p.contracts
    for con_id in sorted(set(want) | set(broker_legs)):
        w, h = want.get(con_id, 0.0), broker_legs.get(con_id, 0.0)
        if abs(w - h) > 1e-9:
            problems.append(f"conId {con_id}: expected {w:+g}, broker holds {h:+g}")
    return problems
```

- [ ] **Step 4: Run the tests and the gate**

Run: `python -m pytest tests/test_spreads_manager.py -q && ruff check . && mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff format src/spreads/manager.py tests/test_spreads_manager.py
git add src/spreads/manager.py tests/test_spreads_manager.py
git commit -m "feat(spreads): exit rules, settlement value, broker reconciliation"
```

---
### Task 9: The spreads database (`data/spreads.db`)

**Files:**
- Create: `src/spreads/store.py`, `tests/test_spreads_store.py`

**Interfaces:**
- Consumes: `GexLevels`, `SpreadCandidate`, `SpreadVerdict`, `SpreadPosition`, `SpreadEntryContext`, `SpreadTradeRecord` (Task 4); `Config.spreads_db_url_abs()` (Task 1); `pricing.ET`.
- Produces:
  - Base and engine: `SpreadsBase`, `get_spreads_engine()`, `init_spreads_db()`, `spreads_session()` (a context manager)
  - Tables: `GexMapRow`, `SpreadCandidateRow`, `SpreadPositionRow` (with the entry tags and the worst mark seen), `SpreadOrderRow`
  - Writers:
    - `record_map(levels) -> None`
    - `record_candidate(c, verdict, regime, now) -> None`
    - `record_order(*, spread_id, kind, order_ref, ib_order_id, perm_id, filled_qty, price, commission, reason, now) -> None`
    - `open_position(c, *, mode, contracts, credit, commission, now, perm_id, context=None) -> SpreadPosition`, where `context: SpreadEntryContext | None` is stored as the position's tags
    - `note_mark(spread_id, mid_debit) -> None`, which keeps the worst (highest) debit-to-close seen while open
    - `mark_expiring(spread_id) -> None`
    - `close_position(spread_id, *, contracts, debit, commission, reason, now) -> float`, which returns the realized USD of this close
  - Readers:
    - `open_positions(mode) -> list[SpreadPosition]`
    - `expiring_positions(mode) -> list[SpreadPosition]`
    - `day_stats(day, mode) -> tuple[int, float]`, returning (trades opened that ET day, realized USD on them)
    - `sides_opened(day, mode) -> list[str]`, the sides opened that ET day, oldest first (the one-side-per-day input)
    - `first_map_em(day) -> float | None`, the expected move of the day's first map that had one (the trigger's yardstick after a restart)
    - `realized_pnl_total(mode) -> float`, all realized P&L the book has booked in *mode* (capital = `starting_capital_usd` + this)
    - `open_risk_usd(mode) -> float`
    - `trade_log(mode) -> list[SpreadTradeRecord]`, every spread opened in *mode* (open or closed), oldest first, with its tags, holding time and MAE
    - `closed_results(mode) -> list[tuple[str, str, float]]`, returning (regime at entry, exit_reason, realized USD) per closed spread, in close order

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_store.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.schemas import GexLevels, SpreadCandidate, SpreadEntryContext, SpreadVerdict

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)
LATER = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import src.spreads.store as st

    monkeypatch.setattr(st, "_engine", None)
    monkeypatch.setattr(st, "_SessionLocal", None)
    monkeypatch.setattr(st, "_resolve_url", lambda: f"sqlite:///{tmp_path / 'spreads.db'}")
    st.init_spreads_db()
    return st


def cand(spread_id: str = "s1") -> SpreadCandidate:
    return SpreadCandidate(
        spread_id=spread_id,
        side="put",
        expiry=date(2026, 10, 7),
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        short_con_id=111,
        long_con_id=222,
        credit_mid=0.61,
        credit_natural=0.56,
        short_delta=-0.12,
        spot=690.0,
        quote_time=NOW,
    )


def test_open_position_round_trips_and_counts_risk(store) -> None:
    pos = store.open_position(
        cand(), mode="shadow", contracts=1, credit=0.57, commission=1.30, now=NOW, perm_id=None
    )
    assert pos.entry_credit == 0.57 and pos.contracts == 1 and pos.short_con_id == 111
    assert [p.spread_id for p in store.open_positions("shadow")] == ["s1"]
    assert store.open_positions("paper") == []
    assert store.open_risk_usd("shadow") == pytest.approx((5.0 - 0.57) * 100)


# Review Focus 3 — partial closes pro-rate the entry commission and keep the rest open.
def test_partial_close_then_final_close(store) -> None:
    store.open_position(
        cand(), mode="paper", contracts=2, credit=0.60, commission=2.60, now=NOW, perm_id=9
    )
    first = store.close_position(
        "s1", contracts=1, debit=0.30, commission=1.30, reason="profit_take", now=LATER
    )
    assert first == pytest.approx(30.0 - 1.30 - 1.30)
    (still,) = store.open_positions("paper")
    assert still.contracts == 1
    second = store.close_position(
        "s1", contracts=1, debit=0.50, commission=1.30, reason="profit_take", now=LATER
    )
    assert second == pytest.approx(10.0 - 1.30 - 1.30)
    assert store.open_positions("paper") == []
    ((regime, reason, pnl),) = store.closed_results("paper")
    assert reason == "profit_take" and pnl == pytest.approx(34.8)
    with store.spreads_session() as s:
        row = s.query(store.SpreadPositionRow).one()
        assert row.exit_debit == pytest.approx(0.40) and row.status == "closed"


def test_day_stats_counts_trades_opened_that_et_day(store) -> None:
    store.open_position(cand("a"), mode="shadow", contracts=1, credit=0.6, commission=1.3, now=NOW, perm_id=None)
    store.open_position(cand("b"), mode="shadow", contracts=1, credit=0.6, commission=1.3, now=NOW, perm_id=None)
    store.close_position("a", contracts=1, debit=1.2, commission=1.3, reason="stop_loss", now=LATER)
    trades, realized = store.day_stats(date(2026, 10, 7), "shadow")
    assert trades == 2
    assert realized == pytest.approx(-60.0 - 1.3 - 1.3)
    assert store.day_stats(date(2026, 10, 8), "shadow") == (0, 0.0)
    assert store.sides_opened(date(2026, 10, 7), "shadow") == ["put", "put"]
    assert store.sides_opened(date(2026, 10, 8), "shadow") == []
    # The book's capital grows and shrinks with everything it has realized, per mode.
    assert store.realized_pnl_total("shadow") == pytest.approx(-60.0 - 1.3 - 1.3)
    assert store.realized_pnl_total("paper") == 0.0


def test_every_trade_is_logged_with_its_tags_hold_time_and_mae(store) -> None:
    tags = SpreadEntryContext(
        trigger="move", move_em=0.7, gap_pct=-0.004, gap_day=True, regime="negative",
        net_gex=-2e9, flip=700.0, expected_move=5.8, day_em=6.0, spot=690.0, minutes_after_open=12,
    )
    store.open_position(cand(), mode="shadow", contracts=2, credit=0.60, commission=2.6, now=NOW, perm_id=None, context=tags)
    store.note_mark("s1", 0.90)
    store.note_mark("s1", 0.70)  # a better mark never lowers the worst one
    store.close_position("s1", contracts=2, debit=0.30, commission=2.6, reason="profit_take", now=LATER)
    (t,) = store.trade_log("shadow")
    assert (t.side, t.status, t.regime, t.trigger, t.gap_day, t.minutes_after_open) == (
        "put", "closed", "negative", "move", True, 12,
    )
    assert t.move_em == pytest.approx(0.7) and t.gap_pct == pytest.approx(-0.004)
    assert t.hold_minutes == pytest.approx(90.0)
    assert t.mae_usd == pytest.approx((0.90 - 0.60) * 100 * 2)
    assert t.pnl_usd == pytest.approx((0.60 - 0.30) * 100 * 2 - 2.6 - 2.6)
    assert store.closed_results("shadow") == [("negative", "profit_take", pytest.approx(t.pnl_usd))]
    with store.spreads_session() as s:
        assert s.query(store.SpreadPositionRow).one().entry_context["net_gex"] == -2e9


def test_an_open_untagged_trade_is_logged_too(store) -> None:
    store.open_position(cand(), mode="paper", contracts=1, credit=0.6, commission=1.3, now=NOW, perm_id=7)
    (t,) = store.trade_log("paper")
    assert (t.status, t.regime, t.trigger) == ("open", "unknown", "always")
    assert t.hold_minutes is None and t.mae_usd is None and t.closed_at is None
    assert store.trade_log("shadow") == []


def test_first_map_em_is_the_days_yardstick(store) -> None:
    def lv(at: datetime, em: float | None) -> GexLevels:
        return GexLevels(as_of=at, spot=690.0, net_gex=1e9, regime="positive", expected_move=em)

    store.record_map(lv(NOW, None))
    store.record_map(lv(LATER, 5.8))
    store.record_map(lv(LATER + timedelta(hours=1), 4.0))
    assert store.first_map_em(date(2026, 10, 7)) == pytest.approx(5.8)
    assert store.first_map_em(date(2026, 10, 8)) is None


def test_expiring_positions_are_tracked_separately(store) -> None:
    store.open_position(cand(), mode="shadow", contracts=1, credit=0.6, commission=1.3, now=NOW, perm_id=None)
    store.mark_expiring("s1")
    assert store.open_positions("shadow") == []
    assert [p.spread_id for p in store.expiring_positions("shadow")] == ["s1"]
    assert store.open_risk_usd("shadow") == pytest.approx(440.0)


def test_maps_candidates_and_orders_are_recorded(store) -> None:
    store.record_map(
        GexLevels(as_of=NOW, spot=690.0, net_gex=1e9, regime="positive", flip=675.0, expected_move=5.8)
    )
    store.record_candidate(
        cand(), SpreadVerdict(spread_id="s1", approved=False, reasons=["negative_gamma"]), "negative", NOW
    )
    store.record_order(
        spread_id="s1", kind="open", order_ref="CS:s1", ib_order_id=7, perm_id=9001,
        filled_qty=0, price=None, commission=0.0, reason="not_filled", now=NOW,
    )
    with store.spreads_session() as s:
        assert s.query(store.GexMapRow).count() == 1
        assert s.query(store.SpreadCandidateRow).one().reasons == ["negative_gamma"]
        assert s.query(store.SpreadOrderRow).one().perm_id == 9001


def test_spreads_tables_never_share_the_trading_base() -> None:
    from src.spreads.store import SpreadsBase
    from src.storage.models import Base

    assert not set(SpreadsBase.metadata.tables) & set(Base.metadata.tables)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.store'`.

- [ ] **Step 3: Implement `src/spreads/store.py`**

```python
"""The spreads system's own SQLite database (``data/spreads.db``).

A separate engine and a separate DeclarativeBase from the trading DB, so ``create_all`` can
never build a spreads table in ``income_system.db`` or a wheel table here (the
``src/research/store`` pattern). Timestamps are stored naive-UTC, like the trading DB.
Commissions are positive costs. ``mode`` keeps shadow and paper books apart.

Every spread is a trade-log row: ``spread_positions`` carries the entry tags
(``SpreadEntryContext``: trigger, move size, gap, gamma regime and levels, minutes after the
open) and the worst mark seen while open, so ``trade_log`` can answer "how did negative-gamma
trades / gap days / call spreads do?" without joining anything.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.common.config import get_config
from src.common.schemas import (
    GexLevels,
    SpreadCandidate,
    SpreadEntryContext,
    SpreadPosition,
    SpreadTradeRecord,
    SpreadVerdict,
)
from src.spreads.pricing import ET


class SpreadsBase(DeclarativeBase):
    pass


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


class GexMapRow(SpreadsBase):
    __tablename__ = "gex_maps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_date: Mapped[date] = mapped_column(Date, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime)
    spot: Mapped[float] = mapped_column(Float)
    net_gex: Mapped[float] = mapped_column(Float)
    regime: Mapped[str] = mapped_column(String(10))
    flip: Mapped[float | None] = mapped_column(Float, nullable=True)
    call_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    put_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_move: Mapped[float | None] = mapped_column(Float, nullable=True)


class SpreadCandidateRow(SpreadsBase):
    __tablename__ = "spread_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spread_id: Mapped[str] = mapped_column(String(48), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    side: Mapped[str] = mapped_column(String(4))
    expiry: Mapped[date] = mapped_column(Date)
    short_strike: Mapped[float] = mapped_column(Float)
    long_strike: Mapped[float] = mapped_column(Float)
    credit_mid: Mapped[float] = mapped_column(Float)
    credit_natural: Mapped[float] = mapped_column(Float)
    short_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime: Mapped[str] = mapped_column(String(10))
    approved: Mapped[bool] = mapped_column(Boolean)
    contracts: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[list] = mapped_column(JSON, default=list)


class SpreadPositionRow(SpreadsBase):
    __tablename__ = "spread_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spread_id: Mapped[str] = mapped_column(String(48), unique=True)
    mode: Mapped[str] = mapped_column(String(6), index=True)
    side: Mapped[str] = mapped_column(String(4))
    expiry: Mapped[date] = mapped_column(Date)
    short_strike: Mapped[float] = mapped_column(Float)
    long_strike: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    contracts_opened: Mapped[int] = mapped_column(Integer)
    contracts: Mapped[int] = mapped_column(Integer)  # still open
    short_con_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    long_con_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_credit: Mapped[float] = mapped_column(Float)
    entry_commission: Mapped[float] = mapped_column(Float)
    open_perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open|expiring|closed
    exit_debit: Mapped[float | None] = mapped_column(Float, nullable=True)  # qty-weighted
    exit_commission: Mapped[float] = mapped_column(Float, default=0.0)
    exit_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    realized_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # Entry tags (SpreadEntryContext) — the trade log's analysis columns.
    regime: Mapped[str] = mapped_column(String(10), default="unknown")
    trigger: Mapped[str] = mapped_column(String(8), default="always")
    move_em: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap_day: Mapped[bool] = mapped_column(Boolean, default=False)
    minutes_after_open: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # the full context
    # Worst (highest) mid debit-to-close seen while open; MAE = (this − entry_credit) × 100 × qty.
    max_debit_seen: Mapped[float | None] = mapped_column(Float, nullable=True)


class SpreadOrderRow(SpreadsBase):
    __tablename__ = "spread_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spread_id: Mapped[str] = mapped_column(String(48), index=True)
    kind: Mapped[str] = mapped_column(String(5))  # open|close
    order_ref: Mapped[str] = mapped_column(String(64))
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filled_qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission: Mapped[float] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_url() -> str:
    """Absolute sqlite URL for the spreads database. Patched in tests."""
    return get_config().spreads_db_url_abs()


def get_spreads_engine() -> Engine:
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


def init_spreads_db() -> None:
    SpreadsBase.metadata.create_all(get_spreads_engine())


@contextmanager
def spreads_session() -> Iterator[Session]:
    get_spreads_engine()
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


def _to_schema(r: SpreadPositionRow) -> SpreadPosition:
    return SpreadPosition(
        spread_id=r.spread_id,
        mode=r.mode,  # type: ignore[arg-type]
        side=r.side,  # type: ignore[arg-type]
        expiry=r.expiry,
        short_strike=r.short_strike,
        long_strike=r.long_strike,
        width=r.width,
        contracts=r.contracts,
        entry_credit=r.entry_credit,
        opened_at=r.opened_at.replace(tzinfo=UTC),
        short_con_id=r.short_con_id,
        long_con_id=r.long_con_id,
    )


def record_map(levels: GexLevels) -> None:
    with spreads_session() as s:
        s.add(
            GexMapRow(
                session_date=levels.as_of.astimezone(ET).date(),
                as_of=_naive(levels.as_of),
                spot=levels.spot,
                net_gex=levels.net_gex,
                regime=levels.regime,
                flip=levels.flip,
                call_wall=levels.call_wall,
                put_wall=levels.put_wall,
                expected_move=levels.expected_move,
            )
        )


def record_candidate(c: SpreadCandidate, verdict: SpreadVerdict, regime: str, now: datetime) -> None:
    with spreads_session() as s:
        s.add(
            SpreadCandidateRow(
                spread_id=c.spread_id,
                created_at=_naive(now),
                side=c.side,
                expiry=c.expiry,
                short_strike=c.short_strike,
                long_strike=c.long_strike,
                credit_mid=c.credit_mid,
                credit_natural=c.credit_natural,
                short_delta=c.short_delta,
                regime=regime,
                approved=verdict.approved,
                contracts=verdict.contracts,
                reasons=list(verdict.reasons),
            )
        )


def record_order(
    *,
    spread_id: str,
    kind: str,
    order_ref: str,
    ib_order_id: int | None,
    perm_id: int | None,
    filled_qty: int,
    price: float | None,
    commission: float,
    reason: str | None,
    now: datetime,
) -> None:
    with spreads_session() as s:
        s.add(
            SpreadOrderRow(
                spread_id=spread_id,
                kind=kind,
                order_ref=order_ref,
                ib_order_id=ib_order_id,
                perm_id=perm_id,
                filled_qty=filled_qty,
                price=price,
                commission=commission,
                reason=reason[:200] if reason else None,
                created_at=_naive(now),
            )
        )


def open_position(
    c: SpreadCandidate,
    *,
    mode: str,
    contracts: int,
    credit: float,
    commission: float,
    now: datetime,
    perm_id: int | None,
    context: SpreadEntryContext | None = None,
) -> SpreadPosition:
    tags: dict = {}
    if context is not None:
        tags = {
            "regime": context.regime,
            "trigger": context.trigger,
            "move_em": context.move_em,
            "gap_pct": context.gap_pct,
            "gap_day": context.gap_day,
            "minutes_after_open": context.minutes_after_open,
            "entry_context": context.model_dump(mode="json"),
        }
    row = SpreadPositionRow(
        **tags,
        spread_id=c.spread_id,
        mode=mode,
        side=c.side,
        expiry=c.expiry,
        short_strike=c.short_strike,
        long_strike=c.long_strike,
        width=c.width,
        contracts_opened=contracts,
        contracts=contracts,
        short_con_id=c.short_con_id,
        long_con_id=c.long_con_id,
        entry_credit=credit,
        entry_commission=commission,
        open_perm_id=perm_id,
        opened_at=_naive(now),
        status="open",
        exit_commission=0.0,
        realized_pnl_usd=0.0,
    )
    with spreads_session() as s:
        s.add(row)
        s.flush()
        return _to_schema(row)


def _positions(mode: str, status: str) -> list[SpreadPosition]:
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.mode == mode, SpreadPositionRow.status == status)
            .order_by(SpreadPositionRow.id)
            .all()
        )
        return [_to_schema(r) for r in rows]


def open_positions(mode: str) -> list[SpreadPosition]:
    return _positions(mode, "open")


def expiring_positions(mode: str) -> list[SpreadPosition]:
    return _positions(mode, "expiring")


def mark_expiring(spread_id: str) -> None:
    with spreads_session() as s:
        row = s.query(SpreadPositionRow).filter_by(spread_id=spread_id).one()
        row.status = "expiring"


def close_position(
    spread_id: str,
    *,
    contracts: int,
    debit: float,
    commission: float,
    reason: str,
    now: datetime,
) -> float:
    """Close up to *contracts*; returns this close's realized USD (entry commission pro-rated)."""
    with spreads_session() as s:
        row = s.query(SpreadPositionRow).filter_by(spread_id=spread_id).one()
        q = max(0, min(contracts, row.contracts))
        if q == 0:
            return 0.0
        entry_share = row.entry_commission * q / row.contracts_opened
        realized = (row.entry_credit - debit) * 100.0 * q - entry_share - commission
        already = row.contracts_opened - row.contracts
        row.exit_debit = (
            debit if already == 0 or row.exit_debit is None
            else (row.exit_debit * already + debit * q) / (already + q)
        )
        row.exit_commission = (row.exit_commission or 0.0) + commission
        row.realized_pnl_usd = (row.realized_pnl_usd or 0.0) + realized
        row.contracts -= q
        if row.contracts == 0:
            row.status = "closed"
            row.exit_reason = reason
            row.closed_at = _naive(now)
        return realized


def day_stats(day: date, mode: str) -> tuple[int, float]:
    """(spreads opened on ET *day*, realized USD booked on them so far)."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=ET) - timedelta(hours=1)
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.mode == mode, SpreadPositionRow.opened_at >= _naive(start))
            .all()
        )
        today = [r for r in rows if r.opened_at.replace(tzinfo=UTC).astimezone(ET).date() == day]
        return len(today), float(sum(r.realized_pnl_usd or 0.0 for r in today))


def open_risk_usd(mode: str) -> float:
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(
                SpreadPositionRow.mode == mode,
                SpreadPositionRow.status.in_(("open", "expiring")),
            )
            .all()
        )
        return float(sum((r.width - r.entry_credit) * 100.0 * r.contracts for r in rows))


def note_mark(spread_id: str, mid_debit: float) -> None:
    """Keep the worst (highest) debit-to-close seen while the spread is open — its MAE."""
    with spreads_session() as s:
        row = s.query(SpreadPositionRow).filter_by(spread_id=spread_id).one()
        if row.max_debit_seen is None or mid_debit > row.max_debit_seen:
            row.max_debit_seen = mid_debit


def sides_opened(day: date, mode: str) -> list[str]:
    """Sides of the spreads opened on ET *day*, oldest first (the one-side-per-day input)."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=ET) - timedelta(hours=1)
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.mode == mode, SpreadPositionRow.opened_at >= _naive(start))
            .order_by(SpreadPositionRow.opened_at, SpreadPositionRow.id)
            .all()
        )
        return [r.side for r in rows if r.opened_at.replace(tzinfo=UTC).astimezone(ET).date() == day]


def realized_pnl_total(mode: str) -> float:
    """Every dollar the book has realized in *mode* — the sizing capital is starting capital + this."""
    with spreads_session() as s:
        rows = s.query(SpreadPositionRow).filter(SpreadPositionRow.mode == mode).all()
        return float(sum(r.realized_pnl_usd or 0.0 for r in rows))


def first_map_em(day: date) -> float | None:
    """The expected move of *day*'s first map that had one — the trigger's yardstick."""
    with spreads_session() as s:
        row = (
            s.query(GexMapRow)
            .filter(GexMapRow.session_date == day, GexMapRow.expected_move.is_not(None))
            .order_by(GexMapRow.as_of, GexMapRow.id)
            .first()
        )
        return row.expected_move if row is not None else None


def _record(r: SpreadPositionRow) -> SpreadTradeRecord:
    opened = r.opened_at.replace(tzinfo=UTC)
    closed = r.closed_at.replace(tzinfo=UTC) if r.closed_at is not None else None
    mae = None
    if r.max_debit_seen is not None:
        mae = max(0.0, (r.max_debit_seen - r.entry_credit) * 100.0 * r.contracts_opened)
    return SpreadTradeRecord(
        spread_id=r.spread_id,
        mode=r.mode,  # type: ignore[arg-type]
        side=r.side,  # type: ignore[arg-type]
        status=r.status,
        opened_at=opened,
        closed_at=closed,
        short_strike=r.short_strike,
        long_strike=r.long_strike,
        width=r.width,
        contracts=r.contracts_opened,
        entry_credit=r.entry_credit,
        exit_debit=r.exit_debit,
        exit_reason=r.exit_reason,
        pnl_usd=r.realized_pnl_usd or 0.0,
        regime=r.regime or "unknown",
        trigger=r.trigger or "always",
        move_em=r.move_em,
        gap_pct=r.gap_pct,
        gap_day=bool(r.gap_day),
        minutes_after_open=r.minutes_after_open,
        hold_minutes=(closed - opened).total_seconds() / 60.0 if closed is not None else None,
        mae_usd=mae,
    )


def trade_log(mode: str) -> list[SpreadTradeRecord]:
    """Every spread opened in *mode*, oldest first, open or closed, with its tags and outcome."""
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.mode == mode)
            .order_by(SpreadPositionRow.opened_at, SpreadPositionRow.id)
            .all()
        )
        return [_record(r) for r in rows]


def closed_results(mode: str) -> list[tuple[str, str, float]]:
    """(regime at entry, exit reason, realized USD) for every closed spread in *mode*, in close order."""
    closed = [t for t in trade_log(mode) if t.status == "closed" and t.closed_at is not None]
    closed.sort(key=lambda t: t.closed_at or t.opened_at)
    return [(t.regime, t.exit_reason or "", t.pnl_usd) for t in closed]
```

- [ ] **Step 4: Run the tests and the gate**

Run: `python -m pytest tests/test_spreads_store.py -q && ruff check . && mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff format src/spreads/store.py tests/test_spreads_store.py
git add src/spreads/store.py tests/test_spreads_store.py
git commit -m "feat(spreads): separate spreads.db — maps, candidates, positions, orders"
```

---

### Task 10: IBKR I/O — line-budgeted chains, quotes, spot, account, broker legs

**Files:**
- Create: `src/spreads/chain.py`, `tests/test_spreads_chain.py`

**Interfaces:**
- Consumes:
  - `req_fresh_mkt_data` (`src.ibkr.market_data`)
  - `qualify_options_async` (`src.ibkr.contracts`)
  - `is_spreads_underlying` (Task 1)
  - `ChainOption`, `ChainSnapshot`, `SessionSnapshot` (Task 4)
  - `pricing.ET`
  - `SpreadsCfg`
- Produces:
  - `to_chain_option(contract, ticker) -> ChainOption`
  - `band_strikes(strikes, spot, band_pct) -> list[float]`
  - `next_expiries(expirations, today, n) -> list[str]`
  - `pick_chain(chains, trading_class) -> Any | None`
  - `parity_spot(options, guess) -> float | None`
  - `class IbkrSpreadsBroker(ib, cfg, account, *, quote_wait_seconds=3.0, now=...)`, with:
    - `async index_spot(symbol, exchange, sec_type="IND") -> float | None` (a `Stock` contract when `sec_type="STK"`, as for SPY)
    - `async spot() -> float | None` (the traded underlying, `cfg.underlying_sec_type`)
    - `async session_quote() -> SessionSnapshot | None` (the traded index's last price plus IBKR's open, high, low and prior close; one line, cancelled before returning)
    - `async fetch_chain(*, symbol, trading_class, exchange, expiries, band_pct, spot_hint=None, sec_type="IND") -> ChainSnapshot | None`
    - `async quote(contracts) -> list[ChainOption]`
    - `async requote(legs: list[ChainOption]) -> list[ChainOption]`
    - `async excess_liquidity() -> float | None`
    - `broker_legs() -> dict[int, float]`

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_chain.py`:

```python
from __future__ import annotations

import itertools
import math
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption
from src.spreads.chain import (
    IbkrSpreadsBroker,
    band_strikes,
    next_expiries,
    parity_spot,
    pick_chain,
    to_chain_option,
)

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)
TODAY = date(2026, 10, 7)
CFG = get_config().spreads.model_copy(update={"max_market_data_lines": 30})


def _contract(strike: float, right: str, con_id: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        strike=strike, right=right, lastTradeDateOrContractMonth="20261007", conId=con_id
    )


# Review Focus 2 — IBKR's -1 bid sentinel and NaN asks become None, never a price.
def test_to_chain_option_cleans_sentinels_and_reads_put_oi() -> None:
    ticker = SimpleNamespace(
        bid=-1.0,
        ask=math.nan,
        modelGreeks=SimpleNamespace(impliedVol=0.21, delta=-0.08),
        callOpenInterest=10,
        putOpenInterest=750,
    )
    o = to_chain_option(_contract(680, "P"), ticker)
    assert o.bid is None and o.ask is None and o.mid is None
    assert (o.iv, o.delta, o.open_interest, o.con_id) == (0.21, -0.08, 750, 5)
    assert o.expiry == TODAY and o.right == "P"


def test_to_chain_option_without_greeks() -> None:
    ticker = SimpleNamespace(bid=0.5, ask=0.6, modelGreeks=None, callOpenInterest=math.nan, putOpenInterest=None)
    o = to_chain_option(_contract(700, "C"), ticker)
    assert o.iv is None and o.delta is None and o.open_interest is None and o.mid == pytest.approx(0.55)


def test_chain_helpers() -> None:
    assert band_strikes([660.0, 669.0, 670.0, 690.0, 710.0, 711.0], 690.0, 0.03) == [670.0, 690.0, 710.0]
    assert next_expiries(["20261006", "20261009", "20261007", "20261008"], TODAY, 2) == ["20261007", "20261008"]
    chains = [
        SimpleNamespace(exchange="CBOE", tradingClass="SPX", expirations=["20261016"], strikes=[1.0]),
        SimpleNamespace(exchange="SMART", tradingClass="SPXW", expirations=["20261007"], strikes=[1.0]),
    ]
    assert pick_chain(chains, "SPXW").tradingClass == "SPXW"
    assert pick_chain(chains, "XSP") is None


def test_parity_spot_uses_the_nearest_fully_quoted_strike() -> None:
    opts = [
        ChainOption(strike=690, right="C", expiry=TODAY, bid=3.0, ask=3.2),
        ChainOption(strike=690, right="P", expiry=TODAY, bid=2.4, ask=2.6),
    ]
    assert parity_spot(opts, 689.0) == pytest.approx(690 + 3.1 - 2.5)
    assert parity_spot([], 689.0) is None


class FakeIB:
    """Records how many market-data lines are open at once."""

    def __init__(self, spot: float | None = 690.0) -> None:
        self.spot = spot
        self.session = {"open": math.nan, "high": math.nan, "low": math.nan, "close": math.nan}
        self.open = 0
        self.max_open = 0
        self._ids = itertools.count(1000)
        self.positions_list: list[SimpleNamespace] = []
        self.values: list[SimpleNamespace] = []
        self.priced: list[tuple[str, str]] = []  # (secType, symbol) of every spot/session request
        self.secdef: list[tuple] = []

    def reqMktData(self, contract, *args, **kwargs):
        self.open += 1
        self.max_open = max(self.max_open, self.open)
        if contract.secType in ("IND", "STK"):
            self.priced.append((contract.secType, contract.symbol))
            return SimpleNamespace(last=self.spot if self.spot else math.nan, **self.session)
        return SimpleNamespace(
            bid=0.40,
            ask=0.45,
            modelGreeks=SimpleNamespace(impliedVol=0.18, delta=-0.1 if contract.right == "P" else 0.1),
            callOpenInterest=500,
            putOpenInterest=700,
        )

    def cancelMktData(self, contract) -> None:
        self.open -= 1

    async def qualifyContractsAsync(self, *contracts):
        for c in contracts:
            if not c.conId:
                c.conId = next(self._ids)
        return list(contracts)

    async def reqSecDefOptParamsAsync(self, *args):
        self.secdef.append(args)
        return [
            SimpleNamespace(
                exchange="SMART",
                tradingClass=tc,
                expirations=["20261007", "20261008"],
                strikes=[float(k) for k in range(650, 731)],
            )
            for tc in ("XSP", "SPY")
        ]

    def positions(self):
        return self.positions_list

    def accountValues(self, account: str = ""):
        return self.values


def _broker(ib: FakeIB) -> IbkrSpreadsBroker:
    return IbkrSpreadsBroker(ib, CFG, "DU1", quote_wait_seconds=0.05, now=lambda: NOW)


async def test_fetch_chain_bands_strikes_and_never_exceeds_the_line_budget() -> None:
    ib = FakeIB()
    snap = await _broker(ib).fetch_chain(
        symbol="XSP", trading_class="XSP", exchange="CBOE", expiries=1, band_pct=0.03
    )
    assert snap is not None and snap.spot == 690.0
    assert {o.expiry for o in snap.options} == {TODAY}
    assert min(o.strike for o in snap.options) == 670.0 and max(o.strike for o in snap.options) == 710.0
    assert len(snap.options) == 41 * 2
    assert ib.max_open <= 30
    assert ib.open == 0  # every line cancelled


async def test_fetch_chain_without_any_spot_returns_none() -> None:
    snap = await _broker(FakeIB(spot=None)).fetch_chain(
        symbol="XSP", trading_class="XSP", exchange="CBOE", expiries=1, band_pct=0.03
    )
    assert snap is None


async def test_fetch_chain_falls_back_to_the_spot_hint() -> None:
    snap = await _broker(FakeIB(spot=None)).fetch_chain(
        symbol="XSP", trading_class="XSP", exchange="CBOE", expiries=1, band_pct=0.03, spot_hint=690.0
    )
    assert snap is not None and snap.spot == 690.0


async def test_session_quote_reads_open_high_low_and_prior_close() -> None:
    ib = FakeIB()
    ib.session = {"open": 688.0, "high": 691.0, "low": 686.5, "close": 689.0}
    snap = await _broker(ib).session_quote()
    assert snap is not None and snap.as_of == NOW
    assert (snap.last, snap.open, snap.high, snap.low, snap.prior_close) == (690.0, 688.0, 691.0, 686.5, 689.0)
    assert ib.priced == [("STK", "SPY")]  # SPY is read as a stock, not an index
    assert ib.open == 0  # the line is cancelled
    assert await _broker(FakeIB(spot=None)).session_quote() is None


async def test_session_quote_without_session_stats_still_has_a_price() -> None:
    snap = await _broker(FakeIB()).session_quote()
    assert snap is not None and snap.last == 690.0
    assert (snap.open, snap.high, snap.low, snap.prior_close) == (None, None, None, None)


async def test_a_spy_chain_is_requested_as_a_stock_chain() -> None:
    ib = FakeIB()
    snap = await _broker(ib).fetch_chain(
        symbol="SPY", trading_class="SPY", exchange="SMART", expiries=1, band_pct=0.03, sec_type="STK"
    )
    assert snap is not None and snap.symbol == "SPY" and snap.spot == 690.0
    assert ib.secdef[-1][2] == "STK" and ("STK", "SPY") in ib.priced


async def test_requote_keeps_known_con_ids() -> None:
    ib = FakeIB()
    legs = [ChainOption(strike=679, right="P", expiry=TODAY, con_id=42)]
    (q,) = await _broker(ib).requote(legs)
    assert q.con_id == 42 and q.bid == 0.40


def test_broker_legs_only_count_this_accounts_spreads_options() -> None:
    ib = FakeIB()
    ib.positions_list = [
        SimpleNamespace(account="DU1", contract=SimpleNamespace(symbol="XSP", secType="OPT", conId=1), position=-1.0),
        SimpleNamespace(account="DU1", contract=SimpleNamespace(symbol="XSP", secType="OPT", conId=2), position=1.0),
        SimpleNamespace(account="DU1", contract=SimpleNamespace(symbol="UPRO", secType="OPT", conId=3), position=-1.0),
        SimpleNamespace(account="DU2", contract=SimpleNamespace(symbol="XSP", secType="OPT", conId=4), position=-1.0),
    ]
    assert _broker(ib).broker_legs() == {1: -1.0, 2: 1.0}


async def test_excess_liquidity_prefers_usd() -> None:
    ib = FakeIB()
    ib.values = [
        SimpleNamespace(account="DU1", tag="ExcessLiquidity", value="80000", currency="BASE"),
        SimpleNamespace(account="DU1", tag="ExcessLiquidity", value="60000", currency="USD"),
    ]
    assert await _broker(ib).excess_liquidity() == 60000.0
    ib.values = []
    assert await _broker(ib).excess_liquidity() is None
```

The `async def` tests run natively: `pyproject.toml` sets `asyncio_mode = "auto"`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_chain.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.chain'`.

- [ ] **Step 3: Implement `src/spreads/chain.py`**

```python
"""IBKR I/O for the spreads system — chains, quotes, spot, account, broker legs.

Every subscription goes through ``req_fresh_mkt_data`` and is cancelled before the next batch,
so at most ``max_market_data_lines`` lines are ever open from this clientId (the ~100-line cap
is shared by every clientId on the login — CLAUDE.md "Safety"). ib_async objects become
``ChainOption`` / ``ChainSnapshot`` here and nowhere else in ``src/spreads``.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Any

from ib_async import Index, Option, Stock

from src.common.books import is_spreads_underlying
from src.common.config import SpreadsCfg
from src.common.schemas import ChainOption, ChainSnapshot, SessionSnapshot
from src.ibkr.contracts import qualify_options_async
from src.ibkr.market_data import req_fresh_mkt_data
from src.spreads.pricing import ET

log = logging.getLogger(__name__)

_SENTINEL = 1e300  # IB reports "no value" as sys.float_info.max


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v) or abs(v) >= _SENTINEL:
        return None
    return v


def to_chain_option(contract: Any, ticker: Any) -> ChainOption:
    right = "C" if str(contract.right).upper().startswith("C") else "P"
    exp = str(contract.lastTradeDateOrContractMonth)[:8]
    g = getattr(ticker, "modelGreeks", None)
    bid = _num(getattr(ticker, "bid", None))
    ask = _num(getattr(ticker, "ask", None))
    oi = _num(getattr(ticker, "callOpenInterest" if right == "C" else "putOpenInterest", None))
    return ChainOption(
        strike=float(contract.strike),
        right=right,  # type: ignore[arg-type]
        expiry=date(int(exp[:4]), int(exp[4:6]), int(exp[6:8])),
        bid=bid if bid is not None and bid >= 0 else None,
        ask=ask if ask is not None and ask > 0 else None,
        iv=_num(getattr(g, "impliedVol", None)) if g is not None else None,
        delta=_num(getattr(g, "delta", None)) if g is not None else None,
        open_interest=int(oi) if oi is not None and oi >= 0 else None,
        con_id=int(getattr(contract, "conId", 0) or 0) or None,
    )


def band_strikes(strikes: Iterable[float], spot: float, band_pct: float) -> list[float]:
    return sorted(float(k) for k in strikes if abs(float(k) - spot) <= spot * band_pct)


def next_expiries(expirations: Iterable[str], today: date, n: int) -> list[str]:
    floor = today.strftime("%Y%m%d")
    return sorted(e for e in expirations if e >= floor)[: max(n, 0)]


def pick_chain(chains: Sequence[Any], trading_class: str) -> Any | None:
    matches = [c for c in chains if c.tradingClass == trading_class and c.expirations]
    if not matches:
        return None
    return max(matches, key=lambda c: (c.exchange == "SMART", len(c.expirations), len(c.strikes)))


def parity_spot(options: list[ChainOption], guess: float) -> float | None:
    """Put-call parity (r≈0 intraday): S ≈ K + C − P at the fully quoted strike nearest *guess*."""
    if not options:
        return None
    earliest = min(o.expiry for o in options)
    mids: dict[float, dict[str, float]] = {}
    for o in options:
        m = o.mid
        if o.expiry == earliest and m is not None:
            mids.setdefault(o.strike, {})[o.right] = m
    both = [k for k, v in mids.items() if "C" in v and "P" in v]
    if not both:
        return None
    k = min(both, key=lambda s: abs(s - guess))
    return k + mids[k]["C"] - mids[k]["P"]


async def _wait(predicate: Callable[[], bool], ceiling: float) -> None:
    deadline = asyncio.get_running_loop().time() + ceiling
    while not predicate() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.05)


def _all_asked(pairs: list[tuple[Any, Any]]) -> Callable[[], bool]:
    """A predicate bound to this batch (a lambda in the batch loop trips ruff B023)."""
    return lambda: all(_num(getattr(t, "ask", None)) is not None for _, t in pairs)


class IbkrSpreadsBroker:
    def __init__(
        self,
        ib: Any,
        cfg: SpreadsCfg,
        account: str,
        *,
        quote_wait_seconds: float = 3.0,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.ib = ib
        self.cfg = cfg
        self.account = account
        self.max_lines = max(1, cfg.max_market_data_lines)
        self.quote_wait = quote_wait_seconds
        self.now = now
        self._indexes: dict[str, Any] = {}

    async def _index(self, symbol: str, exchange: str, sec_type: str = "IND") -> Any:
        """The qualified underlying: an ``Index`` (SPX, XSP) or a ``Stock`` (SPY), cached."""
        if symbol not in self._indexes:
            idx = Stock(symbol, exchange, "USD") if sec_type == "STK" else Index(symbol, exchange, "USD")
            await self.ib.qualifyContractsAsync(idx)
            self._indexes[symbol] = idx
        return self._indexes[symbol]

    async def index_spot(self, symbol: str, exchange: str, sec_type: str = "IND") -> float | None:
        """Last print, else the prior close. None without the data entitlement."""
        idx = await self._index(symbol, exchange, sec_type)
        t = req_fresh_mkt_data(self.ib, idx, "", False, False)
        try:
            await _wait(
                lambda: _num(getattr(t, "last", None)) is not None
                or _num(getattr(t, "close", None)) is not None,
                self.quote_wait,
            )
            value = _num(getattr(t, "last", None))
            if value is None:
                value = _num(getattr(t, "close", None))
            return value if value is not None and value > 0 else None
        finally:
            self.ib.cancelMktData(idx)

    async def spot(self) -> float | None:
        return await self.index_spot(self.cfg.underlying, self.cfg.exchange, self.cfg.underlying_sec_type)

    async def session_quote(self) -> SessionSnapshot | None:
        """The traded index now, with IBKR's session stats (open/high/low/prior close ticks).

        The entry trigger's tape (``tape.SessionTape``) is fed from here every tick. A missing
        stat stays ``None``; the tape keeps the last known value.
        """
        idx = await self._index(self.cfg.underlying, self.cfg.exchange, self.cfg.underlying_sec_type)
        t = req_fresh_mkt_data(self.ib, idx, "", False, False)
        try:
            await _wait(
                lambda: all(_num(getattr(t, f, None)) is not None for f in ("last", "high", "low")),
                self.quote_wait,
            )
            last = _num(getattr(t, "last", None))
            if last is None or last <= 0:
                return None

            def stat(name: str) -> float | None:
                v = _num(getattr(t, name, None))
                return v if v is not None and v > 0 else None

            return SessionSnapshot(
                as_of=self.now(),
                last=last,
                open=stat("open"),
                high=stat("high"),
                low=stat("low"),
                prior_close=stat("close"),
            )
        finally:
            self.ib.cancelMktData(idx)

    async def quote(self, contracts: list[Any]) -> list[ChainOption]:
        out: list[ChainOption] = []
        for i in range(0, len(contracts), self.max_lines):
            batch = contracts[i : i + self.max_lines]
            pairs = [(c, req_fresh_mkt_data(self.ib, c, "101,106", False, False)) for c in batch]
            try:
                await _wait(_all_asked(pairs), self.quote_wait)
                out.extend(to_chain_option(c, t) for c, t in pairs)
            finally:
                for c, _ in pairs:
                    self.ib.cancelMktData(c)
        return out

    async def fetch_chain(
        self,
        *,
        symbol: str,
        trading_class: str,
        exchange: str,
        expiries: int,
        band_pct: float,
        spot_hint: float | None = None,
        sec_type: str = "IND",
    ) -> ChainSnapshot | None:
        idx = await self._index(symbol, exchange, sec_type)
        spot = await self.index_spot(symbol, exchange, sec_type)
        if spot is None:
            spot = spot_hint
        if spot is None:
            log.warning("spreads: no %s index price (index-data subscription?) and no hint", symbol)
            return None
        params = await self.ib.reqSecDefOptParamsAsync(symbol, "", sec_type, idx.conId)
        chain = pick_chain(params, trading_class)
        if chain is None:
            log.warning("spreads: no %s option chain with tradingClass %s", symbol, trading_class)
            return None
        today = self.now().astimezone(ET).date()
        exps = next_expiries(chain.expirations, today, expiries)
        strikes = band_strikes(chain.strikes, spot, band_pct)
        contracts = [
            Option(symbol, e, k, r, "SMART", tradingClass=trading_class)
            for e in exps
            for k in strikes
            for r in ("C", "P")
        ]
        qualified = await qualify_options_async(self.ib, contracts, chunk_size=self.max_lines)
        options = await self.quote(qualified)
        implied = parity_spot(options, spot)
        if implied is not None and abs(implied - spot) / spot > 0.002:
            log.warning("spreads: %s index %.2f vs parity-implied %.2f", symbol, spot, implied)
        return ChainSnapshot(symbol=symbol, spot=spot, as_of=self.now(), options=options)

    async def requote(self, legs: list[ChainOption]) -> list[ChainOption]:
        contracts = []
        for leg in legs:
            c = Option(
                self.cfg.underlying,
                f"{leg.expiry:%Y%m%d}",
                leg.strike,
                leg.right,
                "SMART",
                tradingClass=self.cfg.trading_class,
            )
            if leg.con_id:
                c.conId = leg.con_id
            contracts.append(c)
        unknown = [c for c in contracts if not c.conId]
        if unknown:
            await qualify_options_async(self.ib, unknown, chunk_size=self.max_lines)
        return await self.quote([c for c in contracts if c.conId])

    async def excess_liquidity(self) -> float | None:
        """From the account-update stream ib_async keeps (no reqAccountSummary: Error 322)."""
        by_ccy: dict[str, float] = {}
        for v in self.ib.accountValues(self.account):
            if v.tag == "ExcessLiquidity" and getattr(v, "account", self.account) == self.account:
                num = _num(v.value)
                if num is not None:
                    by_ccy[v.currency] = num
        return by_ccy.get("USD", by_ccy.get("BASE"))

    def broker_legs(self) -> dict[int, float]:
        legs: dict[int, float] = defaultdict(float)
        for p in self.ib.positions():
            c = p.contract
            if p.account == self.account and c.secType == "OPT" and is_spreads_underlying(c.symbol):
                legs[int(c.conId)] += float(p.position)
        return {k: v for k, v in legs.items() if v}
```

- [ ] **Step 4: Run the tests and the gate**

Run: `python -m pytest tests/test_spreads_chain.py -q && ruff check . && mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
ruff format src/spreads/chain.py tests/test_spreads_chain.py
git add src/spreads/chain.py tests/test_spreads_chain.py
git commit -m "feat(spreads): line-budgeted IBKR chain, quote, spot, account and position reads"
```

---

### Task 11: Combo orders and the executor (shadow + paper)

**Files:**
- Create:
  - `src/spreads/orders.py`
  - `src/spreads/executor.py`
  - `scripts/spreads_combo_check.py`
  - `tests/test_spreads_orders.py`
  - `tests/test_spreads_executor.py`

**Interfaces:**
- Consumes:
  - `SpreadCandidate`, `SpreadPosition`, `SpreadVerdict`, `ChainOption` (Task 4)
  - `refresh_candidate` (Task 6)
  - `debit_to_close` (Task 8)
  - `IbkrSpreadsBroker.requote` (Task 10)
- Produces:
  - `orders.round_tick(price, tick=0.01) -> float`
  - `orders.build_open_order(symbol, c, contracts, credit, order_ref) -> tuple[Contract, LimitOrder]`
  - `orders.build_close_order(symbol, pos, contracts, debit, order_ref) -> tuple[Contract, LimitOrder]`
  - `orders.credit_ladder(mid, natural, steps, tick, floor) -> list[float]`
  - `orders.debit_ladder(mid, steps, tick, cap) -> list[float]`
  - `executor.FillResult(filled_qty, price, commission, perm_id=None, ib_order_id=None, reason=None, order_ref="")`
  - `executor.SpreadExecutor(ib, broker, cfg, *, now=..., poll_seconds=0.25)`, with:
    - `async open(c, contracts, recheck) -> FillResult`
    - `async close(pos, short_q, long_q, *, urgent) -> FillResult`

- [ ] **Step 1: Write the failing order tests**

`tests/test_spreads_orders.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.schemas import SpreadCandidate, SpreadPosition
from src.spreads.orders import (
    build_close_order,
    build_open_order,
    credit_ladder,
    debit_ladder,
    round_tick,
)

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)


def cand(**kw) -> SpreadCandidate:
    base = dict(
        spread_id="s1", side="put", expiry=date(2026, 10, 7), short_strike=679.0, long_strike=674.0,
        width=5.0, short_con_id=111, long_con_id=222, credit_mid=0.61, credit_natural=0.56,
        spot=690.0, quote_time=NOW,
    )
    base.update(kw)
    return SpreadCandidate(**base)


def test_open_order_sells_the_short_buys_the_long_at_a_negative_limit() -> None:
    bag, order = build_open_order("XSP", cand(), 2, 0.61, "CS:s1")
    assert bag.secType == "BAG" and bag.symbol == "XSP"
    assert [(leg.conId, leg.action, leg.ratio) for leg in bag.comboLegs] == [(111, "SELL", 1), (222, "BUY", 1)]
    assert (order.action, order.totalQuantity, order.lmtPrice) == ("BUY", 2, -0.61)
    assert order.orderRef == "CS:s1" and order.tif == "DAY" and order.orderType == "LMT"


def test_close_order_reverses_the_legs_at_a_positive_limit() -> None:
    pos = SpreadPosition(
        spread_id="s1", mode="paper", side="put", expiry=date(2026, 10, 7), short_strike=679.0,
        long_strike=674.0, width=5.0, contracts=1, entry_credit=0.6, opened_at=NOW,
        short_con_id=111, long_con_id=222,
    )
    bag, order = build_close_order("XSP", pos, 1, 0.30, "CS:s1:X")
    assert [(leg.conId, leg.action) for leg in bag.comboLegs] == [(111, "BUY"), (222, "SELL")]
    assert (order.action, order.lmtPrice) == ("BUY", 0.30)


def test_orders_refuse_unqualified_legs_and_bad_prices() -> None:
    with pytest.raises(ValueError):
        build_open_order("XSP", cand(short_con_id=None), 1, 0.6, "CS:s1")
    with pytest.raises(ValueError):
        build_open_order("XSP", cand(), 0, 0.6, "CS:s1")
    with pytest.raises(ValueError):
        build_open_order("XSP", cand(), 1, 0.0, "CS:s1")


def test_ladders() -> None:
    assert round_tick(0.6049) == 0.60 and round_tick(-0.61) == -0.61
    assert credit_ladder(0.61, 0.56, 3, 0.01, 0.50) == [0.61, 0.60, 0.59]
    assert credit_ladder(0.61, 0.56, 5, 0.01, 0.60) == [0.61, 0.60]
    assert credit_ladder(0.45, 0.40, 3, 0.01, 0.50) == []
    assert debit_ladder(0.30, 3, 0.01, 0.40) == [0.30, 0.31, 0.32]
    assert debit_ladder(0.30, 3, 0.01, 0.31) == [0.30, 0.31]
```

- [ ] **Step 2: Write the failing executor tests**

`tests/test_spreads_executor.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, SpreadCandidate, SpreadPosition, SpreadVerdict
from src.spreads.executor import SpreadExecutor

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)
TODAY = date(2026, 10, 7)
_BASE = get_config().spreads
FAST = _BASE.execution.model_copy(
    update={
        "order_ttl_seconds": 0.2,
        "close_ttl_seconds": 0.2,
        "reprice_steps": 3,
        "reprice_tick": 0.01,
        "close_max_concession": 0.10,
        "shadow_slippage_per_leg": 0.02,
        "commission_per_contract": 0.65,
    }
)
SEL = _BASE.selection.model_copy(update={"width": 5.0, "min_credit_pct_of_width": 0.10})
SHADOW = _BASE.model_copy(update={"mode": "shadow", "execution": FAST, "selection": SEL})
PAPER = _BASE.model_copy(update={"mode": "paper", "execution": FAST, "selection": SEL})


def cand() -> SpreadCandidate:
    return SpreadCandidate(
        spread_id="s1", side="put", expiry=TODAY, short_strike=679.0, long_strike=674.0, width=5.0,
        short_con_id=111, long_con_id=222, credit_mid=0.61, credit_natural=0.56, short_delta=-0.12,
        short_leg_spread_pct=0.07, long_leg_spread_pct=0.18, spot=690.0, quote_time=NOW,
    )


def position(contracts: int = 1) -> SpreadPosition:
    return SpreadPosition(
        spread_id="s1", mode="paper", side="put", expiry=TODAY, short_strike=679.0, long_strike=674.0,
        width=5.0, contracts=contracts, entry_credit=0.60, opened_at=NOW, short_con_id=111, long_con_id=222,
    )


def q(strike, bid, ask, con) -> ChainOption:
    return ChainOption(strike=strike, right="P", expiry=TODAY, bid=bid, ask=ask, delta=-0.1, con_id=con)


class FakeBroker:
    def __init__(self, quotes: list[ChainOption]) -> None:
        self.quotes = quotes

    async def requote(self, legs):
        return self.quotes


class FakeTrade:
    def __init__(self, order) -> None:
        self.order = order
        self.orderStatus = SimpleNamespace(status="Submitted", filled=0, avgFillPrice=0.0)
        self.fills: list[SimpleNamespace] = []

    def isDone(self) -> bool:
        return self.orderStatus.status in ("Filled", "Cancelled")


class FakeIB:
    """Fills when the limit equals *fill_at* (lmtPrice space), optionally partially."""

    def __init__(self, fill_at: float | None, fill_qty: int | None = None) -> None:
        self.fill_at = fill_at
        self.fill_qty = fill_qty
        self.placed: list[float] = []
        self.trade: FakeTrade | None = None
        self.cancelled = False

    def placeOrder(self, contract, order):
        self.placed.append(order.lmtPrice)
        if self.trade is None:
            order.permId, order.orderId = 9001, 7
            self.trade = FakeTrade(order)
        if self.fill_at is not None and abs(order.lmtPrice - self.fill_at) < 1e-9:
            qty = self.fill_qty or int(order.totalQuantity)
            self.trade.orderStatus.filled = qty
            self.trade.orderStatus.avgFillPrice = order.lmtPrice
            self.trade.orderStatus.status = "Filled" if qty == order.totalQuantity else "Submitted"
            self.trade.fills = [
                SimpleNamespace(commissionReport=SimpleNamespace(commission=0.65 * qty)) for _ in range(2)
            ]
        return self.trade

    def cancelOrder(self, order) -> None:
        self.cancelled = True
        assert self.trade is not None
        self.trade.orderStatus.status = "Cancelled"


def approve(fresh: SpreadCandidate) -> SpreadVerdict:
    return SpreadVerdict(spread_id=fresh.spread_id, approved=True, contracts=2)


def reject(fresh: SpreadCandidate) -> SpreadVerdict:
    return SpreadVerdict(spread_id=fresh.spread_id, approved=False, reasons=["stale_quote"])


async def test_shadow_open_charges_slippage_and_commission() -> None:
    r = await SpreadExecutor(None, FakeBroker([]), SHADOW, now=lambda: NOW).open(cand(), 1, approve)
    assert r.filled_qty == 1 and r.price == pytest.approx(0.57) and r.commission == pytest.approx(1.30)
    assert r.order_ref == "CS:s1"


async def test_shadow_close_uses_mid_plus_slippage_or_the_worst_case() -> None:
    ex = SpreadExecutor(None, FakeBroker([]), SHADOW, now=lambda: NOW)
    r = await ex.close(position(), q(679, 0.38, 0.42, 111), q(674, 0.09, 0.11, 222), urgent=False)
    assert r.price == pytest.approx(0.34)
    worst = await ex.close(position(), None, None, urgent=True)
    assert worst.price == pytest.approx(5.0)


async def test_paper_open_walks_the_ladder_until_it_fills() -> None:
    ib = FakeIB(fill_at=-0.60)
    fresh = [q(679, 0.80, 0.86, 111), q(674, 0.20, 0.24, 222)]
    r = await SpreadExecutor(ib, FakeBroker(fresh), PAPER, now=lambda: NOW, poll_seconds=0.01).open(cand(), 1, approve)
    assert ib.placed == [-0.61, -0.60]
    assert (r.filled_qty, r.price, r.perm_id, r.ib_order_id) == (1, pytest.approx(0.60), 9001, 7)
    assert r.commission == pytest.approx(1.30)


async def test_paper_open_is_regated_on_fresh_quotes_and_can_be_refused() -> None:
    ib = FakeIB(fill_at=-0.61)
    fresh = [q(679, 0.80, 0.86, 111), q(674, 0.20, 0.24, 222)]
    r = await SpreadExecutor(ib, FakeBroker(fresh), PAPER, now=lambda: NOW).open(cand(), 1, reject)
    assert r.filled_qty == 0 and r.reason == "regate:stale_quote" and ib.placed == []


async def test_paper_open_without_a_fresh_quote_never_sends() -> None:
    ib = FakeIB(fill_at=-0.61)
    r = await SpreadExecutor(ib, FakeBroker([]), PAPER, now=lambda: NOW).open(cand(), 1, approve)
    assert r.reason == "no_fresh_quote" and ib.placed == []


# Review Focus 3 — a partial combo fill keeps what filled.
async def test_partial_fill_is_reported_after_the_cancel() -> None:
    ib = FakeIB(fill_at=-0.61, fill_qty=1)
    fresh = [q(679, 0.80, 0.86, 111), q(674, 0.20, 0.24, 222)]
    r = await SpreadExecutor(ib, FakeBroker(fresh), PAPER, now=lambda: NOW, poll_seconds=0.01).open(cand(), 2, approve)
    assert ib.cancelled and r.filled_qty == 1 and r.price == pytest.approx(0.61)


async def test_unfilled_order_is_cancelled() -> None:
    ib = FakeIB(fill_at=None)
    fresh = [q(679, 0.80, 0.86, 111), q(674, 0.20, 0.24, 222)]
    r = await SpreadExecutor(ib, FakeBroker(fresh), PAPER, now=lambda: NOW, poll_seconds=0.01).open(cand(), 1, approve)
    assert ib.cancelled and r.filled_qty == 0 and r.reason == "not_filled"


async def test_urgent_close_ends_at_the_natural_debit() -> None:
    ib = FakeIB(fill_at=0.34)
    ex = SpreadExecutor(ib, FakeBroker([]), PAPER, now=lambda: NOW, poll_seconds=0.01)
    r = await ex.close(position(), q(679, 0.38, 0.42, 111), q(674, 0.08, 0.12, 222), urgent=True)
    assert ib.placed == [0.30, 0.31, 0.32, 0.34]
    assert r.filled_qty == 1 and r.price == pytest.approx(0.34)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_orders.py tests/test_spreads_executor.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.orders'`.

- [ ] **Step 4: Implement `src/spreads/orders.py`**

```python
"""Combo (BAG) orders for a credit vertical, and the price ladders that work them.

IBKR combo convention — the same one ``execution.order_builder.build_combo_roll_order`` uses:
the parent order BUYs the bag and ``lmtPrice`` is the net DEBIT per share, so a credit is a
negative limit. Opening legs: SELL the short, BUY the long. Closing legs: BUY the short, SELL
the long, at a positive limit. **Not yet verified on a live paper session** — run
``scripts/spreads_combo_check.py`` (plan Task 11 Step 9) before trusting paper mode;
STATUS.md tracks it.
"""

from __future__ import annotations

from ib_async import ComboLeg, Contract, LimitOrder

from src.common.schemas import SpreadCandidate, SpreadPosition


def round_tick(price: float, tick: float = 0.01) -> float:
    return round(round(price / tick) * tick, 2)


def _bag(symbol: str, legs: list[ComboLeg]) -> Contract:
    return Contract(symbol=symbol, secType="BAG", currency="USD", exchange="SMART", comboLegs=legs)


def build_open_order(
    symbol: str, c: SpreadCandidate, contracts: int, credit: float, order_ref: str
) -> tuple[Contract, LimitOrder]:
    if contracts < 1:
        raise ValueError(f"spread order needs >= 1 contract, got {contracts}")
    if not c.short_con_id or not c.long_con_id:
        raise ValueError(f"{c.spread_id}: both legs must be qualified (conIds) before an order")
    if credit <= 0:
        raise ValueError(f"{c.spread_id}: an opening credit must be positive, got {credit}")
    bag = _bag(
        symbol,
        [
            ComboLeg(conId=c.short_con_id, ratio=1, action="SELL", exchange="SMART"),
            ComboLeg(conId=c.long_con_id, ratio=1, action="BUY", exchange="SMART"),
        ],
    )
    order = LimitOrder("BUY", contracts, round_tick(-credit), tif="DAY", orderRef=order_ref)
    return bag, order


def build_close_order(
    symbol: str, pos: SpreadPosition, contracts: int, debit: float, order_ref: str
) -> tuple[Contract, LimitOrder]:
    if contracts < 1:
        raise ValueError(f"close needs >= 1 contract, got {contracts}")
    if not pos.short_con_id or not pos.long_con_id:
        raise ValueError(f"{pos.spread_id}: missing leg conIds")
    if debit <= 0:
        raise ValueError(f"{pos.spread_id}: a closing debit must be positive, got {debit}")
    bag = _bag(
        symbol,
        [
            ComboLeg(conId=pos.short_con_id, ratio=1, action="BUY", exchange="SMART"),
            ComboLeg(conId=pos.long_con_id, ratio=1, action="SELL", exchange="SMART"),
        ],
    )
    order = LimitOrder("BUY", contracts, round_tick(debit), tif="DAY", orderRef=order_ref)
    return bag, order


def credit_ladder(mid: float, natural: float, steps: int, tick: float, floor: float) -> list[float]:
    """Mid credit, then one tick worse per step, never below max(natural, floor)."""
    bottom = max(natural, floor)
    start = round_tick(mid, tick)
    out: list[float] = []
    for i in range(max(steps, 1)):
        px = round_tick(start - i * tick, tick)
        if px < bottom - 1e-9:
            break
        out.append(px)
    return out


def debit_ladder(mid: float, steps: int, tick: float, cap: float) -> list[float]:
    """Mid debit, then one tick worse per step, never above *cap*."""
    start = round_tick(max(mid, tick), tick)
    out: list[float] = []
    for i in range(max(steps, 1)):
        px = round_tick(start + i * tick, tick)
        if px > cap + 1e-9:
            break
        out.append(px)
    return out or [round_tick(min(start, cap), tick)]
```

- [ ] **Step 5: Implement `src/spreads/executor.py`**

```python
"""Turns an approved spread into a fill: simulated (shadow) or a laddered paper combo order.

Paper opens are re-gated: the spread is repriced from fresh leg quotes and run through the
caller's ``recheck`` — the same ``risk.validate`` — immediately before the order is sent (the
core invariant's second gate run). An unfilled order is cancelled; a partial fill is reported
as what it is. Shadow fills charge ``shadow_slippage_per_leg`` per leg and the configured
commission so shadow P&L is not flattered by mid-price fills.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from src.common.config import SpreadsCfg
from src.common.schemas import ChainOption, SpreadCandidate, SpreadPosition, SpreadVerdict
from src.spreads.manager import debit_to_close
from src.spreads.orders import (
    build_close_order,
    build_open_order,
    credit_ladder,
    debit_ladder,
    round_tick,
)
from src.spreads.selector import refresh_candidate

log = logging.getLogger(__name__)


class Requoter(Protocol):
    async def requote(self, legs: list[ChainOption]) -> list[ChainOption]: ...


@dataclass(frozen=True)
class FillResult:
    filled_qty: int
    price: float | None  # per share: credit for an open, debit for a close
    commission: float  # positive cost
    perm_id: int | None = None
    ib_order_id: int | None = None
    reason: str | None = None
    order_ref: str = ""


def _right(side: str) -> str:
    return "P" if side == "put" else "C"


def _match(quotes: list[ChainOption], strike: float, right: str) -> ChainOption | None:
    return next((x for x in quotes if x.right == right and abs(x.strike - strike) < 1e-6), None)


def _commission(trade: Any) -> float:
    total = 0.0
    for f in getattr(trade, "fills", []) or []:
        rep = getattr(f, "commissionReport", None)
        try:
            c = float(getattr(rep, "commission", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(c) and abs(c) < 1e9:
            total += abs(c)
    return total


class SpreadExecutor:
    def __init__(
        self,
        ib: Any,
        broker: Requoter,
        cfg: SpreadsCfg,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        poll_seconds: float = 0.25,
    ) -> None:
        self.ib = ib
        self.broker = broker
        self.cfg = cfg
        self.now = now
        self.poll = poll_seconds

    async def open(
        self,
        c: SpreadCandidate,
        contracts: int,
        recheck: Callable[[SpreadCandidate], SpreadVerdict],
    ) -> FillResult:
        x = self.cfg.execution
        ref = f"{self.cfg.order_ref_prefix}{c.spread_id}"
        if self.cfg.mode == "shadow":
            credit = round(c.credit_mid - 2 * x.shadow_slippage_per_leg, 4)
            if credit <= 0:
                return FillResult(0, None, 0.0, reason="shadow_credit_nonpositive", order_ref=ref)
            return FillResult(contracts, credit, 2 * contracts * x.commission_per_contract, order_ref=ref)

        right = _right(c.side)
        legs = [
            ChainOption(strike=c.short_strike, right=right, expiry=c.expiry, con_id=c.short_con_id),  # type: ignore[arg-type]
            ChainOption(strike=c.long_strike, right=right, expiry=c.expiry, con_id=c.long_con_id),  # type: ignore[arg-type]
        ]
        quotes = await self.broker.requote(legs)
        short_q, long_q = _match(quotes, c.short_strike, right), _match(quotes, c.long_strike, right)
        fresh = (
            refresh_candidate(c, short_q, long_q, self.now())
            if short_q is not None and long_q is not None
            else None
        )
        if fresh is None:
            return FillResult(0, None, 0.0, reason="no_fresh_quote", order_ref=ref)
        verdict = recheck(fresh)
        if not verdict.approved:
            return FillResult(0, None, 0.0, reason="regate:" + ",".join(verdict.reasons), order_ref=ref)
        qty = max(1, min(contracts, verdict.contracts))
        floor = self.cfg.selection.min_credit_pct_of_width * self.cfg.selection.width
        ladder = credit_ladder(fresh.credit_mid, fresh.credit_natural, x.reprice_steps, x.reprice_tick, floor)
        if not ladder:
            return FillResult(0, None, 0.0, reason="no_price_above_floor", order_ref=ref)
        bag, order = build_open_order(self.cfg.underlying, fresh, qty, ladder[0], ref)
        filled, avg, commission, perm, oid = await self._work(bag, order, [-p for p in ladder], x.order_ttl_seconds)
        return FillResult(
            filled,
            -avg if avg is not None else None,
            commission,
            perm,
            oid,
            None if filled else "not_filled",
            ref,
        )

    async def close(
        self,
        pos: SpreadPosition,
        short_q: ChainOption | None,
        long_q: ChainOption | None,
        *,
        urgent: bool,
    ) -> FillResult:
        x = self.cfg.execution
        ref = f"{self.cfg.order_ref_prefix}{pos.spread_id}:X"
        mid, nat = debit_to_close(short_q, long_q)
        if self.cfg.mode == "shadow":
            base = mid if mid is not None else nat if nat is not None else pos.width
            debit = min(pos.width, round(base + 2 * x.shadow_slippage_per_leg, 4)) if base < pos.width else pos.width
            return FillResult(
                pos.contracts, debit, 2 * pos.contracts * x.commission_per_contract, order_ref=ref
            )
        start = mid if mid is not None else nat
        if start is None:
            return FillResult(0, None, 0.0, reason="no_quote", order_ref=ref)
        cap = min(pos.width, (nat if nat is not None else start) + x.close_max_concession)
        ladder = debit_ladder(start, x.reprice_steps, x.reprice_tick, cap)
        if urgent and nat is not None and nat <= cap and ladder[-1] < round_tick(nat) - 1e-9:
            ladder.append(round_tick(nat))
        bag, order = build_close_order(self.cfg.underlying, pos, pos.contracts, ladder[0], ref)
        filled, avg, commission, perm, oid = await self._work(bag, order, ladder, x.close_ttl_seconds)
        return FillResult(filled, avg, commission, perm, oid, None if filled else "not_filled", ref)

    async def _wait_done(self, trade: Any, seconds: float) -> bool:
        deadline = asyncio.get_running_loop().time() + seconds
        while not trade.isDone():
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(self.poll)
        return True

    async def _work(
        self, bag: Any, order: Any, lmt_prices: list[float], ttl: float
    ) -> tuple[int, float | None, float, int | None, int | None]:
        trade = self.ib.placeOrder(bag, order)
        per_step = ttl / max(len(lmt_prices), 1)
        for i, px in enumerate(lmt_prices):
            if i > 0:
                if trade.isDone():
                    break
                order.lmtPrice = px
                trade = self.ib.placeOrder(bag, order)
            if await self._wait_done(trade, per_step):
                break
        if not trade.isDone():
            self.ib.cancelOrder(order)
            await self._wait_done(trade, 5.0)
        filled = int(trade.orderStatus.filled or 0)
        avg = float(trade.orderStatus.avgFillPrice) if filled else None
        perm = int(getattr(trade.order, "permId", 0) or 0) or None
        oid = int(getattr(trade.order, "orderId", 0) or 0) or None
        log.info("spreads order %s: filled %d @ %s", getattr(order, "orderRef", ""), filled, avg)
        return filled, avg, _commission(trade), perm, oid
```

- [ ] **Step 6: Run the order and executor tests**

Run: `python -m pytest tests/test_spreads_orders.py tests/test_spreads_executor.py -q && ruff check . && mypy src`
Expected: PASS.

- [ ] **Step 7: Create the operator check script `scripts/spreads_combo_check.py`**

```python
"""Operator check: does a spreads BAG order show in TWS as a CREDIT spread? (plan Task 11 Step 9)

Places ONE deliberately unfillable put credit spread on the configured underlying (SPY) on the PAPER account — limit credit
at 90% of the width, far above any real price — prints what IBKR echoes back, waits so you can
look at the order in TWS/Gateway, then cancels it. Refuses to run with LIVE_TRADING=true.

    python -m scripts.spreads_combo_check --short 600 --long 595

Expected in TWS: a BAG on SPY, "SELL 600P / BUY 595P", shown as a CREDIT of 4.50. If TWS shows
a DEBIT, the sign convention in src/spreads/orders.py is wrong — do not enable paper mode.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from ib_async import IB, Option

from src.common.config import get_config
from src.common.logging import setup_logging
from src.common.market_hours import today_et
from src.common.schemas import SpreadCandidate
from src.ibkr.connection import connect_with_retry
from src.spreads.orders import build_open_order


async def _main(short: float, long_: float, wait: float) -> None:
    cfg = get_config()
    if cfg.is_live:
        raise SystemExit("refusing: LIVE_TRADING=true — this check is paper-only")
    sc = cfg.spreads
    ib = IB()
    await connect_with_retry(
        ib, cfg.ibkr.host, cfg.ibkr_port, cfg.ibkr.client_ids["healthcheck"],
        timeout=cfg.ibkr.connect_timeout_seconds, label="spreads_combo_check",
    )
    try:
        expiry = today_et()
        legs = [Option(sc.underlying, f"{expiry:%Y%m%d}", k, "P", "SMART", tradingClass=sc.trading_class) for k in (short, long_)]
        await ib.qualifyContractsAsync(*legs)
        if not all(leg.conId for leg in legs):
            raise SystemExit(f"could not qualify {sc.underlying} {short}/{long_} puts for {expiry}")
        width = abs(short - long_)
        cand = SpreadCandidate(
            spread_id="combo-check", side="put", expiry=expiry, short_strike=short, long_strike=long_,
            width=width, short_con_id=legs[0].conId, long_con_id=legs[1].conId,
            credit_mid=0.9 * width, credit_natural=0.9 * width, spot=0.0, quote_time=datetime.now(UTC),
        )
        bag, order = build_open_order(sc.underlying, cand, 1, 0.9 * width, f"{sc.order_ref_prefix}combo-check")
        trade = ib.placeOrder(bag, order)
        await asyncio.sleep(2)
        print("orderStatus:", trade.orderStatus)
        print("order:", trade.order)
        print(f"Look at TWS now ({wait:.0f}s): it must show a CREDIT of {0.9 * width:.2f}.")
        await asyncio.sleep(wait)
    finally:
        for t in ib.openTrades():
            if getattr(t.order, "orderRef", "") == f"{sc.order_ref_prefix}combo-check":
                ib.cancelOrder(t.order)
        await asyncio.sleep(2)
        ib.disconnect()


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--short", type=float, required=True)
    p.add_argument("--long", type=float, required=True)
    p.add_argument("--wait", type=float, default=60.0)
    a = p.parse_args()
    asyncio.run(_main(a.short, a.long, a.wait))


if __name__ == "__main__":
    main()
```

It uses the `healthcheck` clientId (19) deliberately, because it's a short-lived operator tool and never runs concurrently with the healthcheck.

- [ ] **Step 8: Commit**

```bash
ruff format src/spreads/orders.py src/spreads/executor.py scripts/spreads_combo_check.py tests/test_spreads_orders.py tests/test_spreads_executor.py
git add src/spreads/orders.py src/spreads/executor.py scripts/spreads_combo_check.py tests/test_spreads_orders.py tests/test_spreads_executor.py
git commit -m "feat(spreads): BAG combo orders, laddered executor with send-time re-gate, shadow fills"
```

- [ ] **Step 9: Operator verification (run once, by a human, before `mode: paper`)**

This step can't run in CI. Record its result in `STATUS.md`.

1. During RTH, run `python -m scripts.spreads_combo_check --short <spot−60, rounded> --long <short−5>` against the paper Gateway.
2. Confirm that TWS shows the BAG as a **credit** of `0.9 × width`.
3. Confirm the order was cancelled.
4. If TWS shows a debit: fix `build_open_order` / `build_close_order` (flip the order action to `SELL` with a positive limit), fix the tests in `tests/test_spreads_orders.py`, and re-run this step.

---

### Task 12: Telegram notifier and message formats

**Files:**
- Create: `src/spreads/notify.py`, `tests/test_spreads_notify.py`
- Modify: `.env.example`, adding `TELEGRAM_THREAD_SPREADS=` under the other `TELEGRAM_THREAD_*` lines

**Interfaces:**
- Consumes: `GexLevels`, `SpreadPosition`, `SpreadEntryContext` (Task 4); `Config.secrets` (Task 1).
- Produces:
  - `SpreadsNotifier(token, chat_id, thread)`, with `.from_config(cfg)`, `.thread_id`, and `async send(text)`
  - `fmt_map(levels, mode) -> str`
  - `fmt_entry(pos, mode, context=None) -> str` (with a context, a second line names the gamma regime, in capitals when negative, the move it sold against, and the gap)
  - `fmt_exit(spread_id, reason, debit, realized_usd, mode) -> str`
  - `fmt_eod(day, mode, trades, realized_usd, open_count) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_notify.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime

import src.spreads.notify as notify
from src.common.schemas import GexLevels, SpreadEntryContext, SpreadPosition
from src.spreads.notify import SpreadsNotifier, fmt_entry, fmt_eod, fmt_exit, fmt_map

NOW = datetime(2026, 10, 7, 13, 45, tzinfo=UTC)


def test_formats_carry_mode_and_numbers() -> None:
    lv = GexLevels(as_of=NOW, spot=690.12, net_gex=2.5e9, regime="positive", flip=676.0,
                   call_wall=700.0, put_wall=680.0, expected_move=5.8)
    m = fmt_map(lv, "shadow")
    assert m.startswith("[SHADOW]") and "690.12" in m and "positive" in m and "680" in m and "±5.80" in m
    pos = SpreadPosition(spread_id="s1", mode="paper", side="put", expiry=date(2026, 10, 7),
                         short_strike=679, long_strike=674, width=5, contracts=1, entry_credit=0.57,
                         opened_at=NOW)
    e = fmt_entry(pos, "paper")
    assert e.startswith("[PAPER]") and "679/674" in e and "0.57" in e and "443" in e
    tags = SpreadEntryContext(trigger="move", move_em=0.63, gap_pct=-0.004, gap_day=True, regime="negative",
                              net_gex=-1e9, spot=690.12, minutes_after_open=14)
    tagged = fmt_entry(pos, "paper", tags)
    assert tagged.startswith(e)
    assert "NEGATIVE GAMMA" in tagged and "0.63× expected-move drop" in tagged and "gap -0.40%" in tagged
    calm = tags.model_copy(update={"regime": "positive", "gap_day": False})
    assert "gamma positive" in fmt_entry(pos, "paper", calm) and "gap" not in fmt_entry(pos, "paper", calm)
    x = fmt_exit("s1", "profit_take", 0.32, 22.4, "paper")
    assert "profit_take" in x and "+$22.40" in x
    assert "-$61.30" in fmt_exit("s1", "stop_loss", 1.2, -61.3, "paper")
    assert "2 trade(s)" in fmt_eod(date(2026, 10, 7), "shadow", 2, -10.0, 0)


async def test_send_without_credentials_never_builds_a_bot(monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("Bot must not be constructed without credentials")

    monkeypatch.setattr(notify, "Bot", boom)
    await SpreadsNotifier("", "", "").send("hello")


async def test_send_posts_to_the_spreads_thread(monkeypatch) -> None:
    sent: list[dict] = []

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_message(self, **kw):
            sent.append(kw)

    monkeypatch.setattr(notify, "Bot", FakeBot)
    await SpreadsNotifier("tok", "123", "77").send("hello")
    assert sent == [{"chat_id": "123", "text": "hello", "message_thread_id": 77}]
    assert SpreadsNotifier("tok", "123", "").thread_id is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_notify.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.notify'`.

- [ ] **Step 3: Implement `src/spreads/notify.py`**

```python
"""Telegram output for the spreads system — its own thread, its own Bot, no src.notify import.

Best effort: a send failure is logged and swallowed, never raised into trading code.
"""

from __future__ import annotations

import logging
from datetime import date

from telegram import Bot

from src.common.config import Config
from src.common.schemas import GexLevels, SpreadEntryContext, SpreadPosition
from src.spreads.pricing import ET

log = logging.getLogger(__name__)


def _tag(mode: str) -> str:
    return f"[{mode.upper()}]"


def _money(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def _lvl(v: float | None) -> str:
    return "n/a" if v is None else f"{v:,.2f}"


def fmt_map(levels: GexLevels, mode: str) -> str:
    em = "n/a" if levels.expected_move is None else f"±{levels.expected_move:.2f}"
    return (
        f"{_tag(mode)} GEX map {levels.as_of.astimezone(ET):%H:%M} ET (levels in traded-underlying points)\n"
        f"spot {levels.spot:,.2f} · regime {levels.regime} · expected move {em}\n"
        f"put wall {_lvl(levels.put_wall)} · flip {_lvl(levels.flip)} · call wall {_lvl(levels.call_wall)}"
    )


def fmt_entry(pos: SpreadPosition, mode: str, context: SpreadEntryContext | None = None) -> str:
    risk = (pos.width - pos.entry_credit) * 100 * pos.contracts
    line = (
        f"{_tag(mode)} OPENED {pos.side} spread {pos.short_strike:g}/{pos.long_strike:g} "
        f"×{pos.contracts} for {pos.entry_credit:.2f} credit · max loss ${risk:,.0f} · {pos.spread_id}"
    )
    if context is None:
        return line
    tags = ["NEGATIVE GAMMA" if context.regime == "negative" else f"gamma {context.regime}"]
    if context.trigger == "move" and context.move_em is not None:
        move = "drop" if pos.side == "put" else "rise"
        tags.append(f"after a {context.move_em:.2f}× expected-move {move}")
    if context.gap_day and context.gap_pct is not None:
        tags.append(f"gap {context.gap_pct * 100:+.2f}%")
    return line + "\n" + " · ".join(tags)


def fmt_exit(
    spread_id: str, reason: str, debit: float | None, realized_usd: float | None, mode: str
) -> str:
    paid = "n/a" if debit is None else f"{debit:.2f}"
    pnl = "pending settlement" if realized_usd is None else _money(realized_usd)
    return f"{_tag(mode)} CLOSED {spread_id} · {reason} · debit {paid} · {pnl}"


def fmt_eod(day: date, mode: str, trades: int, realized_usd: float, open_count: int) -> str:
    return (
        f"{_tag(mode)} spreads {day:%Y-%m-%d}: {trades} trade(s) · realized {_money(realized_usd)}"
        f" · {open_count} still open"
    )


class SpreadsNotifier:
    def __init__(self, token: str, chat_id: str, thread: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self.thread = thread

    @classmethod
    def from_config(cls, cfg: Config) -> SpreadsNotifier:
        s = cfg.secrets
        return cls(s.telegram_bot_token, s.telegram_chat_id, s.telegram_thread_spreads)

    @property
    def thread_id(self) -> int | None:
        raw = (self.thread or "").strip()
        return int(raw) if raw.isdigit() else None

    async def send(self, text: str) -> None:
        log.info("spreads notify: %s", text.splitlines()[0] if text else "")
        if not self.token or not self.chat_id:
            return
        try:
            async with Bot(token=self.token) as bot:
                await bot.send_message(chat_id=self.chat_id, text=text, message_thread_id=self.thread_id)
        except Exception:
            log.exception("spreads notify failed")
```

- [ ] **Step 4: Run the tests and the gate, then commit**

Run: `python -m pytest tests/test_spreads_notify.py -q && ruff check . && mypy src`
Expected: PASS.

```bash
ruff format src/spreads/notify.py tests/test_spreads_notify.py
git add src/spreads/notify.py tests/test_spreads_notify.py .env.example
git commit -m "feat(spreads): Telegram notifier and message formats"
```

---

### Task 13: The spreads service, process entrypoint, and supervisor wiring

**Files:**
- Create: `src/spreads/service.py`, `scripts/run_spreads.py`, `tests/test_spreads_service.py`
- Modify: `scripts/start.py`, `tests/test_start_launcher.py`

**Interfaces:**
- Consumes everything from Tasks 4–12 (including Task 6A's `SessionTape` and `trigger`, and the broker's `session_quote`), plus `src.ledger.live.attach_live_hook`, `src.ledger.state.ledger_account`, `src.storage.db.session_scope`, and `src.ibkr.connection.connect_with_retry`.
- Produces:
  - `SpreadsService(broker, executor, notifier, cfg, *, halt_path, now=...)`, with:
    - `async start()`
    - `on_disconnect()`
    - `async tick()`: map → tape sample → manage (records each open spread's worst mark) → entries (only when the trigger allows a side)
    - `async alert_once(key, text)`
    - attributes `entries_blocked: str | None`, `levels: GexLevels | None`, `tape: SessionTape | None`
  - Every opened position is stored with its `SpreadEntryContext` and announced with it (`fmt_entry(pos, mode, context)`).
  - `async run(stop_event: asyncio.Event | None = None) -> None`
  - `scripts.run_spreads.main()`
  - Supervisor service key `"spreads"` and the `--no-spreads` flag.

- [ ] **Step 1: Write the failing service tests**

`tests/test_spreads_service.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, ChainSnapshot, SessionSnapshot
from src.spreads.executor import SpreadExecutor

TODAY = date(2026, 10, 7)
T0931 = datetime(2026, 10, 7, 13, 31, tzinfo=UTC)
T0936 = datetime(2026, 10, 7, 13, 36, tzinfo=UTC)
T0941 = datetime(2026, 10, 7, 13, 41, tzinfo=UTC)
T0945 = datetime(2026, 10, 7, 13, 45, tzinfo=UTC)
T0947 = datetime(2026, 10, 7, 13, 47, tzinfo=UTC)
T0950 = datetime(2026, 10, 7, 13, 50, tzinfo=UTC)
T1001 = datetime(2026, 10, 7, 14, 1, tzinfo=UTC)
T1005 = datetime(2026, 10, 7, 14, 5, tzinfo=UTC)
T1100 = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
T1610 = datetime(2026, 10, 7, 20, 10, tzinfo=UTC)
SATURDAY = datetime(2026, 10, 10, 14, 5, tzinfo=UTC)

_BASE = get_config().spreads
# The mechanics tests pin the original rule (map 09:45, entries from 10:00, every check, both
# sides) and one contract (max_contracts 1), so they test the loop, not the trigger or the
# sizing. MOVE below exercises the amendment's rules; the sizing test lifts the contract cap.
CFG = _BASE.model_copy(
    update={
        "enabled": True,
        "mode": "shadow",
        "schedule": _BASE.schedule.model_copy(
            update={"map_time": "09:45", "entry_start": "10:00", "entry_end": "13:30",
                    "entry_check_minutes": 5, "map_refresh_minutes": 60, "force_close": "15:45"}
        ),
        "entry": _BASE.entry.model_copy(update={"trigger": "always"}),
        "selection": _BASE.selection.model_copy(
            update={"sides": ["put", "call"], "width": 5.0, "min_credit_pct_of_width": 0.10,
                    "short_delta_max": 0.15, "max_leg_spread_pct": 0.30, "em_multiple": 1.0,
                    "em_straddle_factor": 1.0, "wall_buffer_pct": 0.001}
        ),
        "risk": _BASE.risk.model_copy(
            update={"max_trades_per_day": 2, "max_open_spreads": 2, "max_contracts": 1,
                    "starting_capital_usd": 100_000.0, "max_loss_pct_of_capital": 0.10,
                    "max_total_risk_pct_of_capital": 0.10, "max_daily_loss_pct_of_capital": 0.10,
                    "min_excess_liquidity_usd": 10_000.0, "max_quote_age_seconds": 20.0,
                    "one_side_per_day": True, "events": [], "ex_dividend_dates": []}
        ),
        "exits": _BASE.exits.model_copy(update={"profit_take_pct": 50.0, "stop_debit_multiple": 2.0,
                                                "max_hold_minutes": 150}),
        "gex": _BASE.gex.model_copy(update={"negative_gamma_action": "skip", "flip_buffer_pct": 0.002}),
    }
)
# One entry per day: the 11:00 entry check would otherwise open a second, identical spread.
ONE_A_DAY = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"max_trades_per_day": 1})})
# The amendment's rules: opening map and window, the move trigger, negative gamma traded.
MOVE = ONE_A_DAY.model_copy(
    update={
        "schedule": CFG.schedule.model_copy(update={"map_time": "09:31", "entry_start": "09:35"}),
        "entry": _BASE.entry.model_copy(
            update={"trigger": "move", "min_move_em": 0.5, "max_move_em": 1.5, "stall_minutes": 10,
                    "max_tape_age_seconds": 120.0, "gap_day_pct": 0.003}
        ),
        "gex": CFG.gex.model_copy(update={"negative_gamma_action": "allow"}),
    }
)


def o(strike, right, bid=None, ask=None, *, oi=None, iv=None, delta=None):
    return ChainOption(strike=strike, right=right, expiry=TODAY, bid=bid, ask=ask, open_interest=oi,
                       iv=iv, delta=delta, con_id=int(strike * 10) + (1 if right == "C" else 0))


class FakeBroker:
    """SPX OI makes a positive-gamma day (swap ``spx_oi`` for a negative one); SPY has one
    qualifying put spread (679/674) and an ATM straddle of 5.8; ``session`` is the SPY tape."""

    def __init__(self, clock: list[datetime]) -> None:
        self.clock = clock
        self.calls: list[str] = []
        self.legs: dict[int, float] = {}
        self.fail_requote = False
        self.spx_oi = {"P": 1_000, "C": 40_000}
        self.xsp_atm = {"C": (2.9, 3.1), "P": (2.7, 2.9)}
        self.session: dict[str, float | None] = {
            "last": 690.0, "open": 690.0, "high": 690.0, "low": 690.0, "prior_close": 690.0,
        }
        self.leg_quotes = {
            (679.0, "P"): o(679, "P", 0.80, 0.86, delta=-0.12),
            (674.0, "P"): o(674, "P", 0.20, 0.24),
        }

    async def fetch_chain(self, *, symbol, trading_class, exchange, expiries, band_pct, spot_hint=None, sec_type="IND"):
        self.calls.append(symbol)
        if symbol == "SPX":
            assert sec_type == "IND"
            return ChainSnapshot(symbol="SPX", spot=6900.0, as_of=self.clock[0], options=[
                o(6800, "P", oi=self.spx_oi["P"], iv=0.40), o(6950, "C", oi=self.spx_oi["C"], iv=0.40)])
        assert (symbol, sec_type) == ("SPY", "STK")
        return ChainSnapshot(symbol="SPY", spot=690.0, as_of=self.clock[0], options=[
            o(690, "C", *self.xsp_atm["C"]), o(690, "P", *self.xsp_atm["P"]),
            o(679, "P", 0.80, 0.86, delta=-0.12), o(674, "P", 0.20, 0.24)])

    async def session_quote(self):
        return SessionSnapshot(as_of=self.clock[0], **self.session)

    async def requote(self, legs):
        if self.fail_requote:
            raise ConnectionError("socket dropped")
        return [self.leg_quotes.get((float(x.strike), x.right), x).model_copy(update={"con_id": x.con_id}) for x in legs]

    async def spot(self):
        return 690.0

    async def excess_liquidity(self):
        return 50_000.0

    def broker_legs(self):
        return self.legs


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


@pytest.fixture()
def spreads_db(tmp_path, monkeypatch):
    import src.spreads.store as st

    monkeypatch.setattr(st, "_engine", None)
    monkeypatch.setattr(st, "_SessionLocal", None)
    monkeypatch.setattr(st, "_resolve_url", lambda: f"sqlite:///{tmp_path / 'spreads.db'}")
    st.init_spreads_db()
    return st


def make(tmp_path, clock, cfg=CFG, broker=None):
    from src.spreads.service import SpreadsService

    broker = broker or FakeBroker(clock)
    notifier = FakeNotifier()
    ex = SpreadExecutor(None, broker, cfg, now=lambda: clock[0])
    svc = SpreadsService(broker, ex, notifier, cfg, halt_path=tmp_path / "halt", now=lambda: clock[0])
    return svc, broker, notifier


async def test_a_full_shadow_day_maps_enters_and_takes_profit(tmp_path, spreads_db) -> None:
    clock = [T0945]
    svc, broker, notifier = make(tmp_path, clock, ONE_A_DAY)
    await svc.start()
    await svc.tick()  # 09:45 — map only
    assert svc.levels is not None and svc.levels.regime == "positive"
    assert spreads_db.open_positions("shadow") == []
    clock[0] = T1005
    await svc.tick()  # 10:05 — entry
    (pos,) = spreads_db.open_positions("shadow")
    assert (pos.short_strike, pos.long_strike, pos.entry_credit) == (679.0, 674.0, pytest.approx(0.57))
    broker.leg_quotes = {(679.0, "P"): o(679, "P", 0.30, 0.34), (674.0, "P"): o(674, "P", 0.03, 0.05)}
    clock[0] = T1100
    await svc.tick()  # 11:00 — profit take (mid 0.28 ≤ 0.285)
    assert spreads_db.open_positions("shadow") == []
    ((_, reason, pnl),) = spreads_db.closed_results("shadow")
    assert reason == "profit_take" and pnl == pytest.approx((0.57 - 0.32) * 100 - 1.30 - 1.30)
    (t,) = spreads_db.trade_log("shadow")  # every trade is logged with its tags
    assert (t.trigger, t.regime, t.exit_reason) == ("always", "positive", "profit_take")
    assert t.hold_minutes == pytest.approx(55.0) and t.mae_usd == pytest.approx(0.0)
    assert svc.capital() == pytest.approx(100_000.0 + pnl)  # the book's capital grows with it
    clock[0] = T1610
    await svc.tick()  # EOD summary once
    await svc.tick()
    assert sum("trade(s)" in m for m in notifier.sent) == 1


async def test_entries_are_sized_to_ten_percent_of_the_books_capital(tmp_path, spreads_db) -> None:
    roomy = ONE_A_DAY.model_copy(update={"risk": ONE_A_DAY.risk.model_copy(update={"max_contracts": 100})})
    clock = [T0945]
    svc, _, _ = make(tmp_path, clock, roomy)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    (pos,) = spreads_db.open_positions("shadow")
    assert pos.contracts == 22  # ⌊10% × $100,000 ÷ ((5 − 0.61) × 100)⌋


async def test_a_spread_still_open_after_the_time_stop_raises_the_assignment_alert(tmp_path, spreads_db) -> None:
    from src.spreads.executor import FillResult

    clock = [T0945]
    svc, _, notifier = make(tmp_path, clock, ONE_A_DAY)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    assert len(spreads_db.open_positions("shadow")) == 1

    class NoFill:
        async def close(self, pos, short_q, long_q, *, urgent):
            return FillResult(0, None, 0.0, reason="not_filled", order_ref="CS:x")

    svc.executor = NoFill()
    clock[0] = datetime(2026, 10, 7, 19, 46, tzinfo=UTC)  # 15:46 ET, past the time stop
    await svc.tick()
    await svc.tick()
    assert len(spreads_db.open_positions("shadow")) == 1
    assert sum("risk assignment" in m for m in notifier.sent) == 1


async def _flush(svc, broker, clock) -> None:
    """09:31 map; the index flushes from a 693.5 prior close to a 689.8 low at 09:36, then holds."""
    broker.session.update(last=692.0, open=692.0, high=692.2, low=691.9, prior_close=693.5)
    clock[0] = T0931
    await svc.tick()
    broker.session.update(last=689.8, low=689.8)
    clock[0] = T0936
    await svc.tick()
    broker.session.update(last=690.4)
    clock[0] = T0941
    await svc.tick()


async def test_the_move_trigger_waits_for_a_stalled_flush_then_sells_puts(tmp_path, spreads_db) -> None:
    clock = [T0931]
    svc, broker, notifier = make(tmp_path, clock, MOVE)
    await svc.start()
    await _flush(svc, broker, clock)
    assert svc.tape is not None and svc.tape.day_em == pytest.approx(5.8)
    assert spreads_db.open_positions("shadow") == []
    assert broker.calls.count("SPY") == 1  # only the 09:31 map: no chain fetch until armed
    broker.session.update(last=690.0)
    clock[0] = T0947
    await svc.tick()  # the 09:36 low has held for 11 minutes
    (pos,) = spreads_db.open_positions("shadow")
    assert (pos.side, pos.short_strike, pos.long_strike) == ("put", 679.0, 674.0)
    (t,) = spreads_db.trade_log("shadow")
    assert (t.trigger, t.regime, t.gap_day, t.minutes_after_open) == ("move", "positive", False, 17)
    assert t.move_em == pytest.approx((693.5 - 690.0) / 5.8)
    assert t.gap_pct == pytest.approx(692.0 / 693.5 - 1)
    assert any("after a 0.60× expected-move drop" in m for m in notifier.sent)


async def test_negative_gamma_is_traded_and_tagged(tmp_path, spreads_db) -> None:
    clock = [T0931]
    svc, broker, notifier = make(tmp_path, clock, MOVE)
    broker.spx_oi = {"P": 40_000, "C": 1_000}  # put-heavy: dealers are short gamma at 6900
    await svc.start()
    await _flush(svc, broker, clock)
    assert svc.levels is not None and svc.levels.regime == "negative"
    broker.session.update(last=690.0)
    clock[0] = T0947
    await svc.tick()
    (t,) = spreads_db.trade_log("shadow")
    assert (t.regime, t.side) == ("negative", "put")
    assert any("NEGATIVE GAMMA" in m for m in notifier.sent)


# Review Focus 6 — a restart mid-move waits a full stall window and keeps the day's first yardstick.
async def test_a_restart_mid_flush_cannot_hurry_an_entry(tmp_path, spreads_db) -> None:
    clock = [T0931]
    svc, broker, _ = make(tmp_path, clock, MOVE)
    await svc.start()
    await _flush(svc, broker, clock)  # the 09:31 map stores the day's expected move, 5.8
    broker.xsp_atm = {"C": (1.9, 2.1), "P": (1.7, 1.9)}  # a later, smaller straddle (3.8)
    broker.session.update(last=690.0)
    clock[0] = T0950
    fresh, _, _ = make(tmp_path, clock, MOVE, broker=broker)  # the restarted process
    await fresh.start()
    await fresh.tick()  # rebuilds the map; the 689.8 low printed before this process existed
    assert fresh.tape is not None and fresh.tape.day_em == pytest.approx(5.8)
    assert spreads_db.open_positions("shadow") == []
    broker.session.update(last=690.2)
    clock[0] = T1001
    await fresh.tick()  # 11 minutes after its first observation
    assert len(spreads_db.open_positions("shadow")) == 1


# Review Focus 4 — a restart counts today's trades from the DB, not memory.
async def test_restart_never_exceeds_max_trades_per_day(tmp_path, spreads_db) -> None:
    one_a_day = ONE_A_DAY
    clock = [T0945]
    svc, _, _ = make(tmp_path, clock, one_a_day)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    assert len(spreads_db.open_positions("shadow")) == 1
    clock[0] = datetime(2026, 10, 7, 14, 20, tzinfo=UTC)
    fresh, _, _ = make(tmp_path, clock, one_a_day)  # the restarted process
    await fresh.start()
    await fresh.tick()  # rebuilds the map, then tries to enter
    assert len(spreads_db.open_positions("shadow")) == 1
    with spreads_db.spreads_session() as s:
        last = s.query(spreads_db.SpreadCandidateRow).order_by(spreads_db.SpreadCandidateRow.id.desc()).first()
        assert "max_trades_per_day" in last.reasons


async def test_halt_file_blocks_entries_but_not_exits(tmp_path, spreads_db) -> None:
    clock = [T0945]
    svc, broker, notifier = make(tmp_path, clock)
    await svc.tick()
    (tmp_path / "halt").write_text("")
    clock[0] = T1005
    await svc.tick()
    assert spreads_db.open_positions("shadow") == []
    assert broker.calls.count("SPY") == 1  # only the 09:45 map fetched SPY
    assert any("halt" in m for m in notifier.sent)


# Review Focus 1 — a broker/DB mismatch after a reconnect blocks entries until consistent.
async def test_reconcile_mismatch_blocks_entries_until_consistent(tmp_path, spreads_db) -> None:
    from src.common.schemas import SpreadCandidate

    paper = CFG.model_copy(update={"mode": "paper"})
    spreads_db.open_position(
        SpreadCandidate(spread_id="old", side="put", expiry=TODAY, short_strike=679, long_strike=674, width=5,
                        short_con_id=6790, long_con_id=6740, credit_mid=0.6, credit_natural=0.55, spot=690,
                        quote_time=T0945),
        mode="paper", contracts=1, credit=0.6, commission=1.3, now=T0945, perm_id=1,
    )
    clock = [T0945]
    svc, broker, notifier = make(tmp_path, clock, paper)
    await svc.start()
    assert svc.entries_blocked and "6790" in svc.entries_blocked
    svc.on_disconnect()
    assert svc.entries_blocked == "disconnected"
    broker.legs = {6790: -1.0, 6740: 1.0}
    await svc.start()
    assert svc.entries_blocked is None


async def test_a_failing_phase_never_kills_the_tick(tmp_path, spreads_db) -> None:
    clock = [T0945]
    svc, broker, notifier = make(tmp_path, clock, ONE_A_DAY)
    await svc.tick()
    clock[0] = T1005
    await svc.tick()
    broker.fail_requote = True
    clock[0] = T1100
    await svc.tick()  # manage raises inside; the tick must survive and alert once
    await svc.tick()
    assert sum("manage" in m for m in notifier.sent) == 1
    assert len(spreads_db.open_positions("shadow")) == 1


async def test_nothing_happens_on_a_weekend(tmp_path, spreads_db) -> None:
    clock = [SATURDAY]
    svc, broker, _ = make(tmp_path, clock)
    await svc.tick()
    assert broker.calls == []


async def test_run_idles_when_disabled_and_refuses_live(monkeypatch) -> None:
    import src.spreads.service as service

    def no_ib(*a, **k):
        raise AssertionError("must not connect")

    monkeypatch.setattr("ib_async.IB", no_ib)
    stop = asyncio.Event()
    stop.set()
    base = get_config()
    monkeypatch.setattr(service, "get_config", lambda: base.model_copy(update={"spreads": base.spreads.model_copy(update={"enabled": False})}))
    await service.run(stop)
    live = base.model_copy(update={
        "spreads": base.spreads.model_copy(update={"enabled": True}),
        "secrets": base.secrets.model_copy(update={"live_trading": True}),
    })
    monkeypatch.setattr(service, "get_config", lambda: live)
    await service.run(stop)
```

`ONE_A_DAY` matters in three tests: the 11:00 tick also runs an entry check, and without the cap it would open a second, identical spread. `MOVE` builds on it.

Check the move-trigger numbers: the day's expected move is the SPY straddle at 09:31, 3.0 + 2.8 = 5.8. At 09:47 the drop from the 693.5 prior close is 3.5 = 0.60 × 5.8 (between 0.5 and 1.5), and the 09:36 low has held 11 minutes, so the put side arms. The candidate is the same 679/674 put as the mechanics tests (put wall 680 − 0.69 is below 690 − 5.8). With the put-heavy SPX OI, net GEX at 6900 is negative and the flip sits near 7007 (1.5% away, outside the 0.2% buffer), so the only difference is the `negative` tag.

Check the numbers in the first test:
- Shadow credit = 0.61 − 2 × 0.02 = 0.57.
- At 11:00 the mid debit is (0.32 − 0.04) = 0.28, which is ≤ 0.57 × 0.5 = 0.285, so profit-take fires.
- Shadow debit = 0.28 + 0.04 = 0.32.
- P&L = (0.57 − 0.32) × 100 − 1.30 − 1.30 = 22.40.

The SPX OI (a small put at 6800, a large call at 6950) puts the flip below 6800, more than 1% from spot. So `near_gamma_flip` never triggers and the regime at 6900 is positive.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.service'`.

- [ ] **Step 3: Implement `src/spreads/service.py`**

```python
"""The spreads process: GEX map → price tape → exits → entries → end of day, on the ET clock.

Entries follow the amendment's rules (Design → "Entry rules borrowed from OPG"): the traded
index is sampled into a ``SessionTape`` every tick, and the traded chain is fetched only when
``tape.trigger`` allows a side (one side, against a stalled move). Every opened spread is stored
with its ``SpreadEntryContext`` tags, and each open spread's worst mark is recorded every tick,
so the trade log can be split by regime, side, trigger and gap day later.

``SpreadsService.tick()`` is one pass and owns every scheduling decision; ``run()`` is the
process loop around it (connect, reconcile, tick every ``manage_interval_seconds``, reconnect
after a Gateway drop). Exits run whenever spreads are open, even with entries blocked — a halt
file, a reconcile mismatch, or a disconnect only ever stops NEW risk. Each phase is guarded so
one failing phase (a dropped socket mid-requote) never takes the others down.

This is the only ``src/spreads`` module that may import ``src.ledger`` / ``src.storage``: in
paper mode it attaches the ledger's live commission-report hook so spreads fills land in the
trade ledger (``src/ledger`` dedupes by execId and tags them ``book="spreads"``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from src.common.config import SpreadsCfg, get_config
from src.common.market_hours import is_trading_day
from src.common.schemas import (
    ChainOption,
    ChainSnapshot,
    GexLevels,
    SessionSnapshot,
    SpreadCandidate,
    SpreadEntryContext,
    SpreadPosition,
    SpreadRiskContext,
    SpreadSide,
    SpreadVerdict,
)
from src.spreads import store
from src.spreads.executor import FillResult
from src.spreads.gex import build_levels, expected_move, regime_at
from src.spreads.manager import debit_to_close, evaluate_exit, intrinsic_debit, reconcile
from src.spreads.notify import SpreadsNotifier, fmt_entry, fmt_eod, fmt_exit, fmt_map
from src.spreads.pricing import ET
from src.spreads.risk import validate
from src.spreads.selector import select_candidates
from src.spreads.tape import SessionTape, trigger

log = logging.getLogger(__name__)

_MAP_RETRY = timedelta(minutes=5)


class Broker(Protocol):
    async def fetch_chain(
        self,
        *,
        symbol: str,
        trading_class: str,
        exchange: str,
        expiries: int,
        band_pct: float,
        spot_hint: float | None = None,
        sec_type: str = "IND",
    ) -> ChainSnapshot | None: ...
    async def requote(self, legs: list[ChainOption]) -> list[ChainOption]: ...
    async def spot(self) -> float | None: ...
    async def session_quote(self) -> SessionSnapshot | None: ...
    async def excess_liquidity(self) -> float | None: ...
    def broker_legs(self) -> dict[int, float]: ...


class Executor(Protocol):
    async def open(
        self, c: SpreadCandidate, contracts: int, recheck: Callable[[SpreadCandidate], SpreadVerdict]
    ) -> FillResult: ...
    async def close(
        self,
        pos: SpreadPosition,
        short_q: ChainOption | None,
        long_q: ChainOption | None,
        *,
        urgent: bool,
    ) -> FillResult: ...


class Notifier(Protocol):
    async def send(self, text: str) -> None: ...


def _right(side: str) -> Literal["C", "P"]:
    return "P" if side == "put" else "C"


class SpreadsService:
    def __init__(
        self,
        broker: Broker,
        executor: Executor,
        notifier: Notifier,
        cfg: SpreadsCfg,
        *,
        halt_path: Path,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.broker = broker
        self.executor = executor
        self.notifier = notifier
        self.cfg = cfg
        self.halt_path = halt_path
        self.now = now
        self.gex_chain: ChainSnapshot | None = None
        self.levels: GexLevels | None = None
        self.tape: SessionTape | None = None
        self.map_at: datetime | None = None
        self.map_failed_at: datetime | None = None
        self.last_entry_check: datetime | None = None
        self.last_spot: float | None = None
        self.entries_blocked: str | None = None
        self.eod_sent_for: date | None = None
        self._alerted: set[tuple[date, str]] = set()

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Reconcile open paper spreads with the broker; block entries on any mismatch."""
        mode = self.cfg.mode
        problems: list[str] = []
        if mode == "paper":
            expected = store.open_positions(mode) + store.expiring_positions(mode)
            problems = reconcile(expected, self.broker.broker_legs())
        if problems:
            self.entries_blocked = "reconcile: " + "; ".join(problems)
            await self.notifier.send(
                "[SPREADS] entries blocked — broker and spreads.db disagree:\n" + "\n".join(problems)
            )
        else:
            self.entries_blocked = None
        log.info("spreads service started (mode=%s, blocked=%s)", mode, self.entries_blocked)

    def on_disconnect(self) -> None:
        self.entries_blocked = "disconnected"

    async def alert_once(self, key: str, text: str) -> None:
        mark = (self.now().astimezone(ET).date(), key)
        if mark in self._alerted:
            return
        self._alerted.add(mark)
        await self.notifier.send(text)

    async def _guard(self, phase: str, work: Awaitable[None]) -> None:
        try:
            await work
        except Exception:
            log.exception("spreads %s phase failed", phase)
            await self.alert_once(phase, f"[SPREADS] the {phase} phase failed — see logs/spreads.log")

    # ------------------------------------------------------------------ the pass

    async def tick(self) -> None:
        now = self.now()
        et = now.astimezone(ET)
        today = et.date()
        if not is_trading_day(today):
            return
        hhmm = et.strftime("%H:%M")
        s = self.cfg.schedule
        if self._map_due(now, hhmm):
            await self._guard("map", self._build_map(now))
        if s.map_time <= hhmm < s.force_close:
            await self._guard("tape", self._sample(now))
        await self._guard("manage", self._manage(now))
        if s.entry_start <= hhmm < s.entry_end:
            await self._guard("entries", self._entries(now))
        if hhmm >= s.eod_summary and self.eod_sent_for != today:
            await self._guard("eod", self._eod(now))

    def _map_due(self, now: datetime, hhmm: str) -> bool:
        s = self.cfg.schedule
        if not (s.map_time <= hhmm < s.force_close):
            return False
        if self.map_failed_at is not None and now - self.map_failed_at < _MAP_RETRY:
            return False
        if self.map_at is None or self.map_at.astimezone(ET).date() != now.astimezone(ET).date():
            return True
        return now - self.map_at >= timedelta(minutes=s.map_refresh_minutes)

    def _entry_due(self, now: datetime) -> bool:
        if self.last_entry_check is None:
            return True
        return now - self.last_entry_check >= timedelta(minutes=self.cfg.schedule.entry_check_minutes)

    async def _traded_chain(self, spot_hint: float | None = None) -> ChainSnapshot | None:
        return await self.broker.fetch_chain(
            symbol=self.cfg.underlying,
            trading_class=self.cfg.trading_class,
            exchange=self.cfg.exchange,
            expiries=1,
            band_pct=self.cfg.selection.strike_band_pct,
            spot_hint=spot_hint,
            sec_type=self.cfg.underlying_sec_type,
        )

    async def _build_map(self, now: datetime) -> None:
        g = self.cfg.gex
        gex_chain = await self.broker.fetch_chain(
            symbol=g.symbol,
            trading_class=g.trading_class,
            exchange=g.exchange,
            expiries=g.expiries,
            band_pct=g.strike_band_pct,
            sec_type=g.sec_type,
        )
        traded = await self._traded_chain()
        if gex_chain is None or traded is None:
            self.map_failed_at = now
            self.levels = None
            await self.alert_once(
                "map_missing",
                "[SPREADS] could not build the GEX map (no chain or no index price) — no entries until it builds",
            )
            return
        self.map_failed_at = None
        self.map_at = now
        self.gex_chain = gex_chain
        self.levels = build_levels(gex_chain, traded, self.cfg, now)
        store.record_map(self.levels)
        tape = self._tape_for(now)
        if tape.day_em is None:
            # The day's FIRST expected move, from spreads.db: a restart must not swap in the
            # smaller straddle it sees later in the day.
            tape.day_em = store.first_map_em(now.astimezone(ET).date())
        await self.notifier.send(fmt_map(self.levels, self.cfg.mode))

    def _tape_for(self, now: datetime) -> SessionTape:
        today = now.astimezone(ET).date()
        if self.tape is None or self.tape.day != today:
            self.tape = SessionTape(day=today, day_em=store.first_map_em(today))
        return self.tape

    async def _sample(self, now: datetime) -> None:
        snap = await self.broker.session_quote()
        if snap is None:
            return  # the tape goes stale and the trigger stops arming (max_tape_age_seconds)
        self._tape_for(now).observe(snap)

    def _context(self, now: datetime, levels: GexLevels, excess: float | None) -> SpreadRiskContext:
        mode = self.cfg.mode
        today = now.astimezone(ET).date()
        trades, realized = store.day_stats(today, mode)
        open_count = len(store.open_positions(mode)) + len(store.expiring_positions(mode))
        return SpreadRiskContext(
            now=now,
            levels=levels,
            open_spreads=open_count,
            open_risk_usd=store.open_risk_usd(mode),
            trades_today=trades,
            realized_pnl_today_usd=realized,
            excess_liquidity_usd=excess,
            capital_usd=self.capital(),
            sides_today=store.sides_opened(today, mode),  # type: ignore[arg-type]
        )

    def capital(self) -> float:
        """The book's sizing capital: starting capital plus everything it has realized (this mode)."""
        return self.cfg.risk.starting_capital_usd + store.realized_pnl_total(self.cfg.mode)

    def _entry_context(self, side: SpreadSide, levels: GexLevels, now: datetime) -> SpreadEntryContext:
        tape = self.tape
        gap = tape.gap_pct() if tape is not None else None
        bell = datetime.combine(now.astimezone(ET).date(), time(9, 30), tzinfo=ET)
        return SpreadEntryContext(
            trigger=self.cfg.entry.trigger,
            move_em=tape.move_em(side) if tape is not None else None,
            gap_pct=gap,
            gap_day=gap is not None and abs(gap) >= self.cfg.entry.gap_day_pct,
            regime=levels.regime,
            net_gex=levels.net_gex,
            flip=levels.flip,
            call_wall=levels.call_wall,
            put_wall=levels.put_wall,
            expected_move=levels.expected_move,
            day_em=tape.day_em if tape is not None else None,
            spot=levels.spot,
            minutes_after_open=max(0, int((now - bell).total_seconds() // 60)),
        )

    async def _entries(self, now: datetime) -> None:
        if self.entries_blocked:
            return
        if self.halt_path.exists():
            await self.alert_once("halt", f"[SPREADS] halt file {self.halt_path} present — no new entries")
            return
        if self.levels is None or self.gex_chain is None:
            return
        allowed = trigger(self.tape, now, self.cfg)
        if not allowed.sides:
            log.debug("spreads trigger: %s (move %s)", allowed.reason, allowed.move_em)
            return
        if not self._entry_due(now):
            return
        self.last_entry_check = now
        chain = await self._traded_chain(spot_hint=self.levels.spot)
        if chain is None:
            return
        today = now.astimezone(ET).date()
        levels = self.levels.model_copy(
            update={
                "as_of": now,
                "spot": chain.spot,
                "regime": regime_at(self.gex_chain, chain.spot, self.levels.scale, now),
                "expected_move": expected_move(
                    chain.options, chain.spot, today, self.cfg.selection.em_straddle_factor
                ),
            }
        )
        excess = await self.broker.excess_liquidity()
        for cand in select_candidates(chain, levels, self.cfg, now, sides=allowed.sides):
            verdict = validate(cand, self._context(now, levels, excess), self.cfg)
            store.record_candidate(cand, verdict, levels.regime, now)
            if not verdict.approved:
                continue

            def recheck(fresh: SpreadCandidate) -> SpreadVerdict:
                return validate(fresh, self._context(self.now(), levels, excess), self.cfg)

            result = await self.executor.open(cand, verdict.contracts, recheck)
            store.record_order(
                spread_id=cand.spread_id, kind="open", order_ref=result.order_ref,
                ib_order_id=result.ib_order_id, perm_id=result.perm_id, filled_qty=result.filled_qty,
                price=result.price, commission=result.commission, reason=result.reason, now=now,
            )
            if result.filled_qty < 1 or result.price is None:
                log.info("spreads entry %s not filled: %s", cand.spread_id, result.reason)
                continue
            tags = self._entry_context(cand.side, levels, now)
            pos = store.open_position(
                cand, mode=self.cfg.mode, contracts=result.filled_qty, credit=result.price,
                commission=result.commission, now=now, perm_id=result.perm_id, context=tags,
            )
            await self.notifier.send(fmt_entry(pos, self.cfg.mode, tags))

    async def _manage(self, now: datetime) -> None:
        mode = self.cfg.mode
        positions = store.open_positions(mode)
        if not positions and not store.expiring_positions(mode):
            return
        spot = await self.broker.spot()
        if spot is not None:
            self.last_spot = spot
        if not positions:
            return
        legs: list[ChainOption] = []
        for p in positions:
            r = _right(p.side)
            legs.append(ChainOption(strike=p.short_strike, right=r, expiry=p.expiry, con_id=p.short_con_id))
            legs.append(ChainOption(strike=p.long_strike, right=r, expiry=p.expiry, con_id=p.long_con_id))
        book = {(round(q.strike, 2), q.right, q.expiry): q for q in await self.broker.requote(legs)}
        for p in positions:
            r = _right(p.side)
            short_q = book.get((round(p.short_strike, 2), r, p.expiry))
            long_q = book.get((round(p.long_strike, 2), r, p.expiry))
            mark, _ = debit_to_close(short_q, long_q)
            if mark is not None:
                store.note_mark(p.spread_id, mark)  # the trade log's MAE
            decision = evaluate_exit(p, short_q, long_q, spot, now, self.cfg)
            if decision is None:
                continue
            if not decision.close:
                store.mark_expiring(p.spread_id)
                await self.notifier.send(fmt_exit(p.spread_id, "left to expire", None, None, mode))
                continue
            urgent = decision.reason not in ("profit_take", "max_hold")
            result = await self.executor.close(p, short_q, long_q, urgent=urgent)
            store.record_order(
                spread_id=p.spread_id, kind="close", order_ref=result.order_ref,
                ib_order_id=result.ib_order_id, perm_id=result.perm_id, filled_qty=result.filled_qty,
                price=result.price, commission=result.commission, reason=result.reason, now=now,
            )
            if result.filled_qty < 1 or result.price is None:
                await self.alert_once(
                    f"close:{p.spread_id}:{decision.reason}",
                    f"[SPREADS] close of {p.spread_id} ({decision.reason}) did not fill — retrying every tick",
                )
                continue
            realized = store.close_position(
                p.spread_id, contracts=result.filled_qty, debit=result.price,
                commission=result.commission, reason=decision.reason, now=now,
            )
            await self.notifier.send(fmt_exit(p.spread_id, decision.reason, result.price, realized, mode))
        if now.astimezone(ET).strftime("%H:%M") >= self.cfg.schedule.force_close and not self.cfg.exits.let_expire:
            still = store.open_positions(mode)
            if still:  # a time-stop close did not fill: SPY settles in shares
                await self.alert_once(
                    "open_after_time_stop",
                    f"[SPREADS] {len(still)} {self.cfg.underlying} spread(s) still open after "
                    f"{self.cfg.schedule.force_close} ET — close by hand before 16:00 or risk assignment",
                )

    async def _eod(self, now: datetime) -> None:
        mode = self.cfg.mode
        today = now.astimezone(ET).date()
        for p in store.expiring_positions(mode):
            if p.expiry > today:
                continue
            if self.last_spot is None:
                await self.alert_once(
                    "settle", "[SPREADS] cannot settle expiring spreads: no closing spot seen — settle by hand"
                )
                continue
            debit = intrinsic_debit(p, self.last_spot)
            realized = store.close_position(
                p.spread_id, contracts=p.contracts, debit=debit, commission=0.0,
                reason="expire_worthless" if debit == 0 else "expired_itm", now=now,
            )
            await self.notifier.send(fmt_exit(p.spread_id, "expired", debit, realized, mode))
        trades, realized_today = store.day_stats(today, mode)
        await self.notifier.send(
            fmt_eod(today, mode, trades, realized_today, len(store.open_positions(mode)))
        )
        self.eod_sent_for = today


# ---------------------------------------------------------------------------- process


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def _warn_if_ledger_tracks_another_account(account: str, notifier: Notifier) -> None:
    try:
        from src.ledger.state import ledger_account
        from src.storage.db import session_scope

        with session_scope() as s:
            tracked = ledger_account(s)
    except Exception:
        log.exception("spreads: could not read the ledger's tracked account")
        return
    if tracked != account:
        await notifier.send(
            f"[SPREADS] the trade ledger tracks {tracked or 'no account yet'}, not {account}: paper "
            f"spread fills will not appear in /ledger until config/settings.yaml → ledger.account "
            f"is {account}"
        )


async def run(stop_event: asyncio.Event | None = None) -> None:
    cfg = get_config()
    stop = stop_event or asyncio.Event()
    sc = cfg.spreads
    if not sc.enabled:
        log.warning("spreads: disabled (config/spreads.yaml → enabled: false) — idling")
        await stop.wait()
        return
    if cfg.is_live:
        log.error("spreads: refusing to run with LIVE_TRADING=true — shadow/paper only in this build")
        await stop.wait()
        return

    from ib_async import IB

    from src.ibkr.connection import connect_with_retry
    from src.ledger.live import attach_live_hook
    from src.spreads.chain import IbkrSpreadsBroker
    from src.spreads.executor import SpreadExecutor

    store.init_spreads_db()
    client_id = cfg.ibkr.client_ids["spreads"]
    log.warning(
        "=" * 60 + "\n  SPREADS SERVICE  |  mode=%s  port=%s  clientId=%s\n" + "=" * 60,
        sc.mode, cfg.ibkr_port, client_id,
    )
    ib: Any = IB()

    async def connect() -> bool:
        try:
            await connect_with_retry(
                ib, cfg.ibkr.host, cfg.ibkr_port, client_id,
                timeout=cfg.ibkr.connect_timeout_seconds, label="spreads",
            )
        except Exception:
            log.exception("spreads: connect failed")
            return False
        ib.reqMarketDataType(cfg.ibkr.market_data_type)
        return True

    interval = sc.schedule.manage_interval_seconds
    while not await connect():
        if stop.is_set():
            return
        await _sleep_or_stop(stop, interval)

    account = cfg.secrets.ibkr_account or ib.managedAccounts()[0]
    broker = IbkrSpreadsBroker(ib, sc, account)
    notifier = SpreadsNotifier.from_config(cfg)
    service = SpreadsService(
        broker, SpreadExecutor(ib, broker, sc), notifier, sc, halt_path=cfg.spreads_halt_path()
    )
    if sc.mode == "paper":
        attach_live_hook(ib)
        await _warn_if_ledger_tracks_another_account(account, notifier)
    await service.start()

    while not stop.is_set():
        if not ib.isConnected():
            service.on_disconnect()
            if await connect():
                await service.start()
            else:
                await _sleep_or_stop(stop, interval)
                continue
        try:
            await service.tick()
        except Exception:
            log.exception("spreads tick failed")
            await service.alert_once("tick", "[SPREADS] a tick failed — see logs/spreads.log")
        await _sleep_or_stop(stop, interval)
    ib.disconnect()
```

`attach_live_hook` subscribes on the same `ib`. On a reconnect, ib_async keeps event subscriptions on the `IB` object, so the hook survives reconnects without being attached twice.

- [ ] **Step 4: Create `scripts/run_spreads.py`**

```python
"""Daily credit-spread service entrypoint.

Usage:
    python -m scripts.run_spreads

Connects with clientId 30 (config/settings.yaml → ibkr.client_ids.spreads). Idles when
config/spreads.yaml → enabled is false; refuses to trade when LIVE_TRADING=true. Runs until
SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.
"""

import asyncio
import signal

from src.common.logging import setup_logging
from src.spreads.service import run


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await run(stop)


def main() -> None:
    setup_logging()
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Register the service with the supervisor**

In `scripts/start.py`, anchor the `"research": {` entry of `SERVICES`. After its closing `},`, add:

```python
    "spreads": {
        "label": "spreads_service",
        "module": "scripts.run_spreads",
        "log": PROJECT_ROOT / "logs" / "spreads.log",
    },
```

Anchor `    parser.add_argument("--no-research", action="store_true", help="Skip the research worker")`. Add after it:

```python
    parser.add_argument("--no-spreads", action="store_true", help="Skip the daily credit-spread service")
```

Append to `tests/test_start_launcher.py`:

```python
def test_spreads_service_is_supervised_and_can_be_skipped():
    assert start.SERVICES["spreads"]["module"] == "scripts.run_spreads"
    args = start._build_parser().parse_args(["--no-spreads"])
    active = start._active_services(args)
    assert "spreads" not in active and "approval" in active
```

(If the file imports `start` differently, follow its existing import; the other tests there reference `start.SERVICES`.)

- [ ] **Step 6: Run the tests and the gate**

Run: `python -m pytest tests/test_spreads_service.py tests/test_start_launcher.py -q && python -m pytest -q && ruff check . && mypy src`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
ruff format src/spreads/service.py scripts/run_spreads.py scripts/start.py tests/test_spreads_service.py tests/test_start_launcher.py
git add src/spreads/service.py scripts/run_spreads.py scripts/start.py tests/test_spreads_service.py tests/test_start_launcher.py
git commit -m "feat(spreads): service loop, reconcile/reconnect, ledger hook, supervisor wiring"
```

---

### Task 14: Performance report (`scripts/spreads_report.py`)

**Files:**
- Create: `src/spreads/report.py`, `scripts/spreads_report.py`, `tests/test_spreads_report.py`

**Interfaces:**
- Consumes: `store.trade_log(mode)` (Task 9), `SpreadTradeRecord` (Task 4).
- Produces:
  - `SpreadStats` (a frozen dataclass)
  - `compute_stats(pnls: list[float]) -> SpreadStats`
  - `group_stats(rows: list[tuple[str, float]]) -> dict[str, SpreadStats]`
  - `format_stats(title, stats) -> str`
  - `TaggedTrade` (a read-only Protocol: `side`, `regime`, `trigger`, `gap_day`, `exit_reason`, `pnl_usd`, `hold_minutes`, `mae_usd`), satisfied by `SpreadTradeRecord` and the backtest's `BacktestTrade` (Task 16)
  - `tag_breakdowns(trades) -> dict[str, dict[str, SpreadStats]]`, keyed `regime`, `side`, `trigger`, `gap`, `exit`
  - `format_extras(trades) -> str` (average hold, average and worst MAE)
  - `scripts/spreads_report.py --mode {shadow,paper} [--csv PATH]` (CSV = every trade, open or closed, with every tag)

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_report.py`:

```python
from types import SimpleNamespace

import pytest

from src.spreads.report import (
    compute_stats,
    format_extras,
    format_stats,
    group_stats,
    tag_breakdowns,
)


def test_stats_expose_the_win_rate_trap() -> None:
    s = compute_stats([30.0, 30.0, -100.0, 30.0])
    assert (s.n, s.wins, s.losses) == (4, 3, 1)
    assert s.win_rate == pytest.approx(0.75)
    assert s.avg_win == pytest.approx(30.0) and s.avg_loss == pytest.approx(-100.0)
    assert s.expectancy == pytest.approx(-2.5)
    assert s.breakeven_win_rate == pytest.approx(100 / 130)
    assert s.total_pnl == pytest.approx(-10.0)
    assert s.max_drawdown == pytest.approx(100.0)


def test_empty_and_all_wins() -> None:
    e = compute_stats([])
    assert e.n == 0 and e.win_rate is None and e.expectancy is None and e.max_drawdown == 0.0
    w = compute_stats([10.0, 5.0])
    assert w.breakeven_win_rate is None and w.max_drawdown == 0.0


def test_group_and_format() -> None:
    g = group_stats([("positive", 20.0), ("negative", -50.0), ("positive", 10.0)])
    assert g["positive"].n == 2 and g["negative"].total_pnl == -50.0
    text = format_stats("shadow", compute_stats([30.0, -100.0]))
    assert "win rate 50.0%" in text and "break-even" in text and "expectancy" in text


def _t(**kw) -> SimpleNamespace:
    base = dict(side="put", regime="positive", trigger="move", gap_day=False, exit_reason="profit_take",
                pnl_usd=20.0, hold_minutes=40.0, mae_usd=5.0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_tag_breakdowns_split_negative_gamma_gap_days_and_sides() -> None:
    trades = [
        _t(),
        _t(regime="negative", pnl_usd=-60.0, exit_reason="stop_loss", mae_usd=80.0),
        _t(regime="negative", gap_day=True, side="call"),
    ]
    b = tag_breakdowns(trades)
    assert set(b) == {"regime", "side", "trigger", "gap", "exit"}
    assert b["regime"]["negative"].n == 2 and b["regime"]["negative"].total_pnl == pytest.approx(-40.0)
    assert b["gap"]["gap day"].n == 1 and b["gap"]["normal open"].n == 2
    assert b["side"]["call"].n == 1 and b["exit"]["stop_loss"].losses == 1
    extras = format_extras(trades)
    assert "avg hold 40 min" in extras and "worst MAE $80.00" in extras
    assert "avg hold n/a" in format_extras([_t(hold_minutes=None, mae_usd=None)])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_report.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/spreads/report.py`**

```python
"""Shadow/paper/backtest performance — the numbers that decide whether this strategy lives.

A high win rate is not an edge. ``breakeven_win_rate`` (|avg loss| / (avg win + |avg loss|))
is printed beside the actual win rate so the gap — or its absence — is the first thing read.
``tag_breakdowns`` splits the same numbers by the entry tags every trade carries (gamma regime,
side, trigger, gap day, exit reason), for live trade logs and backtests alike.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from statistics import mean
from typing import Protocol


@dataclass(frozen=True)
class SpreadStats:
    n: int
    wins: int
    losses: int
    win_rate: float | None
    avg_win: float | None
    avg_loss: float | None
    expectancy: float | None
    breakeven_win_rate: float | None
    total_pnl: float
    max_drawdown: float


def compute_stats(pnls: list[float]) -> SpreadStats:
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = mean(wins) if wins else None
    avg_loss = mean(losses) if losses else None
    breakeven = None
    if avg_win is not None and avg_loss is not None and avg_win + abs(avg_loss) > 0:
        breakeven = abs(avg_loss) / (avg_win + abs(avg_loss))
    equity = peak = drawdown = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return SpreadStats(
        n=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / n if n else None,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=sum(pnls) / n if n else None,
        breakeven_win_rate=breakeven,
        total_pnl=float(sum(pnls)),
        max_drawdown=drawdown,
    )


def group_stats(rows: list[tuple[str, float]]) -> dict[str, SpreadStats]:
    by: dict[str, list[float]] = defaultdict(list)
    for key, pnl in rows:
        by[key].append(pnl)
    return {k: compute_stats(v) for k, v in sorted(by.items())}


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _usd(v: float | None) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def format_stats(title: str, s: SpreadStats) -> str:
    return (
        f"{title}: {s.n} trades · win rate {_pct(s.win_rate)} (break-even {_pct(s.breakeven_win_rate)})"
        f" · avg win {_usd(s.avg_win)} · avg loss {_usd(s.avg_loss)} · expectancy {_usd(s.expectancy)}"
        f" · total {_usd(s.total_pnl)} · max drawdown {_usd(s.max_drawdown)}"
    )


class TaggedTrade(Protocol):
    """What a breakdown needs from a trade: ``SpreadTradeRecord`` and ``BacktestTrade`` both fit."""

    @property
    def side(self) -> str: ...
    @property
    def regime(self) -> str: ...
    @property
    def trigger(self) -> str: ...
    @property
    def gap_day(self) -> bool: ...
    @property
    def exit_reason(self) -> str | None: ...
    @property
    def pnl_usd(self) -> float: ...
    @property
    def hold_minutes(self) -> float | None: ...
    @property
    def mae_usd(self) -> float | None: ...


_TAGS: dict[str, Callable[[TaggedTrade], str]] = {
    "regime": lambda t: t.regime,
    "side": lambda t: t.side,
    "trigger": lambda t: t.trigger,
    "gap": lambda t: "gap day" if t.gap_day else "normal open",
    "exit": lambda t: t.exit_reason or "open",
}


def tag_breakdowns(trades: Sequence[TaggedTrade]) -> dict[str, dict[str, SpreadStats]]:
    """Stats per tag value: negative vs positive gamma, puts vs calls, gap days, exit reasons."""
    return {name: group_stats([(key(t), t.pnl_usd) for t in trades]) for name, key in _TAGS.items()}


def format_extras(trades: Sequence[TaggedTrade]) -> str:
    holds = [t.hold_minutes for t in trades if t.hold_minutes is not None]
    maes = [t.mae_usd for t in trades if t.mae_usd is not None]
    hold = f"{mean(holds):.0f} min" if holds else "n/a"
    return (
        f"avg hold {hold} · avg MAE {_usd(mean(maes) if maes else None)}"
        f" · worst MAE {_usd(max(maes) if maes else None)}"
    )
```

- [ ] **Step 4: Create `scripts/spreads_report.py`**

```python
"""Print spreads performance from data/spreads.db, split by every trade tag.

    python -m scripts.spreads_report --mode shadow
    python -m scripts.spreads_report --mode paper --csv data/spreads_paper_trades.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from src.common.schemas import SpreadTradeRecord
from src.spreads import store
from src.spreads.report import compute_stats, format_extras, format_stats, tag_breakdowns


def main() -> None:
    p = argparse.ArgumentParser(description="Daily credit-spread performance")
    p.add_argument("--mode", choices=("shadow", "paper"), default="shadow")
    p.add_argument("--csv", type=Path, default=None, help="write every trade, open or closed, with its tags")
    a = p.parse_args()
    store.init_spreads_db()
    log = store.trade_log(a.mode)
    closed = sorted((t for t in log if t.status == "closed"), key=lambda t: t.closed_at or t.opened_at)
    print(format_stats(f"{a.mode} (closed)", compute_stats([t.pnl_usd for t in closed])))
    print("  " + format_extras(closed))
    for name, groups in tag_breakdowns(closed).items():
        for value, s in groups.items():
            print(format_stats(f"  {name}={value}", s))
    if len(log) > len(closed):
        print(f"  {len(log) - len(closed)} spread(s) still open or expiring")
    if a.csv:
        a.csv.parent.mkdir(parents=True, exist_ok=True)
        with a.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(SpreadTradeRecord.model_fields))
            w.writeheader()
            w.writerows(t.model_dump(mode="json") for t in log)
        print(f"wrote {len(log)} trades to {a.csv}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests and the gate, then commit**

Run: `python -m pytest tests/test_spreads_report.py -q && ruff check . && mypy src`
Expected: PASS.

```bash
ruff format src/spreads/report.py scripts/spreads_report.py tests/test_spreads_report.py
git add src/spreads/report.py scripts/spreads_report.py tests/test_spreads_report.py
git commit -m "feat(spreads): performance report with break-even win rate and per-tag breakdowns"
```

---
### Task 15: ThetaData v3 client with a disk cache

**Files:**
- Create: `src/spreads/backtest/__init__.py`, `src/spreads/backtest/thetadata.py`, `tests/test_spreads_thetadata.py`

**Interfaces:**
- Produces: `ThetaDataClient(base_url, cache_dir, *, http=None, timeout=120.0)`, with these methods (each returns `list[dict[str, str]]`):
  - `option_quotes(symbol, expiration, day, interval="1m")`
  - `open_interest(symbol, expiration, day)`
  - `index_prices(symbol, day, interval="1m")`

The endpoints were verified against the ThetaData v3 docs on 2026-10-07. The Theta Terminal runs locally on `127.0.0.1:25503`.

| Endpoint | Required params | CSV columns used |
|---|---|---|
| `GET /v3/option/history/quote` | `symbol`, `expiration` (YYYYMMDD), `date`, `interval` | `strike`, `right`, `timestamp`, `bid`, `ask` |
| `GET /v3/option/history/open_interest` | `symbol`, `expiration`, `date` | `strike`, `right`, `open_interest` |
| `GET /v3/index/history/price` | `symbol`, `date`, `interval` | `timestamp`, `price` |

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_thetadata.py`:

```python
from __future__ import annotations

from datetime import date

import httpx
import pytest

from src.spreads.backtest.thetadata import ThetaDataClient

DAY = date(2026, 10, 7)


def _client(tmp_path, handler) -> ThetaDataClient:
    return ThetaDataClient(
        "http://127.0.0.1:25503", tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_index_prices_hit_the_v3_endpoint_as_csv_and_are_cached(tmp_path) -> None:
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, text="timestamp,price\n2026-10-07T10:00:00.000,6900.5\n")

    c = _client(tmp_path, handler)
    assert c.index_prices("SPX", DAY) == [{"timestamp": "2026-10-07T10:00:00.000", "price": "6900.5"}]
    c.index_prices("SPX", DAY)
    assert seen == [
        ("/v3/index/history/price", {"symbol": "SPX", "date": "20261007", "interval": "1m", "format": "csv"})
    ]


def test_option_endpoints(tmp_path) -> None:
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, text="strike,right\n")

    c = _client(tmp_path, handler)
    c.option_quotes("SPXW", DAY, DAY)
    c.open_interest("SPXW", DAY, DAY)
    assert seen == [
        ("/v3/option/history/quote",
         {"symbol": "SPXW", "expiration": "20261007", "date": "20261007", "interval": "1m", "format": "csv"}),
        ("/v3/option/history/open_interest",
         {"symbol": "SPXW", "expiration": "20261007", "date": "20261007", "format": "csv"}),
    ]


def test_http_errors_are_raised_and_never_cached(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="terminal not ready")
        return httpx.Response(200, text="timestamp,price\n")

    c = _client(tmp_path, handler)
    with pytest.raises(httpx.HTTPStatusError):
        c.index_prices("SPX", DAY)
    assert c.index_prices("SPX", DAY) == []
    assert calls["n"] == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_thetadata.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.backtest'`.

- [ ] **Step 3: Implement**

`src/spreads/backtest/__init__.py`:

```python
"""Offline backtest for the spreads rules over ThetaData history. Never imported by the service."""
```

`src/spreads/backtest/thetadata.py`:

```python
"""ThetaData v3 REST client (the local Theta Terminal) with an on-disk CSV cache.

Endpoints (https://thetadata.net/docs, v3; Terminal default http://127.0.0.1:25503):
  GET /v3/option/history/quote          symbol, expiration, date, interval → bid/ask per strike/right/time
  GET /v3/option/history/open_interest  symbol, expiration, date           → prior-close OI (OPRA ~06:30 ET)
  GET /v3/index/history/price           symbol, date, interval             → index price per time
Responses are requested as CSV and cached by (path, params), so a re-run never re-downloads a
day — one $80 month of Options Standard is enough to build the cache, then cancel.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import httpx


class ThetaDataClient:
    def __init__(
        self,
        base_url: str,
        cache_dir: Path,
        *,
        http: httpx.Client | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.http = http or httpx.Client(timeout=timeout)

    def _get(self, path: str, params: dict[str, str]) -> list[dict[str, str]]:
        key = hashlib.sha256(f"{path}?{urlencode(sorted(params.items()))}".encode()).hexdigest()[:32]
        cached = self.cache_dir / f"{key}.csv"
        if cached.exists():
            text = cached.read_text(encoding="utf-8")
        else:
            r = self.http.get(f"{self.base_url}{path}", params={**params, "format": "csv"})
            r.raise_for_status()
            text = r.text
            cached.write_text(text, encoding="utf-8")
        return list(csv.DictReader(io.StringIO(text)))

    def option_quotes(
        self, symbol: str, expiration: date, day: date, interval: str = "1m"
    ) -> list[dict[str, str]]:
        return self._get(
            "/v3/option/history/quote",
            {"symbol": symbol, "expiration": f"{expiration:%Y%m%d}", "date": f"{day:%Y%m%d}", "interval": interval},
        )

    def open_interest(self, symbol: str, expiration: date, day: date) -> list[dict[str, str]]:
        return self._get(
            "/v3/option/history/open_interest",
            {"symbol": symbol, "expiration": f"{expiration:%Y%m%d}", "date": f"{day:%Y%m%d}"},
        )

    def index_prices(self, symbol: str, day: date, interval: str = "1m") -> list[dict[str, str]]:
        return self._get(
            "/v3/index/history/price", {"symbol": symbol, "date": f"{day:%Y%m%d}", "interval": interval}
        )
```

- [ ] **Step 4: Run the tests and the gate, then commit**

Run: `python -m pytest tests/test_spreads_thetadata.py -q && ruff check . && mypy src`
Expected: PASS.

```bash
ruff format src/spreads/backtest/__init__.py src/spreads/backtest/thetadata.py tests/test_spreads_thetadata.py
git add src/spreads/backtest/__init__.py src/spreads/backtest/thetadata.py tests/test_spreads_thetadata.py
git commit -m "feat(spreads): ThetaData v3 client with disk cache for the backtest"
```

- [ ] **Step 5: Operator check of the symbol name (once, with the Terminal running)**

Run `curl "http://127.0.0.1:25503/v3/option/list/expirations?symbol=SPXW&format=csv" | head`.
- If it lists daily expirations, `backtest.option_symbol: "SPXW"` is right.
- If it returns nothing, try `symbol=SPX`. If that lists the dailies, set `option_symbol: "SPX"` in `config/spreads.yaml`.

Record which symbol worked in `SETUP.md` §16.

---

### Task 16: Minute replay engine and `scripts/spreads_backtest.py`

**Files:**
- Create: `src/spreads/backtest/engine.py`, `scripts/spreads_backtest.py`, `tests/test_spreads_backtest.py`

**Interfaces:**
- Consumes:
  - `ThetaDataClient` (Task 15)
  - `build_levels`, `expected_move`, `regime_at` (Task 5)
  - `select_candidates` (Task 6)
  - `SessionTape`, `trigger` (Task 6A)
  - `validate` (Task 7)
  - `evaluate_exit`, `debit_to_close`, `intrinsic_debit` (Task 8)
  - `pricing.implied_vol`, `delta`, `years_to_close`, `ET`
  - `src.common.market_hours.previous_session`
  - `compute_stats`, `format_stats`, `tag_breakdowns`, `format_extras` (Task 14)
- Produces:
  - `DayData` (a dataclass, with `prior_close: float | None = None`)
  - `BacktestTrade` (a frozen dataclass carrying the same tags as the live trade log: `trigger`, `move_em`, `gap_pct`, `gap_day`, `minutes_after_open`, `hold_minutes`, `mae_usd`)
  - `load_day(client, bt_cfg, day) -> DayData` (also reads the previous session's last index print as `prior_close`)
  - `chain_at(data, minute, symbol) -> ChainSnapshot | None`
  - `backtest_cfg(cfg) -> SpreadsCfg`
  - `with_overrides(cfg, *, profit_take_pct=None, entry_trigger=None, negative_gamma=None) -> SpreadsCfg`
  - `run_day(data, cfg, capital_usd=None) -> list[BacktestTrade]` (sizes off *capital_usd*, default `starting_capital_usd`)
  - `run_backtest(client, cfg, start, end) -> list[BacktestTrade]` (compounds each day's realized P&L into the next day's capital)
  - `scripts/spreads_backtest.py` flags `--profit-take PCT`, `--trigger {move,always}`, `--negative-gamma {allow,skip}`

- [ ] **Step 1: Write the failing tests**

`tests/test_spreads_backtest.py`:

```python
from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.common.config import get_config
from src.spreads.backtest.engine import (
    DayData,
    backtest_cfg,
    load_day,
    run_backtest,
    run_day,
    with_overrides,
)

DAY = date(2026, 10, 7)
M0931 = datetime(2026, 10, 7, 13, 31, tzinfo=UTC)
M0935 = datetime(2026, 10, 7, 13, 35, tzinfo=UTC)
M0940 = datetime(2026, 10, 7, 13, 40, tzinfo=UTC)
M0945 = datetime(2026, 10, 7, 13, 45, tzinfo=UTC)
M0950 = datetime(2026, 10, 7, 13, 50, tzinfo=UTC)
M1000 = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)
M1100 = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
M1546 = datetime(2026, 10, 7, 19, 46, tzinfo=UTC)

_BASE = get_config().spreads
# The mechanics tests pin the original rule (map 09:45, entries from 10:00, every check, both
# sides) and one contract; MOVE_CFG below replays the amendment's trigger, and the sizing tests
# lift the contract cap.
CFG = _BASE.model_copy(
    update={
        "schedule": _BASE.schedule.model_copy(
            update={"map_time": "09:45", "entry_start": "10:00", "entry_end": "13:30",
                    "entry_check_minutes": 5, "map_refresh_minutes": 60, "force_close": "15:45"}
        ),
        "entry": _BASE.entry.model_copy(update={"trigger": "always"}),
        "selection": _BASE.selection.model_copy(
            update={"sides": ["put", "call"], "width": 5.0, "min_credit_pct_of_width": 0.05,
                    "short_delta_max": 0.15, "max_leg_spread_pct": 0.30, "em_multiple": 1.0,
                    "wall_buffer_pct": 0.001, "em_straddle_factor": 1.0}
        ),
        "risk": _BASE.risk.model_copy(
            update={"max_contracts": 1, "starting_capital_usd": 100_000.0, "max_loss_pct_of_capital": 0.10,
                    "max_total_risk_pct_of_capital": 0.10, "max_daily_loss_pct_of_capital": 0.10,
                    "max_open_spreads": 2, "max_trades_per_day": 2,
                    "one_side_per_day": True, "events": [], "ex_dividend_dates": []}
        ),
        "exits": _BASE.exits.model_copy(
            update={"profit_take_pct": 50.0, "stop_debit_multiple": 2.0, "max_hold_minutes": 150,
                    "let_expire_max_debit": 0.05}
        ),
        "execution": _BASE.execution.model_copy(update={"commission_per_contract": 0.65}),
        "backtest": _BASE.backtest.model_copy(update={"trade_scale": 10.0, "fill_haircut": 0.5}),
        "gex": _BASE.gex.model_copy(update={"negative_gamma_action": "skip", "flip_buffer_pct": 0.002}),
    }
)

MORNING = {
    (6900.0, "C"): (19.9, 20.1),
    (6900.0, "P"): (19.9, 20.1),  # expected move 40 SPX points
    (6800.0, "P"): (4.8, 5.2),  # put OI carrier → put wall 6800
    (6950.0, "C"): (7.8, 8.2),  # call OI carrier → call wall 6950, positive gamma at 6900
    (6790.0, "P"): (4.0, 4.4),
    (6740.0, "P"): (1.0, 1.2),
}
OI = {(6800.0, "P"): 1_000, (6950.0, "C"): 40_000}


def _day(later: dict[datetime, dict]) -> DayData:
    quotes = {M0945: MORNING, M1000: MORNING, **later}
    return DayData(day=DAY, spot={m: 6900.0 for m in quotes}, quotes=quotes, oi=OI)


def test_backtest_cfg_restates_the_rules_in_spx_units() -> None:
    b = backtest_cfg(CFG)
    assert b.selection.width == 50.0 and b.gex.scale_to_underlying == 1.0
    assert b.exits.let_expire_max_debit == pytest.approx(0.5)
    assert b.risk.max_loss_pct_of_capital == CFG.risk.max_loss_pct_of_capital  # shares need no scaling
    assert b.enabled and b.mode == "shadow"


def test_a_day_that_takes_profit() -> None:
    later = {M1100: {(6790.0, "P"): (1.0, 1.2), (6740.0, "P"): (0.2, 0.3)}}
    (t,) = run_day(_day(later), CFG)
    assert (t.side, t.short_strike, t.long_strike) == ("put", 6790.0, 6740.0)
    assert t.entry_credit == pytest.approx(2.95)  # 3.10 mid, half-way to the 2.80 natural
    assert t.exit_reason == "profit_take" and t.exit_debit == pytest.approx(0.925)
    assert t.regime == "positive"
    assert t.pnl_usd == pytest.approx((2.95 - 0.925) * 100 / 10 - 4 * 0.65)
    assert (t.trigger, t.entry_time) == ("always", M1000)
    assert t.hold_minutes == pytest.approx(60.0) and t.mae_usd == pytest.approx(0.0)


def test_a_cash_settled_day_left_to_expire_settles_at_intrinsic() -> None:
    later = {M1546: {(6790.0, "P"): (0.02, 0.05), (6740.0, "P"): (0.0, 0.02)}}
    cash_settled = CFG.model_copy(update={"exits": CFG.exits.model_copy(update={"let_expire": True})})
    (t,) = run_day(_day(later), cash_settled)
    assert t.exit_reason == "expired" and t.exit_debit == 0.0
    assert t.pnl_usd == pytest.approx(2.95 * 100 / 10 - 2 * 0.65)


def test_a_spy_day_closes_at_the_time_stop_instead() -> None:
    later = {M1546: {(6790.0, "P"): (0.02, 0.05), (6740.0, "P"): (0.0, 0.02)}}
    (t,) = run_day(_day(later), CFG)  # exits.let_expire: false, the SPY default
    assert t.exit_reason == "time_stop"
    assert t.exit_debit == pytest.approx(0.0375)  # mid 0.025, half-way to the 0.05 natural


class FakeClient:
    def __init__(self) -> None:
        self.days: list[date] = []

    def index_prices(self, symbol, day, interval="1m"):
        self.days.append(day)
        return [{"timestamp": "2026-10-07T09:45:00.000", "price": "6900"}]

    def option_quotes(self, symbol, expiration, day, interval="1m"):
        return [
            {"strike": "6790", "right": "PUT", "timestamp": "2026-10-07T09:45:00.000", "bid": "4.0", "ask": "4.4"},
            {"strike": "6790", "right": "C", "timestamp": "2026-10-07T09:45:00.000", "bid": "0", "ask": "0"},
        ]

    def open_interest(self, symbol, expiration, day):
        return [{"strike": "6800", "right": "P", "open_interest": "1000"}]


def test_load_day_parses_et_timestamps_rights_and_drops_empty_asks() -> None:
    data = load_day(FakeClient(), CFG.backtest, DAY)
    assert data.spot == {M0945: 6900.0}
    assert data.quotes == {M0945: {(6790.0, "P"): (4.0, 4.4)}}
    assert data.oi == {(6800.0, "P"): 1000}
    assert data.prior_close == 6900.0  # the previous session's last print


def test_run_backtest_skips_non_trading_days() -> None:
    client = FakeClient()
    run_backtest(client, CFG, date(2026, 10, 9), date(2026, 10, 12))  # Fri, Sat, Sun, Mon
    # Each trading day reads its own index prices, then the previous session's for the prior close.
    assert client.days == [date(2026, 10, 9), date(2026, 10, 8), date(2026, 10, 12), date(2026, 10, 9)]


MOVE_CFG = CFG.model_copy(
    update={
        "schedule": CFG.schedule.model_copy(update={"map_time": "09:31", "entry_start": "09:35"}),
        "entry": CFG.entry.model_copy(
            update={"trigger": "move", "min_move_em": 0.5, "max_move_em": 1.5, "stall_minutes": 10,
                    "max_tape_age_seconds": 120.0, "gap_day_pct": 0.003}
        ),
    }
)


def test_the_move_trigger_sells_puts_after_a_stalled_flush() -> None:
    path = {M0931: 6935.0, M0935: 6920.0, M0940: 6900.0, M0945: 6905.0, M0950: 6902.0, M1100: 6910.0}
    quotes = {m: MORNING for m in path}
    quotes[M1100] = {(6790.0, "P"): (1.0, 1.2), (6740.0, "P"): (0.2, 0.3)}
    data = DayData(day=DAY, spot=path, quotes=quotes, oi=OI, prior_close=6935.0)
    (t,) = run_day(data, MOVE_CFG)
    assert (t.side, t.short_strike, t.long_strike, t.entry_time) == ("put", 6790.0, 6740.0, M0950)
    assert (t.trigger, t.gap_day, t.minutes_after_open) == ("move", False, 20)
    assert t.move_em == pytest.approx((6935.0 - 6902.0) / 40.0)
    assert t.exit_reason == "profit_take" and t.hold_minutes == pytest.approx(70.0)


def test_size_is_ten_percent_of_the_capital_it_is_given() -> None:
    roomy = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"max_contracts": 100})})
    later = {M1100: {(6790.0, "P"): (1.0, 1.2), (6740.0, "P"): (0.2, 0.3)}}
    (big,) = run_day(_day(later), roomy, capital_usd=100_000.0)
    (small,) = run_day(_day(later), roomy, capital_usd=10_000.0)
    # Max loss per SPY-equivalent contract = (50 − 2.95) × 100 / 10 = $470.50.
    assert (big.contracts, small.contracts) == (21, 2)
    assert big.pnl_usd == pytest.approx(21 * ((2.95 - 0.925) * 100 / 10 - 4 * 0.65))


def test_run_backtest_compounds_realized_pnl_into_the_next_days_capital(monkeypatch) -> None:
    import src.spreads.backtest.engine as engine

    seen: list[float | None] = []

    def fake_run_day(data, cfg, capital_usd=None):
        seen.append(capital_usd)
        return [SimpleNamespace(pnl_usd=500.0)]

    monkeypatch.setattr(engine, "run_day", fake_run_day)
    engine.run_backtest(FakeClient(), CFG, date(2026, 10, 9), date(2026, 10, 12))
    assert seen == [100_000.0, 100_500.0]


def test_overrides_change_only_what_is_asked() -> None:
    o = with_overrides(CFG, profit_take_pct=80.0, entry_trigger="move", negative_gamma="allow")
    assert (o.exits.profit_take_pct, o.entry.trigger, o.gex.negative_gamma_action) == (80.0, "move", "allow")
    assert o.exits.stop_debit_multiple == CFG.exits.stop_debit_multiple
    assert with_overrides(CFG) == CFG
```

Check the move-trigger numbers: the 09:31 map's straddle at 6900 is 20 + 20 = 40 SPX points (the day's yardstick). The drop from the 6935 prior close is 15 at 09:35 (0.375×, no move), 35 at 09:40 (a new low, still moving), and 33 at 09:50, ten minutes after the 09:40 low, so the put side arms (0.825×). The put boundary and fill are the same as `test_a_day_that_takes_profit`. At 11:00 the trigger is still armed, but the 11:00 chain has no straddle, so there is no expected move and no second candidate.

Check the numbers:
- Expected move = 20.0 + 20.0 = 40.
- Put boundary = min(6860, 6800 − 6.9) = 6793.1, so the short strike is 6790 and the long is 6740 (50 wide).
- Mid credit = 4.2 − 1.1 = 3.1, and natural = 4.0 − 1.2 = 2.8, so the fill is 3.1 + 0.5 × (2.8 − 3.1) = 2.95.
- At 11:00 the mid debit is 1.1 − 0.25 = 0.85, which is ≤ 1.475, so profit-take fires. Natural is 1.2 − 0.2 = 1.0, so the fill is 0.925.
- P&L = 2.025 × 100 / 10 − 2.60 = 17.65.
- The short put's IV comes out near 0.47 and its delta near −0.10, which is under the 0.15 cap.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_spreads_backtest.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.spreads.backtest.engine'`.

- [ ] **Step 3: Implement `src/spreads/backtest/engine.py`**

```python
"""Minute-by-minute replay of the live spreads rules over ThetaData history.

The backtest trades SPX dailies as a stand-in for SPY (SPY ≈ SPX/10 less accrued dividends, and SPX history
is deeper and tighter): every dollar threshold is scaled by ``backtest.trade_scale`` and P&L is
reported in SPY-equivalent dollars after SPY commissions. It reuses the service's pure modules
— gex, selector, risk, manager — so a result is a statement about the exact rules that trade.
Known differences from live: OI is the prior close (same as live), IV is backed out of each
minute's mid, fills pay ``fill_haircut`` of the mid→natural gap, 0DTE expiry only for GEX.
The entry trigger's tape is rebuilt from the minute index prices (open = the first print at or
after 09:30, a running high/low, prior close = the previous session's last print), and every
trade carries the same tags as the live trade log, so ``report.tag_breakdowns`` reads both.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, Protocol

from src.common.config import SpreadsBacktestCfg, SpreadsCfg
from src.common.market_hours import is_trading_day, previous_session
from src.common.schemas import (
    ChainOption,
    ChainSnapshot,
    EntryTrigger,
    SessionSnapshot,
    SpreadPosition,
    SpreadRiskContext,
    SpreadSide,
)
from src.spreads.gex import build_levels, expected_move, regime_at
from src.spreads.manager import debit_to_close, evaluate_exit, intrinsic_debit
from src.spreads.pricing import ET, delta, implied_vol, years_to_close
from src.spreads.risk import validate
from src.spreads.selector import select_candidates
from src.spreads.tape import SessionTape, trigger


class HistorySource(Protocol):
    def option_quotes(self, symbol: str, expiration: date, day: date, interval: str = "1m") -> list[dict[str, str]]: ...
    def open_interest(self, symbol: str, expiration: date, day: date) -> list[dict[str, str]]: ...
    def index_prices(self, symbol: str, day: date, interval: str = "1m") -> list[dict[str, str]]: ...


@dataclass
class DayData:
    day: date
    spot: dict[datetime, float]  # aware-UTC minute → index price
    quotes: dict[datetime, dict[tuple[float, str], tuple[float, float]]]  # minute → (strike, right) → (bid, ask)
    oi: dict[tuple[float, str], int]
    prior_close: float | None = None  # the previous session's last index print


@dataclass(frozen=True)
class BacktestTrade:
    day: date
    side: str
    short_strike: float
    long_strike: float
    contracts: int
    entry_time: datetime
    exit_time: datetime
    entry_credit: float  # SPX points
    exit_debit: float  # SPX points
    exit_reason: str
    regime: str
    pnl_usd: float  # SPY-equivalent, after commissions
    trigger: str
    move_em: float | None
    gap_pct: float | None
    gap_day: bool
    minutes_after_open: int
    hold_minutes: float
    mae_usd: float  # SPY-equivalent: the worst mark against the position while open


@dataclass
class _Held:
    """An open backtest position and the tags it was opened with."""

    pos: SpreadPosition
    opened: datetime
    regime: str
    move_em: float | None
    gap_pct: float | None
    gap_day: bool
    minutes_after_open: int
    worst_debit: float  # highest mid debit-to-close seen, SPX points


def _minute(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(UTC).replace(second=0, microsecond=0)


def _right(raw: str) -> str:
    return "C" if raw.strip().upper().startswith("C") else "P"


def load_day(client: HistorySource, cfg: SpreadsBacktestCfg, day: date) -> DayData:
    spot: dict[datetime, float] = {}
    for r in client.index_prices(cfg.index_symbol, day):
        price = float(r.get("price") or 0.0)
        if price > 0:
            spot[_minute(r["timestamp"])] = price
    before = [float(r.get("price") or 0.0) for r in client.index_prices(cfg.index_symbol, previous_session(day))]
    prior_close = next((p for p in reversed(before) if p > 0), None)
    quotes: dict[datetime, dict[tuple[float, str], tuple[float, float]]] = defaultdict(dict)
    for r in client.option_quotes(cfg.option_symbol, day, day):
        bid, ask = float(r.get("bid") or 0.0), float(r.get("ask") or 0.0)
        if ask <= 0:
            continue
        quotes[_minute(r["timestamp"])][(float(r["strike"]), _right(r["right"]))] = (bid, ask)
    oi = {
        (float(r["strike"]), _right(r["right"])): int(float(r["open_interest"]))
        for r in client.open_interest(cfg.option_symbol, day, day)
        if r.get("open_interest")
    }
    return DayData(day=day, spot=spot, quotes=dict(quotes), oi=oi, prior_close=prior_close)


def chain_at(data: DayData, minute: datetime, symbol: str) -> ChainSnapshot | None:
    spot = data.spot.get(minute)
    book = data.quotes.get(minute)
    if spot is None or not book:
        return None
    t = years_to_close(minute, data.day)
    options = []
    for (k, r), (bid, ask) in book.items():
        mid = (bid + ask) / 2 if ask >= bid >= 0 else None
        iv = implied_vol(mid, spot, k, t, r) if mid else None
        options.append(
            ChainOption(
                strike=k,
                right=r,  # type: ignore[arg-type]
                expiry=data.day,
                bid=bid,
                ask=ask,
                iv=iv,
                delta=delta(spot, k, t, iv, r) if iv else None,
                open_interest=data.oi.get((k, r)),
            )
        )
    return ChainSnapshot(symbol=symbol, spot=spot, as_of=minute, options=options)


def backtest_cfg(cfg: SpreadsCfg) -> SpreadsCfg:
    """The live rules restated in SPX units (every dollar/point threshold × trade_scale)."""
    k = cfg.backtest.trade_scale
    return cfg.model_copy(
        update={
            "enabled": True,
            "mode": "shadow",
            "gex": cfg.gex.model_copy(update={"scale_to_underlying": 1.0}),
            "selection": cfg.selection.model_copy(update={"width": cfg.selection.width * k}),
            # The risk caps are shares of capital, so they need no scaling; run_day passes the
            # capital itself in SPX dollars (× trade_scale).
            "risk": cfg.risk.model_copy(
                update={"min_excess_liquidity_usd": 0.0, "max_quote_age_seconds": 1e9}
            ),
            "exits": cfg.exits.model_copy(
                update={"let_expire_max_debit": cfg.exits.let_expire_max_debit * k}
            ),
        }
    )


def with_overrides(
    cfg: SpreadsCfg,
    *,
    profit_take_pct: float | None = None,
    entry_trigger: EntryTrigger | None = None,
    negative_gamma: Literal["allow", "skip"] | None = None,
) -> SpreadsCfg:
    """The backtest CLI's comparison switches (None keeps the configured value)."""
    out = cfg
    if profit_take_pct is not None:
        out = out.model_copy(update={"exits": out.exits.model_copy(update={"profit_take_pct": profit_take_pct})})
    if entry_trigger is not None:
        out = out.model_copy(update={"entry": out.entry.model_copy(update={"trigger": entry_trigger})})
    if negative_gamma is not None:
        out = out.model_copy(
            update={"gex": out.gex.model_copy(update={"negative_gamma_action": negative_gamma})}
        )
    return out


def _leg(data: DayData, minute: datetime, strike: float, right: str) -> ChainOption | None:
    bidask = data.quotes.get(minute, {}).get((strike, right))
    if bidask is None:
        return None
    return ChainOption(strike=strike, right=right, expiry=data.day, bid=bidask[0], ask=bidask[1])  # type: ignore[arg-type]


def _fill(mid: float, natural: float, haircut: float) -> float:
    return mid + haircut * (natural - mid)


def run_day(data: DayData, cfg: SpreadsCfg, capital_usd: float | None = None) -> list[BacktestTrade]:
    """One day of the live rules. *capital_usd* (default: the starting capital) sizes every trade."""
    bcfg = backtest_cfg(cfg)
    k, h = cfg.backtest.trade_scale, cfg.backtest.fill_haircut
    capital = cfg.risk.starting_capital_usd if capital_usd is None else capital_usd
    comm = cfg.execution.commission_per_contract
    s = cfg.schedule
    symbol = cfg.backtest.option_symbol
    refresh = timedelta(minutes=s.map_refresh_minutes)
    entry_every = timedelta(minutes=s.entry_check_minutes)
    minutes = sorted(m for m in data.quotes if m in data.spot)
    bell = datetime.combine(data.day, time(9, 30), tzinfo=ET)

    gex_chain: ChainSnapshot | None = None
    levels = None
    map_at: datetime | None = None
    last_entry: datetime | None = None
    tape = SessionTape(day=data.day)
    day_open: float | None = None
    high: float | None = None
    low: float | None = None
    open_: list[_Held] = []
    expiring: list[_Held] = []
    trades: list[BacktestTrade] = []
    sides_today: list[SpreadSide] = []
    realized_scaled = 0.0
    last_spot: float | None = None

    def book(held: _Held, t1: datetime, debit: float, reason: str, legs: int) -> BacktestTrade:
        pos = held.pos
        pnl = (pos.entry_credit - debit) * 100 * pos.contracts / k - (2 + legs) * comm * pos.contracts
        mae = max(0.0, held.worst_debit - pos.entry_credit) * 100 * pos.contracts / k
        return BacktestTrade(
            day=data.day, side=pos.side, short_strike=pos.short_strike, long_strike=pos.long_strike,
            contracts=pos.contracts, entry_time=held.opened, exit_time=t1, entry_credit=pos.entry_credit,
            exit_debit=debit, exit_reason=reason, regime=held.regime, pnl_usd=pnl,
            trigger=cfg.entry.trigger, move_em=held.move_em, gap_pct=held.gap_pct, gap_day=held.gap_day,
            minutes_after_open=held.minutes_after_open,
            hold_minutes=(t1 - held.opened).total_seconds() / 60.0, mae_usd=mae,
        )

    for m in minutes:
        hhmm = m.astimezone(ET).strftime("%H:%M")
        spot = data.spot[m]
        last_spot = spot
        if m >= bell:  # the session tape, as the live service would have sampled it
            day_open = spot if day_open is None else day_open
            high = spot if high is None else max(high, spot)
            low = spot if low is None else min(low, spot)
            tape.observe(
                SessionSnapshot(
                    as_of=m, last=spot, open=day_open, high=high, low=low, prior_close=data.prior_close
                )
            )
        if s.map_time <= hhmm < s.force_close and (map_at is None or m - map_at >= refresh):
            chain = chain_at(data, m, symbol)
            if chain is not None:
                gex_chain, map_at = chain, m
                levels = build_levels(chain, chain, bcfg, m)
                if tape.day_em is None:
                    tape.day_em = levels.expected_move  # the day's first expected move

        for held in list(open_):
            pos = held.pos
            right = "P" if pos.side == "put" else "C"
            sq, lq = _leg(data, m, pos.short_strike, right), _leg(data, m, pos.long_strike, right)
            mid, nat = debit_to_close(sq, lq)
            if mid is not None:
                held.worst_debit = max(held.worst_debit, mid)
            decision = evaluate_exit(pos, sq, lq, spot, m, bcfg)
            if decision is None:
                continue
            open_.remove(held)
            if not decision.close:
                expiring.append(held)
                continue
            base = mid if mid is not None else nat if nat is not None else pos.width
            debit = min(pos.width, _fill(base, nat if nat is not None else base, h))
            trade = book(held, m, debit, decision.reason, 2)
            trades.append(trade)
            realized_scaled += trade.pnl_usd * k

        if levels is None or gex_chain is None or not (s.entry_start <= hhmm < s.entry_end):
            continue
        allowed = trigger(tape, m, bcfg)
        if not allowed.sides or (last_entry is not None and m - last_entry < entry_every):
            continue
        last_entry = m
        chain = chain_at(data, m, symbol)
        if chain is None:
            continue
        lv = levels.model_copy(
            update={
                "as_of": m,
                "spot": chain.spot,
                "regime": regime_at(gex_chain, chain.spot, levels.scale, m),
                "expected_move": expected_move(
                    chain.options, chain.spot, data.day, bcfg.selection.em_straddle_factor
                ),
            }
        )
        for c in select_candidates(chain, lv, bcfg, m, sides=allowed.sides):
            held_now = open_ + expiring
            ctx = SpreadRiskContext(
                now=m,
                levels=lv,
                open_spreads=len(held_now),
                open_risk_usd=sum((x.pos.width - x.pos.entry_credit) * 100 * x.pos.contracts for x in held_now),
                trades_today=len(sides_today),
                realized_pnl_today_usd=realized_scaled,
                excess_liquidity_usd=1e12,
                capital_usd=capital * k,  # SPX-scale dollars, like every other amount here
                sides_today=list(sides_today),
            )
            v = validate(c, ctx, bcfg)
            if not v.approved:
                continue
            credit = _fill(c.credit_mid, c.credit_natural, h)
            pos = SpreadPosition(
                spread_id=c.spread_id, mode="shadow", side=c.side, expiry=c.expiry,
                short_strike=c.short_strike, long_strike=c.long_strike, width=c.width,
                contracts=v.contracts, entry_credit=credit, opened_at=m,
            )
            gap = tape.gap_pct()
            open_.append(
                _Held(
                    pos=pos, opened=m, regime=lv.regime, move_em=tape.move_em(c.side), gap_pct=gap,
                    gap_day=gap is not None and abs(gap) >= cfg.entry.gap_day_pct,
                    minutes_after_open=max(0, int((m - bell).total_seconds() // 60)),
                    worst_debit=credit,
                )
            )
            sides_today.append(c.side)

    end = minutes[-1] if minutes else None
    for held in expiring + open_:
        debit = intrinsic_debit(held.pos, last_spot) if last_spot is not None else held.pos.width
        trades.append(book(held, end or held.opened, debit, "expired", 0))
    return trades


def run_backtest(client: HistorySource, cfg: SpreadsCfg, start: date, end: date) -> list[BacktestTrade]:
    """Every trading day in [start, end]; each day sizes off the capital the days before left."""
    trades: list[BacktestTrade] = []
    capital = cfg.risk.starting_capital_usd
    day = start
    while day <= end:
        if is_trading_day(day):
            data = load_day(client, cfg.backtest, day)
            if data.quotes:
                today = run_day(data, cfg, capital)
                capital += sum(t.pnl_usd for t in today)
                trades.extend(today)
        day += timedelta(days=1)
    return trades
```

- [ ] **Step 4: Create `scripts/spreads_backtest.py`**

```python
"""Backtest the daily credit-spread rules over ThetaData history (Theta Terminal must be running).

    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --csv data/spreads_bt/june.csv
    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --profit-take 80
    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --trigger always
    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --negative-gamma skip

Prints overall stats (win rate beside break-even win rate), average hold and MAE, and the same
numbers split by regime, side, trigger, gap day and exit reason, in SPY-equivalent dollars;
optionally writes every trade with its tags to CSV. Run once per setting to compare.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import date
from pathlib import Path

from src.common.config import ROOT, get_config
from src.spreads.backtest.engine import run_backtest, with_overrides
from src.spreads.backtest.thetadata import ThetaDataClient
from src.spreads.report import compute_stats, format_extras, format_stats, tag_breakdowns


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest the daily credit-spread rules")
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--csv", type=Path, default=None)
    p.add_argument("--profit-take", type=float, default=None, help="override exits.profit_take_pct, e.g. 50 or 80")
    p.add_argument("--trigger", choices=("move", "always"), default=None, help="override entry.trigger")
    p.add_argument("--negative-gamma", choices=("allow", "skip"), default=None, help="override gex.negative_gamma_action")
    a = p.parse_args()
    cfg = with_overrides(
        get_config().spreads,
        profit_take_pct=a.profit_take,
        entry_trigger=a.trigger,
        negative_gamma=a.negative_gamma,
    )
    client = ThetaDataClient(cfg.backtest.thetadata_url, ROOT / cfg.backtest.cache_dir)
    trades = run_backtest(client, cfg, a.start, a.end)
    print(
        f"settings: profit_take {cfg.exits.profit_take_pct:g}% · trigger {cfg.entry.trigger}"
        f" · negative gamma {cfg.gex.negative_gamma_action}"
    )
    print(format_stats(f"backtest {a.start}..{a.end}", compute_stats([t.pnl_usd for t in trades])))
    start_cap = cfg.risk.starting_capital_usd
    end_cap = start_cap + sum(t.pnl_usd for t in trades)
    print(f"  capital ${start_cap:,.0f} → ${end_cap:,.0f} ({(end_cap / start_cap - 1) * 100:+.1f}%), compounding at {cfg.risk.max_loss_pct_of_capital:.0%} max loss per trade")
    print("  " + format_extras(trades))
    for name, groups in tag_breakdowns(trades).items():
        for value, s in groups.items():
            print(format_stats(f"  {name}={value}", s))
    if a.csv and trades:
        a.csv.parent.mkdir(parents=True, exist_ok=True)
        with a.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(asdict(trades[0])))
            w.writeheader()
            w.writerows(asdict(t) for t in trades)
        print(f"wrote {len(trades)} trades to {a.csv}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests and the gate, then commit**

Run: `python -m pytest tests/test_spreads_backtest.py -q && ruff check . && mypy src`
Expected: PASS.

```bash
ruff format src/spreads/backtest/engine.py scripts/spreads_backtest.py tests/test_spreads_backtest.py
git add src/spreads/backtest/engine.py scripts/spreads_backtest.py tests/test_spreads_backtest.py
git commit -m "feat(spreads): minute-replay backtest over ThetaData using the live rules"
```

---

### Task 17: Fences, docs, and the full gate

**Files:**
- Create: `tests/test_spreads_fence.py`
- Modify: `CLAUDE.md`, `ARCHITECTURE.md`, `SETUP.md`, `STATUS.md`

**Interfaces:**
- Consumes everything above. Produces no code interfaces; this task is guarantees and documentation.

- [ ] **Step 1: Write the fence tests**

`tests/test_spreads_fence.py`:

```python
"""The spreads fence: src/spreads/ is a second system beside the wheel, not a wheel module.

Same globbing rule as tests/test_web_fence.py — a hand-kept list goes stale the moment a module
is added, and a fence that silently stops covering new code is worse than none.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPREADS = sorted((ROOT / "src" / "spreads").rglob("*.py"))

FORBIDDEN_FOR_SPREADS = (
    "src.claude", "src.engine", "src.execution", "src.strategies", "src.orchestrator",
    "src.monitor", "src.notify", "src.reporting", "src.api", "src.research",
)
WHEEL_DIRS = ("engine", "execution", "strategies", "orchestrator", "monitor", "notify", "ledger", "reporting", "api")


def _imports(text: str, module: str) -> bool:
    return f"from {module}" in text or f"import {module}" in text


def test_spreads_package_exists() -> None:
    assert len(SPREADS) >= 10, "fence must cover the spreads package"


def test_spreads_imports_none_of_the_wheel_layers() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} → {m}"
        for p in SPREADS
        for m in FORBIDDEN_FOR_SPREADS
        if _imports(p.read_text(encoding="utf-8"), m)
    ]
    assert offenders == []


def test_only_the_service_reaches_the_ledger_or_the_trading_db() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in SPREADS
        if p.name != "service.py"
        and any(_imports(p.read_text(encoding="utf-8"), m) for m in ("src.ledger", "src.storage"))
    ]
    assert offenders == []


def test_no_wheel_layer_imports_spreads() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for d in WHEEL_DIRS
        for p in sorted((ROOT / "src" / d).rglob("*.py"))
        if "src.spreads" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_spreads_never_calls_reqmktdata_directly_or_sends_market_orders() -> None:
    for p in SPREADS:
        text = p.read_text(encoding="utf-8")
        assert ".reqMktData(" not in text, f"{p.relative_to(ROOT)}: use req_fresh_mkt_data"
        assert "MarketOrder" not in text, f"{p.relative_to(ROOT)}: LimitOrder only"


def test_spreads_store_has_its_own_declarative_base() -> None:
    assert "src.storage.models" not in (ROOT / "src" / "spreads" / "store.py").read_text(encoding="utf-8")
```

Run: `python -m pytest tests/test_spreads_fence.py -q`
Expected: PASS. If any assertion fails, the offending import is a real fence breach. Fix the code, not the test.

- [ ] **Step 2: `CLAUDE.md`: add the spreads fence**

Anchor: the heading `## Reference documentation`. Insert directly above it:

```markdown
### The spreads fence — `src/spreads/` is a second system, not a wheel module

`src/spreads/` (docs/superpowers/plans/2026-10-07-daily-credit-spreads.md) trades daily SPY
credit spreads in the **same IBKR account and Gateway** as the wheel, with its own process
(`scripts/run_spreads.py`, clientId 30), its own SQLite file (`data/spreads.db`, its own
`SpreadsBase`), its own config (the operator's private `config/spreads.yaml`; the repo commits
`config/spreads.example.yaml`) and its own Telegram thread. The rules:

- **Book = underlying.** `config/spreads.yaml → book_underlyings` (SPY, SPX, XSP) must never appear in
  `config/universe.yaml` — `Config._spreads_isolated` refuses the overlap at load. Positions
  carry no order tag and IBKR nets same-contract positions across clientIds, so the underlying
  is the only sound separator; order ids are unique per clientId only and are never used.
- **The wheel learns about the spreads book only through `src/common/books.py`.** Three places:
  `get_positions()` drops spreads contracts by default (only `scripts/healthcheck.py` passes
  `include_spreads=True`), the rules engine rejects `reserved_for_spreads_book`, and ledger
  ingest tags `book="spreads"`. No wheel layer imports `src.spreads`.
- **`src/spreads/risk.py::validate` is the spreads system's only gate** — deterministic, no LLM,
  run at decision time and again at send time on fresh quotes. The core invariant holds
  unchanged: nothing an LLM produces reaches a spreads order (the package imports nothing from
  `src.claude`). The entry trigger (`src/spreads/tape.py`) is deterministic too; it only decides
  *when* the chain is fetched and *which side* is offered to the gate, never a size.
- `src/spreads/` imports nothing from `src.claude`, `src.engine`, `src.execution`,
  `src.strategies`, `src.orchestrator`, `src.monitor`, `src.notify`, `src.reporting`, `src.api`,
  `src.research`; only `src/spreads/service.py` may import `src.ledger` / `src.storage`.
- At most `max_market_data_lines` (30) open lines; `market_data.chain_batch_size + 30 ≤ 95`
  is enforced at load. `req_fresh_mkt_data` only; `LimitOrder` only.
- `run()` idles when `LIVE_TRADING=true` — shadow/paper only until a separate live plan exists.

Enforced by `tests/test_spreads_fence.py`, `tests/test_wheel_spreads_isolation.py` and
`tests/test_spreads_config.py` — keep them green.
```

In the doc-update trigger table (anchor: the row starting `| **New module under \`src/reporting/\`**`), add a row after it:

```markdown
| **New module under `src/spreads/`** or a new key in `config/spreads.example.yaml` | `ARCHITECTURE.md` `src/spreads/` section · `SETUP.md` §16 if operator-facing · root `CLAUDE.md` spreads-fence section if it changes what the package may import |
```

- [ ] **Step 3: `ARCHITECTURE.md`: folder guide, config, scripts, processes**

1. In the `### config/` table, after the row starting `` | `settings.yaml → ledger:` ``, add:

```markdown
| `spreads.yaml` (private) / `spreads.example.yaml` (committed) | **Daily credit spreads** (docs/superpowers/plans/2026-10-07-daily-credit-spreads.md). `enabled` (ships `false`), `mode` (`shadow` records simulated, cost-realistic fills; `paper` places real combo orders on the paper account), the traded underlying (`SPY`, read as a stock) and GEX source (`gex.symbol: SPX`, `SPXW` dailies, × the live SPY/SPX ratio when `scale_to_underlying` is `null`), `book_underlyings` (must not appear in `universe.yaml` — refused at load), `max_market_data_lines` (30), the ET `schedule` (map 09:31, entries 09:35–13:30, time stop 15:45), `entry` (the trigger: `move` = sell only after a move of 0.5–1.5 × the day's expected move that has stalled 10 minutes, one side; `always` = the original every-check rule; `gap_day_pct` tag), `gex.negative_gamma_action` (`allow` = traded and tagged; `skip`), `selection` (width, delta cap, expected-move multiple, wall buffer, minimum credit), `risk` (sizing from the book's own capital: `starting_capital_usd` plus realized P&L, with per-trade/total/daily loss as shares of it, a `max_contracts` ceiling; trades per day, `one_side_per_day`, excess-liquidity floor, `events` with an optional `until` time, `ex_dividend_dates`), `exits` (profit take, stop, strike touch, `max_hold_minutes`, `let_expire` off for SPY), `execution` (price ladder, shadow slippage, commission) and `backtest` (ThetaData). A missing private file falls back to the example. |
```

2. In the `### src/common/` table, add a row at the end of the table:

```markdown
| `books.py` | Which book a contract belongs to: `spreads_underlyings()` / `is_spreads_underlying()`. The only way wheel code (portfolio, rules engine, ledger ingest) learns the spreads book exists. Book = underlying, because positions carry no order tag. |
```

3. Directly above the heading `` ### `src/ops/` ``, insert a new section:

```markdown
### `src/spreads/` — Daily credit spreads (a second, isolated system)

Same-day (0DTE) SPY credit spreads placed outside the day's dealer-gamma "action zones", sold
only after a stalled move (the entry rules borrowed from OPG, see the plan's Design section).
Runs as its own process (`scripts/run_spreads.py`, clientId 30) beside the wheel in the same
account, with its own database (`data/spreads.db`), config (private `config/spreads.yaml`,
template `config/spreads.example.yaml`) and Telegram thread (`TELEGRAM_THREAD_SPREADS`). See
CLAUDE.md "The spreads fence".

| File | What it does |
|---|---|
| `pricing.py` | Black-Scholes gamma/delta/price/implied vol with fractional-year time, plus the ET clock (`analytics/black_scholes.py` takes integer DTE and returns `None` at 0 DTE). |
| `gex.py` | Per-strike dealer GEX (Γ·OI·100·S²·1%, calls +, puts −), net GEX, gamma flip, call/put walls, ATM-straddle expected move; `build_levels` (SPX levels × the live SPY/SPX ratio → SPY) and `regime_at` (re-evaluates the regime at a new spot between map refreshes). |
| `selector.py` | Candidate verticals: short strike beyond both the expected move and the wall, delta cap, minimum credit, limited to the trigger's side; `refresh_candidate` reprices on fresh quotes for the send-time gate. |
| `tape.py` | `SessionTape` (open, prior close, running high/low and when each was made, the day's first expected move) and `trigger()`: sell only after a move of 0.5–1.5 × the expected move that has stalled, one side, against the most recent stalled extreme. A restart can only delay an entry. |
| `risk.py` | **The only gate in front of a spreads order.** Calendar/clock, event windows, no call spreads around SPY ex-dividend dates, regime (negative gamma traded by default), quote quality, economics, book limits (incl. one side per day), account floor; `size()` is the only place a contract count is set: 10% of the book's capital (starting capital + realized P&L) ÷ max loss per contract. |
| `manager.py` | Exit rules (profit take, stop, strike touch, maximum hold time, 15:45 time stop; SPY is never left to expire, a cash-settled book may let a far-OTM spread expire), settlement value, broker reconciliation. |
| `chain.py` | `IbkrSpreadsBroker` — the only ib_async code in the package: index spot and session stats (open/high/low/prior close), chain fetch (`reqSecDefOptParamsAsync`, band, qualify, OI/IV ticks), requote, `ExcessLiquidity` from the account stream, broker legs. Never more than `max_market_data_lines` open lines. |
| `orders.py` | Two-leg BAG open/close builders (BUY the bag, negative limit = credit) and the credit/debit price ladders. |
| `executor.py` | Shadow fills (mid − slippage − commission) or laddered paper combo orders with a send-time re-gate; cancels unfilled orders, reports partial fills. |
| `store.py` | `data/spreads.db` (separate `SpreadsBase`): GEX maps, every candidate with its verdict, positions (shadow and paper kept apart by `mode`) with their entry tags and worst mark, orders; `trade_log()` returns every trade with its tags, holding time and MAE. |
| `notify.py` | Telegram messages to the spreads thread; an entry names its gamma regime (NEGATIVE GAMMA in capitals), the move it sold against and any gap. |
| `service.py` | `SpreadsService.tick()` (map → tape → manage → entries when the trigger allows → end of day) and `run()` (connect, reconcile, reconnect after a Gateway drop, ledger live hook in paper mode). The only module that may import `src.ledger`/`src.storage`. |
| `report.py` | Win rate beside break-even win rate, expectancy, drawdown, average hold and MAE, split by regime, side, trigger, gap day and exit reason (live trade logs and backtests alike). |
| `backtest/thetadata.py` | ThetaData v3 REST client with an on-disk CSV cache. |
| `backtest/engine.py` | Minute replay of the live rules over SPX history, reported in SPY-equivalent dollars, sizing off a capital that compounds day to day. |
```

4. In the `### scripts/` table, after the row starting `` | `run_monitor.py` ``, add:

```markdown
| `run_spreads.py` | `python -m scripts.run_spreads` | Starts the daily credit-spread service (clientId 30). Supervised by `scripts.start`; idles while `config/spreads.yaml → enabled` is `false`; refuses to run with `LIVE_TRADING=true` |
| `spreads_report.py` | `python -m scripts.spreads_report --mode shadow [--csv path]` | Prints spreads performance from `data/spreads.db`, split by regime, side, trigger, gap day and exit reason; `--csv` writes every trade with its tags |
| `spreads_backtest.py` | `python -m scripts.spreads_backtest --start YYYY-MM-DD --end YYYY-MM-DD [--csv path] [--profit-take PCT] [--trigger move\|always] [--negative-gamma allow\|skip]` | Replays the spreads rules over ThetaData history (Theta Terminal must be running); the flags compare settings one run at a time |
| `spreads_combo_check.py` | `python -m scripts.spreads_combo_check --short K --long K` | One-off operator check that a spreads BAG order shows as a credit in TWS (paper only) |
```

5. Under `## Process architecture (what runs where)`, add a bullet or table row in the same style as the existing processes. Its content: "**Spreads service** (`scripts.run_spreads`, clientId 30): the daily credit-spread system. It shares the Gateway with the wheel daemons and holds at most 30 market-data lines. It places orders only in `mode: paper`. If the Gateway restarts (`src/ops/gateway_control.py`), it reconnects and re-reconciles before entering again."

6. Under `## Key invariants`, add a bullet: "The wheel and the spreads book never share an underlying, and the wheel never sees a spreads leg (`get_positions` default, the rules-engine reject `reserved_for_spreads_book`, ledger `book=\"spreads\"`)."

- [ ] **Step 4: `SETUP.md`: operator section**

Anchor: the heading `## Troubleshooting`. Insert directly above it:

```markdown
## 16. Daily credit spreads (optional)

A second, isolated system that trades same-day SPY credit spreads beside the wheel, in the same
paper account and through the same IB Gateway. It ships **disabled** and, once enabled, in
**shadow** mode: it records the trades it would have made (simulated fills with slippage and
commission) and places no orders.

### What it costs

| Item | Needed for | Cost |
|---|---|---|
| IBKR **OPRA Top of Book** (US options L1) | Live SPY/SPX option quotes | USD 1.50/mo, waived above USD 20/mo commissions. You likely already have it for the wheel |
| IBKR **Cboe index data** (SPX index value) | The SPX spot the GEX map is built around (SPY's own price comes from the stock quote the wheel already uses) | A few USD/mo. Check Client Portal → Settings → Market Data Subscriptions for the current package name and price. Without it the service logs "no index price" and builds no map |
| **ThetaData Options Standard** | The backtest only (tick-level NBBO since 2016, SPX index since 2022) | USD 80/mo. Subscribe for one month, run the backtest (it caches to `data/spreads_bt/`), then cancel |

### Enable it

1. Add `TELEGRAM_THREAD_SPREADS=<topic id>` to `.env`, or leave it empty for the main chat.
2. Copy the template: `cp config/spreads.example.yaml config/spreads.yaml` (your copy is git-ignored). Make sure your private `config/settings.yaml` has `spreads: 30` under `ibkr.client_ids`.
   - **Sizing:** the book trades as if it had `risk.starting_capital_usd` ($100,000), plus whatever it has realized since. Each spread is sized so a full loss is `risk.max_loss_pct_of_capital` (10%) of that, about 21 SPY spreads at the start. Your account's own size (about $1M on paper) is not used.
   - Fill in `risk.ex_dividend_dates` with SPY's upcoming ex-dividend dates (quarterly); no new call spreads go on those days or the day before.
3. In `config/spreads.yaml`, set `enabled: true` and keep `mode: shadow`. Restart: `./ibkr restart` (the supervisor starts `scripts.run_spreads` with the other daemons; `--no-spreads` skips it).
4. Each trading day you get, in the spreads thread: the 09:31 ET GEX map (spot, regime, expected move, put wall / flip / call wall), every entry and exit, and a 16:10 ET summary. Entries are rare by design: the system sells only after the market has moved at least half a day's expected move and stopped extending it for 10 minutes, and only on the side against that move. An entry message names its gamma regime; **NEGATIVE GAMMA** trades are taken on purpose and tagged so you can judge them later.
5. Weekly: `python -m scripts.spreads_report --mode shadow`. Compare **win rate against break-even win rate**. A 90% win rate with a 95% break-even is a losing strategy. The report repeats the numbers for negative vs positive gamma, puts vs calls, gap days and each exit reason; `--csv data/spreads_trades.csv` exports every trade with its tags.
6. Maintain `risk.events` yourself: `- {day: 2026-10-28, label: FOMC}` blocks a whole day; `- {day: 2026-08-28, until: "10:30", label: Fed chair speech}` blocks entries only until 10:30 ET. CPI and PPI print before the open, so they usually need no entry.
7. **Stop new entries instantly:** `touch data/spreads.halt`. Exits keep running. Delete the file to resume.

### Backtest before paper

1. Install and start the Theta Terminal (v3, port 25503).
2. Run the one-time symbol check: `curl "http://127.0.0.1:25503/v3/option/list/expirations?symbol=SPXW&format=csv" | head`. If that's empty, set `backtest.option_symbol: "SPX"`.
3. Run `python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --csv data/spreads_bt/june.csv`.
4. Compare one setting at a time (the cache makes reruns free):
   - profit take: `--profit-take 50` vs `--profit-take 80`
   - entry rule: `--trigger move` (sell after a stalled move) vs `--trigger always` (the original every-check rule)
   - negative gamma: `--negative-gamma allow` vs `--negative-gamma skip`

   Each run prints the settings it used, the totals, average hold and MAE, and the breakdown by regime, side, trigger, gap day and exit reason.

### Moving to paper orders

Only do this if shadow **and** backtest both show positive expectancy after costs.

1. During RTH, run `python -m scripts.spreads_combo_check --short <spot−60> --long <short−5>`. TWS must show the BAG as a **credit**. If it shows a debit, stop: see STATUS.md.
2. Make sure the trade ledger tracks the **paper** account: `config/settings.yaml → ledger.account: "<DU…>"`. Otherwise paper spread fills won't appear in `/ledger`; the service warns about this on startup.
3. Set `mode: paper` and restart. Spread fills appear in the ledger under book **Spreads**.

Live trading is not supported by this build. The service refuses to run with `LIVE_TRADING=true`.
```

In the `## Troubleshooting` table, add these rows:

```markdown
| Spreads thread says "could not build the GEX map (no chain or no index price)" | No Cboe index-data subscription for SPX, or the Gateway lost its data farm. Check Client Portal market-data subscriptions, then `python -m scripts.healthcheck` |
| Shadow mode records no spreads for days | Expected on quiet days: the move trigger sells only after a move of at least half the day's expected move has stalled. Check that the SPY session stats arrive (`python -m scripts.healthcheck`), and compare `python -m scripts.spreads_backtest ... --trigger always` to see what the original every-check rule would have done |
| Spreads thread says "entries blocked — broker and spreads.db disagree" | A paper spread was closed or changed outside the system (or a fill was missed during a Gateway restart). Compare TWS positions with `data/spreads.db → spread_positions`, fix the row or the position, then restart the spreads service |
| Config load fails with "spreads.book_underlyings [...] also appear in config/universe.yaml" | SPY, XSP or SPX is in the wheel universe (the committed example used to list SPY). Remove it: the two books may never share an underlying |
```

- [ ] **Step 5: `STATUS.md`: what is built, what needs live verification**

Anchor: the heading `## Built (2026-10-06 — trade ledger backend: CSV/Flex/live ingestion, read-only API, Google Sheets mirror)`. Insert directly above it:

```markdown
## Built (2026-10-07 — daily credit spreads: an isolated SPY 0DTE system beside the wheel)

Plan: `docs/superpowers/plans/2026-10-07-daily-credit-spreads.md`. Ships `enabled: false`, `mode: shadow`.

- `src/spreads/`: SPX-sourced GEX map (net gamma, flip, walls) plus the SPY expected move (levels scaled by the live SPY/SPX ratio), then candidate verticals beyond the action zone, then a deterministic gate (`risk.validate`, run twice), then a shadow or laddered paper BAG executor, then exit rules. Separate `data/spreads.db`, clientId 30, Telegram thread, supervisor service `spreads`.
- Entry rules borrowed from OPG's journal (2026-10-07 amendment): a session tape of the traded index and a deterministic trigger (sell only after a move of 0.5–1.5 × the day's expected move that has stalled 10 minutes, one side per day), entries from 09:35, event blocks with an optional `until` time, a 150-minute maximum hold. Negative gamma is traded by default and tagged.
- Trade log: every spread carries its entry tags (trigger and move size, gap day, gamma regime and levels, minutes after the open) plus holding time and MAE; `scripts.spreads_report` splits results by tag and exports CSV; `scripts.spreads_backtest` compares settings with `--profit-take`, `--trigger`, `--negative-gamma`.
- Sizing: every trade's max loss is 10% of the book's own capital ($100,000 plus its realized P&L, per mode), so size compounds both ways; open risk and the daily loss are capped at 10% too.
- Wheel isolation: `get_positions()` drops SPY/SPX/XSP by default (SPY also left the committed example universe); the rules engine rejects `reserved_for_spreads_book`; config load refuses any wheel/spreads underlying overlap and a market-data line budget over 95.
- Ledger: executions on spreads underlyings are tagged `book="spreads"` (labelled `Spread` in the strategy breakdown, filterable in `/ledger/trades`).
- Reporting (`scripts.spreads_report`) and a ThetaData minute-replay backtest (`scripts.spreads_backtest`).

**Needs live verification before `mode: paper`:**
- The BAG credit sign convention (BUY the bag, negative limit = credit) via `scripts/spreads_combo_check.py`. Same convention as the unverified roll combo.
- The SPX index price arriving on the paper login (the Cboe index entitlement), and the SPY session stats (open, high, low, prior close) the entry trigger reads. Without them the trigger reports `stale_tape` / `no_move` and never arms.
- SPXW open interest (generic tick 101) populated at 09:31 ET.
- `ExcessLiquidity` currency on this account (the code prefers `USD`, falls back to `BASE`).
- The ThetaData option symbol for SPX dailies (`SPXW` vs `SPX`).

**Known limitations:**
- Account margin is shared: open spreads reduce the wheel's `ExcessLiquidity` budget. Both directions are conservative.
- GEX uses prior-close open interest and the standard dealer-positioning assumption. Intraday 0DTE flow is invisible.
- Shadow fills are modelled (mid − 2 × slippage); paper fills will differ.
- The backtest trades SPX as a SPY proxy (dividend drift between SPY and SPX/10 ignored).
- SPY settles in shares: every spread is closed by the 15:45 time stop, and a close that does not fill raises an "assignment" alert to close by hand before 16:00. `risk.ex_dividend_dates` (no new call spreads the day before or of SPY's ex-dividend date) is maintained by hand.
- Expiring spreads are settled in `spreads.db` at the last observed spot. For paper mode the ledger is the source of truth.
- `risk.events` is maintained by hand.
- The entry trigger samples the index every 30 seconds, so a high or low printed between samples is seen only through IBKR's session high/low, timed to the next sample. After a restart the stall clock starts again, so a restart can delay an entry by up to `stall_minutes`.
- The thresholds (`min_move_em` 0.5, `max_move_em` 1.5, `stall_minutes` 10, `max_hold_minutes` 150) are first guesses from OPG's journal, not fitted values. The backtest and the tagged trade log are how to check them.
```

In `## Not built (deliberately deferred)`, add a bullet: "Live trading for the spreads system (`run()` refuses `LIVE_TRADING=true`), intraday flow-based GEX (needs a paid vendor feed), and web pages for the spreads book beyond the ledger filter."

- [ ] **Step 6: Run the full gate**

Run:

```bash
python -m pytest -q
ruff check .
mypy src
cd web && npm test && cd ..
```

Expected: all green. Then re-check the doc-update trigger table in `CLAUDE.md` against this branch:
- new modules: done
- new config file: done
- new scripts: done
- new storage models: these are in `src/spreads/store.py`, not `src/storage/models.py`, so no `src/storage/` doc change
- new schemas: covered by the `src/spreads/` section

- [ ] **Step 7: Commit**

```bash
ruff format tests/test_spreads_fence.py
git add tests/test_spreads_fence.py CLAUDE.md ARCHITECTURE.md SETUP.md STATUS.md
git commit -m "docs(spreads): spreads fence, folder guide, setup section, status"
```

---

## Self-review notes (for the reviewer of this plan)

| Design requirement | Task |
|---|---|
| Separate process, clientId, DB, config, Telegram thread | 1, 9, 12, 13 |
| Wheel never sees or sizes a spread leg | 2 |
| Rules-engine reject for a spreads underlying in the wheel universe | 1 |
| Config refuses wheel/spreads underlying overlap and line-budget overrun | 1 |
| Ledger `spreads` book: ingest tag, order-id collision, builder label, API, web | 3 |
| GEX map: per-strike, net, flip, walls, expected move, SPX → SPY scaling (live ratio), intraday regime | 5 |
| Strikes beyond the action zone | 6 |
| Deterministic gate run twice; sizing inside the gate | 7, 11 |
| Exits: profit take, stop, strike touch, time stop, let-expire; settlement | 8, 13 |
| Shadow mode with cost-realistic fills; paper mode with laddered combo orders | 11 |
| Reconcile, reconnect, halt file, kill entries only | 13 |
| Paper fills into the ledger, plus the ledger-account warning | 13 |
| Report with break-even win rate | 14 |
| Backtest over ThetaData | 15, 16 |
| Fences + docs | 17 |
| Live trading | Out of scope by design (`run()` refuses) |
| *Amendment:* move trigger, stall check, trend-day cap, one side per trigger | 6A (rule), 6 (`sides`), 13 (service), 16 (backtest) |
| *Amendment:* one side per day in the gate | 4 (`sides_today`), 7, 9 (`sides_opened`), 13 |
| *Amendment:* 09:31 map, 09:35 entries | 1, 7 (`test_opening_entries_start_at_0935`) |
| *Amendment:* negative gamma traded and tagged | 1 (default `allow`), 7 (`test_negative_gamma_is_traded_by_default`), 9, 12, 13 (`test_negative_gamma_is_traded_and_tagged`) |
| *Amendment:* timed event blocks | 1 (`SpreadsEventCfg`), 7 |
| *Amendment:* maximum hold time | 1, 4 (`max_hold` reason), 8, 13 (non-urgent close) |
| *Amendment:* every trade logged with tags, hold time, MAE | 4 (`SpreadEntryContext`, `SpreadTradeRecord`), 9 (`trade_log`, `note_mark`), 13, 14 (breakdowns, CSV), 16 (`BacktestTrade` tags) |
| *Amendment:* 50 vs 80 profit-take (and trigger, negative gamma) comparisons | 16 (`with_overrides`, CLI flags), 17 (SETUP) |
| *Amendment:* restart keeps the day's yardstick and cannot hurry an entry (Review Focus 6) | 6A, 9 (`first_map_em`), 13 (`test_a_restart_mid_flush_cannot_hurry_an_entry`) |
| *Amendment:* stale or missing tape never arms (Review Focus 7) | 6A (`test_missing_or_stale_inputs_never_arm`), 10 (`session_quote` → `None`) |
| *Amendment:* private/example config split | 1, 17 |
| *Operator decision:* SPY as the traded underlying (stock spot/session, live SPY/SPX ratio, never held to expiry, after-time-stop alert, no calls around ex-dividend, SPY out of the example universe) | 1, 2, 5, 7, 8, 10, 13, 17 |
| *Operator decision:* 10% of a compounding $100,000 book per trade (also total open risk and daily loss) | 1, 4 (`capital_usd`), 7 (`size`), 9 (`realized_pnl_total`), 13 (`capital()`), 16 (compounding backtest) |
| Three existing wheel tests that used SPY as a wheel ticker | 1 (Step 7b) |
