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

    # Research DB — isolated + seeded, so the universe_add/universe_remove boundary check
    # (Fix 2) has a real symbol directory to check an unknown symbol against, mirroring
    # tests/test_drain_universe.py's fixture.
    from src.research.store.models import SymbolRow
    from src.research.store.session import init_research_db, research_session

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session() as s:
        s.add(SymbolRow(symbol="NVDA", cik="1", name="NVIDIA Corp"))

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
    """Task 4.1 gates promote on an assessed row at a promotable stage — seed one
    for "abc" so this test can stay focused on the live-mode confirmation behaviour
    it's named for. The guard itself is exercised by tests/test_promote_guard.py."""
    from datetime import date, timedelta

    from src.storage.db import session_scope
    from src.storage.models import RiskVerdictRow

    with session_scope() as s:
        s.add(
            RiskVerdictRow(
                candidate_id="abc",
                run_id="run-1",
                symbol="NVDA",
                strategy="covered_call",
                strike=105.0,
                expiry=date.today() + timedelta(days=30),
                verdict="pass",
                stage="top_n",
                reasons=[],
                blended_score=70.0,
                premium=3.0,
            )
        )

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


# ---------------------------------------------------------------------------
# M6 Task 6.2 — control kinds at the API boundary.
# ---------------------------------------------------------------------------


def test_post_set_autonomy_with_an_invalid_level_is_422_and_creates_no_row(client) -> None:
    """A level outside the four rungs never becomes a command row."""
    r = client.post(
        "/commands",
        json={"kind": "set_autonomy", "payload": {"level": "yolo"}},
        headers=AUTH,
    )
    assert r.status_code == 422
    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow

    with session_scope() as s:
        assert s.query(AppCommandRow).count() == 0


def test_post_halt_with_an_over_length_reason_is_422_and_creates_no_row(client) -> None:
    r = client.post(
        "/commands",
        json={"kind": "halt", "payload": {"reason": "x" * 201}},
        headers=AUTH,
    )
    assert r.status_code == 422
    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow

    with session_scope() as s:
        assert s.query(AppCommandRow).count() == 0


def test_post_universe_add_with_an_unknown_symbol_is_404_and_creates_no_row(client) -> None:
    """M7 final-review Fix 2: routers/universe.py's thin POST/DELETE wrappers already 404 on
    an unknown symbol, but the generic POST /commands route accepted a universe_add/
    universe_remove payload directly with no such check — an owner could smuggle an override
    for a symbol that doesn't exist in the research directory straight past those wrappers.
    """
    r = client.post(
        "/commands",
        json={"kind": "universe_add", "payload": {"symbol": "ZZZZZZ", "list_name": "would_own"}},
        headers=AUTH,
    )
    assert r.status_code == 404

    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow

    with session_scope() as s:
        assert s.query(AppCommandRow).count() == 0


def test_post_universe_remove_with_an_unknown_symbol_is_404_and_creates_no_row(client) -> None:
    r = client.post(
        "/commands",
        json={
            "kind": "universe_remove",
            "payload": {"symbol": "ZZZZZZ", "list_name": "watchlist"},
        },
        headers=AUTH,
    )
    assert r.status_code == 404

    from src.storage.db import session_scope
    from src.storage.models import AppCommandRow

    with session_scope() as s:
        assert s.query(AppCommandRow).count() == 0


def test_post_universe_add_with_a_known_symbol_still_works_via_the_generic_route(client) -> None:
    """The Fix 2 guard must not refuse a symbol that genuinely exists — NVDA is seeded into
    the research DB by the client fixture."""
    r = client.post(
        "/commands",
        json={"kind": "universe_add", "payload": {"symbol": "NVDA", "list_name": "would_own"}},
        headers=AUTH,
    )
    assert r.status_code == 201
    assert r.json()["kind"] == "universe_add"


def test_post_halt_in_live_mode_needs_no_confirmation(client, monkeypatch) -> None:
    """The deliberate asymmetry (M6): the live token in §4.6 is for intents that can
    reach an order. A halt is not one — a halt must never be slowed by a second step.
    This looks like an oversight otherwise; the test name says it is not."""
    monkeypatch.setattr("src.api.routers.commands.get_config", lambda: _live_config())
    r = client.post(
        "/commands",
        json={"kind": "halt", "payload": {"reason": "checking something"}},
        headers=AUTH,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["needs_confirmation"] is False
    assert body["confirm_token"] is None
