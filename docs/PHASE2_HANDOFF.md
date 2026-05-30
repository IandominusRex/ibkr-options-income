# Phase 2 Handoff — Analytics Layer

> Read this first, then `PLAN.md` (Phase 2 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 1)

**Phases 0 and 1 are complete and verified** (`mypy src` clean, `ruff` clean, 32/32 tests pass).

What already exists and should be **reused, not rebuilt**:

| File | What it gives you |
|---|---|
| `src/ibkr/market_data.py` | `get_option_chain_quotes(ib, symbol) -> list[OptionQuote]` — live chain with Greeks. `persist_chain_quotes(symbol, quotes, run_id)` writes to `option_quotes` table. |
| `src/ibkr/contracts.py` | `qualify_stock`, `qualify_options`, `build_stock`, `build_option`. |
| `src/common/schemas.py` | `OptionQuote`, `IVStats`, `TechnicalStats`, `FundamentalStats`, `ScoreCard`, `Regime`. Phase 2 **populates** these fully. Do not add new cross-module shapes without a reason. |
| `src/storage/models.py` | `IVHistoryRow` (seeded by backfill), `OptionQuoteRow`. Phase 2 reads from `IVHistoryRow`; it does not write any new tables. |
| `src/storage/db.py` | `session_scope()` for read queries. |
| `config/risk_limits.yaml` | `iv.min_iv_rank`, `liquidity.max_bid_ask_spread_pct`, `liquidity.min_open_interest`, `liquidity.min_option_volume`, `events.earnings_blackout_days`. All thresholds live here. |
| `config/scoring_weights.yaml` | Per-strategy weights used by Phase 4's `scoring.py`. Analytics returns raw stats; Phase 4 normalizes to 0–100. |

## Phase 2 goal (acceptance criterion)

> A single call — `get_analytics(symbol, quotes)` — returns a fully populated tuple of
> `(IVStats, TechnicalStats, FundamentalStats)`, and a single `OptionQuote` can be scored
> for liquidity. `pytest` green, `mypy` clean.

You do **not** need a live TWS connection for this phase. IV stats read from `iv_history` in
SQLite; technicals and fundamentals pull from `yfinance`; liquidity scores are computed from
the `OptionQuote` objects already in memory.

## Files to create

```
src/analytics/iv.py           # IV Rank/Percentile from iv_history + term structure + skew
src/analytics/technicals.py   # RSI/ATR/MACD/MAs/S-R + regime classifier  (yfinance data)
src/analytics/fundamentals.py # FCF, debt, earnings dates, dividend safety (yfinance)
src/analytics/liquidity.py    # bid/ask spread %, OI, volume gate — pure OptionQuote math
tests/test_analytics.py       # unit tests; mock yfinance + DB; no TWS needed
```

`src/analytics/__init__.py` already exists (empty). Do not add a top-level aggregator function
here yet — the orchestrator (Phase 9) will own that call sequence.

## Implementation notes (the parts that bite)

### 1. `iv.py` — data sources are split

IV Rank and Percentile come from the `iv_history` table (one row per symbol/date, seeded by
`scripts/backfill_iv.py`). The "current IV" used for rank computation is the most recent row in
that table — **not** the live `ticker.modelGreeks.impliedVol`. The latter is per-contract; this
is the constant-maturity underlying series.

```python
def get_iv_stats(symbol: str, quotes: list[OptionQuote] | None = None) -> IVStats
```

- Query `IVHistoryRow` for the symbol, order by `obs_date DESC`, take up to 365 rows.
- `current_iv` = most recent row's `iv`.
- `iv_rank` = `(current - min_52w) / (max_52w - min_52w) * 100`. Guard division-by-zero
  (flat vol curve) by returning `None`.
- `iv_percentile` = `sum(1 for h in history if h < current) / len(history) * 100`.
- `hv_30` — 30-day historical volatility of underlying closes. Compute from yfinance
  OHLCV (`close.pct_change().rolling(30).std() * sqrt(252) * 100`). Keep in same pass as
  technicals if you want, or compute inline here.
