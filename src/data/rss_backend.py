"""RSS 2.0 / Atom feeds with HTTP conditional GET (ETag / Last-Modified), stdlib XML only.

The MarketGPT idea (spec §3): skip unchanged feeds with a 304 instead of re-downloading.
Never raises: network, HTTP and parse errors degrade to ``FeedFetch(items=[])`` and
record a breaker failure keyed by host, so one dead feed never blocks the others.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

from src.data.breaker import get_breaker
from src.data.protocols import FeedFetch, NewsItem

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; ibkr-income-system/1.0; news)"
_TIMEOUT = 10.0
_TAG = re.compile(r"<[^>]+>")
_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"


def _clean(s: str | None, limit: int = 1000) -> str | None:
    if not s:
        return None
    t = " ".join(_TAG.sub(" ", html.unescape(html.unescape(s))).split())
    return t[:limit] or None


def _date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _image(elem: ElementTree.Element) -> str | None:
    for tag in (f"{_MEDIA}content", f"{_MEDIA}thumbnail"):
        m = elem.find(tag)
        if m is not None and m.get("url"):
            return m.get("url")
    enc = elem.find("enclosure")
    if enc is not None and (enc.get("type") or "").startswith("image") and enc.get("url"):
        return enc.get("url")
    return None


def parse_feed(xml_text: str, limit: int) -> list[NewsItem]:
    root = ElementTree.fromstring(xml_text)
    out: list[NewsItem] = []
    if root.tag == f"{_ATOM}feed":
        for e in root.iter(f"{_ATOM}entry"):
            title = _clean(e.findtext(f"{_ATOM}title"), 500)
            if not title:
                continue
            link = e.find(f"{_ATOM}link")
            out.append(
                NewsItem(
                    title=title,
                    url=link.get("href") if link is not None else None,
                    published=_date(
                        e.findtext(f"{_ATOM}updated") or e.findtext(f"{_ATOM}published")
                    ),
                    summary=_clean(e.findtext(f"{_ATOM}summary")),
                )
            )
            if len(out) >= limit:
                break
        return out
    for e in root.iter("item"):
        title = _clean(e.findtext("title"), 500)
        if not title:
            continue
        href = (e.findtext("link") or "").strip() or None
        out.append(
            NewsItem(
                title=title,
                url=href,
                source=_clean(e.findtext("source"), 120),
                published=_date(e.findtext("pubDate")),
                summary=_clean(e.findtext("description")),
                image_url=_image(e),
            )
        )
        if len(out) >= limit:
            break
    return out


class RssFeedProvider:
    def fetch(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        limit: int = 50,
    ) -> FeedFetch:
        breaker = get_breaker(f"rss:{urlsplit(url).netloc}")
        if not breaker.allow():
            return FeedFetch(items=[], etag=etag, last_modified=last_modified)
        headers = {"User-Agent": _UA}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            resp = httpx.get(url, headers=headers, timeout=_TIMEOUT, follow_redirects=True)
            if resp.status_code == 304:
                breaker.record_success()
                return FeedFetch(
                    items=[], etag=etag, last_modified=last_modified, not_modified=True
                )
            resp.raise_for_status()
            items = parse_feed(resp.text, limit)
        except Exception as exc:  # noqa: BLE001 — providers never raise
            log.debug("rss: fetch %s failed: %s", url, exc)
            breaker.record_failure()
            return FeedFetch(items=[], etag=etag, last_modified=last_modified)
        breaker.record_success()
        return FeedFetch(
            items=items,
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
