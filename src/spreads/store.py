"""The spreads system's own SQLite database (``data/spreads.db``).

A separate engine and a separate DeclarativeBase from the trading DB, so ``create_all`` can
never build a spreads table in ``income_system.db`` or a wheel table here (the
``src/research/store`` pattern). Timestamps are stored naive-UTC, like the trading DB.
Commissions are positive costs. ``mode`` keeps shadow and paper books apart.

Every spread is a trade-log row: ``spread_positions`` carries the entry tags
(``SpreadEntryContext``: trigger, move size, gap, gamma regime and levels, minutes after the
open) and the worst mark seen while open, so ``trade_log`` can answer "how did negative-gamma
trades / gap days / call spreads do?" without joining anything.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.common.config import get_config
from src.common.schemas import (
    GexLevels,
    SpreadCandidate,
    SpreadEntryContext,
    SpreadPosition,
    SpreadTradeRecord,
    SpreadVerdict,
)
from src.spreads.pricing import ET


class SpreadsBase(DeclarativeBase):
    pass


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


class GexMapRow(SpreadsBase):
    __tablename__ = "gex_maps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_date: Mapped[date] = mapped_column(Date, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime)
    spot: Mapped[float] = mapped_column(Float)
    net_gex: Mapped[float] = mapped_column(Float)
    regime: Mapped[str] = mapped_column(String(10))
    flip: Mapped[float | None] = mapped_column(Float, nullable=True)
    call_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    put_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_move: Mapped[float | None] = mapped_column(Float, nullable=True)


class SpreadCandidateRow(SpreadsBase):
    __tablename__ = "spread_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spread_id: Mapped[str] = mapped_column(String(48), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    side: Mapped[str] = mapped_column(String(4))
    expiry: Mapped[date] = mapped_column(Date)
    short_strike: Mapped[float] = mapped_column(Float)
    long_strike: Mapped[float] = mapped_column(Float)
    credit_mid: Mapped[float] = mapped_column(Float)
    credit_natural: Mapped[float] = mapped_column(Float)
    short_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime: Mapped[str] = mapped_column(String(10))
    approved: Mapped[bool] = mapped_column(Boolean)
    contracts: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[list] = mapped_column(JSON, default=list)


class SpreadPositionRow(SpreadsBase):
    __tablename__ = "spread_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spread_id: Mapped[str] = mapped_column(String(48), unique=True)
    mode: Mapped[str] = mapped_column(String(6), index=True)
    side: Mapped[str] = mapped_column(String(4))
    expiry: Mapped[date] = mapped_column(Date)
    short_strike: Mapped[float] = mapped_column(Float)
    long_strike: Mapped[float] = mapped_column(Float)
    width: Mapped[float] = mapped_column(Float)
    contracts_opened: Mapped[int] = mapped_column(Integer)
    contracts: Mapped[int] = mapped_column(Integer)  # still open
    short_con_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    long_con_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_credit: Mapped[float] = mapped_column(Float)
    entry_commission: Mapped[float] = mapped_column(Float)
    open_perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open|expiring|closed
    exit_debit: Mapped[float | None] = mapped_column(Float, nullable=True)  # qty-weighted
    exit_commission: Mapped[float] = mapped_column(Float, default=0.0)
    exit_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    realized_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # Entry tags (SpreadEntryContext) — the trade log's analysis columns.
    regime: Mapped[str] = mapped_column(String(10), default="unknown")
    trigger: Mapped[str] = mapped_column(String(8), default="always")
    move_em: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap_day: Mapped[bool] = mapped_column(Boolean, default=False)
    minutes_after_open: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_context: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # the full context
    # Worst (highest) mid debit-to-close seen while open; MAE = (this − entry_credit) × 100 × qty.
    max_debit_seen: Mapped[float | None] = mapped_column(Float, nullable=True)


class SpreadOrderRow(SpreadsBase):
    __tablename__ = "spread_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spread_id: Mapped[str] = mapped_column(String(48), index=True)
    kind: Mapped[str] = mapped_column(String(5))  # open|close
    order_ref: Mapped[str] = mapped_column(String(64))
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filled_qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission: Mapped[float] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_url() -> str:
    """Absolute sqlite URL for the spreads database. Patched in tests."""
    return get_config().spreads_db_url_abs()


def get_spreads_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = _resolve_url()
        if url.startswith("sqlite:///"):
            Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True)

        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def init_spreads_db() -> None:
    SpreadsBase.metadata.create_all(get_spreads_engine())


@contextmanager
def spreads_session() -> Iterator[Session]:
    get_spreads_engine()
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _to_schema(r: SpreadPositionRow) -> SpreadPosition:
    return SpreadPosition(
        spread_id=r.spread_id,
        mode=r.mode,  # type: ignore[arg-type]
        side=r.side,  # type: ignore[arg-type]
        expiry=r.expiry,
        short_strike=r.short_strike,
        long_strike=r.long_strike,
        width=r.width,
        contracts=r.contracts,
        entry_credit=r.entry_credit,
        opened_at=r.opened_at.replace(tzinfo=UTC),
        short_con_id=r.short_con_id,
        long_con_id=r.long_con_id,
    )


def record_map(levels: GexLevels) -> None:
    with spreads_session() as s:
        s.add(
            GexMapRow(
                session_date=levels.as_of.astimezone(ET).date(),
                as_of=_naive(levels.as_of),
                spot=levels.spot,
                net_gex=levels.net_gex,
                regime=levels.regime,
                flip=levels.flip,
                call_wall=levels.call_wall,
                put_wall=levels.put_wall,
                expected_move=levels.expected_move,
            )
        )


def record_candidate(
    c: SpreadCandidate, verdict: SpreadVerdict, regime: str, now: datetime
) -> None:
    with spreads_session() as s:
        s.add(
            SpreadCandidateRow(
                spread_id=c.spread_id,
                created_at=_naive(now),
                side=c.side,
                expiry=c.expiry,
                short_strike=c.short_strike,
                long_strike=c.long_strike,
                credit_mid=c.credit_mid,
                credit_natural=c.credit_natural,
                short_delta=c.short_delta,
                regime=regime,
                approved=verdict.approved,
                contracts=verdict.contracts,
                reasons=list(verdict.reasons),
            )
        )


def record_order(
    *,
    spread_id: str,
    kind: str,
    order_ref: str,
    ib_order_id: int | None,
    perm_id: int | None,
    filled_qty: int,
    price: float | None,
    commission: float,
    reason: str | None,
    now: datetime,
) -> None:
    with spreads_session() as s:
        s.add(
            SpreadOrderRow(
                spread_id=spread_id,
                kind=kind,
                order_ref=order_ref,
                ib_order_id=ib_order_id,
                perm_id=perm_id,
                filled_qty=filled_qty,
                price=price,
                commission=commission,
                reason=reason[:200] if reason else None,
                created_at=_naive(now),
            )
        )


def open_position(
    c: SpreadCandidate,
    *,
    mode: str,
    contracts: int,
    credit: float,
    commission: float,
    now: datetime,
    perm_id: int | None,
    context: SpreadEntryContext | None = None,
) -> SpreadPosition:
    tags: dict = {}
    if context is not None:
        tags = {
            "regime": context.regime,
            "trigger": context.trigger,
            "move_em": context.move_em,
            "gap_pct": context.gap_pct,
            "gap_day": context.gap_day,
            "minutes_after_open": context.minutes_after_open,
            "entry_context": context.model_dump(mode="json"),
        }
    row = SpreadPositionRow(
        **tags,
        spread_id=c.spread_id,
        mode=mode,
        side=c.side,
        expiry=c.expiry,
        short_strike=c.short_strike,
        long_strike=c.long_strike,
        width=c.width,
        contracts_opened=contracts,
        contracts=contracts,
        short_con_id=c.short_con_id,
        long_con_id=c.long_con_id,
        entry_credit=credit,
        entry_commission=commission,
        open_perm_id=perm_id,
        opened_at=_naive(now),
        status="open",
        exit_commission=0.0,
        realized_pnl_usd=0.0,
    )
    with spreads_session() as s:
        s.add(row)
        s.flush()
        return _to_schema(row)


def _positions(mode: str, status: str) -> list[SpreadPosition]:
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.mode == mode, SpreadPositionRow.status == status)
            .order_by(SpreadPositionRow.id)
            .all()
        )
        return [_to_schema(r) for r in rows]


def open_positions(mode: str) -> list[SpreadPosition]:
    return _positions(mode, "open")


def expiring_positions(mode: str) -> list[SpreadPosition]:
    return _positions(mode, "expiring")


def mark_expiring(spread_id: str) -> None:
    with spreads_session() as s:
        row = s.query(SpreadPositionRow).filter_by(spread_id=spread_id).one()
        row.status = "expiring"


def held_contracts(spread_id: str) -> int | None:
    """Contracts still open on an open or expiring spread; None if there is no such spread."""
    with spreads_session() as s:
        row = (
            s.query(SpreadPositionRow)
            .filter(
                SpreadPositionRow.spread_id == spread_id,
                SpreadPositionRow.status.in_(("open", "expiring")),
            )
            .one_or_none()
        )
        return row.contracts if row is not None else None


def close_position(
    spread_id: str,
    *,
    contracts: int,
    debit: float,
    commission: float,
    reason: str,
    now: datetime,
) -> float:
    """Close up to *contracts*; returns this close's realized USD (entry commission pro-rated)."""
    with spreads_session() as s:
        row = s.query(SpreadPositionRow).filter_by(spread_id=spread_id).one()
        q = max(0, min(contracts, row.contracts))
        if q == 0:
            return 0.0
        entry_share = row.entry_commission * q / row.contracts_opened
        realized = (row.entry_credit - debit) * 100.0 * q - entry_share - commission
        already = row.contracts_opened - row.contracts
        row.exit_debit = (
            debit
            if already == 0 or row.exit_debit is None
            else (row.exit_debit * already + debit * q) / (already + q)
        )
        row.exit_commission = (row.exit_commission or 0.0) + commission
        row.realized_pnl_usd = (row.realized_pnl_usd or 0.0) + realized
        row.contracts -= q
        if row.contracts == 0:
            row.status = "closed"
            row.exit_reason = reason
            row.closed_at = _naive(now)
        return realized


