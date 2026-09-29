"""Tests for AutoReconnect and account-summary helpers in src/ibkr/connection.py.

P1-09: _reconnecting flag set synchronously before create_task.
P1-10: after max_reconnect_attempts fast retries the loop logs CRITICAL once and drops to a
quiet watch mode (bare TCP probe of the Gateway port) instead of giving up for good.
"""

from __future__ import annotations

import asyncio
import logging
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
    ib,
    *,
    max_reconnect_attempts: int = 20,
    backoff_base: float = 0.01,
    max_backoff: float = 0.01,
    on_reconnect=None,
) -> AutoReconnect:
    return AutoReconnect(
        ib,
        host="127.0.0.1",
        port=7497,
        client_id=14,
        backoff_base=backoff_base,
        max_backoff=max_backoff,
        max_reconnect_attempts=max_reconnect_attempts,
        on_reconnect=on_reconnect,
        label="test",
    )


def _flaky_connect(ib: MagicMock, *, fail_times: int) -> AsyncMock:
    """A connectAsync that refuses ``fail_times`` times, then connects."""
    calls = {"n": 0}

    async def _connect(*_a: object, **_k: object) -> None:
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise ConnectionRefusedError("refused")
        ib.isConnected.return_value = True

    return AsyncMock(side_effect=_connect)


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


async def test_reconnect_loop_keeps_watching_after_max_attempts_and_reconnects() -> None:
    """After the fast attempts are spent the loop logs CRITICAL once, then only probes the
    Gateway port (no connectAsync while it is closed) and reconnects when the port opens."""
    ib = _make_ib(connected=False)
    on_reconnect = AsyncMock()
    auto = _make_auto(ib, max_reconnect_attempts=3, on_reconnect=on_reconnect)
    auto._reconnecting = True  # mark as running (normally set by _on_disconnect)

    ib.connectAsync = _flaky_connect(ib, fail_times=3)  # the 3 fast attempts all refuse
    ib.reqMarketDataType = MagicMock()
    probe = AsyncMock(side_effect=[False, False, True])  # Gateway returns on the 3rd probe

    with (
        patch.object(auto, "_port_open", probe),
        patch.object(logging.getLogger("src.ibkr.connection"), "critical") as mock_crit,
    ):
        await asyncio.wait_for(auto._reconnect_loop(), timeout=5)

    assert mock_crit.call_count == 1
    assert probe.await_count == 3
    assert ib.connectAsync.call_count == 4  # 3 fast attempts + 1 once the port opened
    on_reconnect.assert_awaited_once()
    assert auto._reconnecting is False


async def test_watch_mode_retries_when_port_opens_but_handshake_fails() -> None:
    """Gateway can open its port before the API is ready (or while clientId is still held).
    A failed connectAsync in watch mode must not end the loop — it retries next tick."""
    ib = _make_ib(connected=False)
    auto = _make_auto(ib, max_reconnect_attempts=3)
    auto._reconnecting = True

    ib.connectAsync = _flaky_connect(ib, fail_times=5)  # 3 fast + 2 failed handshakes
    ib.reqMarketDataType = MagicMock()
    probe = AsyncMock(return_value=True)

    with (
        patch.object(auto, "_port_open", probe),
        patch.object(logging.getLogger("src.ibkr.connection"), "critical") as mock_crit,
    ):
        await asyncio.wait_for(auto._reconnect_loop(), timeout=5)

    assert probe.await_count == 3  # two failed handshakes, then the successful one
    assert ib.connectAsync.call_count == 6
    assert mock_crit.call_count == 1
    assert ib.isConnected() is True
    assert auto._reconnecting is False


async def test_watch_mode_survives_thousands_of_ticks() -> None:
    """A Gateway that stays down for hours means thousands of watch ticks; the backoff must
    not keep doubling (2**attempt overflows a float around attempt 1024)."""
    ib = _make_ib(connected=False)
    auto = _make_auto(ib, max_reconnect_attempts=3, backoff_base=0.001, max_backoff=0.0)
    auto._reconnecting = True

    ib.connectAsync = _flaky_connect(ib, fail_times=3)
    ib.reqMarketDataType = MagicMock()
    probe = AsyncMock(side_effect=[False] * 1100 + [True])

    with patch.object(auto, "_port_open", probe):
        await asyncio.wait_for(auto._reconnect_loop(), timeout=10)

    assert probe.await_count == 1101
    assert ib.isConnected() is True


async def test_stop_ends_watch_mode() -> None:
    """stop() (intentional shutdown) must end the watch loop, not leave it probing forever."""
    ib = _make_ib(connected=False)
    auto = _make_auto(ib, max_reconnect_attempts=3)
    auto._reconnecting = True

    ib.connectAsync = AsyncMock(side_effect=ConnectionRefusedError("refused"))

    async def _stop_then_closed() -> bool:
        auto.stop()
        return False

    probe = AsyncMock(side_effect=_stop_then_closed)

    with patch.object(auto, "_port_open", probe):
        await asyncio.wait_for(auto._reconnect_loop(), timeout=5)

    assert probe.await_count == 1
    assert ib.connectAsync.call_count == 3  # only the fast attempts; watch mode never connected
    assert auto._reconnecting is False


async def test_port_open_probe_reports_listening_and_closed_ports() -> None:
    """The real probe: True for a listening socket, False once nothing listens (no mocks)."""
    server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    auto = AutoReconnect(_make_ib(False), "127.0.0.1", port, 14, label="test")
    try:
        assert await auto._port_open() is True
    finally:
        server.close()
        await server.wait_closed()
    assert await auto._port_open() is False


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
