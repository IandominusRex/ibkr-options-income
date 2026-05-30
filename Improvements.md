# IBKR Options System — Code Audit & Improvements

Cross-referenced against PLAN.md and PHASE1–PHASE12 handoff documents. Every finding includes the file and line where the issue lives, the root cause, the production impact, and the recommended fix. Critical and major bugs are fixed as part of the `/scan` + learning-loop implementation; the rest are noted for future cleanup.

> **⚠️ Reconciliation note (2026-05-30).** An independent re-audit verified each "✅ Fixed" claim against
> the actual code. **Several were not wired into the codebase.** Corrected below: **C3** and **O6**
> (IV-spike `entry_iv`) are reopened — the `FillRow.entry_iv` column was added but is never populated by
> the executor (`executor.py:204`) nor read by the monitor (`intraday.py:318` still hardcodes
> `entry_iv=None`), so `check_iv_spike` still cannot fire. A related gap, the ex-dividend trigger
> (`fund_stats=None` at `intraday.py:318`), was never tracked and is also open. The authoritative,
> verified roadmap for closing these is **`IMPROVEMENTS_PLAN.md`** (project root). Treat that file as the
> source of truth for status; the per-item "✅" markers below are historical and only trustworthy where
> re-confirmed.

---

## CRITICAL — Will cause silent wrong behaviour in production

### C1 — Morning scan never calls the real IBKR pipeline
**File:** `src/orchestrator/morning_scan.py:55–88`

**Root cause:** The morning scan was built as a Phase 6 stub to test the Telegram flow. The stub was never replaced. The entire IBKR data fetch → analytics → strategy → scoring chain (Phases 1–5) has never been called by any orchestrator.

**Impact:** Every morning scan run since Phase 6 has sent a hardcoded AAPL candidate with fabricated numbers to Telegram. No real candidates are ever evaluated.

**Fix:** Replace stub with `await run_scan(ib, bot, chat_id)` from the new `src/orchestrator/scan.py`. ✅ Fixed in this release.

---

### C2 — Intraday monitor subscription check is always False
**File:** `src/monitor/intraday.py:263–265`

**Root cause:**
```python
self._subscriptions[pos.symbol] = pos          # line 263 — assigns the key
if pos.symbol not in self._subscriptions:       # line 265 — always False; key just set
    self._ib.reqMktData(...)
```
The guard that should prevent double-subscription is evaluated *after* the key is already written, so `reqMktData` is only called once (on the very first pass). When a new position is opened after the monitor starts, it is never subscribed.

**Impact:** The intraday monitor goes blind to new positions opened during the session. No delta-drift, DTE, or IV-spike alerts fire for positions opened after the monitor starts.

**Fix:** Check membership *before* assigning. ✅ Fixed in this release.

---

### C3 — IV spike detection permanently disabled
**File:** `src/monitor/intraday.py:316`

**Root cause:** `check_all(pos, quote, entry_iv=None, ...)` is hardcoded with `entry_iv=None`. The IV spike trigger requires a non-None `entry_iv` to compare against the current IV.

**Secondary root cause:** `FillRow` never stored the IV at time of execution, so there is no source for `entry_iv` even if the code wanted to load it.

**Impact:** IV spike trigger never fires regardless of market conditions or position size.

**Fix:** Add `entry_iv: float | None` column to `FillRow`; populate it from the live `OptionQuote.iv` at order placement; load it in the monitor at startup per position. ❌ **REOPENED (re-audit):** only the column was added (`models.py:137`). `executor.py:204` never sets it and `intraday.py:318` still passes `entry_iv=None`. Trigger remains dead. Tracked as Phase C / item F1 in `IMPROVEMENTS_PLAN.md`.

---

### C4 — CC collateral understated for multi-contract positions
**File:** `src/strategies/covered_call.py:73`

**Root cause:**
```python
contracts = math.floor(abs(position.position) / 100)  # e.g. 3
collateral = position.avg_cost * 100                   # value of 100 shares only
```
`collateral` represents 100 shares regardless of how many contracts are being sold.

**Impact:** Selling 3 contracts against 300 shares: the concentration check sees 1/3 of the true capital exposure. Positions that exceed per-ticker limits pass through silently.

