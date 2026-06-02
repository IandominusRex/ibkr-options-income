# System Audit & Remediation Plan
**Date:** 2026-06-02  
**Scope:** Full pre-live audit — 6 parallel agents covering Rules Engine, Trading Logic, IBKR Integration, Execution/Telegram, Database/Data Flow, and Testing/Documentation  
**Status:** Paper-trading v1. Do NOT flip `LIVE_TRADING=true` until all P0 and the listed P1 fixes are implemented and the quality gate passes.

---

## Executive Summary

The system architecture is sound. The two-pass risk gate, TTL-gated approvals, deterministic Rules Engine, and Claude-as-enrichment pattern are all correct in design. For paper trading, the system works. However, the audit found **11 true P0 bugs** (real-money risks), **~35 P1 issues**, and a production readiness score of **38/100** before the fixes below are applied.

The most dangerous failures concentrate in three areas:

1. **Double-order execution** — A TOCTOU race on the `PENDING → APPROVED` state transition, combined with absent database unique constraints, can cause two identical orders to reach the broker when Telegram retries a callback delivery (standard Telegram behavior on slow ACK). In live trading, this means two short contracts sold on the same candidate.

2. **Rolling module economics are fiction** — Roll candidates compute ROC as `roll_credit / option_entry_premium` (~$1.30), not against the actual collateral (~$34,000). Every roll shows 60%+ ROC. Combined with roll collateral being $260 instead of $34,000, the roll `TradeCandidate` is completely wrong economically and would cause all roll candidates to clear income gates regardless of actual merit.

3. **Intraday monitor goes blind after reconnect** — `AutoReconnect` fires `_refresh_subscriptions` but never clears `self._subscriptions` first. Every TWS reconnect doubles the active market data subscriptions (subscriptions are added but never cancelled). After 2–3 reconnects the ~100-line limit is breached. The monitor appears to be running but evaluates no triggers.

---

## System Score: 58 / 100
## Production Readiness Score: 38 / 100

### By area:
| Area | Score | Key Issues |
|---|---|---|
| Rules Engine | 7/10 | No P0s; delta sign not validated; quote stale at CONFIRM LIVE |
| Trading Logic | 5.5/10 | Rolling ROC/collateral completely wrong; ATR score backwards |
| IBKR Integration | 5/10 | Double-subscribe on reconnect; unqualified cancelMktData |
| Execution Flow | 5/10 | TOCTOU double-order; orphan SUBMITTED state |
| Database/Storage | 4/10 | No unique constraints; session held across network I/O |
| Testing | 62% | buy_candidates, scan.py, connection.py untested |
| Production Readiness | 38% | No backup, no supervisor, cron timezone wrong |

---

## P0 Findings — Must Fix Before Live Trading

---

### P0-01 · TOCTOU Double-Order Race
**Files:** `src/notify/approval_service.py:89` + `src/storage/models.py`  
**Risk:** Two identical broker orders placed for the same candidate.

When Telegram's delivery acknowledgement is slow (any network hiccup), Telegram re-delivers the same callback. Both deliveries enter `_process_button`. The read-then-write pattern (`check status == PENDING` → `set APPROVED`) is not atomic — two concurrent calls can both read `PENDING` and both proceed to create `OrderRow`. This is the most dangerous bug in the system.

**Fix:**
1. Add `UniqueConstraint("candidate_id", name="uq_approvals_candidate_id")` to `ApprovalRow` — prevents a second approval row for the same candidate.
2. Add `UniqueConstraint("approval_id", name="uq_orders_approval_id")` to `OrderRow` — ensures only one order per approval, with the second insert raising `IntegrityError` and rolling back cleanly.
3. Wrap the insert in `try/except IntegrityError` in `_process_button` and return the "already approved" response.

---

### P0-02 · Orphan SUBMITTED Orders After Crash
**Files:** `src/execution/approval.py:159` + `src/execution/executor.py:264`  
**Risk:** Orders stuck in SUBMITTED state with no IB order behind them — never retried, never cancelled.

`process_queued_orders` sets `OrderState.SUBMITTED` in Phase 1 (preventing double-pickup) before calling `execute_candidate`. If the process crashes between Phase 1 commit and `ib.placeOrder`, the row stays permanently SUBMITTED with `ib_order_id = NULL`. The poll loop never revisits SUBMITTED rows. The order is invisible.

**Fix:**
On `_run_service` startup, add a recovery pass:
```python
with session_scope() as s:
    orphans = s.query(OrderRow).filter(
        OrderRow.state == OrderState.SUBMITTED,
        OrderRow.ib_order_id.is_(None)
    ).all()
    for o in orphans:
        o.state = OrderState.QUEUED
        log.warning("Recovered orphan order %s to QUEUED", o.id)
```

---

