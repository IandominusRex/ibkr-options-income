# tests/test_news_sentiment_integration.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)


def _seed(rows):
    from src.news.store.models import NewsItemRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        for i, (score, hours_ago, cluster, sym) in enumerate(rows):
            s.add(
                NewsItemRow(
                    url_hash=f"u{i}",
                    title_hash=f"t{i}",
                    title=f"headline {i}",
                    category="ticker",
                    origin="google",
                    fetched_at=naive_utc(NOW - timedelta(hours=hours_ago)),
                    tickers=[sym],
                    tags=[],
                    det_sentiment=score,
                    cluster_id=cluster,
                )
            )


def test_recency_weighted_store_sentiment(news_db) -> None:
    from src.analytics.sentiment import _news_from_store

    _seed(
        [
            (0.8, 1, 1, "NVDA"),
            (-0.8, 48, 2, "NVDA"),
            (0.5, 2, 1, "NVDA"),
            (0.9, 1, 3, "AAPL"),
            (0.9, 100, 4, "NVDA"),
        ]
    )
    score, count, top = _news_from_store("NVDA", now=NOW)
    assert count == 2  # distinct clusters within 72h (the 100h-old item is out)
    assert 50 < score < 90  # recent positives outweigh the 48h-old negative
    assert top == "headline 0"


def test_store_missing_falls_back_to_yfinance(tmp_path, monkeypatch) -> None:
    from src.analytics import sentiment
    from src.news.store import readonly

    readonly.reset_engine()
    monkeypatch.setattr(readonly, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    assert sentiment._news_from_store("NVDA", now=NOW) is None
    monkeypatch.setattr(sentiment, "_load_sentiment_cache", lambda s, src: None)
    monkeypatch.setattr(sentiment, "_save_sentiment_cache", lambda *a: None)
    monkeypatch.setattr(
        "src.data.factory.get_news_provider",
        lambda: type(
            "P",
            (),
            {"get_headlines": lambda self, s, limit=50: [{"title": "NVDA surges to record"}]},
        )(),
    )
    score, count, top = sentiment._fetch_news.__wrapped__(
        "NVDA"
    )  # daily_cached uses functools.wraps
    assert count == 1 and top == "NVDA surges to record"


def test_store_answer_wins_and_skips_the_disk_cache(news_db, monkeypatch) -> None:
    from src.analytics import sentiment

    _seed([(0.6, 1, 1, "NVDA")])
    real = sentiment._news_from_store
    monkeypatch.setattr(sentiment, "_news_from_store", lambda s: real(s, now=NOW))

    def boom(*a, **k):
        raise AssertionError("the yfinance path / disk cache must not run when the store answered")

    monkeypatch.setattr(sentiment, "_load_sentiment_cache", boom)
    monkeypatch.setattr(sentiment, "_save_sentiment_cache", boom)
    score, count, top = sentiment._fetch_news.__wrapped__("NVDA")
    assert score is not None and score > 50 and count == 1 and top == "headline 0"


def test_symbol_with_no_store_rows_is_none(news_db) -> None:
    from src.analytics.sentiment import _news_from_store

    _seed([(0.9, 1, 3, "AAPL")])
    assert _news_from_store("NVDA", now=NOW) is None


def test_tests_never_read_the_operators_news_db() -> None:
    # Without the news_db fixture, sentiment._fetch_news must not see a real data/news.db
    # (it would make test_sentiment depend on whatever the news service last collected).
    from pathlib import Path

    from src.news.store import readonly

    root = Path(__file__).resolve().parents[1]
    assert not Path(readonly._resolve_path()).resolve().is_relative_to(root / "data")
