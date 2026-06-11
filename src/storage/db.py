"""SQLAlchemy engine + session factory. SQLite for v1.

The DB is the integration backbone: every pipeline stage persists here so runs
are resumable/inspectable and Telegram/dashboard read from one source of truth.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config
from src.storage.models import Base

_engine = None
_SessionLocal: sessionmaker[Session] | None = None

# New columns added after the original schema. SQLAlchemy's create_all() never ALTERs an
# existing table, so a DB created before these columns existed would be missing them. We
# add them in-place on init (cheap, idempotent) rather than requiring Alembic for v1.
# table -> {column: "<SQL column definition>"}
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "fills": {
        "action": "VARCHAR(4) DEFAULT 'SELL'",
        "entry_iv": "FLOAT",
    },
}

# Partial/conditional indexes that SQLAlchemy's model metadata can't express portably.
# Applied idempotently on init. Supported by both SQLite and Postgres.
_PARTIAL_INDEXES: list[str] = [
    # At most one *working* order per candidate. This is the hard DB-level backstop for
    # the application guard in storage.orders.has_active_order: it closes the race where
    # two concurrent callbacks for two different approvals of the same candidate both
    # create a QUEUED order. FILLED/PARTIAL are intentionally excluded so a strike/expiry
    # can be legitimately re-sold after a buy-to-close.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_active_candidate "
    "ON orders (candidate_id) WHERE state IN ('queued', 'submitted')",
]


def _init() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        return
    cfg = get_config()
    url = cfg.db_url_abs()
    # Ensure the data directory exists so SQLite can create the file on first run.
    if url.startswith("sqlite"):
        db_path = Path(url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args, future=True)
    if url.startswith("sqlite"):
        _enable_sqlite_concurrency(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def _enable_sqlite_concurrency(engine: Engine) -> None:
    """WAL mode + a busy timeout so concurrent processes (morning_scan, approval_service,
    monitor, eod) don't immediately hit 'database is locked'. WAL lets readers proceed
    during a write; busy_timeout makes a writer wait instead of failing."""

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn: Any, _rec: object) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


def _ensure_added_columns(engine: Engine) -> None:
    """Add any post-schema columns missing from an existing DB (lightweight migration).

    Each ALTER is executed in its own transaction so a duplicate-column error from a
    concurrent startup doesn't abort the entire migration run.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, cols in _ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue  # create_all will have built it with all columns
        present = {c["name"] for c in inspector.get_columns(table)}
        for col, ddl in cols.items():
            if col not in present:
                try:
                    with engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                except Exception as exc:
                    if "duplicate column" in str(exc).lower():
                        pass  # another process beat us to it — idempotent
                    else:
                        raise


def _ensure_indexes(engine: Engine) -> None:
    """Create partial/conditional indexes not expressible in the model metadata.

    Each runs in its own transaction with IF NOT EXISTS so repeated startups and
    concurrent processes are harmless.
    """
    for ddl in _PARTIAL_INDEXES:
        try:
            with engine.begin() as conn:
                conn.execute(text(ddl))
        except Exception as exc:
            if "already exists" in str(exc).lower():
                continue
            raise


def init_db() -> None:
    """Create all tables, then patch in any newly-added columns. Safe to call repeatedly."""
    _init()
    assert _engine is not None
    Base.metadata.create_all(_engine)
    _ensure_added_columns(_engine)
    _ensure_indexes(_engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session context. Commits on success, rolls back on error."""
    _init()
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