### P0-03 · No Unique Constraint on `candidates.candidate_id`
**Files:** `src/storage/models.py:36-48` + `src/orchestrator/scan.py:161`  
**Risk:** Stale `TradeCandidate` payload (wrong strike/premium/delta) retrieved for live order execution.

Every scan unconditionally does `sess.add(CandidateRow(...))`. Running `/scan` twice creates two rows with the same `candidate_id`. `_load_candidate()` uses `.first()` — whichever SQLite returns, which may be the older scan's stale data.

**Fix:**
1. Add `UniqueConstraint("candidate_id", name="uq_candidates_candidate_id")` to `CandidateRow`.
2. In `_persist_candidates()`, use `INSERT OR REPLACE` (via `merge()` or delete-then-insert with a session check).

---

### P0-04 · DB Session Held Open Across IBKR Network I/O
**Files:** `src/execution/approval.py:65-76`  
**Risk:** A single slow IBKR call holds the SQLite write lock for up to 30 seconds, blocking the morning scan and all other writers.

`process_queued_orders` opens a `session_scope()` that wraps both `get_account_snapshot(ib)` and `get_positions(ib)` — synchronous network calls to TWS. The busy-timeout is 30 seconds, meaning a slow TWS response can freeze the morning scan.

**Fix:**
Fetch IBKR data before opening the session:
```python
account_snap = get_account_snapshot(ib, acct)
positions = get_positions(ib)
with session_scope() as session:
    # use pre-fetched data
```

---

### P0-05 · Double-Subscribe on AutoReconnect — Monitor Goes Blind
**Files:** `src/monitor/intraday.py:314-326` + `src/ibkr/connection.py`  
**Risk:** After each TWS reconnect, every position gets a duplicate market data subscription. After 2–3 reconnects the ~100-line limit is breached; the monitor goes silent.

`_refresh_subscriptions` checks `pos.symbol in self._subscriptions` (the in-memory set) but then also checks `ib.tickers()`. After reconnect, `ib.tickers()` is empty (fresh connection), so the guard's second branch is `True` for all positions already in `self._subscriptions`. Every position gets subscribed again. `self._subscriptions` is never cleared on disconnect.

**Fix:**
In `on_reconnect` (or in a `_on_disconnect` handler), clear state before re-subscribing:
```python
async def _on_reconnect(self):
    self._subscriptions.clear()
    self._entry_iv.clear()
    await self._refresh_subscriptions()
```

---

### P0-06 · `cancelMktData` With Unqualified Contract — Line Leak
**Files:** `src/monitor/intraday.py:329-344`  
**Risk:** Market data subscriptions are never actually cancelled for closed positions. Lines accumulate until the ~100 cap is hit.

The unsubscribe path calls `build_option(...)` to construct a new `Option` object (no `conId`) and passes it to `ib.cancelMktData`. ib_async matches cancellations by `reqId`, not by contract equality. Since the cancellation object has no `conId` and is a different Python object from the one used to subscribe, the cancel silently no-ops.

**Fix:**
Store the original subscribed `Contract` object in `self._subscriptions`:
```python
self._subscriptions[symbol] = contract  # the qualified Contract, not just True
```
Cancel using the stored object: `ib.cancelMktData(self._subscriptions.pop(symbol))`.

---

### P0-07 · Stale Spot Price from `snapshot=True`
**Files:** `src/ibkr/market_data.py:62-69`  
**Risk:** Pre-market or stale close prices used as spot price for entire chain scan; correct strikes not found; scan aborted.

`_get_spot` uses `snapshot=True` then `ib.sleep(1)`. A snapshot returns the last cached tick, which may be hours stale (previous session close). If the market is pre-open, `ticker.marketPrice()` returns `NaN`, `_safe()` returns `None`, and the entire symbol's chain scan is aborted silently.

**Fix:**
Either use `snapshot=False` with a bounded polling loop, or fall back to `reqHistoricalData` for a last-trade bar:
```python
if math.isnan(price) or price <= 0:
    bars = ib.reqHistoricalData(stock, endDateTime="", durationStr="1 D",
                                barSizeSetting="1 day", whatToShow="TRADES",
                                useRTH=True, keepUpToDate=False)
    if bars:
        price = bars[-1].close
```

---

### P0-08 · [CONFIRM LIVE] Uses Pre-Wait Quote — Stale Limit Price at Execution
**Files:** `src/execution/executor.py:218-251`  
**Risk:** In live mode, the order's limit price is computed from a quote that may be 5 minutes old when the broker receives the order.

The execution sequence is: fetch quote → validate → build order → **wait up to 5 minutes for CONFIRM LIVE tap** → place order. The limit price computed in step 3 is baked in before the wait. If the stock moved during the wait, the order is placed at a stale price. Additionally, no re-validation of delta against the Rules Engine occurs after the confirm tap.

