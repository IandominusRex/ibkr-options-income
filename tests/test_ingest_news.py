"""News ingest handles both yfinance shapes and upserts on (symbol, url)."""

from __future__ import annotations

import pytest

from src.research.ingest.news import _extract, ingest_news, recent_news
from src.research.store.models import NewsItemRow
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def test_extract_legacy_flat_shape() -> None:
    ex = _extract(
        {
            "title": "AAPL up",
            "link": "http://x",
            "pubDate": "2026-08-29T14:30:00Z",
            "publisher": "Reuters",
        }
    )
    assert ex["title"] == "AAPL up"
    assert ex["url"] == "http://x"
    assert ex["source"] == "Reuters"
    assert ex["published_at"] is not None


def test_extract_nested_content_shape() -> None:
    ex = _extract(
        {
            "content": {
                "title": "AAPL down",
                "url": "http://y",
                "pubDate": "2026-08-30T10:00:00Z",
                "provider": {"displayName": "Bloomberg"},
            }
        }
    )
    assert ex["title"] == "AAPL down"
    assert ex["url"] == "http://y"
    assert ex["source"] == "Bloomberg"


def test_extract_missing_fields_are_none() -> None:
    ex = _extract({"title": "No URL here"})
    assert ex["title"] == "No URL here"
    assert ex["url"] is None
    assert ex["published_at"] is None
    assert ex["source"] is None


def test_recent_news_scores_each_headline(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.news.get_news_provider",
        lambda: type(
            "P",
            (),
            {
                "get_headlines": staticmethod(
                    lambda sym, limit=25: [{"title": "AAPL surges"}, {"title": "AAPL crashes"}]
                )
            },
        )(),
    )
    rows = recent_news("AAPL")
    assert len(rows) == 2
    assert rows[0]["title"] == "AAPL surges"
    assert "sentiment" in rows[0]
    assert isinstance(rows[0]["sentiment"], float)


def test_ingest_news_upserts_on_url(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.news.get_news_provider",
        lambda: type(
            "P",
            (),
            {
                "get_headlines": staticmethod(
                    lambda sym, limit=25: [{"title": "Old", "link": "http://x"}]
                )
            },
        )(),
    )
    assert ingest_news("AAPL") == 1
    monkeypatch.setattr(
        "src.research.ingest.news.get_news_provider",
        lambda: type(
            "P",
            (),
            {
                "get_headlines": staticmethod(
                    lambda sym, limit=25: [{"title": "Updated", "link": "http://x"}]
                )
            },
        )(),
    )
    assert ingest_news("AAPL") == 1
    with research_session() as s:
        rows = s.query(NewsItemRow).filter_by(symbol="AAPL").all()
        assert len(rows) == 1
        assert rows[0].title == "Updated"


def test_ingest_news_empty_fetch_writes_nothing(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.news.get_news_provider",
        lambda: type("P", (), {"get_headlines": staticmethod(lambda sym, limit=25: [])})(),
    )
    assert ingest_news("AAPL") == 0
