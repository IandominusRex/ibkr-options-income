"""The drain applies what it can, fails what it cannot, and never stalls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def drain_env(monkeypatch, tmp_path):
    """A temp trading DB + fake bot + enqueue/status/result helpers."""
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()

    from src.notify.command_drain import HANDLERS
    from src.storage.app_commands import enqueue_command
    from src.storage.models import AppCommandRow

    # Save and restore HANDLERS so a registration in one test cannot leak.
    saved_handlers = dict(HANDLERS)
    HANDLERS.clear()

    bot = AsyncMock()
    bot.send_message = AsyncMock()

    def enqueue(kind: str, payload: dict, *, confirm_token: str | None = None) -> int:
        with dbmod.session_scope() as s:
            row, _ = enqueue_command(
                s,
                kind=kind,
                payload=payload,
                requested_by="test",
                confirm_token=confirm_token,
            )
            return row.id

    def status(cid: int) -> str:
        with dbmod.session_scope() as s:
            row = s.get(AppCommandRow, cid)
            assert row is not None
            return row.status

    def result(cid: int) -> dict:
        with dbmod.session_scope() as s:
            row = s.get(AppCommandRow, cid)
            assert row is not None
            return row.result or {}

    yield _DrainEnv(bot=bot, enqueue=enqueue, status=status, result=result)

    HANDLERS.clear()
    HANDLERS.update(saved_handlers)


class _DrainEnv:
    def __init__(self, bot, enqueue, status, result):
        self.bot = bot
        self.enqueue = enqueue
        self.status = status
        self.result = result


@pytest.mark.asyncio
async def test_an_unknown_kind_is_failed_not_left_pending(drain_env) -> None:
    """A command stuck pending forever is invisible to the operator. Fail it loudly."""
    cid = drain_env.enqueue("no_such_kind", {})
    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "unknown_kind"


@pytest.mark.asyncio
async def test_a_throwing_handler_fails_only_its_own_command(drain_env) -> None:
    from src.notify.command_drain import drain_once, register

    @register("boom")
    def _boom(**_):
        raise RuntimeError("kaboom")

    # Register a harmless handler for "refresh" so it gets applied
    @register("refresh")
    def _refresh(**_):
        pass

    bad = drain_env.enqueue("boom", {})
    good = drain_env.enqueue("refresh", {})
    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(bad) == "failed"
    assert "kaboom" in drain_env.result(bad)["detail"]["error"]
    assert drain_env.status(good) == "applied"


@pytest.mark.asyncio
async def test_a_command_awaiting_confirmation_is_skipped_not_failed(drain_env) -> None:
    cid = drain_env.enqueue("refresh", {}, confirm_token="tok")
    from src.notify.command_drain import drain_once

    processed = await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "pending"
    assert processed == 0


@pytest.mark.asyncio
async def test_broker_free_commands_apply_with_no_exec_connection(drain_env) -> None:
    """TWS down must not stop a reject, a halt, or a universe edit."""
    from src.notify.command_drain import drain_once, register

    @register("refresh")
    def _refresh(**_):
        pass

    cid = drain_env.enqueue("refresh", {})
    await drain_once(None, drain_env.bot, "chat")  # ib is None
    assert drain_env.status(cid) == "applied"


@pytest.mark.asyncio
async def test_expire_stale_commands_runs_once_per_drain(drain_env) -> None:
    """A command past its TTL is expired, not left pending."""
    from src.notify.command_drain import drain_once
    from src.storage.app_commands import enqueue_command
    from src.storage.db import session_scope

    # Insert a command and backdate its created_at to before the TTL.
    with session_scope() as s:
        row, _ = enqueue_command(s, kind="refresh", payload={}, requested_by="test")
        row.created_at = datetime.now(UTC) - timedelta(hours=2)
        cid = row.id

    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "expired"


@pytest.mark.asyncio
async def test_the_drain_writes_a_heartbeat_after_the_cycle(drain_env) -> None:
    """The drain writes command_drain_heartbeat to system_settings after every cycle.

    Written AFTER the work, never before, so a hung handler cannot make the loop look
    healthy. M2's /options/controls reads this to tell an operator their click is
    queued and nothing is picking it up (M1 Task 1.5 design point 6).
    """
    from src.notify.command_drain import COMMAND_DRAIN_HEARTBEAT_KEY, drain_once
    from src.storage.system_settings import get_setting

    # Snapshot the heartbeat before, then run a cycle that processes nothing.
    before = get_setting(COMMAND_DRAIN_HEARTBEAT_KEY, "")
    await drain_once(None, drain_env.bot, "chat")
    after = get_setting(COMMAND_DRAIN_HEARTBEAT_KEY, "")
    # The heartbeat must be written even when nothing was processed, and it must
    # advance (not stay equal to the pre-cycle value).
    assert after != ""
    assert after != before


@pytest.mark.asyncio
async def test_a_hung_handler_does_not_advance_the_heartbeat_before_failing(
    drain_env,
) -> None:
    """The heartbeat is written AFTER the work. A handler that raises must not leave
    a heartbeat timestamp that precedes the failure — the loop only writes it once,
    at the end, after all commands have been processed or failed."""
    from src.notify.command_drain import COMMAND_DRAIN_HEARTBEAT_KEY, drain_once, register
    from src.storage.system_settings import get_setting

    @register("hang")
    def _hang(**_):
        raise RuntimeError("stuck")

    before = get_setting(COMMAND_DRAIN_HEARTBEAT_KEY, "")
    drain_env.enqueue("hang", {})
    await drain_once(None, drain_env.bot, "chat")
    after = get_setting(COMMAND_DRAIN_HEARTBEAT_KEY, "")
    # The heartbeat advances despite the failure — the cycle completed, the handler
    # only failed its own command.
    assert after != before