**Fix:**
Move `_fetch_quote`, `validate_live_quote`, and `build_limit_order` to **after** the `CONFIRM LIVE` event:
```python
# 1. Send "About to place..." message with candidate details
# 2. Register and wait for live_confirm event (timeout = confirm_timeout_seconds, e.g. 120s)
# 3. After confirmation: fetch fresh quote, validate, build order, place
```

---

### P0-09 · `buy_candidates.py` Has Zero Test Coverage
**Files:** `src/strategies/buy_candidates.py` — no test file exists  
**Risk:** Untested module in the live scan pipeline.

The entire `buy_candidates.py` — including `generate_buy_candidates`, `_iv_sub_score`, `_fundamental_sub_score`, `_technical_sub_score` — is in the daily scan pipeline and has no tests at all.

**Fix:** Add `tests/test_buy_candidates.py`.

---

### P0-10 · `scan.py` Pipeline Has No Integration Test
**Files:** `src/orchestrator/scan.py` — no test wires through it  
**Risk:** A regression in the 300-line orchestration pipeline is undetectable by the current suite.

`test_live_cutover.py` only tests `morning_scan.py` in dry-run mode (no IBKR call, no scan). `run_scan()` is never exercised end-to-end with mocked components.

**Fix:** Add an integration test for `run_scan()` with a fully mocked IB object, asserting that `CandidateRow` records are written to DB and that `send_candidates` is called.

---

### P0-11 · No Regression Test for Double-Execution Prevention
**Files:** `tests/test_execution.py` — missing test  
**Risk:** The P0 fix for double-execution (atomic SUBMITTED claim) has no test. A regression is undetectable.

The fix is the most critical safety property in the system. It must have a test.

**Fix:** Add a concurrent test that calls `process_queued_orders` twice with the same QUEUED `OrderRow` and asserts `placeOrder` is called exactly once.

---

## P1 Findings — Should Fix Before Live Trading

### P1-01 · Rolling Module ROC Denominator Is Wrong *(High business impact)*
**File:** `src/strategies/rolling.py:89-95`

Roll ROC is computed as `roll_credit / position.avg_cost`, where `avg_cost` is the original **option premium** (~$1.30). A $0.80 roll credit shows 61.5% ROC. The correct denominator is the collateral at risk: `strike × 100 × contracts` for puts (~$34,000). Every roll candidate appears to have extraordinary economics and will always clear the `min_roc_pct: 1.0` gate regardless of actual merit.

**Fix:** `roc_pct = (roll_credit / quote.strike) * 100` for put rolls; `roc_pct = (roll_credit / underlying_cost_per_share) * 100` for call rolls.

---

### P1-02 · Roll Collateral Shows $260 Instead of $34,000
**File:** `src/strategies/rolling.py:94`

`collateral = position.avg_cost * contracts * 100` — `position.avg_cost` for a short option is the entry premium received (~$1.30), giving $1.30 × 2 × 100 = $260 instead of the actual ~$34,000 collateral. Any risk report reading `TradeCandidate.collateral` from a ROLL candidate massively undercounts exposure.

**Fix:** For PUT rolls: `collateral = quote.strike * contracts * 100`. For CALL rolls: `collateral = underlying_avg_cost_per_share * contracts * 100` (requires passing the stock position into the function).

---

### P1-03 · IBKR Negative Bid Sentinel (-1.0) Produces Underpriced Orders
**Files:** `src/ibkr/market_data.py`, `src/engine/risk_engine.py:223`, `src/execution/executor.py`

IBKR uses `-1.0` as a sentinel for "no bid data". `validate_live_quote` checks `ask > 0` but not `bid >= 0`. A bid of -1.0 with ask of $2.00 gives `mid = (-1.0 + 2.0) / 2 = $0.50` — the order is placed at half the fair value, collecting far less premium.

**Fix:** In `_fetch_quote`: `if bid is not None and bid < 0: bid = None`. In `validate_live_quote`: add `if quote.bid is not None and quote.bid < 0: reasons.append("negative_bid_sentinel")`.

---

### P1-04 · `bid=0` Inconsistency — `order_builder` Rejects What `_fetch_quote` Allows
**Files:** `src/execution/order_builder.py:33`, `src/execution/executor.py:138`

`_fetch_quote` explicitly allows `bid=0.00` for far-OTM options (comment on line 138). But `build_limit_order` raises `ValueError` on `bid <= 0`. The order that passed the live gate is then rejected at build time with no user notification.

**Fix:** In `build_limit_order`, change guard to: `if quote.ask is None or quote.ask <= 0: raise ValueError(...)`. Allow `bid=0` as long as `ask > 0`; compute `mid = ask / 2`.

---

### P1-05 · Delta Sign Not Validated — Wrong-Sign Put Delta Silently Passes
**Files:** `src/engine/risk_engine.py:141-147`

