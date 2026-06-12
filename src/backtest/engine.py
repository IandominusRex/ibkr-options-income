"""Deterministic option-income backtest core.

`simulate` walks a daily close series, writing non-overlapping short-premium cycles (the
"wheel" cadence: each cycle starts the day the previous one expires) and settling each at
expiry against the realised close. Premiums are Black-Scholes-priced from the underlying spot
and its trailing 30-day realised volatility (the IV proxy — the system has no historical IV
series), and the strike is chosen as the listed-ish strike whose model delta is closest to the
target.

Model & assumptions (documented because they bound how far to trust the output):
  * European, **cash-settled at expiry** — no early assignment, no intraday path dependence.
  * Premium = Black-Scholes mid at entry using trailing HV as IV; no bid/ask spread.
  * Short-option income only. For a covered call this is the *option overlay* P&L
    (premium − call-away intrinsic); the underlying's own appreciation is reported separately
    as the buy-&-hold benchmark, not added in. For a cash-secured put it is premium − put
    intrinsic, with collateral = strike × 100.
  * Flat per-contract-per-side commission (default 0). No slippage, no dividends, no margin.
  * Trailing HV needs ≥ 31 prior closes; cycles before that (or with degenerate BS inputs)
    are skipped.

Pure and offline: takes an in-memory price series, returns a `BacktestResult`. The yfinance
loader lives in `data.py` so this core is unit-testable without a network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from src.analytics.black_scholes import bs_delta, bs_price

# Trading days per year for annualising realised vol from daily log returns.
_TRADING_DAYS = 252
_HV_WINDOW = 30
OPTION_MULTIPLIER = 100


@dataclass(frozen=True)
class BacktestParams:
    """Strategy + pricing knobs for a backtest run."""

    strategy: str  # "covered_call" | "cash_secured_put"
    target_delta: float = 0.30  # |delta| to target when choosing the strike
    dte: int = 30  # calendar days to expiry per cycle
    contracts: int = 1
    risk_free_rate: float = 0.05
    commission_per_contract: float = 0.65  # charged per contract on entry only (short premium)

    @property
    def right(self) -> str:
        return "C" if self.strategy == "covered_call" else "P"


@dataclass(frozen=True)
class BacktestTrade:
    """One settled cycle."""

    entry_date: date
    expiry_date: date
    right: str
    spot_at_entry: float
    strike: float
    premium: float  # per share
    spot_at_expiry: float
    intrinsic_cost: float  # per share paid to the long at expiry (max(0, …))
    pnl: float  # dollars for the whole position (contracts × 100), net of commission
    assigned: bool


@dataclass
class BacktestResult:
    """Aggregate outcome of a backtest run."""

    symbol: str
    strategy: str
    start: date
    end: date
    params: BacktestParams
    trades: list[BacktestTrade] = field(default_factory=list)
    total_premium: float = 0.0  # gross premium collected (dollars)
    total_pnl: float = 0.0  # net P&L (dollars), premium − intrinsic − commission
    num_cycles: int = 0
    win_rate: float = 0.0  # fraction of cycles with pnl > 0
    assignment_rate: float = 0.0
    capital_base: float = 0.0  # collateral committed (first cycle), dollars
    return_on_capital_pct: float = 0.0
    annualized_return_pct: float = 0.0
    buy_hold_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0


def _trailing_hv(closes: list[float], end_idx: int) -> float | None:
    """Annualised trailing realised vol (decimal) from log returns ending at ``end_idx``."""
    if end_idx < _HV_WINDOW:
        return None
    window = closes[end_idx - _HV_WINDOW : end_idx + 1]
    rets = [math.log(window[i] / window[i - 1]) for i in range(1, len(window)) if window[i - 1] > 0]
    if len(rets) < _HV_WINDOW:
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    hv = math.sqrt(var) * math.sqrt(_TRADING_DAYS)
    return hv if hv > 0 else None


def _strike_for_delta(spot: float, dte: int, iv: float, right: str, target_delta: float, r: float) -> float | None:
    """Pick the strike whose model |delta| is closest to ``target_delta``.

    Scans a $0.50-granular grid spanning ±35% of spot (wide enough to bracket any sane income
    delta), rounding candidate strikes to a listed-like increment so results are stable.
    """
    step = max(0.5, round(spot * 0.005 / 0.5) * 0.5)  # ~0.5% of spot, min $0.50, on a $0.50 grid
    lo = spot * 0.65
    hi = spot * 1.35
    best: float | None = None
    best_err = float("inf")
    k = math.ceil(lo / step) * step
    while k <= hi:
        d = bs_delta(spot, k, dte, iv, right, r)
        if d is not None:
            err = abs(abs(d) - target_delta)
            if err < best_err:
                best_err, best = err, k
        k += step
    return best


def simulate(
    symbol: str,
    prices: list[tuple[date, float]],
    params: BacktestParams,
) -> BacktestResult:
    """Run the income simulation over ``prices`` (ascending by date) and return the aggregate.

    Never raises on ordinary data shortfalls — an empty/short series yields a zero-cycle result.
    """
    result = BacktestResult(
        symbol=symbol,
        strategy=params.strategy,
        start=prices[0][0] if prices else date.today(),
        end=prices[-1][0] if prices else date.today(),
        params=params,
    )
    if len(prices) < _HV_WINDOW + 2:
        return result

    dates = [d for d, _ in prices]
    closes = [c for _, c in prices]
    mult = OPTION_MULTIPLIER * params.contracts

    entry_idx = _HV_WINDOW  # first index with enough trailing history
    while entry_idx < len(prices):
        expiry_idx = _find_expiry_idx(dates, entry_idx, params.dte)
        if expiry_idx is None:
            break  # not enough data left for a full cycle

        spot = closes[entry_idx]
        iv = _trailing_hv(closes, entry_idx)
        dte_actual = (dates[expiry_idx] - dates[entry_idx]).days
        if iv is not None and dte_actual > 0:
            strike = _strike_for_delta(spot, dte_actual, iv, params.right, params.target_delta, params.risk_free_rate)
            premium = (
                bs_price(spot, strike, dte_actual, iv, params.right, params.risk_free_rate)
                if strike is not None
                else None
            )
            if strike is not None and premium is not None and premium > 0:
                s_t = closes[expiry_idx]
                if params.right == "C":
                    intrinsic = max(0.0, s_t - strike)
                else:
                    intrinsic = max(0.0, strike - s_t)
                commission = params.commission_per_contract * params.contracts
                pnl = (premium - intrinsic) * mult - commission
                result.trades.append(
                    BacktestTrade(
                        entry_date=dates[entry_idx],
                        expiry_date=dates[expiry_idx],
                        right=params.right,
                        spot_at_entry=spot,
                        strike=strike,
                        premium=round(premium, 4),
                        spot_at_expiry=s_t,
                        intrinsic_cost=round(intrinsic, 4),
                        pnl=round(pnl, 2),
                        assigned=intrinsic > 0,
                    )
                )
        entry_idx = expiry_idx  # next cycle opens when this one expires

    _finalize(result, closes, dates, mult)
    return result


def _find_expiry_idx(dates: list[date], entry_idx: int, dte: int) -> int | None:
    """First index on/after entry_date + dte. None if the series ends before then."""
    target = dates[entry_idx].toordinal() + dte
    for i in range(entry_idx + 1, len(dates)):
        if dates[i].toordinal() >= target:
            return i
    return None


def _finalize(result: BacktestResult, closes: list[float], dates: list[date], mult: int) -> None:
    trades = result.trades
    result.num_cycles = len(trades)
    if not trades:
        return

    result.total_premium = round(sum(t.premium for t in trades) * mult, 2)
    result.total_pnl = round(sum(t.pnl for t in trades), 2)
    wins = sum(1 for t in trades if t.pnl > 0)
    assigned = sum(1 for t in trades if t.assigned)
    result.win_rate = round(wins / len(trades), 4)
    result.assignment_rate = round(assigned / len(trades), 4)

    first = trades[0]
    if first.right == "P":
        result.capital_base = first.strike * mult
    else:
        result.capital_base = first.spot_at_entry * mult
    if result.capital_base > 0:
        total_return = result.total_pnl / result.capital_base
        result.return_on_capital_pct = round(total_return * 100, 4)
        span_days = (dates[-1] - dates[0]).days
        if span_days > 0:
            result.annualized_return_pct = round(
                ((1 + total_return) ** (365 / span_days) - 1) * 100, 4
            )

    if closes[0] > 0:
        result.buy_hold_return_pct = round((closes[-1] / closes[0] - 1) * 100, 4)
    result.max_drawdown_pct = _max_drawdown_pct(trades, result.capital_base)


def _max_drawdown_pct(trades: list[BacktestTrade], capital_base: float) -> float:
    """Max peak-to-trough drop of the cumulative-P&L equity curve, as % of capital base."""
    if capital_base <= 0:
        return 0.0
    equity = capital_base
    peak = equity
    max_dd = 0.0
    for t in trades:
        equity += t.pnl
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return round(max_dd * 100, 4)