- `term_structure_slope` and `put_call_skew` require the live `quotes` list (optional param).
  If `quotes` is None or empty, leave both fields `None` — they'll be enriched when the chain
  is available.
  - **Term structure:** group ATM-ish quotes by expiry, compute mean IV per expiry, fit a
    linear slope in (dte, iv) space. "ATM-ish" = strikes within 5% of spot. Spot can be
    inferred as the midpoint of the tightest-spread ATM options across the chain.
  - **Put/call skew:** at each expiry, find the put and call at approximately the same absolute
    delta (~0.30). Skew = mean(put.iv) - mean(call.iv). Positive = put premium (normal).

### 2. `technicals.py` — yfinance quirks

```python
def get_technical_stats(symbol: str, lookback_days: int = 260) -> TechnicalStats
```

Use `yfinance.Ticker(symbol).history(period="1y")` for OHLCV. This returns a `pandas.DataFrame`
with a `DatetimeIndex`. Common gotcha: the DataFrame is empty for very illiquid names or if the
symbol is wrong — always guard `if df.empty: return TechnicalStats(symbol=symbol, price=0.0)`.

**RSI-14:**
```
delta = close.diff()
gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
rs = gain / loss
rsi = 100 - 100 / (1 + rs)
```

**ATR-14:** `ta.atr(high, low, close, 14)` if you add `ta-lib` or `pandas_ta`, otherwise:
```
tr = max(high-low, |high-prev_close|, |low-prev_close|) per row
atr = tr.ewm(com=13, adjust=False).mean()
```

**MACD:** 12-EMA minus 26-EMA; signal = 9-EMA of MACD line.

**SMAs:** `close.rolling(N).mean()` — take `iloc[-1]` for the current value.

**ADX (trend strength):** Needed for `trend_strength`. Standard Wilder's ADX over 14 periods.
It is fiddly to implement from scratch; use `pandas_ta` if it is already in `pyproject.toml`,
or add it. If not, a simplified proxy: `(atr_14 / close.mean()) * 100` — lower is sideways.

**Regime classifier** (`Regime` enum from `schemas.py`):
- `HIGH_VOL` if ATR-14 / close[-1] > 0.025 (>2.5% daily range)
- `BULLISH` if close > SMA-50 > SMA-200 and RSI > 55
- `BEARISH` if close < SMA-50 < SMA-200 and RSI < 45
- `SIDEWAYS` otherwise (default)
- `LOW_VOL` if ATR-14 / close[-1] < 0.008

Apply in order: HIGH_VOL → BULLISH → BEARISH → SIDEWAYS → LOW_VOL.

**Support/resistance levels:** Simple approach — local minima/maxima in a 30-bar rolling
window. Take the 3 most recent levels on each side. Return as sorted lists. Placeholder `[]`
if fewer than 50 bars available.

### 3. `fundamentals.py` — graceful degradation is essential

```python
def get_fundamental_stats(symbol: str) -> FundamentalStats
```

yfinance can return incomplete or `None` data for ETFs and some symbols. Wrap every field read in
`try/except` or use `.get()` with a default. Never let a KeyError in fundamentals kill the
analytics pipeline.

```python
info = yf.Ticker(symbol).info
```

Key fields:
- `next_earnings`: `yf.Ticker(symbol).calendar` returns a dict with `"Earnings Date"` — a list
  of `Timestamp`. Take the first future date. Can be `None` for ETFs.
- `pe_ratio`: `info.get("trailingPE")`
- `free_cash_flow`: `info.get("freeCashflow")` — in absolute dollars, not per share.
- `debt_to_equity`: `info.get("debtToEquity")`
- `dividend_yield`: `info.get("dividendYield")`
- `ex_dividend_date`: `info.get("exDividendDate")` — a Unix timestamp; convert with
  `datetime.fromtimestamp(ts).date()`.
- `dividend_safe`: heuristic — `payout_ratio < 0.60` AND `free_cash_flow > 0`. Both from info.
  `True` if both pass, `False` if either fails, `None` if data unavailable.
