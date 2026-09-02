"""The research database is a separate schema with its own Base."""

from __future__ import annotations

import sqlalchemy as sa

from src.research.store import models as research_models
from src.research.store.session import init_research_db, research_session
from src.storage import models as trading_models


def test_research_base_is_not_the_trading_base() -> None:
    """A shared Base would let create_all() build either schema against either engine."""
    assert research_models.Base is not trading_models.Base


def test_init_creates_every_table(tmp_path, monkeypatch) -> None:
    db = tmp_path / "research.db"
    monkeypatch.setattr(
        "src.research.store.session._resolve_url", lambda: f"sqlite:///{db.as_posix()}"
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()

    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    names = set(sa.inspect(engine).get_table_names())
    assert {
        "symbols",
        "company_facts_raw",
        "financials",
        "daily_bars",
        "quotes",
        "news_items",
        "analysis_cache",
        "check_results",
        "summaries",
        "watchlists",
        "watchlist_items",
        "recently_viewed",
        "ingest_jobs",
    } <= names


def test_symbol_roundtrip(tmp_path, monkeypatch) -> None:
    db = tmp_path / "research.db"
    monkeypatch.setattr(
        "src.research.store.session._resolve_url", lambda: f"sqlite:///{db.as_posix()}"
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()

    with research_session() as s:
        s.add(research_models.SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc."))
    with research_session() as s:
        row = s.get(research_models.SymbolRow, "AAPL")
        assert row is not None
        assert row.cik == "0000320193"
        assert row.is_etf is False