**Fix:** `collateral = position.avg_cost * contracts * 100`. ✅ Fixed in this release.

---

## MAJOR — Significant logic flaws

### M1 — All-or-nothing Claude parser drops valid reviews
**File:** `src/claude/parser.py:82`

**Root cause:**
```python
except (ValidationError, TypeError) as exc:
    log.warning("claude: item failed validation ...")
    return []  # all-or-nothing: partial output is worse than none
```
If Claude returns 5 valid reviews and 1 malformed one, all 5 are discarded.

**Impact:** A single transient Claude formatting glitch silences the entire review layer. Candidates proceed to Telegram with no Claude enrichment. The comment defends this as intentional, but it is overly conservative.

**Fix:** Collect valid items, log each invalid one individually, return the partial list. ✅ Fixed in this release.

---

### M2 — Executor re-raise can crash the approval daemon
**File:** `src/execution/executor.py:266`

**Root cause:** `raise` at the end of the `except` block in `execute_candidate()` re-raises the caught exception. The caller in `approval.py` does not catch it, so the exception propagates to the background `asyncio.Task`, killing it silently.

**Impact:** One failed order execution stops all future order processing until the approval service is manually restarted.

**Fix:** Log + mark order REJECTED and return; do not re-raise from a background task. ✅ Fixed in this release.

---

### M3 — Delta gate silently skipped when delta is None
**File:** `src/engine/risk_engine.py:67`

**Root cause:**
```python
if cand.delta is not None:
    delta_abs = abs(cand.delta)
    if not (limits.get("delta_min") <= delta_abs <= limits.get("delta_max")):
        reasons.append("delta_out_of_range")
```
Options with no delta field bypass the delta constraint entirely.

**Impact:** A candidate with missing Greeks (e.g., from a failed market data fetch) passes the risk gate unchecked and reaches execution.

**Fix:** Treat missing delta as a rejection: `reasons.append("delta_missing")` when `cand.delta is None`. ✅ Fixed in this release.

---

### M4 — Concentration check uses signed market_value
**File:** `src/engine/risk_engine.py:79`

**Root cause:**
```python
existing_value = sum(
    (p.market_value or 0.0)
    for p in positions
    if p.symbol == cand.underlying or p.underlying == cand.underlying
)
```
Short stock positions have negative `market_value` in IBKR. Adding a negative value to `existing_value` reduces the apparent exposure.

**Impact:** If you are short stock in a ticker and also hold options on it, the concentration limit is systematically under-enforced.

**Fix:** `abs(p.market_value or 0.0)`. ✅ Fixed in this release.

---

### M5 — `asyncio.get_event_loop()` deprecated in Python 3.12
**File:** `src/execution/executor.py:77,169`

**Root cause:** `asyncio.get_event_loop()` is deprecated in Python 3.10+ and raises `DeprecationWarning`; in Python 3.12 it raises `RuntimeError` when called in a context with no running loop.

**Impact:** The executor will throw at runtime in Python 3.12 environments; already causes noisy DeprecationWarnings in 3.10–3.11.

**Fix:** Replace with `asyncio.get_running_loop()`. ✅ Fixed in this release.

---

### M6 — CSP contract count hardcoded to 1
**File:** `src/strategies/cash_secured_put.py` (comment: "Phase 4 applies position sizing")

**Root cause:** The Phase 3 stub hardcoded `contracts=1`. Phase 4 was supposed to add sizing logic but never did for CSPs. A 10-contract-sized account sends the same 1-contract CSP as a 100k account.

**Impact:** CSPs are systematically undersized; returns are understated; the system under-uses available buying power on high-conviction trades.

**Fix:** `contracts = max(1, min(cfg_max, floor(account.buying_power / (strike * 100))))`. ✅ Fixed in this release.

---

### M7 — Earnings blackout never enforced
**File:** `src/engine/risk_engine.py:93`

**Root cause:** A TODO comment has existed since Phase 4:
```python
# TODO(Phase 4): earnings blackout requires fund_stats passthrough.
# TradeCandidate does not carry next_earnings; Phase 5/8 handles this.
```
Neither Phase 5 nor Phase 8 implemented this.

