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

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.common.config import get_config
from src.common.schemas import (
    GexLevels,
    SpreadBriefResult,
    SpreadCandidate,
    SpreadDayPlan,
    SpreadEntryContext,
    SpreadMarketSnapshot,
    SpreadMenuItem,
    SpreadPick,
    SpreadPickRecord,
    SpreadPickSnapshot,
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
    mode: Mapped[str] = mapped_column(String(8), index=True)
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
    # The latest mid debit-to-close (risk-envelope Task 4): the open P&L the daily and monthly
    # loss stops and the wheel's daily loss leg (src/common/spreads_view.py) read.
    last_mid_debit: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Claude picks (ai.enabled): the pick that opened a main-book spread, and the trigger
    # episode of either book's spread — the comparison report lines the books up by these.
    pick_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_key: Mapped[str | None] = mapped_column(String(64), nullable=True)


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


class SpreadDayPlanRow(SpreadsBase):
    __tablename__ = "spread_day_plans"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    failed: Mapped[bool] = mapped_column(Boolean)
    plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    market: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(40))
    effort: Mapped[str] = mapped_column(String(8))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_text: Mapped[str] = mapped_column(Text)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)


class SpreadPickRow(SpreadsBase):
    __tablename__ = "spread_picks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    day: Mapped[date] = mapped_column(Date, index=True)
    episode_key: Mapped[str] = mapped_column(String(64), index=True)
    book_mode: Mapped[str] = mapped_column(String(8))
    menu: Mapped[list] = mapped_column(JSON)
    choice: Mapped[str] = mapped_column(String(8))
    reason: Mapped[str] = mapped_column(String(500), default="")
    fallback_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    executed_letter: Mapped[str | None] = mapped_column(String(2), nullable=True)
    send_rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    send_reasons: Mapped[list] = mapped_column(JSON, default=list)
    filled: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str] = mapped_column(String(40))
    effort: Mapped[str] = mapped_column(String(8))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_text: Mapped[str] = mapped_column(Text, default="")
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON)  # SpreadPickSnapshot — authoritative
    market: Mapped[dict] = mapped_column(JSON)  # SpreadMarketSnapshot — authoritative
    # Typed copies of the conditions, for grouping in plain SQL (the report reads the JSON).
    regime: Mapped[str] = mapped_column(String(10))
    flip_distance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_move: Mapped[float | None] = mapped_column(Float, nullable=True)
    move_em: Mapped[float | None] = mapped_column(Float, nullable=True)
    stall_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap_day: Mapped[bool] = mapped_column(Boolean, default=False)
    side: Mapped[str] = mapped_column(String(9), default="")
    event_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    plan_bias: Mapped[str | None] = mapped_column(String(8), nullable=True)
    vix: Mapped[float | None] = mapped_column(Float, nullable=True)
    vix_term_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    spy_vs_sma20_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    spy_vs_sma50_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi14: Mapped[float | None] = mapped_column(Float, nullable=True)
    headline_count: Mapped[int] = mapped_column(Integer, default=0)
    headline_sentiment_mean: Mapped[float | None] = mapped_column(Float, nullable=True)


class SpreadFlagRow(SpreadsBase):
    """A named, durable flag of the book (risk-envelope Task 4: ``month_stop``)."""

    __tablename__ = "spread_flags"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


MONTH_STOP_KEY = "month_stop"

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


# Columns added after a table's first release: create_all never ALTERs an existing table.
_ADDED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "spread_positions": (
        ("pick_id", "INTEGER"),
        ("episode_key", "VARCHAR(64)"),
        ("last_mid_debit", "FLOAT"),
    ),
}


def _add_missing_columns(engine: Engine) -> None:
    insp = inspect(engine)
    for table, cols in _ADDED_COLUMNS.items():
        if not insp.has_table(table):
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in cols:
            if name not in have:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_spreads_db() -> None:
    engine = get_spreads_engine()
    SpreadsBase.metadata.create_all(engine)
    _add_missing_columns(engine)


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
        pick_id=r.pick_id,
        episode_key=r.episode_key,
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
    pick_id: int | None = None,
    episode_key: str | None = None,
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
        pick_id=pick_id,
        episode_key=episode_key,
    )
    with spreads_session() as s:
        s.add(row)
        s.flush()
        return _to_schema(row)


