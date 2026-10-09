"""Shared option-contract lookup cache (docs/superpowers/plans/2026-10-10-contract-cache.md).

Every IBKR process — scan, monitor, portfolio greeks, spreads — qualifies option contracts
through ``src.ibkr.contracts.qualify_options_async``, which consults this cache first. A
contract's conId can't change before expiry, so each one is looked up at IBKR once; a strike
IBKR says doesn't exist is remembered for the rest of the ET day. Prices are never cached.

Neutral reference data on purpose: this module imports only the stdlib, SQLAlchemy, ib_async
and src.common, so the wheel and the spreads process can both use it without crossing either
fence. It owns ``data/contracts.db``; nothing else writes it.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Date,
    Float,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    or_,
    select,
)
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from src.common.config import get_config
from src.common.logging import get_logger

log = get_logger(__name__)

ET = ZoneInfo("America/New_York")

# (symbol, expiry YYYYMMDD, strike, right C/P, trading_class, exchange) — as the caller ASKED.
Key = tuple[str, str, float, str, str, str]


def _et_today() -> date:
    return datetime.now(ET).date()


class ContractCacheBase(DeclarativeBase):
    pass


class ContractRow(ContractCacheBase):
    __tablename__ = "option_contracts"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "expiry",
            "strike",
            "right",
            "trading_class",
            "exchange",
            name="uq_option_contract",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16))
    expiry: Mapped[str] = mapped_column(String(8))
    strike: Mapped[float] = mapped_column(Float)
    right: Mapped[str] = mapped_column(String(1))
    trading_class: Mapped[str] = mapped_column(String(16), default="")
    exchange: Mapped[str] = mapped_column(String(16), default="SMART")
    # None = IBKR answered "no security definition" (a negative entry, valid for checked_on).
    con_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    multiplier: Mapped[str] = mapped_column(String(8), default="")
    currency: Mapped[str] = mapped_column(String(8), default="")
    local_symbol: Mapped[str] = mapped_column(String(32), default="")
    checked_on: Mapped[date] = mapped_column(Date)


class ChainClassRow(ContractCacheBase):
    """The trading classes IBKR listed for a symbol's option chain when last seen. A class
    newly appearing marks a corporate action (see ContractCache.note_trading_classes)."""

    __tablename__ = "chain_classes"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    classes: Mapped[str] = mapped_column(String(256))  # sorted, comma-joined


def contract_key(c: Any) -> Key:
    return (
        str(c.symbol).upper(),
        str(c.lastTradeDateOrContractMonth)[:8],
        round(float(c.strike), 4),
        str(c.right).upper()[:1],
        str(getattr(c, "tradingClass", "") or ""),
        str(getattr(c, "exchange", "") or "SMART"),
    )


def confirmed_missing(missing: Sequence[Key], good: Sequence[Key]) -> list[Key]:
    """The missing keys safe to remember: those whose (symbol, expiry, trading class) has at
    least one contract that DID qualify. A whole expiry coming back missing is a transient
    failure — the expiry list came from IBKR itself — so none of it is remembered."""
    groups = {(k[0], k[1], k[4]) for k in good}
    return [k for k in missing if (k[0], k[1], k[4]) in groups]


@dataclass
class Lookup:
    hits: list[Any] = field(default_factory=list)
    misses: list[Any] = field(default_factory=list)
    known_missing: int = 0


class ContractCache:
    def __init__(self, url: str, *, today: Callable[[], date] = _et_today) -> None:
        if url.startswith("sqlite:///"):
            Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(url, future=True)

        @event.listens_for(self._engine, "connect")
        def _pragmas(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        ContractCacheBase.metadata.create_all(self._engine)
        self._session = sessionmaker(bind=self._engine, future=True, expire_on_commit=False)
        self._today = today
        self.lock_path = Path(url[len("sqlite:///") :]).with_suffix(".lock")

    def lookup(self, contracts: Sequence[Any]) -> Lookup:
        today = self._today()
        keys = [contract_key(c) for c in contracts]
        symbols = {k[0] for k in keys}
        with self._session() as s:
            rows = s.scalars(select(ContractRow).where(ContractRow.symbol.in_(symbols))).all()
        index = {
            (r.symbol, r.expiry, round(r.strike, 4), r.right, r.trading_class, r.exchange): r
            for r in rows
        }
        out = Lookup()
        for c, k in zip(contracts, keys, strict=True):
            r = index.get(k)
            if r is not None and r.con_id is not None and r.expiry >= today.strftime("%Y%m%d"):
                c.conId, c.multiplier, c.currency = r.con_id, r.multiplier, r.currency
                c.localSymbol = r.local_symbol
                out.hits.append(c)
            elif r is not None and r.con_id is None and r.checked_on == today:
                out.known_missing += 1
            else:
                out.misses.append(c)
        return out

    def record(self, entries: Sequence[tuple[Key, Any | None]]) -> None:
        if not entries:
            return
        today = self._today()
        values = [
            {
                "symbol": k[0],
                "expiry": k[1],
                "strike": k[2],
                "right": k[3],
                "trading_class": k[4],
                "exchange": k[5],
                "con_id": int(q.conId) if q is not None else None,
                "multiplier": str(getattr(q, "multiplier", "") or "") if q is not None else "",
                "currency": str(getattr(q, "currency", "") or "") if q is not None else "",
                "local_symbol": str(getattr(q, "localSymbol", "") or "") if q is not None else "",
                "checked_on": today,
            }
            for k, q in entries
        ]
        stmt = insert(ContractRow).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "expiry", "strike", "right", "trading_class", "exchange"],
            set_={
                c: stmt.excluded[c]
                for c in ("con_id", "multiplier", "currency", "local_symbol", "checked_on")
            },
        )
        with self._session() as s, s.begin():
            s.execute(stmt)

    def note_trading_classes(self, symbol: str, classes: Iterable[str]) -> bool:
        """Record the chain's trading classes. A class not seen before for this symbol means a
        corporate action re-classed its contracts: drop every cached entry for the symbol and
        return True. First sight only sets the baseline; a class disappearing drops nothing."""
        sym = symbol.upper()
        now = sorted({c for c in classes if c})
        with self._session() as s, s.begin():
            row = s.get(ChainClassRow, sym)
            before = set(row.classes.split(",")) if row is not None and row.classes else None
            added = before is not None and bool(set(now) - before)
            if added:
                s.execute(delete(ContractRow).where(ContractRow.symbol == sym))
                log.warning(
                    "contract cache: new trading class for %s (%s) — dropped its cached contracts",
                    sym,
                    sorted(set(now) - (before or set())),
                )
            if row is None:
                s.add(ChainClassRow(symbol=sym, classes=",".join(now)))
            else:
                row.classes = ",".join(now)
        return added

    def prune(self) -> int:
        today = self._today()
        with self._session() as s, s.begin():
            result = s.execute(
                delete(ContractRow).where(
                    or_(
                        ContractRow.expiry < today.strftime("%Y%m%d"),
                        (ContractRow.con_id.is_(None)) & (ContractRow.checked_on < today),
                    )
                )
            )
        # rowcount is a CursorResult attribute; mypy only sees the ORM-wrapped result.
        return int(getattr(result, "rowcount", 0) or 0)


_CACHE: ContractCache | None = None
_CACHE_FAILED = False
_PRUNED_ON: date | None = None


def get_contract_cache() -> ContractCache | None:
    """The process-wide cache, or None when disabled or unusable (logged once). Prunes at most
    once per ET day per process."""
    global _CACHE, _CACHE_FAILED, _PRUNED_ON
    cfg = get_config()
    if not cfg.market_data.contract_cache_enabled or _CACHE_FAILED:
        return None
    if _CACHE is None:
        try:
            _CACHE = ContractCache(cfg.contract_cache_url_abs())
        except Exception:
            log.warning(
                "contract cache unavailable — qualifying every contract at IBKR", exc_info=True
            )
            _CACHE_FAILED = True
            return None
    today = _et_today()
    if _PRUNED_ON != today:
        _PRUNED_ON = today
        try:
            pruned = _CACHE.prune()
            if pruned:
                log.info(
                    "contract cache: pruned %d expired entr%s",
                    pruned,
                    "y" if pruned == 1 else "ies",
                )
        except Exception:
            log.warning("contract cache prune failed", exc_info=True)
    return _CACHE


@contextlib.asynccontextmanager
async def contract_details_slot(lock_path: Path | None, wait_seconds: float) -> AsyncIterator[bool]:
    """Hold the cross-process contract-lookup lock for one chunk. Yields True when held, False
    when there is no lock (cache disabled) or the wait ran out — the caller proceeds either way.
    flock locks belong to the open file, so two opens in one process exclude each other too."""
    if lock_path is None:
        yield False
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+")  # noqa: SIM115 — closed in finally
    held = False
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except BlockingIOError:
                if loop.time() >= deadline:
                    log.warning(
                        "contract lookup lock busy for %.0fs — qualifying without it", wait_seconds
                    )
                    break
                await asyncio.sleep(0.05)
        yield held
    finally:
        if held:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