IBKR reports put deltas as negative (e.g., -0.25). The risk engine uses `abs(cand.delta)`. A data error returning `delta=+0.25` on a PUT passes `abs(0.25) = 0.25` within `[0.15, 0.30]` — indistinguishable from correct data. The test fixtures in `test_execution.py` already use `delta=0.25` (positive) for CSPs, confirming the sign convention is not enforced anywhere.

**Fix:** In `validate_candidates`, add:
```python
if cand.right == OptionRight.PUT and cand.delta is not None and cand.delta > 0:
    reasons.append("delta_sign_mismatch")
if cand.right == OptionRight.CALL and cand.delta is not None and cand.delta < 0:
    reasons.append("delta_sign_mismatch")
```
Fix test fixtures to use `delta=-0.25` for CSPs.

---

### P1-06 · `max_contracts` Config Key Is Dead Code — Never Enforced
**Files:** `config/risk_limits.yaml:20-22`, `src/engine/risk_engine.py`

`cash_secured_put.max_contracts: 10` is configured but never read by the risk engine. A candidate with 15 contracts on a single CSP passes unchecked, potentially consuming a large portion of the CSP budget in one trade.

**Fix:** In `validate_candidates`, add:
```python
max_contracts = limits.get("max_contracts")
if max_contracts is not None and cand.contracts > max_contracts:
    reasons.append("contracts_exceeds_max")
```

---

### P1-07 · Stale DTE in Re-Validation at Execution Time
**Files:** `src/execution/approval.py`, `src/engine/risk_engine.py:137`

`validate_candidates` in Phase 1 re-validation uses `cand.dte` from the scan-time DB record. A Friday scan (DTE=28) processed Monday morning (actual DTE=25) passes re-validation with the stale DTE=28. The re-validation does not re-compute DTE from `cand.expiry`.

**Fix:** Before Phase 1 re-validation, recompute DTE:
```python
from datetime import date
from zoneinfo import ZoneInfo
_ET = ZoneInfo("America/New_York")
today = datetime.now(_ET).date()
cand = cand.model_copy(update={"dte": (cand.expiry - today).days})
```

---

### P1-08 · Wrong Margin/Buying Power Field for CSP Sizing
**Files:** `src/ibkr/portfolio.py:122-147`

`AccountSnapshot.buying_power` is populated from IBKR's `BuyingPower` tag, which is `AvailableFunds × 4` (Reg-T intraday) or `× 2` (overnight) for margin accounts. This overstates available capital by 2–4×. CSP collateral should be sized from `AvailableFunds` or `ExcessLiquidity` (the post-margin-requirement cushion).

**Fix:** In `get_account_snapshot`, populate `buying_power` from `AvailableFunds` or `ExcessLiquidity`, not `BuyingPower`. Document which IBKR tag is used and why.

---

### P1-09 · Reconnect Race: `_reconnecting` Flag Set Inside Coroutine
**File:** `src/ibkr/connection.py:226-238`

`_on_disconnect` fires synchronously from the event loop. It creates a task to run `_reconnect_loop()`. The `_reconnecting = True` flag is set inside the coroutine, not before task creation. If `disconnectedEvent` fires twice before the task starts, two concurrent reconnect coroutines are created.

**Fix:** Set `self._reconnecting = True` synchronously inside `_on_disconnect` before `create_task`, not inside `_reconnect_loop`.

---

### P1-10 · Infinite AutoReconnect Retry Loop
**File:** `src/ibkr/connection.py:240-270`

The reconnect loop has no maximum retry count. If TWS is down for extended maintenance, the process spins forever without alerting the operator.

**Fix:** Add configurable `max_reconnect_attempts` (default: 20). After exhausting retries, log `CRITICAL` and optionally send a Telegram alert.

---

### P1-11 · TTL Computed Once at Send Time, Not Per Approval
**File:** `src/notify/sender.py:67`

`expires_at = datetime.now(UTC) + timedelta(minutes=ttl)` is computed once before the loop. All candidates in a batch share the same absolute expiry. A user who takes 45 minutes to review 5 candidates before approving the last one finds it has 15 minutes of TTL remaining — possibly not enough for RTH execution.

**Fix:** Compute `expires_at` inside the loop for each candidate: `approval.expires_at = datetime.now(UTC) + timedelta(minutes=ttl)`.

---

### P1-12 · Telegram Send Failure Leaves Dangling PENDING Approval
**File:** `src/notify/sender.py:94-107`

If `bot.send_message` raises, the exception is caught and logged. The `ApprovalRow` is already committed as PENDING with `telegram_message_id = NULL`. The user never sees the trade. The approval sits PENDING until TTL expiry — silently cancelled with no user notification.