def day_stats(day: date, mode: str) -> tuple[int, float]:
    """(spreads opened on ET *day*, realized USD booked on them so far)."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=ET) - timedelta(hours=1)
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.mode == mode, SpreadPositionRow.opened_at >= _naive(start))
            .all()
        )
        today = [r for r in rows if r.opened_at.replace(tzinfo=UTC).astimezone(ET).date() == day]
        return len(today), float(sum(r.realized_pnl_usd or 0.0 for r in today))


def open_risk_usd(mode: str) -> float:
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(
                SpreadPositionRow.mode == mode,
                SpreadPositionRow.status.in_(("open", "expiring")),
            )
            .all()
        )
        return float(sum((r.width - r.entry_credit) * 100.0 * r.contracts for r in rows))


def note_mark(spread_id: str, mid_debit: float) -> None:
    """Keep the worst (highest) debit-to-close seen while the spread is open — its MAE."""
    with spreads_session() as s:
        row = s.query(SpreadPositionRow).filter_by(spread_id=spread_id).one()
        if row.max_debit_seen is None or mid_debit > row.max_debit_seen:
            row.max_debit_seen = mid_debit


def sides_opened(day: date, mode: str) -> list[str]:
    """Sides of the spreads opened on ET *day*, oldest first (the one-side-per-day input)."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=ET) - timedelta(hours=1)
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.mode == mode, SpreadPositionRow.opened_at >= _naive(start))
            .order_by(SpreadPositionRow.opened_at, SpreadPositionRow.id)
            .all()
        )
        return [
            r.side for r in rows if r.opened_at.replace(tzinfo=UTC).astimezone(ET).date() == day
        ]


