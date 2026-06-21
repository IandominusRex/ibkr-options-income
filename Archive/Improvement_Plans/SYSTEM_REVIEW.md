# System Review & Improvement Plan

*Independent code-level review, 2026-06-12. Scope: full read of the execution path
(risk engine, executor, approval bridge, approval daemon, scan orchestrator, sender),
market-data layer, Claude runner, verdict learning loop, and all three config files.
Test suite verified: 450/450 pass in ~9 s.*

---

## Verdict

This is an unusually well-engineered hobby trading system. The core safety architecture —
a deterministic, twice-run, portfolio-aware risk gate with the LLM fenced off as
enrichment-only — is correctly designed **and** correctly implemented, and the invariant is
enforced by a test rather than by documentation alone. The audit/remediation history
(31 P0/P1 bugs found and fixed across two passes) shows real operational rigor.

The biggest residual risks are **not** in the manual-approval pipeline, which is solid.
They are in **AUTOMATED mode's profit-take auto-close path**, which bypasses the entire
order infrastructure this project so carefully built, and in a handful of gaps that only
matter once real money flows. Findings F1–F3 below are new — they are not in STATUS.md's
known-issues list.

---

## What's good

**Safety architecture (the headline strength)**
- The Rules Engine is genuinely deterministic, runs at decision time *and* send time, and
  the send-time pass re-runs the *batched, cumulative* gate (`process_queued_orders` sorts
  survivors by score and re-validates the whole pending set) — so N pending orders can't
  each claim the whole account. That's a subtle correctness point most systems miss.
- The covered-call exemption from concentration/BP budgets (`adds_new_exposure`) is
  financially correct reasoning, not a shortcut — CC premium against already-held shares
  adds no new exposure, and charging it would falsely reject exactly the right trades.
- "The fence" around the learning loop is enforced by
  `tests/test_eval_skills.py::test_skills_never_reach_the_engine`, and skill promotion is a
  human-gated file move. The guarantee survives refactors because a test, not a comment,
  owns it.
- Live trading is triple-gated (env flag + port + per-order `[CONFIRM LIVE]` tap), and the
  live quote is fetched *after* the confirm tap (P0-08 fix) — the right order of operations.

**Defense-in-depth idempotency**
- Duplicate-order protection is layered: `UniqueConstraint(approval_id)`,
  the partial unique index `uq_orders_active_candidate`, the application-level
  `has_active_order` check in *both* order-creation paths, and per-candidate SAVEPOINTs in
  the auto-queue batch. Any one layer failing still leaves the others.

**Fail-soft LLM integration**
- Claude is invoked over stdin (ARG_MAX-safe), strictly parsed, retried once, and every
  failure path degrades to the deterministic list. Claude really cannot block or corrupt
  the pipeline. Cost logging from the envelope is a nice touch.
- The verdict ledger freezes the exact signal vector Claude saw, records a deterministic
  baseline counterfactual, and the evaluator scores on held-out windows with the
  survivorship caveat stated in every report. That's honest measurement design.

**Operational hygiene**
- WAL + busy-timeout, no DB session held across network I/O (and comments explaining why),
  clientId registry, market-data batch/cancel discipline with `finally` blocks, orphan-order
  recovery and additive-only fill reconciliation on startup, a dependency-free holiday-aware
  market calendar.
- Documentation is the best part: STATUS.md candidly lists what is *not* built and what is
  only mock-verified, and the doc-update rule is enforced by a hook. A reader of
  ARCHITECTURE.md gets an accurate picture — rare.
- 450 tests in 9 seconds means the suite actually gets run.

---

## What's bad — new findings (not in STATUS.md)

### F1 · The AUTOMATED-mode auto-close path bypasses the entire order infrastructure
**Severity: P1 now (paper, MANUAL default) — P0 the moment AUTOMATED mode is used.**

`_auto_close_position` (src/notify/approval_service.py:712) calls `ib_exec.placeOrder`
directly. Unlike every other order in the system, it:

1. **Never cancels on timeout.** It waits `fill_timeout_minutes`, then just reports. The
   DAY limit order stays working at IBKR. Fifteen minutes later the next intraday cycle
   sees the position still short, and **places a second BUY for the full quantity**. If
   both fill, the account is net *long* calls it never wanted. (`executor.execute_candidate`
   cancels on timeout; this path forgot to.)
2. **Writes no OrderRow and no FillRow.** Consequences cascade:
   - The EOD premium cashflow (`eod_report` sums FillRows) **overstates the day** — the
     BUY debit is invisible.
   - The verdict-ledger reconciler classifies outcomes from FillRows; an auto-closed
     position has no BUY fill, so after expiry it is labeled `expired_worthless` with the
     **full premium as realized P&L** — silently corrupting the labels the entire learning
     loop trains on.
   - `/fills` and `/status` never show the close.
