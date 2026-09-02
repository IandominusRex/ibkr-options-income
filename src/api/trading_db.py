"""Read-only access to the trading database.

The API reads positions, candidates and recommendations from `income_system.db` and writes
to it NEVER. That is enforced by SQLite itself through the `mode=ro` URI, not by convention:
an accidental INSERT raises OperationalError rather than corrupting operational state.
See design §4.3.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


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
