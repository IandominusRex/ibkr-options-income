"""The research database is a separate schema with its own Base."""

from __future__ import annotations

from datetime import date

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


def test_init_backfills_a_column_a_later_milestone_added(tmp_path, monkeypatch) -> None:
    """create_all() never alters an existing table.

    A `data/research.db` left over from an earlier milestone keeps the old `financials`
    schema forever unless init_research_db() actively backfills new columns — otherwise
    every query touching `financials.form` (added in M3) raises OperationalError against
    a database that predates it. Simulate that by creating the table by hand without the
    column, the way M2's schema actually shipped it.
    """
    db = tmp_path / "research.db"
    monkeypatch.setattr(
        "src.research.store.session._resolve_url", lambda: f"sqlite:///{db.as_posix()}"
    )
    monkeypatch.setattr("src.research.store.session._engine", None)

    pre_m3_engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    with pre_m3_engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE financials (
                id INTEGER NOT NULL PRIMARY KEY,
                symbol VARCHAR(16) NOT NULL,
                period_end DATE NOT NULL,
                period_type VARCHAR(8) NOT NULL,
                line_item VARCHAR(64) NOT NULL,
                value FLOAT,
                concept VARCHAR(128),
                accn VARCHAR(32),
                filed DATE
            )
            """
        )
    pre_m3_engine.dispose()

    init_research_db()

    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    columns = {row[1] for row in engine.connect().exec_driver_sql("PRAGMA table_info(financials)")}
    assert "form" in columns

    with research_session() as s:
        s.add(
            research_models.FinancialRow(
                symbol="AAPL",
                period_end=date(2024, 9, 28),
                period_type="annual",
                line_item="revenue",
                value=1.0,
                form="10-K",
            )
        )
    with research_session() as s:
        row = s.query(research_models.FinancialRow).filter_by(symbol="AAPL").one()
        assert row.form == "10-K"


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
