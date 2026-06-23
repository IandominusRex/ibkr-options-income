"""Tests for AutoReconnect and account-summary helpers in src/ibkr/connection.py.

P1-09: _reconnecting flag set synchronously before create_task.
P1-10: max_reconnect_attempts stops the loop and logs CRITICAL.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import ib_async
import pytest

from src.ibkr.connection import (
    AutoReconnect,
    debounce_account_summary_on_reconnect,
    suppress_account_summary_on_reconnect,
)


def _make_ib(connected: bool = True) -> MagicMock:
    ib = MagicMock()
    ib.isConnected.return_value = connected
    ib.disconnectedEvent = MagicMock()
    ib.disconnectedEvent.__iadd__ = MagicMock(return_value=None)
    ib.disconnectedEvent.__isub__ = MagicMock(return_value=None)
    return ib


def _make_auto(
    ib, *, max_reconnect_attempts: int = 20, backoff_base: float = 0.01
) -> AutoReconnect:
    return AutoReconnect(
        ib,
        host="127.0.0.1",
        port=7497,
        client_id=14,
        backoff_base=backoff_base,
        max_reconnect_attempts=max_reconnect_attempts,
        label="test",
    )


# ---------------------------------------------------------------------------
# P1-09: _reconnecting flag set synchronously in _on_disconnect
# ---------------------------------------------------------------------------


def test_reconnecting_flag_set_before_task_creation() -> None:
    """_reconnecting must be True immediately after _on_disconnect fires —
    before the reconnect coroutine actually runs — so a second disconnected event
    cannot spawn a second concurrent reconnect loop."""
    ib = _make_ib(connected=False)
    auto = _make_auto(ib)

    loop = asyncio.new_event_loop()
    try:
        tasks_created = []

        def fake_create_task(coro):
            # Record that the flag was already True when create_task was called.
            tasks_created.append(auto._reconnecting)
            coro.close()  # avoid coroutine-never-awaited warning
            return MagicMock()

        loop.create_task = fake_create_task  # type: ignore[method-assign]

        with patch("asyncio.get_running_loop", return_value=loop):
            auto._on_disconnect()

        # Flag must have been True at task creation time.
        assert len(tasks_created) == 1
        assert tasks_created[0] is True
    finally:
        loop.close()


def test_second_disconnect_event_does_not_spawn_second_loop() -> None:
    """If _reconnecting is already True, a second _on_disconnect call must be a no-op."""
    ib = _make_ib(connected=False)
    auto = _make_auto(ib)
    auto._reconnecting = True  # simulate: reconnect loop already running

    loop = asyncio.new_event_loop()
    tasks_created = []

    def fake_create_task(coro):
        tasks_created.append(coro)
        return MagicMock()

    loop.create_task = fake_create_task  # type: ignore[method-assign]
    try:
        with patch("asyncio.get_running_loop", return_value=loop):
            auto._on_disconnect()
        assert tasks_created == []  # no new task created
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# P1-10: max reconnect attempts
# ---------------------------------------------------------------------------


async def test_reconnect_loop_stops_after_max_attempts() -> None:
    """After max_reconnect_attempts failures, the loop exits and logs CRITICAL."""
    ib = _make_ib(connected=False)
    auto = _make_auto(ib, max_reconnect_attempts=3, backoff_base=0.001)
    auto._reconnecting = True  # mark as running (normally set by _on_disconnect)

    # connectAsync always fails.
    ib.connectAsync = AsyncMock(side_effect=ConnectionRefusedError("refused"))

    with patch.object(auto, "_ib", ib):
        import logging

        with patch.object(logging.getLogger("src.ibkr.connection"), "critical") as mock_crit:
            await auto._reconnect_loop()

    # After 3 failed attempts, CRITICAL must have been logged.
    assert mock_crit.called
    # _reconnecting must be reset to False so future disconnects can trigger a new loop.
    assert auto._reconnecting is False
    # connectAsync called exactly max_reconnect_attempts (3) times.
    assert ib.connectAsync.call_count == 3


async def test_reconnect_loop_succeeds_and_calls_callback() -> None:
    """A successful reconnect calls the on_reconnect callback and resets the flag."""
    ib = _make_ib(connected=False)

    on_reconnect = AsyncMock()
    auto = AutoReconnect(
        ib,
        host="127.0.0.1",
        port=7497,
        client_id=14,
        backoff_base=0.001,
        max_reconnect_attempts=5,
        on_reconnect=on_reconnect,
        label="test",
    )
    auto._reconnecting = True

    # First connect attempt succeeds.
    async def fake_connect(*args, **kwargs):
        ib.isConnected.return_value = True

    ib.connectAsync = AsyncMock(side_effect=fake_connect)
    ib.reqMarketDataType = MagicMock()

    await auto._reconnect_loop()

    ib.connectAsync.assert_called_once()
    on_reconnect.assert_called_once()
    assert auto._reconnecting is False


def test_stop_disables_future_reconnects() -> None:
    """stop() must prevent _on_disconnect from scheduling a new reconnect."""
    ib = _make_ib(connected=True)
    auto = _make_auto(ib)
    auto.stop()

    loop = asyncio.new_event_loop()
    tasks_created = []

    def fake_create_task(coro):
        tasks_created.append(coro)
        return MagicMock()

    loop.create_task = fake_create_task  # type: ignore[method-assign]
    try:
        with patch("asyncio.get_running_loop", return_value=loop):
            auto._on_disconnect()
        assert tasks_created == []
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Account-summary reconnect helpers
# ---------------------------------------------------------------------------


async def test_suppress_account_summary_on_reconnect_blocks_1102() -> None:
    """suppress_account_summary_on_reconnect must prevent reqAccountSummaryAsync
    from firing when Error 1102 arrives on the patched (exec) IB object."""
    ib = ib_async.IB()
    subscribe_calls: list[bool] = []

    orig = ib_async.IB.reqAccountSummaryAsync

    async def _tracked(self: ib_async.IB) -> None:  # type: ignore[override]
        subscribe_calls.append(True)

    ib_async.IB.reqAccountSummaryAsync = _tracked  # type: ignore[method-assign]
    try:
        suppress_account_summary_on_reconnect(ib)
        ib.errorEvent.emit(-1, 1102, "Connectivity restored", None)
        await asyncio.sleep(0)
        assert subscribe_calls == [], (
            "exec connection must not subscribe to account summary on 1102"
        )
    finally:
        ib_async.IB.reqAccountSummaryAsync = orig  # type: ignore[method-assign]


async def test_suppress_account_summary_passes_other_errors() -> None:
    """Non-1102 errors must still be forwarded to ib_async's normal handler."""
    ib = ib_async.IB()
    other_errors: list[int] = []

    orig = ib_async.IB._onError

    def _tracking(self: ib_async.IB, reqId: int, errorCode: int, *a: object) -> None:
        other_errors.append(errorCode)

    ib_async.IB._onError = _tracking  # type: ignore[method-assign]
    try:
        suppress_account_summary_on_reconnect(ib)
        ib.errorEvent.emit(1, 200, "No security definition", None)
        await asyncio.sleep(0)
        assert 200 in other_errors
    finally:
        ib_async.IB._onError = orig  # type: ignore[method-assign]


