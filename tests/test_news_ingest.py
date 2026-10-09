from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.common.config import get_config
from src.data.protocols import NewsItem
from src.news.tagging import build_alias_index

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
IDX = build_alias_index(["NVDA", "AAPL"], {})


def _ingest(items, **kw):
    from src.news.ingest import ingest

    return ingest(
        items,
        category=kw.pop("category", "ticker"),
        origin="google",
        alias_index=IDX,
        cfg=get_config().news,
        now=kw.pop("now", NOW),
        **kw,
    )


def test_same_url_and_same_title_dedupe(news_db) -> None:
    a = NewsItem(
        title="NVDA falls on export curbs - Reuters",
        source="Reuters",
        url="https://reuters.com/a?utm_source=x",
    )
    b = NewsItem(title="NVDA falls on export curbs", source="Yahoo", url="https://reuters.com/a")
    c = NewsItem(title="nvda falls on export curbs!", source="CNBC", url="https://cnbc.com/c")
    r = _ingest([a, b, c])
    assert r.new_items == 1


def test_similar_titles_join_one_cluster_and_count_domains(news_db) -> None:
    from src.news.store.models import NewsClusterRow
    from src.news.store.session import news_session

    r = _ingest(
        [
            NewsItem(
                title="Nvidia shares fall after new China export curbs", url="https://reuters.com/1"
            ),
            NewsItem(
                title="Nvidia shares fall on fresh China export curbs", url="https://cnbc.com/2"
            ),
            NewsItem(title="Apple unveils new iPhone lineup", url="https://cnbc.com/3"),
        ]
    )
    assert r.new_items == 3 and len(r.cluster_ids) == 2
    with news_session() as s:
        rows = {c.headline: c for c in s.query(NewsClusterRow)}
    nv = next(c for h, c in rows.items() if "Nvidia" in h)
    assert nv.source_count == 2 and set(nv.source_domains) == {"reuters.com", "cnbc.com"}


def test_cluster_window_expires(news_db) -> None:
    _ingest([NewsItem(title="Nvidia shares fall after China export curbs", url="https://a.com/1")])
    later = NOW + timedelta(hours=get_config().news.cluster.window_hours + 1)
    r = _ingest(
        [
            NewsItem(
                title="Nvidia shares fall after China export curbs again", url="https://b.com/2"
            )
        ],
        now=later,
    )
    assert len(r.cluster_ids) == 1
    from src.news.store.models import NewsClusterRow
    from src.news.store.session import news_session

    with news_session() as s:
        assert s.query(NewsClusterRow).count() == 2


def test_tags_and_tickers_persist(news_db) -> None:
    from src.news.store.models import NewsItemRow
    from src.news.store.session import news_session

    _ingest(
        [
            NewsItem(
                title="NVDA reportedly weighs $2 billion deal",
                url="https://x.com/1",
                summary="s",
                image_url="https://img/1.png",
            )
        ],
        scheduled_symbols=frozenset({"NVDA"}),
    )
    with news_session() as s:
        row = s.query(NewsItemRow).one()
    assert row.tickers == ["NVDA"]
    assert {"rumor", "quantified", "scheduled"} <= set(row.tags)
    assert row.image_url == "https://img/1.png" and row.summary == "s"
    assert row.det_sentiment is not None


def test_ticker_query_item_without_match_is_background(news_db) -> None:
    from src.news.store.models import NewsItemRow
    from src.news.store.session import news_session

    _ingest([NewsItem(title="Chipmakers rally as AI demand grows", url="https://x.com/2")])
    with news_session() as s:
        assert s.query(NewsItemRow).one().tickers == []


def test_google_items_count_publishers_not_the_aggregator(news_db) -> None:
    """Final review: every Google News link is on news.google.com, so a story carried by Reuters
    and CNBC counted ONE source — the ≥2-source breaking trigger and source ranking never saw
    the publishers."""
    from src.news.store.models import NewsClusterRow
    from src.news.store.session import news_session

    _ingest(
        [
            NewsItem(
                title="Oil jumps after strike on Gulf refinery",
                source="Reuters",
                url="https://news.google.com/rss/articles/1",
                source_url="https://www.reuters.com",
            ),
            NewsItem(
                title="Oil jumps after a strike on Gulf refinery",
                source="CNBC",
                url="https://news.google.com/rss/articles/2",
                source_url="https://www.cnbc.com",
            ),
        ],
        category="geopolitics",
    )
    with news_session() as s:
        (c,) = s.query(NewsClusterRow).all()
    assert c.source_count == 2 and set(c.source_domains) == {"reuters.com", "cnbc.com"}


def test_sentiment_is_scored_outside_the_write_transaction_and_only_for_new_titles(
    news_db, monkeypatch
) -> None:
    """FinBERT is tens of ms a headline: scoring inside ingest's transaction held news.db's
    write lock for the whole batch. A re-polled duplicate is never scored again."""
    from contextlib import contextmanager

    import src.news.ingest as I
    import src.news.tagging as tagging

    real = I.news_session
    state = {"open": False}
    scored: list[str] = []

    @contextmanager
    def tracked():
        with real() as s:
            state["open"] = True
            try:
                yield s
            finally:
                state["open"] = False

    def score(title, model="vader"):
        assert not state["open"], "scored with a news.db session open"
        scored.append(title)
        return 0.5

    monkeypatch.setattr(I, "news_session", tracked)
    monkeypatch.setattr(tagging, "det_sentiment", score)
    a = NewsItem(title="Nvidia beats estimates", url="https://x.com/a", source="Reuters")
    assert _ingest([a]).new_items == 1
    assert _ingest([a]).new_items == 0
    assert scored == ["Nvidia beats estimates"]
