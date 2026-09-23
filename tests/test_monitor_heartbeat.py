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


@pytest.mark.asyncio
async def test_refresh_subscriptions_writes_the_heartbeat_even_when_get_positions_fails(
    monitor_env,
) -> None:
    """Final-review fix #3: a failing get_positions() used to hit an early `return`
    before `_write_heartbeat()`, so the status card's "Intraday monitor" row stayed
    stuck on "unknown" forever instead of ever going "down". The heartbeat write now
    lives in a `finally`, so it must still land even on this failure path."""
    monitor, mock_ib = monitor_env
    with (
        patch("src.monitor.intraday.get_positions", side_effect=RuntimeError("boom")),
        patch("src.monitor.intraday.is_rth", return_value=False),
    ):
        await monitor._refresh_subscriptions()
    assert get_setting(MONITOR_HEARTBEAT_KEY, "") != ""
    assert get_setting(MONITOR_IBKR_CONNECTED_KEY, "") == "true"
