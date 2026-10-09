"""Tests for `src.claude.news_context` (Task 11) — the `=== NEWS ===` block builder.

`_fetch` (the per-query provider call) is monkeypatched wholesale in every test here so these
stay pure unit tests of the numbering/dedupe/rendering logic — no real Google News or yfinance
call. `tests/test_data_providers.py` covers the real `GoogleNewsSearchProvider`.
"""

from __future__ import annotations

from src.claude import news_context
from src.data.protocols import NewsItem


def test_news_block_numbers_and_dedupes(monkeypatch):
    dup = NewsItem(id="", title="AMZN wins cloud deal", source="A", published=None, url=None)
    monkeypatch.setattr(news_context, "_fetch", lambda sym, days, limit: [dup, dup])
    block, index = news_context.build_news_block(["AMZN"], per_symbol=5, days=7)
    assert "N1" in block and "N2" not in block and index["N1"].title == "AMZN wins cloud deal"


def test_news_block_empty_when_nothing_found(monkeypatch):
    monkeypatch.setattr(news_context, "_fetch", lambda sym, days, limit: [])
    block, index = news_context.build_news_block(["AMZN"], per_symbol=5, days=7)
    assert block == "" and index == {}


def test_news_block_dedupes_case_and_whitespace_insensitively(monkeypatch):
    a = NewsItem(id="", title="AAPL beats estimates", source="A", published=None, url=None)
    b = NewsItem(id="", title="  aapl   beats  estimates  ", source="B", published=None, url=None)
    monkeypatch.setattr(news_context, "_fetch", lambda sym, days, limit: [a, b])
    block, index = news_context.build_news_block(["AAPL"], per_symbol=5, days=7)
    assert len(index) == 1
    assert index["N1"].source == "A"  # first occurrence wins


def test_news_block_includes_market_query_headlines(monkeypatch):
    def _fake_fetch(sym, days, limit):
        if sym == news_context._MARKET_QUERY:
            return [
                NewsItem(
                    id="", title="Fed holds rates steady", source=None, published=None, url=None
                )
            ]
        return [NewsItem(id="", title=f"{sym} rallies", source=None, published=None, url=None)]

    monkeypatch.setattr(news_context, "_fetch", _fake_fetch)
    block, index = news_context.build_news_block(["AAPL"], per_symbol=5, days=7)
    titles = {item.title for item in index.values()}
    assert "AAPL rallies" in titles
    assert "Fed holds rates steady" in titles


def test_news_block_caps_at_max_items(monkeypatch):
    items = [
        NewsItem(id="", title=f"Headline {i}", source=None, published=None, url=None)
        for i in range(30)
    ]
    monkeypatch.setattr(news_context, "_fetch", lambda sym, days, limit: items)
    block, index = news_context.build_news_block(["AAPL"], per_symbol=30, days=7, max_items=5)
    assert len(index) == 5
    assert "N6" not in block


def test_news_block_truncates_long_titles(monkeypatch):
    long_title = "X" * 300
    item = NewsItem(id="", title=long_title, source=None, published=None, url=None)
    monkeypatch.setattr(news_context, "_fetch", lambda sym, days, limit: [item])
    _block, index = news_context.build_news_block(["AAPL"], per_symbol=5, days=7)
    assert len(index["N1"].title) == 140


def test_news_block_for_candidates_never_raises_on_bad_fetch(monkeypatch):
    from datetime import date

    from src.common.schemas import OptionRight, ScoreCard, Strategy, TradeCandidate

    def _boom(sym, days, limit):
        raise RuntimeError("provider outage")

    monkeypatch.setattr(news_context, "_fetch", _boom)
    candidate = TradeCandidate(
        candidate_id="c-1",
        strategy=Strategy.COVERED_CALL,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date(2026, 7, 17),
        contracts=1,
        premium=1.5,
        collateral=18_000.0,
        roc_pct=0.83,
        annualized_yield_pct=18.5,
        breakeven=183.5,
        dte=48,
        scores=ScoreCard(symbol="AAPL"),
        blended_score=74.5,
    )
    block, index = news_context.news_block_for_candidates(
        [candidate], per_symbol=5, days=7, max_items=25
    )
    assert block == "" and index == {}


# --- final review I2: the NEWS fetch stops when its share of the review deadline runs out ---


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_news_block_stops_fetching_at_the_deadline(monkeypatch):
    """Each fetch takes 10s on a fake clock; with a 25s share only the first three queries
    start (t=0,10,20) — the rest, including the market query, are skipped, and what was
    already fetched is still rendered."""
    clock = _Clock()
    monkeypatch.setattr(news_context.time, "monotonic", clock)
    fetched: list[str] = []

    def _slow_fetch(sym, days, limit):
        fetched.append(sym)
        clock.t += 10.0
        return [NewsItem(id="", title=f"{sym} headline", source=None, published=None, url=None)]

    monkeypatch.setattr(news_context, "_fetch", _slow_fetch)
    block, index = news_context.build_news_block(
        ["A", "B", "C", "D", "E"], per_symbol=5, days=7, deadline=clock.t + 25.0
    )
    assert fetched == ["A", "B", "C"]
    assert news_context._MARKET_QUERY not in fetched
    assert len(index) == 3 and "N3" in block


def test_news_block_without_deadline_fetches_everything(monkeypatch):
    fetched: list[str] = []
    monkeypatch.setattr(news_context, "_fetch", lambda sym, days, limit: fetched.append(sym) or [])
    news_context.build_news_block(["A", "B"], per_symbol=5, days=7)
    assert fetched == ["A", "B", news_context._MARKET_QUERY]


