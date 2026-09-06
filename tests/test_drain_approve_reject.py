"""The web approve is the Telegram approve. Same function, same guarantees."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.common.schemas import ApprovalStatus, OrderState

_EXPIRY = date.today() + timedelta(days=30)


def _snapshot(*, contracts: int = 1, premium: float = 3.25) -> dict:
    return {
        "underlying": "NVDA",
        "strategy": "cash_secured_put",
        "right": "P",
        "strike": 190.0,
        "expiry": _EXPIRY.isoformat(),
        "contracts": contracts,
        "premium": premium,
        "blended_score": 72.0,
    }


@pytest.fixture
def drain_env(monkeypatch, tmp_path):
    """A temp trading DB + fake bot + approval/command helpers.

    Extends the M1 fixture with the approval-side helpers M3 needs:
    ``seed_pending_approval``, ``approval_status``, ``order_for_approval``,
    ``order_count_for_approval`` and ``decide``.
    """
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()

    from src.notify.command_drain import HANDLERS
    from src.storage.app_commands import enqueue_command
    from src.storage.models import AppCommandRow, ApprovalRow, OrderRow

    # Save and restore HANDLERS so a registration in one test cannot leak.
    saved_handlers = dict(HANDLERS)
    HANDLERS.clear()
    # Re-expose only the production handlers under test (approve/reject, registered
    # at import time above) — unlike the M1 machinery tests, these tests exist to
    # exercise the real handlers, not to prove the registry is empty.
    HANDLERS.update({k: v for k, v in saved_handlers.items() if k in ("approve", "reject")})

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

    def seed_pending_approval(underlying: str = "NVDA", *, snapshot: dict | None = None) -> int:
        """Insert a PENDING ApprovalRow and return its id."""
        with dbmod.session_scope() as s:
            row = ApprovalRow(
                candidate_id=f"{underlying}-cand-1",
                status=ApprovalStatus.PENDING,
                snapshot=snapshot or _snapshot(),
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
            s.add(row)
            s.flush()
            return row.id

    def approval_status(approval_id: int) -> str:
        with dbmod.session_scope() as s:
            row = s.get(ApprovalRow, approval_id)
            assert row is not None
            return row.status

    def order_for_approval(approval_id: int) -> OrderRow | None:
        with dbmod.session_scope() as s:
            row = s.query(OrderRow).filter(OrderRow.approval_id == approval_id).one_or_none()
            if row is None:
                return None
            # Detach a snapshot of the row so callers can read attributes after
            # the session closes.
            s.expunge(row)
            return row

    def order_count_for_approval(approval_id: int) -> int:
        with dbmod.session_scope() as s:
            return s.query(OrderRow).filter(OrderRow.approval_id == approval_id).count()

    def decide(approval_id: int, new_status: ApprovalStatus) -> None:
        """Flip an approval's status directly, simulating a Telegram decision."""
        with dbmod.session_scope() as s:
            row = s.get(ApprovalRow, approval_id)
            assert row is not None
            row.status = new_status
            row.decided_at = datetime.now(UTC)

    def reset_to_pending_without_touching_the_approval(cid: int) -> None:
        """Simulate a crashed drain: un-mark an applied command so it is retried.

        The approval keeps its decided status — the point is that the retry hits
        ``_process_button``'s idempotency guard, not a fresh mutation.
        """
        with dbmod.session_scope() as s:
            row = s.get(AppCommandRow, cid)
            assert row is not None
            row.status = "pending"
            row.applied_at = None

    env = _DrainEnv(
        bot=bot,
        enqueue=enqueue,
        status=status,
        result=result,
        seed_pending_approval=seed_pending_approval,
        approval_status=approval_status,
        order_for_approval=order_for_approval,
        order_count_for_approval=order_count_for_approval,
        decide=decide,
        reset_to_pending_without_touching_the_approval=reset_to_pending_without_touching_the_approval,
    )
    yield env

    HANDLERS.clear()
    HANDLERS.update(saved_handlers)


