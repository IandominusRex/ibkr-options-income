"""Read-only access to data/spreads.db for the web API (web overhaul Part 1, Task 8).

The spreads fence forbids src/api from importing src.spreads, so this module opens the file
itself with SQLite mode=ro and reads it with plain SQL. It yields None when the file does not
exist yet or cannot be opened (or is not a SQLite database), so a route answers
`available: false` instead of a 500.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, DateTime, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config

log = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

_COLUMNS = (
    "spread_id, mode, side, expiry, short_strike, long_strike, width, contracts_opened, "
    "contracts, entry_credit, entry_commission, opened_at, status, exit_debit, "
    "exit_commission, exit_reason, closed_at, realized_pnl_usd"
)


def _resolve_path() -> str:
    """Filesystem path of data/spreads.db. Patched in tests."""
    url = get_config().spreads_db_url_abs()
    return url[len("sqlite:///") :] if url.startswith("sqlite:///") else url


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


@contextmanager
def spreads_read_session() -> Iterator[Session | None]:
    global _engine, _SessionLocal
    path = _resolve_path()
    if not Path(path).exists():
        yield None
        return
    s: Session | None = None
    try:
        if _engine is None:
            _engine = create_engine(
                f"sqlite:///file:{path}?mode=ro&uri=true",
                future=True,
                connect_args={"timeout": 5},
            )
            _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
        assert _SessionLocal is not None
        s = _SessionLocal()
        # Reads the schema page: `SELECT 1` never touches the file, so a file that is not a
        # SQLite database would pass it and then read as an empty book.
        s.execute(text("SELECT count(*) FROM sqlite_master"))
    except Exception as exc:  # noqa: BLE001 - a /spreads route degrades, never 500s
        log.debug("api spreads_db: cannot open %s: %s", path, exc)
        if s is not None:
            s.close()
        yield None
        return
    try:
        yield s
    finally:
        s.close()


def try_read_spread_rows(
    session: Session, *, mode: str, status: str, limit: int
) -> list[dict[str, Any]] | None:
    """spread_positions rows as dicts, newest first, or None when the read failed (a missing
    table on an old file). `status` is open|closed|all; "open" includes "expiring" (still
    held, settling today)."""
    where = "mode = :mode"
    if status == "open":
        where += " AND status IN ('open', 'expiring')"
    elif status == "closed":
        where += " AND status = 'closed'"
    # Typed, so SQLite's stored strings come back as date/datetime (naive UTC, as written).
    sql = text(
        f"SELECT {_COLUMNS} FROM spread_positions WHERE {where} ORDER BY opened_at DESC LIMIT :limit"
    ).columns(expiry=Date, opened_at=DateTime, closed_at=DateTime)
    try:
        result = session.execute(sql, {"mode": mode, "limit": limit})
    except Exception as exc:  # noqa: BLE001 - the caller decides what unreadable means
        log.debug("api spreads_db: read failed: %s", exc)
        return None
    return [dict(r._mapping) for r in result]


def read_spread_rows(
    session: Session, *, mode: str, status: str, limit: int
) -> list[dict[str, Any]]:
    """`try_read_spread_rows`, with a failed read (a missing table on an old file) as empty."""
    rows = try_read_spread_rows(session, mode=mode, status=status, limit=limit)
    return rows if rows is not None else []


_PICK_COLUMNS = (
    "id, created_at, day, book_mode, menu, choice, reason, fallback_reason, executed_letter, "
    "send_rejected, send_reasons, filled, model, regime, side, plan_bias, event_flag"
)
_NEW_YORK = ZoneInfo("America/New_York")


def _json_list(raw: Any) -> list[Any] | None:
    """A JSON column read through plain SQL comes back as text. None when it is not a list."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        return value if isinstance(value, list) else None
    return None


def _columns_of(session: Session, table: str) -> set[str]:
    """Column names of a table; empty when the table does not exist (an older file)."""
    try:
        return {str(r[1]) for r in session.execute(text(f"PRAGMA table_info({table})"))}
    except Exception:  # noqa: BLE001 - an unreadable schema reads as no columns
        session.rollback()
        return set()