def add_contracts(spread_id: str, *, contracts: int, credit: float, commission: float) -> bool:
    """Book an opening fill that arrived after the open was recorded (a late fill on an order
    whose cancel went unconfirmed): the entry credit becomes the contract-weighted average.
    False when the spread has no open row to add to."""
    with spreads_session() as s:
        row = s.query(SpreadPositionRow).filter_by(spread_id=spread_id).one_or_none()
        if row is None or row.status != "open" or contracts < 1:
            return False
        total = row.contracts_opened + contracts
        row.entry_credit = (row.entry_credit * row.contracts_opened + credit * contracts) / total
        row.entry_commission = (row.entry_commission or 0.0) + commission
        row.contracts_opened = total
        row.contracts += contracts
        return True


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
    """Keep the worst (highest) debit-to-close seen while the spread is open — its MAE — and
    the latest one, its open P&L mark."""
    with spreads_session() as s:
        row = s.query(SpreadPositionRow).filter_by(spread_id=spread_id).one()
        if row.max_debit_seen is None or mid_debit > row.max_debit_seen:
            row.max_debit_seen = mid_debit
        row.last_mid_debit = mid_debit


def open_pnl_usd(mode: str) -> float:
    """Marked P&L of *mode*'s open and expiring spreads: (entry credit − latest mid debit) × 100
    × contracts still open. A spread not yet marked counts 0."""
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(
                SpreadPositionRow.mode == mode,
                SpreadPositionRow.status.in_(("open", "expiring")),
            )
            .all()
        )
        return float(
            sum(
                (r.entry_credit - r.last_mid_debit) * 100.0 * r.contracts
                for r in rows
                if r.last_mid_debit is not None
            )
        )


def month_realized_pnl(year: int, month: int, mode: str) -> float:
    """Realized USD of *mode*'s spreads opened in ET month *year*-*month* (0DTE: opened and
    closed the same day, so this is the month's booked P&L)."""
    start = datetime(year, month, 1, tzinfo=ET) - timedelta(hours=1)
    with spreads_session() as s:
        rows = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.mode == mode, SpreadPositionRow.opened_at >= _naive(start))
            .all()
        )
        return float(
            sum(
                r.realized_pnl_usd or 0.0
                for r in rows
                if (et := r.opened_at.replace(tzinfo=UTC).astimezone(ET)).year == year
                and et.month == month
            )
        )


def month_stop_get() -> dict | None:
    """The month stop's record (``month``, ``pnl_usd``, ``nlv_usd``, ``set_at``), or None when it
    is not set. It stays set across months until a human clears it."""
    with spreads_session() as s:
        row = s.get(SpreadFlagRow, MONTH_STOP_KEY)
        return dict(row.value) if row is not None else None


def month_stop_set(
    month: str,
    *,
    pnl_usd: float | None = None,
    nlv_usd: float | None = None,
    now: datetime | None = None,
) -> None:
    """Set the month stop for *month* (``YYYY-MM``); an existing record is left as it was."""
    at = now or datetime.now(UTC)
    with spreads_session() as s:
        if s.get(SpreadFlagRow, MONTH_STOP_KEY) is not None:
            return
        s.add(
            SpreadFlagRow(
                key=MONTH_STOP_KEY,
                value={
                    "month": month,
                    "pnl_usd": pnl_usd,
                    "nlv_usd": nlv_usd,
                    "set_at": at.astimezone(UTC).isoformat(),
                },
                updated_at=_naive(at),
            )
        )


def month_stop_clear() -> dict | None:
    """Clear the month stop (the human reset); returns the record it cleared, or None."""
    with spreads_session() as s:
        row = s.get(SpreadFlagRow, MONTH_STOP_KEY)
        if row is None:
            return None
        cleared = dict(row.value)
        s.delete(row)
        return cleared


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
        pick_id=r.pick_id,
        episode_key=r.episode_key,
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


def record_day_plan(day: date, result: SpreadBriefResult, now: datetime) -> None:
    c = result.call
    with spreads_session() as s:
        s.merge(
            SpreadDayPlanRow(
                day=day,
                created_at=_naive(now),
                failed=result.plan is None,
                plan=result.plan.model_dump(mode="json") if result.plan else None,
                market=result.market.model_dump(mode="json"),
                model=c.model,
                effort=c.effort,
                latency_ms=c.latency_ms,
                cost_usd=c.cost_usd,
                error=c.error,
                prompt_text=c.prompt_text,
                raw_response=c.raw_response,
            )
        )


def day_plan(day: date) -> SpreadDayPlan | None:
    with spreads_session() as s:
        row = s.get(SpreadDayPlanRow, day)
        if row is None or row.plan is None:
            return None
        return SpreadDayPlan.model_validate(row.plan)


