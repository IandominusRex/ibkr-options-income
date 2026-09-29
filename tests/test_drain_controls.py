"""The kill switch works when everything else does not. M6 Task 6.1.

The three control handlers are the lightest in the drain, and the most safety-critical:
`halt` must apply when TWS is down (that is when halting matters most), halting an
already-halted system is a satisfied intent, not a failure, and the reason must be
readable on `/status` and the console.
"""

from __future__ import annotations

import pytest

from src.common.schemas import AutonomyLevel
from src.storage.system_settings import get_autonomy_level, get_halt_reason, is_halted


def _sent_texts(bot) -> list[str]:
    """The message text of every send the fake bot was asked to make."""
    return [
        call.kwargs.get("text", call.args[-1] if call.args else "")
        for call in bot.send_message.call_args_list
    ]


@pytest.fixture
def drain_env(monkeypatch, tmp_path):
    """A temp trading DB + fake bot + control-side helpers, from the M3/M5 fixture pattern.

    Only the three control handlers are re-exposed (the fixture saves and restores
    ``HANDLERS`` so a registration in one test cannot leak, same as M3).
    """
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()

    from unittest.mock import AsyncMock

    from src.notify.command_drain import HANDLERS
    from src.storage.app_commands import enqueue_command
    from src.storage.models import AppCommandRow

    saved_handlers = dict(HANDLERS)
    HANDLERS.clear()
    HANDLERS.update(
        {k: v for k, v in saved_handlers.items() if k in ("halt", "resume", "set_autonomy")}
    )

    bot = AsyncMock()
    bot.send_message = AsyncMock()

    def enqueue(kind: str, payload: dict, *, requested_by: str = "test") -> int:
        with dbmod.session_scope() as s:
            row, _ = enqueue_command(
                s,
                kind=kind,
                payload=payload,
                requested_by=requested_by,
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

    class _DrainEnv:
        pass

    env = _DrainEnv()
    env.bot = bot
    env.enqueue = enqueue
    env.status = status
    env.result = result
    env.halt_reason = get_halt_reason  # the milestone's tests read the setting directly
    yield env

    HANDLERS.clear()
    HANDLERS.update(saved_handlers)


@pytest.mark.asyncio
async def test_halt_applies_with_no_broker_connection(drain_env) -> None:
    """Halting matters most when something is already wrong."""
    cid = drain_env.enqueue("halt", {"reason": "spread blew out"})

    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert is_halted() is True
    assert get_halt_reason() == "spread blew out"


@pytest.mark.asyncio
async def test_halting_an_already_halted_system_is_applied(drain_env) -> None:
    """The operator's intent is satisfied. Not a failure."""
    from src.notify.command_drain import drain_once

    drain_env.enqueue("halt", {"reason": "first"})
    await drain_once(None, drain_env.bot, "chat")
    cid = drain_env.enqueue("halt", {"reason": "second"})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert is_halted() is True
    assert get_halt_reason() == "second"


@pytest.mark.asyncio
async def test_an_empty_halt_reason_becomes_something_readable(drain_env) -> None:
    from src.notify.command_drain import drain_once

    drain_env.enqueue("halt", {"reason": ""})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.halt_reason() != ""
    assert is_halted() is True


@pytest.mark.asyncio
async def test_halt_with_a_missing_reason_key_is_readable_too(drain_env) -> None:
    """The API defaults the key to "", but the drain must not rely on the API having done so."""
    from src.notify.command_drain import drain_once

    drain_env.enqueue("halt", {})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.halt_reason() != ""


@pytest.mark.asyncio
async def test_resume_releases_the_halt(drain_env) -> None:
    from src.notify.command_drain import drain_once

    drain_env.enqueue("halt", {"reason": "checking something"})
    await drain_once(None, drain_env.bot, "chat")
    cid = drain_env.enqueue("resume", {})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert is_halted() is False


@pytest.mark.asyncio
async def test_resume_records_who_released_it(drain_env) -> None:
    from src.notify.command_drain import drain_once

    drain_env.enqueue("halt", {"reason": "first"})
    await drain_once(None, drain_env.bot, "chat")
    cid = drain_env.enqueue("resume", {}, requested_by="owner")
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert drain_env.result(cid)["released_by"] == "owner"


@pytest.mark.asyncio
async def test_resume_when_not_halted_is_applied_not_failed(drain_env) -> None:
    """Releasing an un-engaged switch is a satisfied intent (Telegram reports the same
    shape as a neutral "not halted")."""
    from src.notify.command_drain import drain_once

    cid = drain_env.enqueue("resume", {})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"


@pytest.mark.asyncio
async def test_set_autonomy_moves_the_rung(drain_env) -> None:
    from src.notify.command_drain import drain_once

    cid = drain_env.enqueue("set_autonomy", {"level": "manual"})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert get_autonomy_level() is AutonomyLevel.MANUAL


@pytest.mark.asyncio
async def test_set_autonomy_promotion_refused_carries_the_blockers(drain_env, monkeypatch) -> None:
    """The web must not become the rung ladder's back door: a promotion with unmet
    evidence criteria fails with the blockers, exactly like Telegram's /autonomy."""
    from src.common.config import get_config
    from src.common.schemas import AutonomyLevel
    from src.notify.command_drain import drain_once
    from src.storage.system_settings import set_autonomy_level

    # Task 12's paper-only bypass ships on in config/settings.yaml for this deployment — turn
    # it off here so this test exercises the evidence gate itself, not the bypass around it.
    monkeypatch.setattr(get_config().automation, "paper_skip_promotion_gate", False)

    set_autonomy_level(AutonomyLevel.OBSERVE)
    cid = drain_env.enqueue("set_autonomy", {"level": "full"})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "promotion_refused"
    assert drain_env.result(cid)["detail"]["blockers"]
    assert get_autonomy_level() is AutonomyLevel.OBSERVE


@pytest.mark.asyncio
async def test_set_autonomy_demotion_always_applies(drain_env) -> None:
    """Demotion needs no evidence (same rule as Telegram)."""
    from src.notify.command_drain import drain_once
    from src.storage.system_settings import set_autonomy_level

    set_autonomy_level(AutonomyLevel.MANUAL)
    cid = drain_env.enqueue("set_autonomy", {"level": "observe"})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert get_autonomy_level() is AutonomyLevel.OBSERVE


@pytest.mark.asyncio
async def test_a_control_change_notifies_telegram(drain_env) -> None:
    """A halt raised from the browser must be visible wherever the operator is."""
    from src.notify.command_drain import drain_once

    drain_env.enqueue("halt", {"reason": "checking something"})
    await drain_once(None, drain_env.bot, "chat")

    assert any("halt" in m.lower() for m in _sent_texts(drain_env.bot))


@pytest.mark.asyncio
async def test_resume_and_set_autonomy_also_notify(drain_env) -> None:
    from src.notify.command_drain import drain_once

    drain_env.enqueue("halt", {"reason": "x"})
    await drain_once(None, drain_env.bot, "chat")
    drain_env.bot.send_message.reset_mock()

    drain_env.enqueue("resume", {})
    drain_env.enqueue("set_autonomy", {"level": "manual"})
    await drain_once(None, drain_env.bot, "chat")

    assert len(_sent_texts(drain_env.bot)) == 2


@pytest.mark.asyncio
async def test_all_three_controls_apply_with_no_broker_connection(drain_env) -> None:
    """Parametrised over halt, resume, set_autonomy. None may need TWS."""
    from src.notify.command_drain import drain_once

    pairs = [
        ("halt", {"reason": "r"}),
        ("resume", {}),
        ("set_autonomy", {"level": "manual"}),
    ]
    for kind, payload in pairs:
        cid = drain_env.enqueue(kind, payload)
        await drain_once(None, drain_env.bot, "chat")
        assert drain_env.status(cid) == "applied", f"{kind} did not apply with ib=None"
