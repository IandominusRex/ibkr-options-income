"""The wheel's only window onto the value book (spec §9.1, §9.2; revision 4).

Read-only: ``data/value.db`` opened ``mode=ro`` with plain SQL. Imports nothing from ``src.value``
and no enrichment, so the engine, the strategies and execution may import it (with
``src.common.books``) and nothing else of the value book (tests/test_value_fence.py).

``read_book`` returns ``None`` when value.db exists but cannot be read: callers then **fail
closed** (the wheel uses its own share count alone and writes no covered call on unexplained
shares). A value.db that does not exist yet, or predates the Part 5 tables, is an empty book: no
value order has ever been placed, so that is the truth.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.common.config import get_config

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
