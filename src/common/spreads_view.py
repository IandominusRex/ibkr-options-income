"""The wheel's read-only window onto the spreads book's P&L (risk-envelope Task 6, spec §3.2c).

``data/spreads.db`` opened ``mode=ro`` with plain SQL, the ``value_view`` pattern. It imports
nothing from the spreads package and no enrichment, so the execution path (the circuit
breakers' daily loss leg) may import it; ``tests/test_web_fence.py`` keeps it the one reader of
that file outside ``src/api/`` and the book itself.

Only the book's real modes count (ruling P12): ``paper`` and ``live`` rows are positions IBKR
holds or held; ``shadow`` and ``baseline`` rows are simulated and never reach the account.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.common.config import get_config

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
REAL_MODES = ("paper", "live")


def _path() -> Path | None:
    url = get_config().spreads_db_url_abs()
    if not url.startswith("sqlite:///"):
        return None
    return Path(url[len("sqlite:///") :])


def connect() -> sqlite3.Connection | None:
    """A read-only connection to spreads.db, or None when the file does not exist."""
    path = _path()
    if path is None or not path.exists():
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _et_day(raw: str | None) -> date | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw).replace(tzinfo=UTC).astimezone(_ET).date()


def pnl_today(day: date) -> float | None:
    """The spreads book's P&L on ET *day* in its real modes: the realised P&L of spreads closed
    that day (and of the part already closed of one still open), plus (entry credit − latest
    mid debit) × 100 × contracts still open. None when the file is missing or unreadable."""
    try:
        con = connect()
    except sqlite3.Error:
        log.warning("spreads_view: spreads.db could not be opened", exc_info=True)
        return None
    if con is None:
        return None
    # Rows that can matter to *day*: anything still open, or opened since the day before.
    since = (
        datetime(day.year, day.month, day.day, tzinfo=_ET).astimezone(UTC) - timedelta(days=1)
    ).replace(tzinfo=None)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(spread_positions)")}
        if not cols:
            return 0.0  # an empty database: nothing has ever traded
        mark = "last_mid_debit" if "last_mid_debit" in cols else "NULL"
        rows = con.execute(
            "SELECT status, opened_at, closed_at, realized_pnl_usd, entry_credit, contracts, "
            f"{mark} FROM spread_positions WHERE mode IN (?, ?) "
            "AND (status IN ('open', 'expiring') OR opened_at >= ?)",
            (*REAL_MODES, since.isoformat(sep=" ")),
        ).fetchall()
    except sqlite3.Error:
        log.warning("spreads_view: spreads.db could not be read", exc_info=True)
        return None
    finally:
        con.close()
    total = 0.0
    for status, opened_at, closed_at, realized, credit, contracts, last in rows:
        if status == "closed":
            if _et_day(closed_at) == day:
                total += float(realized or 0.0)
            continue
        if _et_day(opened_at) == day:
            total += float(realized or 0.0)  # the part of a 0DTE spread already closed today
        if last is not None:
            total += (float(credit) - float(last)) * 100.0 * int(contracts)
    return total
