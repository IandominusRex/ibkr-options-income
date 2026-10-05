"""Live fills -> ledger (spec §5.3; Review Focus 3).

Controller rulings pinned here:
- F7a: the periodic sweep reuses ``src.execution.reconciliation._req_executions_bounded``
  rather than re-implementing the bounded ``reqExecutions`` call; its ``None`` return (failure/
  timeout) must never be read as "no executions".
- F7b: the sweep is gated to RTH (``src.common.market_hours.is_rth``) each cycle; the
  commission-report hook still records fills at any hour.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select


def fill(
    *,
    sec="OPT",
    side="SLD",
    shares=1,
    price=1.9,
    account="U0000001",
    exec_id="e1",
    perm=7,
    order_id=55,
    commission=1.05,
    realized=sys.float_info.max,
):
    return SimpleNamespace(
        contract=SimpleNamespace(
            secType=sec,
            symbol="NVDA",
            lastTradeDateOrContractMonth="20250718",
            strike=170.0,
            right="P",
            multiplier="100" if sec == "OPT" else "",
            currency="USD",
        ),
        execution=SimpleNamespace(
            execId=exec_id,
            time=datetime(2025, 7, 11, 14, 0, tzinfo=UTC),
            acctNumber=account,
            side=side,
            shares=shares,
            price=price,
            permId=perm,
            orderId=order_id,
        ),
        commissionReport=SimpleNamespace(commission=commission, realizedPNL=realized),
    )


def test_fill_to_execution_option_sell() -> None:
    from src.ledger.live import fill_to_execution

    e = fill_to_execution(fill())
    assert e is not None
    assert (e.quantity, e.proceeds, e.commission, e.exec_id, e.perm_id) == (
        -1.0,
        190.0,
        -1.05,
        "e1",
        7,
    )
    assert e.ibkr_realized_pnl is None and e.source_kind == "exec"
    assert e.contract.expiry == date(2025, 7, 18)


def test_fill_to_execution_skips_combos() -> None:
    from src.ledger.live import fill_to_execution

    assert fill_to_execution(fill(sec="BAG")) is None


def test_live_fills_are_skipped_until_an_import_locks_the_account(db) -> None:
    from src.ledger.live import ingest_fills
    from src.storage.models import BrokerExecutionRow, LedgerImportRunRow

    assert ingest_fills([fill()]) == 0
    with db() as s:
        assert s.scalars(select(BrokerExecutionRow)).first() is None
        assert s.scalars(select(LedgerImportRunRow)).first() is None


def test_paper_fills_never_reach_the_real_ledger(db) -> None:
    # Review Focus 3.
    from src.ledger.live import ingest_fills
    from src.ledger.state import lock_account
    from src.storage.models import LedgerImportRunRow

    with db() as s:
        lock_account(s, "U0000001")
    assert ingest_fills([fill(account="DU999")]) == 0
    with db() as s:
        assert s.scalars(select(LedgerImportRunRow)).first() is None


def test_matching_account_fill_is_ingested(db) -> None:
    from src.ledger.live import ingest_fills
    from src.ledger.state import lock_account
    from src.storage.models import BrokerExecutionRow

    with db() as s:
        lock_account(s, "U0000001")
    assert ingest_fills([fill()]) == 1
    assert ingest_fills([fill()]) == 0  # same execId again
    with db() as s:
        row = s.scalars(select(BrokerExecutionRow)).one()
        assert (row.source, row.exec_id) == ("live", "e1")


def test_hook_swallows_errors(monkeypatch) -> None:
    import src.ledger.live as live

    def boom(_fills):
        raise RuntimeError("db locked")

    monkeypatch.setattr(live, "ingest_fills", boom)
    live.on_commission_report(None, fill(), None)  # must not raise


def test_approval_service_wires_the_ledger_tasks() -> None:
    text = Path("src/notify/approval_service.py").read_text()
    assert "attach_live_hook(ib)" in text and "live_sweep_loop(ib)" in text


# --------------------------------------------------------------------------- #
# Sweep gating (F7a / F7b)
# --------------------------------------------------------------------------- #


async def _boom_req_executions(ib, context):
    raise AssertionError("reqExecutions must not be called outside RTH")


@pytest.mark.asyncio
async def test_sweep_skips_outside_rth(monkeypatch) -> None:
    import src.ledger.live as live

    monkeypatch.setattr(live, "is_rth", lambda: False)
    monkeypatch.setattr(live, "_req_executions_bounded", _boom_req_executions)
    result = await live._sweep_once(SimpleNamespace(isConnected=lambda: True))
    assert result is None


@pytest.mark.asyncio
async def test_sweep_skips_when_disconnected(monkeypatch) -> None:
    import src.ledger.live as live

    monkeypatch.setattr(live, "is_rth", lambda: True)
    monkeypatch.setattr(live, "_req_executions_bounded", _boom_req_executions)
    result = await live._sweep_once(SimpleNamespace(isConnected=lambda: False))
    assert result is None


@pytest.mark.asyncio
async def test_sweep_treats_a_failed_req_executions_as_skip_not_empty(monkeypatch) -> None:
    """F7a: None (failure/timeout) must never be folded into a "0 new executions" ingest call."""
    import src.ledger.live as live

    calls: list[object] = []

    async def returns_none(ib, context):
        return None

    def spy_ingest_fills(fills):
        calls.append(fills)
        return 0

    monkeypatch.setattr(live, "is_rth", lambda: True)
    monkeypatch.setattr(live, "_req_executions_bounded", returns_none)
    monkeypatch.setattr(live, "ingest_fills", spy_ingest_fills)
    result = await live._sweep_once(SimpleNamespace(isConnected=lambda: True))
    assert result is None
    assert calls == []  # ingest_fills was never reached


@pytest.mark.asyncio
async def test_sweep_ingests_fills_returned_during_rth(monkeypatch) -> None:
    import src.ledger.live as live

    sentinel_fills = [fill()]

    async def returns_fills(ib, context):
        return sentinel_fills

    calls: list[object] = []

    def spy_ingest_fills(fills):
        calls.append(fills)
        return 3

    monkeypatch.setattr(live, "is_rth", lambda: True)
    monkeypatch.setattr(live, "_req_executions_bounded", returns_fills)
    monkeypatch.setattr(live, "ingest_fills", spy_ingest_fills)
    result = await live._sweep_once(SimpleNamespace(isConnected=lambda: True))
    assert result == 3
    assert calls == [sentinel_fills]
