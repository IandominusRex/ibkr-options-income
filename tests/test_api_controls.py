"""GET /options/controls — autonomy rung, halt state, mode, drain health.

``drain_healthy`` reads the ``command_drain_heartbeat`` system_settings key (not
/health's ``worker_heartbeat``, which reports the research worker). A drain that
has never run is ``false`` with ``drain_last_seen: null`` — it must never default
to ``true``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.storage.db import session_scope
from src.storage.models import AppCommandRow, SystemSettingRow

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


def test_controls_requires_owner_auth(client) -> None:
    assert client.get("/options/controls").status_code == 401


def test_controls_requires_owner_role(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/options/controls", headers=AUTH).status_code == 403


def test_autonomy_level_reads_through_get_autonomy_level(client) -> None:
    from src.common.schemas import AutonomyLevel
    from src.storage.system_settings import set_autonomy_level

    set_autonomy_level(AutonomyLevel.MANUAL)
    r = client.get("/options/controls", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["autonomy"]["level"] == "manual"


def test_rungs_lists_all_four_in_ladder_order(client) -> None:
    r = client.get("/options/controls", headers=AUTH)
    rungs = r.json()["rungs"]
    levels = [rung["level"] for rung in rungs]
    assert levels == ["observe", "manual", "whitelist", "full"]


def test_mode_derives_from_cfg_is_live_paper(client) -> None:
    r = client.get("/options/controls", headers=AUTH)
    assert r.json()["mode"] == "paper"


def test_mode_derives_from_cfg_is_live_live(client, monkeypatch) -> None:
    class _FakeSecrets:
        live_trading = True

    class _FakeConfig:
        secrets = _FakeSecrets()

        @property
        def is_live(self) -> bool:
            return True

        execution = type("E", (), {"poll_interval_seconds": 30})()
        weights: dict = {}

    monkeypatch.setattr("src.api.routers.options.get_config", lambda: _FakeConfig())
    r = client.get("/options/controls", headers=AUTH)
    assert r.json()["mode"] == "live"


def test_drain_healthy_is_false_when_never_run(client) -> None:
    """A drain that has never run must be false with null drain_last_seen."""
    r = client.get("/options/controls", headers=AUTH)
    body = r.json()
    assert body["drain_healthy"] is False
    assert body["drain_last_seen"] is None


def test_drain_healthy_is_true_when_heartbeat_is_recent(client) -> None:
    with session_scope() as s:
        s.add(
            SystemSettingRow(
                key="command_drain_heartbeat",
                value=datetime.now(UTC).isoformat(),
            )
        )
    r = client.get("/options/controls", headers=AUTH)
    assert r.json()["drain_healthy"] is True
    assert r.json()["drain_last_seen"] is not None


def test_drain_healthy_is_false_when_heartbeat_is_stale(client) -> None:
    """Older than twice the poll interval → false."""
    from src.common.config import get_config

    poll = get_config().execution.poll_interval_seconds
    stale = datetime.now(UTC) - timedelta(seconds=poll * 3)
    with session_scope() as s:
        s.add(
            SystemSettingRow(
                key="command_drain_heartbeat",
                value=stale.isoformat(),
            )
        )
    r = client.get("/options/controls", headers=AUTH)
    assert r.json()["drain_healthy"] is False
    assert r.json()["drain_last_seen"] is not None  # the stale timestamp is still shown


def test_pending_commands_counts_pending_rows(client) -> None:
    with session_scope() as s:
        s.add(AppCommandRow(kind="refresh", payload={}, requested_by="owner", status="pending"))
        s.add(AppCommandRow(kind="refresh", payload={}, requested_by="owner", status="pending"))
        s.add(AppCommandRow(kind="refresh", payload={}, requested_by="owner", status="applied"))
    r = client.get("/options/controls", headers=AUTH)
    assert r.json()["pending_commands"] == 2


def test_halted_and_halt_reason(client) -> None:
    from src.storage.system_settings import set_halted

    set_halted(True, reason="manual kill switch")
    r = client.get("/options/controls", headers=AUTH)
    body = r.json()
    assert body["halted"] is True
    assert body["halt_reason"] == "manual kill switch"
    # cleanup
    set_halted(False)


def test_halted_at_derives_from_the_most_recent_applied_halt_command(client) -> None:
    """M6 Task 6.3: the banner shows when the halt was engaged, derived from the
    command queue (no separate settings key). A breaker-tripped halt has no command
    row, so it renders no time rather than a fabricated one."""
    from src.storage.system_settings import set_halted

    when = datetime.now(UTC) - timedelta(minutes=3)
    with session_scope() as s:
        s.add(
            AppCommandRow(
                kind="halt",
                payload={"reason": "from the web"},
                requested_by="owner",
                status="applied",
                applied_at=when,
            )
        )
    set_halted(True, reason="from the web")
    try:
        r = client.get("/options/controls", headers=AUTH)
        body = r.json()
        assert body["halted"] is True
        assert body["halted_at"] is not None
        # The exact second survives the JSON round trip (server stores naive UTC).
        assert body["halted_at"].startswith(when.strftime("%Y-%m-%dT%H:%M:%S"))
    finally:
        set_halted(False)


def test_halted_at_is_null_for_a_halt_with_no_command_row(client) -> None:
    """A circuit-breaker halt has no command row: honest null, no fabricated time."""
    from src.storage.system_settings import set_halted

    set_halted(True, reason="circuit breaker")
    try:
        r = client.get("/options/controls", headers=AUTH)
        body = r.json()
        assert body["halted"] is True
        assert body["halted_at"] is None
    finally:
        set_halted(False)


def test_halted_at_does_not_leak_a_stale_timestamp_from_a_prior_halt_cycle(client) -> None:
    """A resumed web halt must not shadow a later, command-row-less halt.

    Without a lower bound on the halt search, the max-applied-halt query would keep
    returning the *first* halt's timestamp forever, even after a resume and a brand
    new (breaker-tripped) halt — fabricating a stale time instead of the honest null
    the earlier test above requires for a halt with no command row.
    """
    from src.storage.system_settings import set_halted

    old_halt = datetime.now(UTC) - timedelta(hours=2)
    old_resume = datetime.now(UTC) - timedelta(hours=1)
    with session_scope() as s:
        s.add(
            AppCommandRow(
                kind="halt",
                payload={"reason": "earlier web halt"},
                requested_by="owner",
                status="applied",
                applied_at=old_halt,
            )
        )
        s.add(
            AppCommandRow(
                kind="resume",
                payload={},
                requested_by="owner",
                status="applied",
                applied_at=old_resume,
                result={"released_by": "owner"},
            )
        )
    # A fresh halt with no command row of its own — e.g. a circuit breaker trip.
    set_halted(True, reason="circuit breaker, second episode")
    try:
        r = client.get("/options/controls", headers=AUTH)
        body = r.json()
        assert body["halted"] is True
        assert body["halted_at"] is None
    finally:
        set_halted(False)