def test_news_block_for_candidates_passes_the_deadline_through(monkeypatch):
    seen: dict = {}

    def _fake_build(symbols, *, per_symbol, days, max_items, deadline=None):
        seen["deadline"] = deadline
        return "", {}

    monkeypatch.setattr(news_context, "build_news_block", _fake_build)
    news_context.news_block_for_candidates([], per_symbol=5, days=7, max_items=25, deadline=42.0)
    assert seen["deadline"] == 42.0


# --- news plan Task 26: a ticker query prefers the news service's deduped store (spec §8) ---


def _store_item(
    url_hash: str, title: str, tickers: list[str], cluster_id: int | None, age_h: float = 1.0
):
    from datetime import UTC, datetime, timedelta

    from src.news.store.models import NewsItemRow
    from src.news.store.queries import naive_utc

    return NewsItemRow(
        url_hash=url_hash,
        title_hash=url_hash,
        title=title,
        url=f"https://r.com/{url_hash}",
        source="Reuters",
        category="ticker",
        origin="google",
        fetched_at=naive_utc(datetime.now(UTC) - timedelta(hours=age_h)),
        tickers=tickers,
        tags=[],
        det_sentiment=0.5,
        cluster_id=cluster_id,
    )


def test_ticker_query_uses_store_first(news_db, monkeypatch) -> None:
    from datetime import UTC, datetime

    from src.news.store.models import NewsItemRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(
            NewsItemRow(
                url_hash="u",
                title_hash="t",
                title="NVDA wins big contract",
                url="https://r.com/a",
                source="Reuters",
                category="ticker",
                origin="google",
                fetched_at=naive_utc(datetime.now(UTC)),
                tickers=["NVDA"],
                tags=[],
                det_sentiment=0.5,
                cluster_id=1,
            )
        )

    def boom():
        raise AssertionError("live provider must not be called when the store has items")

    monkeypatch.setattr("src.data.factory.get_news_search_provider", boom)
    items = news_context._fetch("NVDA", 7, 5)
    assert [i.title for i in items] == ["NVDA wins big contract"]


def test_market_query_still_goes_live(news_db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.data.factory.get_news_search_provider",
        lambda: type(
            "S", (), {"search": lambda self, q, days=7, limit=10: [NewsItem(title="Stocks rally")]}
        )(),
    )
    assert [i.title for i in news_context._fetch("stock market today", 7, 3)] == ["Stocks rally"]


def test_store_returns_one_item_per_cluster_for_that_ticker_only_newest_first(news_db) -> None:
    from datetime import UTC, datetime, timedelta

    from src.news.store.queries import recent_items_for
    from src.news.store.session import news_session

    with news_session() as s:
        s.add_all(
            [
                _store_item("a", "NVDA older syndication", ["NVDA"], 7, age_h=5),
                _store_item("b", "NVDA newest take", ["NVDA"], 7, age_h=1),
                _store_item("c", "AAPL unrelated", ["AAPL"], 8, age_h=0.5),
                _store_item("d", "NVDA second story", ["NVDA", "AMD"], 9, age_h=3),
                _store_item("e", "NVDA too old", ["NVDA"], 10, age_h=24 * 30),
            ]
        )
    with news_session() as s:
        got = recent_items_for(s, "nvda", datetime.now(UTC) - timedelta(days=7), 10)
        capped = recent_items_for(s, "NVDA", datetime.now(UTC) - timedelta(days=7), 1)
    assert [i.title for i in got] == ["NVDA newest take", "NVDA second story"]
    assert [i.title for i in capped] == ["NVDA newest take"]


def test_store_keeps_every_unclustered_item(news_db) -> None:
    """cluster_id is nullable: items not yet clustered are distinct stories, not one."""
    from datetime import UTC, datetime, timedelta

    from src.news.store.queries import recent_items_for
    from src.news.store.session import news_session

    with news_session() as s:
        s.add_all(
            [
                _store_item("a", "NVDA one", ["NVDA"], None, age_h=2),
                _store_item("b", "NVDA two", ["NVDA"], None, age_h=1),
            ]
        )
    with news_session() as s:
        got = recent_items_for(s, "NVDA", datetime.now(UTC) - timedelta(days=7), 10)
    assert [i.title for i in got] == ["NVDA two", "NVDA one"]


def test_ticker_with_no_stored_items_falls_back_to_live(news_db, monkeypatch) -> None:
    class _Search:
        def search(self, q, days=7, limit=10):
            return [NewsItem(title="Live headline")]

    monkeypatch.setattr("src.data.factory.get_news_search_provider", lambda: _Search())
    monkeypatch.setattr(
        "src.data.factory.get_news_provider",
        lambda: type("P", (), {"get_headlines": lambda self, sym, limit=5: []})(),
    )
    assert [i.title for i in news_context._fetch("NVDA", 7, 5)] == ["Live headline"]


def test_store_missing_falls_back_to_live(monkeypatch) -> None:
    """No news.db yet (fresh install, service not started): the live path answers (Review Focus 5)."""

    class _Search:
        def search(self, q, days=7, limit=10):
            return [NewsItem(title="Live headline")]

    monkeypatch.setattr("src.data.factory.get_news_search_provider", lambda: _Search())
    monkeypatch.setattr(
        "src.data.factory.get_news_provider",
        lambda: type("P", (), {"get_headlines": lambda self, sym, limit=5: []})(),
    )
    assert [i.title for i in news_context._fetch("NVDA", 7, 5)] == ["Live headline"]
