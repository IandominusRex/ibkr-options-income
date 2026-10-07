"""Intraday-loop wiring for the automatic Gateway restart on an Error 10197 block.

The restart mechanics themselves are covered in tests/test_gateway_control.py; this checks
that the loop calls them only for 10197, reports the outcome, and skips the scan-socket
reconnect once a restart has already dropped every socket.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.ibkr.market_data import ProbeHealth
from src.ops.gateway_control import RestartOutcome


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _blocked_texts(bot: AsyncMock) -> list[str]:
    return [
        c.kwargs["text"]
        for c in bot.send_message.call_args_list
        if "Scan blocked" in c.kwargs.get("text", "")
    ]


async def _run_one_blocked_cycle(probe: ProbeHealth, restart_result: tuple[str, bool]):
    """Drive _intraday_scan_loop until the first blocked cycle's notice is sent."""
    import src.notify.approval_service as approval_service

    ib_scan = MagicMock()
    ib_scan.isConnected.return_value = True
    bot = AsyncMock()
    app = SimpleNamespace(bot=bot, bot_data={})
    restart = AsyncMock(return_value=restart_result)
    reconnect = AsyncMock()

    with (
        patch.object(approval_service, "is_rth", return_value=True),
        patch.object(approval_service, "is_halted", return_value=False),
        patch.object(approval_service, "is_new_entry_window", return_value=True),
        patch.object(approval_service, "seconds_until_next_aligned_mark", return_value=0.01),
        patch.object(approval_service, "_check_profit_takes", AsyncMock()),
        patch.object(approval_service, "_check_loss_exits", AsyncMock()),
        patch.object(approval_service, "_update_pending_order_notifications", AsyncMock()),
        patch.object(approval_service, "_restart_gateway_for_competing_session", restart),
        patch.object(approval_service, "_force_scan_reconnect", reconnect),
        patch("src.ibkr.market_data.probe_market_data_health", AsyncMock(return_value=probe)),
    ):
        task = asyncio.create_task(approval_service._intraday_scan_loop(app, ib_scan, None, "1"))
        try:
            for _ in range(200):
                if _blocked_texts(bot):
                    break
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    texts = _blocked_texts(bot)
    assert texts, "loop never sent a scan-blocked notice"
    text = texts[0]
    return restart, reconnect, text


def _probe(codes: list[int]) -> ProbeHealth:
    return ProbeHealth(
        healthy=False,
        diagnosis="blocked",
        action_hint="do something",
        error_codes=codes,
        probe_symbol="SPY",
        probe_timeout=15.0,
    )


async def test_10197_block_restarts_gateway_and_skips_socket_reconnect(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    restart, reconnect, text = await _run_one_blocked_cycle(
        _probe([10197]), ("Restarted IB Gateway with a fresh login (attempt 1/3 today).", True)
    )
    restart.assert_awaited()
    reconnect.assert_not_awaited()
    assert "Restarted IB Gateway" in text
    assert "Forcing a reconnect" not in text


async def test_10197_block_without_a_restart_still_reconnects(tmp_path, monkeypatch):
    """Cooldown / daily cap / agent not loaded: nothing dropped the socket, so reconnect."""
    _db_setup(tmp_path, monkeypatch)
    restart, reconnect, text = await _run_one_blocked_cycle(
        _probe([10197]), ("Gateway was restarted 5 min ago; holding off.", False)
    )
    restart.assert_awaited()
    reconnect.assert_awaited()
    assert "holding off" in text


async def test_non_10197_block_keeps_the_old_reconnect(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    restart, reconnect, text = await _run_one_blocked_cycle(_probe([1100]), ("unused", True))
    restart.assert_not_awaited()
    reconnect.assert_awaited()
    assert "Forcing a reconnect" in text


async def test_helper_reuses_one_restarter_across_cycles():
    """Cooldown/daily-cap state must survive between cycles, so one instance in bot_data."""
    from src.notify.approval_service import _restart_gateway_for_competing_session

    restarter = MagicMock()
    restarter.restart.return_value = RestartOutcome(True, True, "Restarted.", 1)
    bot_data: dict = {"gateway_restarter": restarter}
    assert await _restart_gateway_for_competing_session(bot_data) == ("Restarted.", True)
    assert await _restart_gateway_for_competing_session(bot_data) == ("Restarted.", True)
    assert restarter.restart.call_count == 2
    assert bot_data["gateway_restarter"] is restarter


async def test_helper_never_raises():
    from src.notify.approval_service import _restart_gateway_for_competing_session

    restarter = MagicMock()
    restarter.restart.side_effect = RuntimeError("launchctl exploded")
    msg, attempted = await _restart_gateway_for_competing_session({"gateway_restarter": restarter})
    assert attempted is False
    assert "failed unexpectedly" in msg
