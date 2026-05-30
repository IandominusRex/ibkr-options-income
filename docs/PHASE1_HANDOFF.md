# Phase 1 Handoff — Market Data Agent

> Read this first, then `PLAN.md` (Phase 1 + "Process model" addendum) and `CLAUDE.md`.
> The official IBKR API reference is `ib_async_documentation.md` (root) — consult it for every
> `reqXxx` signature; do not guess.

## Where things stand (end of previous session)

**Phase 0 is complete and verified** (`mypy src` clean, `ruff` clean, 7/7 tests pass). The only
unrun step is `python -m scripts.healthcheck` against live TWS (needs the user's Gateway up on
paper port 7497).

What already exists and should be **reused, not rebuilt**:

| File | What it gives you |
|---|---|
| `src/ibkr/connection.py` | `IBKRConnection(role)` context manager: connect/reconnect + backoff, clientId from config, live/paper safety banner, `resolve_account()`. **Use this for every IB connection.** |
| `src/ibkr/portfolio.py` | `get_positions(ib)`, `get_account_snapshot(ib, account)` → typed schemas. Extend here for margin/Greeks enrichment. |
| `src/common/schemas.py` | All Pydantic contracts. Phase 1 **populates** `OptionQuote`, `IVStats` (partial), and uses `PositionSnapshot`. Don't add new cross-module shapes without a reason. |
| `src/common/config.py` | `get_config()` (cached). Phase 1 reads `cfg.market_data.*` (batch size, throttle, line cap), `cfg.universe`, `cfg.ibkr.client_ids["backfill"]`. |
| `src/storage/db.py` + `models.py` | `session_scope()`, `init_db()`, `IVHistoryRow` (already defined — backfill writes here). |
| `config/settings.yaml` | `market_data.max_concurrent_lines: 90`, `chain_batch_size: 40`, `request_throttle_seconds: 0.25`. clientId `backfill: 13`. |

## Phase 1 goal (acceptance criterion)

> Full option chain + live Greeks/IV for a watchlist name land in SQLite, and `iv_history` is
> seeded with ~1y of daily IV for each universe symbol.

## Files to create

```
src/ibkr/contracts.py     # contract builders + qualification
src/ibkr/market_data.py    # chains, live quotes+Greeks, historical IV
scripts/backfill_iv.py     # one-shot: seed iv_history (clientId "backfill")
tests/test_market_data.py  # unit tests with a mocked IB (no TWS)
```
Optionally add a `CandidateRow`-style `OptionQuoteRow` to `models.py` only if you decide to persist
full chains (the acceptance test wants chains "in SQLite"). Simplest: a small `option_quotes` table
keyed by run_id; or persist as JSON. Decide and note it.

## Implementation notes (the parts that bite)

### 1. Contracts (`contracts.py`)
- `Stock(symbol, "SMART", "USD")` and `Option(symbol, "YYYYMMDD", strike, "C"/"P", "SMART")`.
- **Always `ib.qualifyContracts(contract)` before use** — fills in conId/exchange and validates.
  Unqualified option contracts silently return no data. (CLAUDE.md mandates this before orders too.)

### 2. Option chains (`market_data.py`)
- Use `ib.reqSecDefOptParams(underlyingSymbol, "", underlyingSecType, underlyingConId)` to get the
  set of expirations + strikes. It returns multiple exchange rows — filter to SMART. You must first
  qualify the **underlying** to get its `conId`.
- Pick expirations within `risk_limits.yaml` DTE windows (21–45) and strikes within a band around
  spot (e.g. ±15%) so you don't request thousands of contracts.

### 3. Live quotes + Greeks — **the timing gotcha**
- `ticker = ib.reqMktData(option, genericTickList="", snapshot=False, regulatorySnapshot=False)`.
- Greeks/IV arrive **asynchronously** on the ticker, not instantly. After requesting, you must
  `ib.sleep(2)` (or loop until populated) before reading. Then read **`ticker.modelGreeks`**
  (`.impliedVol`, `.delta`, `.gamma`, `.theta`, `.vega`). `bid/ask/last/volume` come off the ticker
  directly. `open_interest` needs generic tick `101`.
- **Cancel every line** with `ib.cancelMktData(option)` when done with a batch — this is how you
  stay under the ~90-line cap.

### 4. Line-limit batching (do NOT request a whole chain at once)
Pattern: chunk qualified option contracts into `chain_batch_size` (40); for each batch →
`reqMktData` all, `ib.sleep(throttle)` then wait for Greeks, snapshot into `OptionQuote`, then
`cancelMktData` all before the next batch. Respect `max_concurrent_lines`.

### 5. Set `greeks_source`
When you read from `ticker.modelGreeks`, set `OptionQuote.greeks_source = "ibkr"`. The Black-Scholes
fallback (Phase 2, `analytics/greeks.py`) sets `"black_scholes"`. If `modelGreeks` is None after the
wait (illiquid/no sub on that line), leave Greeks None — Phase 2 fills them.

### 6. IV history backfill (`scripts/backfill_iv.py`) — for IV Rank
- This is **underlying-level**, not per-contract. For each symbol in `universe` (indexes + watchlist
  + would_own, de-duped):
  ```python
  bars = ib.reqHistoricalData(stock, endDateTime="", durationStr="1 Y",
                              barSizeSetting="1 day",
                              whatToShow="OPTION_IMPLIED_VOLATILITY", useRTH=True)
  ```
  This returns IBKR's ~30-day constant-maturity IV index for the name — one value per day. Write
  each `(symbol, bar.date, bar.close)` to `IVHistoryRow` (source="ibkr"). Idempotent: skip dates
  already present.
- Use `IBKRConnection("backfill")` (clientId 13). Throttle between symbols (`reqHistoricalData` is
  pacing-sensitive — ~`ib.sleep(0.5)` between calls; if you get pacing violations, back off more).
- IV Rank/Percentile **computation** lives in Phase 2 (`analytics/iv.py`) reading this table; Phase
  1 only seeds the data.

### 7. Async vs sync
Phase 1 scripts are one-shot and synchronous — use the blocking `ib.reqXxx` + `ib.sleep` style (see
`ib_async_documentation.md` "Basic Script Usage"). Do **not** introduce APScheduler here. The async
event-driven style is only for the Phase 8 intraday monitor.

## Testing without TWS
Mock the `IB` object. Build a fake ticker with a `modelGreeks` namespace and assert `OptionQuote`
fields map correctly; assert batching chunks by `chain_batch_size` and that `cancelMktData` is
called per contract. Don't hit a real socket in unit tests (Phase 0 tests are the pattern).

## Quick verification when TWS is up
```bash
source .venv/bin/activate
python -m scripts.backfill_iv                 # seeds iv_history
python -c "from src.ibkr.connection import IBKRConnection; \
from src.ibkr.market_data import get_option_chain_quotes; \
ib=IBKRConnection('engine').connect(); \
print(get_option_chain_quotes(ib,'QQQ')[:3]); ib.disconnect()"
python -m pytest -q && ruff check . && mypy src
```

## Open decisions to make in Phase 1 (none block starting)
- Persist full chains to a new `option_quotes` table vs keep in-memory for the pipeline? (Acceptance
  says "in SQLite" → lean toward a lightweight table or JSON blob per run.)
- Strike band width and how many expirations to pull (start ±15% spot, nearest 2–3 expiries in the
  DTE window).

## Task tracking
GSD/Task list item **#2 "Phase 1 — Market Data Agent"** is pending. Mark it `in_progress` when you
start. Phases #3–#12 follow in `PLAN.md`.
