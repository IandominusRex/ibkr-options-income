"""Health, identity, and the nav manifest that drives the left rail."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app

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
    from src.research.store.session import init_research_db

    init_research_db()
    return TestClient(create_app())


def test_health_needs_no_auth(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in {"ok", "degraded"}
    assert "as_of" in r.json()


def test_me_requires_auth(client) -> None:
    assert client.get("/me").status_code == 401


def test_me_returns_the_owner(client) -> None:
    r = client.get("/me", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["id"] == "owner"
    assert r.json()["role"] == "owner"


def test_nav_lists_every_section_with_availability(client) -> None:
    r = client.get("/nav", headers=AUTH)
    assert r.status_code == 200
    sections = {s["key"]: s for s in r.json()["sections"]}
    assert set(sections) == {"research", "options", "portfolio", "pnl", "universe"}
    assert sections["research"]["available"] is True
    # P2 M2 ships the options console read surfaces — the rail is now available.
    assert sections["options"]["available"] is True
    assert sections["options"]["note"] is None
    # P3 M3 ships the portfolio console read surfaces — the rail is now available.
    assert sections["portfolio"]["available"] is True
    assert sections["portfolio"]["note"] is None
    # P4 still renders a placeholder.
    assert sections["pnl"]["available"] is False
    assert sections["pnl"]["note"]


def test_unknown_route_returns_json_not_html(client) -> None:
    r = client.get("/nope", headers=AUTH)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_an_open_breaker_makes_health_report_degraded(client) -> None:
    """A provider with an open circuit degrades /health, not just the section it serves."""
    from src.data.breaker import get_breaker

    # Clear any prior state by recording enough failures to open the edgar breaker.
    edgar = get_breaker("edgar", threshold=3, cooldown_seconds=300.0)
    edgar.record_success()  # reset
    for _ in range(3):
        edgar.record_failure()
    assert edgar.state == "open"

    r = client.get("/health")
    body = r.json()
    assert body["status"] == "degraded"
    assert body["providers"]["edgar"] == "open"

    # Clean up so other tests don't see an open circuit.
    edgar.record_success()
