# Phase 3 Handoff — Strategy Modules

> Read this first, then `PLAN.md` (Phase 3 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 2)

**Phases 0, 1, and 2 are complete and verified** (58/58 tests pass, `ruff` clean, `mypy` clean).

What now exists and should be **reused, not rebuilt**:

| File | What it gives you |
|---|---|
| `src/analytics/iv.py` | `get_iv_stats(symbol, quotes) -> IVStats` — IV Rank/Percentile/HV30/skew/term structure. |
| `src/analytics/technicals.py` | `get_technical_stats(symbol) -> TechnicalStats` — RSI/ATR/MACD/SMAs/S-R/regime. |
| `src/analytics/fundamentals.py` | `get_fundamental_stats(symbol) -> FundamentalStats` — earnings date, quality screen, dividends. |
| `src/analytics/liquidity.py` | `score_liquidity(quote) -> float`, `passes_liquidity_gates(quote) -> bool`. |
| `src/ibkr/market_data.py` | `get_option_chain_quotes(ib, symbol) -> list[OptionQuote]` — live chain from IBKR. |
| `src/common/schemas.py` | `OptionQuote`, `IVStats`, `TechnicalStats`, `FundamentalStats`, `TradeCandidate`, `ScoreCard`. Phase 3 **produces** `TradeCandidate` objects. |
| `config/risk_limits.yaml` | `covered_call.{delta_min/max, dte_min/max}`, `cash_secured_put.{delta_min/max, dte_min/max}`, `income.{min_roc_pct, min_annualized_yield_pct}`. |
| `config/universe.yaml` | `would_own` list (CSP filter), `watchlist`, `indexes`. |

## Phase 3 goal (acceptance criterion)

> Given a live `list[OptionQuote]` plus analytics stats, each strategy module produces a ranked
> `list[TradeCandidate]` with all economics fields populated. `pytest` green, `mypy` clean.

No live TWS connection needed for tests — mock the chain with canned `OptionQuote` objects.

## Files to create

```
src/strategies/covered_call.py      # CC candidates from existing long stock positions
src/strategies/cash_secured_put.py  # CSP candidates filtered to would_own list
src/strategies/rolling.py           # Roll candidates for existing short options
tests/test_strategies.py            # unit tests; no TWS needed
```

`src/strategies/__init__.py` already exists (empty).

## Implementation notes (the parts that bite)

### 1. `candidate_id` — must be stable and collision-free

```python
import hashlib, json
from datetime import date

def _make_candidate_id(strategy: str, underlying: str, right: str, strike: float, expiry: date) -> str:
    key = f"{strategy}|{underlying}|{right}|{strike}|{expiry}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]
```

This makes the same trade produce the same ID across re-runs, which lets the DB deduplicate.

### 2. `covered_call.py`

```python
def generate_cc_candidates(
    symbol: str,
    quotes: list[OptionQuote],
    position: PositionSnapshot,   # the long stock position
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
) -> list[TradeCandidate]
```

**Strike selection:** Filter calls where:
- `delta` is between `config.risk["covered_call"]["delta_min"]` and `config.risk["covered_call"]["delta_max"]`
- `dte` is between `dte_min` and `dte_max`
- `mid` is not None and > 0
- `passes_liquidity_gates(quote)` is True

