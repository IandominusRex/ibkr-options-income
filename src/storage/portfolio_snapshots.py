"""Intraday portfolio-snapshot persistence for the web portfolio (P3-P4 M1 Task 1.1).

`portfolio_snapshots` is the API's data source for positions and account values: the API
cannot ask IBKR anything, so the processes that already hold an IB connection (the intraday
monitor, the `refresh` command, the EOD run) write down what IBKR said. Append-only, no
unique constraint, pruned by the EOD run to `storage.portfolio_snapshot_retention_days`.

Deliberately separate from `position_snapshots` (src/storage/positions.py): that table is
one row per ET trading day and assignment auto-detection diffs its rows. Never write both
from the same code path.

Best-effort throughout — never raises. The monitor calls `save_portfolio_snapshot` from
inside a live event loop whose real job is firing roll alerts; a failed snapshot write must
not interrupt it (mirrors save_position_snapshot's swallow-and-log discipline).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from src.common.market_hours import today_et
from src.common.schemas import AccountSnapshot, PortfolioSnapshot, PositionSnapshot
from src.storage.db import session_scope
from src.storage.models import PortfolioSnapshotRow

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def save_portfolio_snapshot(
    *,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    source: str,
    captured_at: datetime | None = None,
) -> int | None:
    """Append one snapshot. Returns the new row id, or None on any failure.

    NEVER RAISES. Callers include a live event loop whose real job is firing roll alerts;
    a failed snapshot write must not interrupt it. Mirrors save_position_snapshot's
    swallow-and-log discipline.
    """
    when = captured_at if captured_at is not None else datetime.now(UTC)
    try:
        row = PortfolioSnapshotRow(
            captured_at=when,
            source=source,
            account=account.model_dump(mode="json"),
            positions=[p.model_dump(mode="json") for p in positions],
        )
        with session_scope() as s:
            s.add(row)
        return int(row.id)
    except Exception:
        log.exception("save_portfolio_snapshot(%s) failed", source)
        return None


def load_latest_portfolio_snapshot(before: datetime | None = None) -> PortfolioSnapshot | None:
    """The newest snapshot (captured strictly before *before*, if given), or None when there is
    none. Never raises."""
    try:
        with session_scope() as s:
            q = s.query(PortfolioSnapshotRow)
            if before is not None:
                cutoff = before.astimezone(UTC).replace(tzinfo=None) if before.tzinfo else before
                q = q.filter(PortfolioSnapshotRow.captured_at < cutoff)
            row = q.order_by(PortfolioSnapshotRow.id.desc()).first()
            if row is None:
                return None
            return _row_to_snapshot(row)
    except Exception:
        log.exception("load_latest_portfolio_snapshot failed")
        return None


def latest_capture_time() -> datetime | None:
    """captured_at of the newest row without deserialising its payload. Never raises."""
    try:
        with session_scope() as s:
            value = (
                s.query(PortfolioSnapshotRow.captured_at)
                .order_by(PortfolioSnapshotRow.id.desc())
                .first()
            )
        if value is None:
            return None
        return _as_utc(value[0])
    except Exception:
        log.exception("latest_capture_time failed")
        return None


def window_high_net_liq(sessions: int, today: date | None = None) -> float:
    """Highest net liquidation the monitor recorded across the last ``sessions`` ET days on file
    (today included); 0.0 when nothing is recorded. The drawdown breaker's reference level: the
    monitor snapshots all day, so it does not depend on the breaker having run on a quiet day.
    Never raises."""
    today = today or today_et()
    since = datetime.combine(today - timedelta(days=sessions * 3 + 4), datetime.min.time())
    try:
        with session_scope() as s:
            rows = s.execute(
                select(
                    PortfolioSnapshotRow.captured_at,
                    func.json_extract(PortfolioSnapshotRow.account, "$.net_liquidation"),
                ).where(PortfolioSnapshotRow.captured_at >= since)
            ).all()
    except Exception:
        log.exception("window_high_net_liq failed")
        return 0.0
    best: dict[date, float] = {}
    for at, nlv in rows:
        captured = _as_utc(at)
        if captured is None or not nlv or float(nlv) <= 0:
            continue
        day = captured.astimezone(_ET).date()
        if day <= today:
            best[day] = max(best.get(day, 0.0), float(nlv))
    days = sorted(best)[-max(sessions, 1) :]
    return max((best[d] for d in days), default=0.0)


def prune_portfolio_snapshots(days: int) -> int:
    """Delete rows older than `days`. Returns how many were deleted. Never raises."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    try:
        with session_scope() as s:
            deleted = (
                s.query(PortfolioSnapshotRow)
                .filter(PortfolioSnapshotRow.captured_at < cutoff)
                .delete(synchronize_session=False)
            )
        if deleted:
            log.info("Pruned %d portfolio_snapshots row(s) older than %d days", deleted, days)
        return int(deleted or 0)
    except Exception:
        log.exception("portfolio_snapshots purge failed")
        return 0


def _row_to_snapshot(row: PortfolioSnapshotRow) -> PortfolioSnapshot:
    """Deserialize one row's JSON payloads into the read-side schema."""
    captured_at = _as_utc(row.captured_at)
    assert captured_at is not None  # non-nullable column
    return PortfolioSnapshot(
        captured_at=captured_at,
        source=row.source,  # type: ignore[arg-type]
        account=AccountSnapshot.model_validate(row.account),
        positions=[PositionSnapshot.model_validate(p) for p in row.positions],
    )


def _as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; give them back UTC-aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
