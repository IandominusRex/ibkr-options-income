"""Symbol search: ranking, limits, and input handling."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.research.store.models import SymbolRow
from src.research.store.session import init_research_db, research_session

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session() as s:
        s.add_all(
            [
                SymbolRow(symbol="AA", cik="1", name="Alcoa Corp"),
                SymbolRow(symbol="AAPL", cik="2", name="Apple Inc."),
                SymbolRow(symbol="AAP", cik="3", name="Advance Auto Parts"),
                SymbolRow(symbol="MSFT", cik="4", name="Microsoft Corp"),
                SymbolRow(symbol="SPY", cik="5", name="SPDR S&P 500 ETF", is_etf=True),
            ]
        )
    return TestClient(create_app())


def test_search_requires_auth(client) -> None:
    assert client.get("/research/search?q=AAPL").status_code == 401


def test_exact_ticker_match_ranks_first(client) -> None:
    r = client.get("/research/search?q=AAP", headers=AUTH)
    assert r.status_code == 200
    symbols = [h["symbol"] for h in r.json()["results"]]
    assert symbols[0] == "AAP"  # exact
    assert "AAPL" in symbols  # prefix


def test_name_substring_matches(client) -> None:
    r = client.get("/research/search?q=microsoft", headers=AUTH)
    symbols = [h["symbol"] for h in r.json()["results"]]
    assert symbols == ["MSFT"]


def test_search_is_case_insensitive(client) -> None:
    r = client.get("/research/search?q=aapl", headers=AUTH)
    assert r.json()["results"][0]["symbol"] == "AAPL"


def test_etf_flag_is_returned(client) -> None:
    r = client.get("/research/search?q=SPY", headers=AUTH)
    assert r.json()["results"][0]["is_etf"] is True


def test_blank_query_returns_no_results_not_the_whole_table(client) -> None:
    r = client.get("/research/search?q=", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["results"] == []


def test_limit_is_capped(client) -> None:
    r = client.get("/research/search?q=A&limit=999", headers=AUTH)
    assert r.status_code == 422