3. **Violates the core invariant as written.** "The Rules Engine is the only path to order
   execution" — there are now two `placeOrder` call sites, and this one skips the gate,
   the storage layer, and the idempotency guards. (Buy-to-close is risk-*reducing*, so the
   gate arguably shouldn't block it — but it must still go through the order/fill records
   and cancel discipline.)

**Fix:** route auto-closes through the same machinery as entries — create an OrderRow
(state QUEUED, a synthetic `close:` candidate or a dedicated close-order type), execute via
a shared place-monitor-cancel-record helper, write the FillRow with `action="BUY"`. Add an
idempotency check (`has_active_order`-style) keyed on the contract so a working close is
never doubled.

### F2 · The live re-gate has no premium-collapse check
**Severity: P1 — wrong-economics fills are possible.**

`validate_live_quote` checks delta drift and a sane two-sided market — but the order is
then **placed at the live mid**, whatever it is. The batch re-validation in
`process_queued_orders` re-runs ROC/yield checks against the **stored scan-time premium**,
not the live one. So a candidate approved Friday at a $2.50 premium can execute Monday at
a $0.60 mid: delta still in range, quote valid, every gate passes — and you've sold for a
quarter of what you approved. The TTL (60 min) bounds this but doesn't close it (premium
can collapse intraday on an IV crush).

**Fix:** in `validate_live_quote`, reject when the live mid is below a configurable floor
relative to the approved premium (e.g. `min_live_premium_ratio: 0.8` in risk_limits.yaml),
or recompute ROC/annualized yield from the live mid and re-apply the income gates.

### F3 · A malformed `entry_cutoff` silently kills the intraday loop forever
**Severity: P2 — robustness.**

The new (uncommitted) `is_new_entry_window` does `int(p) for p in entry_cutoff.split(":")`.
In `_intraday_scan_loop` this call sits *outside* any try block (unlike the profit-take and
scan steps, which are individually guarded). A config typo like `entry_cutoff: "3pm"`
raises `ValueError`, which propagates out of `while True` and kills the task — no restart,
no Telegram alert; profit-takes and scans just stop. `SchedulerCfg.entry_cutoff` is a bare
`str` with no validation.

**Fix:** validate the `HH:MM` format with a Pydantic validator in `SchedulerCfg` (fail loud
at startup), and wrap the intraday loop body in a catch-all like `_order_poll_loop` already
has.

### F4 · The uncommitted entry-cutoff feature has no tests
The working tree adds `is_new_entry_window` + the loop gate, but `grep is_new_entry_window
tests/` comes back empty — violating the project's own change workflow ("add/adjust tests
for the behaviour you changed"). Boundary cases worth covering: exactly 15:00, early-close
days (13:00 close < 15:00 cutoff), holiday, malformed string (after F3).

### F5 · Two processes can scan concurrently against an account-level line cap
The `scan_running` single-flight flag lives in the daemon's `bot_data` — in-process only.
The morning cron (clientId 11) and the daemon's 15-min loop (clientId 15) can both run full
chain scans at once; the ~100 market-data line cap is per *account*, not per connection, so
two concurrent 40-line batches plus the monitor's subscriptions can breach it and poison
both scans. Simplest fix: **retire the morning cron** — the 15-min loop makes it redundant.
Alternatively, a DB-level scan lock (a `system_settings` lease with a timestamp).

### F6 · Black-Scholes/yfinance greeks can gate live trades
The fallback (`_enrich_greeks_yf`) exists for paper accounts without market data — good.
But nothing downstream restricts it: in live mode, a quote whose delta came from delayed
yfinance IV passes the delta gates like any other. Quotes already carry `greeks_source`;
add a live-mode check (risk engine or strategy layer) that income candidates require
`greeks_source == "ibkr"`.

### F7 · Closes that happen outside the system are invisible
Manual buy-to-close in TWS (which the roll alerts explicitly invite, since rolls are
alert-only) writes no FillRow — so the ledger later labels those positions
`expired_worthless` and EOD cashflow drifts. The startup `_reconcile_orphan_fills` is the
right machinery in the wrong scope: make it a **periodic** sweep (it already only writes
proven fills, so running it often is safe), extend it to BUY-side executions, and match
against open ledger positions, not just SUBMITTED orders. This also closes STATUS.md's
"fill during mid-session reconnect" residual gap.

