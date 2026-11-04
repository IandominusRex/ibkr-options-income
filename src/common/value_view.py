"""The wheel's only window onto the value book (spec §9.1, §9.2; revision 4).

Read-only: ``data/value.db`` opened ``mode=ro`` with plain SQL. Imports nothing from ``src.value``
and no enrichment, so the engine, the strategies and execution may import it (with
``src.common.books``) and nothing else of the value book (tests/test_value_fence.py).

Part 6 adds the read-only surface of the Telegram ``/value`` command and the watchdog
(``read_ticker_file``, ``top_names``, ``open_proposals``, ``last_nightly_run``): each returns
``None`` when value.db is missing or unreadable and never raises.

``read_book`` returns ``None`` when value.db exists but cannot be read: callers then **fail
closed** (the wheel uses its own share count alone and writes no covered call on unexplained
shares). A value.db that does not exist yet, or predates the Part 5 tables, is an empty book: no
value order has ever been placed, so that is the truth.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.common.config import get_config
from src.common.value_commands import proposal_fingerprint

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ValueHolding:
    """One name's value shares: filled (bought less sold), and what open orders would add or
    take away. ``cost`` is the filled shares' cost, in dollars."""

    symbol: str
    filled: float = 0.0
    pending_buy: float = 0.0
    pending_sell: float = 0.0
    cost: float = 0.0
    mark: float | None = None  # the last price the value process saw

    @property
    def market_value(self) -> float:
        """Filled shares at the last mark, else at cost."""
        return self.filled * self.mark if self.mark is not None else self.cost

    @property
    def claimed(self) -> float:
        """The shares the wheel must never write against: filled plus pending buys."""
        return self.filled + self.pending_buy


@dataclass(frozen=True, slots=True)
class FundingRequest:
    id: int
    proposal_id: int
    symbol: str
    needed_usd: float
    created_at: datetime
    expires_at: datetime
    # When the value process last wrote ``needed_usd`` from a fresh account snapshot (naive UTC).
    # ``needed_usd`` already excludes every close made before it, so only releases after this
    # moment may be subtracted from it; a request whose ``as_of`` has gone stale is not served
    # (the value process is not running). A row from before the column is read as ``created_at``.
    as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class ValueBook:
    holdings: dict[str, ValueHolding] = field(default_factory=dict)
    earmarked_usd: float = (
        0.0  # approved and sent buys not yet filled: cash the wheel must not re-use
    )
    frozen: frozenset[str] = frozenset()  # names whose attribution is frozen (spec §9.2)
    requests: tuple[FundingRequest, ...] = ()  # open capital-release requests

    def holding(self, symbol: str) -> ValueHolding:
        return self.holdings.get(symbol.upper(), ValueHolding(symbol.upper()))


def _path() -> Path:
    url = get_config().value_db_url_abs()
    return Path(url[len("sqlite:///") :] if url.startswith("sqlite:///") else url)