**Fix:** On send failure, mark the approval as `EXPIRED` (or rollback the session) before the session commits. Alternatively, commit the approval only after a successful send.

---

### P1-13 · No Telegram Notification When TTL-Null Approval Cancelled
**File:** `src/execution/approval.py:95-96`

When `expires_at = None`, the order is cancelled with `detail = "Approval missing TTL"` and logged — but no Telegram message is sent. The user approved the trade and receives no feedback.

**Fix:** After setting `OrderState.CANCELLED` for missing TTL, send a Telegram notification: `"Order CANCELLED: approval record is missing TTL. Please re-scan."`.

---

### P1-14 · Journal Duplicate Rows — No Unique on `entry_date`
**File:** `src/storage/models.py:191-202`, `src/orchestrator/eod_report.py:136`

`JournalRow` has no `UniqueConstraint("entry_date")`. Re-running the EOD script creates a second row. `_load_yesterday_unrealized()` returns whichever row `.first()` gives — potentially stale.

**Fix:** Add `UniqueConstraint("entry_date", name="uq_journal_entry_date")`. Use upsert in `_write_journal`.

---

### P1-15 · ARG_MAX Risk — Claude Prompt Passed as Shell Argument
**File:** `src/claude/runner.py:53`

The prompt is passed as `-p "<prompt>"`. Linux ARG_MAX for a single argument is ~128 KB. With a large universe and 30 days of history, the prompt can breach this, raising `OSError: Argument list too long` — silently caught, returning `[]` with no distinct warning.

**Fix:** Pass the prompt via stdin: `subprocess.run(["claude", "--output-format", "json"], input=prompt, ...)` and remove the `-p` argument. This bypasses ARG_MAX entirely.

---

### P1-16 · HV Calculated with Simple Returns Instead of Log Returns
**File:** `src/analytics/iv.py:97-100`

`pct_change()` (simple returns) is used for HV. Log returns are the standard for volatility calculation and for comparing against IBKR's IV (which uses log-normal assumptions). Simple returns overstate HV for high-move names.

**Fix:** One-line change: `pct = np.log(df["Close"] / df["Close"].shift(1)).dropna()`

---

### P1-17 · IV Percentile Unreliable With Small History (< 30 observations)
**File:** `src/analytics/iv.py:50-51`

With 5 observations, IV percentile moves in 20-point steps. The system computes and acts on percentile from as few as 3 observations. No guard for minimum history length.

**Fix:** Add `if len(history) < 30: return IVStats(..., iv_percentile=None, ...)` and document that meaningful percentile requires ≥ 60 observations.

---

### P1-18 · ATR-Based Technical Score Penalizes High-IV Stocks (Backwards)
**File:** `src/strategies/_scoring.py:26`

The technical score adds up to +10 points for *low* ATR stocks and 0 for high-ATR stocks. High-ATR stocks (NVDA, SOXL) typically have richer IV and are *better* income-selling candidates. This directly contradicts the income-selling strategy.

**Fix:** Remove the ATR contribution from `technical_score` in `_scoring.py`. ATR-based regime classification already handles this correctly in `buy_candidates.py`.

---

### P1-19 · CSP Sizing Uses `total_cash` Which Double-Counts Existing CSP Collateral
**File:** `src/strategies/cash_secured_put.py:77`

For a margin account, `TotalCashValue` includes premium from existing short puts but does not deduct the reserved collateral. Using `total_cash` can overstate available capacity.

