"""Anchors and loss exits for the scale-in ladder (deterministic tier; reads the trading DB).

The ladder (`src/analytics/scale_in.py`) places a name's next-lot zone below its **anchor**: the
underlying's price at the last CSP lot. This module finds that anchor, and finds the loss exits
that fire the ladder's name-level trigger and its same-day block. Both read the trading database
and write nothing.

**How a lot is found.** An opening order's frozen ``snapshot`` carries the candidate (strategy,
underlying, ``ideal.spot``). A *close* order (``execution/position_manager.py``) carries no
snapshot, and ``OrderRow`` has no ``underlying`` column. A buy-to-close **fill**, however,
carries the *opening* order's candidate id, so a close is tied to its lot by that id; a close
whose opening row is gone falls back to parsing a ``close:<SYM>:...`` candidate id (on the fill
or on its own order).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.common.schemas import OrderState, PositionSnapshot, Strategy
from src.storage.models import FillRow, OrderRow, PriceHistoryRow

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_EPS = 1e-9


def et_date(moment: datetime) -> date:
    """The ET calendar date of a stored datetime (SQLite hands back naive UTC)."""
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(_ET).date()


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """[start, end) of an ET day as naive UTC datetimes (the DB's convention)."""
    nxt = day + timedelta(days=1)
    start = datetime(day.year, day.month, day.day, tzinfo=_ET).astimezone(UTC)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=_ET).astimezone(UTC)
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# loss exits
# --------------------------------------------------------------------------- #


def _parse_close_symbol(candidate_id: str | None) -> str | None:
    """``close:SOXL:20261016:130:P`` -> ``SOXL``."""
    if candidate_id and candidate_id.startswith("close:"):
        parts = candidate_id.split(":")
        if len(parts) >= 2 and parts[1]:
            return parts[1].upper()
    return None


def _underlying_of_fill(session: Session, fill: FillRow) -> str | None:
    """The underlying a buy-to-close fill closed (see the module docstring)."""
    for (snap,) in session.query(OrderRow.snapshot).filter(
        OrderRow.candidate_id == fill.candidate_id
    ):
        if isinstance(snap, dict) and snap.get("underlying"):
            return str(snap["underlying"]).upper()
    parsed = _parse_close_symbol(fill.candidate_id)
    if parsed:
        return parsed
    close_order = session.get(OrderRow, fill.order_id)
    return _parse_close_symbol(close_order.candidate_id if close_order else None)


def _loss_exit_events(
    session: Session, since_utc: datetime, until_utc: datetime | None = None
) -> list[tuple[str, date]]:
    """``[(underlying, ET date)]`` of every loss-exit buy-to-close fill in the window."""
    query = session.query(FillRow).filter(
        FillRow.action == "BUY",
        FillRow.close_reason == "loss_exit",
        FillRow.filled_at >= since_utc,
    )
    if until_utc is not None:
        query = query.filter(FillRow.filled_at < until_utc)
    events: list[tuple[str, date]] = []
    for fill in query.all():
        symbol = _underlying_of_fill(session, fill)
        if symbol:
            events.append((symbol, et_date(fill.filled_at)))
    return events


def loss_exits_today(session: Session, *, today: date) -> list[str]:
    """Underlyings with a loss-exit buy-to-close fill on the ET day *today* (sorted, unique)."""
    start, end = _day_bounds_utc(today)
    return sorted({symbol for symbol, _ in _loss_exit_events(session, start, end)})


def recent_loss_exit_names(session: Session, *, days: int, today: date) -> set[str]:
    """Underlyings with a loss exit within the last *days* calendar days (today counts)."""
    start, _ = _day_bounds_utc(today - timedelta(days=days))
    return {
        sym for sym, when in _loss_exit_events(session, start) if 0 <= (today - when).days <= days
    }


def recent_loss_exit(session: Session, symbol: str, *, days: int, today: date) -> bool:
    """True when *symbol* had a loss exit within the last *days* calendar days (today counts)."""
    return symbol.upper() in recent_loss_exit_names(session, days=days, today=today)


# --------------------------------------------------------------------------- #
# anchors
# --------------------------------------------------------------------------- #


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _fill_moment(session: Session, order: OrderRow) -> datetime:
    """When the lot was filled: the latest SELL fill of the order, else the order's creation."""
    latest = (
        session.query(func.max(FillRow.filled_at))
        .filter(FillRow.order_id == order.id, FillRow.action == "SELL")
        .scalar()
    )
    return latest or order.created_at


