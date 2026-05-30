# IBKR Options System — Improvement Roadmap

> Independent audit of the system against `PLAN.md`, `Improvements.md`, and the `docs/PHASE*_HANDOFF.md`
> files. Every finding was verified by reading the code at the cited line — not by trusting the docs.
> **System status: paper-only.** Tier 0–2 are the explicit blockers for any live cutover.
>
> Execution model: phases run sequentially, each as its own reviewable git commit, with the quality gate
> (`pytest -q && ruff check . && mypy src`) run between phases.

---

## Honest verdict

**The architecture is genuinely good. The safety guarantees are partly fictional.**

The *design* is sound and mature for a v1 (deterministic-Python-owns-numbers / Claude-enriches-only,
SQLite-as-integration-backbone, decoupled approval→execution via DB, paper/live three-layer gating,
`qualifyContracts` before every order, graceful Claude degradation — all real in the code). But the
**Rules Engine, on which the entire safety story rests, enforces fewer than half of its documented
limits**, and the prior self-audit (`Improvements.md`) marks several critical fixes "✅ Fixed" that do not
exist in the code. The system looks safer than it is — the most dangerous failure mode for a trading
system. Solid paper-trading research tool today; **not** live-ready until Tier 0–2 close.

Grade: **strong implementation of an excellent design, undermined by enforcement gaps and doc drift.**
Recoverable in a focused pass, not a rewrite.

---

## Findings (verified)

### TIER 0 — Process / integrity
- **P1 — Project untracked in git.** Git root resolves to `/Users/ianlim` (home dir); zero project files
  tracked. No history, no rollback, no diff to review. Must be fixed before any code change.

### TIER 1 — Claimed-fixed-but-not (doc says ✅, code disagrees)
- **F1 — IV-spike trigger still dead.** `FillRow.entry_iv` column exists (`models.py:137`) but
  `executor.py:204` never sets it and `intraday.py:318` still hardcodes `entry_iv=None`. `check_iv_spike`
  can never fire.
- **F2 — Ex-div assignment trigger dead.** `intraday.py:318` hardcodes `fund_stats=None`; `check_ex_div`
  never runs. Only 2 of 4 monitor triggers (delta-drift, DTE) work.
- **F3 — Earnings blackout unenforced.** `earnings_blackout_days: 14` is advertised in config; risk engine
  still carries the original TODO (`risk_engine.py:95`). `next_earnings` never threaded into candidates.

### TIER 2 — Safety-critical correctness
- **S1 — Rules Engine enforces <50% of configured limits.** No reference anywhere in `src/` to:
  `min_iv_rank`, `max_csp_allocation_pct`, `max_pct_per_sector`, `max_correlated_exposure_pct`,
  `min_candidate_score`, `earnings_blackout_days`, `ex_dividend_assignment_guard`. Config theater.
- **S2 — Concentration/BP checks are cumulative-blind.** `validate_candidates` gates each candidate
  independently vs. current positions only (`risk_engine.py:80`, `scan.py:308`). N same-ticker candidates
  each pass; `max_new_positions_per_run` caps count, not exposure.
- **S3 — CSP sizing consumes full buying power per candidate, off margin not cash.**
  `cash_secured_put.py:66` sizes each CSP to all of `buying_power`. With S2, 3 approved CSPs ≈ 300% of
  capital. Not actually cash-secured. `max_csp_allocation_pct` (unenforced, S1) is the missing cap.
- **S4 — Second risk gate validates a stale candidate, not the fresh quote.** `approval.py:118` re-runs
  the gate on the morning's stored candidate; the fresh live quote from `executor._fetch_quote` is never
  re-scored/re-gated. Promised "gate vs. fresh quote" is half-wired.
- **S5 — `delta_missing` reject nested under `if limits:`** (`risk_engine.py:63,67`). Strategies with no
  limits dict skip the delta check entirely.

### TIER 3 — Logic / efficiency / dead code
- **L1 — Learning loop records only rejections.** `_update_memory_outcome` only ever called with
  `"user_rejected"` (`approval_service.py:95`); `filled`/`risk_rejected`/`expired` never written. Claude's
  memory is negatively biased.
- **L2 — Term-structure & skew analytics dead in production.** `scan.py:_fetch_analytics` calls
  `get_iv_stats(symbol)` without quotes → `_chain_stats` never runs (`iv.py:47`). The O3 `_infer_spot` bug
  is moot because unreachable.
- **L3 — Cross-thread `ib_async` calls.** `scan.py:257` and `intraday.py:333,342` run IB calls in
  `run_in_executor` worker threads — the exact violation `PLAN.md` warns against.
- **L4 — Sequential per-symbol scan** (`scan.py:252`) — minutes per run, no batching.
- **L5 — Stale config knobs.** `min_candidate_score` / `top_n_for_claude` never read; `select_top_candidates`
  uses `max_new_positions_per_run`.
