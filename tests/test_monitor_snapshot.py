"""The monitor may write portfolio snapshots. It may never let that interrupt its real job.

`_maybe_write_snapshot` (P3-P4 M1 Task 1.3) is called from `_refresh_subscriptions` with the
positions that pass already fetched — no second `get_positions` round-trip. The monitor's
real job is `_on_pending_tickers` → `check_all` → roll/assignment alerts; a snapshot write is
strictly secondary, so every failure path must log and return. A `RuntimeError` escaping into
`_refresh_loop` kills the refresh task, and a dead refresh task means the monitor stops
subscribing to new positions — roll alerts then silently stop firing for anything opened
after that moment. That is the single most dangerous failure in the milestone, and it has its
own test here.

Fixture follows tests/test_monitor.py's `_make_monitor` (a real `IntradayMonitor` around a
MagicMock IB) rather than building a second harness.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.schemas import AccountSnapshot


def _make_monitor_env() -> Any:
    """(monitor, mock_ib) — mirrors tests/test_monitor.py::_make_monitor, plus the keys
    _maybe_write_snapshot reads (market_data.portfolio_snapshot_interval_minutes,
    secrets.ibkr_account)."""
    mock_ib = MagicMock()
    mock_ib.tickers.return_value = []
    mock_ib.portfolio.return_value = []
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


@pytest.fixture()
def monitor_env():
    monitor, mock_ib = _make_monitor_env()
    yield monitor
    monitor._executor.shutdown(wait=False)


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123",
        net_liquidation=100_000.0,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=5_000.0,
        excess_liquidity=75_000.0,
    )


def _patch_account_fetch() -> AsyncMock:
    """Patch get_account_snapshot_async at the monitor module's import site."""
    return AsyncMock(return_value=_account())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_snapshot_is_written_during_rth_after_the_interval(monitor_env) -> None:
    with (
        patch("src.monitor.intraday.is_rth", return_value=True),
        patch(
            "src.monitor.intraday.latest_capture_time",
            return_value=datetime.now(UTC) - timedelta(minutes=20),
        ),
        patch("src.monitor.intraday.get_account_snapshot_async", new=_patch_account_fetch()),
        patch("src.monitor.intraday.get_positions", return_value=[]),
        patch("src.monitor.intraday.save_portfolio_snapshot") as save,
    ):
        await monitor_env._refresh_subscriptions()
    save.assert_called_once()
    assert save.call_args.kwargs["source"] == "monitor"


@pytest.mark.asyncio
async def test_nothing_is_written_outside_rth(monitor_env) -> None:
    with (
        patch("src.monitor.intraday.is_rth", return_value=False),
        patch("src.monitor.intraday.get_positions", return_value=[]),
        patch("src.monitor.intraday.save_portfolio_snapshot") as save,
    ):
        await monitor_env._refresh_subscriptions()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_nothing_is_written_inside_the_interval(monitor_env) -> None:
    with (
        patch("src.monitor.intraday.is_rth", return_value=True),
        patch(
            "src.monitor.intraday.latest_capture_time",
            return_value=datetime.now(UTC) - timedelta(minutes=2),
        ),
        patch("src.monitor.intraday.get_positions", return_value=[]),
        patch("src.monitor.intraday.save_portfolio_snapshot") as save,
    ):
        await monitor_env._refresh_subscriptions()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_a_failing_snapshot_write_never_reaches_the_refresh_loop(monitor_env) -> None:
    """If this escapes, the refresh task dies and roll alerts stop for new positions."""
    from src.common.schemas import OptionRight, PositionSnapshot

    mock_ib = monitor_env._ib
    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.50,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date.today() + timedelta(days=30),
        underlying="AAPL",
    )
    with (
        patch("src.monitor.intraday.is_rth", return_value=True),
        patch("src.monitor.intraday.latest_capture_time", return_value=None),
        patch("src.monitor.intraday.get_account_snapshot_async", new=_patch_account_fetch()),
        patch("src.monitor.intraday.get_positions", return_value=[pos]),
        patch("src.monitor.intraday._load_entry_iv", return_value=None),
        patch("src.monitor.intraday.get_fundamental_stats", return_value=MagicMock()),
        patch("src.monitor.intraday.build_option", return_value=MagicMock()),
        patch(
            "src.monitor.intraday.save_portfolio_snapshot",
            side_effect=RuntimeError("database is locked"),
        ),
    ):
        await monitor_env._refresh_subscriptions()  # must not raise

    # The real work still happened, proven by the observable the existing monitor
    # tests use (tests/test_monitor.py's double-subscribe test asserts on the same
    # call): reqMktData fired for the new short option — the subscription pass ran
    # to completion despite the snapshot write raising underneath it.
    mock_ib.reqMktData.assert_called_once()


@pytest.mark.asyncio
async def test_a_failing_account_fetch_writes_nothing_and_does_not_raise(monitor_env) -> None:
    with (
        patch("src.monitor.intraday.is_rth", return_value=True),
        patch("src.monitor.intraday.latest_capture_time", return_value=None),
        patch(
            "src.monitor.intraday.get_account_snapshot_async",
            new=AsyncMock(side_effect=TimeoutError()),
        ),
        patch("src.monitor.intraday.get_positions", return_value=[]),
        patch("src.monitor.intraday.save_portfolio_snapshot") as save,
    ):
        await monitor_env._refresh_subscriptions()  # must not raise
    save.assert_not_called()


@pytest.mark.asyncio
async def test_positions_are_fetched_once_per_pass(monitor_env) -> None:
    with (
        patch("src.monitor.intraday.is_rth", return_value=True),
        patch("src.monitor.intraday.latest_capture_time", return_value=None),
        patch("src.monitor.intraday.get_account_snapshot_async", new=_patch_account_fetch()),
        patch("src.monitor.intraday.get_positions", return_value=[]) as get_pos,
        patch("src.monitor.intraday.save_portfolio_snapshot"),
    ):
        await monitor_env._refresh_subscriptions()
    assert get_pos.call_count == 1
