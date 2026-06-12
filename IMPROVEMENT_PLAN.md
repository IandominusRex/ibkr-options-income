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
| **F1** auto-close bypasses order infra | P0 *if AUTOMATED* | ✅ fixed | routed through `position_manager.close_short_position` (OrderRow/FillRow + cancel-on-timeout + idempotency) |
| **F2** no premium-collapse re-gate | P1 | ✅ fixed | `live_premium_collapse` gate using `min_live_premium_ratio` |
| **F3** malformed `entry_cutoff` kills loop | P2 | ✅ fixed | `SchedulerCfg` HH:MM validator + intraday-loop catch-all |
| **F4** entry-cutoff feature untested | — | ✅ fixed | tests in test_market_hours / test_foundation / test_position_manager |
| **F5** concurrent cross-process scans | P2 | ✅ fixed | persisted scan lease wraps `run_scan` |
| **F6** live trades on yfinance greeks | P1 | ✅ fixed | `live_greeks_required` gate in LIVE mode |
| **F7** out-of-system closes invisible | P2 | ✅ fixed | periodic reconciler + `reconcile_external_closes` records manual TWS buy-to-closes under the original `candidate_id` |
| **F8** fragile profit-take entry price | P3 | ✅ fixed | qty-weighted SELL credit net of commission (`_net_entry_credit_per_share`) |

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

### Phase 2 — before live cutover  ✅ DONE (2026-06-12)
- [x] **F2** Premium-floor in `validate_live_quote`: rejects (`live_premium_collapse`) when live mid < `min_live_premium_ratio` × approved premium (`risk_limits.yaml → live_execution`).
- [x] **F6** LIVE mode requires IBKR-sourced greeks (`live_greeks_required`) for the income delta gate; `require_ibkr_greeks_when_live` knob; paper degrade preserved.
- [x] **Circuit breakers:** `src/execution/circuit_breakers.py` — `max_auto_trades_per_day` (enforced in `process_queued_orders`) + `daily_loss_halt_pct` (auto-trips kill switch). `/halt` + `/resume` flip a persisted `execution_halted` switch checked by the order-poll loop, auto-queue, and intraday loop; closes still run while halted.
- [x] **Nightly DB backup:** `maintenance.backup_database()` (SQLite online backup + 7-snapshot rotation) in the EOD run.
- [x] **F5** Cross-process scan lease (`system_settings.acquire/release_scan_lease`) wraps `run_scan`; morning cron documented as optional/redundant.

**Gate after Phase 2:** 488 tests pass, ruff clean, mypy clean. SETUP.md §12 now carries the live-cutover safety checklist.

### Phase 3 — hygiene (any time)  🟡 PARTIAL (2026-06-12)
- [x] **God-module split (partial):** broker reconciliation extracted to `src/execution/reconciliation.py`; close mechanics already in `position_manager` (Phase 1). Profit-take/auto-close *orchestration* deliberately kept in `approval_service` (it drives Telegram notification; moving it would invert layering / need a callback redesign).
- [x] **F7 (full):** `reconcile_orphan_fills` runs periodically (recovers SELL fills missed during a mid-session reconnect) **and** `reconcile_external_closes` records manual buy-to-closes done in TWS as BUY FillRows under the original short's `candidate_id` (idempotent on IBKR `execId`) → ledger labels `closed_early` not `expired_worthless`, EOD cashflow includes the debit. End-to-end test in `test_eval.py`.
- [x] **F8:** qty-weighted entry credit net of commission (`_net_entry_credit_per_share`) replaces the last-single-fill entry price.
- [x] **Unenforced-config-key guard:** `tests/test_config_keys.py` fails if any `risk_limits.yaml` key is read by no source file (allowlist: `max_correlated_exposure_pct`, `ex_dividend_assignment_guard`).
- [ ] **Deferred:** consolidate sync/async market-data twins — the sync `_batch_quotes` is what the line-cap/cancel-discipline tests exercise, so collapsing it risks weakening that coverage without a live session to re-validate. Low value, pure hygiene.

**Gate after Phase 3:** 498 tests pass, ruff clean, mypy clean.

### Phase 4 — deliberate roadmap  🟡 IN PROGRESS
- [x] **Assignment auto-detection via position diffing** (2026-06-12): `position_snapshots` table + `src/storage/positions.py` (daily snapshot) + `src/claude/eval/assignment.py` (`detect_assignments` pure diff, `assigned_candidate_ids` orchestration). EOD now diffs prior snapshot vs current positions and feeds `reconcile(assigned_candidate_ids=…)`, replacing the manual `--assigned` flag. Residuals: option-leg-only realized P&L; CC assignment needs a prior snapshot (not detectable on the first-ever EOD). **Gate: 511 tests, ruff + mypy clean.**
- [ ] Roll execution as a two-leg combo order. *(highest value, highest risk — places real combo orders)*
- [ ] Limit-order repricing (chase logic).
- [ ] Backtest harness.

---

## Quality gate (run after every change set)
```bash
python -m pytest -q     # all pass
ruff check .            # no lint
mypy src                # no type errors
```

## Do-not-go-live until
Phase 1 (F1) and Phase 2 are complete — both now ✅ done. The SETUP.md §12 live-cutover checklist
carries the Phase 2 knobs (premium floor, live greeks, circuit breakers, kill switch, backups).
Remaining: only the sync/async market-data twin consolidation (deferred, pure hygiene) and the
≥10–20 paper-cycle validation gate. All F1–F8 findings are now resolved.