def day_plan_attempted(day: date) -> bool:
    with spreads_session() as s:
        return s.get(SpreadDayPlanRow, day) is not None


def record_pick(
    *,
    now: datetime,
    episode_key: str,
    book_mode: str,
    menu: list[SpreadMenuItem],
    pick: SpreadPick,
    fallback_reason: str | None,
    executed_letter: str | None,
    snapshot: SpreadPickSnapshot,
) -> int:
    m, c = pick.market, pick.call
    row = SpreadPickRow(
        created_at=_naive(now),
        day=now.astimezone(ET).date(),
        episode_key=episode_key,
        book_mode=book_mode,
        menu=[i.model_dump(mode="json") for i in menu],
        choice=pick.choice[:8],
        reason=pick.reason[:500],
        fallback_reason=fallback_reason,
        executed_letter=executed_letter,
        model=c.model,
        effort=c.effort,
        latency_ms=c.latency_ms,
        cost_usd=c.cost_usd,
        prompt_text=c.prompt_text,
        raw_response=c.raw_response,
        snapshot=snapshot.model_dump(mode="json"),
        market=m.model_dump(mode="json"),
        regime=snapshot.regime,
        flip_distance_pct=snapshot.flip_distance_pct,
        expected_move=snapshot.expected_move,
        move_em=snapshot.move_em,
        stall_minutes=snapshot.stall_minutes,
        gap_pct=snapshot.gap_pct,
        gap_day=snapshot.gap_day,
        side=snapshot.side,
        event_flag=snapshot.event_flag,
        plan_bias=snapshot.plan_bias,
        vix=m.vix,
        vix_term_ratio=m.vix_term_ratio,
        spy_vs_sma20_pct=m.spy_vs_sma20_pct,
        spy_vs_sma50_pct=m.spy_vs_sma50_pct,
        rsi14=m.rsi14,
        headline_count=m.headline_count,
        headline_sentiment_mean=m.headline_sentiment_mean,
    )
    with spreads_session() as s:
        s.add(row)
        s.flush()
        return row.id


def mark_pick_sent(
    pick_id: int, *, send_rejected: bool, send_reasons: list[str], filled: bool
) -> None:
    with spreads_session() as s:
        row = s.get(SpreadPickRow, pick_id)
        if row is None:
            return
        row.send_rejected = send_rejected
        row.send_reasons = list(send_reasons)
        row.filled = filled


def pick_exists(episode_key: str) -> bool:
    with spreads_session() as s:
        return s.query(SpreadPickRow.id).filter_by(episode_key=episode_key).first() is not None


def pick_calls_today(day: date) -> int:
    with spreads_session() as s:
        return s.query(SpreadPickRow).filter(SpreadPickRow.day == day).count()


def _pick_record(r: SpreadPickRow) -> SpreadPickRecord:
    return SpreadPickRecord(
        pick_id=r.id,
        created_at=r.created_at.replace(tzinfo=UTC),
        day=r.day,
        episode_key=r.episode_key,
        book_mode=r.book_mode,
        menu=[SpreadMenuItem.model_validate(m) for m in r.menu],
        choice=r.choice,
        reason=r.reason or "",
        fallback_reason=r.fallback_reason,
        executed_letter=r.executed_letter,
        send_rejected=bool(r.send_rejected),
        send_reasons=list(r.send_reasons or []),
        filled=bool(r.filled),
        model=r.model,
        effort=r.effort,
        latency_ms=r.latency_ms,
        cost_usd=r.cost_usd,
        snapshot=SpreadPickSnapshot.model_validate(r.snapshot),
        market=SpreadMarketSnapshot.model_validate(r.market),
        prompt_text=r.prompt_text or "",
        raw_response=r.raw_response,
    )


def picks(day: date | None = None) -> list[SpreadPickRecord]:
    with spreads_session() as s:
        q = s.query(SpreadPickRow)
        if day is not None:
            q = q.filter(SpreadPickRow.day == day)
        return [_pick_record(r) for r in q.order_by(SpreadPickRow.id).all()]


def episode_trade(episode_key: str, mode: str) -> SpreadTradeRecord | None:
    """The spread *mode*'s book opened in trigger episode *episode_key*, if any."""
    with spreads_session() as s:
        row = (
            s.query(SpreadPositionRow)
            .filter(SpreadPositionRow.episode_key == episode_key, SpreadPositionRow.mode == mode)
            .order_by(SpreadPositionRow.id)
            .first()
        )
        return _record(row) if row is not None else None
