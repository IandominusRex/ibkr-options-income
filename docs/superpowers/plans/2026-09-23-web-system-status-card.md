# Web System Status Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a status card pinned to the bottom of the web console's left rail showing
red/green health for 7 systems (2 databases, data providers, the command drain, the
intraday monitor, the research worker, and the aggregate IBKR connection), with a
click-through slide-over panel per daemon showing its tailed, level-filtered log.

**Architecture:** Two daemons that currently report no health signal
(`intraday_monitor`, `approval_service`) start writing a heartbeat + IBKR-connected flag
to the trading DB's `system_settings` table, the same mechanism the command drain
already uses for its own heartbeat. A new owner-only FastAPI router
(`src/api/routers/system.py`) aggregates all 7 signals into `GET /system/status` and
serves a level-filtered log tail per daemon via `GET /system/{name}/log`. A new
`SystemStatusCard` component polls the status endpoint every 20s and renders the rows;
clicking one with a log opens a focus-trapped slide-over panel (`SystemLogPanel`) that
fetches on open only.

**Tech Stack:** FastAPI + SQLAlchemy + Pydantic (backend), Next.js + TypeScript +
`@tanstack/react-query` + Tailwind (frontend), pytest (backend tests), Vitest +
Testing Library (frontend tests).

**Spec:** `docs/superpowers/specs/2026-09-23-web-system-status-card-design.md`

## Global Constraints