- **L6 — `get_event_loop()` deprecation half-fixed** (`intraday.py:190,330`).

### TIER 4 — Edge cases
- **E-a — Parser brittle to surrounding prose** (`parser.py:62`, fence regex `parser.py:22`).
- **E-b — Nickel rounding on penny-pilot options** (`order_builder.py:28`).
- **E-c — CC ROC denominator uses `avg_cost`** (`covered_call.py:77`) — overstates yield after a run-up.
- **E-d — IV rank uses last *stored* IV, not live** (`iv.py:34`).
- **E-e — Roll execution undefined** — `build_limit_order` always single-leg SELL; nothing stops a `ROLL`
  candidate reaching the executor.
- **E-f — EOD realized-P&L day window mixes local and UTC dates** (`eod_report.py:40`). `_compute_realized_pnl`
  builds the day window as `datetime(today.year, today.month, today.day, tzinfo=UTC)` from a *local*
  `date.today()`. In UTC+8 (your tz), between local midnight and 08:00 the local date is ahead of the UTC
  date, so fills stored via `datetime.now(UTC)` fall outside the UTC window and realized P&L reads 0.
  Surfaced by `test_compute_realized_pnl_sums_fills` failing when run just after local midnight. Pre-existing
  (fails on the baseline commit too). Fix: anchor the EOD "day" to the market timezone (ET) consistently for
  both storage comparison and the window. Tracked in Phase D.

---

## Phases

### Phase A — Integrity & truth  ☐
1. `git init` the project as its own repo; baseline commit (`.gitignore` already present). *(P1)*
2. Reconcile `Improvements.md`: downgrade every "✅ Fixed" that isn't (F1, F2, F3) to open. *(doc drift)*

### Phase B — Make the Rules Engine real (safety-critical)  ☐
3. Enforce `min_iv_rank`, `max_pct_per_sector`, `max_correlated_exposure_pct` (add symbol→sector map to
   `universe.yaml`; start with sector, defer correlation if no data). *(S1)*
4. Make `validate_candidates` portfolio-aware: walk ranked list accumulating per-ticker exposure,
   aggregate CSP collateral (`max_csp_allocation_pct`) and remaining buying power; reject on running
   breach. *(S2, S3)*
5. Size CSPs off a cash-secured budget and remaining capital, not margin `buying_power`. *(S3, folds into 4)*
6. Re-gate the fresh quote at send time: rebuild live delta/premium/roc in `approval.py`/`executor.py` and
   re-run `validate_candidates` before `placeOrder`. *(S4)*
7. Lift the `delta is None → reject` out of `if limits:`. *(S5)*
8. Add `next_earnings` to `TradeCandidate`, populate from `FundamentalStats`, reject when
   `expiry >= next_earnings`. *(F3)*

### Phase C — Revive dead monitor triggers  ☐
9. Wire `entry_iv` end-to-end: capture `quote.iv` in `_fetch_quote`, store on `FillRow.entry_iv`, load
   latest fill IV per position in the monitor and pass into `check_all`. *(F1)*
10. Fetch/cache `FundamentalStats` per monitored underlying; pass into `check_all` for ex-div. *(F2)*

### Phase D — Correctness & learning loop  ☐
11. Write `filled` (executor), `risk_rejected` (approval re-validation), `expired` (TTL) outcomes. *(L1)*
12. Pass quotes into `get_iv_stats`; fix `_infer_spot` via put-call parity or `ticker.last`. *(L2)*
13. Honor `min_candidate_score` / `top_n_for_claude`, or delete them. *(L5)*
13b. Anchor the EOD realized-P&L day window to the market timezone (ET) for both storage comparison
    and the window bounds, so it doesn't read 0 across the local/UTC midnight gap. *(E-f)*

### Phase E — Robustness & efficiency (post-safety)  ☐
14. Replace `run_in_executor` IB calls with proper async on the loop thread. *(L3)*
15. Batch/parallelize the scan within the market-data line limit. *(L4)*
16. Harden parser to extract the first JSON span. *(E-a)*
17. Tick-size-aware limit pricing (E-b); document CC ROC choice (E-c); guard `ROLL` from the executor
    (E-e); fix remaining `get_event_loop()` (L6).

### Verification (per phase)
- `python -m pytest -q && ruff check . && mypy src` after each phase.
- New regression tests (the dead code passed CI, so coverage is the gap):
  portfolio-aware concentration; end-to-end `entry_iv` → `check_iv_spike` fires; stale-quote re-gate
  rejects an ITM-drifted quote; earnings-blackout rejection.
- For Tier 0–2: manual paper dry run of `morning_scan` + one approve→fill cycle, confirming new
  rejections actually trigger (e.g. temporarily tighten `max_csp_allocation_pct`).

### Out of scope (for now)
Backtesting engine, ML regime detection, Postgres migration, multi-leg roll execution. Revisit after
Tier 0–2 land and a few clean paper cycles.
