"""Engine and session factory for `data/research.db`.

WAL mode, matching the trading database, so the API can read while the worker writes.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config
from src.research.store.models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_url() -> str:
    """Absolute sqlite URL for the research database. Patched in tests."""
    return get_config().research_db_url_abs()


def get_research_engine() -> Engine:
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
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def init_research_db() -> None:
    """Create every research table, then backfill any columns a later milestone added.

    ``create_all()`` only creates tables that don't exist yet — it never alters one that
    does. A ``data/research.db`` left over from an earlier milestone (e.g. M2, before M3
    added ``financials.form`` and ``company_facts_raw.etag``) silently keeps the old
    schema, and every query touching the new column then fails with
    ``OperationalError: no such column``. There's no migration framework in this project
    (a single-owner SQLite research cache doesn't warrant Alembic), so this backfills
    missing columns directly via SQLite's ``ALTER TABLE ... ADD COLUMN``. Idempotent.
    """
    engine = get_research_engine()
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table.name})")
            }
            for column in table.columns:
                if column.name not in existing:
                    col_type = column.type.compile(engine.dialect)
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"
                    )


@contextmanager
def research_session() -> Iterator[Session]:
    """Transactional scope around a research-database session."""
    get_research_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
