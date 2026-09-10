"""refresh is the phase's only write, and it is the least dangerous command in the system.

The `refresh` drain handler (P3-P4 M1 Task 1.4) captures positions + account values now and
writes ONE `portfolio_snapshots` row (`source="refresh"`). It creates no candidate, no
approval, and no order — this is where the phase's no-new-order-path assertion lives. It
ignores the monitor's interval gate: an operator asking for a fetch gets one. `ib is None`
fails `broker_unavailable` rather than writing a row of whatever the last known state was.

Fixture mirrors tests/test_drain_universe.py's `drain_env` (temp trading DB + fake bot,
HANDLERS saved/restored), extended with snapshot/approval/order counters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import AccountSnapshot, PositionSnapshot


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123",
        net_liquidation=100_000.0,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=5_000.0,
        excess_liquidity=75_000.0,
    )


@pytest.fixture
def drain_env(monkeypatch, tmp_path):
    """Temp trading DB + fake bot + fake connected IB, mirroring test_drain_universe.py."""
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()

    from src.notify.command_drain import HANDLERS
    from src.storage.app_commands import enqueue_command
    from src.storage.models import (
        AppCommandRow,
        ApprovalRow,
        OrderRow,
        PortfolioSnapshotRow,
    )

    saved_handlers = dict(HANDLERS)
    HANDLERS.clear()
    HANDLERS.update({k: v for k, v in saved_handlers.items() if k == "refresh"})

    bot = AsyncMock()
    ib = MagicMock(name="ib")
    monkeypatch.setattr(
        "src.notify.command_drain.get_positions",
        lambda ib_: [
            PositionSnapshot(symbol="NVDA", sec_type="STK", position=100.0, avg_cost=170.0)
        ],
    )
    monkeypatch.setattr(
        "src.notify.command_drain.get_account_snapshot_async",
        AsyncMock(return_value=_account()),
    )

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

    def snapshot_count() -> int:
        with dbmod.session_scope() as s:
            return s.query(PortfolioSnapshotRow).count()

    def approval_count() -> int:
        with dbmod.session_scope() as s:
            return s.query(ApprovalRow).count()

    def order_count() -> int:
        with dbmod.session_scope() as s:
            return s.query(OrderRow).count()

    class _DrainEnv:
        pass

    env = _DrainEnv()
    env.bot = bot
    env.ib = ib
    env.enqueue = enqueue
    env.status = status
    env.result = result
    env.snapshot_count = snapshot_count
    env.approval_count = approval_count
    env.order_count = order_count
    yield env

    HANDLERS.clear()
    HANDLERS.update(saved_handlers)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_refresh_writes_one_snapshot_and_applies(drain_env) -> None:
    from src.notify.command_drain import drain_once

    cid = drain_env.enqueue("refresh", {})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    result = drain_env.result(cid)
    assert "captured_at" in result
    assert result["positions"] >= 0
    assert drain_env.snapshot_count() == 1


@pytest.mark.asyncio
async def test_a_refresh_with_no_broker_fails_honestly(drain_env) -> None:
    """Writing the last known state and calling it fresh is worse than saying no."""
    from src.notify.command_drain import drain_once

    cid = drain_env.enqueue("refresh", {})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "broker_unavailable"
    assert drain_env.snapshot_count() == 0


@pytest.mark.asyncio
async def test_a_refresh_creates_no_approval_and_no_order(drain_env) -> None:
    """P3 and P4 add no path to an order. This is where that is asserted."""
    from src.notify.command_drain import drain_once

    approvals_before = drain_env.approval_count()
    orders_before = drain_env.order_count()

    drain_env.enqueue("refresh", {})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.approval_count() == approvals_before
    assert drain_env.order_count() == orders_before


@pytest.mark.asyncio
async def test_a_failed_write_fails_with_its_own_reason(drain_env, monkeypatch) -> None:
    from src.notify.command_drain import drain_once

    cid = drain_env.enqueue("refresh", {})
    monkeypatch.setattr("src.notify.command_drain.save_portfolio_snapshot", lambda **kwargs: None)
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "snapshot_failed"


@pytest.mark.asyncio
async def test_two_refreshes_both_apply(drain_env) -> None:
    from src.notify.command_drain import drain_once

    first = drain_env.enqueue("refresh", {})
    second = drain_env.enqueue("refresh", {})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(first) == "applied"
    assert drain_env.status(second) == "applied"
    assert drain_env.snapshot_count() == 2


@pytest.mark.asyncio
async def test_the_written_row_is_a_refresh_source_with_positions(drain_env) -> None:
    """The row's source must be 'refresh' and carry the fetched positions, so the API's
    fallback chain can distinguish an operator-requested capture from a monitor one."""
    import src.storage.db as dbmod
    from src.notify.command_drain import drain_once
    from src.storage.models import PortfolioSnapshotRow

    cid = drain_env.enqueue("refresh", {})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    with dbmod.session_scope() as s:
        row = s.query(PortfolioSnapshotRow).one()
        assert row.source == "refresh"
        assert len(row.positions) == 1
        captured = row.captured_at
    assert captured is not None
    assert isinstance(captured, datetime)
    # SQLite returns the stored instant naive; the receipt reported it UTC-aware. The
    # receipt's captured_at must be the row's capture time — the same instant, not a
    # second now() — so a refresh receipt can never claim a fresher capture than the
    # row the API's fallback chain will actually serve.
    result_captured = datetime.fromisoformat(drain_env.result(cid)["captured_at"])
    assert captured.replace(tzinfo=UTC) == result_captured