### F8 · Profit-take entry price is fragile
`_check_profit_takes` takes the **latest** SELL fill for the contract as the entry price:
multi-fill entries use only the last fill's price, commissions are ignored in the profit
percentage, and positions opened outside the system are silently skipped (fail-safe, at
least). Acceptable for v1; worth a qty-weighted average and a commission haircut.

---

## What's bad — structural

- **`approval_service.py` is a 1,363-line god module.** It is the Telegram UI layer, but
  it also contains real trading logic (`_auto_close_position`, `_check_profit_takes`) and
  broker reconciliation (`_reconcile_orphan_fills`). That contradicts the project's own
  folder contract ("notify = messaging"). Extract: profit-take/auto-close →
  `src/execution/position_manager.py`; fill reconciliation → `src/execution/` or
  `src/ibkr/`; keep handlers + bootstrap in notify. This also naturally fixes F1, since
  the extracted close path would be built on the executor's helpers.
- **Sync/async duplication in the market-data layer.** `_batch_quotes` /
  `_batch_quotes_async`, `_get_spot` / `_get_spot_async`, `get_option_chain_quotes` /
  `..._async` are near-identical twins. They have already drifted once (the sync spot path
  hardcodes `ib.sleep(1)` vs the async path's configurable `quote_sleep_seconds`). Keep the
  async versions; make the sync ones thin `ib.run(...)` wrappers.
- **No circuit breakers for AUTOMATED mode.** The cumulative gates bound *exposure*, but
  nothing bounds *activity or losses*: no max auto-trades per day, no daily realized-loss
  halt, no `/halt` master kill switch (only `/mode`, which a user must think to use).
  Standard kit for any auto-trading loop; should exist before AUTOMATED is used in anger,
  even on paper.
- **No DB backup story.** `data/income_system.db` is the system of record — orders, fills,
  the entire labeled learning history. One corrupted file (or a fat-fingered delete) loses
  it all. A nightly `sqlite3 .backup` in the EOD run plus a 7-day rotation is ~10 lines.
- **Unenforced-config-key pattern.** `max_correlated_exposure_pct` sits in
  risk_limits.yaml looking enforced but isn't (documented, to be fair). Dangerous pattern —
  a user tuning that knob gets silent nothing. Emit a startup warning for known-unenforced
  keys, or better, a test asserting every key in risk_limits.yaml is read somewhere.

---

## Improvement plan

### Phase 1 — before any further AUTOMATED-mode paper runs
1. **Fix F1**: route auto-close through OrderRow/FillRow + cancel-on-timeout + contract-level
   idempotency. This is the one finding that can directly create unintended positions and
   it also silently corrupts the learning loop's labels.
2. **Fix F3 + F4**: validate `entry_cutoff` at config load, guard the intraday loop body,
   add `is_new_entry_window` tests — then commit the pending working-tree change.

### Phase 2 — before live cutover (add to the SETUP.md §11 gate)
3. **Fix F2**: premium-floor (or live-ROC recompute) in `validate_live_quote`.
4. **Fix F6**: live mode requires `greeks_source == "ibkr"` for gating greeks.
5. **Circuit breakers**: `max_auto_trades_per_day`, `daily_loss_halt_pct`, and a `/halt`
   command that flips a `system_settings` kill switch checked by both the order poll loop
   and the intraday loop.
6. **Nightly DB backup** in the EOD run.
7. **Fix F5**: retire the morning cron (preferred) or add a cross-process scan lease.

### Phase 3 — hygiene (any time)
8. Split `approval_service.py` (extract position_manager + reconciliation).
9. **Fix F7**: periodic execution sweep replacing/extending the startup-only reconciler.
10. Consolidate the sync/async market-data twins.
11. F8: qty-weighted entry price + commission-aware profit %.
12. Startup warning (or test) for unenforced config keys.

### Phase 4 — deliberate roadmap items (already correctly deferred; priority order)
13. **Roll execution as a two-leg combo order** — the monitor's alerts are wired, but acting
    on them is manual; this is the largest remaining gap between "alerted" and "managed".
14. Limit-order repricing (chase logic) — directly improves fill rate; validate on paper.
15. Assignment auto-detection via position diffing — removes the manual `--assigned` flag
    and fixes the ledger's weakest label.
16. Backtest harness — until then, treat the 10–20-paper-cycle gate as the only evidence
    the *strategy* (as opposed to the *software*) works.

---

## Bottom line

The manual pipeline (scan → gate → review → approve → re-gate → execute) is trustworthy
and better-engineered than most production trading code. The system's own documentation is
honest about its limits, which made this review easier and is itself a quality signal.
Do not run AUTOMATED mode again until F1 is fixed; do not go live until Phase 2 is done.
The live-cutover gate in SETUP.md §11 should absorb Phase 2 as explicit checklist items.
