"""The value book's own SQLite database (``data/value.db``), spec §6.9 and §9.7.

A separate engine and DeclarativeBase (the ``src/spreads/store.py`` pattern), so ``create_all``
can never build a value table in another database. ``src/value/`` is its only writer
(tests/test_web_fence.py). Timestamps are naive UTC.

Part 1 tables:
- ``value_ticker_files`` - the latest Part 1 of every name ever scored (one row per symbol);
- ``value_ticker_history`` - append-only: a full row when anything that matters changed, a
  compact row once per session for names in the ranked universe;
- ``value_runs`` - one row per scoring run (the dry run included).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from src.common.config import get_config


class ValueBase(DeclarativeBase):
    pass


class ValueTickerFileRow(ValueBase):
    __tablename__ = "value_ticker_files"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime)
    as_of: Mapped[date] = mapped_column(Date)
    universe: Mapped[str] = mapped_column(String(16))  # trading | evidence | lookup
    fingerprint_key: Mapped[str] = mapped_column(String(16))
    fingerprint_json: Mapped[str] = mapped_column(Text)
    ruleset_version: Mapped[str] = mapped_column(String(32))
    ruleset_hash: Mapped[str] = mapped_column(String(12))
    company_class: Mapped[str] = mapped_column(String(16))
    data_quality: Mapped[str] = mapped_column(String(16))
    health: Mapped[str] = mapped_column(String(16))
    verdict_deep: Mapped[str] = mapped_column(String(16))
    verdict_growth: Mapped[str] = mapped_column(String(16))
    filed_list: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fair_value_deep: Mapped[float | None] = mapped_column(Float, nullable=True)
    fair_value_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    mos_deep: Mapped[float | None] = mapped_column(Float, nullable=True)
    mos_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_deep: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text)
    scorecard_json: Mapped[str] = mapped_column(Text)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ValueTickerHistoryRow(ValueBase):
    __tablename__ = "value_ticker_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16))
    recorded_at: Mapped[datetime] = mapped_column(DateTime)
    as_of: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(16))  # changed | session
    changed: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of what changed
    fingerprint_key: Mapped[str] = mapped_column(String(16))
    ruleset_version: Mapped[str] = mapped_column(String(32))
    summary_json: Mapped[str] = mapped_column(Text)
    scorecard_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # full on "changed"

    __table_args__ = (Index("ix_value_history_symbol_asof", "symbol", "as_of"),)


class ValueRunRow(ValueBase):
    __tablename__ = "value_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))  # dry_run | nightly | lookup
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    as_of: Mapped[date] = mapped_column(Date)
    ruleset_version: Mapped[str] = mapped_column(String(32))
    ruleset_hash: Mapped[str] = mapped_column(String(12))
    names: Mapped[int] = mapped_column(Integer, default=0)
    rs_cutoff_6m: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_url() -> str:
    """Absolute sqlite URL for the value database. Patched in tests."""
    return get_config().value_db_url_abs()


def get_value_engine() -> Engine:
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


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


def init_value_db() -> None:
    ValueBase.metadata.create_all(get_value_engine())


@contextmanager
def value_session() -> Iterator[Session]:
    get_value_engine()
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
