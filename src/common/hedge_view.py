"""Everyone else's read-only window onto the hedge book (risk-envelope Task 33; spec §3.10.9, H9).

The trading database file opened ``mode=ro`` with plain SQL over the ``hedge_*`` tables, the
``spreads_view`` / ``value_view`` pattern. It imports only ``src.common.config`` and the standard
library, so the Rules Engine (the clash rules), ``get_positions`` (dropping hedge contracts by
``conId``), the circuit breakers (the daily leg, net) and the envelope (the net measures) may read
it without importing ``src.hedge``. Only ``src/hedge/`` writes these tables.

* ``open_hedges()`` -> the open positions (contracts from the fills: an opening buy adds, a sale,
  a settlement or a lapse subtracts) plus any opening order still working (0 contracts, its legs
  held for the clash rules). ``None`` when the file exists but cannot be read (callers fail
  closed); an empty list when it, or the tables, do not exist yet (no hedge was ever placed).
* ``hedge_con_ids()`` -> the ``conId`` of every leg in ``open_hedges()``.
* ``marks_today(day)`` / ``pnl_today(day)`` -> the day's marks and the book's P&L for the ET day
  (latest mark today less the latest before it, plus the day's cash flows), signed.
* ``spend()`` -> premium paid less received over every fill (the H3 net premium).
* ``latest_programme()`` -> the bridge programme's latest row as a plain mapping.
* ``leg_quotes(con_ids)`` -> each contract's newest captured quote (the envelope's net lines).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.common.config import get_config

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_WORKING = ("submitted", "working")  # "partial" is final: part filled, the rest cancelled
_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class OpenLeg:
    action: str  # BUY (long) | SELL (a vertical's short leg)
    right: str
    strike: float
    expiry: date
    con_id: int | None


@dataclass(frozen=True, slots=True)
class OpenHedge:
    """One hedge position: ``contracts`` open now (0 for an opening still working), ``cost`` the
    open contracts' premium at cost in dollars, ``working`` True while an order on it works."""

    hedge_id: str
    instrument: str
    kind: str
    legs: tuple[OpenLeg, ...]
    contracts: float
    multiplier: int
    cost: float
    opened_on: date | None
    working: bool = False

    @property
    def expiry(self) -> date | None:
        return min((leg.expiry for leg in self.legs), default=None)


def _path() -> Path | None:
    url = get_config().db_url_abs()
    if not url.startswith("sqlite:///"):
        return None
    return Path(url[len("sqlite:///") :])


def connect() -> sqlite3.Connection | None:
    """A read-only connection to the trading database, or None when the file does not exist."""
    path = _path()
    if path is None or not path.exists():
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if str(r[0]).startswith("hedge_")
    }


