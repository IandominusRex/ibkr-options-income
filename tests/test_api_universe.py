"""GET /universe — the effective scan universe, reshaped for per-list override metadata
(M7 Task 7.4).

``lists`` carries exactly four entries in file order (indexes, watchlist, would_own,
actively_wheeling), each with its own ``overridable`` flag and an ``entries`` array
carrying provenance (``overridden``, ``removed``, ``created_by``, ``created_at``) for
``would_own``/``watchlist``. ``editable`` is ``true`` — Task 7.4 is the write path this
route's shape describes. The route requires auth.
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


def _list(body: dict, name: str) -> dict:
    return next(lst for lst in body["lists"] if lst["name"] == name)


def _symbols(lst: dict) -> list[str]:
    return [e["symbol"] for e in lst["entries"]]


def test_requires_auth(client) -> None:
    assert client.get("/universe").status_code == 401


def test_returns_every_list_unmodified_in_file_order(client) -> None:
    r = client.get("/universe", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    u = _universe()
    assert _symbols(_list(body, "indexes")) == list(u["indexes"])
    assert _symbols(_list(body, "watchlist")) == list(u["watchlist"])
    assert _symbols(_list(body, "would_own")) == list(u["would_own"])
    assert _symbols(_list(body, "actively_wheeling")) == list(u["actively_wheeling"])
    # file order is preserved — the first index in universe.yaml is SPY.
    assert _symbols(_list(body, "indexes"))[0] == "SPY"


def test_the_four_lists_appear_in_the_documented_order(client) -> None:
    body = client.get("/universe", headers=AUTH).json()
    names = [lst["name"] for lst in body["lists"]]
    assert names == ["indexes", "watchlist", "would_own", "actively_wheeling"]


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


def test_editable_is_true(client) -> None:
    """Task 7.4 is the write path this route's shape now describes."""
    assert client.get("/universe", headers=AUTH).json()["editable"] is True


def test_would_own_and_watchlist_are_overridable_and_nothing_else_is(client) -> None:
    body = client.get("/universe", headers=AUTH).json()
    overridable = {lst["name"] for lst in body["lists"] if lst["overridable"]}
    assert overridable == {"would_own", "watchlist"}


def test_unoverridden_entries_carry_no_provenance(client) -> None:
    """A base symbol with no override row is overridden=False, removed=False, with null
    created_by/created_at."""
    body = client.get("/universe", headers=AUTH).json()
    would_own = _list(body, "would_own")
    entry = next(e for e in would_own["entries"] if e["symbol"] == "AAPL")
    assert entry["overridden"] is False
    assert entry["removed"] is False
    assert entry["created_by"] is None
    assert entry["created_at"] is None


def test_actively_wheeling_is_subset_of_would_own(client) -> None:
    """Documented invariant: every actively_wheeling name is in would_own."""
    body = client.get("/universe", headers=AUTH).json()
    would_own = set(_symbols(_list(body, "would_own")))
    for s in _symbols(_list(body, "actively_wheeling")):
        assert s in would_own, f"{s} is actively_wheeling but not in would_own"
