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
    # Frozen approved candidate payload (N2a) — see Approval/Order row docstrings.
    "approvals": {
        "snapshot": "JSON",
    },
    "orders": {
        "snapshot": "JSON",
    },
    # risk_verdicts existed as an empty, unwired table long before anything wrote to it, so
    # deployed databases already have the original three-column shape. These are the columns
    # added when the assessment audit trail was turned on.
    "risk_verdicts": {
        "run_id": "VARCHAR(40)",
        "symbol": "VARCHAR(16)",
        "strategy": "VARCHAR(20)",
        "strike": "FLOAT",
        "expiry": "DATE",
        "stage": "VARCHAR(16)",
        "blended_score": "FLOAT",
        "premium": "FLOAT",
        "ideal_lo": "FLOAT",
        "ideal_hi": "FLOAT",
        "min_credit": "FLOAT",
        # Quote microstructure behind a liquidity verdict (Task 7 — split `illiquid` into
        # precise sub-reasons). See RiskVerdictRow.liquidity docstring.
        "liquidity": "JSON",
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
    # At most one *pending* command per dedupe key. ``promote``/``roll_request`` key on a
    # target (candidate_id / position_symbol) that outlives one approval cycle, so this must
    # NOT be a global constraint — see ``_ensure_app_commands_pending_only_dedupe`` below,
    # which rebuilds a pre-existing table that still carries the old global one.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_app_commands_dedupe_key_pending "
    "ON app_commands (dedupe_key) WHERE status = 'pending'",
]

# Columns making up the ``app_commands`` table, in schema order, before the M7.1 dedupe-key
# fix. Used only to rebuild the table when migrating away from its old global unique
# constraint (see ``_ensure_app_commands_pending_only_dedupe``) — kept separate from the ORM
# model so a future column addition to ``AppCommandRow`` doesn't silently change what this
# one-time migration copies.
_APP_COMMANDS_COLUMNS = (
    "id",
    "kind",
    "payload",
    "dedupe_key",
    "status",
    "result",
    "requested_by",
    "confirm_token",
    "created_at",
    "applied_at",
)


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
    """WAL mode + a busy timeout so concurrent processes (approval_service,
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


def _ensure_app_commands_pending_only_dedupe(engine: Engine) -> None:
    """Rebuild ``app_commands`` if it still carries the pre-fix global UNIQUE on ``dedupe_key``.

    That constraint fired regardless of a row's status, so a ``promote``/``roll_request``
    dedupe key — stable for a candidate's/position's whole lifetime, unlike ``approve``'s
    per-decision ``approval_id`` — permanently blocked a fresh request once the first one had
    already been applied: a re-promote after the original approval expired silently no-op'd
    with the OLD command's stale "Applied" receipt (STATUS.md's "Remaining known issues").
    The replacement, ``uq_app_commands_dedupe_key_pending`` in ``_PARTIAL_INDEXES``, scopes
    the same protection to ``status = 'pending'``.

    SQLite has no ``ALTER TABLE ... DROP CONSTRAINT``, so a table created before this fix is
    rebuilt: a fresh table without the constraint, the data copied across by explicit column
    list (order-independent, immune to a future column addition reordering anything), the old
    table dropped, and the new one renamed into place — one transaction, so a mid-run crash
    just leaves the untouched original table for this function to retry cleanly next startup.
    A table created fresh by ``create_all()`` (no ``unique=True`` in the model any more) never
    matches the detection below and this is a no-op.
    """
    inspector = inspect(engine)
    if "app_commands" not in inspector.get_table_names():
        return  # create_all will have built it without the old constraint
    has_old_constraint = any(
        uc["column_names"] == ["dedupe_key"]
        for uc in inspector.get_unique_constraints("app_commands")
    )
    if not has_old_constraint:
        return
    cols = ", ".join(_APP_COMMANDS_COLUMNS)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS app_commands__migrating"))
        conn.execute(
            text(
                "CREATE TABLE app_commands__migrating ("
                "id INTEGER NOT NULL, "
                "kind VARCHAR(24) NOT NULL, "
                "payload JSON NOT NULL, "
                "dedupe_key VARCHAR(96), "
                "status VARCHAR(10) NOT NULL, "
                "result JSON, "
                "requested_by VARCHAR(64) NOT NULL, "
                "confirm_token VARCHAR(128), "
                "created_at DATETIME NOT NULL, "
                "applied_at DATETIME, "
                "PRIMARY KEY (id)"
                ")"
            )
        )
        conn.execute(
            text(f"INSERT INTO app_commands__migrating ({cols}) SELECT {cols} FROM app_commands")
        )
        conn.execute(text("DROP TABLE app_commands"))
        conn.execute(text("ALTER TABLE app_commands__migrating RENAME TO app_commands"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_app_commands_kind ON app_commands (kind)"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_app_commands_status ON app_commands (status)")
        )


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
    _ensure_app_commands_pending_only_dedupe(_engine)
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