**Fix:** Use `account.excess_liquidity` (IBKR's post-margin-requirement liquid cushion) as the CSP sizing denominator. Update `get_account_snapshot` to populate this field from the `ExcessLiquidity` tag.

---

### P1-20 · No Process Supervisor / Service Manager Documentation
**File:** `SETUP.md`  
**Category:** Production Readiness

The daemons (approval service, monitor) are documented as "run in a terminal." A terminal that closes kills the daemons: no Telegram responses, no roll alerts, no order fills.

**Fix:** Add a `systemd` unit file example or macOS `launchd` plist to `SETUP.md`. At minimum, add a restart-on-failure shell wrapper:
```bash
while true; do python -m scripts.run_approval_service; sleep 5; done
```

---

### P1-21 · Cron Timezone Instructions Incorrect for UTC Servers
**File:** `SETUP.md`

Cron times are documented as ET but cron uses the system's local timezone. A UTC server fires `45 9 * * 1-5` at 9:45 UTC = 5:45 AM ET.

**Fix:** Update the cron template to prepend `TZ=America/New_York`:
```
TZ=America/New_York
45 9 * * 1-5 cd "/path/to/IBKR Investments" && .venv/bin/python -m scripts.run_morning
15 16 * * 1-5 cd "/path/to/IBKR Investments" && .venv/bin/python -m scripts.run_eod
```

---

## P2 Findings — Correct Before Live; Fix on First Available Sprint

| # | Area | Location | Issue |
|---|---|---|---|
| 2-01 | IBKR | `intraday.py:378-402` | `pendingTickersEvent` registered *after* `_refresh_subscriptions` — ticks during startup window dropped |
| 2-02 | IBKR | `connection.py:162` | Disconnect in `__aexit__` is fragile if ib_async ever makes `disconnect()` async |
| 2-03 | IBKR | `market_data.py:155` | `genericTickList="101"` only; model Greeks rely on ib_async implicit subscription |
| 2-04 | IBKR | `intraday.py:350-372` | Ticker matched by `localSymbol` only — falls back to empty dict-miss if field absent |
| 2-05 | IBKR | `executor.py:113` | `reqMktData` in `_fetch_quote` not cancelled on `CancelledError` — line leak |
| 2-06 | IBKR | `portfolio.py:90-119` | `ib.portfolio()` vs `ib.positions()` — silently omits sub-accounts in multi-account setups |
| 2-07 | IBKR | `contracts.py:36-43` | Large `qualifyContracts` batches (>50) can hit TWS pacing limit — chunk to 50 |
| 2-08 | Exec | `approval_service.py:210` | `/scan` task not held by a strong reference — may be GC'd before completion |
| 2-09 | Exec | `executor.py:334-346` | `cancelOrder` followed by 2s sleep — cancel confirmation not awaited; fill-after-cancel possible |
| 2-10 | Exec | `formatters.py:150` | `date.today()` uses system timezone (not ET) for DTE display in `/positions` |
| 2-11 | Exec | `approval_service.py:55` | `int(telegram_chat_id)` crashes on malformed config — validate at startup |
| 2-12 | Exec | `config.py:131` | No runtime check that connected port matches `is_live` |
| 2-13 | Exec | `sender.py:134` | `send_buy_list` embeds `regime` string unescaped into MarkdownV2 — `"high_volatility"` contains underscore = Telegram parse error |
| 2-14 | Exec | `formatters.py:86` | Message truncation at character boundary can cut mid-escape-sequence — truncate at newline |
| 2-15 | DB | `models.py:191` | No unique on `journal.entry_date` — duplicate EOD runs create duplicate rows |
| 2-16 | DB | `scan.py:320` | Second scan while approvals are PENDING creates overlapping candidates and stale approval payloads |
| 2-17 | DB | `eod_report.py:99` | `date.today()` in `_build_eod_summary` uses local timezone, not ET |
| 2-18 | DB | `models.py:129` | `FillRow.action` nullable at DB level despite `Mapped[str]` non-nullable ORM type — backfill needed |
| 2-19 | DB | `runner.py:55` | No retry backoff between Claude subprocess attempts — tight-loop retries on rate-limit |
| 2-20 | DB | `memory.py:44` | Duplicate `ClaudeMemoryRow` for same candidate — outcome only back-filled to most recent |
| 2-21 | Rules | `risk_engine.py:93` | `margin_exceeded = False` when `net_liq = 0` — fails open rather than closed |
| 2-22 | Rules | `risk_engine.py:162` | No assertion that `strategy == COVERED_CALL implies right == CALL` |
| 2-23 | Rules | `order_builder.py:15` | Tick rounding: `round()` uses banker's rounding — use `math.floor(x/tick + 0.5) * tick` |
| 2-24 | Trading | `analytics/iv.py:163` | Live ATM IV from nearest expiry only — 0DTE/1DTE weekly inflates IV Rank near expiry |
| 2-25 | Trading | `strategies/rolling.py:103` | Roll breakeven uses only incremental credit — cumulative credit not tracked |
| 2-26 | Trading | `monitor/triggers.py:85` | Ex-div guard fires only at delta ≥ 0.50 — misses 0.40–0.49 delta calls on high-dividend stocks |
| 2-27 | Trading | `analytics/iv.py:201` | Skew calculation mixes expiries — compute per front-month expiry |
| 2-28 | Trading | `strategies/rolling.py:42` | Roll trigger uses stale position delta — use fresh quote delta when available |
| 2-29 | Doc | `ARCHITECTURE.md` | `triggers.py` description says "each trigger calls Claude" — wrong; Claude is called in `intraday.py::fire_alerts` |
| 2-30 | Doc | `settings.yaml` | `morning_scan` and `eod_report` share clientId 11 — add dedicated `eod: 16` to prevent concurrent collision |

---

## P3 Findings — Address in Follow-On Sprints

| # | Area | Issue |
|---|---|---|
| 3-01 | IBKR | `reqMarketDataType` not called after initial connect in monitor `run()` — config ignored |
| 3-02 | IBKR | Fixed 15% strike band doesn't cover high-IV names (NVDA 20%+ OTM can be 30-delta) |
| 3-03 | Rules | YAML null values for limit keys (e.g. `max_pct_per_ticker: null`) would cause TypeError — use `or default` |
| 3-04 | Rules | `_live_confirm_events` dict leaks entries on exception before cleanup |
| 3-05 | Rules | Stale `next_earnings` in Phase 1 re-validation — worth a comment noting the limitation |
| 3-06 | Rules | RTH deferral can silently expire overnight approvals — add Telegram notification on TTL expiry |
| 3-07 | Rules | `prob_profit = 1 - delta` is an approximation — label as `otm_probability_approx` in schema |
| 3-08 | Trading | `ADX proxy` is actually `ATR/price` — rename field to `atr_pct` to avoid confusing downstream |
| 3-09 | Trading | Earnings blackout OR condition blocks DTE<21 options expiring before earnings — remove condition (b) |
| 3-10 | Trading | Quality screen returns `None` (→ score 50) for any missing field — too generous; return `False` on negative FCF |
| 3-11 | Trading | Reddit sentiment is a momentum signal, not an income signal — consider removing or replacing with volume-only |
| 3-12 | DB | `claude_memory` table grows indefinitely — add 90-day purge in EOD script |
| 3-13 | DB | `option_quotes` table: never read by any production code path; unbounded growth |
| 3-14 | DB | `ClaudeMemoryRow` duplicate per day for same candidate — add `UniqueConstraint("scan_date", "candidate_id")` |
| 3-15 | Dead Code | `greeks_source = "black_scholes"` — document as permanently unreachable in schema comment |
| 3-16 | Dead Code | `ex_dividend_assignment_guard` config key never read — remove or wire to `triggers.py` |
| 3-17 | Dead Code | `iv_history_parquet` config key never read — remove |
| 3-18 | Dead Code | `BuyCandidate.rationale` always empty string — remove until Claude enrichment is implemented |
| 3-19 | Dead Code | `max_correlated_exposure_pct` — add startup log warning that this limit is configured but not enforced |
| 3-20 | Doc | SETUP.md cron uses backslash-escaped path — use double-quoted paths |

---

## Call to Action

Follow this sequence exactly. Do not advance to a later step until the earlier step is done.

### Step 1 — Implement all P0 fixes

Work through P0-01 through P0-11 in order. Each fix is described above. The highest-leverage changes are:

**P0-01 (double-order):** Add `UniqueConstraint` on `ApprovalRow.candidate_id` and `OrderRow.approval_id`.

**P0-02 (orphan SUBMITTED):** Add startup recovery pass in `_run_service`.

**P0-03 (candidates unique):** Add `UniqueConstraint` on `CandidateRow.candidate_id`; use upsert in `_persist_candidates`.

**P0-04 (session across I/O):** Hoist IBKR data fetches before `session_scope` in `process_queued_orders`.

**P0-05 (double-subscribe):** Clear `self._subscriptions` before re-subscribing in `on_reconnect`.

**P0-06 (cancelMktData):** Store the subscribed `Contract` object and use it for cancellation.

**P0-07 (stale spot):** Add historical data fallback in `_get_spot` and `_get_spot_async`.

**P0-08 (CONFIRM LIVE stale quote):** Move `_fetch_quote`, `validate_live_quote`, and `build_limit_order` to after the confirm event fires.

**P0-09/10/11 (test gaps):** Create `test_buy_candidates.py`, add `run_scan()` integration test, add concurrent double-execution test.

---

### Step 2 — Implement safe/high-value P1 fixes

Prioritize in this order (business impact × ease):

1. **P1-01 + P1-02** — Fix rolling ROC denominator and collateral. This is the most impactful trading logic error.
2. **P1-05** — Add delta sign validation to risk engine. One-line check.
3. **P1-06** — Enforce `max_contracts` from config. ~3 lines.
4. **P1-03 + P1-04** — Fix negative bid sentinel and `bid=0` inconsistency.
5. **P1-07** — Recompute DTE from `cand.expiry` in Phase 1 re-validation.
6. **P1-08** — Switch to `ExcessLiquidity` for buying power/CSP sizing.
7. **P1-11** — Per-candidate TTL computation in `sender.py`.
8. **P1-12 + P1-13** — Fix send failure leaving dangling PENDING; add Telegram notification on TTL-null cancel.
9. **P1-14** — Add `UniqueConstraint` on `journal.entry_date`.
10. **P1-15** — Switch Claude runner to use stdin instead of `-p` arg.
11. **P1-16 + P1-17** — Log returns for HV; minimum history guard for IV percentile.
12. **P1-18** — Remove backwards ATR score from `_scoring.py`.
13. **P1-19** — Switch CSP sizing to `ExcessLiquidity`.
14. **P1-20 + P1-21** — Add supervisor examples and fix cron timezone in SETUP.md.
15. **P1-09 + P1-10** — Fix reconnect flag race; add max retry count.

---

### Step 3 — Add and update tests

After the code fixes, ensure these tests are added or updated:

- `tests/test_buy_candidates.py` — full coverage (scoring, sorting, empty, regime, analytics failure)
- `tests/test_engine.py` — add: delta sign mismatch rejects, `bid=-1` rejects, `max_contracts` enforced, DTE boundary (21/20/45/46)
- `tests/test_execution.py` — add: concurrent double-execution → 1 order, CONFIRM LIVE stale-quote prevention, fill recovery on disconnect, naked-call scenario documented, bid=0/ask>0 passes order builder
- `tests/test_strategies.py` — add: roll ROC uses correct denominator, zero-DTE guard, roll collateral correct
- `tests/test_monitor.py` — add: AutoReconnect re-subscribe, double-subscribe prevention
- `tests/test_connection.py` — new file: connect, AutoReconnect backoff, max retries, reconnect flag timing
- `tests/test_analytics.py` — add: IV percentile returns None with <30 observations, HV uses log returns
- `tests/test_notify.py` — add: each command handler (auth check, happy path, IBKR unavailable)

---

### Step 4 — Run the quality gate

All three must pass with zero failures/errors/warnings:

```bash
python -m pytest -q
ruff check .
mypy src
```

Fix every failure before proceeding. The 6 Streamlit dashboard tests skip without the optional dep — that is expected.

---

### Step 5 — Update all affected documentation

Apply every documentation fix required by CLAUDE.md's mandatory doc-update table:

- **ARCHITECTURE.md:**
  - Correct `triggers.py` description (triggers are stateless functions; Claude/Telegram called in `intraday.py::fire_alerts`)
  - Add dedicated `eod: 16` clientId to process table; note concurrent risk
  - Update `OptionQuote` data flow entry to mention computed `mid`, `spread_pct`, `dte` (ET-aware)
  - Add `BuyCandidate` schema note that `rationale` is currently always empty
  - Fix `scoring_weights.yaml` config description: per-strategy weight dicts, not a single global set
  
- **STATUS.md:**
  - Add `option_quotes` to "Not built (deliberately deferred)": written every scan, never read; document as write-only
  - Update "Remaining known issues": add rolling ROC/collateral fix status; add `max_contracts` enforcement
  - Update "Bugs fixed" list with all P0/P1 fixes from this audit
  - Remove or update any "remaining known issues" that are now fixed

- **SETUP.md:**
  - Fix cron template to use `TZ=America/New_York` prefix and double-quoted paths
  - Add process supervisor section (systemd/launchd examples)
  - Add database backup section
  - Add Reddit credential optional keys to `.env.example` template
  - Extend troubleshooting table with: expired RTH approval, partial fill recovery, DB locked error, IV history stale
  - Add TWS/Gateway session expiry note (IBC for headless operation)

- **`src/common/schemas.py`:**
  - Change `greeks_source` comment: `"ibkr" only (black_scholes path not yet built — see STATUS.md)`
  - Rename `trend_strength` in `TechnicalStats` to `atr_pct` (currently misnamed as ADX proxy)

---

## Final Deliverable (Post-Remediation Target)

After all steps above are complete and the quality gate passes, re-run a manual verification:

1. `python -m scripts.healthcheck` — confirms connection, prints account
2. `python -m pytest -q` — all tests pass
3. `ruff check . && mypy src` — zero issues
4. Start approval service and monitor in paper mode, run `/health`, verify all-green
5. Trigger a `/scan`, approve a candidate, verify order placed and confirmed back to Telegram
6. Verify a reconnect (restart TWS) and confirm monitor re-subscribes without doubling lines

**Target scores post-remediation:**
- System Score: 80 / 100
- Production Readiness Score: 72 / 100
- Remaining risks: overnight stale data (DTE/earnings), share-ownership at execution, no fill reconciliation on reconnect — all documented in STATUS.md and mitigated by paper-first policy and TTL tuning

---

## Remaining Risks After All P0/P1 Fixes

These are known and documented — do not flip `LIVE_TRADING=true` without understanding them:

| Risk | Mitigation |
|---|---|
| Overnight stale data (DTE/earnings) | Reduce `approval.ttl_minutes` to 30–45 min; never approve pre-market |
| Share ownership not re-verified at execution | Reconcile positions manually before going live |
| Unqualified contracts in monitor/greeks enrichment | Monitor market data line count in `/health`; restart monitor if line count grows |
| Post-reconnect fill recovery (no `reqExecutions` reconciliation) | Check `/status` after any TWS restart during an active order |
| `next_earnings=None` bypasses blackout | ETFs never earn; individual stocks without calendar data require manual check |
| `AutoReconnect` timing under real OPRA tick load | Validate on ≥ 10 paper sessions before going live |
