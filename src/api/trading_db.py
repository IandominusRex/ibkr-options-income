"""Read-only and command-scoped access to the trading database.

The API reads positions, candidates and recommendations from `income_system.db` and
writes to exactly one table — `app_commands` — through a separate read-write engine.
The read path is enforced by SQLite itself through the `mode=ro` URI (an accidental
INSERT raises OperationalError). The write path is enforced structurally:
`get_command_engine` is imported from `src/api/commands.py` only, and a runtime
listener on the command session rejects any flush that targets a table other than
`app_commands`. See design §4.2.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config
from src.storage.models import AppCommandRow

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

# The write-scoped engine — app_commands only. Imported from src/api/commands.py only.
# tests/test_web_fence.py asserts that no other module imports get_command_engine.
_cmd_engine: Engine | None = None
_cmd_session_factory: sessionmaker[Session] | None = None


def read_only_url(db_path: str) -> str:
    """SQLAlchemy URL that opens `db_path` read-only via SQLite's URI filename syntax."""
    return f"sqlite:///file:{db_path}?mode=ro&uri=true"


def _resolve_path() -> str:
    url = get_config().db_url_abs()
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"Trading DB must be sqlite for read-only access, got {url!r}")
    return url[len(prefix) :]


def get_trading_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(read_only_url(_resolve_path()), future=True)
        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


@contextmanager
def trading_session() -> Iterator[Session]:
    """Read-only session against the trading database. Never commits."""
    get_trading_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_command_engine() -> Engine:
    """Read-WRITE engine on the trading database, for app_commands and nothing else.

    Import this from src/api/commands.py only. tests/test_web_fence.py asserts that.
    The runtime listener in command_session rejects any flush targeting a table
    other than app_commands.
    """
    global _cmd_engine, _cmd_session_factory
    if _cmd_engine is None:
        path = _resolve_path()
        _cmd_engine = create_engine(f"sqlite:///{path}", future=True)
        _cmd_session_factory = sessionmaker(bind=_cmd_engine, future=True, expire_on_commit=False)
    return _cmd_engine


class WriteFenceViolation(Exception):
    """Raised when the command engine tries to flush a non-app_commands object."""


def _on_before_flush(session: Session, _flush_context: object, _instances: object) -> None:
    """Raise if any non-AppCommandRow object is in the flush set.

    Spec §4.2: the guarantee is structural, not conventional. This listener raises
    before the flush reaches the database, naming the offending table in the message,
    so an accidental INSERT into orders from the write path fails loudly rather than
    corrupting operational state. The read-only engine already raises OperationalError
    on any write; this is the symmetric guard on the write engine.
    """
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if not isinstance(obj, AppCommandRow):
            tbl = getattr(obj, "__tablename__", type(obj).__name__)
            raise WriteFenceViolation(f"command engine may only write app_commands, not {tbl}")


@contextmanager
def command_session() -> Iterator[Session]:
    """Write session for app_commands only. The fence rejects anything else."""
    get_command_engine()
    assert _cmd_session_factory is not None
    session = _cmd_session_factory()
    event.listen(session, "before_flush", _on_before_flush)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