**Economics per candidate:**
- `premium` = `quote.mid` (per share)
- `contracts` = `floor(abs(position.position) / 100)` (can't sell more calls than you own shares)
- `collateral` = `position.avg_cost * 100` (basis per contract — the upside we're capping)
- `roc_pct` = `(premium / (collateral / 100)) * 100`
- `annualized_yield_pct` = `roc_pct * (365 / dte)`
- `breakeven` = `position.avg_cost - premium` (basis reduced by premium)
- `prob_profit` = proxy via `1 - abs(delta)` (delta ≈ PoP that expires ITM, so P(profit) ≈ 1-delta)

**ScoreCard:** Build a `ScoreCard` with:
- `iv_score` = `iv_stats.iv_rank` if not None else 0.0 (already 0-100)
- `technical_score` — use `_technical_score(quote, tech_stats)` helper below
- `fundamental_score` — use `_fundamental_score(fund_stats)` helper below
- `liquidity_score` = `score_liquidity(quote)` (already 0-100)
- `assignment_risk_score` — for CC, higher = safer. Use `(1 - abs(quote.delta)) * 100`.

**Leave `blended_score=0.0`** — Phase 4 (`scoring.py`/`decision_engine.py`) applies the weights.

**Gotcha:** `position.position` is signed (negative = short). For CC the position should be
positive (long stock). Guard: skip if `position.position <= 0`.

### 3. `cash_secured_put.py`

```python
def generate_csp_candidates(
    symbol: str,
    quotes: list[OptionQuote],
    account: AccountSnapshot,
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
) -> list[TradeCandidate]
```

**CSP allowlist gate first:** check `symbol in get_config().universe["would_own"]`. Return `[]` immediately if not.

**Strike selection:** Filter puts where:
- `abs(delta)` is between `delta_min` and `delta_max` (put delta is negative; use `abs`)
- `dte` between `dte_min` and `dte_max`
- `mid > 0` and `passes_liquidity_gates(quote)`

**Economics:**
- `premium` = `quote.mid`
- `contracts` = 1 (Phase 3 uses 1 contract; sizing lives in Phase 4)
- `collateral` = `quote.strike * 100` (cash needed to secure the put)
- `roc_pct` = `(premium / quote.strike) * 100`
- `annualized_yield_pct` = `roc_pct * (365 / dte)`
- `breakeven` = `quote.strike - premium`
- `prob_profit` = `1 - abs(quote.delta)`

**ScoreCard:**
- `assignment_risk_score` for CSP = `abs(quote.delta) * 100` inverted: `(1 - abs(quote.delta)) * 100`.
  A 0.15-delta CSP has 85/100 safety score — lower delta means less assignment risk.

### 4. `rolling.py`

```python
def generate_roll_candidates(
    position: PositionSnapshot,   # the existing short option
    quotes: list[OptionQuote],    # chain for the same underlying
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
) -> list[TradeCandidate]
```

A roll = close the existing short + open a new short at a further expiry / adjusted strike.
For Phase 3, model a roll as a new `TradeCandidate` with `strategy=Strategy.ROLL` where:
- `dte` > current position's DTE (rolling further out)
- Same delta targeting as CC/CSP rules depending on whether it was a call or put
- `premium` = new_mid - existing_mid (the roll credit; must be > 0 for a credit roll)
- `collateral` = same as the original position
- `roc_pct` and `annualized_yield_pct` based on the roll credit and remaining DTE of new leg

**Filter:** only generate roll candidates when `position.dte` is not None and `position.dte <= 21`
(nearing expiry) OR `abs(position.delta) > 0.40` (delta drift). The `intraday_monitor` (Phase 8)
will handle real-time triggering; Phase 3 just needs to *produce* candidates when asked.

**Gotcha:** `position.expiry` gives the current option's expiry. Build `OptionQuote` strikes for
the same underlying but a later expiry from `quotes`. The position's current mid is
`(bid+ask)/2` on the *existing* short — pass this in as a separate `current_mid: float` param
if needed, or infer from quotes by matching strike+expiry+right.

### 5. Shared score-helper functions

Put these in a thin `src/strategies/_scoring.py` (or inline in each module — your call):

```python
def _technical_score(quote: OptionQuote, tech: TechnicalStats) -> float:
    """0-100: proximity of strike to support/resistance + regime bonus."""
    score = 50.0  # neutral baseline
    # For calls: strike above nearest resistance → safer (less likely to be called)
    # For puts: strike below nearest support → safer (less likely to be put)
    if tech.regime == Regime.BULLISH:
        score += 10.0 if quote.right == OptionRight.CALL else -5.0
    elif tech.regime == Regime.BEARISH:
        score += 10.0 if quote.right == OptionRight.PUT else -5.0
    # ATR proximity: tighter ATR → more predictable → slight bonus
    if tech.atr_14 is not None and tech.price > 0:
        atr_pct = tech.atr_14 / tech.price
        score += max(0, 10 * (0.02 - atr_pct) / 0.02)  # bonus if ATR < 2%
    return max(0.0, min(100.0, score))

def _fundamental_score(fund: FundamentalStats) -> float:
    """0-100: binary quality gates mapped to a score."""
    if fund.quality_flag is True:
        score = 70.0
    elif fund.quality_flag is False:
        score = 20.0
    else:
        score = 50.0  # unknown — neutral
    if fund.dividend_safe is True:
        score += 15.0
    return min(100.0, score)
```

These are heuristics. Phase 4 normalises everything; Phase 3 just needs *reasonable* 0-100 inputs.

### 6. Filtering duplicates / income gate

After building the raw candidate list, filter out any where:
- `roc_pct < config.risk["income"]["min_roc_pct"]` — not worth the collateral
- `annualized_yield_pct < config.risk["income"]["min_annualized_yield_pct"]` — too low yield
- `contracts < 1` — can't trade fractions of contracts

Return the remaining list sorted by `roc_pct DESC` so the best trades surface first.

## Testing without live data

All tests use canned `OptionQuote` and `PositionSnapshot` objects — no mocking of IBKR or yfinance.
Build realistic `TechnicalStats` and `FundamentalStats` objects directly.

Minimum coverage:
- CC generates correct `contracts` count from position size (e.g. 200 shares → 2 contracts)
- CC breakeven = `avg_cost - premium`
- CC `annualized_yield_pct` formula check: known inputs → expected output
- CSP rejects symbol not in `would_own`
- CSP `collateral = strike * 100`
- CSP filters by delta range (a 0.50-delta put should not appear)
- Income gate filters out low-yield candidates
- Roll candidate has DTE > current position's DTE
- `candidate_id` is deterministic (same inputs → same id)
- Empty quotes list → empty candidate list (not an error)

## Quick verification when ready

```bash
source .venv/bin/activate
python -c "
from datetime import date
from src.common.schemas import OptionQuote, OptionRight, PositionSnapshot, AccountSnapshot
from src.analytics.iv import IVStats
from src.analytics.technicals import TechnicalStats
from src.analytics.fundamentals import FundamentalStats
from src.strategies.covered_call import generate_cc_candidates
from src.strategies.cash_secured_put import generate_csp_candidates

quotes = [
    OptionQuote(underlying='AAPL', right=OptionRight.CALL, strike=200.0,
                expiry=date(2025, 8, 15), bid=1.20, ask=1.40, volume=500,
                open_interest=2000, iv=0.28, delta=0.28, dte=46),
]
pos = PositionSnapshot(symbol='AAPL', sec_type='STK', position=200.0, avg_cost=175.0)
acct = AccountSnapshot(account='DU123', net_liquidation=100000, total_cash=50000,
                       buying_power=80000, maintenance_margin=10000, excess_liquidity=70000)
iv = IVStats(symbol='AAPL', current_iv=28.0, iv_rank=65.0)
tech = TechnicalStats(symbol='AAPL', price=185.0, rsi_14=55.0)
fund = FundamentalStats(symbol='AAPL', quality_flag=True)

cc = generate_cc_candidates('AAPL', quotes, pos, iv, tech, fund)
csp_quotes = [q.model_copy(update={'right': OptionRight.PUT, 'delta': -0.25}) for q in quotes]
csp = generate_csp_candidates('AAPL', csp_quotes, acct, iv, tech, fund)
print('CC candidates:', len(cc), cc[0].roc_pct if cc else 'none')
print('CSP candidates:', len(csp), csp[0].roc_pct if csp else 'none')
"
python -m pytest -q && ruff check . && mypy src
```

## Open decisions to make in Phase 3

- **Contract sizing for CSPs:** Phase 3 hardcodes `contracts=1`. Phase 4 will size by buying power.
  That's fine — leave a `# TODO(Phase 4): apply position sizing` comment if you want a marker.
- **Roll modelling depth:** Rolling is complex in real life (choosing the right expiry/strike).
  Phase 3 just needs to produce plausible roll candidates; the roll decision logic lives in
  Phase 8 intraday monitor. Keep `rolling.py` simple.
- **`_scoring.py` placement:** inline helpers vs shared module. Either works; just be consistent
  so Phase 4 can import or replace them.
- **OptionQuote.dte property:** `OptionQuote.dte` calls `date.today()` — in tests, some DTE
  values may go negative if the test date is past the expiry. Use far-future expiries in test
  fixtures to avoid this fragility.