async def test_debounce_account_summary_on_reconnect_deduplicates() -> None:
    """debounce_account_summary_on_reconnect must issue only one resubscription
    even when Error 1102 fires multiple times before the first resolves."""
    ib = ib_async.IB()
    subscribe_calls: list[bool] = []

    async def _tracked() -> None:
        subscribe_calls.append(True)

    ib.reqAccountSummaryAsync = _tracked  # type: ignore[assignment]

    # _reconnect_delay=0 avoids a real 0.5 s sleep; we yield with real asyncio.sleep(0).
    debounce_account_summary_on_reconnect(ib, _reconnect_delay=0)
    # Fire 1102 three times rapidly before any scheduled task can run.
    ib.errorEvent.emit(-1, 1102, "restored", None)
    ib.errorEvent.emit(-1, 1102, "restored", None)
    ib.errorEvent.emit(-1, 1102, "restored", None)
    # Yield twice: once to start the task, once for it to reach reqAccountSummaryAsync.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert len(subscribe_calls) == 1, (
        f"expected exactly 1 resubscription, got {len(subscribe_calls)}"
    )


# ---------------------------------------------------------------------------
# connect_with_retry — startup clientId-collision resilience
# ---------------------------------------------------------------------------


async def test_connect_with_retry_succeeds_first_try():
    from src.ibkr.connection import connect_with_retry

    ib = MagicMock()
    ib.connectAsync = AsyncMock(return_value=None)

    await connect_with_retry(
        ib, "127.0.0.1", 4002, 15, timeout=5.0, label="scan", retries=5, backoff_base=0.0
    )
    ib.connectAsync.assert_called_once()
    assert ib.connectAsync.call_args.kwargs["clientId"] == 15


async def test_connect_with_retry_retries_then_succeeds():
    """A transient 'client id already in use' on restart must self-heal, not disable the
    connection for the session."""
    from src.ibkr.connection import connect_with_retry

    calls = {"n": 0}

    async def _flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("client id is already in use")
        return None

    ib = MagicMock()
    ib.connectAsync = AsyncMock(side_effect=_flaky)

    await connect_with_retry(
        ib, "127.0.0.1", 4002, 15, timeout=5.0, label="scan", retries=5, backoff_base=0.0
    )
    assert calls["n"] == 3  # failed twice, succeeded on the third


async def test_connect_with_retry_raises_after_exhausting_attempts():
    from src.ibkr.connection import connect_with_retry

    ib = MagicMock()
    ib.connectAsync = AsyncMock(side_effect=ConnectionRefusedError("refused"))

    with pytest.raises(ConnectionRefusedError):
        await connect_with_retry(
            ib, "127.0.0.1", 4002, 15, timeout=5.0, label="scan", retries=3, backoff_base=0.0
        )
    assert ib.connectAsync.call_count == 3
