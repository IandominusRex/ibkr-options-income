"""Google News RSS search — keyless, no API key, the Task 11 :class:`NewsSearchProvider`.

Hits ``https://news.google.com/rss/search`` with a free-text query and a ``when:<days>d``
window, parsed with the stdlib :mod:`xml.etree.ElementTree` (no extra dependency). Wrapped in
the existing per-provider circuit breaker (:mod:`src.data.breaker`, name ``"google_news"``) and
an in-process, 15-minute-TTL per-query cache — Google News has no published rate limit, but a
scan/review cycle can call ``search`` several times a minute for the same handful of symbols, so
caching avoids hammering it for headlines that haven't changed in the last few minutes.

Like every provider in :mod:`src.data`, ``search`` never raises: a network error, a malformed
response, or a parse failure all degrade to an empty list, logged at DEBUG so a Google News
outage never blocks a review (CLAUDE.md's enrichment-must-degrade-independently rule).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

from src.data.breaker import get_breaker
from src.data.protocols import NewsItem

log = logging.getLogger(__name__)

_RSS_URL = "https://news.google.com/rss/search"
_USER_AGENT = "Mozilla/5.0 (compatible; ibkr-income-system/1.0)"
_TIMEOUT_SECONDS = 8.0
_CACHE_TTL_SECONDS = 15 * 60

# In-process, per-query cache: {(query, days): (cached_at_monotonic, items)}. Deliberately not a
# DB table (CLAUDE.md: "the 15-min per-query cache and breaker must be in-process") — this is
# ephemeral request de-duplication, not durable state.
_cache: dict[tuple[str, int], tuple[float, list[NewsItem]]] = {}
_cache_lock = threading.Lock()


def _cache_get(query: str, days: int) -> list[NewsItem] | None:
    with _cache_lock:
        entry = _cache.get((query, days))
        if entry is None:
            return None
        cached_at, items = entry
        if time.monotonic() - cached_at > _CACHE_TTL_SECONDS:
            del _cache[(query, days)]
            return None
        return items


def _cache_set(query: str, days: int, items: list[NewsItem]) -> None:
    with _cache_lock:
        _cache[(query, days)] = (time.monotonic(), items)


def _parse_pub_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None


def _parse_rss(xml_text: str, limit: int) -> list[NewsItem]:
    """Parse Google News RSS XML into `NewsItem`s. Raises on malformed XML — the caller
    catches broadly, consistent with every other provider's never-raises contract."""
    root = ElementTree.fromstring(xml_text)
    items: list[NewsItem] = []
    for elem in root.iter("item"):
        title = (elem.findtext("title") or "").strip()
        if not title:
            continue
        link = elem.findtext("link")
        source_el = elem.find("source")
        source = source_el.text if source_el is not None else None
        published = _parse_pub_date(elem.findtext("pubDate"))
        items.append(
            NewsItem(
                id="",
                title=title,
                source=source.strip() if source else None,
                published=published,
                url=link.strip() if link else None,
                source_url=(source_el.get("url") or None) if source_el is not None else None,
            )
        )
        if len(items) >= limit:
            break
    return items


class GoogleNewsSearchProvider:
    """`NewsSearchProvider` backed by Google News' keyless RSS search endpoint."""

    def search(self, query: str, *, days: int = 7, limit: int = 10) -> list[NewsItem]:
        """Recent news items matching *query* (newest first). Empty list on any failure.

        Cached in-process for 15 minutes per ``(query, days)`` pair; ``limit`` is applied
        after the cache lookup so a smaller follow-up request reuses a larger cached fetch.
        """
        cached = _cache_get(query, days)
        if cached is not None:
            return cached[:limit]

        breaker = get_breaker("google_news")
        if not breaker.allow():
            return []

        url = f"{_RSS_URL}?q={quote(query)}+when:{days}d&hl=en-US&gl=US&ceid=US:en"
        try:
            resp = httpx.get(url, timeout=_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
            items = _parse_rss(resp.text, limit=max(limit, 25))
        except Exception as exc:  # noqa: BLE001 — every provider in src.data never raises
            log.debug("google_news: search(%r, days=%d) failed: %s", query, days, exc)
            breaker.record_failure()
            return []

        breaker.record_success()
        _cache_set(query, days, items)
        return items[:limit]
