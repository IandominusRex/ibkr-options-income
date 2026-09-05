"""Watchlist routes: user-scoped items, idempotent add/remove, unknown-symbol 404.

The multi-user seam is proven: a second user's items are not returned. Adding a symbol
promotes it to the warm tier (warm_symbols reads WatchlistItemRow). Adding an unknown
symbol returns 404 rather than creating a row that can never resolve.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.research.store.models import SymbolRow
from src.research.store.session import init_research_db, research_session

TOKEN_OWNER = "owner-token"
TOKEN_VIEWER = "viewer-token"
AUTH_OWNER = {"Authorization": f"Bearer {TOKEN_OWNER}"}
AUTH_VIEWER = {"Authorization": f"Bearer {TOKEN_VIEWER}"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN_OWNER)
    # Allow either token: owner and viewer resolve to distinct users so the multi-user
    # seam is testable. Patched at the deps import site (where current_user calls it).
    from src.api.auth import Role, User

    def fake_auth(token: str | None):
        if token == TOKEN_OWNER:
            return User(id="owner", role=Role.OWNER)
        if token == TOKEN_VIEWER:
            return User(id="viewer", role=Role.VIEWER)
        return None

    monkeypatch.setattr("src.api.deps.authenticate", fake_auth)
    monkeypatch.setattr("src.api.auth.authenticate", fake_auth)

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()

    # Trading DB (read-only) for iv_history lookups.
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

    with research_session() as s:
        s.add_all(
            [
                SymbolRow(symbol="NVDA", cik="1", name="NVIDIA Corp"),
                SymbolRow(symbol="AAPL", cik="2", name="Apple Inc."),
            ]
        )

    return TestClient(create_app())


def test_get_requires_auth(client) -> None:
    assert client.get("/watchlist").status_code == 401


def test_add_returns_201_first_time(client) -> None:
    r = client.post("/watchlist/NVDA", headers=AUTH_OWNER)
    assert r.status_code == 201
    assert r.json()["added"] is True


def test_add_is_idempotent_repeat_is_200(client) -> None:
    assert client.post("/watchlist/NVDA", headers=AUTH_OWNER).status_code == 201
    r = client.post("/watchlist/NVDA", headers=AUTH_OWNER)
    assert r.status_code == 200
    assert r.json()["added"] is False


def test_add_unknown_symbol_returns_404(client) -> None:
    assert client.post("/watchlist/ZZZZ", headers=AUTH_OWNER).status_code == 404


def test_add_then_list_contains_the_symbol(client) -> None:
    client.post("/watchlist/NVDA", headers=AUTH_OWNER)
    items = client.get("/watchlist", headers=AUTH_OWNER).json()["items"]
    assert [i["symbol"] for i in items] == ["NVDA"]
    assert items[0]["name"] == "NVIDIA Corp"


def test_delete_is_idempotent(client) -> None:
    client.post("/watchlist/NVDA", headers=AUTH_OWNER)
    assert client.delete("/watchlist/NVDA", headers=AUTH_OWNER).status_code == 204
    # Repeat delete is still 204.
    assert client.delete("/watchlist/NVDA", headers=AUTH_OWNER).status_code == 204
    assert client.get("/watchlist", headers=AUTH_OWNER).json()["items"] == []


def test_second_users_items_are_not_returned(client) -> None:
    """The multi-user seam: viewer cannot see owner's items."""
    client.post("/watchlist/NVDA", headers=AUTH_OWNER)
    viewer_items = client.get("/watchlist", headers=AUTH_VIEWER).json()["items"]
    assert viewer_items == []


def test_add_promotes_to_warm_tier(client) -> None:
    """warm_symbols() reads WatchlistItemRow; an added symbol appears immediately."""
    from src.research.ingest.quotes import warm_symbols

    client.post("/watchlist/NVDA", headers=AUTH_OWNER)
    assert "NVDA" in warm_symbols()


def test_add_second_symbol_orders_newest_first(client) -> None:
    client.post("/watchlist/NVDA", headers=AUTH_OWNER)
    client.post("/watchlist/AAPL", headers=AUTH_OWNER)
    syms = [i["symbol"] for i in client.get("/watchlist", headers=AUTH_OWNER).json()["items"]]
    assert syms == ["AAPL", "NVDA"]


def test_next_earnings_is_sourced_from_the_fundamentals_cache(client) -> None:
    """next_earnings reads from FundamentalCacheRow in the trading DB, not a hardcoded None."""
    from datetime import date

    import src.storage.db as dbmod
    from src.storage.models import FundamentalCacheRow

    client.post("/watchlist/NVDA", headers=AUTH_OWNER)
    with dbmod.session_scope() as s:
        s.add(
            FundamentalCacheRow(
                symbol="NVDA",
                data_json="{}",
                next_earnings_date=date(2026, 12, 15),
            )
        )
    items = client.get("/watchlist", headers=AUTH_OWNER).json()["items"]
    nvda = next(i for i in items if i["symbol"] == "NVDA")
    assert nvda["next_earnings"] == "2026-12-15"
