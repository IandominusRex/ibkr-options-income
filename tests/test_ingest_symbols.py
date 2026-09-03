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
