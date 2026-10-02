"""Trigger conditions for the intraday monitor.

Each check_* function is a pure function: given position + market data + thresholds,
it returns a RollAlert when its condition is met, or None when not triggered.
call check_all() to run every trigger in one pass.

This module also owns the human-readable labels for the trigger codes it produces
(`TRIGGER_LABELS` + `humanize_trigger`). The labels moved here from
`src/notify/formatters.py` in M5 Task 5.3 so the Telegram formatter and the web API
import the one mapping rather than each keeping a copy — the trigger codes are this
module's internal vocabulary, so their human names belong beside them. The API
router populates `RollAlertSummary.trigger_label` through `humanize_trigger`, and
the web renders that verbatim; no second mapping lives anywhere.
"""

from __future__ import annotations

from src.common.assignment_risk import is_assignment_risk
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


def check_strike_breach(
    pos: PositionSnapshot,
    quote: OptionQuote,
) -> RollAlert | None:
    """Fire when the underlying has crossed a short option's strike (it is in the money).

    The one trigger that means a roll is genuinely needed rather than worth considering: a
    short put with the stock below its strike, or a short call with the stock above it. Reads
    the live underlying from the option ticker (``undPrice``); missing spot → no alert.
    """
    from src.common.schemas import OptionRight

    if pos.position >= 0 or pos.strike is None or pos.right is None:
        return None
    spot = quote.underlying_price
    if spot is None:
        return None
    if pos.right == OptionRight.PUT and spot < pos.strike:
        side = "below"
    elif pos.right == OptionRight.CALL and spot > pos.strike:
        side = "above"
    else:
        return None
    strike = f"{pos.strike:g}"
    return RollAlert(
        position_symbol=pos.symbol,
        underlying=pos.underlying or pos.symbol,
        trigger="strike_breach",
        detail=(
            f"{pos.underlying or pos.symbol} at ${spot:.2f} is {side} the ${strike} strike — "
            f"the short is in the money"
        ),
        current_delta=quote.delta,
        dte=quote.dte,
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
    the operator should act (roll out-and-up, buy to close, or let assignment proceed). The
    risk decision itself is delegated to ``src.common.assignment_risk.is_assignment_risk`` —
    the one definition also read by ``/options/shorts`` (Task 0.3) — so this function only
    computes DTE and owns the ``RollAlert`` it builds. Missing delta or expiry is treated as
    data unavailable — no alert.
    """
    dte = (pos.expiry - today_et()).days if pos.expiry is not None else None
    if not is_assignment_risk(
        position=pos.position,
        delta=quote.delta,
        dte=dte,
        delta_threshold=delta_threshold,
        dte_threshold=dte_threshold,
    ):
        return None
    assert quote.delta is not None and dte is not None  # guaranteed by is_assignment_risk
    abs_delta = abs(quote.delta)
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


def check_loss_multiple(
    pos: PositionSnapshot,
    quote: OptionQuote,
    entry_credit: float | None,
    multiple: float,
) -> RollAlert | None:
    """Fire when cost-to-close has reached *multiple* × the entry credit.

    The loss line that used to buy the short back outright (``automation.max_loss_multiple``).
    Outside the leveraged ETFs the system now proposes a defensive roll here instead of taking
    the loss — the caller passes ``entry_credit=None`` for a leveraged short, which the
    approval service's loss exit still closes. Cost-to-close is priced the same way as the
    loss exit's own check: mid, or the ask when there is no bid.
    """
    if pos.position >= 0 or entry_credit is None or entry_credit <= 0 or multiple <= 0:
        return None
    ask = quote.ask
    if ask is None or ask <= 0:
        return None
    bid = quote.bid or 0.0
    cost = (bid + ask) / 2 if bid > 0 else ask
    if cost < multiple * entry_credit:
        return None
    return RollAlert(
        position_symbol=pos.symbol,
        underlying=pos.underlying or pos.symbol,
        trigger="loss_multiple",
        detail=(
            f"Cost to close ${cost:.2f} is {cost / entry_credit:.1f}× the ${entry_credit:.2f} "
            f"credit — past the {multiple:g}× loss line. Not closing at a loss: roll out "
            f"(and away from the strike) or accept assignment"
        ),
        current_delta=quote.delta,
        dte=quote.dte,
    )


def check_all(
    pos: PositionSnapshot,
    quote: OptionQuote,
    entry_iv: float | None,
    fund_stats: FundamentalStats | None,
    limits: dict,
    entry_dte: int | None = None,
    entry_credit: float | None = None,
) -> list[RollAlert]:
    """Run all triggers and return every alert that fires.

    Pass entry_iv=None to skip the IV-spike check (no entry data available).
    Pass fund_stats=None to skip the ex-div check.
    Pass entry_credit=None to skip the loss-line check (no fill on record, or a leveraged ETF
    whose loss exit closes rather than rolls).
    ``entry_dte`` is the position's DTE on the day it was opened. The two expiry-window
    triggers (``manage_dte``, ``dte``) mark a point the position *crosses*; a position opened
    already inside a window never crossed it, so that trigger is skipped (2026-10-01: a
    TQQQ put opened at 9 DTE drew a "21-day management point" alert a minute after it
    filled). None (no fill on record) keeps the old always-fire behaviour.
    """
    alerts: list[RollAlert] = []

    alert = check_delta_drift(pos, quote, limits.get("delta_ceiling", 0.45))
    if alert:
        alerts.append(alert)

    alert = check_strike_breach(pos, quote)
    if alert:
        alerts.append(alert)

    dte_threshold = limits.get("dte_threshold", 7)
    if entry_dte is None or entry_dte > dte_threshold:
        alert = check_dte_threshold(pos, dte_threshold)
        if alert:
            alerts.append(alert)

    manage_dte = limits.get("manage_at_dte", 21)
    if entry_dte is None or entry_dte > manage_dte:
        alert = check_manage_at_dte(pos, manage_dte)
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

    alert = check_loss_multiple(pos, quote, entry_credit, limits.get("max_loss_multiple", 0.0))
    if alert:
        alerts.append(alert)

    return alerts


# ---------------------------------------------------------------------------
# Human-readable labels for the trigger codes above.
#
# The single mapping both the Telegram formatter (`src/notify/formatters.py`) and the web API
# (`src/api/routers/options.py`) import — M5 Task 5.3: "Do not write a second mapping; if it
# needs to be shared, move it somewhere both can import rather than copying it." The codes are
# this module's internal vocabulary; their human names belong beside them. Unknown codes
# de-snake-case, matching how `_humanize_reject_reason` degrades in the formatter.
# ---------------------------------------------------------------------------

TRIGGER_LABELS: dict[str, str] = {
    "delta_drift": "delta drift",
    "strike_breach": "strike breached",
    "dte": "nearing expiry",
    "manage_dte": "management point",
    "iv_spike": "IV spike",
    "ex_div": "ex-dividend",
    "assignment_risk": "assignment risk",
    "loss_multiple": "loss limit",
}


def humanize_trigger(code: str) -> str:
    """Return the human-readable label for a trigger code, de-snake-casing unknown codes."""
    return TRIGGER_LABELS.get(code, code.replace("_", " "))
