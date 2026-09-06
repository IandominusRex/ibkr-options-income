"""POST /commands and GET /commands/{id} — the first write routes.

Owner-only, dedupe returns the existing row, live-mode intents get a confirm_token,
and reads go through the read-only engine.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)

    trading_db = tmp_path / "income_system.db"
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())
    monkeypatch.setattr("src.api.trading_db._cmd_engine", None)
    monkeypatch.setattr("src.api.trading_db._cmd_session_factory", None)

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()
    return TestClient(create_app())


def test_post_commands_requires_owner_auth(client) -> None:
    """A missing token gets 401, not a command row."""
    r = client.post("/commands", json={"kind": "refresh", "payload": {}})
    assert r.status_code == 401


def test_post_commands_requires_owner_role(client, monkeypatch) -> None:
    """A viewer token gets 403 — the first use of require_owner."""
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr(
        "src.api.deps.authenticate",
        lambda token: viewer if token else None,
    )
    r = client.post("/commands", json={"kind": "refresh", "payload": {}}, headers=AUTH)
    assert r.status_code == 403


def test_post_refresh_creates_a_command(client) -> None:
    r = client.post("/commands", json={"kind": "refresh", "payload": {}}, headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    assert body["created"] is True
    assert body["kind"] == "refresh"
    assert body["status"] == "pending"
    assert body["id"] > 0


def test_a_duplicate_post_returns_the_existing_id(client) -> None:
    r1 = client.post(
        "/commands",
        json={"kind": "approve", "payload": {"approval_id": 42}},
        headers=AUTH,
    )
    assert r1.status_code == 201
    r2 = client.post(
        "/commands",
        json={"kind": "approve", "payload": {"approval_id": 42}},
        headers=AUTH,
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == r1.json()["id"]
    assert r2.json()["created"] is False


def test_get_commands_returns_the_status(client) -> None:
    r = client.post("/commands", json={"kind": "refresh", "payload": {}}, headers=AUTH)
    cid = r.json()["id"]
    got = client.get(f"/commands/{cid}", headers=AUTH)
    assert got.status_code == 200
    assert got.json()["id"] == cid
    assert got.json()["status"] == "pending"


def test_get_commands_unknown_id_is_404(client) -> None:
    r = client.get("/commands/99999", headers=AUTH)
    assert r.status_code == 404


def test_get_commands_requires_owner_auth(client) -> None:
    r = client.get("/commands/1")
    assert r.status_code == 401


def test_post_approve_in_paper_mode_has_no_confirm_token(client) -> None:
    r = client.post(
        "/commands",
        json={"kind": "approve", "payload": {"approval_id": 42}},
        headers=AUTH,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["needs_confirmation"] is False


def test_post_approve_in_live_mode_needs_confirmation(client, monkeypatch) -> None:
    """In live mode, order-reaching intents get a confirm_token and needs_confirmation."""
    monkeypatch.setattr("src.api.routers.commands.get_config", lambda: _live_config())
    r = client.post(
        "/commands",
        json={"kind": "approve", "payload": {"approval_id": 99}},
        headers=AUTH,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["needs_confirmation"] is True


def test_post_refresh_in_live_mode_does_not_need_confirmation(client, monkeypatch) -> None:
    """refresh is not an order-reaching intent, so it never needs confirmation."""
    monkeypatch.setattr("src.api.routers.commands.get_config", lambda: _live_config())
    r = client.post("/commands", json={"kind": "refresh", "payload": {}}, headers=AUTH)
    assert r.status_code == 201
    assert r.json()["needs_confirmation"] is False


def test_post_promote_in_live_mode_needs_confirmation(client, monkeypatch) -> None:
    monkeypatch.setattr("src.api.routers.commands.get_config", lambda: _live_config())
    r = client.post(
        "/commands",
        json={
            "kind": "promote",
            "payload": {
                "candidate_id": "abc",
                "symbol": "NVDA",
                "strategy": "covered_call",
                "strike": 105.0,
                "expiry": "2026-10-16",
            },
        },
        headers=AUTH,
    )
    assert r.status_code == 201
    assert r.json()["needs_confirmation"] is True


def test_post_roll_request_in_live_mode_needs_confirmation(client, monkeypatch) -> None:
    monkeypatch.setattr("src.api.routers.commands.get_config", lambda: _live_config())
    r = client.post(
        "/commands",
        json={"kind": "roll_request", "payload": {"position_symbol": "NVDA"}},
        headers=AUTH,
    )
    assert r.status_code == 201
    assert r.json()["needs_confirmation"] is True


def test_post_invalid_payload_returns_422(client) -> None:
    r = client.post(
        "/commands",
        json={"kind": "approve", "payload": {"not_approval_id": 7}},
        headers=AUTH,
    )
    assert r.status_code == 422


def test_post_confirm_on_a_paper_command_is_409(client) -> None:
    """In paper mode there is no token, so the command is not awaiting confirmation —
    the M3 contract makes that a 409 rather than a silent 204."""
    r = client.post(
        "/commands",
        json={"kind": "approve", "payload": {"approval_id": 42}},
        headers=AUTH,
    )
    cid = r.json()["id"]
    got = client.post(f"/commands/{cid}/confirm", json={"confirm_token": ""}, headers=AUTH)
    assert got.status_code == 409


def test_post_confirm_in_live_mode_clears_the_token(client, monkeypatch) -> None:
    """A successful confirm clears the confirm_token so the drain will process the command.

    The clear-write goes through src/api/commands.py (the only module allowed to hold
    the write handle) — the router must not import command_session.
    """
    monkeypatch.setattr("src.api.routers.commands.get_config", lambda: _live_config())
    r = client.post(
        "/commands",
        json={"kind": "approve", "payload": {"approval_id": 77}},
        headers=AUTH,
    )
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["needs_confirmation"] is True

    # Read the token back through the read-only engine to supply it.
    from src.api.trading_db import trading_session
    from src.storage.models import AppCommandRow

    with trading_session() as s:
        row = s.get(AppCommandRow, cid)
        assert row is not None and row.confirm_token is not None
        token = row.confirm_token

    got = client.post(f"/commands/{cid}/confirm", json={"confirm_token": token}, headers=AUTH)
    assert got.status_code == 204

    # The token is now cleared — needs_confirmation must be False.
    status = client.get(f"/commands/{cid}", headers=AUTH).json()
    assert status["needs_confirmation"] is False


def test_post_confirm_with_a_wrong_token_returns_403(client, monkeypatch) -> None:
    """M3 Task 3.5: a wrong token is 403 (not 409) and does not clear the field."""
    monkeypatch.setattr("src.api.routers.commands.get_config", lambda: _live_config())
    r = client.post(
        "/commands",
        json={"kind": "approve", "payload": {"approval_id": 88}},
        headers=AUTH,
    )
    cid = r.json()["id"]
    got = client.post(
        f"/commands/{cid}/confirm",
        json={"confirm_token": "wrong-token"},
        headers=AUTH,
    )
    assert got.status_code == 403
    # The token is NOT cleared — the command is still pending and still awaiting.
    status = client.get(f"/commands/{cid}", headers=AUTH).json()
    assert status["status"] == "pending"
    assert status["needs_confirmation"] is True


# --- helpers ----------------------------------------------------------------


class _FakeSecrets:
    live_trading = True


class _FakeConfig:
    secrets = _FakeSecrets()

    @property
    def is_live(self) -> bool:
        return True


def _live_config() -> _FakeConfig:
    return _FakeConfig()
