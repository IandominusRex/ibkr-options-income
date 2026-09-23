"""Directory ingest upserts, preserves enrichment, and never truncates on a failed fetch."""

from __future__ import annotations

import pytest

from src.data.protocols import SymbolRecord
from src.research.ingest.symbols import refresh_symbol_directory
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


class _Stub:
    def __init__(self, rows: list[SymbolRecord]) -> None:
        self._rows = rows

    def list_symbols(self) -> list[SymbolRecord]:
        return self._rows


def test_writes_every_symbol(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.symbols.get_symbol_directory_provider",
        lambda: _Stub(
            [
                SymbolRecord(symbol="AAPL", cik="0000320193", name="Apple Inc.", exchange="Nasdaq"),
                SymbolRecord(symbol="MSFT", cik="0000789019", name="MICROSOFT CORP"),
            ]
        ),
    )
    assert refresh_symbol_directory() == 2
    with research_session() as s:
        assert s.get(SymbolRow, "AAPL").name == "Apple Inc."


def test_upsert_preserves_locally_enriched_columns(db, monkeypatch) -> None:
    """sector/industry/is_etf are filled in later by other jobs; a refresh must not wipe them."""
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="old", sector="tech", is_etf=False))

    monkeypatch.setattr(
        "src.research.ingest.symbols.get_symbol_directory_provider",
        lambda: _Stub([SymbolRecord(symbol="AAPL", cik="0000320193", name="Apple Inc.")]),
    )
    refresh_symbol_directory()

    with research_session() as s:
        row = s.get(SymbolRow, "AAPL")
        assert row.name == "Apple Inc."  # refreshed
        assert row.sector == "tech"  # preserved


def test_empty_fetch_leaves_existing_rows_alone(db, monkeypatch) -> None:
    """A failed SEC fetch must never empty the directory that search depends on."""
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc."))

    monkeypatch.setattr(
        "src.research.ingest.symbols.get_symbol_directory_provider", lambda: _Stub([])
    )
    assert refresh_symbol_directory() == 0

    with research_session() as s:
        assert s.get(SymbolRow, "AAPL") is not None


def test_overrides_seed_symbols_the_provider_never_returns(db, monkeypatch) -> None:
    """TQQQ/SOXL/UPRO aren't in EDGAR's directory at all; the override file fills them in."""
    monkeypatch.setattr(
        "src.research.ingest.symbols.get_symbol_directory_provider",
        lambda: _Stub([SymbolRecord(symbol="AAPL", cik="0000320193", name="Apple Inc.")]),
    )
    refresh_symbol_directory()

    with research_session() as s:
        row = s.get(SymbolRow, "TQQQ")
        assert row is not None
        assert row.cik is None  # no standalone SEC filer to give it
        assert row.is_etf is True


def test_overrides_still_seed_when_the_provider_fetch_fails(db, monkeypatch) -> None:
    """Overrides are static local data — an EDGAR outage must not hide them either."""
    monkeypatch.setattr(
        "src.research.ingest.symbols.get_symbol_directory_provider", lambda: _Stub([])
    )
    refresh_symbol_directory()

    with research_session() as s:
        assert s.get(SymbolRow, "SOXL") is not None


def test_overrides_never_overwrite_an_existing_row(db, monkeypatch) -> None:
    """If EDGAR (or a prior run) already covers a symbol, the override must not touch it."""
    with research_session() as s:
        s.add(SymbolRow(symbol="TQQQ", cik="0001234567", name="real filer", is_etf=False))

    monkeypatch.setattr(
        "src.research.ingest.symbols.get_symbol_directory_provider", lambda: _Stub([])
    )
    refresh_symbol_directory()

    with research_session() as s:
        row = s.get(SymbolRow, "TQQQ")
        assert row.cik == "0001234567"
        assert row.name == "real filer"
        assert row.is_etf is False
