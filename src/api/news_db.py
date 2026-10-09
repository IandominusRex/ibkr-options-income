"""Read-only access to data/news.db for the web API (spec §7.6, fence §10.6).

The API never imports src.news.store.session (the news process's read-write engine). Opens
SQLite with mode=ro; yields None when the file does not exist yet, so every /news route can
answer `available: false` instead of a 500 on a fresh install.
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
def news_read_session() -> Iterator[Session | None]:
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
    except Exception as exc:  # noqa: BLE001 — a /news route degrades, never 500s
        log.debug("api news_db: cannot open %s: %s", path, exc)
        yield None
        return
    try:
        yield s
    finally:
        s.rollback()
        s.close()