def _naive(text: str | None) -> datetime | None:
    if not text:
        return None
    dt = datetime.fromisoformat(text)
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def read_book(now: datetime | None = None) -> ValueBook | None:
    """The value book as the wheel sees it, or None when value.db cannot be read."""
    path = _path()
    if not path.exists():
        return ValueBook()
    now = now or datetime.now(UTC).replace(tzinfo=None)
    try:
        with _connect(path) as con:
            orders = con.execute(
                "SELECT symbol, side, shares, filled, avg_price, status FROM value_orders"
            ).fetchall()
            earmark = con.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM value_proposals "
                "WHERE kind = 'buy' AND status IN ('approved', 'funding')"
            ).fetchone()[0]
            sent = con.execute(
                "SELECT p.id, p.cost_usd, o.shares, o.filled, o.limit_price, o.status "
                "FROM value_proposals p LEFT JOIN value_orders o ON o.proposal_id = p.id "
                "WHERE p.kind = 'buy' AND p.status = 'sent'"
            ).fetchall()
            attribution = con.execute(
                "SELECT symbol, state, mark FROM value_attribution"
            ).fetchall()
            has_as_of = any(
                r[1] == "as_of" for r in con.execute("PRAGMA table_info(value_funding_requests)")
            )
            requests = con.execute(
                "SELECT id, proposal_id, symbol, needed_usd, created_at, expires_at, "
                + ("as_of" if has_as_of else "NULL")
                + " FROM value_funding_requests WHERE status = 'open' ORDER BY id"
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table: value_orders" in str(exc):
            return ValueBook()  # a value.db from before Part 5: no value order exists
        # any other missing table is a half-migrated or damaged file: fail closed
        log.critical("value_view: value.db unreadable (%s): the wheel fails closed", exc)
        return None
    except Exception as exc:  # noqa: BLE001 - the wheel must never read a damaged book as empty
        log.critical("value_view: value.db unreadable (%s): the wheel fails closed", exc)
        return None
    acc: dict[str, dict[str, float]] = {}
    for symbol, side, shares, filled, avg, status in orders:
        h = acc.setdefault(
            symbol.upper(), dict.fromkeys(("bought", "sold", "buy", "sell", "spent"), 0.0)
        )
        done = float(filled or 0.0)
        working = status in ("pending", "submitted", "partial")
        open_qty = max(0.0, float(shares) - done) if working else 0.0
        if side == "buy":
            h["bought"] += done
            h["spent"] += done * float(avg or 0.0)
            h["buy"] += open_qty
        else:
            h["sold"] += done
            h["sell"] += open_qty
    marks = {str(sym).upper(): float(m) for sym, _, m in attribution if m is not None}
    holdings: dict[str, ValueHolding] = {}
    for s, v in acc.items():
        held = max(0.0, v["bought"] - v["sold"])
        avg_cost = v["spent"] / v["bought"] if v["bought"] else 0.0
        holdings[s] = ValueHolding(s, held, v["buy"], v["sell"], held * avg_cost, marks.get(s))
    reqs = tuple(
        FundingRequest(
            int(i), int(p), str(s).upper(), float(n), created, expires, _naive(a) or created
        )
        for i, p, s, n, c, e, a in requests
        if (created := _naive(c)) is not None
        and (expires := _naive(e)) is not None
        and expires > now
    )
    return ValueBook(
        holdings=holdings,
        earmarked_usd=float(earmark or 0.0) + _sent_earmark(sent),
        frozen=frozenset(str(sym).upper() for sym, state, _ in attribution if state == "frozen"),
        requests=reqs,
    )


def _sent_earmark(rows: list[tuple]) -> float:
    """Buys the value process has sent but not finished: the unfilled remainder of each working
    order at its limit (market value counts filled shares only), else the proposal's whole cost
    while its order row is not written yet. A sent proposal whose orders are all over adds 0."""
    total = 0.0
    by_proposal: dict[int, list[tuple]] = {}
    for pid, cost, shares, filled, limit, status in rows:
        by_proposal.setdefault(int(pid), []).append((cost, shares, filled, limit, status))
    for items in by_proposal.values():
        if all(it[1] is None for it in items):
            total += float(items[0][0] or 0.0)
            continue
        for _, shares, filled, limit, status in items:
            if shares is not None and status in ("pending", "submitted", "partial"):
                total += max(0.0, float(shares) - float(filled or 0.0)) * float(limit or 0.0)
    return total


def put_ceiling(symbol: str) -> float | None:
    """Spec §9.1: the highest effective entry ceiling among the lists on which *symbol* is
    READY, WATCH or WAIT (the strike ceiling of a value-suggested put); None when it has none or
    value.db cannot be read. In live while ``value.claude.apply_live`` is off the effective
    verdict is Python's baseline already (``value_effective``)."""
    path = _path()
    if not path.exists():
        return None
    try:
        with _connect(path) as con:
            row = con.execute(
                "SELECT MAX(entry_ceiling) FROM value_effective WHERE symbol = ? "
                "AND verdict IN ('READY', 'WATCH', 'WAIT') AND entry_ceiling IS NOT NULL",
                (symbol.upper(),),
            ).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None or row[0] is None else float(row[0])


# --- Part 6: the read-only surface of /value, the watchdog and (Task 10) the VALUE NOTE ---------

_REEVAL_OPEN_DAYS = 10  # a held re-evaluation's last trigger within this many days reads as open
LIST_NAMES = ("deep_value", "quality_growth")


@dataclass(frozen=True, slots=True)
class TickerFileView:
    """One row of ``value_ticker_files``, the summary fields only."""

    symbol: str
    computed_at: datetime
    as_of: date
    universe: str
    verdict_deep: str
    verdict_growth: str
    filed_list: str | None
    fair_value_deep: float | None
    fair_value_growth: float | None
    mos_deep: float | None
    mos_growth: float | None
    price: float | None
    effective: dict[str, tuple[str, str]]  # list -> (verdict, "claude" | "python")
    held_shares: float
    open_reevaluation: str | None  # severity of an open held re-evaluation
    freshness_json: str | None


@dataclass(frozen=True, slots=True)
class ProposalView:
    id: int
    kind: str
    symbol: str
    list_name: str
    shares: float
    price: float | None
    reason: str
    cause: str
    needs_tap: bool
    status: str
    created_at: datetime
    expires_at: datetime
    fingerprint: str


def _open_ro() -> sqlite3.Connection | None:
    path = _path()
    if not path.exists():
        return None
    try:
        return _connect(path)
    except sqlite3.Error:
        return None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in con.execute(f"PRAGMA table_info({table})")}


_FILE_COLS = (
    "symbol, computed_at, as_of, universe, verdict_deep, verdict_growth, filed_list, "
    "fair_value_deep, fair_value_growth, mos_deep, mos_growth, price"
)


