from __future__ import annotations

from pathlib import Path

import httpx

from src.data.protocols import FeedFetch
from src.data.rss_backend import RssFeedProvider, parse_feed

FIX = Path(__file__).parent / "fixtures" / "news"


def test_parse_rss_items_images_and_bad_dates() -> None:
    items = parse_feed((FIX / "rss_sample.xml").read_text(), limit=10)
    assert [i.title for i in items] == [
        "Fed holds rates steady, signals patience",
        "CPI rises 0.4% in September",
    ]
    assert items[0].image_url == "https://img.example.com/fed.jpg"
    assert items[0].published is not None and items[0].published.year == 2026
    assert items[0].summary == "The Federal Open Market Committee decided…"
    assert items[1].published is None and items[1].image_url == "https://img.example.com/cpi.png"


def test_parse_atom() -> None:
    items = parse_feed((FIX / "atom_sample.xml").read_text(), limit=10)
    assert items[0].url == "https://home.treasury.gov/news/press-releases/x1"
    assert items[0].published is not None


def test_conditional_get_304_and_failure(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_get(url, headers, timeout, follow_redirects):
        calls.append(headers)
        if headers.get("If-None-Match") == '"abc"':
            return httpx.Response(304, request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            text=(FIX / "rss_sample.xml").read_text(),
            headers={"ETag": '"abc"', "Last-Modified": "Thu, 09 Oct 2026 18:00:00 GMT"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("src.data.rss_backend.httpx.get", fake_get)
    p = RssFeedProvider()
    first = p.fetch("https://feed.example/rss")
    assert isinstance(first, FeedFetch) and len(first.items) == 2 and first.etag == '"abc"'
    second = p.fetch("https://feed.example/rss", etag='"abc"')
    assert second.not_modified and second.items == []

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("src.data.rss_backend.httpx.get", boom)
    assert RssFeedProvider().fetch("https://other.example/rss").items == []
