"""News ingest for the warm/cold tier.

Reads ``get_news_provider().get_headlines(symbol, limit)``, handles both yfinance shapes
(the legacy flat ``title`` key and the newer ``{"content": {...}}`` nesting, as documented
in :mod:`src.data.protocols`), scores each headline with the VADER helper in
:mod:`src.analytics.sentiment`, and upserts :class:`NewsItemRow` rows deduplicated on
``(symbol, url)``.

Enrichment tier: news and its per-item sentiment reach the ticker-page card and the
reasoning prompt only — never the deterministic engine. The same fence that governs
:mod:`src.analytics.sentiment` governs this module.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.analytics.sentiment import _vader_compound
from src.data.factory import get_news_provider
from src.research.store.models import NewsItemRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)


def _extract(item: dict) -> dict[str, object | None]:
    """Normalise one yfinance news item across both shapes.

    Legacy flat shape: ``{"title": ..., "link"/"url": ..., "pubDate": ..., "publisher": ...}``
    Newer nested shape: ``{"content": {"title": ..., "url": ..., "pubDate": ..., "provider": {"displayName": ...}}}``
    Missing fields are ``None``; never raises.
    """
    content = item.get("content") if isinstance(item.get("content"), dict) else None
    blob: dict = content or item
    title = blob.get("title") or item.get("title")
    url = blob.get("url") or blob.get("link") or item.get("link")
    pub = blob.get("pubDate") or item.get("pubDate")
    publisher = blob.get("publisher")
    if isinstance(publisher, dict):
        publisher = publisher.get("displayName")
    if publisher is None:
        publisher = blob.get("provider")
        if isinstance(publisher, dict):
            publisher = publisher.get("displayName")
    return {
        "title": str(title) if title else None,
        "url": str(url) if url else None,
        "published_at": _parse_dt(pub) if pub else None,
        "source": str(publisher) if publisher else None,
    }


def _parse_dt(raw: str) -> datetime | None:
    """Parse yfinance's ISO-8601 pubDate (best-effort). Returns None on any failure."""
    try:
        # yfinance ships e.g. "2026-08-29T14:30:00Z" or with a timezone offset.
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def recent_news(symbol: str, limit: int = 25) -> list[dict]:
    """Fetch and normalise news for *symbol* into a list of dicts (no persistence).

    Returned for the analysis payload's news section. Each item has
    ``title, url, published_at, source, sentiment``. Empty list on failure. Never raises.
    """
    try:
        items = get_news_provider().get_headlines(symbol, limit=limit) or []
    except Exception as exc:
        log.warning("News fetch failed for %s: %s", symbol, exc)
        return []

    out: list[dict] = []
    for item in items:
        ex = _extract(item)
        if not ex["title"]:
            continue
        ex["sentiment"] = _vader_compound(str(ex["title"]))
        out.append(ex)

    # Newest first. The provider's own ordering isn't a documented contract, so this is
    # enforced here rather than relied on; items with an unparseable date sort last.
    out.sort(key=lambda x: x["published_at"] or datetime.min.replace(tzinfo=UTC), reverse=True)
    return out


def ingest_news(symbol: str, limit: int = 25) -> int:
    """Fetch, score, and upsert news for *symbol*. Returns rows written.

    Deduplicated on ``(symbol, url)``: a re-ingest updates the title/sentiment/timestamp
    for an existing URL rather than duplicating. Items without a URL are always inserted
    (no natural key); duplicates among them are tolerated.
    """
    rows = recent_news(symbol, limit=limit)
    if not rows:
        return 0

    written = 0
    with research_session() as session:
        existing_by_url: dict[str, NewsItemRow | None] = {
            r.url: r for r in session.query(NewsItemRow).filter_by(symbol=symbol).all() if r.url
        }
        for r in rows:
            title = str(r["title"])
            url = r["url"] if isinstance(r["url"], str) else None
            pub = r["published_at"] if isinstance(r["published_at"], datetime) else None
            source = r["source"] if isinstance(r["source"], str) else None
            sentiment = float(r["sentiment"]) if r["sentiment"] is not None else None
            target = existing_by_url.get(url) if url else None
            if target is not None:
                target.title = title
                target.published_at = pub
                target.source = source
                target.sentiment = sentiment
            else:
                session.add(
                    NewsItemRow(
                        symbol=symbol,
                        title=title,
                        url=url,
                        published_at=pub,
                        source=source,
                        sentiment=sentiment,
                    )
                )
                if url:
                    existing_by_url[url] = None  # placeholder; not re-looked in this run
            written += 1
    return written
