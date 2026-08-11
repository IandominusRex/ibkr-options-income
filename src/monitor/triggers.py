"""Trigger conditions for the intraday monitor.

Each check_* function is a pure function: given position + market data + thresholds,
it returns a RollAlert when its condition is met, or None when not triggered.
call check_all() to run all four triggers in one pass.
"""

from __future__ import annotations

from src.common.market_hours import today_et
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
            detail=(
                f"Delta {abs(quote.delta):.2f} has drifted past the {delta_ceiling:.2f} "
                f"roll line — the short is tracking the underlying more closely than intended"
            ),
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
    dte = (pos.expiry - today_et()).days
    if dte <= dte_threshold:
        return RollAlert(
            position_symbol=pos.symbol,
            underlying=pos.underlying or pos.symbol,
            trigger="dte",
            detail=(
                f"{dte} days left, inside the {dte_threshold}-day roll window — "
                f"gamma risk rises sharply from here"
            ),
            dte=dte,
        )
    return None


def check_manage_at_dte(
    pos: PositionSnapshot,
    manage_dte: int,
) -> RollAlert | None:
    """Fire at the mechanical management point, well before the gamma window.

    Entries sit at 21-45 DTE and ``check_dte_threshold`` fires at 7 days — by then the
    position has little extrinsic left and few good options. This is the decision point where
    closing, rolling, or explicitly holding are all still available.
    """
    if pos.position >= 0 or pos.expiry is None:
        return None
    dte = (pos.expiry - today_et()).days
    if dte > manage_dte:
        return None
    return RollAlert(
        position_symbol=pos.symbol,
        underlying=pos.underlying or pos.symbol,
        trigger="manage_dte",
        detail=(
            f"{dte} days left — the {manage_dte}-day management point. Close, roll, or "
            f"decide to hold while extrinsic value still makes all three viable"
        ),
        dte=dte,
    )


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
            detail=(
                f"IV has risen to {quote.iv:.1%} from {entry_iv:.1%} at entry "
                f"(+{change_pct:.0f}%) — buying this back now costs more than it did"
            ),
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
    days_to_ex = (fund_stats.ex_dividend_date - today_et()).days
    if 0 <= days_to_ex <= days_ahead:
        dte = (pos.expiry - today_et()).days if pos.expiry else None
        return RollAlert(
            position_symbol=pos.symbol,
            underlying=pos.underlying or pos.symbol,
            trigger="ex_div",
            detail=(
                f"Goes ex-dividend in {days_to_ex} day{'' if days_to_ex == 1 else 's'} "
                f"({fund_stats.ex_dividend_date:%b %d}) — an ITM short call can be assigned "
                f"early to capture it"
            ),
            dte=dte,
        )
    return None


def check_assignment_risk(
    pos: PositionSnapshot,
    quote: OptionQuote,
    delta_threshold: float,
    dte_threshold: int,
) -> RollAlert | None:
    """Fire when a short is deep-ITM (|delta| ≥ threshold) within dte_threshold days of expiry.

    This combined check targets genuine assignment risk: a high-delta short near expiry where
    the operator should act (roll out-and-up, buy to close, or let assignment proceed).
    Missing delta is treated as data unavailable — no alert.
    """
    if pos.position >= 0:
        return None
    if pos.expiry is None:
        return None
    if quote.delta is None:
        return None
    dte = (pos.expiry - today_et()).days
    abs_delta = abs(quote.delta)
    if abs_delta >= delta_threshold and dte <= dte_threshold:
        return RollAlert(
            position_symbol=pos.symbol,
            underlying=pos.underlying or pos.symbol,
            trigger="assignment_risk",
            detail=(
                f"Delta {abs_delta:.2f} at or past {delta_threshold:.2f} with {dte} days "
                f"left — assignment is a live possibility, not a tail risk"
            ),
            current_delta=quote.delta,
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
    """Run all triggers and return every alert that fires.

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

    alert = check_manage_at_dte(pos, limits.get("manage_at_dte", 21))
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

    alert = check_assignment_risk(
        pos,
        quote,
        limits.get("assignment_alert_delta", 0.70),
        limits.get("assignment_alert_dte", 21),
    )
    if alert:
        alerts.append(alert)

    return alerts