- Every new endpoint is owner-only (`OwnerUser`, 401 unauthenticated / 403 non-owner) — same sensitivity class as `GET /options/controls`.
- No fourth color: `ok` renders in the `gain` tone, `down` in the `loss` tone, and both `degraded` and `unknown` render in the existing `unknown` tone (hatch texture) — distinguished only by their `detail` text, per `web/CLAUDE.md`'s tri-tone rule.
- `GET /system/{name}/log`'s `name` is validated against a fixed allowlist mapped to real paths — never built from the request path.
- Log responses are capped at 150 lines.
- The log slide-over panel fetches on open only — no auto-poll inside it.
- `src/api/**` may import nothing that pulls `ib_async` into its own file text (`tests/test_web_fence.py::test_the_api_never_constructs_a_broker_connection` greps for the literal substring `"ib_async"` under `src/api/`) — this feature adds zero broker-facing imports anywhere under `src/api/`.
- This feature is entirely read-only: no route added here writes to any table (matches `tests/test_web_fence.py`'s single-write-table guarantee).

---

## Task 1: Intraday monitor writes a heartbeat + IBKR-connected flag

**Files:**
- Modify: `src/storage/system_settings.py` (add two key constants)
- Modify: `src/monitor/intraday.py` (add `_write_heartbeat`, call it from `_refresh_subscriptions`)
- Test: `tests/test_monitor_heartbeat.py` (new)

**Interfaces:**
- Produces: `MONITOR_HEARTBEAT_KEY = "monitor_heartbeat"`, `MONITOR_IBKR_CONNECTED_KEY = "monitor_ibkr_connected"` (in `src.storage.system_settings`, read later by Task 4's `system.py`). `IntradayMonitor._write_heartbeat(self) -> None`.

- [ ] **Step 1: Add the two new setting keys**

In `src/storage/system_settings.py`, add alongside the existing key constants (after
`HIGH_WATER_MARK_KEY = "nlv_high_water_mark"`):

```python
MONITOR_HEARTBEAT_KEY = "monitor_heartbeat"
MONITOR_IBKR_CONNECTED_KEY = "monitor_ibkr_connected"
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_monitor_heartbeat.py`:

```python
"""The monitor writes a heartbeat + IBKR-connected flag every refresh cycle.

Read by GET /system/status (src/api/routers/system.py) to drive the "Intraday monitor"
and "IBKR connection" rows on the web status card (docs/superpowers/specs/
2026-09-23-web-system-status-card-design.md). set_setting never raises, so a write here
cannot destabilise the refresh loop the way an unguarded DB write could.

Fixture mirrors tests/test_monitor_snapshot.py's `_make_monitor_env` rather than
importing it — each monitor test file builds its own copy of the harness, per that
file's own docstring convention.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.storage.system_settings import (
    MONITOR_HEARTBEAT_KEY,
    MONITOR_IBKR_CONNECTED_KEY,
    get_setting,
)


def _make_monitor_env() -> Any:
    mock_ib = MagicMock()
    mock_ib.tickers.return_value = []
    mock_ib.portfolio.return_value = []
    mock_ib.isConnected.return_value = True
    mock_ib.qualifyContractsAsync = AsyncMock(side_effect=lambda *contracts: list(contracts))
    mock_cfg = MagicMock()
    mock_cfg.monitor.delta_ceiling = 0.45
    mock_cfg.monitor.dte_threshold = 7
    mock_cfg.monitor.manage_at_dte = 21
    mock_cfg.monitor.iv_spike_pct = 40.0
    mock_cfg.monitor.ex_div_days_ahead = 5
    mock_cfg.monitor.alert_cooldown_minutes = 60
    mock_cfg.scheduler.intraday_poll_seconds = 60
    mock_cfg.claude.enabled = False
    mock_cfg.market_data.portfolio_snapshot_interval_minutes = 15
    mock_cfg.ibkr.connect_timeout_seconds = 10.0
    mock_cfg.secrets.ibkr_account = "DU123"

    from src.monitor.intraday import IntradayMonitor

    executor = ThreadPoolExecutor(max_workers=1)
    monitor = IntradayMonitor(mock_ib, AsyncMock(), "99999", mock_cfg, executor)
    return monitor, mock_ib


@pytest.fixture
def monitor_env(monkeypatch, tmp_path):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(
        Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'monitor_heartbeat.db'}"
    )
    dbmod.init_db()

    monitor, mock_ib = _make_monitor_env()
    yield monitor, mock_ib
    monitor._executor.shutdown(wait=False)


def test_write_heartbeat_records_the_current_time(monitor_env) -> None:
    monitor, _mock_ib = monitor_env
    before = datetime.now(UTC)
    monitor._write_heartbeat()
    raw = get_setting(MONITOR_HEARTBEAT_KEY, "")
    assert raw != ""
    written = datetime.fromisoformat(raw)
    assert written >= before


def test_write_heartbeat_records_connected_true(monitor_env) -> None:
    monitor, mock_ib = monitor_env
    mock_ib.isConnected.return_value = True
    monitor._write_heartbeat()
    assert get_setting(MONITOR_IBKR_CONNECTED_KEY, "") == "true"


def test_write_heartbeat_records_connected_false(monitor_env) -> None:
    monitor, mock_ib = monitor_env
    mock_ib.isConnected.return_value = False
    monitor._write_heartbeat()
    assert get_setting(MONITOR_IBKR_CONNECTED_KEY, "") == "false"


@pytest.mark.asyncio
async def test_refresh_subscriptions_writes_the_heartbeat(monitor_env) -> None:
    """Integration check: the real refresh cycle reaches _write_heartbeat, not just a
    direct call to it."""
    monitor, _mock_ib = monitor_env
    with patch("src.monitor.intraday.is_rth", return_value=False):
        await monitor._refresh_subscriptions()
    assert get_setting(MONITOR_HEARTBEAT_KEY, "") != ""
```

- [ ] **Step 3: Run the tests, verify they fail**

Run: `python -m pytest tests/test_monitor_heartbeat.py -v`
Expected: FAIL — `AttributeError: 'IntradayMonitor' object has no attribute '_write_heartbeat'`

- [ ] **Step 4: Implement `_write_heartbeat` and wire it in**

In `src/monitor/intraday.py`, add the import (alongside the existing
`from src.storage.portfolio_snapshots import (...)` block):

```python
from src.storage.system_settings import (
    MONITOR_HEARTBEAT_KEY,
    MONITOR_IBKR_CONNECTED_KEY,
    set_setting,
)
```

Add the method to `IntradayMonitor`, directly after `_maybe_write_snapshot`:

```python
    def _write_heartbeat(self) -> None:
        """Record that this refresh cycle completed and whether IBKR is connected.

        Read by GET /system/status (src/api/routers/system.py) to drive the "Intraday
        monitor" and "IBKR connection" rows on the web status card. set_setting never
        raises, so this cannot destabilise the refresh loop.
        """
        set_setting(MONITOR_HEARTBEAT_KEY, datetime.now(UTC).isoformat())
        set_setting(MONITOR_IBKR_CONNECTED_KEY, "true" if self._ib.isConnected() else "false")
```

At the end of `_refresh_subscriptions`, immediately after the existing
`await self._maybe_write_snapshot(positions)` line, add:

```python
        # Heartbeat for the web status card (GET /system/status) — written every cycle,
        # connected or not, mirroring the command drain's "write after the work, never
        # before" rule so a hung loop cannot make the monitor look healthy.
        self._write_heartbeat()
```

- [ ] **Step 5: Run the tests, verify they pass**

Run: `python -m pytest tests/test_monitor_heartbeat.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add src/storage/system_settings.py src/monitor/intraday.py tests/test_monitor_heartbeat.py
git commit -m "feat(monitor): write a heartbeat + IBKR-connected flag every refresh cycle"
```

---

## Task 2: Command drain writes an IBKR-connected flag

**Files:**
- Modify: `src/storage/system_settings.py` (add one key constant)
- Modify: `src/notify/command_drain.py` (write the flag alongside the existing heartbeat)
- Test: `tests/test_command_drain.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `COMMAND_DRAIN_IBKR_CONNECTED_KEY = "command_drain_ibkr_connected"` (in `src.storage.system_settings`, read later by Task 4's `system.py`).

- [ ] **Step 1: Add the new setting key**

In `src/storage/system_settings.py`, add directly below the two constants Task 1 added:

```python
COMMAND_DRAIN_IBKR_CONNECTED_KEY = "command_drain_ibkr_connected"
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_command_drain.py` (after
`test_a_hung_handler_does_not_advance_the_heartbeat_before_failing`):

```python
@pytest.mark.asyncio
async def test_ibkr_connected_is_false_when_ib_is_none(drain_env) -> None:
    from src.notify.command_drain import drain_once
    from src.storage.system_settings import COMMAND_DRAIN_IBKR_CONNECTED_KEY, get_setting

    await drain_once(None, drain_env.bot, "chat")
    assert get_setting(COMMAND_DRAIN_IBKR_CONNECTED_KEY, "") == "false"


@pytest.mark.asyncio
async def test_ibkr_connected_is_true_when_ib_reports_connected(drain_env) -> None:
    from unittest.mock import MagicMock

    from src.notify.command_drain import drain_once
    from src.storage.system_settings import COMMAND_DRAIN_IBKR_CONNECTED_KEY, get_setting

    fake_ib = MagicMock()
    fake_ib.isConnected.return_value = True
    await drain_once(fake_ib, drain_env.bot, "chat")
    assert get_setting(COMMAND_DRAIN_IBKR_CONNECTED_KEY, "") == "true"


@pytest.mark.asyncio
async def test_ibkr_connected_is_false_when_ib_reports_disconnected(drain_env) -> None:
    from unittest.mock import MagicMock

    from src.notify.command_drain import drain_once
    from src.storage.system_settings import COMMAND_DRAIN_IBKR_CONNECTED_KEY, get_setting

    fake_ib = MagicMock()
    fake_ib.isConnected.return_value = False
    await drain_once(fake_ib, drain_env.bot, "chat")
    assert get_setting(COMMAND_DRAIN_IBKR_CONNECTED_KEY, "") == "false"
```

- [ ] **Step 3: Run the tests, verify they fail**

Run: `python -m pytest tests/test_command_drain.py -v -k ibkr_connected`
Expected: FAIL — each `get_setting(...)` call returns `""`, not `"true"`/`"false"`.

- [ ] **Step 4: Write the flag alongside the existing heartbeat**

In `src/notify/command_drain.py`, change the import on line 49 from:

```python
from src.storage.system_settings import set_setting
```

to:

```python
from src.storage.system_settings import COMMAND_DRAIN_IBKR_CONNECTED_KEY, set_setting
```

Then change the heartbeat-write block at the end of `drain_once` from:

```python
    set_setting(
        COMMAND_DRAIN_HEARTBEAT_KEY,
        datetime.now(UTC).isoformat(),
    )
    return processed
```

to:

```python
    set_setting(
        COMMAND_DRAIN_HEARTBEAT_KEY,
        datetime.now(UTC).isoformat(),
    )
    # IBKR-connected flag for the web status card's "IBKR connection" row (GET
    # /system/status) — written alongside the heartbeat, from the same `ib` this
    # drain cycle ran with, so a stale flag can never outlive a fresh heartbeat.
    set_setting(
        COMMAND_DRAIN_IBKR_CONNECTED_KEY,
        "true" if ib is not None and ib.isConnected() else "false",
    )
    return processed
```

- [ ] **Step 5: Run the tests, verify they pass**

Run: `python -m pytest tests/test_command_drain.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 6: Commit**

```bash
git add src/storage/system_settings.py src/notify/command_drain.py tests/test_command_drain.py
git commit -m "feat(approval_service): write an IBKR-connected flag alongside the drain heartbeat"
```

---

## Task 3: Extract the shared system_settings reader

**Files:**
- Create: `src/api/settings_read.py`
- Modify: `src/api/routers/options.py`
- Test: `tests/test_api_settings_read.py` (new)

**Interfaces:**
- Produces: `read_setting(db: TradingDb, key: str) -> str | None`, `parse_setting_dt(raw: str | None) -> datetime | None` (in `src.api.settings_read`, imported by Task 4's `system.py` and by `options.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_settings_read.py`:

```python
"""src/api/settings_read.py — the shared system_settings reader both /options/controls
and /system/status use."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.api.settings_read import parse_setting_dt, read_setting


@pytest.fixture
def trading_db_session(monkeypatch, tmp_path):
    import src.storage.db as dbmod
    from src.common.config import Config

    trading_db = tmp_path / "settings_read.db"
    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()

    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())

    from src.storage.models import SystemSettingRow

    with dbmod.session_scope() as s:
        s.add(SystemSettingRow(key="known_key", value="hello"))

    from src.api.trading_db import trading_session

    with trading_session() as session:
        yield session


def test_read_setting_returns_the_stored_value(trading_db_session) -> None:
    assert read_setting(trading_db_session, "known_key") == "hello"


def test_read_setting_returns_none_for_an_unknown_key(trading_db_session) -> None:
    assert read_setting(trading_db_session, "no_such_key") is None


def test_parse_setting_dt_returns_none_for_none() -> None:
    assert parse_setting_dt(None) is None


def test_parse_setting_dt_returns_none_for_empty_string() -> None:
    assert parse_setting_dt("") is None


def test_parse_setting_dt_returns_none_for_garbage() -> None:
    assert parse_setting_dt("not-a-date") is None


def test_parse_setting_dt_parses_an_iso_timestamp_as_utc() -> None:
    raw = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC).isoformat()
    parsed = parse_setting_dt(raw)
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.year == 2026
    assert parsed.month == 9
    assert parsed.day == 23
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `python -m pytest tests/test_api_settings_read.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.api.settings_read'`

- [ ] **Step 3: Implement the shared module**

Create `src/api/settings_read.py`:

```python
"""Shared read of a system_settings row through an injected DB session.

Used by GET /options/controls (the drain heartbeat) and GET /system/status (the drain
and monitor heartbeats) so the two routers read a setting the same way rather than each
keeping its own private copy.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from src.api.deps import TradingDb
from src.api.models.common import as_utc
from src.storage.models import SystemSettingRow


def read_setting(db: TradingDb, key: str) -> str | None:
    row = db.execute(
        select(SystemSettingRow.value).where(SystemSettingRow.key == key)
    ).scalar_one_or_none()
    return row if row is not None else None


def parse_setting_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        return as_utc(dt)
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 4: Run the new tests, verify they pass**

Run: `python -m pytest tests/test_api_settings_read.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Point `options.py` at the shared module**

In `src/api/routers/options.py`, delete the private helpers (currently just above
`@router.get("/controls", ...)`):

```python
def _read_setting(db: TradingDb, key: str) -> str | None:
    from src.storage.models import SystemSettingRow

    row = db.execute(
        select(SystemSettingRow.value).where(SystemSettingRow.key == key)
    ).scalar_one_or_none()
    return row if row is not None else None


def _parse_setting_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        return as_utc(dt)
    except (ValueError, TypeError):
        return None
```

Add the import near the top of the file, alongside the existing
`from src.api.deps import OwnerUser, TradingDb` line:

```python
from src.api.settings_read import parse_setting_dt, read_setting
```

Inside `controls()`, change:

```python
    drain_raw = _read_setting(db, _DRAIN_HEARTBEAT_KEY)
    drain_last_seen = _parse_setting_dt(drain_raw)
```

to:

```python
    drain_raw = read_setting(db, _DRAIN_HEARTBEAT_KEY)
    drain_last_seen = parse_setting_dt(drain_raw)
```

- [ ] **Step 6: Run the existing controls tests, verify no regression**

Run: `python -m pytest tests/test_api_controls.py -v`
Expected: PASS (all tests, unchanged behavior)

- [ ] **Step 7: Commit**

```bash
git add src/api/settings_read.py src/api/routers/options.py tests/test_api_settings_read.py
git commit -m "refactor(api): extract the system_settings reader shared by controls and system routers"
```

---

## Task 4: `GET /system/status`

**Files:**
- Create: `src/api/routers/system.py`
- Modify: `src/api/main.py`
- Test: `tests/test_api_system.py` (new)

**Interfaces:**
- Consumes: `read_setting`/`parse_setting_dt` (Task 3), `MONITOR_HEARTBEAT_KEY`/`MONITOR_IBKR_CONNECTED_KEY` (Task 1), `COMMAND_DRAIN_IBKR_CONNECTED_KEY` (Task 2), `OwnerUser`/`TradingDb`/`ResearchDb` (`src.api.deps`), `breaker_states()` (`src.data.breaker`), `read_heartbeat()` (`src.research.ingest.jobs`), `Envelope`/`as_utc_opt` (`src.api.models.common`).
- Produces: `router` (mounted at `/system`), `SystemRow`/`SystemStatusResponse` models, `_LOG_FILES: dict[str, Path]` (read by Task 5).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_system.py`:

```python
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
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `python -m pytest tests/test_api_system.py -v`
Expected: FAIL — every request 404s (`/system/status` doesn't exist yet).

- [ ] **Step 3: Implement the router**

Create `src/api/routers/system.py`:

```python
"""System status: per-subsystem health for the left-rail status card, plus a log tail
per daemon. Read-only, owner-only — the same sensitivity class as /options/controls,
since this surfaces internal operational detail (log lines, heartbeat ages) rather than
research data. See docs/superpowers/specs/2026-09-23-web-system-status-card-design.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter

from src.api.deps import OwnerUser, ResearchDb, TradingDb
from src.api.models.common import Envelope, as_utc_opt
from src.api.settings_read import parse_setting_dt, read_setting
from src.common.config import ROOT, get_config
from src.data.breaker import breaker_states
from src.research.ingest.jobs import read_heartbeat
from src.storage.system_settings import (
    COMMAND_DRAIN_IBKR_CONNECTED_KEY,
    MONITOR_HEARTBEAT_KEY,
    MONITOR_IBKR_CONNECTED_KEY,
)

router = APIRouter(prefix="/system", tags=["system"])

# See routers/options.py's own `_DRAIN_HEARTBEAT_KEY` — the API layer duplicates this one
# literal rather than importing the daemon module (src.notify.command_drain) that owns
# it, matching that existing precedent.
_DRAIN_HEARTBEAT_KEY = "command_drain_heartbeat"

State = Literal["ok", "degraded", "unknown", "down"]

# name -> real log file path (scripts/start.py's SERVICES dict). Fixed allowlist: a path
# is never built from the request. "api" is deliberately absent — no status row reads
# its own log (design doc §2).
_LOG_FILES: dict[str, Path] = {
    "approval": ROOT / "logs" / "approval.log",
    "monitor": ROOT / "logs" / "monitor.log",
    "research": ROOT / "logs" / "research.log",
}

_MAX_LOG_LINES = 150

# 2x the fastest research-worker job's cadence (drain_ingest_jobs, a 30s IntervalTrigger
# in src/research/ingest/jobs.py) — the same "2x cadence" staleness rule /options/
# controls applies to the drain heartbeat, hand-derived since that 30s interval is a
# literal in jobs.py, not a config value.
_RESEARCH_WORKER_MAX_AGE = timedelta(minutes=2)


class SystemRow(Envelope):
    key: str
    label: str
    state: State
    detail: str
    log_key: str | None = None


class SystemStatusResponse(Envelope):
    rows: list[SystemRow]


def _heartbeat_row(
    now: datetime,
    *,
    key: str,
    label: str,
    heartbeat: datetime | None,
    max_age: timedelta,
    log_key: str | None,
) -> SystemRow:
    if heartbeat is None:
        return SystemRow(
            as_of=now, key=key, label=label, state="unknown",
            detail="not yet reporting", log_key=log_key,
        )
    age = now - heartbeat
    if age <= max_age:
        return SystemRow(
            as_of=now, key=key, label=label, state="ok",
            detail=f"last heartbeat {int(age.total_seconds())}s ago", log_key=log_key,
        )
    return SystemRow(
        as_of=now, key=key, label=label, state="down",
        detail=f"last heartbeat {int(age.total_seconds())}s ago (stale)", log_key=log_key,
    )


def _worst(states: list[State]) -> State:
    rank = {"ok": 0, "degraded": 1, "unknown": 1, "down": 2}
    return max(states, key=lambda s: rank[s])


def _ibkr_leg(
    heartbeat: datetime | None, max_age: timedelta, connected_raw: str | None
) -> tuple[State, str]:
    if heartbeat is None:
        return "unknown", "not yet reporting"
    if datetime.now(UTC) - heartbeat > max_age:
        return "down", "heartbeat stale"
    if connected_raw == "true":
        return "ok", "connected"
    return "down", "disconnected"


@router.get("/status", response_model=SystemStatusResponse)
def system_status(
    _user: OwnerUser, trading_db: TradingDb, research_db: ResearchDb
) -> SystemStatusResponse:
    now = datetime.now(UTC)
    cfg = get_config()
    rows: list[SystemRow] = []

    try:
        trading_db.execute(sa.text("SELECT 1"))
        rows.append(
            SystemRow(as_of=now, key="trading_db", label="Trading DB", state="ok",
                       detail="reachable", log_key=None)
        )
    except Exception:
        rows.append(
            SystemRow(as_of=now, key="trading_db", label="Trading DB", state="down",
                       detail="unreachable", log_key=None)
        )

    try:
        research_db.execute(sa.text("SELECT 1"))
        rows.append(
            SystemRow(as_of=now, key="research_db", label="Research DB", state="ok",
                       detail="reachable", log_key=None)
        )
    except Exception:
        rows.append(
            SystemRow(as_of=now, key="research_db", label="Research DB", state="down",
                       detail="unreachable", log_key=None)
        )

    providers = breaker_states()
    provider_states: list[State] = []
    open_names: list[str] = []
    half_open_names: list[str] = []
    for name, state in providers.items():
        if state == "open":
            provider_states.append("down")
            open_names.append(name)
        elif state == "half_open":
            provider_states.append("degraded")
            half_open_names.append(name)
        else:
            provider_states.append("ok")
    if not provider_states:
        rows.append(
            SystemRow(as_of=now, key="data_providers", label="Data providers", state="ok",
                       detail="no providers registered", log_key=None)
        )
    else:
        worst = _worst(provider_states)
        if worst == "ok":
            detail = "no breakers tripped"
        elif open_names and half_open_names:
            detail = f"{', '.join(open_names)} open, {', '.join(half_open_names)} recovering"
        elif open_names:
            detail = f"{', '.join(open_names)} open"
        else:
            detail = f"{', '.join(half_open_names)} recovering"
        rows.append(
            SystemRow(as_of=now, key="data_providers", label="Data providers", state=worst,
                       detail=detail, log_key=None)
        )

    drain_hb = parse_setting_dt(read_setting(trading_db, _DRAIN_HEARTBEAT_KEY))
    drain_max_age = timedelta(seconds=cfg.execution.poll_interval_seconds * 2)
    rows.append(
        _heartbeat_row(now, key="command_drain", label="Command drain (approval_service)",
                        heartbeat=drain_hb, max_age=drain_max_age, log_key="approval")
    )

    monitor_hb = parse_setting_dt(read_setting(trading_db, MONITOR_HEARTBEAT_KEY))
    monitor_max_age = timedelta(seconds=cfg.scheduler.intraday_poll_seconds * 2)
    rows.append(
        _heartbeat_row(now, key="intraday_monitor", label="Intraday monitor",
                        heartbeat=monitor_hb, max_age=monitor_max_age, log_key="monitor")
    )

    worker_hb = as_utc_opt(read_heartbeat())
    rows.append(
        _heartbeat_row(now, key="research_worker", label="Research worker",
                        heartbeat=worker_hb, max_age=_RESEARCH_WORKER_MAX_AGE,
                        log_key="research")
    )

    drain_connected_raw = read_setting(trading_db, COMMAND_DRAIN_IBKR_CONNECTED_KEY)
    monitor_connected_raw = read_setting(trading_db, MONITOR_IBKR_CONNECTED_KEY)
    drain_leg_state, drain_leg_detail = _ibkr_leg(drain_hb, drain_max_age, drain_connected_raw)
    monitor_leg_state, monitor_leg_detail = _ibkr_leg(
        monitor_hb, monitor_max_age, monitor_connected_raw
    )
    rows.append(
        SystemRow(
            as_of=now,
            key="ibkr_connection",
            label="IBKR connection",
            state=_worst([drain_leg_state, monitor_leg_state]),
            detail=(
                f"approval_service: {drain_leg_detail}; "
                f"intraday_monitor: {monitor_leg_detail}"
            ),
            log_key=None,
        )
    )

    return SystemStatusResponse(as_of=now, rows=rows)
```

- [ ] **Step 4: Register the router**

In `src/api/main.py`, add `system` to the import:

```python
from src.api.routers import (
    commands,
    meta,
    options,
    pnl,
    portfolio,
    research,
    system,
    universe,
    watchlist,
)
```

And mount it, directly after `app.include_router(options.router)`:

```python
    app.include_router(system.router)
```

- [ ] **Step 5: Run the tests, verify they pass**

Run: `python -m pytest tests/test_api_system.py -v`
Expected: PASS (15 tests)

- [ ] **Step 6: Commit**

```bash
git add src/api/routers/system.py src/api/main.py tests/test_api_system.py
git commit -m "feat(api): add GET /system/status aggregating 7 subsystem health signals"
```

---

## Task 5: `GET /system/{name}/log`

**Files:**
- Modify: `src/api/routers/system.py`
- Test: `tests/test_api_system.py` (append)

**Interfaces:**
- Consumes: `_LOG_FILES` (Task 4, same file).
- Produces: nothing new consumed elsewhere — this is the log-tail read surface the frontend calls directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_system.py`:

```python
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
    assert r.json()["lines"] == []


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
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `python -m pytest tests/test_api_system.py -v -k log`
Expected: FAIL — 404 on every request (`GET /system/{name}/log` doesn't exist yet).

- [ ] **Step 3: Implement the endpoint**

In `src/api/routers/system.py`, add to the imports:

```python
import re

from fastapi import APIRouter, HTTPException, Query
```

(replacing the existing `from fastapi import APIRouter` line with the one above).

Add, near the other module-level constants:

```python
# Matches src/common/logging.py's plain file formatter:
# "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s". \s* around the level name
# tolerates the -8s left-justify padding without hardcoding an exact width.
_LEVEL_PATTERN: dict[str, re.Pattern[str]] = {
    "warn": re.compile(r"\|\s*(WARNING|ERROR|CRITICAL)\s*\|"),
    "info": re.compile(r"\|\s*(INFO|WARNING|ERROR|CRITICAL)\s*\|"),
}
```

Add the response model, beside `SystemStatusResponse`:

```python
class SystemLogResponse(Envelope):
    name: str
    level: Literal["warn", "info"]
    lines: list[str]
```

Add the route, after `system_status`:

```python
@router.get("/{name}/log", response_model=SystemLogResponse)
def system_log(
    name: str,
    _user: OwnerUser,
    level: Literal["warn", "info"] = Query("warn"),
    lines: int = Query(100, ge=1, le=_MAX_LOG_LINES),
) -> SystemLogResponse:
    now = datetime.now(UTC)
    path = _LOG_FILES.get(name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown system {name!r}")
    if not path.exists():
        return SystemLogResponse(as_of=now, name=name, level=level, lines=[])

    pattern = _LEVEL_PATTERN[level]
    matched: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if pattern.search(line):
                matched.append(line.rstrip("\n"))
    return SystemLogResponse(as_of=now, name=name, level=level, lines=matched[-lines:])
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `python -m pytest tests/test_api_system.py -v`
Expected: PASS (21 tests)

- [ ] **Step 5: Run the full backend quality gate**

Run: `python -m pytest -q && ruff check . && mypy src`
Expected: all green — this is the last backend task, so this is the point to catch any
cross-task regression before moving to the frontend.

- [ ] **Step 6: Commit**

```bash
git add src/api/routers/system.py tests/test_api_system.py
git commit -m "feat(api): add GET /system/{name}/log, a level-filtered tail per daemon"
```

---

## Task 6: `SystemStatusCard` + Rail layout

**Files:**
- Create: `web/components/shell/SystemStatusCard.tsx`
- Modify: `web/components/shell/Rail.tsx`
- Test: `web/components/shell/SystemStatusCard.test.tsx` (new)

**Interfaces:**
- Consumes: `apiFetch` (`@/lib/api`), `renderWithQuery`/`apiFetchMock` (`@/lib/test-query`, test only).
- Produces: `export type SystemState = "ok" | "degraded" | "unknown" | "down"`, `export type SystemRow = { key, label, state, detail, log_key }` (consumed by Task 7's `SystemLogPanel`), `export function SystemStatusCard()`.

- [ ] **Step 1: Write the failing tests**

Create `web/components/shell/SystemStatusCard.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { SystemStatusCard } from "./SystemStatusCard";

const ISO = new Date().toISOString();

function statusResponse(rows: Array<Record<string, unknown>>) {
  return { as_of: ISO, rows };
}

describe("SystemStatusCard", () => {
  it("renders one row per system with its label", async () => {
    renderWithQuery(<SystemStatusCard />, {
      "/system/status": statusResponse([
        {
          key: "trading_db",
          label: "Trading DB",
          state: "ok",
          detail: "reachable",
          log_key: null,
        },
        {
          key: "command_drain",
          label: "Command drain (approval_service)",
          state: "unknown",
          detail: "not yet reporting",
          log_key: "approval",
        },
      ]),
    });
    expect(await screen.findByText("Trading DB")).toBeDefined();
    expect(screen.getByText("Command drain (approval_service)")).toBeDefined();
  });

  it("renders an ok row's dot with the ok state", async () => {
    renderWithQuery(<SystemStatusCard />, {
      "/system/status": statusResponse([
        { key: "trading_db", label: "Trading DB", state: "ok", detail: "reachable", log_key: null },
      ]),
    });
    const dot = await screen.findByTestId("status-dot");
    expect(dot.getAttribute("data-state")).toBe("ok");
  });

  it("renders a down row's dot distinctly from ok", async () => {
    renderWithQuery(<SystemStatusCard />, {
      "/system/status": statusResponse([
        {
          key: "research_db",
          label: "Research DB",
          state: "down",
          detail: "unreachable",
          log_key: null,
        },
      ]),
    });
    const dot = await screen.findByTestId("status-dot");
    expect(dot.getAttribute("data-state")).toBe("down");
  });

  it("disables a row with no log_key", async () => {
    renderWithQuery(<SystemStatusCard />, {
      "/system/status": statusResponse([
        { key: "trading_db", label: "Trading DB", state: "ok", detail: "reachable", log_key: null },
      ]),
    });
    const button = await screen.findByRole("button", { name: /trading db/i });
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("renders a degraded fallback line when the fetch fails", async () => {
    renderWithQuery(<SystemStatusCard />, {});
    expect(await screen.findByText("Status unavailable")).toBeDefined();
  });
});
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `cd web && npm run test -- SystemStatusCard`
Expected: FAIL — `Cannot find module './SystemStatusCard'`

- [ ] **Step 3: Implement `SystemStatusCard`**

Create `web/components/shell/SystemStatusCard.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import clsx from "clsx";
import { apiFetch } from "@/lib/api";
import { SystemLogPanel } from "./SystemLogPanel";

export type SystemState = "ok" | "degraded" | "unknown" | "down";

export type SystemRow = {
  key: string;
  label: string;
  state: SystemState;
  detail: string;
  log_key: string | null;
};

type SystemStatusResponse = { as_of: string; rows: SystemRow[] };

function dotClass(state: SystemState): string {
  switch (state) {
    case "ok":
      return "bg-gain";
    case "down":
      return "border border-loss";
    case "degraded":
    case "unknown":
      return "hatch";
  }
}

export function SystemStatusCard() {
  const [openRow, setOpenRow] = useState<SystemRow | null>(null);
  const { data, isError } = useQuery({
    queryKey: ["system", "status"],
    queryFn: () => apiFetch<SystemStatusResponse>("/system/status"),
    refetchInterval: 20_000,
  });

  return (
    <div className="border-t border-border px-3 py-3">
      <div className="mb-2 font-mono text-xs text-muted">System status</div>
      {isError ? (
        <p className="text-xs text-unknown">Status unavailable</p>
      ) : (
        <ul className="space-y-1.5">
          {(data?.rows ?? []).map((row) => (
            <li key={row.key}>
              <button
                type="button"
                disabled={row.log_key === null}
                onClick={() => setOpenRow(row)}
                className="flex w-full items-center gap-2 rounded-sm px-1 py-0.5 text-left enabled:hover:bg-surface disabled:cursor-default"
              >
                <span
                  data-testid="status-dot"
                  data-state={row.state}
                  className={clsx("h-2 w-2 shrink-0 rounded-full", dotClass(row.state))}
                />
                <span className="flex-1 truncate text-xs text-content">{row.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {openRow && <SystemLogPanel row={openRow} onClose={() => setOpenRow(null)} />}
    </div>
  );
}
```

This imports `SystemLogPanel`, built in Task 7 — until then, add a placeholder so this
file compiles:

Create `web/components/shell/SystemLogPanel.tsx` (temporary — Task 7 replaces this body):

```tsx
"use client";

import type { SystemRow } from "./SystemStatusCard";

export function SystemLogPanel(_props: { row: SystemRow; onClose: () => void }) {
  return null;
}
```

- [ ] **Step 4: Wire the card into `Rail`**

Replace `web/components/shell/Rail.tsx` with:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { RailSection } from "./RailSection";
import { SystemStatusCard } from "./SystemStatusCard";

type NavSection = {
  key: string;
  label: string;
  available: boolean;
  note: string | null;
};

type NavResponse = { as_of: string; sections: NavSection[] };

export function Rail() {
  const { data } = useQuery({
    queryKey: ["nav"],
    queryFn: () => apiFetch<NavResponse>("/nav"),
    staleTime: 5 * 60 * 1000,
  });

  return (
    <nav className="flex w-[260px] shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex-1 overflow-y-auto px-3 py-4">
        <div className="px-3 pb-6 font-mono text-sm text-muted">Research</div>
        <ul className="space-y-1">
          {(data?.sections ?? []).map((s) => (
            <RailSection
              key={s.key}
              sectionKey={s.key}
              label={s.label}
              available={s.available}
              note={s.note}
            />
          ))}
        </ul>
      </div>
      <SystemStatusCard />
    </nav>
  );
}
```

(The nav list's own `overflow-y-auto` moves from the `<nav>` element itself onto this
inner wrapper div, so the status card below it — a sibling, not a scrolled child — stays
pinned to the bottom of the rail regardless of nav-list length or scroll position.)

- [ ] **Step 5: Run the tests, verify they pass**

Run: `cd web && npm run test -- SystemStatusCard`
Expected: PASS (5 tests)

- [ ] **Step 6: Run the full frontend test suite, verify no regression**

Run: `cd web && npm run test && npm run lint`
Expected: all green — `RailSection.test.tsx` is unaffected (it tests `RailSection`
directly, not `Rail`).

- [ ] **Step 7: Commit**

```bash
cd web && git add components/shell/SystemStatusCard.tsx components/shell/SystemStatusCard.test.tsx components/shell/SystemLogPanel.tsx components/shell/Rail.tsx
git commit -m "feat(web): add the left-rail system status card"
```

---

## Task 7: `SystemLogPanel`

**Files:**
- Modify: `web/components/shell/SystemLogPanel.tsx` (replace Task 6's placeholder)
- Test: `web/components/shell/SystemLogPanel.test.tsx` (new)

**Interfaces:**
- Consumes: `SystemRow` (Task 6, same directory), `apiFetch` (`@/lib/api`).
- Produces: `export function SystemLogPanel({ row, onClose })`.

- [ ] **Step 1: Write the failing tests**

Create `web/components/shell/SystemLogPanel.test.tsx`:

```tsx
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { SystemLogPanel } from "./SystemLogPanel";
import type { SystemRow } from "./SystemStatusCard";

const ISO = new Date().toISOString();

const row: SystemRow = {
  key: "command_drain",
  label: "Command drain (approval_service)",
  state: "ok",
  detail: "last heartbeat 4s ago",
  log_key: "approval",
};

function logResponse(lines: string[], level: "warn" | "info" = "warn") {
  return { as_of: ISO, name: "approval", level, lines };
}

describe("SystemLogPanel", () => {
  it("fetches and renders the tailed log lines on open", async () => {
    renderWithQuery(<SystemLogPanel row={row} onClose={() => {}} />, {
      "/system/approval/log?level=warn": logResponse(["2026-09-23 | WARNING | x | boom"]),
    });
    expect(await screen.findByText(/boom/)).toBeDefined();
  });

  it("shows the empty-log message when the file has no matching lines", async () => {
    renderWithQuery(<SystemLogPanel row={row} onClose={() => {}} />, {
      "/system/approval/log?level=warn": logResponse([]),
    });
    expect(await screen.findByText("No log file yet")).toBeDefined();
  });

  it("switching to Info+ refetches at the info level", async () => {
    renderWithQuery(<SystemLogPanel row={row} onClose={() => {}} />, {
      "/system/approval/log?level=warn": logResponse(["only a warning line"]),
      "/system/approval/log?level=info": logResponse(["an info line", "a warning line"]),
    });
    await screen.findByText("only a warning line");
    fireEvent.click(screen.getByRole("button", { name: /info\+/i }));
    expect(await screen.findByText(/an info line/)).toBeDefined();
  });

  it("Escape calls onClose", async () => {
    let closed = false;
    renderWithQuery(<SystemLogPanel row={row} onClose={() => (closed = true)} />, {
      "/system/approval/log?level=warn": logResponse([]),
    });
    await screen.findByText("No log file yet");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(closed).toBe(true));
  });

  it("the Close button calls onClose", async () => {
    let closed = false;
    renderWithQuery(<SystemLogPanel row={row} onClose={() => (closed = true)} />, {
      "/system/approval/log?level=warn": logResponse([]),
    });
    await screen.findByText("No log file yet");
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(closed).toBe(true);
  });
});
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `cd web && npm run test -- SystemLogPanel`
Expected: FAIL — Task 6's placeholder renders `null`, so every text/role query finds
nothing.

- [ ] **Step 3: Implement `SystemLogPanel`**

Replace `web/components/shell/SystemLogPanel.tsx`:

```tsx
"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { apiFetch } from "@/lib/api";
import type { SystemRow } from "./SystemStatusCard";

type LogLevel = "warn" | "info";

type SystemLogResponse = {
  as_of: string;
  name: string;
  level: LogLevel;
  lines: string[];
};

export function SystemLogPanel({ row, onClose }: { row: SystemRow; onClose: () => void }) {
  const [level, setLevel] = useState<LogLevel>("warn");
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<Element | null>(null);
  const headingId = useId();

  const { data, isFetching, refetch } = useQuery({
    queryKey: ["system", "log", row.log_key, level],
    queryFn: () => apiFetch<SystemLogResponse>(`/system/${row.log_key}/log?level=${level}`),
    enabled: row.log_key !== null,
  });

  useEffect(() => {
    triggerRef.current = document.activeElement;
    closeRef.current?.focus();
    return () => {
      const trigger = triggerRef.current;
      if (trigger instanceof HTMLElement) trigger.focus();
    };
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusables = panel.querySelectorAll<HTMLElement>(
        "button:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={headingId}
      data-testid="system-log-panel"
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-surface p-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id={headingId} className="text-sm text-content">
          {row.label}
        </h2>
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          className="rounded-sm border border-border bg-background px-2 py-1 text-xs text-content hover:bg-elevated focus-visible:ring-focus"
        >
          Close
        </button>
      </div>
      <p className="mt-1 text-xs text-muted">{row.detail}</p>

      <div className="mt-3 flex items-center gap-2">
        <div className="flex gap-1" role="group" aria-label="Log level">
          {(["warn", "info"] as const).map((lvl) => (
            <button
              key={lvl}
              type="button"
              aria-pressed={level === lvl}
              onClick={() => setLevel(lvl)}
              className={clsx(
                "rounded-sm border px-2 py-1 text-xs",
                level === lvl
                  ? "border-focus text-content"
                  : "border-border text-muted hover:bg-elevated",
              )}
            >
              {lvl === "warn" ? "Warnings+" : "Info+"}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="rounded-sm border border-border bg-background px-2 py-1 text-xs text-content enabled:hover:bg-elevated disabled:opacity-50"
        >
          Refresh
        </button>
      </div>

      <div className="mt-3 flex-1 overflow-y-auto rounded-sm border border-border bg-background p-2">
        {data === undefined ? (
          <p className="text-xs text-muted">Loading…</p>
        ) : data.lines.length === 0 ? (
          <p className="text-xs text-muted">No log file yet</p>
        ) : (
          <pre className="whitespace-pre-wrap font-mono text-xs text-content">
            {data.lines.join("\n")}
          </pre>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `cd web && npm run test -- SystemLogPanel`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full frontend quality gate**

Run: `cd web && npm run test && npm run lint && npm run build`
Expected: all green — `npm run build` catches any TypeScript error the test runner's
transpile-only path wouldn't.

- [ ] **Step 6: Commit**

```bash
cd web && git add components/shell/SystemLogPanel.tsx components/shell/SystemLogPanel.test.tsx
git commit -m "feat(web): add the per-system log slide-over panel"
```

---

## Task 8: Docs

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `web/CLAUDE.md`

**Interfaces:** none — documentation only.

- [ ] **Step 1: `README.md`**

In the layout table, find the `src/api/` row (the one ending "...unit-suffixed headers
with `None` as an empty cell, never `0`") and append, before the closing `|`:

```
; `routers/system.py` (the left-rail status card's backend) is `GET /system/status`
(7 subsystem health rows: both databases, data providers, the command drain, the
intraday monitor, the research worker, and the aggregate IBKR connection) plus
`GET /system/{name}/log` (a level-filtered log tail per daemon, capped at 150 lines,
`name` validated against a fixed allowlist)
```

- [ ] **Step 2: `ARCHITECTURE.md` — the `src/api/` table**

In the table under `### \`src/api/\` — The FastAPI web layer`, add two new rows,
directly after the `models/portfolio.py` row and before the `main.py` row:

```
| `settings_read.py` | `read_setting(db, key) -> str \| None` / `parse_setting_dt(raw) -> datetime \| None` — the system_settings-row reader shared by `routers/options.py`'s `drain_healthy` and `routers/system.py`'s heartbeat rows, extracted so the two routers can't drift on how a setting is read or parsed. |
| `routers/system.py` | **The left-rail status card's backend.** `GET /system/status` (owner-only) returns 7 rows — Trading DB / Research DB (a live `SELECT 1` each), Data providers (`src.data.breaker.breaker_states()`, rolled up to the worst state), Command drain / Intraday monitor / Research worker (each a heartbeat-age check — `ok` within 2x that process's own poll interval, `down` if stale, `unknown` if the heartbeat has never been written this run — never a false "down" on a cold start), and IBKR connection (an aggregate of the two `_ibkr_connected` flags `intraday.py` and `command_drain.py` now write alongside their heartbeats, `down` if either daemon disagrees or its heartbeat is stale). No row for `web_api` itself (a failed fetch of this very endpoint *is* that signal) or `eod_report` (a daily batch job, not a thing that's "up" at a point in time). `GET /system/{name}/log` tails that daemon's log file (`name` through a fixed allowlist — `approval`/`monitor`/`research`, mapped to the real paths in `scripts/start.py`'s `SERVICES` dict, never built from the request), filtered server-side to WARNING+ by default (`level=info` widens to INFO+), capped at 150 lines. |
```

Then update the `main.py` row (replace the parenthetical listing the router mounts) to
end with:

```
; P3-P4 M5 adds `routers/pnl.py` under the `/pnl` prefix; this plan adds
`routers/system.py`)
```

- [ ] **Step 3: `ARCHITECTURE.md` — the `command_drain.py` row**

Append one sentence to the end of the `command_drain.py` row (after "...`result` carries
`captured_at`/`positions`/`snapshot_id` so the receipt says what was actually
captured."):

```
**This plan adds one more write to the end of every drain cycle:** an
`ibkr_connected` flag (`command_drain_ibkr_connected`), alongside the existing
heartbeat, from the same `ib` the cycle just ran with — read by `routers/system.py`'s
"IBKR connection" row.
```

- [ ] **Step 4: `ARCHITECTURE.md` — the `intraday.py` row**

Append one sentence to the end of the `intraday.py` row (after "...The account fetch is
awaited with `asyncio.wait_for` at the connection timeout so a hung `accountSummaryAsync`
can't stall the refresh loop."):

```
**This plan adds a heartbeat write** (`_write_heartbeat`, called at the end of
`_refresh_subscriptions` alongside the snapshot write) recording `monitor_heartbeat` and
an `ibkr_connected` flag every cycle, connected or not — read by `routers/system.py`'s
"Intraday monitor" and "IBKR connection" rows.
```

- [ ] **Step 5: `ARCHITECTURE.md` — the `system_settings.py` row**

Append one clause to the end of the `system_settings.py` row (after "...All persist
across restarts."):

```
**This plan adds three more keys**, all read by `routers/system.py`:
`monitor_heartbeat` / `monitor_ibkr_connected` (written by `intraday.py`) and
`command_drain_ibkr_connected` (written by `command_drain.py`, alongside its existing
`command_drain_heartbeat`).
```

- [ ] **Step 6: `web/CLAUDE.md`**

In the `Layout` section's `layout.tsx` bullet, the existing note already documents Rail
staying pinned; extend it with one clause (after "...the left rail stays pinned in place
(2026-09-23)"):

```
, and `Rail.tsx` (2026-09-23) is itself now `flex flex-col`: the nav list keeps its own
`overflow-y-auto` inside a `flex-1` wrapper, with `<SystemStatusCard/>` below it as a
sibling, outside the scroll area, so the status card stays visible regardless of nav-list
length
```

In the `components/` `shell/` bullet (currently just "Rail, RailSection"), replace it
with:

```
shell/            Rail, RailSection, SystemStatusCard (react-query on GET /system/status,
                    `refetchInterval` 20s; renders one row per system with a state dot -
                    `bg-gain` for ok, a `border-loss` outline for down, `.hatch` texture
                    for both degraded and unknown, per this app's tri-tone rule; a row
                    with `log_key: null` is not clickable; a failed fetch renders one
                    `text-unknown` line, "Status unavailable", instead of the row list),
                    SystemLogPanel (the per-row slide-over: focus-trapped `role="dialog"`
                    matching `ConfirmAction`'s pattern, fetches `GET /system/{log_key}/log`
                    on open only - no auto-poll inside it - with a Warnings+/Info+ toggle
                    and a manual Refresh button; an empty tail renders "No log file yet")
```

- [ ] **Step 7: Run the full quality gate one last time**

Run:

```bash
python -m pytest -q
ruff check .
mypy src
cd web && npm run test && npm run lint && npm run build
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add README.md ARCHITECTURE.md web/CLAUDE.md
git commit -m "docs: document the system status card (README, ARCHITECTURE, web/CLAUDE)"
```