def realized_pnl_total(mode: str) -> float:
    """Every dollar the book has realized in *mode* — the sizing capital is starting capital + this."""
    with spreads_session() as s:
        rows = s.query(SpreadPositionRow).filter(SpreadPositionRow.mode == mode).all()
        return float(sum(r.realized_pnl_usd or 0.0 for r in rows))


def first_map_em(day: date) -> float | None:
    """The expected move of *day*'s first map that had one — the trigger's yardstick."""
    with spreads_session() as s:
        row = (
            s.query(GexMapRow)
            .filter(GexMapRow.session_date == day, GexMapRow.expected_move.is_not(None))
            .order_by(GexMapRow.as_of, GexMapRow.id)
            .first()
        )
        return row.expected_move if row is not None else None


def _record(r: SpreadPositionRow) -> SpreadTradeRecord:
    opened = r.opened_at.replace(tzinfo=UTC)
    closed = r.closed_at.replace(tzinfo=UTC) if r.closed_at is not None else None
    mae = None
    if r.max_debit_seen is not None:
        mae = max(0.0, (r.max_debit_seen - r.entry_credit) * 100.0 * r.contracts_opened)
    return SpreadTradeRecord(
        spread_id=r.spread_id,
        mode=r.mode,  # type: ignore[arg-type]
        side=r.side,  # type: ignore[arg-type]
        status=r.status,
        opened_at=opened,
        closed_at=closed,
        short_strike=r.short_strike,
        long_strike=r.long_strike,
        width=r.width,
        contracts=r.contracts_opened,
        entry_credit=r.entry_credit,
        exit_debit=r.exit_debit,
        exit_reason=r.exit_reason,
        pnl_usd=r.realized_pnl_usd or 0.0,
        regime=r.regime or "unknown",
        trigger=r.trigger or "always",
        move_em=r.move_em,
        gap_pct=r.gap_pct,
        gap_day=bool(r.gap_day),
        minutes_after_open=r.minutes_after_open,
        hold_minutes=(closed - opened).total_seconds() / 60.0 if closed is not None else None,
        mae_usd=mae,
    )


def trade_log(mode: str) -> list[SpreadTradeRecord]:
    """Every spread opened in *mode*, oldest first, open or closed, with its tags and outcome."""
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.mode == mode)
            .order_by(SpreadPositionRow.opened_at, SpreadPositionRow.id)
            .all()
        )
        return [_record(r) for r in rows]


def closed_results(mode: str) -> list[tuple[str, str, float]]:
    """(regime at entry, exit reason, realized USD) for every closed spread in *mode*, in close order."""
    closed = [t for t in trade_log(mode) if t.status == "closed" and t.closed_at is not None]
    closed.sort(key=lambda t: t.closed_at or t.opened_at)
    return [(t.regime, t.exit_reason or "", t.pnl_usd) for t in closed]
