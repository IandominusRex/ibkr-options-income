"""Enrichment sections degrade independently and never fail the page."""

from __future__ import annotations

import pytest

from src.research.ingest.materialize import SectionState, materialize
from src.research.store.models import SymbolRow
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc."))
    # Serve fundamentals from the cache so the cold path doesn't hit SEC in tests.
    monkeypatch.setattr(
        "src.research.ingest.materialize.load_cached_financials",
        lambda sym: None,
    )
    monkeypatch.setattr(
        "src.research.ingest.materialize.ingest_fundamentals",
        lambda sym, cik: None,
    )


def test_a_sentiment_outage_does_not_break_technicals(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.materialize._technicals",
        lambda symbol: {"rsi_14": 55.0},
    )

    def boom(symbol: str):
        raise RuntimeError("StockTwits down")

    monkeypatch.setattr("src.research.ingest.materialize._sentiment", boom)
    monkeypatch.setattr(
        "src.research.ingest.materialize._news",
        lambda symbol: [{"title": "x"}],
    )

    result = materialize("AAPL")
    assert result.technicals_state is SectionState.READY
    assert result.sentiment_state is SectionState.UNAVAILABLE
    assert "StockTwits down" in (result.sentiment_reason or "")


def test_sentiment_is_never_an_input_to_the_deterministic_sections(db) -> None:
    """Structural guard: materialize must not pass sentiment into technicals or fundamentals."""
    import inspect

    from src.research.ingest import materialize as mod

    source = inspect.getsource(mod.materialize)
    sentiment_line = next((line for line in source.splitlines() if "_sentiment(" in line), "")
    assert "technical" not in sentiment_line.lower()
    assert "fundamental" not in sentiment_line.lower()


def test_a_news_outage_leaves_technicals_and_sentiment_rendering(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.materialize._technicals",
        lambda symbol: {"rsi_14": 55.0},
    )
    monkeypatch.setattr(
        "src.research.ingest.materialize._sentiment",
        lambda symbol: {"overall": 60.0},
    )

    def boom(symbol: str):
        raise RuntimeError("yfinance news down")

    monkeypatch.setattr("src.research.ingest.materialize._news", boom)

    result = materialize("AAPL")
    assert result.technicals_state is SectionState.READY
    assert result.sentiment_state is SectionState.READY
    assert result.news_state is SectionState.UNAVAILABLE
    assert "yfinance news down" in (result.news_reason or "")


def test_a_technicals_outage_leaves_sentiment_rendering(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.materialize._technicals",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("yfinance history down")),
    )
    monkeypatch.setattr(
        "src.research.ingest.materialize._sentiment",
        lambda symbol: {"overall": 60.0},
    )
    monkeypatch.setattr(
        "src.research.ingest.materialize._news",
        lambda symbol: [],
    )

    result = materialize("AAPL")
    assert result.technicals_state is SectionState.UNAVAILABLE
    assert result.sentiment_state is SectionState.READY


def test_no_filer_means_no_enrichment_runs(monkeypatch, tmp_path) -> None:
    """A symbol with no directory row returns fundamentals UNAVAILABLE and no sections."""
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()

    called: list[str] = []
    monkeypatch.setattr(
        "src.research.ingest.materialize._technicals",
        lambda symbol: called.append("tech") or {"rsi_14": 1.0},
    )
    monkeypatch.setattr(
        "src.research.ingest.materialize._sentiment",
        lambda symbol: called.append("sent") or {"overall": 50.0},
    )

    result = materialize("NOPE")
    assert result.fundamentals_state is SectionState.UNAVAILABLE
    assert called == []  # no enrichment on a 404-equivalent
