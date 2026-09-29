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
