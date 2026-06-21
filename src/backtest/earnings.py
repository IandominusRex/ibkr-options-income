"""Earnings-cycle backtest + vol-crush mode (C10).

Segments a price series by historical earnings dates and evaluates strategy performance
across each inter-earnings window. Two modes:

  * Pre-earnings cycle  — enter after the previous earnings blackout clears, hold until the
    next earnings blackout starts (entry gated when the window is too narrow for the DTE).
  * Vol-crush mode      — also enter a short-DTE trade right after each earnings release while
    IV is still elevated but the binary event risk is resolved.

Pure and offline: takes in-memory price + earnings date lists, returns structured results.
The yfinance loader lives in ``data.py`` so this core is unit-testable without a network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from src.analytics.black_scholes import bs_price
from src.backtest.engine import (
    OPTION_MULTIPLIER,
    BacktestParams,
    BacktestTrade,
    _find_expiry_idx,
    _strike_for_delta,
    _trailing_hv,
)


@dataclass(frozen=True)
class EarningsCycleResult:
    """One inter-earnings window and its optional vol-crush follow-on."""

    earnings_date: date
    cycle_start: date
    cycle_end: date
    entry_gated: bool  # True when window was too narrow or data insufficient
    pre_earnings_trade: BacktestTrade | None = None
    vol_crush_trade: BacktestTrade | None = None


@dataclass
class EarningsCycleBacktestResult:
    """Aggregate outcome of an earnings-cycle backtest run."""

    symbol: str
    strategy: str
    params: BacktestParams
    blackout_before: int
    blackout_after: int
    vol_crush_dte: int | None
    cycles: list[EarningsCycleResult] = field(default_factory=list)
    # Pre-earnings leg aggregates
    num_pre_cycles: int = 0
    total_pre_pnl: float = 0.0
    pre_win_rate: float = 0.0
    pre_assignment_rate: float = 0.0
    # Vol-crush leg aggregates
    num_vol_crush_cycles: int = 0
    total_vol_crush_pnl: float = 0.0
    vol_crush_win_rate: float = 0.0


def _idx_on_or_after(dates: list[date], target: date) -> int | None:
    """First index whose date is >= target, or None."""
    for i, d in enumerate(dates):
        if d >= target:
            return i
    return None


def _idx_before(dates: list[date], target: date) -> int | None:
    """Last index whose date is < target, or None."""
    result = None
    for i, d in enumerate(dates):
        if d < target:
            result = i
    return result


def _make_trade(
    dates: list[date],
    closes: list[float],
    params: BacktestParams,
    entry_idx: int,
    expiry_idx: int,
    iv_series: list[float | None] | None,
) -> BacktestTrade | None:
    """Synthesise one BacktestTrade for the given entry/expiry indices. Returns None on bad inputs."""
    hv = _trailing_hv(closes, entry_idx)
    entry_iv: float | None = None
    if iv_series is not None and entry_idx < len(iv_series) and iv_series[entry_idx] is not None:
        entry_iv = iv_series[entry_idx]
    if entry_iv is None or entry_iv <= 0:
        entry_iv = hv
    if entry_iv is None or entry_iv <= 0:
        return None

    spot = closes[entry_idx]
    dte_actual = (dates[expiry_idx] - dates[entry_idx]).days
    if dte_actual <= 0:
        return None

    strike = _strike_for_delta(
        spot, dte_actual, entry_iv, params.right, params.target_delta, params.risk_free_rate
    )
    if strike is None:
        return None
    premium = bs_price(spot, strike, dte_actual, entry_iv, params.right, params.risk_free_rate)
    if premium is None or premium <= 0:
        return None

    mult = OPTION_MULTIPLIER * params.contracts
    commission = params.commission_per_contract * params.contracts
    s_t = closes[expiry_idx]
    intrinsic = max(0.0, s_t - strike) if params.right == "C" else max(0.0, strike - s_t)
    pnl = (premium - intrinsic) * mult - commission

    return BacktestTrade(
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
        entry_iv=round(entry_iv, 6),
        entry_hv=round(hv, 6) if hv is not None else None,
    )


def simulate_earnings_cycles(
    symbol: str,
    prices: list[tuple[date, float]],
    params: BacktestParams,
    earnings_dates: list[date],
    *,
    blackout_before: int = 14,
    blackout_after: int = 3,
    vol_crush_dte: int | None = None,
    iv_series: list[float | None] | None = None,
) -> EarningsCycleBacktestResult:
    """Backtest strategy behaviour across prior earnings cycles.

    For each earnings date in the series:
      1. Pre-earnings window: enter after previous-earnings blackout clears, exit before the
         next earnings blackout starts. Skip when the window is narrower than ``params.dte``.
      2. Vol-crush entry (when ``vol_crush_dte`` is set): enter ``blackout_after`` days after
         earnings using a short DTE so the short premium ride the IV crush as uncertainty resolves.

    Never raises — bad inputs yield a zero-cycle result.
    """
    result = EarningsCycleBacktestResult(
        symbol=symbol,
        strategy=params.strategy,
        params=params,
        blackout_before=blackout_before,
        blackout_after=blackout_after,
        vol_crush_dte=vol_crush_dte,
    )
    if not prices or not earnings_dates:
        return result

    dates = [d for d, _ in prices]
    closes = [c for _, c in prices]
    series_start, series_end = dates[0], dates[-1]

    # Filter to earnings dates within the price series window.
    relevant = sorted({e for e in earnings_dates if series_start <= e <= series_end})
    if not relevant:
        return result

    for e_idx, earnings in enumerate(relevant):
        prev_earnings = relevant[e_idx - 1] if e_idx > 0 else None

        # Pre-earnings window: from after the previous earnings blackout until just before this one.
        window_open = (
            (prev_earnings + timedelta(days=blackout_after)) if prev_earnings else series_start
        )
        window_close = earnings - timedelta(days=blackout_before)

        cycle_result = _build_pre_earnings_cycle(
            earnings, window_open, window_close, dates, closes, params, iv_series
        )
        result.cycles.append(cycle_result)

        # Vol-crush entry: short-DTE trade entered right after this earnings release.
        if vol_crush_dte is not None and not cycle_result.entry_gated:
            vc_entry_target = earnings + timedelta(days=blackout_after)
            vc_entry_idx = _idx_on_or_after(dates, vc_entry_target)
            if vc_entry_idx is not None:
                vc_expiry_idx = _find_expiry_idx(dates, vc_entry_idx, vol_crush_dte)
                if vc_expiry_idx is not None and vc_entry_idx >= 30:
                    vc_trade = _make_trade(
                        dates, closes, params, vc_entry_idx, vc_expiry_idx, iv_series
                    )
                    if vc_trade is not None:
                        # Replace the cycle result with the vol-crush trade attached.
                        result.cycles[-1] = EarningsCycleResult(
                            earnings_date=cycle_result.earnings_date,
                            cycle_start=cycle_result.cycle_start,
                            cycle_end=cycle_result.cycle_end,
                            entry_gated=cycle_result.entry_gated,
                            pre_earnings_trade=cycle_result.pre_earnings_trade,
                            vol_crush_trade=vc_trade,
                        )

    _finalize_earnings_result(result)
    return result


def _build_pre_earnings_cycle(
    earnings: date,
    window_open: date,
    window_close: date,
    dates: list[date],
    closes: list[float],
    params: BacktestParams,
    iv_series: list[float | None] | None,
) -> EarningsCycleResult:
    _gated = EarningsCycleResult(
        earnings_date=earnings,
        cycle_start=window_open,
        cycle_end=window_close,
        entry_gated=True,
    )
    entry_idx = _idx_on_or_after(dates, window_open)
    if entry_idx is None or entry_idx < 30:  # need 30 prior closes for trailing HV
        return _gated
    expiry_idx = _idx_before(dates, window_close + timedelta(days=1))
    if expiry_idx is None or entry_idx >= expiry_idx:
        return _gated
    if (dates[expiry_idx] - dates[entry_idx]).days < params.dte // 2:
        return _gated

    trade = _make_trade(dates, closes, params, entry_idx, expiry_idx, iv_series)
    return EarningsCycleResult(
        earnings_date=earnings,
        cycle_start=dates[entry_idx],
        cycle_end=dates[expiry_idx],
        entry_gated=trade is None,
        pre_earnings_trade=trade,
    )


def _finalize_earnings_result(result: EarningsCycleBacktestResult) -> None:
    pre_trades = [c.pre_earnings_trade for c in result.cycles if c.pre_earnings_trade]
    vc_trades = [c.vol_crush_trade for c in result.cycles if c.vol_crush_trade]

    result.num_pre_cycles = len(pre_trades)
    result.total_pre_pnl = round(sum(t.pnl for t in pre_trades), 2)
    if pre_trades:
        result.pre_win_rate = round(sum(1 for t in pre_trades if t.pnl > 0) / len(pre_trades), 4)
        result.pre_assignment_rate = round(
            sum(1 for t in pre_trades if t.assigned) / len(pre_trades), 4
        )

    result.num_vol_crush_cycles = len(vc_trades)
    result.total_vol_crush_pnl = round(sum(t.pnl for t in vc_trades), 2)
    if vc_trades:
        result.vol_crush_win_rate = round(
            sum(1 for t in vc_trades if t.pnl > 0) / len(vc_trades), 4
        )