class _DrainEnv:
    def __init__(
        self,
        bot,
        enqueue,
        status,
        result,
        seed_pending_approval,
        approval_status,
        order_for_approval,
        order_count_for_approval,
        decide,
        reset_to_pending_without_touching_the_approval,
    ):
        self.bot = bot
        self.enqueue = enqueue
        self.status = status
        self.result = result
        self.seed_pending_approval = seed_pending_approval
        self.approval_status = approval_status
        self.order_for_approval = order_for_approval
        self.order_count_for_approval = order_count_for_approval
        self.decide = decide
        self.reset_to_pending_without_touching_the_approval = (
            reset_to_pending_without_touching_the_approval
        )


# ---------------------------------------------------------------------------
# The seven M3 tests, verbatim from the plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_creates_a_queued_order_from_the_frozen_snapshot(drain_env) -> None:
    approval_id = drain_env.seed_pending_approval("NVDA", snapshot={"contracts": 2})
    cid = drain_env.enqueue("approve", {"approval_id": approval_id})

    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert drain_env.approval_status(approval_id) == ApprovalStatus.APPROVED
    order = drain_env.order_for_approval(approval_id)
    assert order is not None
    assert order.state == OrderState.QUEUED
    assert order.snapshot == {"contracts": 2}  # N2a: the payload the human was shown


@pytest.mark.asyncio
async def test_the_handler_calls_process_button_rather_than_reimplementing_it(
    drain_env, monkeypatch
) -> None:
    """A refactor must not be able to fork the mutation without this test failing."""
    calls = []
    import src.notify.command_drain as drain
    from src.notify.approval_service import _process_button as real

    monkeypatch.setattr(
        drain,
        "_process_button",
        lambda aid, action: (calls.append((aid, action)), real(aid, action))[1],
    )
    approval_id = drain_env.seed_pending_approval("NVDA")
    drain_env.enqueue("approve", {"approval_id": approval_id})
    await drain.drain_once(None, drain_env.bot, "chat")

    assert calls == [(approval_id, "approve")]


@pytest.mark.asyncio
async def test_an_already_decided_approval_applies_neutrally(drain_env) -> None:
    """Telegram got there first. That is a normal race, not a malfunction."""
    approval_id = drain_env.seed_pending_approval("NVDA")
    drain_env.decide(approval_id, ApprovalStatus.APPROVED)
    cid = drain_env.enqueue("approve", {"approval_id": approval_id})

    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert "Already" in drain_env.result(cid)["decision"]


@pytest.mark.asyncio
async def test_a_replayed_drain_creates_no_second_order(drain_env) -> None:
    approval_id = drain_env.seed_pending_approval("NVDA")
    cid = drain_env.enqueue("approve", {"approval_id": approval_id})

    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")
    drain_env.reset_to_pending_without_touching_the_approval(cid)
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.order_count_for_approval(approval_id) == 1


@pytest.mark.asyncio
async def test_approve_applies_with_no_exec_connection(drain_env) -> None:
    """TWS down queues the order. It does not lose the decision."""
    approval_id = drain_env.seed_pending_approval("NVDA")
    cid = drain_env.enqueue("approve", {"approval_id": approval_id})

    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")  # ib is None
    assert drain_env.status(cid) == "applied"
    order = drain_env.order_for_approval(approval_id)
    assert order is not None
    assert order.state == OrderState.QUEUED


@pytest.mark.asyncio
async def test_reject_records_the_outcome(drain_env) -> None:
    approval_id = drain_env.seed_pending_approval("NVDA")
    cid = drain_env.enqueue("reject", {"approval_id": approval_id})

    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert drain_env.approval_status(approval_id) == ApprovalStatus.REJECTED
    assert drain_env.order_for_approval(approval_id) is None


@pytest.mark.asyncio
async def test_an_unknown_approval_id_fails_the_command(drain_env) -> None:
    cid = drain_env.enqueue("approve", {"approval_id": 999999})

    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "approval_not_found"
