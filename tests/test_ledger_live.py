"""Live fills -> ledger (spec §5.3; Review Focus 3).

Controller rulings pinned here:
- F7a: the periodic sweep reuses ``src.execution.reconciliation._req_executions_bounded``
  rather than re-implementing the bounded ``reqExecutions`` call; its ``None`` return (failure/
  timeout) must never be read as "no executions".
- F7b: the sweep is gated to RTH (``src.common.market_hours.is_rth``) each cycle; the
  commission-report hook still records fills at any hour.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select


def fill(
    *,
    sec="OPT",
    symbol="NVDA",
    side="SLD",
    shares=1,
    price=1.9,
    account="U0000001",
    exec_id="e1",
    perm=7,
    order_id=55,
    commission=1.05,
    realized=sys.float_info.max,
    time=None,
    currency="USD",
):
    return SimpleNamespace(
        contract=SimpleNamespace(
            secType=sec,
            symbol=symbol,
            lastTradeDateOrContractMonth="20250718",
            strike=170.0,
            right="P",
            multiplier="100" if sec == "OPT" else "",
            currency=currency,
        ),
        execution=SimpleNamespace(
            execId=exec_id,
            time=time if time is not None else datetime(2025, 7, 11, 14, 0, tzinfo=UTC),
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
    from src.ledger.state import ledger_account
    from src.storage.models import BrokerExecutionRow, LedgerImportRunRow

    assert ingest_fills([fill()]) == 0
    with db() as s:
        assert s.scalars(select(BrokerExecutionRow)).first() is None
        assert s.scalars(select(LedgerImportRunRow)).first() is None
        assert ledger_account(s) is None


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


def test_overnight_sgx_live_fill_twins_its_csv_row_through_the_live_path(db) -> None:
    # Review Focus 4, exercised through src.ledger.live (fill_to_execution + ingest_fills), not
    # the ingest()-level ParsedExecution bypass pinned in tests/test_ledger_ingest.py.
    # 03:30 UTC Nov 3 == 22:30 ET Nov 2, so the CSV row and the live fill must land on the same
    # ET trade date and twin-match.
    from src.ledger.ingest import ingest
    from src.ledger.live import ingest_fills
    from src.ledger.state import lock_account
    from src.storage.models import BrokerExecutionRow
    from tests.test_ledger_ingest import ex, stmt

    with db() as s:
        lock_account(s, "U0000001")
    ingest(stmt(ex("A17U", "2025-11-02, 22:30:00", 500, 2.77, currency="SGD")), source="csv")

    new = ingest_fills(
        [
            fill(
                sec="STK",
                symbol="A17U",
                side="BOT",
                shares=500,
                price=2.77,
                currency="SGD",
                time=datetime(2025, 11, 3, 3, 30, tzinfo=UTC),
                exec_id="x1",
                perm=5,
            )
        ]
    )
    assert new == 1

    with db() as s:
        rows = list(s.scalars(select(BrokerExecutionRow)))
    csv_row = next(r for r in rows if r.source_kind == "order")
    live_row = next(r for r in rows if r.source_kind == "exec")
    assert csv_row.superseded_by is not None
    assert live_row.trade_date == date(2025, 11, 2)


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


# --------------------------------------------------------------------------- #
# Sweep-loop hardening: an unguarded failure (is_rth()/ib.isConnected()/get_config() raising)
# must not kill the background task — the approval service's shutdown `finally` awaits it
# outside a CancelledError suppress and would otherwise re-raise whatever killed it.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_sweep_loop_survives_a_failing_iteration(monkeypatch) -> None:
    import src.ledger.live as live

    calls = {"sleep": 0, "sweep": 0}

    async def fake_sleep(_seconds):
        calls["sleep"] += 1
        if calls["sleep"] > 2:
            raise asyncio.CancelledError

    async def flaky_sweep_once(_ib):
        calls["sweep"] += 1
        if calls["sweep"] == 1:
            raise RuntimeError("is_rth() blew up")
        return 0

    monkeypatch.setattr(live.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(live, "_sweep_once", flaky_sweep_once)

    with pytest.raises(asyncio.CancelledError):
        await live.live_sweep_loop(
            SimpleNamespace(isConnected=lambda: True), interval_minutes=0.001
        )

    # The first (raising) iteration didn't kill the loop — a second iteration ran.
    assert calls["sweep"] == 2


@pytest.mark.asyncio
async def test_hook_returns_without_ingesting_synchronously(monkeypatch) -> None:
    """I1: the hook only schedules the write on a worker thread; it never blocks the loop."""
    import threading

    import src.ledger.live as live

    main = threading.get_ident()
    seen: list[int] = []

    def spy(fills):
        seen.append(threading.get_ident())
        return 1

    monkeypatch.setattr(live, "ingest_fills", spy)
    live.on_commission_report(None, fill(), None)
    assert seen == []  # not run inline
    await asyncio.gather(*list(live._hook_tasks))
    assert seen and seen[0] != main


@pytest.mark.asyncio
async def test_hook_task_exceptions_are_logged_not_raised(monkeypatch, caplog) -> None:
    import src.ledger.live as live

    def boom(_fills):
        raise RuntimeError("db locked")

    monkeypatch.setattr(live, "ingest_fills", boom)
    with caplog.at_level("WARNING"):
        live.on_commission_report(None, fill(), None)
        await asyncio.gather(*list(live._hook_tasks), return_exceptions=True)
        await asyncio.sleep(0)
    assert "ledger live hook failed" in caplog.text


@pytest.mark.asyncio
async def test_sweep_ingests_off_the_event_loop(monkeypatch) -> None:
    import threading

    import src.ledger.live as live

    main = threading.get_ident()
    seen: list[int] = []

    async def returns_fills(ib, context):
        return [fill()]

    def spy(fills):
        seen.append(threading.get_ident())
        return 1

    monkeypatch.setattr(live, "is_rth", lambda: True)
    monkeypatch.setattr(live, "_req_executions_bounded", returns_fills)
    monkeypatch.setattr(live, "ingest_fills", spy)
    assert await live._sweep_once(SimpleNamespace(isConnected=lambda: True)) == 1
    assert seen[0] != main