def _closed_on(session: Session, order: OrderRow, today: date) -> date | None:
    """The ET date the lot stopped being open, or None while it still is.

    Closed when buy-to-close fills (a profit take, a loss exit or a roll) cover its quantity;
    otherwise closed on its expiry once that has passed (expired or assigned).
    """
    bought, last = (
        session.query(func.coalesce(func.sum(FillRow.filled_qty), 0.0), func.max(FillRow.filled_at))
        .filter(FillRow.candidate_id == order.candidate_id, FillRow.action == "BUY")
        .one()
    )
    if last is not None and float(bought) >= float(order.filled_qty) - _EPS:
        return et_date(last)
    expiry = _parse_date((order.snapshot or {}).get("expiry"))
    if expiry is not None and expiry < today:
        return expiry
    return None


def _lot_spot(
    session: Session, order: OrderRow, symbol: str, fill_day: date
) -> tuple[float, str] | None:
    """The underlying's price at the lot: the snapshot's spot, else the close on the fill date."""
    ideal = (order.snapshot or {}).get("ideal")
    spot = ideal.get("spot") if isinstance(ideal, dict) else None
    if isinstance(spot, int | float) and spot > 0:
        return float(spot), "order_snapshot"
    close = (
        session.query(PriceHistoryRow.close)
        .filter(PriceHistoryRow.symbol == symbol, PriceHistoryRow.obs_date <= fill_day)
        .order_by(PriceHistoryRow.obs_date.desc())
        .limit(1)
        .scalar()
    )
    if close is not None and close > 0:
        return float(close), "price_history"
    return None


def latest_anchor(
    session: Session,
    symbol: str,
    positions: list[PositionSnapshot],
    *,
    survival_days: int,
    today: date,
    spot: float | None = None,
) -> tuple[float, str, date] | None:
    """``(price, source, fill date)`` of *symbol*'s most recent CSP lot, or None (the first lot is free).

    In order: (1) the most recent CSP lot that is still open or closed within *survival_days*
    (a profit take or loss exit does not clear it, so a stop-out cannot reset the ladder), its
    price the order snapshot's ``ideal.spot``, else the ``price_history`` close on the fill
    date. A CSP order that has been **sent but is not yet filled** (``submitted``, or ``partial``
    before its fill is recorded) is a lot too, dated by its creation day (its last fill's, once
    it has one): a lot sent at 10:00 and still working at the 10:15 scan must anchor the ladder,
    or that scan would take the name for a first lot and propose a second at the same price. A
    cancelled or rejected order with no fill never counts, and a queued one has not been sent;
    (2) held shares' ``avg_cost`` (an assignment); (3) a short put in *positions* with no
    system fill: ``max(strike, spot)`` (*spot* defaults to the strike). Rolls never move it: a
    roll's own order is a ROLL, not a lot. The third item is the lot's fill date (ET), used by
    ``recovered(after=)``; shares and positions carry ``date.min`` (no date is known).
    """
    target = symbol.upper()
    lots = (
        session.query(OrderRow)
        .filter(
            or_(
                OrderRow.filled_qty > 0,
                OrderRow.state.in_([OrderState.SUBMITTED.value, OrderState.PARTIAL.value]),
            ),
            OrderRow.candidate_id.notlike("close:%"),
            func.json_extract(OrderRow.snapshot, "$.underlying") == target,
            func.json_extract(OrderRow.snapshot, "$.strategy") == Strategy.CASH_SECURED_PUT.value,
        )
        .all()
    )
    dated = sorted(
        ((_fill_moment(session, o), o) for o in lots), key=lambda mo: mo[0], reverse=True
    )
    for moment, order in dated:
        closed = _closed_on(session, order, today)
        if closed is not None and (today - closed).days > survival_days:
            continue
        fill_day = et_date(moment)
        priced = _lot_spot(session, order, target, fill_day)
        if priced is not None:
            return priced[0], priced[1], fill_day

    for p in positions:
        if p.sec_type == "STK" and p.symbol.upper() == target and p.position > 0 and p.avg_cost > 0:
            return float(p.avg_cost), "shares", date.min

    strikes = [
        p.strike
        for p in positions
        if p.sec_type == "OPT"
        and p.right is not None
        and p.right.value == "P"
        and p.position < 0
        and p.strike is not None
        and (p.underlying or p.symbol).upper() == target
    ]
    if strikes:
        strike = float(max(strikes))
        return max(strike, spot) if spot else strike, "position", date.min
    return None