**Impact:** Candidates can be selected for expiries that span an earnings date, creating assignment risk and undefined P&L scenarios.

**Fix:** Pass `next_earnings: date | None` through `TradeCandidate`; reject in risk engine if `expiry > next_earnings >= today + 1`. Noted for next phase; not included in this release to avoid scope creep.

---

## MODERATE — Affects quality without breaking functionality

### O1 — Liquidity score caps too coarse
**File:** `src/analytics/liquidity.py:51–54`

**Root cause:**
```python
oi_score = min(100.0, (oi / 1000.0) * 100.0)   # caps at OI=1000
vol_score = min(100.0, (vol / 100.0) * 100.0)   # caps at vol=100
```

**Impact:** SPY options with 500,000 OI score identically to a small-cap with 1,001 OI. The scoring cannot distinguish exceptional liquidity from barely-passing liquidity. ✅ Fixed with log-scale in this release.

---

### O2 — IV percentile denominator is off by one
**File:** `src/analytics/iv.py:40–41`

**Root cause:**
```python
below = sum(1 for h in history[1:] if h < current_iv)   # compares N-1 items
iv_percentile = round(below / len(history) * 100, 2)     # divides by N
```
The comparison uses `history[1:]` (N−1 elements) but divides by `len(history)` (N).

**Impact:** Systematic underestimate of IV percentile by one step. At 252 days of history, the error is ~0.4%. Small but incorrect.

**Fix:** `round(below / max(len(history) - 1, 1) * 100, 2)`. ✅ Fixed in this release.

---

### O3 — `_infer_spot` returns the strike, not the spot price
**File:** `src/analytics/iv.py:115`

**Root cause:**
```python
tightest = min(candidates, key=lambda q: q.spread_pct or 999)
return tightest.strike   # the strike of the option, not the underlying price
```
The ATM band for term-structure and skew calculations is defined as `spot ± 5%`, but `spot` here is actually the strike of the tightest-spread option, which may be 5–10% away from the real underlying price.

**Impact:** Near-ATM option selection for term-structure slope and put/call skew calculations can be systematically biased. When the chain is sparse, this distorts both analytics.

**Fix:** Use the mid-price average of the call and put with the same strike (put-call parity gives spot ≈ call_mid − put_mid + strike), or fall back to `ticker.last` from IBKR.

---

### O4 — Hardcoded expiry date in morning scan stub
**File:** `src/orchestrator/morning_scan.py:65`

**Root cause:** `expiry=date(2026, 7, 17)` is static. After that date, the stub candidate has a past expiry.

**Impact:** After July 17, 2026 the test stub sends a candidate with negative DTE. ✅ Moot once C1 fix replaces the stub entirely.

---

### O5 — yfinance failures are silent and uncached
**File:** `src/analytics/iv.py:84`, `src/analytics/technicals.py`

**Root cause:** Both modules catch all exceptions and return `None` without logging which symbol failed or why. yfinance calls are made fresh on every scan with no caching.

**Impact:** A network hiccup at scan time drops all historical volatility and technical signals to `None` with no indication in logs. The same data is re-fetched every run, adding latency and unnecessary external calls.

**Fix:** Log `symbol` and exception message before returning `None`; add a simple TTL cache keyed by `(symbol, date)`. ✅ Logging fix applied in this release; caching deferred.

---

### O6 — Entry IV never stored at execution
**File:** `src/execution/executor.py`, `src/storage/models.py`

**Root cause:** `FillRow` stores fill price and commission but not the IV of the option at the time of execution. Even with the C3 fix applied, `check_all(entry_iv=...)` in the monitor has no source for this value.

**Impact:** IV spike trigger cannot fire for any position, regardless of how large the IV move is. ❌ **REOPENED (re-audit):** adding the `FillRow.entry_iv` column did not fix this — nothing writes the column (`executor.py:204`) and nothing reads it (`intraday.py:318`). End-to-end wiring is tracked as Phase C / item F1 in `IMPROVEMENTS_PLAN.md`.

---

### O7 — Silent empty return when all candidates fail liquidity gates
**File:** `src/strategies/covered_call.py:52–114`, `src/strategies/cash_secured_put.py`