def _day(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _et_day(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).replace(tzinfo=UTC).astimezone(_ET).date()
    except ValueError:
        return None


def _legs(raw: Any) -> tuple[OpenLeg, ...]:
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        return ()
    out: list[OpenLeg] = []
    for it in items:
        exp = _day(it.get("expiry"))
        if exp is None:
            continue
        cid = it.get("con_id")
        out.append(
            OpenLeg(
                action=str(it.get("action", "BUY")).upper(),
                right=str(it.get("right", "P")).upper()[:1],
                strike=float(it.get("strike") or 0.0),
                expiry=exp,
                con_id=int(cid) if cid else None,
            )
        )
    return tuple(out)


def _read(fn: Any) -> Any:
    """Run *fn(con)* on a read-only connection. ``[]``-style empty results when the file or the
    tables are missing (``fn`` receives None); None when the file cannot be read."""
    try:
        con = connect()
    except sqlite3.Error:
        log.warning("hedge_view: the trading database could not be opened", exc_info=True)
        return None
    if con is None:
        return fn(None)
    try:
        if not {"hedge_orders", "hedge_fills"} <= _tables(con):
            return fn(None)
        return fn(con)
    except sqlite3.Error:
        log.warning("hedge_view: the hedge tables could not be read", exc_info=True)
        return None
    finally:
        con.close()


def _open(con: sqlite3.Connection | None) -> list[OpenHedge]:
    if con is None:
        return []
    orders = con.execute(
        "SELECT hedge_id, instrument, intent, kind, multiplier, legs, state, created_at "
        "FROM hedge_orders ORDER BY id"
    ).fetchall()
    fills = con.execute("SELECT hedge_id, qty, cash FROM hedge_fills").fetchall()
    qty: dict[str, float] = {}
    bought: dict[str, float] = {}
    paid: dict[str, float] = {}
    for hid, q, cash in fills:
        qty[hid] = qty.get(hid, 0.0) + float(q)
        if float(q) > 0:
            bought[hid] = bought.get(hid, 0.0) + float(q)
            paid[hid] = paid.get(hid, 0.0) - float(cash)
    opening: dict[str, tuple[Any, ...]] = {}
    working: set[str] = set()
    for hid, instrument, intent, kind, mult, legs, state, created in orders:
        if intent == "open" and hid not in opening:
            opening[hid] = (instrument, kind, mult, legs, created)
        if state in _WORKING:
            working.add(hid)
    out: list[OpenHedge] = []
    for hid, (instrument, kind, mult, legs, created) in opening.items():
        n = qty.get(hid, 0.0)
        if n <= _EPS and hid not in working:
            continue
        unit = paid.get(hid, 0.0) / bought[hid] if bought.get(hid) else 0.0
        out.append(
            OpenHedge(
                hedge_id=hid,
                instrument=str(instrument).upper(),
                kind=str(kind),
                legs=_legs(legs),
                contracts=max(0.0, n),
                multiplier=int(mult or 100),
                cost=max(0.0, n) * unit,
                opened_on=_et_day(created),
                working=hid in working,
            )
        )
    return out


def open_hedges() -> list[OpenHedge] | None:
    """The open hedge positions and working openings; None when the database cannot be read."""
    return _read(_open)


def hedge_con_ids() -> frozenset[int] | None:
    """Every leg ``conId`` of an open or working hedge; None when the database cannot be read."""
    book = open_hedges()
    if book is None:
        return None
    return frozenset(leg.con_id for h in book for leg in h.legs if leg.con_id)


def hedge_underlyings_open() -> frozenset[str] | None:
    """The instruments with an open or working hedge (the QQQ-route rule); None = unreadable."""
    book = open_hedges()
    if book is None:
        return None
    return frozenset(h.instrument for h in book)


def spend() -> float | None:
    """Premium paid less premium received (sales, settlements) over every hedge fill, dollars."""

    def run(con: sqlite3.Connection | None) -> float:
        if con is None:
            return 0.0
        row = con.execute("SELECT COALESCE(SUM(cash), 0) FROM hedge_fills").fetchone()
        return -float(row[0] or 0.0)

    return _read(run)


def marks_today(day: date) -> list[dict[str, Any]] | None:
    """The marks stored for ET *day*, latest per position: ``hedge_id``, ``mark``, ``value``,
    ``contracts``, ``source``. None when unreadable."""

    def run(con: sqlite3.Connection | None) -> list[dict[str, Any]]:
        if con is None or "hedge_marks" not in _tables(con):
            return []
        rows = con.execute(
            "SELECT hedge_id, mark, value, contracts, source, marked_at FROM hedge_marks "
            "WHERE session_date = ? ORDER BY marked_at, id",
            (day.isoformat(),),
        ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for hid, mark, value, contracts, source, _at in rows:
            latest[hid] = {
                "hedge_id": hid,
                "mark": float(mark),
                "value": float(value),
                "contracts": float(contracts),
                "source": source,
            }
        return list(latest.values())

    return _read(run)


def pnl_today(day: date) -> float | None:
    """The hedge book's P&L on ET *day*, signed (a gain is positive): for every position, its
    latest mark today (0 once closed today) less its latest mark before today (0 if opened today),
    plus the cash its fills moved today. None when the database cannot be read."""

    def run(con: sqlite3.Connection | None) -> float:
        if con is None:
            return 0.0
        has_marks = "hedge_marks" in _tables(con)
        start = (
            datetime(day.year, day.month, day.day, tzinfo=_ET).astimezone(UTC).replace(tzinfo=None)
        )
        end = start + timedelta(days=1)
        flows: dict[str, float] = {}
        for hid, cash in con.execute(
            "SELECT hedge_id, cash FROM hedge_fills WHERE filled_at >= ? AND filled_at < ?",
            (start.isoformat(sep=" "), end.isoformat(sep=" ")),
        ).fetchall():
            flows[hid] = flows.get(hid, 0.0) + float(cash)
        today: dict[str, float] = {}
        before: dict[str, float] = {}
        if has_marks:
            for hid, value, sday in con.execute(
                "SELECT hedge_id, value, session_date FROM hedge_marks "
                "WHERE session_date <= ? ORDER BY session_date, marked_at, id",
                (day.isoformat(),),
            ).fetchall():
                if _day(sday) == day:
                    today[hid] = float(value)
                else:
                    before[hid] = float(value)
        open_now = {h.hedge_id for h in _open(con) if h.contracts > _EPS}
        total = 0.0
        for hid in set(flows) | set(today) | set(before):
            if hid in before and hid not in today and hid in open_now and hid not in flows:
                continue  # not marked yet today: no move to report
            cur = today.get(hid, 0.0) if hid in open_now else 0.0
            total += cur - before.get(hid, 0.0) + flows.get(hid, 0.0)
        return total

    return _read(run)


def latest_programme() -> dict[str, Any] | None:
    """The bridge programme's latest row (``state``, ``instrument``, ``started_on``, ``nlv0`` ...),
    or None when there is none or it cannot be read."""

    def run(con: sqlite3.Connection | None) -> dict[str, Any] | None:
        if con is None or "hedge_programme" not in _tables(con):
            return None
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM hedge_programme ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row is not None else None

    return _read(run)


def leg_quotes(con_ids: list[int]) -> dict[int, dict[str, Any]] | None:
    """The newest captured quote (``hedge_quotes``) of each contract: ``spot``, ``iv``, ``mid``,
    ``session_date``. None when unreadable; contracts never captured are absent."""
    wanted = sorted({int(c) for c in con_ids if c})

    def run(con: sqlite3.Connection | None) -> dict[int, dict[str, Any]]:
        if con is None or not wanted or "hedge_quotes" not in _tables(con):
            return {}
        cols = {r[1] for r in con.execute("PRAGMA table_info(hedge_quotes)")}
        iv = "iv" if "iv" in cols else "NULL"
        marks = ",".join("?" for _ in wanted)
        out: dict[int, dict[str, Any]] = {}
        for cid, spot, ivv, mid, sday in con.execute(
            f"SELECT con_id, spot, {iv}, mid, session_date FROM hedge_quotes "
            f"WHERE con_id IN ({marks}) ORDER BY captured_at, id",
            wanted,
        ).fetchall():
            out[int(cid)] = {"spot": spot, "iv": ivv, "mid": mid, "session_date": _day(sday)}
        return out

    return _read(run)