def _stamp(dt: datetime) -> str:
    """A naive-UTC datetime in the text form SQLAlchemy stores in SQLite, for plain-SQL ranges."""
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def try_read_pick_rows(session: Session, *, day: date) -> list[dict[str, Any]] | None:
    """spread_picks rows for one New York day (the service stamps `day` in New York), newest
    first, or None when the read failed (an older file without the table: the picker never ran).
    `menu` and `send_reasons` come back parsed; a `menu` that is not a JSON list is None."""
    sql = text(
        f"SELECT {_PICK_COLUMNS} FROM spread_picks WHERE day = :day "
        "ORDER BY created_at DESC, id DESC"
    ).columns(day=Date, created_at=DateTime)
    try:
        result = session.execute(sql, {"day": day.isoformat()})
    except Exception as exc:  # noqa: BLE001 - the caller decides what unreadable means
        log.debug("api spreads_db: pick read failed: %s", exc)
        session.rollback()  # the next read on this session starts clean
        return None
    rows: list[dict[str, Any]] = []
    for r in result:
        row = dict(r._mapping)
        row["menu"] = _json_list(row["menu"])
        row["send_reasons"] = _json_list(row["send_reasons"]) or []
        for flag in ("send_rejected", "filled", "event_flag"):
            row[flag] = bool(row[flag])
        rows.append(row)
    return rows


def try_read_spread_rows_opened(
    session: Session, *, start: datetime, end: datetime
) -> list[dict[str, Any]] | None:
    """spread_positions rows of every mode opened in [start, end) (naive UTC, as stored), oldest
    first, each with `pick_id` (None on an older file that has no such column), or None when the
    read failed."""
    pick = "pick_id" if "pick_id" in _columns_of(session, "spread_positions") else "NULL AS pick_id"
    sql = text(
        f"SELECT {_COLUMNS}, {pick} FROM spread_positions "
        "WHERE opened_at >= :start AND opened_at < :end ORDER BY opened_at"
    ).columns(expiry=Date, opened_at=DateTime, closed_at=DateTime)
    try:
        result = session.execute(sql, {"start": _stamp(start), "end": _stamp(end)})
    except Exception as exc:  # noqa: BLE001 - the caller decides what unreadable means
        log.debug("api spreads_db: opened read failed: %s", exc)
        session.rollback()
        return None
    return [dict(r._mapping) for r in result]


def read_activity_days(session: Session) -> set[date]:
    """New York days with a pick or an opened spread, for the day navigation. A table an older
    file lacks contributes nothing."""
    days: set[date] = set()
    try:
        for (d,) in session.execute(
            text("SELECT DISTINCT day FROM spread_picks").columns(day=Date)
        ):
            if d is not None:
                days.add(d)
    except Exception:  # noqa: BLE001 - no picks table: the picker never ran
        session.rollback()
    try:
        opened = text("SELECT opened_at FROM spread_positions").columns(opened_at=DateTime)
        for (at,) in session.execute(opened):
            if at is not None:
                days.add(at.replace(tzinfo=UTC).astimezone(_NEW_YORK).date())
    except Exception:  # noqa: BLE001
        session.rollback()
    return days


def try_read_spread_order_rows(
    session: Session, *, start: datetime, limit: int
) -> list[dict[str, Any]] | None:
    """spread_orders rows created at or after *start* (naive UTC, as stored), newest first, each
    joined to its position for `mode`, `side`, `expiry` and the strikes (None when the position
    row is missing).

    An older file that has no `spread_orders` table at all has nothing to read: an empty list.
    None means the read failed (the table exists and cannot be read, or the check itself failed),
    which the caller must not present as "no orders"."""
    try:
        present = (
            session.execute(
                text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'spread_orders'")
            ).first()
            is not None
        )
    except Exception as exc:  # noqa: BLE001 - an unreadable schema is a failed read, not an empty one
        log.debug("api spreads_db: order table check failed: %s", exc)
        session.rollback()
        return None
    if not present:
        return []
    sql = text(
        "SELECT o.id, o.spread_id, o.kind, o.ib_order_id, o.perm_id, o.filled_qty, o.price, "
        "o.commission, o.reason, o.created_at, p.mode, p.side, p.expiry, p.short_strike, "
        "p.long_strike FROM spread_orders o LEFT JOIN spread_positions p "
        "ON p.spread_id = o.spread_id WHERE o.created_at >= :start "
        "ORDER BY o.created_at DESC, o.id DESC LIMIT :limit"
    ).columns(created_at=DateTime, expiry=Date)
    try:
        result = session.execute(sql, {"start": _stamp(start), "limit": limit})
    except Exception as exc:  # noqa: BLE001 - the caller decides what unreadable means
        log.debug("api spreads_db: order read failed: %s", exc)
        session.rollback()
        return None
    return [dict(r._mapping) for r in result]