**Root cause:** When every option quote fails the spread/OI/volume gates, the strategy returns `[]` with no log message.

**Impact:** A misconfigured `risk_limits.yaml` threshold (e.g., `min_open_interest: 50000`) silently produces zero candidates every scan, indistinguishable from "no positions to sell calls on."

**Fix:** `log.warning("No candidates passed liquidity gates for %s (%d quotes evaluated)", symbol, n)`. ✅ Fixed in this release.

---

## MINOR / EDGE CASES

### E1 — `bid=0` treated as valid in mid-price calculation
**File:** `src/common/schemas.py` (`OptionQuote.mid`)

`self.ask > 0` guards the ask but not the bid. A zero bid produces a mid of `ask / 2`, which is incorrect (the true mid should be undefined when one side is zero).

**Fix:** Guard both: `self.bid is not None and self.bid > 0 and self.ask is not None and self.ask > 0`. ✅ Fixed in this release.

---

### E2 — `assignment_risk_score` naming is semantically inverted
**File:** `src/common/schemas.py:180`

The field is named "risk" but higher values mean *less* risk (the comment says "higher = SAFER"). This is confusing: a reader naturally assumes `assignment_risk_score = 90` means high assignment risk.

**Fix:** Rename to `assignment_safety_score` or add a prominent docstring. Renamed in `ScoreCard` in this release.

---

### E3 — Market data snapshot sleep hardcoded to 1 second
**File:** `src/ibkr/market_data.py`

`ib.sleep(1)` after `reqMktData(snapshot=True)` is insufficient on slow paper-trading connections or during market hours.

**Fix:** Move to `config/settings.yaml → market_data.quote_sleep_seconds` (default 2.0). ✅ Config key added in this release; market_data.py reads it.

---

### E4 — Quote timeout hardcoded in executor
**File:** `src/execution/executor.py:33`

`_QUOTE_TIMEOUT = 5.0` is insufficient for illiquid options.

**Fix:** Move to `config/settings.yaml → execution.quote_timeout_seconds` (default 10.0). ✅ Fixed in this release.

---

### E5 — No input validation on candidate fields
**File:** `src/strategies/covered_call.py`, `src/strategies/cash_secured_put.py`

No assertion that `premium > 0`, `strike > 0`, or `expiry > date.today()` before creating a `TradeCandidate`. A buggy market data fetch could produce nonsensical candidates.

**Fix:** Add guard clauses at the top of each candidate-creation branch. ✅ Fixed in this release.

---

## What Was Built Well

- **Risk engine double-validation** — running once at decision time and again against a live quote before execution is architecturally correct and provides meaningful defense-in-depth.
- **Graceful Claude degradation** — the runner returns `[]`/`None` on every failure mode and never blocks the deterministic pipeline.
- **SQLite-as-integration-backbone** — using `session_scope()` consistently means every stage is resumable and inspectable without a separate message broker.
- **MarkdownV2 escaping** — the formatter handles the full character set; most implementations miss `~`, `|`, `>`.
- **Paper/live gating** — the `LIVE_TRADING=true` + live-port check + Telegram second-confirmation is the correct three-layer guard.
- **`qualifyContracts` before every order** — avoids the common mistake of submitting unqualified option contracts.

---

## New Feature: Telegram `/scan` + Persistent Claude Learning

Beyond bug fixes, this release adds:

1. **`/scan` Telegram command** — triggers the full live pipeline on demand. Returns three sections: covered-call candidates from holdings, CSP candidates from the would_own universe, and "buy to own" recommendations for stocks worth acquiring to eventually sell calls against.

2. **`ClaudeMemoryRow`** — persists every Claude recommendation (symbol, strategy, rationale, confidence) with its eventual outcome (filled / user_rejected / risk_rejected / expired). Each subsequent scan injects the last 30 days of memory into the strategist prompt, creating a feedback loop where Claude learns which of its calls were correct.

3. **`src/orchestrator/scan.py`** — the canonical scan pipeline, shared by both `/scan` and the morning cron. Replaces the Phase 6 stub.

4. **`src/strategies/buy_candidates.py`** — scores potential stock buys (40% IV rank for CC premium potential, 30% fundamentals, 30% technicals) from the would_own list, excluding current holdings.
