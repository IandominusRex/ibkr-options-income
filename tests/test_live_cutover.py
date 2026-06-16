"""Tests for Phase 11: Live cutover + mode-flag logic.

All tests run without a live TWS connection — config and Telegram are monkeypatched.
DB tests use tmp_path + SQLite so they never touch production state.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from src.common.config import (
    ApprovalCfg,
    AutomationCfg,
    ClaudeCfg,
    Config,
    ExecutionCfg,
    IBKRCfg,
    LoggingCfg,
    MarketDataCfg,
    MonitorCfg,
    SchedulerCfg,
    Secrets,
    StorageCfg,
)
from src.common.schemas import (
    OptionRight,
    OrderState,
    ScoreCard,
    Strategy,
    TradeCandidate,
)
from src.storage.models import ApprovalRow, OrderRow

# --------------------------------------------------------------------------- #
# Helpers shared across tests
# --------------------------------------------------------------------------- #


def _make_config(live: bool) -> Config:
    """Construct a minimal Config without loading files or the real .env."""
    secrets = Secrets.model_construct(
        live_trading=live,
        ibkr_account="DU123456",
        telegram_bot_token="",
        telegram_chat_id="",
    )
    return Config(
        ibkr=IBKRCfg(paper_port=7497, live_port=7496),
        scheduler=SchedulerCfg(),
        market_data=MarketDataCfg(),
        claude=ClaudeCfg(),
        storage=StorageCfg(),
        logging=LoggingCfg(),
        approval=ApprovalCfg(),
        execution=ExecutionCfg(),
        monitor=MonitorCfg(),
        automation=AutomationCfg(),
        risk={},
        universe={},
        weights={},
        secrets=secrets,
    )


def _make_candidate(candidate_id: str = "cand-001") -> TradeCandidate:
    scores = ScoreCard(
        symbol="AAPL",
        iv_score=72.0,
        technical_score=65.0,
        fundamental_score=80.0,
        liquidity_score=90.0,
        assignment_safety_score=70.0,
    )
    return TradeCandidate(
        candidate_id=candidate_id,
        strategy=Strategy.CASH_SECURED_PUT,
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=185.0,
        expiry=date(2026, 7, 18),
        contracts=1,
        premium=1.55,
        collateral=18_500.0,
        roc_pct=0.84,
        annualized_yield_pct=19.0,
        breakeven=183.45,
        prob_otm=0.75,
        delta=0.25,
        iv_rank=68.0,
        dte=49,
        scores=scores,
        blended_score=76.0,
    )


def _make_mock_ib() -> MagicMock:
    mock_ib = MagicMock()
    qualified = MagicMock()
    qualified.conId = 12345678
    mock_ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    ticker = MagicMock()
    ticker.bid = 1.44
    ticker.ask = 1.60
    ticker.modelGreeks = None  # no live greeks → send-time re-gate defers to decision-time gate
    mock_ib.reqMktData.return_value = ticker
    mock_ib.cancelMktData = MagicMock()
    mock_fill = MagicMock()
    mock_fill.execution.execId = "0001.01.01"
    mock_fill.commissionReport.commission = 0.65
    mock_trade = MagicMock()
    mock_trade.isDone.return_value = True
    mock_trade.order.orderId = 42
    mock_trade.orderStatus.status = "Filled"
    mock_trade.orderStatus.filled = 1.0
    mock_trade.orderStatus.avgFillPrice = 1.52
    mock_trade.fills = [mock_fill]
    mock_ib.placeOrder.return_value = mock_trade
    mock_ib.cancelOrder = MagicMock()
    return mock_ib


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


# --------------------------------------------------------------------------- #
# Port switch
# --------------------------------------------------------------------------- #


def test_ibkr_port_returns_live_port_when_live():
    cfg = _make_config(live=True)
    assert cfg.ibkr_port == 7496


def test_ibkr_port_returns_paper_port_when_not_live():
    cfg = _make_config(live=False)
    assert cfg.ibkr_port == 7497


def test_is_live_reflects_secrets_flag():
    assert _make_config(live=True).is_live is True
    assert _make_config(live=False).is_live is False


# --------------------------------------------------------------------------- #
# Live confirmation in executor
# --------------------------------------------------------------------------- #


async def test_live_confirm_timeout_cancels_order(monkeypatch, tmp_path):
    """When live confirmation is not received, the order must be CANCELLED."""
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.is_live = True
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)

    # Patch asyncio.wait_for to raise TimeoutError without actually waiting.
    async def _immediate_timeout(coro, timeout):
        if hasattr(coro, "close"):
            coro.close()
        raise TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", _immediate_timeout)

    with dbmod.session_scope() as session:
        order = OrderRow(candidate_id="cand-001", state=OrderState.QUEUED)
        session.add(order)
        session.flush()
        order_id = order.id

    from src.execution.executor import execute_candidate

    mock_ib = _make_mock_ib()
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()

    # No one calls resolve_live_confirm, so the event would never fire.
    await execute_candidate(mock_ib, mock_bot, "99999", order_id, _make_candidate())

    with dbmod.session_scope() as s:
        row = s.get(OrderRow, order_id)

    assert row.state == OrderState.CANCELLED
    assert "timeout" in (row.detail or "").lower()
    # Timeout alert must have been sent to Telegram.
    timeout_msgs = [
        c
        for c in mock_bot.send_message.call_args_list
        if "timed out" in str(c).lower() or "not placed" in str(c).lower()
    ]
    assert len(timeout_msgs) >= 1


async def test_live_confirm_timeout_does_not_place_order(monkeypatch, tmp_path):
    """ib.placeOrder must NOT be called if live confirmation times out."""
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.is_live = True
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)

    async def _immediate_timeout(coro, timeout):
        if hasattr(coro, "close"):
            coro.close()
        raise TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", _immediate_timeout)

    with dbmod.session_scope() as session:
        order = OrderRow(candidate_id="cand-001", state=OrderState.QUEUED)
        session.add(order)
        session.flush()
        order_id = order.id

    from src.execution.executor import execute_candidate

    mock_ib = _make_mock_ib()
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()

    await execute_candidate(mock_ib, mock_bot, "99999", order_id, _make_candidate())

    mock_ib.placeOrder.assert_not_called()


async def test_live_confirm_resolve_sets_event(monkeypatch, tmp_path):
    """resolve_live_confirm must set the event and return True."""
    from src.execution.executor import register_live_confirm, resolve_live_confirm

    event = register_live_confirm(order_id=9999)
    assert not event.is_set()

    result = resolve_live_confirm(9999)

    assert result is True
    assert event.is_set()


def test_live_confirm_resolve_returns_false_for_unknown_id():
    from src.execution.executor import resolve_live_confirm

    result = resolve_live_confirm(order_id=99998877)
    assert result is False


async def test_paper_mode_skips_live_confirmation(monkeypatch, tmp_path):
    """In paper mode, execute_candidate must NOT wait for live confirmation."""
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.is_live = False  # paper mode
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)

    with dbmod.session_scope() as session:
        order = OrderRow(candidate_id="cand-001", state=OrderState.QUEUED)
        session.add(order)
        session.flush()
        order_id = order.id

    from src.execution.executor import execute_candidate

    mock_ib = _make_mock_ib()
    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock()

    await execute_candidate(mock_ib, mock_bot, "99999", order_id, _make_candidate())

    # Paper mode: placeOrder is called, live confirm message is NOT sent.
    mock_ib.placeOrder.assert_called_once()
    confirm_msgs = [c for c in mock_bot.send_message.call_args_list if "CONFIRM LIVE" in str(c)]
    assert len(confirm_msgs) == 0
