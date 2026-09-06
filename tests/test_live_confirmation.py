"""Live-mode second confirmation (M3 Task 3.5 / spec §4.6). The gate must fail closed.

In live mode an order-reaching intent (`approve`, `promote`, `roll_request`) is created
with a ``confirm_token`` and the drain SKIPS it until ``POST /commands/{id}/confirm``
supplies the right token. If the confirm route were broken, nothing executes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


def _live(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.common.config.Config.is_live", property(lambda self: True), raising=False
    )


def _paper(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.common.config.Config.is_live", property(lambda self: False), raising=False
    )


def _post_approve(client) -> dict:
    return client.post(
        "/commands", json={"kind": "approve", "payload": {"approval_id": 1}}, headers=AUTH
    ).json()


def _seed_approval() -> int:
    from src.common.schemas import ApprovalStatus
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    with session_scope() as s:
        row = ApprovalRow(
            candidate_id="NVDA-cand-1",
            status=ApprovalStatus.PENDING,
            snapshot={"underlying": "NVDA", "contracts": 1},
            expires_at=datetime.now(UTC) + timedelta(hours=2),
        )
        s.add(row)
        s.flush()
        return row.id


# ---------------------------------------------------------------------------
# Token creation — live vs paper, by kind
# ---------------------------------------------------------------------------


def test_live_mode_approve_stores_a_token_and_needs_confirmation(client, monkeypatch) -> None:
    _live(monkeypatch)
    body = _post_approve(client)
    assert body["needs_confirmation"] is True
    assert body["confirm_token"]
    assert body["status"] == "pending"


def test_paper_mode_approve_stores_no_token(client, monkeypatch) -> None:
    _paper(monkeypatch)
    body = _post_approve(client)
    assert body["needs_confirmation"] is False
    assert body.get("confirm_token") is None


def test_live_mode_reject_needs_no_confirmation(client, monkeypatch) -> None:
    """Reject cannot reach an order, so it never needs the second confirmation."""
    _live(monkeypatch)
    r = client.post(
        "/commands", json={"kind": "reject", "payload": {"approval_id": 1}}, headers=AUTH
    )
    assert r.json()["needs_confirmation"] is False


def test_live_mode_promote_and_roll_request_need_confirmation(client, monkeypatch) -> None:
    _live(monkeypatch)
    promote = client.post(
        "/commands",
        json={
            "kind": "promote",
            "payload": {
                "candidate_id": "c1",
                "symbol": "NVDA",
                "strategy": "cash_secured_put",
                "strike": 190.0,
                "expiry": "2026-10-16",
            },
        },
        headers=AUTH,
    ).json()
    roll = client.post(
        "/commands",
        json={"kind": "roll_request", "payload": {"position_symbol": "NVDA 261016C00190000"}},
        headers=AUTH,
    ).json()
    assert promote["needs_confirmation"] is True
    assert roll["needs_confirmation"] is True


# ---------------------------------------------------------------------------
# The drain skips unconfirmed commands — fail closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_drain_skips_an_unresolved_confirm_token(monkeypatch, tmp_path) -> None:
    """Asserted against the drain, not the UI. If the confirm route were broken,
    nothing executes."""
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()

    from unittest.mock import AsyncMock

    from src.notify.command_drain import drain_once
    from src.storage.app_commands import enqueue_command
    from src.storage.models import AppCommandRow

    with dbmod.session_scope() as s:
        row, _ = enqueue_command(
            s,
            kind="approve",
            payload={"approval_id": 1},
            requested_by="test",
            confirm_token="tok",
        )
        cid = row.id

    processed = await drain_once(None, AsyncMock(), "chat")

    with dbmod.session_scope() as s:
        row = s.get(AppCommandRow, cid)
        assert row is not None
        assert row.status == "pending"  # skipped, not applied, not failed
    assert processed == 0


@pytest.mark.asyncio
async def test_a_confirmed_command_applies_on_the_next_drain(client, monkeypatch) -> None:
    """The right token clears the field; the next drain applies the command."""
    _live(monkeypatch)
    approval_id = _seed_approval()
    body = client.post(
        "/commands", json={"kind": "approve", "payload": {"approval_id": approval_id}}, headers=AUTH
    ).json()
    cid, token = body["id"], body["confirm_token"]

    # Confirm with the right token.
    r = client.post(f"/commands/{cid}/confirm", json={"confirm_token": token}, headers=AUTH)
    assert r.status_code == 204

    # Reuse the API client's monkeypatched DB for the drain (same tmp trading db).
    from unittest.mock import AsyncMock

    from src.notify.command_drain import drain_once
    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow

    await drain_once(None, AsyncMock(), "chat")
    with session_scope() as s:
        row = s.get(AppCommandRow, cid)
        assert row is not None
        assert row.status == "applied"


def test_a_wrong_token_is_403_and_does_not_clear(client, monkeypatch) -> None:
    _live(monkeypatch)
    body = _post_approve(client)
    cid = body["id"]

    r = client.post(f"/commands/{cid}/confirm", json={"confirm_token": "wrong"}, headers=AUTH)
    assert r.status_code == 403

    status = client.get(f"/commands/{cid}", headers=AUTH).json()
    assert status["status"] == "pending"  # still pending — not applied, not failed
    assert status["needs_confirmation"] is True  # token NOT cleared


def test_confirming_a_command_not_awaiting_confirmation_is_409(client, monkeypatch) -> None:
    _paper(monkeypatch)  # paper → no token → not awaiting
    body = _post_approve(client)
    cid = body["id"]

    r = client.post(f"/commands/{cid}/confirm", json={"confirm_token": "anything"}, headers=AUTH)
    assert r.status_code == 409


def test_an_expired_command_is_swept_never_applied(client, monkeypatch) -> None:
    """The token expires with approval.ttl_minutes; the sweep moves it to expired."""
    _live(monkeypatch)
    body = _post_approve(client)
    cid = body["id"]

    # Move the clock forward: backdate created_at past the TTL, then drain.
    from unittest.mock import AsyncMock

    from src.notify.command_drain import drain_once
    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow

    ttl = 60  # config default
    with session_scope() as s:
        row = s.get(AppCommandRow, cid)
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(minutes=ttl + 1)

    import asyncio

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        drain_once(None, AsyncMock(), "chat")
    )
    with session_scope() as s:
        row = s.get(AppCommandRow, cid)
        assert row is not None
        assert row.status == "expired"
        assert row.result["reason"] == "ttl_expired"
