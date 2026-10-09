"""Read-write engine for data/news.db — imported only by the news process's modules.

src/api/ must never import this module (spec §10.6); it reads through src/api/news_db.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config
from src.news.store.models import NewsBase

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_url() -> str:
    """Absolute sqlite URL for data/news.db. Patched in tests."""
    return get_config().news_db_url_abs()


def get_news_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = _resolve_url()
        if url.startswith("sqlite:///"):
            Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True, connect_args={"timeout": 15})

        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def init_news_db() -> None:
    NewsBase.metadata.create_all(get_news_engine())


@contextmanager
def news_session() -> Iterator[Session]:
    get_news_engine()
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
