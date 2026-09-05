"""GET /universe — the effective scan universe, read-only in P1.

Every list is returned unmodified and in file order; ``editable`` is ``false`` so the
client never renders an edit affordance that has no write path behind it (§4.5). The
route requires auth.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.common.config import get_config

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)
    return TestClient(create_app())


def _universe() -> dict[str, object]:
    return get_config().universe


def test_requires_auth(client) -> None:
    assert client.get("/universe").status_code == 401


def test_returns_every_list_unmodified_in_file_order(client) -> None:
    r = client.get("/universe", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    u = _universe()
    assert body["indexes"] == list(u["indexes"])
    assert body["watchlist"] == list(u["watchlist"])
    assert body["would_own"] == list(u["would_own"])
    assert body["actively_wheeling"] == list(u["actively_wheeling"])
    # file order is preserved — the first index in universe.yaml is SPY.
    assert body["indexes"][0] == "SPY"


def test_sectors_map_is_returned(client) -> None:
    body = client.get("/universe", headers=AUTH).json()
    u = _universe()
    assert body["sectors"] == {str(k): str(v) for k, v in (u["sectors"] or {}).items()}
    assert body["sectors"]["NVDA"] == "semis"


def test_strike_bands_are_returned(client) -> None:
    body = client.get("/universe", headers=AUTH).json()
    u = _universe()
    assert body["strike_bands"] == {str(k): float(v) for k, v in (u["strike_bands"] or {}).items()}
    assert body["strike_bands"]["SOXL"] == 0.45


def test_editable_is_false(client) -> None:
    """The client cannot render an edit affordance that has no write path (§4.5)."""
    assert client.get("/universe", headers=AUTH).json()["editable"] is False


def test_actively_wheeling_is_subset_of_would_own(client) -> None:
    """Documented invariant: every actively_wheeling name is in would_own."""
    body = client.get("/universe", headers=AUTH).json()
    would_own = set(body["would_own"])
    for s in body["actively_wheeling"]:
        assert s in would_own, f"{s} is actively_wheeling but not in would_own"
