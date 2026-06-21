"""Tests for the buy-to-close path (SYSTEM_REVIEW F1).

The auto-close must route through the OrderRow/FillRow lifecycle, cancel on timeout,
and be idempotent at the contract level so the next intraday cycle can't stack a
second buy-to-close on a position whose close is still working.

All IB calls are mocked; the DB uses tmp_path SQLite.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import OptionRight, OrderState, PositionSnapshot
from src.execution.position_manager import close_candidate_id, close_short_position
from src.storage.models import FillRow, OrderRow

_TODAY = date.today()


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _mock_cfg(monkeypatch, fill_timeout_minutes: float = 5.0, is_live: bool = False) -> None:
    import src.execution.position_manager as pm

    cfg = MagicMock()
    cfg.is_live = is_live
    cfg.execution.fill_timeout_minutes = fill_timeout_minutes
    monkeypatch.setattr(pm, "get_config", lambda: cfg)
    # Make sleeps instant so the timeout path doesn't really wait.
    monkeypatch.setattr(pm.asyncio, "sleep", AsyncMock())


def _make_pos() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="AAPL  260117P00185000",
        sec_type="OPT",
        position=-2.0,  # short 2 contracts
        avg_cost=1.55,
        right=OptionRight.PUT,
        strike=185.0,
        expiry=_TODAY + timedelta(days=30),
        underlying="AAPL",
    )


def _make_close_ib(
    filled: bool = True, fill_qty: float = 2.0, avg_price: float = 0.40
) -> MagicMock:
    ib = MagicMock()
    qualified = MagicMock()
    qualified.conId = 99999999
    ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])

    fill = MagicMock()
    fill.execution.execId = "0002.02.02"
    fill.commissionReport.commission = 0.65

    trade = MagicMock()
    trade.isDone.return_value = filled  # if not filled → timeout/cancel path
    trade.order.orderId = 77
    trade.orderStatus.filled = fill_qty if filled else 0.0
    trade.orderStatus.avgFillPrice = avg_price if filled else 0.0
    trade.fills = [fill] if filled else []

    ib.placeOrder.return_value = trade
    ib.cancelOrder = MagicMock()
    return ib


def test_close_candidate_id_is_deterministic():
    pos = _make_pos()
    assert close_candidate_id(pos) == close_candidate_id(_make_pos())
    assert close_candidate_id(pos).startswith("close:AAPL:")


async def test_close_writes_order_and_buy_fill(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)
    ib = _make_close_ib(filled=True, fill_qty=2.0, avg_price=0.40)

    result = await close_short_position(ib, _make_pos(), bid=0.38, ask=0.42)

    assert result.status == "filled"
    assert result.filled_qty == 2.0
    ib.placeOrder.assert_called_once()

    from src.storage.db import session_scope

    with session_scope() as s:
        orders = s.query(OrderRow).all()
        fills = s.query(FillRow).all()
        assert len(orders) == 1
        assert orders[0].state == OrderState.FILLED
        assert len(fills) == 1
        assert fills[0].action == "BUY"  # buy-to-close debit → EOD cashflow sign
        assert fills[0].filled_qty == 2.0


async def test_close_is_idempotent_no_double_order(tmp_path, monkeypatch):
    """A second close while the first is still active must not place a second order (F1)."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch)

    # First close fills.
    ib1 = _make_close_ib(filled=True)
    first = await close_short_position(ib1, _make_pos(), bid=0.38, ask=0.42)
    assert first.status == "filled"

    # Second close on the same contract — a FILLED order is an active order → skipped.
    ib2 = _make_close_ib(filled=True)
    second = await close_short_position(ib2, _make_pos(), bid=0.38, ask=0.42)
    assert second.status == "skipped"
    ib2.placeOrder.assert_not_called()

    from src.storage.db import session_scope

    with session_scope() as s:
        assert s.query(OrderRow).count() == 1


async def test_close_cancels_on_timeout(tmp_path, monkeypatch):
    """No fill before the deadline → cancelOrder called, OrderRow ends CANCELLED (F1)."""
    _db_setup(tmp_path, monkeypatch)
    _mock_cfg(monkeypatch, fill_timeout_minutes=0.0)  # deadline already passed
    ib = _make_close_ib(filled=False)

    result = await close_short_position(ib, _make_pos(), bid=0.38, ask=0.42)

    assert result.status == "working"
    ib.cancelOrder.assert_called_once()

    from src.storage.db import session_scope

    with session_scope() as s:
        orders = s.query(OrderRow).all()
        assert len(orders) == 1
        assert orders[0].state == OrderState.CANCELLED
        assert s.query(FillRow).count() == 0


async def test_close_reprice_steps_toward_ask(tmp_path, monkeypatch):
    """With chase enabled, an unfilled buy-to-close is repriced upward toward the ask (C5)."""
    _db_setup(tmp_path, monkeypatch)
    import src.execution.position_manager as pm

    cfg = MagicMock()
    cfg.is_live = False
    cfg.execution.fill_timeout_minutes = 1
    cfg.execution.reprice_enabled = True
    cfg.execution.reprice_interval_seconds = 0.0  # reprice on the first poll
    cfg.execution.max_reprices = 1
    cfg.execution.reprice_step_pct = 0.5
    monkeypatch.setattr(pm, "get_config", lambda: cfg)
    monkeypatch.setattr(pm.asyncio, "sleep", AsyncMock())
    # Stub _refetch_bid_ask so the reprice step has known bid/ask without calling executor's config.
    monkeypatch.setattr(pm, "_refetch_bid_ask", AsyncMock(return_value=(0.38, 0.42)))

    ib = _make_close_ib(filled=True, fill_qty=2.0, avg_price=0.41)
    # isDone: False×2 (enter loop + reprice guard), then True (exit).
    calls: dict[str, int] = {"n": 0}

    def _isdone() -> bool:
        calls["n"] += 1
        return calls["n"] >= 3

    ib.placeOrder.return_value.isDone.side_effect = _isdone

    result = await close_short_position(ib, _make_pos(), bid=0.38, ask=0.42)

    assert result.status == "filled"
    # Two placeOrder calls: initial mid-price order + one reprice toward the ask.
    assert ib.placeOrder.call_count == 2

    from src.storage.db import session_scope

    with session_scope() as s:
        row = s.query(OrderRow).first()
        # Initial mid = (0.38+0.42)/2 = 0.40; reprice("BUY", 0.40, ask=0.42, step=0.5) = 0.41.
        assert row.limit_price == pytest.approx(0.41)
