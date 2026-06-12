# Systematic Improvement Plan

**Created:** 2026-06-12
**Sources:** [`REMEDIATION.md`](REMEDIATION.md) (pre-live audit, 2026-06-02) · [`SYSTEM_REVIEW.md`](SYSTEM_REVIEW.md) (independent code review, 2026-06-12)
**Purpose:** One tracker that reconciles both review documents against the *current* codebase and sequences the remaining work toward the live-cutover gate.

---

## Verification verdict (against current code, 2026-06-12)

### `REMEDIATION.md` — ✅ RESOLVED
All 11 P0 and 21 P1 findings are implemented and verified in the codebase. Spot-checked markers:

| Finding | Evidence in code |
|---|---|
| P0-01 double-order | `UniqueConstraint("approval_id")` on `OrderRow` (models.py:88) + `IntegrityError` handler (approval_service.py:147) |
| P0-02 orphan SUBMITTED | `_recover_orphan_orders()` on startup (approval_service.py:941, called 1359) |
| P0-03 candidate upsert | `UniqueConstraint("candidate_id")` on `CandidateRow` (models.py:37) |
| P0-05/06 monitor re-subscribe | `_on_reconnect` clears state; stores `Contract` for cancel (intraday.py) |
| P1-01/02 rolling ROC | ROC = credit/strike; collateral = strike×contracts×100 |
| P1-05 delta sign | `delta_sign_mismatch` gate (risk_engine.py:149/151) |
| P1-06 max_contracts | enforced (risk_engine.py:158) |
| P1-03 negative bid | `negative_bid_sentinel` gate (risk_engine.py:243) |
| P1-15 ARG_MAX | Claude runner uses `input=prompt` over stdin (runner.py:66/125/173) |
| P1-14 journal unique | `UniqueConstraint("entry_date")` (models.py:252) |

Baseline: **450/450 tests pass** (~9 s).

### `SYSTEM_REVIEW.md` — ❌ OPEN (F1–F8 + structural)
None of the F-findings were addressed at review time. Confirmed open against current code:

| Finding | Severity | Status | Evidence |
|---|---|---|---|
| **F1** auto-close bypasses order infra | P0 *if AUTOMATED* | ❌ open | `_auto_close_position` calls `ib_exec.placeOrder` directly (approval_service.py:744); no OrderRow/FillRow; no cancel-on-timeout |
| **F2** no premium-collapse re-gate | P1 | ❌ open | no `min_live_premium_ratio` anywhere; `validate_live_quote` checks delta only |
| **F3** malformed `entry_cutoff` kills loop | P2 | ❌ open | `is_new_entry_window` at approval_service.py:903 sits outside any try; `SchedulerCfg.entry_cutoff` is a bare `str` |
| **F4** entry-cutoff feature untested | — | ❌ open | `grep is_new_entry_window tests/` empty |
| **F5** concurrent cross-process scans | P2 | ❌ open | `scan_running` lives in in-process `bot_data` only |
| **F6** live trades on yfinance greeks | P1 | ❌ open | no downstream `greeks_source == "ibkr"` gate |
| **F7** out-of-system closes invisible | P2 | ❌ open | `_reconcile_orphan_fills` is startup-only + SUBMITTED/SELL scope |
| **F8** fragile profit-take entry price | P3 | ❌ open | uses latest single SELL fill; ignores commission/multi-fill |

---

## Phased plan

Sequencing mirrors `SYSTEM_REVIEW.md`'s own phases. Each task lists the finding it closes.

### Phase 1 — before any further AUTOMATED-mode paper runs  ✅ DONE (2026-06-12)
- [x] **F1** Route auto-close through `OrderRow`/`FillRow` + cancel-on-timeout + contract-level idempotency.
      New `src/execution/position_manager.py::close_short_position`; `_auto_close_position` rewired to a thin notify wrapper.
- [x] **F3** Validate `morning_scan`/`eod_report`/`entry_cutoff` `HH:MM` with a Pydantic validator on `SchedulerCfg` (fail loud at startup); intraday-loop body wrapped in a catch-all.
- [x] **F4** Tests added: `is_new_entry_window` boundaries (15:00 exact, early-close day, holiday, custom, malformed) in `test_market_hours.py`; `SchedulerCfg` time validation in `test_foundation.py`; close-path order/fill + idempotency + cancel-on-timeout in `test_position_manager.py`.
- [ ] Commit the pending working-tree `entry_cutoff` change together with the above (user-gated — not yet committed).

**Gate after Phase 1:** 467 tests pass, ruff clean, mypy clean. (Also excluded the deprecated `Archive/` Streamlit dashboard from ruff — it is neither packaged nor tested.)

### Phase 2 — before live cutover (fold into SETUP.md §11 gate)
- [ ] **F2** Premium-floor in `validate_live_quote`: reject when live mid < `min_live_premium_ratio` × approved premium (new key in `risk_limits.yaml`), or recompute ROC/yield from live mid.
- [ ] **F6** Live mode requires `greeks_source == "ibkr"` for gating greeks (risk engine or strategy layer).
- [ ] **Circuit breakers:** `max_auto_trades_per_day`, `daily_loss_halt_pct`, and a `/halt` command flipping a `system_settings` kill switch checked by both the order-poll loop and the intraday loop.
- [ ] **Nightly DB backup** (`sqlite3 .backup` + 7-day rotation) in the EOD run.
- [ ] **F5** Retire the morning cron (preferred) or add a cross-process scan lease in `system_settings`.

### Phase 3 — hygiene (any time)
- [ ] Split `approval_service.py` (1,363 lines): extract `position_manager` (started in Phase 1) + fill reconciliation.
- [ ] **F7** Make `_reconcile_orphan_fills` a periodic sweep; extend to BUY-side + match open ledger positions.
- [ ] Consolidate sync/async market-data twins (keep async; sync = thin `ib.run(...)` wrappers).
- [ ] **F8** Qty-weighted entry price + commission-aware profit %.
- [ ] Startup warning (or test) for unenforced `risk_limits.yaml` keys (e.g. `max_correlated_exposure_pct`).

### Phase 4 — deliberate roadmap (already correctly deferred)
- [ ] Roll execution as a two-leg combo order.
- [ ] Limit-order repricing (chase logic).
- [ ] Assignment auto-detection via position diffing.
- [ ] Backtest harness.

---

## Quality gate (run after every change set)
```bash
python -m pytest -q     # all pass
ruff check .            # no lint
mypy src                # no type errors
```

## Do-not-go-live until
F1 fixed (no more AUTOMATED runs before then) and all of Phase 2 complete and checked into the SETUP.md §11 live-cutover gate.
