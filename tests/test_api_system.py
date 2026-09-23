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


def test_status_degrades_gracefully_instead_of_500ing_when_trading_db_is_unreachable(
    client, tmp_path, monkeypatch
) -> None:
    """Final-review fix #1: a broken trading DB used to 500 the whole endpoint, because
    `read_setting`/`_ibkr_leg` kept reading the same already-failed Session past the
    initial `SELECT 1` reachability check. Point the read-only engine at a file that was
    never created (`mode=ro` refuses to open a missing file) and confirm the response is
    still a clean 200 with every trading_db-dependent row reading "unknown", not a 500."""
    broken = tmp_path / "no_such_income_system.db"
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: broken.as_posix())
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)

    r = client.get("/system/status", headers=AUTH)
    assert r.status_code == 200
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["trading_db"]["state"] == "down"
    assert rows["command_drain"]["state"] == "unknown"
    assert rows["intraday_monitor"]["state"] == "unknown"
    assert rows["ibkr_connection"]["state"] == "unknown"
    # The research DB is untouched by this and stays reachable.
    assert rows["research_db"]["state"] == "ok"


def test_status_degrades_gracefully_instead_of_500ing_when_research_db_is_unreachable(
    client, tmp_path, monkeypatch
) -> None:
    """Same as above for the research DB: `read_heartbeat()` (the research-worker row)
    must be skipped, not raise, once the initial `SELECT 1` shows the DB unreachable.
    A directory in place of the db file makes sqlite's own open() fail immediately,
    the same "unopenable path" shape as the trading DB test above."""
    broken_dir = tmp_path / "research_db_is_actually_a_directory"
    broken_dir.mkdir()
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{broken_dir.as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    monkeypatch.setattr("src.research.store.session._SessionLocal", None)

    r = client.get("/system/status", headers=AUTH)
    assert r.status_code == 200
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["research_db"]["state"] == "down"
    assert rows["research_worker"]["state"] == "unknown"
    # The trading DB is untouched by this and stays reachable.
    assert rows["trading_db"]["state"] == "ok"


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


def test_intraday_monitor_is_down_with_a_stale_heartbeat(client) -> None:
    from src.common.config import get_config

    poll = get_config().scheduler.intraday_poll_seconds
    stale = datetime.now(UTC) - timedelta(seconds=poll * 3)
    _set("monitor_heartbeat", stale.isoformat())
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["intraday_monitor"]["state"] == "down"


def _set_research_heartbeat(when: datetime) -> None:
    from src.research.store.models import WorkerHeartbeatRow
    from src.research.store.session import research_session

    with research_session() as session:
        row = session.get(WorkerHeartbeatRow, 1)
        if row is None:
            session.add(WorkerHeartbeatRow(id=1, beat_at=when, last_job="test"))
        else:
            row.beat_at = when


def test_research_worker_is_unknown_when_never_run(client) -> None:
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["research_worker"]["state"] == "unknown"
    assert rows["research_worker"]["log_key"] == "research"


def test_research_worker_is_down_with_a_stale_heartbeat(client) -> None:
    from src.api.routers.system import _RESEARCH_WORKER_MAX_AGE

    stale = datetime.now(UTC) - (_RESEARCH_WORKER_MAX_AGE * 3)
    _set_research_heartbeat(stale)
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["research_worker"]["state"] == "down"


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


def test_ibkr_connection_reads_the_worse_of_one_unknown_and_one_ok_leg(client) -> None:
    """Only the drain has ever reported (ok, connected); the monitor never has, so its
    leg is "unknown". The aggregate must read the worse of the two legs, not just the
    first one computed."""
    now = datetime.now(UTC).isoformat()
    _set("command_drain_heartbeat", now)
    _set("command_drain_ibkr_connected", "true")
    r = client.get("/system/status", headers=AUTH)
    rows = {row["key"]: row for row in r.json()["rows"]}
    assert rows["ibkr_connection"]["state"] == "unknown"
    assert "intraday_monitor: not yet reporting" in rows["ibkr_connection"]["detail"]


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


def test_a_half_open_breaker_makes_data_providers_degraded(client) -> None:
    from src.data.breaker import get_breaker

    # A zero cooldown means the breaker is eligible to report half_open the instant it
    # opens — no need to fake the clock.
    fmp = get_breaker("fmp_test_half_open", threshold=3, cooldown_seconds=0.0)
    fmp.record_success()  # reset any prior state from another test
    for _ in range(3):
        fmp.record_failure()
    try:
        r = client.get("/system/status", headers=AUTH)
        rows = {row["key"]: row for row in r.json()["rows"]}
        assert rows["data_providers"]["state"] == "degraded"
        assert "recovering" in rows["data_providers"]["detail"]
    finally:
        fmp.record_success()


def test_log_requires_owner_auth(client) -> None:
    assert client.get("/system/monitor/log").status_code == 401


def test_log_rejects_an_unknown_system_name(client) -> None:
    r = client.get("/system/api/log", headers=AUTH)
    assert r.status_code == 404


def test_log_returns_empty_lines_when_the_file_does_not_exist(client, tmp_path, monkeypatch):
    from src.api.routers import system as system_router

    monkeypatch.setitem(system_router._LOG_FILES, "monitor", tmp_path / "no_such_file.log")
    r = client.get("/system/monitor/log", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["lines"] == []
    assert body["file_exists"] is False


def test_log_reports_file_exists_true_when_the_file_has_no_matching_lines(
    client, tmp_path, monkeypatch
):
    """Final-review fix #3: a log file that exists but has nothing at the requested
    level (the common, healthy-daemon case) must be distinguishable from a genuinely
    missing log file, so the frontend does not render "No log file yet" for a clean
    log."""
    log_file = tmp_path / "monitor.log"
    log_file.write_text(
        "2026-09-23 10:00:00 | INFO     | src.monitor.intraday | subscribed AAPL\n",
        encoding="utf-8",
    )
    from src.api.routers import system as system_router

    monkeypatch.setitem(system_router._LOG_FILES, "monitor", log_file)
    r = client.get("/system/monitor/log", headers=AUTH)  # default level=warn
    assert r.status_code == 200
    body = r.json()
    assert body["lines"] == []
    assert body["file_exists"] is True


def test_log_filters_to_warning_and_above_by_default(client, tmp_path, monkeypatch):
    log_file = tmp_path / "monitor.log"
    log_file.write_text(
        "2026-09-23 10:00:00 | INFO     | src.monitor.intraday | subscribed AAPL\n"
        "2026-09-23 10:00:01 | WARNING  | src.monitor.intraday | IV spike detected\n"
        "2026-09-23 10:00:02 | ERROR    | src.monitor.intraday | reqMktData failed\n",
        encoding="utf-8",
    )
    from src.api.routers import system as system_router

    monkeypatch.setitem(system_router._LOG_FILES, "monitor", log_file)
    r = client.get("/system/monitor/log", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert len(body["lines"]) == 2
    assert all("INFO" not in line for line in body["lines"])


def test_log_level_info_widens_to_include_info_lines(client, tmp_path, monkeypatch):
    log_file = tmp_path / "monitor.log"
    log_file.write_text(
        "2026-09-23 10:00:00 | INFO     | src.monitor.intraday | subscribed AAPL\n"
        "2026-09-23 10:00:01 | WARNING  | src.monitor.intraday | IV spike detected\n",
        encoding="utf-8",
    )
    from src.api.routers import system as system_router

    monkeypatch.setitem(system_router._LOG_FILES, "monitor", log_file)
    r = client.get("/system/monitor/log?level=info", headers=AUTH)
    assert len(r.json()["lines"]) == 2


def test_log_caps_at_the_requested_line_count(client, tmp_path, monkeypatch):
    log_file = tmp_path / "monitor.log"
    lines = "".join(
        f"2026-09-23 10:00:{i:02d} | WARNING  | src.monitor.intraday | alert {i}\n"
        for i in range(10)
    )
    log_file.write_text(lines, encoding="utf-8")
    from src.api.routers import system as system_router

    monkeypatch.setitem(system_router._LOG_FILES, "monitor", log_file)
    r = client.get("/system/monitor/log?lines=3", headers=AUTH)
    body = r.json()["lines"]
    assert len(body) == 3
    assert "alert 9" in body[-1]
    assert "alert 7" in body[0]
