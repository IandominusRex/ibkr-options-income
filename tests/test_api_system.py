"""GET /system/status — the left-rail status card's backend.

See docs/superpowers/specs/2026-09-23-web-system-status-card-design.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.storage.db import session_scope
from src.storage.models import SystemSettingRow

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

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    from src.research.store.session import init_research_db

    init_research_db()

    return TestClient(create_app())


def _set(key: str, value: str) -> None:
    with session_scope() as s:
        row = s.query(SystemSettingRow).filter_by(key=key).first()
        if row:
            row.value = value
        else:
            s.add(SystemSettingRow(key=key, value=value))


def test_status_requires_owner_auth(client) -> None:
    assert client.get("/system/status").status_code == 401


def test_status_requires_owner_role(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/system/status", headers=AUTH).status_code == 403


def test_status_lists_all_seven_rows(client) -> None:
    r = client.get("/system/status", headers=AUTH)
    assert r.status_code == 200
    keys = {row["key"] for row in r.json()["rows"]}
    assert keys == {
        "trading_db",
        "research_db",
        "data_providers",
        "command_drain",
        "intraday_monitor",
        "research_worker",
        "ibkr_connection",
    }


def test_trading_db_and_research_db_are_ok_by_default(client) -> None:
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["trading_db"]["state"] == "ok"
    assert rows["research_db"]["state"] == "ok"


def test_command_drain_is_unknown_when_never_run(client) -> None:
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["command_drain"]["state"] == "unknown"
    assert rows["command_drain"]["log_key"] == "approval"


def test_command_drain_is_ok_with_a_recent_heartbeat(client) -> None:
    _set("command_drain_heartbeat", datetime.now(UTC).isoformat())
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["command_drain"]["state"] == "ok"


def test_command_drain_is_down_with_a_stale_heartbeat(client) -> None:
    from src.common.config import get_config

    poll = get_config().execution.poll_interval_seconds
    stale = datetime.now(UTC) - timedelta(seconds=poll * 3)
    _set("command_drain_heartbeat", stale.isoformat())
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["command_drain"]["state"] == "down"


def test_intraday_monitor_is_unknown_when_never_run(client) -> None:
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["intraday_monitor"]["state"] == "unknown"
    assert rows["intraday_monitor"]["log_key"] == "monitor"


def test_intraday_monitor_is_ok_with_a_recent_heartbeat(client) -> None:
    _set("monitor_heartbeat", datetime.now(UTC).isoformat())
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["intraday_monitor"]["state"] == "ok"


def test_research_worker_is_unknown_when_never_run(client) -> None:
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["research_worker"]["state"] == "unknown"
    assert rows["research_worker"]["log_key"] == "research"


def test_ibkr_connection_is_unknown_when_neither_daemon_has_reported(client) -> None:
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["ibkr_connection"]["state"] == "unknown"
    assert rows["ibkr_connection"]["log_key"] is None


def test_ibkr_connection_is_ok_when_both_daemons_report_connected(client) -> None:
    now = datetime.now(UTC).isoformat()
    _set("command_drain_heartbeat", now)
    _set("command_drain_ibkr_connected", "true")
    _set("monitor_heartbeat", now)
    _set("monitor_ibkr_connected", "true")
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["ibkr_connection"]["state"] == "ok"


def test_ibkr_connection_is_down_when_one_daemon_reports_disconnected(client) -> None:
    now = datetime.now(UTC).isoformat()
    _set("command_drain_heartbeat", now)
    _set("command_drain_ibkr_connected", "true")
    _set("monitor_heartbeat", now)
    _set("monitor_ibkr_connected", "false")
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["ibkr_connection"]["state"] == "down"


def test_data_providers_is_ok_by_default(client) -> None:
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["data_providers"]["state"] == "ok"
    assert rows["data_providers"]["log_key"] is None


def test_an_open_breaker_makes_data_providers_down(client) -> None:
    from src.data.breaker import get_breaker

    edgar = get_breaker("edgar", threshold=3, cooldown_seconds=300.0)
    edgar.record_success()  # reset any prior state from another test
    for _ in range(3):
        edgar.record_failure()
    try:
        r = client.get("/system/status", headers=AUTH)
        rows = {row["key"]: row for row in r.json()["rows"]}
        assert rows["data_providers"]["state"] == "down"
    finally:
        edgar.record_success()
