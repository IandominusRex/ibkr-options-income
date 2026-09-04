"""Warm-tier quote refresh covers watchlisted and recently viewed symbols, and only those."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.research.ingest.quotes import refresh_quotes, warm_symbols
from src.research.store.models import (
    QuoteRow,
    RecentlyViewedRow,
    WatchlistItemRow,
    WatchlistRow,
)
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def test_warm_set_is_empty_by_default(db) -> None:
    assert warm_symbols() == []


def test_watchlisted_symbols_are_warm(db) -> None:
    with research_session() as s:
        s.add(WatchlistRow(id=1, user_id="owner", name="Default"))
        s.flush()  # parent must land before the FK child (no relationship() declared)
        s.add(WatchlistItemRow(watchlist_id=1, symbol="NVDA", added_at=datetime.now(UTC)))
    assert warm_symbols() == ["NVDA"]


def test_recently_viewed_symbols_are_warm(db) -> None:
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="META", viewed_at=datetime.now(UTC)))
    assert warm_symbols() == ["META"]


def test_stale_views_fall_out_of_the_warm_set(db) -> None:
    with research_session() as s:
        s.add(
            RecentlyViewedRow(
                user_id="owner",
                symbol="OLD",
                viewed_at=datetime.now(UTC) - timedelta(days=30),
            )
        )
    assert warm_symbols() == []


def test_refresh_writes_a_quote(db, monkeypatch) -> None:
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="AAPL", viewed_at=datetime.now(UTC)))
    monkeypatch.setattr("src.research.ingest.quotes.is_rth", lambda: True)
    monkeypatch.setattr(
        "src.research.ingest.quotes.get_price_provider",
        lambda: type("P", (), {"get_last_price": staticmethod(lambda sym: 221.4)})(),
    )
    assert refresh_quotes() == 1
    with research_session() as s:
        assert s.get(QuoteRow, "AAPL").price == 221.4


def test_a_missing_quote_does_not_write_a_row(db, monkeypatch) -> None:
    """No quote is not the same as a price of zero."""
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="AAPL", viewed_at=datetime.now(UTC)))
    monkeypatch.setattr("src.research.ingest.quotes.is_rth", lambda: True)
    monkeypatch.setattr(
        "src.research.ingest.quotes.get_price_provider",
        lambda: type("P", (), {"get_last_price": staticmethod(lambda sym: None)})(),
    )
    assert refresh_quotes() == 0
    with research_session() as s:
        assert s.get(QuoteRow, "AAPL") is None


def test_refresh_is_a_noop_outside_rth(db, monkeypatch) -> None:
    """The RTH guard means a manual call outside market hours writes nothing."""
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="AAPL", viewed_at=datetime.now(UTC)))
    monkeypatch.setattr("src.research.ingest.quotes.is_rth", lambda: False)
    monkeypatch.setattr(
        "src.research.ingest.quotes.get_price_provider",
        lambda: type("P", (), {"get_last_price": staticmethod(lambda sym: 221.4)})(),
    )
    assert refresh_quotes() == 0
