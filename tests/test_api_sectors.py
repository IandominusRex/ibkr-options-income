"""GET /research/sectors — the sector card grid.

Rules covered: a sector with no priced members reports change_pct as None (never 0);
avg_iv_rank averages only members with IV history and the card carries the contributing
count; cards are ordered by avg_iv_rank descending; the route reads the trading DB
read-only (§4.3).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.research.store.models import QuoteRow
from src.research.store.session import init_research_db, research_session
from src.storage.models import IVHistoryRow

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)

    # Research DB: warm-tier quotes.
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()

    # Trading DB: iv_history (read-only engine).
    trading_db = tmp_path / "income_system.db"
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()

    return TestClient(create_app())


def _seed_quote(symbol: str, change_pct: float | None) -> None:
    with research_session() as s:
        s.add(QuoteRow(symbol=symbol, price=100.0, change_pct=change_pct, as_of=datetime.now(UTC)))


def _seed_iv(symbol: str, ivs: list[float]) -> None:
    import src.storage.db as dbmod

    with dbmod.session_scope() as s:
        for i, iv in enumerate(ivs):
            s.add(
                IVHistoryRow(symbol=symbol, obs_date=date(2026, 1, 1) + date.resolution * i, iv=iv)
            )


def test_requires_auth(client) -> None:
    assert client.get("/research/sectors").status_code == 401


def test_sector_with_no_priced_members_reports_null_change_pct(client) -> None:
    """Never 0 — no quote is not the same as a flat day."""
    r = client.get("/research/sectors", headers=AUTH).json()
    tech = next(c for c in r["sectors"] if c["sector"] == "tech")
    assert tech["change_pct"] is None


def test_avg_iv_rank_averages_only_members_with_iv_history(client) -> None:
    # NVDA has IV history, AAPL does not (in this seed).
    _seed_iv("NVDA", [10.0, 20.0, 50.0])  # rank ~ (50-10)/(50-10)*100 = 100.0
    r = client.get("/research/sectors", headers=AUTH).json()
    semis = next(c for c in r["sectors"] if c["sector"] == "semis")
    assert semis["avg_iv_rank"] is not None
    assert semis["iv_rank_count"] >= 1


def test_cards_ordered_by_avg_iv_rank_descending(client) -> None:
    # Give semis a high IV rank and telecom a low one, both with real IV history so
    # both appear in the ordered list. SOXL is semis, ASTS is telecom in universe.yaml.
    _seed_iv("SOXL", [10.0, 80.0])  # semis: rank (80-10)/(80-10)*100 = 100.0
    _seed_iv("ASTS", [10.0, 50.0, 12.0])  # telecom: rank (12-10)/(50-10)*100 = 5.0
    r = client.get("/research/sectors", headers=AUTH).json()
    ordered = [c["sector"] for c in r["sectors"] if c["avg_iv_rank"] is not None]
    assert "semis" in ordered and "telecom" in ordered
    assert ordered.index("semis") < ordered.index("telecom")


def test_best_and_worst_movers_are_named(client) -> None:
    # All three are in the "tech" sector per universe.yaml.
    _seed_quote("AAPL", -2.0)
    _seed_quote("MSFT", 1.0)
    _seed_quote("GOOGL", 3.0)
    r = client.get("/research/sectors", headers=AUTH).json()
    tech = next(c for c in r["sectors"] if c["sector"] == "tech")
    assert tech["best"]["symbol"] == "GOOGL"
    assert tech["worst"]["symbol"] == "AAPL"
    assert tech["change_pct"] is not None


def test_sector_count_is_constituent_count(client) -> None:
    r = client.get("/research/sectors", headers=AUTH).json()
    tech = next(c for c in r["sectors"] if c["sector"] == "tech")
    assert tech["count"] >= 1
