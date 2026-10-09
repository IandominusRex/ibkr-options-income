"""Retention (spec §5.2): headlines older than news.retention_days, empty clusters and
alert bookkeeping older than 7 days are deleted. Posts (and their charts) are kept."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select

from src.news.store.models import AlertStateRow, NewsClusterRow, NewsItemRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session


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
        s.execute(
            delete(AlertStateRow).where(AlertStateRow.fired_at < naive_utc(now - timedelta(days=7)))
        )
    return int(n)
