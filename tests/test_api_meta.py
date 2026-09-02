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
    # P2-P4 render a placeholder rather than being hidden, so the shape is visible.
    assert sections["options"]["available"] is False
    assert sections["options"]["note"]


def test_unknown_route_returns_json_not_html(client) -> None:
    r = client.get("/nope", headers=AUTH)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
