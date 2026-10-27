"""Account value over time — read-only, like the rest of src/reporting/.

Two sources, one shape: the EOD journal (one net-liquidation point per trading day) and the
intraday `portfolio_snapshots` table (every ~15 minutes, 30-day retention). Imports nothing
from the enrichment layer or the API package (tests/test_web_fence.py greps for the names).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.schemas import (
    AccountSnapshot,
    AccountValuePoint,
    AccountValueRange,
    AccountValueSeries,
)
from src.reporting import pnl
from src.reporting.pnl import _net_liquidation_from_payload
from src.storage.models import JournalRow, PortfolioSnapshotRow

_ET = ZoneInfo("America/New_York")
_SessionFactory = Callable[[], AbstractContextManager[Session]]
_INTRADAY_DAYS = {"1d": 1, "1w": 7}
_DAILY_DAYS = {"1m": 31, "3m": 92}
_LATEST_SCAN = 50  # newest snapshots searched for one with a known value


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _naive_utc(dt: datetime) -> datetime:
    return _as_utc(dt).replace(tzinfo=None)


def _known(value: float | None) -> float | None:
    """A net liquidation of 0 or less is unknown, not an account worth $0: IBKR's account
    summary can come back without its NetLiquidation tag, and 0.0 is what gets stored then."""
    return value if value is not None and value > 0 else None


def _journal_value(entry_date: date, payload: dict) -> float | None:
    """A journal day's net liquidation, USD only: earlier days were written in SGD."""
    if entry_date < pnl.NET_LIQ_USD_FROM_DAY:
        return None
    return _known(_net_liquidation_from_payload(payload))


def _snap_value(row: PortfolioSnapshotRow) -> float | None:
    if _naive_utc(row.captured_at) < pnl.NET_LIQ_USD_FROM:
        return None  # captured in SGD
    try:
        return _known(AccountSnapshot.model_validate(row.account).net_liquidation)
    except Exception:
        return None


def _close_at(day: date) -> datetime:
    """A journal day plotted at that day's 16:00 ET close."""
    return datetime.combine(day, time(16, 0), tzinfo=_ET).astimezone(UTC)


def account_value_series(
    session: _SessionFactory, range_key: AccountValueRange, *, now: datetime
) -> AccountValueSeries:
    now_utc = _as_utc(now)
    today_et = now_utc.astimezone(_ET).date()
    with session() as sess:
        journal = (
            sess.execute(select(JournalRow).order_by(JournalRow.entry_date.asc())).scalars().all()
        )
        # The newest snapshot with a known value (a 0.0 capture is skipped, not the headline).
        recent = sess.execute(
            select(PortfolioSnapshotRow)
            .order_by(PortfolioSnapshotRow.captured_at.desc(), PortfolioSnapshotRow.id.desc())
            .limit(_LATEST_SCAN)
        ).scalars()
        latest_snap = next(
            ((row.captured_at, v) for row in recent if (v := _snap_value(row)) is not None), None
        )
        snaps: list[PortfolioSnapshotRow] = []
        if range_key in _INTRADAY_DAYS:
            start = _naive_utc(now - timedelta(days=_INTRADAY_DAYS[range_key]))
            snaps = list(
                sess.execute(
                    select(PortfolioSnapshotRow)
                    .where(PortfolioSnapshotRow.captured_at >= start)
                    .order_by(PortfolioSnapshotRow.captured_at.asc(), PortfolioSnapshotRow.id.asc())
                ).scalars()
            )

    daily = [(r.entry_date, _journal_value(r.entry_date, r.payload)) for r in journal]
    # A journal day is a close only once its 16:00 ET has passed: a row for today written early
    # is not yet a close, so it neither plots nor competes with a live snapshot.
    closes = [(d, v) for d, v in daily if v is not None and _close_at(d) <= now_utc]

    # The newer of the latest snapshot and the latest close, compared as instants: after the
    # close the official close leads, and a monitor that stopped days ago never does.
    latest: float | None = None
    latest_at: datetime | None = None
    if latest_snap is not None:
        latest, latest_at = latest_snap[1], _as_utc(latest_snap[0])
    if closes and (latest_at is None or _close_at(closes[-1][0]) > latest_at):
        latest, latest_at = closes[-1][1], _close_at(closes[-1][0])

    points: list[AccountValuePoint] = []
    if range_key in _INTRADAY_DAYS:
        for row in snaps:
            if (v := _snap_value(row)) is not None:
                points.append(AccountValuePoint(at=_as_utc(row.captured_at), value=v))
        # After the close the headline is that close: the chart ends on it too.
        window_start = now_utc - timedelta(days=_INTRADAY_DAYS[range_key])
        if (
            latest is not None
            and latest_at is not None
            and latest_at >= window_start
            and (not points or latest_at > points[-1].at)
        ):
            points.append(AccountValuePoint(at=latest_at, value=latest))
    else:
        if range_key == "ytd":
            start_day: date | None = date(today_et.year, 1, 1)
        elif range_key == "all":
            start_day = None
        else:
            start_day = today_et - timedelta(days=_DAILY_DAYS[range_key])
        for d, v in closes:
            if start_day is None or d >= start_day:
                points.append(AccountValuePoint(at=_close_at(d), value=v))
        if (
            latest is not None
            and latest_at is not None
            and (not points or latest_at > points[-1].at)
        ):
            points.append(AccountValuePoint(at=latest_at, value=latest))

    # The close before the New York day `latest` belongs to. The change is "today's" only when
    # that day is today; on a weekend or before today's first snapshot it is unknown, never 0.
    latest_day = latest_at.astimezone(_ET).date() if latest_at is not None else None
    before = [v for d, v in closes if latest_day is not None and d < latest_day]
    previous_close = before[-1] if before else None
    change = (
        latest - previous_close
        if latest is not None and previous_close is not None and latest_day == today_et
        else None
    )
    change_pct = change / previous_close * 100 if change is not None and previous_close else None

    return AccountValueSeries(
        range=range_key,
        points=points,
        latest=latest,
        latest_at=latest_at,
        previous_close=previous_close,
        change_today=change,
        change_today_pct=change_pct,
    )


def month_start_value(session: _SessionFactory, first_day: date) -> float | None:
    """Net liquidation at the last journal close before `first_day` with a known (> 0) USD value;
    None when there is none (the days before 2026-10-09 were written in SGD and are not used)."""
    with session() as sess:
        rows = sess.execute(
            select(JournalRow)
            .where(JournalRow.entry_date < first_day)
            .order_by(JournalRow.entry_date.desc())
        ).scalars()
        for r in rows:
            v = _journal_value(r.entry_date, r.payload)
            if v is not None:
                return v
    return None
