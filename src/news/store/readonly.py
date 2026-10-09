"""Read-only access to data/news.db for readers outside the news process.

Used by src/analytics/sentiment.py, src/claude/news_context.py, src/news/briefs.py's
reads and the watchdog. Opens SQLite with ``mode=ro`` so an accidental write raises.
Yields ``None`` when the file does not exist yet (fresh install) or cannot be opened —
callers treat that as "no news" and fall back (Review Focus 5).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config

log = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_path() -> str:
    """Filesystem path of data/news.db. Patched in tests."""
    url = get_config().news_db_url_abs()
    return url[len("sqlite:///") :] if url.startswith("sqlite:///") else url


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


@contextmanager
def read_only_session() -> Iterator[Session | None]:
    global _engine, _SessionLocal
    path = _resolve_path()
    if not Path(path).exists():
        yield None
        return
    try:
        if _engine is None:
            _engine = create_engine(
                f"sqlite:///file:{path}?mode=ro&uri=true",
                future=True,
                connect_args={"timeout": 5},
            )
            _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
        assert _SessionLocal is not None
        s = _SessionLocal()
        s.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — readers must degrade, never raise
        log.debug("news readonly: cannot open %s: %s", path, exc)
        yield None
        return
    try:
        yield s
    finally:
        s.rollback()
        s.close()
