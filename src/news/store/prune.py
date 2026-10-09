"""Retention (spec §5.2): headlines older than news.retention_days, empty clusters and
alert bookkeeping (fired and held-back alerts) older than 7 days are deleted. Posts (and
their charts) are kept."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select

from src.news.store.models import AlertStateRow, NewsClusterRow, NewsItemRow, NewsStateRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.store.state import HELD_PREFIX


def prune(now: datetime, *, retention_days: int) -> int:
    cutoff = naive_utc(now - timedelta(days=retention_days))
    with news_session() as s:
        res = s.execute(delete(NewsItemRow).where(NewsItemRow.fetched_at < cutoff))
        # rowcount is a CursorResult attribute; mypy only sees the ORM-wrapped result.
        n = getattr(res, "rowcount", 0) or 0
        live = select(NewsItemRow.cluster_id).where(NewsItemRow.cluster_id.is_not(None))
        s.execute(
            delete(NewsClusterRow).where(
                NewsClusterRow.last_seen < cutoff, NewsClusterRow.id.not_in(live)
            )
        )
        week_ago = naive_utc(now - timedelta(days=7))
        s.execute(delete(AlertStateRow).where(AlertStateRow.fired_at < week_ago))
        s.execute(  # held alerts no digest ever consumed (e.g. digests disabled)
            delete(NewsStateRow).where(
                NewsStateRow.key.startswith(HELD_PREFIX, autoescape=True),
                NewsStateRow.updated_at < week_ago,
            )
        )
    return int(n)