def _file_view(con: sqlite3.Connection, row: tuple, fresh_col: bool) -> TickerFileView | None:
    computed, as_of = _naive(row[1]), row[2]
    if computed is None or not as_of:
        return None
    symbol = str(row[0]).upper()
    effective = {
        str(ln): (str(v), str(by))
        for ln, v, by in con.execute(
            "SELECT list_name, verdict, decided_by FROM value_effective WHERE symbol = ?",
            (symbol,),
        )
    }
    held = con.execute(
        "SELECT COALESCE(SUM(CASE WHEN side = 'buy' THEN filled ELSE -filled END), 0) "
        "FROM value_orders WHERE symbol = ?",
        (symbol,),
    ).fetchone()[0]
    since = (datetime.now(UTC).date() - timedelta(days=_REEVAL_OPEN_DAYS)).isoformat()
    sev = con.execute(
        "SELECT r.severity FROM value_reevaluations r JOIN value_positions p ON p.id = r.position_id "
        "WHERE r.symbol = ? AND p.status = 'open' AND (r.last_session >= ? "
        "OR r.review_state IN ('WEAKENED', 'BROKEN')) ORDER BY r.id DESC LIMIT 1",
        (symbol, since),
    ).fetchone()
    fresh = None
    if fresh_col:
        r = con.execute(
            "SELECT freshness_json FROM value_ticker_files WHERE symbol = ?", (symbol,)
        ).fetchone()
        fresh = None if r is None else r[0]
    return TickerFileView(
        symbol=symbol,
        computed_at=computed,
        as_of=date.fromisoformat(str(as_of)),
        universe=str(row[3]),
        verdict_deep=str(row[4]),
        verdict_growth=str(row[5]),
        filed_list=row[6],
        fair_value_deep=row[7],
        fair_value_growth=row[8],
        mos_deep=row[9],
        mos_growth=row[10],
        price=row[11],
        effective=effective,
        held_shares=max(0.0, float(held or 0.0)),
        open_reevaluation=None if sev is None else str(sev[0]),
        freshness_json=fresh,
    )


def read_ticker_file(symbol: str) -> TickerFileView | None:
    """The stored ticker file's summary, or None when there is none or value.db cannot be read."""
    con = _open_ro()
    if con is None:
        return None
    try:
        with con:
            row = con.execute(
                f"SELECT {_FILE_COLS} FROM value_ticker_files WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
            if row is None:
                return None
            return _file_view(con, row, "freshness_json" in _columns(con, "value_ticker_files"))
    except Exception as exc:  # noqa: BLE001 - a read surface never raises
        log.warning("value_view: read_ticker_file failed (%s)", exc)
        return None


def top_names(list_name: str, n: int = 5) -> list[TickerFileView] | None:
    """The top names on one list by the effective verdict: READY first, then WATCH, each by rank
    (higher is better). None when value.db cannot be read; an empty list when it has none."""
    if list_name not in LIST_NAMES:
        return []
    con = _open_ro()
    if con is None:
        return None
    rank = "rank_deep" if list_name == "deep_value" else "rank_growth"
    try:
        with con:
            fresh_col = "freshness_json" in _columns(con, "value_ticker_files")
            rows = con.execute(
                "SELECT "
                + ", ".join(f"t.{c.strip()}" for c in _FILE_COLS.split(","))
                + " FROM value_ticker_files t JOIN value_effective e "
                "ON e.symbol = t.symbol AND e.list_name = ? "
                "WHERE t.universe = 'trading' AND e.verdict IN ('READY', 'WATCH') "
                f"ORDER BY CASE e.verdict WHEN 'READY' THEN 0 ELSE 1 END, t.{rank} DESC, t.symbol "
                "LIMIT ?",
                (list_name, int(n)),
            ).fetchall()
            return [v for r in rows if (v := _file_view(con, r, fresh_col)) is not None]
    except Exception as exc:  # noqa: BLE001
        log.warning("value_view: top_names failed (%s)", exc)
        return None


def open_proposals() -> list[ProposalView] | None:
    """Pending, approved, funding and sent proposals, oldest first, each with the fingerprint a
    tap must carry back. None when value.db cannot be read."""
    con = _open_ro()
    if con is None:
        return None
    try:
        with con:
            rows = con.execute(
                "SELECT id, kind, symbol, list_name, shares, price, reason, cause, needs_tap, "
                "status, created_at, expires_at FROM value_proposals "
                "WHERE status IN ('pending', 'approved', 'funding', 'sent') ORDER BY id"
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        log.warning("value_view: open_proposals failed (%s)", exc)
        return None
    out: list[ProposalView] = []
    for pid, kind, sym, ln, shares, price, reason, cause, tap, status, c, e in rows:
        created, expires = _naive(c), _naive(e)
        if created is None or expires is None:
            continue
        out.append(
            ProposalView(
                int(pid),
                str(kind),
                str(sym),
                str(ln),
                float(shares),
                price,
                str(reason),
                str(cause),
                bool(tap),
                str(status),
                created,
                expires,
                proposal_fingerprint(int(pid), str(kind), str(sym), float(shares), created),
            )
        )
    return out


def last_nightly_run() -> datetime | None:
    """When the newest finished nightly run ended (naive UTC), or None: never ran, no value.db,
    or unreadable."""
    con = _open_ro()
    if con is None:
        return None
    try:
        with con:
            row = con.execute(
                "SELECT MAX(finished_at) FROM value_runs WHERE kind = 'nightly' "
                "AND finished_at IS NOT NULL"
            ).fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning("value_view: last_nightly_run failed (%s)", exc)
        return None
    return None if row is None else _naive(row[0])
