"""Trigger conditions for the intraday monitor.

Each check_* function is a pure function: given position + market data + thresholds,
it returns a RollAlert when its condition is met, or None when not triggered.
call check_all() to run all four triggers in one pass.
"""

from __future__ import annotations

from datetime import date

from src.common.schemas import FundamentalStats, OptionQuote, PositionSnapshot, RollAlert


def check_delta_drift(
    pos: PositionSnapshot,
    quote: OptionQuote,
    delta_ceiling: float,
) -> RollAlert | None:
    """Fire if |delta| has drifted above delta_ceiling for a short option."""
    if pos.position >= 0:
        return None
    if quote.delta is None:
        return None
    if abs(quote.delta) > delta_ceiling:
        return RollAlert(
            position_symbol=pos.symbol,
            underlying=pos.underlying or pos.symbol,
            trigger="delta_drift",
            detail=f"delta={quote.delta:.2f} > ceiling={delta_ceiling}",
            current_delta=quote.delta,
            dte=quote.dte,
        )
    return None


def check_dte_threshold(
    pos: PositionSnapshot,
    dte_threshold: int,
) -> RollAlert | None:
    """Fire when the position's DTE has dropped to or below the threshold."""
    if pos.position >= 0:
        return None
    if pos.expiry is None:
        return None
    dte = (pos.expiry - date.today()).days
    if dte <= dte_threshold:
        return RollAlert(
            position_symbol=pos.symbol,
            underlying=pos.underlying or pos.symbol,
            trigger="dte",
            detail=f"DTE={dte} <= threshold={dte_threshold}",
            dte=dte,
        )
    return None


def check_iv_spike(
    pos: PositionSnapshot,
    quote: OptionQuote,
    entry_iv: float,
    spike_pct: float,
) -> RollAlert | None:
    """Fire when IV has risen more than spike_pct% above entry_iv."""
    if pos.position >= 0:
        return None
    if quote.iv is None or entry_iv <= 0:
        return None
    change_pct = (quote.iv - entry_iv) / entry_iv * 100.0
    if change_pct > spike_pct:
        return RollAlert(
            position_symbol=pos.symbol,
            underlying=pos.underlying or pos.symbol,
            trigger="iv_spike",
            detail=f"IV={quote.iv:.2%} (+{change_pct:.1f}% vs entry {entry_iv:.2%})",
            current_delta=quote.delta,
            dte=quote.dte,
        )
    return None


# Below this |delta| a short call is far enough OTM that early assignment to capture the
# dividend is economically irrational (remaining extrinsic value exceeds the dividend), so
# the ex-div alert is just noise. Only applied when a live delta is available.
_EX_DIV_MIN_DELTA = 0.50


def check_ex_div(
    pos: PositionSnapshot,
    fund_stats: FundamentalStats,
    days_ahead: int,
    quote: OptionQuote | None = None,
) -> RollAlert | None:
    """Fire when ex-div date is within days_ahead for an *ITM-ish* short call.

    Real early-assignment risk requires the call to be in/near the money (the dividend must
    exceed remaining extrinsic). When the live quote carries a delta, OTM calls (|delta| <
    threshold) are suppressed; without a delta we keep the conservative original behaviour.
    """
    if pos.position >= 0:
        return None
    from src.common.schemas import OptionRight

    if pos.right != OptionRight.CALL:
        return None
    if fund_stats.ex_dividend_date is None:
        return None
    if quote is not None and quote.delta is not None and abs(quote.delta) < _EX_DIV_MIN_DELTA:
        return None  # OTM short call — no real assignment risk into the dividend
    days_to_ex = (fund_stats.ex_dividend_date - date.today()).days
    if 0 <= days_to_ex <= days_ahead:
        dte = (pos.expiry - date.today()).days if pos.expiry else None
        return RollAlert(
            position_symbol=pos.symbol,
            underlying=pos.underlying or pos.symbol,
            trigger="ex_div",
            detail=f"ex-div in {days_to_ex} day(s) ({fund_stats.ex_dividend_date})",
            dte=dte,
        )
    return None


def check_all(
    pos: PositionSnapshot,
    quote: OptionQuote,
    entry_iv: float | None,
    fund_stats: FundamentalStats | None,
    limits: dict,
) -> list[RollAlert]:
    """Run all four triggers and return every alert that fires.

    Pass entry_iv=None to skip the IV-spike check (no entry data available).
    Pass fund_stats=None to skip the ex-div check.
    """
    alerts: list[RollAlert] = []

    alert = check_delta_drift(pos, quote, limits.get("delta_ceiling", 0.45))
    if alert:
        alerts.append(alert)

    alert = check_dte_threshold(pos, limits.get("dte_threshold", 7))
    if alert:
        alerts.append(alert)

    if entry_iv is not None:
        alert = check_iv_spike(pos, quote, entry_iv, limits.get("iv_spike_pct", 40.0))
        if alert:
            alerts.append(alert)

    if fund_stats is not None:
        alert = check_ex_div(pos, fund_stats, limits.get("ex_div_days_ahead", 5), quote=quote)
        if alert:
            alerts.append(alert)

    return alerts
