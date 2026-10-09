"""Normalise → dedupe → tag → cluster → persist (spec §5.3–5.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select

from src.common.config import NewsCfg
from src.data.protocols import NewsItem
from src.news import tagging, text
from src.news.store.models import NewsClusterRow, NewsItemRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session


@dataclass
class IngestResult:
    new_items: int = 0
    cluster_ids: set[int] = field(default_factory=set)


def _best_cluster(
    clusters: list[NewsClusterRow], tokens: frozenset[str], threshold: float
) -> NewsClusterRow | None:
    best, best_score = None, 0.0
    for c in clusters:
        score = text.jaccard(tokens, c.title_tokens)
        if score > best_score:
            best, best_score = c, score
    return best if best is not None and best_score >= threshold else None


def ingest(
    items: list[NewsItem],
    *,
    category: str,
    origin: str,
    alias_index: tagging.AliasIndex,
    cfg: NewsCfg,
    now: datetime,
    scheduled_symbols: frozenset[str] = frozenset(),
    scheduled_terms: tuple[str, ...] = (),
) -> IngestResult:
    result = IngestResult()
    now_n = naive_utc(now)
    window_start = now_n - timedelta(hours=cfg.cluster.window_hours)
    with news_session() as s:
        clusters = list(
            s.scalars(
                select(NewsClusterRow).where(
                    NewsClusterRow.category == category, NewsClusterRow.last_seen >= window_start
                )
            )
        )
        seen_url: set[str] = set()
        seen_title: set[str] = set()
        for item in items:
            title = (item.title or "").strip()
            if not title:
                continue
            uh = text.url_hash(item.url, title, item.source)
            th = text.title_hash(title, item.source)
            if uh in seen_url or th in seen_title:
                continue
            if s.scalar(select(NewsItemRow.id).where(NewsItemRow.url_hash == uh)) is not None:
                continue
            dup_title = s.scalar(
                select(NewsItemRow.id).where(
                    NewsItemRow.title_hash == th, NewsItemRow.fetched_at >= window_start
                )
            )
            if dup_title is not None:
                continue
            seen_url.add(uh)
            seen_title.add(th)

            tickers = tagging.tag_tickers(title, alias_index)
            low = title.lower()
            scheduled = bool(set(tickers) & scheduled_symbols) or any(
                t in low for t in scheduled_terms
            )
            tags = tagging.tag_events(title, scheduled=scheduled, cfg=cfg.tagging)
            # The publisher, not an aggregator's redirect host (every Google News link is on
            # news.google.com): source_count and source ranking count publishers.
            domain = (
                text.domain_of(item.source_url)
                or text.domain_of(item.url)
                or (item.source or "").lower()
                or None
            )
            tokens = text.title_tokens(title)

            cluster = _best_cluster(clusters, tokens, cfg.cluster.similarity)
            if cluster is None:
                cluster = NewsClusterRow(
                    headline=title[:500],
                    category=category,
                    first_seen=now_n,
                    last_seen=now_n,
                    source_domains=[domain] if domain else [],
                    source_count=1 if domain else 0,
                    tickers=tickers,
                    tags=tags,
                    topic_class=tagging.topic_class(title, cfg.tagging),
                    title_tokens=sorted(tokens),
                )
                s.add(cluster)
                s.flush()
                clusters.append(cluster)
            else:
                domains = set(cluster.source_domains or [])
                if domain:
                    domains.add(domain)
                cluster.source_domains = sorted(domains)
                cluster.source_count = len(domains)
                cluster.tickers = sorted(set(cluster.tickers or []) | set(tickers))
                cluster.tags = sorted(set(cluster.tags or []) | set(tags))
                cluster.last_seen = now_n

            s.add(
                NewsItemRow(
                    url_hash=uh,
                    title_hash=th,
                    title=title[:500],
                    url=item.url,
                    source=item.source,
                    source_domain=domain,
                    category=category,
                    origin=origin,
                    published_at=naive_utc(item.published) if item.published else None,
                    fetched_at=now_n,
                    tickers=tickers,
                    tags=tags,
                    det_sentiment=tagging.det_sentiment(title, cfg.sentiment.model),
                    summary=item.summary or None,
                    image_url=item.image_url or None,
                    cluster_id=cluster.id,
                )
            )
            result.new_items += 1
            result.cluster_ids.add(cluster.id)
    return result
