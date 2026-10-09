"""Session-parameterised read helpers over data/news.db.

Takes a Session and never opens one, so the news process (read-write engine), the API
(src/api/news_db.py, read-only) and the read-only readers share one query implementation.
Imports no engine module — src/api/ may import this file (spec §10.6).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.news.schemas import ClusterView, EarningsView, EconEventView, ItemView
from src.news.store.models import EarningsEventRow, EconEventRow, NewsClusterRow, NewsItemRow


def naive_utc(dt: datetime) -> datetime:
    """Aware → naive UTC for storage (the spreads-store convention). Naive input is assumed UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def aware_utc(dt: datetime) -> datetime:
    """Stored naive-UTC → aware UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _cluster(s: Session, c: NewsClusterRow, max_items: int) -> ClusterView:
    items = s.scalars(
        select(NewsItemRow)
        .where(NewsItemRow.cluster_id == c.id)
        .order_by(NewsItemRow.fetched_at)
        .limit(max_items)
    )
    return ClusterView(
        id=c.id,
        headline=c.headline,
        category=c.category,
        first_seen=aware_utc(c.first_seen),
        last_seen=aware_utc(c.last_seen),
        source_count=c.source_count,
        source_domains=list(c.source_domains or []),
        tickers=list(c.tickers or []),
        tags=list(c.tags or []),
        topic_class=c.topic_class,
        items=[
            ItemView(
                title=i.title,
                url=i.url,
                source=i.source,
                source_domain=i.source_domain,
                published_at=aware_utc(i.published_at) if i.published_at else None,
                summary=i.summary,
                image_url=i.image_url,
                det_sentiment=i.det_sentiment,
            )
            for i in items
        ],
    )


def cluster_view(s: Session, cid: int, *, max_items: int = 6) -> ClusterView | None:
    c = s.get(NewsClusterRow, cid)
    return None if c is None else _cluster(s, c, max_items)


def clusters_since(
    s: Session,
    since: datetime,
    *,
    category: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[ClusterView]:
    q = select(NewsClusterRow).where(NewsClusterRow.last_seen >= naive_utc(since))
    if category:
        q = q.where(NewsClusterRow.category == category)
    rows = list(
        s.scalars(
            q.order_by(NewsClusterRow.source_count.desc(), NewsClusterRow.last_seen.desc()).limit(
                limit * 4
            )
        )
    )
    if symbol:
        rows = [r for r in rows if symbol.upper() in (r.tickers or [])]
    return [_cluster(s, r, 6) for r in rows[:limit]]


def econ_view(r: EconEventRow) -> EconEventView:
    return EconEventView(
        event_key=r.event_key,
        title=r.title,
        playbook_key=r.playbook_key,
        scheduled_at=aware_utc(r.scheduled_at),
        impact=r.impact,
        forecast=r.forecast,
        previous=r.previous,
        consensus=r.consensus,
        actual=r.actual,
        surprise_dir=r.surprise_dir,
    )


def econ_events_between(s: Session, start: datetime, end: datetime) -> list[EconEventView]:
    rows = s.scalars(
        select(EconEventRow)
        .where(
            EconEventRow.scheduled_at >= naive_utc(start),
            EconEventRow.scheduled_at < naive_utc(end),
        )
        .order_by(EconEventRow.scheduled_at)
    )
    return [econ_view(r) for r in rows]


def earnings_between(
    s: Session, start: date, end: date, symbols: set[str] | None = None
) -> list[EarningsView]:
    rows = s.scalars(
        select(EarningsEventRow)
        .where(EarningsEventRow.report_date >= start, EarningsEventRow.report_date <= end)
        .order_by(EarningsEventRow.report_date, EarningsEventRow.symbol)
    )
    return [
        EarningsView(
            symbol=r.symbol,
            report_date=r.report_date,
            timing=r.timing,
            eps_est=r.eps_est,
            eps_actual=r.eps_actual,
            rev_est=r.rev_est,
            rev_actual=r.rev_actual,
            status=r.status,
        )
        for r in rows
        if symbols is None or r.symbol in symbols
    ]