- `quality_flag`: `pe_ratio > 0` AND `debt_to_equity < 150` AND `free_cash_flow > 0`. A rough
  "not a zombie stock" screen. Set `None` if insufficient data for ETFs (they have no PE).

**ETF shortcut:** ETFs return almost no fundamental data. Check `info.get("quoteType") == "ETF"`
and return a `FundamentalStats` with only `symbol` and `quality_flag=True` (ETFs pass quality
by assumption in this system).

**Rate limits:** yfinance is not rate-limited severely for small universes, but add `time.sleep(0.2)`
between calls in batch usage to be safe.

### 4. `liquidity.py` — pure OptionQuote math, no external calls

```python
def score_liquidity(quote: OptionQuote) -> float          # 0.0–100.0
def passes_liquidity_gates(quote: OptionQuote) -> bool
```

`passes_liquidity_gates` reads thresholds from `config/risk_limits.yaml` via `get_config()`:
- `spread_pct <= cfg.risk["liquidity"]["max_bid_ask_spread_pct"]`
- `open_interest >= cfg.risk["liquidity"]["min_open_interest"]`
- `volume >= cfg.risk["liquidity"]["min_option_volume"]`
- Any field that is `None` → that gate fails (conservative default).

`score_liquidity` maps the same three dimensions to 0–100 each, then averages:
- **Spread score**: `max(0, 100 - (spread_pct / max_spread) * 100)` — tighter spread = higher score.
- **OI score**: `min(100, (open_interest / 1000) * 100)` — saturates at OI ≥ 1000.
- **Volume score**: `min(100, (volume / 100) * 100)` — saturates at volume ≥ 100.
- Average the three. If any is None, treat it as 0 (penalise missing data).

## Testing without live data

Mock the DB session (monkeypatch `session_scope`) and `yfinance.Ticker`. For iv.py tests, create
in-memory `IVHistoryRow` objects directly — no SQLite connection needed. For technicals/fundamentals,
build a minimal fake `yf.Ticker` with a canned `history()` DataFrame and `info` dict.

Minimum test coverage:
- `iv_rank` formula: known history → expected rank value
- `iv_percentile` formula: same
- Edge case: flat vol history (min == max) → `iv_rank` is `None`
- `TechnicalStats.regime` classification for each branch
- `passes_liquidity_gates`: each gate failing independently
- `score_liquidity`: spread=0%, OI=5000, vol=500 → perfect score 100
- `get_fundamental_stats` with ETF shortcut returns `quality_flag=True`
- `get_fundamental_stats` gracefully handles missing yfinance fields

## Quick verification when ready

```bash
source .venv/bin/activate
python -c "
from src.analytics.iv import get_iv_stats
from src.analytics.technicals import get_technical_stats
from src.analytics.fundamentals import get_fundamental_stats
print(get_iv_stats('QQQ'))
print(get_technical_stats('QQQ'))
print(get_fundamental_stats('QQQ'))
"
python -m pytest -q && ruff check . && mypy src
```

`get_iv_stats` requires `iv_history` to be seeded (run `backfill_iv.py` first). If the table
is empty, it returns `IVStats(symbol=symbol)` with all fields `None`.

## Open decisions to make in Phase 2

- **HV-30 data source:** compute from yfinance closes (simplest, stays offline) vs. use
  `reqHistoricalData(whatToShow='HISTORICAL_VOLATILITY')` from IBKR (live but requires TWS).
  Recommendation: yfinance for Phase 2 — consistent with technicals; swap later if needed.
- **pandas_ta dependency:** adds ATR/ADX cleanly. Alternative: hand-roll Wilder's ATR (15 lines).
  Decision affects `pyproject.toml`.
- **Fundamentals caching:** yfinance calls are slow (~0.5 s each) and data changes daily at most.
  Consider a `FundamentalsRow` SQLite cache with a 24-hour TTL, or just call fresh each morning
  scan. For v1, fresh-each-time is fine.
