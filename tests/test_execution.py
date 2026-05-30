"""Tests for Phase 7: Execution Engine.

All IB and Telegram calls are mocked — no TWS or live Telegram API needed.
DB tests use tmp_path + SQLite so they never touch production state.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import (
    AccountSnapshot,
    ApprovalStatus,
    OptionQuote,
    OptionRight,
    OrderState,
    ScoreCard,
    Strategy,
    TradeCandidate,
    Verdict,
)
from src.execution.order_builder import build_limit_order
from src.storage.models import ApprovalRow, FillRow, OrderRow

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _make_candidate(
    candidate_id: str = "cand-001",
    underlying: str = "AAPL",
    strategy: Strategy = Strategy.CASH_SECURED_PUT,
    premium: float = 1.55,
    roc_pct: float = 1.8,
    annualized_yield_pct: float = 22.0,
    contracts: int = 1,
    collateral: float = 3_800.0,
    delta: float = 0.25,
    dte: int = 30,
) -> TradeCandidate:
    scores = ScoreCard(
        symbol=underlying,
        iv_score=75.0,
        technical_score=65.0,
        fundamental_score=80.0,
        liquidity_score=88.0,
        assignment_safety_score=72.0,
    )
    return TradeCandidate(
        candidate_id=candidate_id,
        strategy=strategy,
        underlying=underlying,
        right=OptionRight.PUT,
        strike=185.0,
        expiry=date(2026, 7, 18),
        contracts=contracts,
        premium=premium,
        collateral=collateral,
        roc_pct=roc_pct,
        annualized_yield_pct=annualized_yield_pct,
        breakeven=183.45,
        prob_profit=0.75,
        delta=delta,
        iv_rank=68.0,
        dte=dte,
        scores=scores,
        blended_score=77.2,
    )


def _make_quote(bid: float | None = 1.50, ask: float | None = 1.60) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=185.0,
        expiry=date(2026, 7, 18),
        bid=bid,
        ask=ask,
    )


def _make_account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=200_000.0,
        total_cash=150_000.0,
        buying_power=120_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=110_000.0,
    )


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


# --------------------------------------------------------------------------- #
# order_builder
# --------------------------------------------------------------------------- #


def test_build_limit_order_rounds_to_tick():
    """Mid of 1.52 should round to 1.50 (nearest $0.05)."""
    quote = _make_quote(bid=1.44, ask=1.60)  # mid = 1.52
    order = build_limit_order(_make_candidate(), quote)
    assert order.lmtPrice == 1.50


def test_build_limit_order_rounds_up_to_tick():
    """Mid of 1.53 should round to 1.55 (nearest $0.05)."""
    quote = _make_quote(bid=1.46, ask=1.60)  # mid = 1.53
    order = build_limit_order(_make_candidate(), quote)
    assert order.lmtPrice == 1.55


def test_build_limit_order_exact_tick_unchanged():
    """Mid of 1.50 exactly should stay 1.50."""
    quote = _make_quote(bid=1.40, ask=1.60)  # mid = 1.50
    order = build_limit_order(_make_candidate(), quote)
    assert order.lmtPrice == 1.50


def test_build_limit_order_raises_on_no_mid_both_none():
    quote = _make_quote(bid=None, ask=None)
    with pytest.raises(ValueError, match="No mid price"):
        build_limit_order(_make_candidate(), quote)


def test_build_limit_order_raises_on_no_mid_missing_ask():
    quote = _make_quote(bid=1.50, ask=None)
    with pytest.raises(ValueError, match="No mid price"):
        build_limit_order(_make_candidate(), quote)


def test_build_limit_order_is_sell_day():
    quote = _make_quote()
    order = build_limit_order(_make_candidate(), quote)
    assert order.action == "SELL"
    assert order.tif == "DAY"


def test_build_limit_order_uses_candidate_contracts():
    quote = _make_quote()
    order = build_limit_order(_make_candidate(contracts=3), quote)
    assert order.totalQuantity == 3


# --------------------------------------------------------------------------- #
# executor — execute_candidate
# --------------------------------------------------------------------------- #


def _make_mock_ib(filled: bool = True, fill_qty: float = 1.0, avg_price: float = 1.52) -> MagicMock:
    mock_ib = MagicMock()

    qualified = MagicMock()
    qualified.conId = 12345678
    mock_ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])

    ticker = MagicMock()
    ticker.bid = 1.44
    ticker.ask = 1.60
    # No live greeks in the mock → send-time re-gate degrades to the decision-time gate
    # (delta is only enforced live when greeks are actually present).
    ticker.modelGreeks = None
    mock_ib.reqMktData.return_value = ticker
    mock_ib.cancelMktData = MagicMock()

    mock_fill = MagicMock()
    mock_fill.execution.execId = "0001.01.01"
    mock_fill.execution.shares = fill_qty
    mock_fill.execution.avgPrice = avg_price
    mock_fill.commissionReport.commission = 0.65

    mock_trade = MagicMock()
    mock_trade.isDone.return_value = True
    mock_trade.order.orderId = 42
    mock_trade.orderStatus.status = "Filled" if filled else "Inactive"
    mock_trade.orderStatus.filled = fill_qty if filled else 0.0
    mock_trade.orderStatus.avgFillPrice = avg_price if filled else 0.0
    mock_trade.fills = [mock_fill] if filled else []

    mock_ib.placeOrder.return_value = mock_trade
    mock_ib.cancelOrder = MagicMock()

    return mock_ib


def _make_mock_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


async def test_execute_candidate_writes_fill_row(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)

    from sqlalchemy import select

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.is_live = False
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)

    with dbmod.session_scope() as session:
        order = OrderRow(candidate_id="cand-001", state=OrderState.QUEUED)
        session.add(order)
        session.flush()
        order_id = order.id

    from src.execution.executor import execute_candidate

    mock_ib = _make_mock_ib(filled=True, fill_qty=1.0, avg_price=1.52)
    mock_bot = _make_mock_bot()

    await execute_candidate(mock_ib, mock_bot, "99999", order_id, _make_candidate())

    with dbmod.session_scope() as s:
        fills = s.execute(select(FillRow).where(FillRow.order_id == order_id)).scalars().all()
        order_row = s.get(OrderRow, order_id)

    assert len(fills) == 1
    assert fills[0].filled_qty == 1.0
    assert fills[0].avg_price == pytest.approx(1.52)
    assert fills[0].is_live is False
    assert order_row.state == OrderState.FILLED
    assert order_row.filled_qty == 1.0


async def test_execute_candidate_sends_telegram_confirmation(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.is_live = False
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)

    with dbmod.session_scope() as session:
        order = OrderRow(candidate_id="cand-001", state=OrderState.QUEUED)
        session.add(order)
        session.flush()
        order_id = order.id

    from src.execution.executor import execute_candidate

    mock_ib = _make_mock_ib(filled=True)
    mock_bot = _make_mock_bot()

    await execute_candidate(mock_ib, mock_bot, "99999", order_id, _make_candidate())

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "AAPL" in call_kwargs["text"]
    assert "Filled" in call_kwargs["text"]


async def test_execute_candidate_marks_rejected_on_ib_reject(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.is_live = False
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)

    with dbmod.session_scope() as session:
        order = OrderRow(candidate_id="cand-001", state=OrderState.QUEUED)
        session.add(order)
        session.flush()
        order_id = order.id

    from src.execution.executor import execute_candidate

    mock_ib = _make_mock_ib(filled=False)
    mock_ib.placeOrder.return_value.orderStatus.status = "Inactive"
    mock_bot = _make_mock_bot()

    await execute_candidate(mock_ib, mock_bot, "99999", order_id, _make_candidate())

    with dbmod.session_scope() as s:
        row = s.get(OrderRow, order_id)

    assert row.state == OrderState.REJECTED
    mock_bot.send_message.assert_called_once()
    assert "rejected" in mock_bot.send_message.call_args.kwargs["text"].lower()


async def test_execute_candidate_marks_rejected_on_qualify_failure(monkeypatch, tmp_path):
    """Qualification failure must mark the order REJECTED without re-raising."""
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.execution.quote_timeout_seconds = 5.0
    mock_cfg.is_live = False
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)

    with dbmod.session_scope() as session:
        order = OrderRow(candidate_id="cand-001", state=OrderState.QUEUED)
        session.add(order)
        session.flush()
        order_id = order.id

    from src.execution.executor import execute_candidate

    mock_ib = _make_mock_ib()
    # Return empty list — qualification failure
    mock_ib.qualifyContractsAsync = AsyncMock(return_value=[])
    mock_bot = _make_mock_bot()

    # Must NOT raise — executor handles the exception gracefully to protect the approval loop.
    await execute_candidate(mock_ib, mock_bot, "99999", order_id, _make_candidate())

    with dbmod.session_scope() as s:
        row = s.get(OrderRow, order_id)
    assert row.state == OrderState.REJECTED


# --------------------------------------------------------------------------- #
# approval — process_queued_orders
# --------------------------------------------------------------------------- #


def _insert_queued_order(
    session,
    candidate_id: str = "cand-001",
    expires_at: datetime | None = None,
) -> tuple[int, int]:
    """Insert an ApprovalRow + QUEUED OrderRow; return (approval_id, order_id)."""
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(hours=1)
    approval = ApprovalRow(
        candidate_id=candidate_id,
        status=ApprovalStatus.APPROVED,
        expires_at=expires_at,
    )
    session.add(approval)
    session.flush()
    order = OrderRow(
        candidate_id=candidate_id,
        approval_id=approval.id,
        state=OrderState.QUEUED,
    )
    session.add(order)
    session.flush()
    return approval.id, order.id


def _insert_candidate_row(session, candidate: TradeCandidate) -> None:
    from src.storage.models import CandidateRow

    row = CandidateRow(
        candidate_id=candidate.candidate_id,
        run_id="run-test",
        strategy=candidate.strategy.value,
        underlying=candidate.underlying,
        right=candidate.right.value,
        strike=candidate.strike,
        expiry=candidate.expiry,
        blended_score=candidate.blended_score,
        payload=candidate.model_dump(mode="json"),
    )
    session.add(row)


async def test_process_queued_orders_expires_ttl(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.secrets.ibkr_account = ""
    mock_cfg.execution.transmit_only_in_rth = False
    monkeypatch.setattr("src.execution.approval.get_config", lambda: mock_cfg)

    expired_at = datetime.now(UTC) - timedelta(minutes=5)
    with dbmod.session_scope() as session:
        approval_id, order_id = _insert_queued_order(session, "cand-ttl", expires_at=expired_at)

    from src.execution.approval import process_queued_orders

    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    mock_bot = AsyncMock()

    await process_queued_orders(mock_ib, mock_bot, "99999")

    with dbmod.session_scope() as s:
        approval = s.get(ApprovalRow, approval_id)
        order = s.get(OrderRow, order_id)

    assert approval.status == ApprovalStatus.EXPIRED
    assert order.state == OrderState.CANCELLED
    assert order.detail == "TTL expired"


async def test_process_queued_orders_defers_outside_rth(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.secrets.ibkr_account = ""
    mock_cfg.execution.transmit_only_in_rth = True
    monkeypatch.setattr("src.execution.approval.get_config", lambda: mock_cfg)
    monkeypatch.setattr("src.execution.approval._is_rth", lambda: False)

    with dbmod.session_scope() as session:
        _, order_id = _insert_queued_order(session, "cand-rth")

    from src.execution.approval import process_queued_orders

    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    mock_ib.accountSummary.return_value = []
    mock_ib.portfolio.return_value = []
    mock_bot = AsyncMock()

    await process_queued_orders(mock_ib, mock_bot, "99999")

    with dbmod.session_scope() as s:
        order = s.get(OrderRow, order_id)

    # Must still be QUEUED — deferred, not cancelled
    assert order.state == OrderState.QUEUED


async def test_process_queued_orders_cancels_if_candidate_not_found(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.secrets.ibkr_account = ""
    mock_cfg.execution.transmit_only_in_rth = False
    monkeypatch.setattr("src.execution.approval.get_config", lambda: mock_cfg)
    monkeypatch.setattr("src.execution.approval._is_rth", lambda: True)

    account_snap = _make_account()
    monkeypatch.setattr(
        "src.execution.approval.get_account_snapshot", lambda ib, acct: account_snap
    )
    monkeypatch.setattr("src.execution.approval.get_positions", lambda ib: [])

    with dbmod.session_scope() as session:
        # Insert order but no CandidateRow
        _, order_id = _insert_queued_order(session, "missing-cand")

    from src.execution.approval import process_queued_orders

    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    mock_bot = AsyncMock()

    await process_queued_orders(mock_ib, mock_bot, "99999")

    with dbmod.session_scope() as s:
        order = s.get(OrderRow, order_id)

    assert order.state == OrderState.CANCELLED
    assert "not found" in (order.detail or "").lower()


async def test_process_queued_orders_cancels_if_revalidation_fails(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.secrets.ibkr_account = ""
    mock_cfg.execution.transmit_only_in_rth = False
    monkeypatch.setattr("src.execution.approval.get_config", lambda: mock_cfg)
    monkeypatch.setattr("src.execution.approval._is_rth", lambda: True)

    account_snap = _make_account()
    monkeypatch.setattr(
        "src.execution.approval.get_account_snapshot", lambda ib, acct: account_snap
    )
    monkeypatch.setattr("src.execution.approval.get_positions", lambda ib: [])

    from src.common.schemas import RiskVerdict

    mock_verdict = RiskVerdict(
        candidate_id="cand-001",
        verdict=Verdict.REJECT,
        reasons=["margin_limit"],
    )
    monkeypatch.setattr(
        "src.execution.approval.validate_candidates",
        lambda candidates, account, positions: [mock_verdict],
    )

    candidate = _make_candidate()
    with dbmod.session_scope() as session:
        _insert_candidate_row(session, candidate)
        _, order_id = _insert_queued_order(session, candidate.candidate_id)

    from src.execution.approval import process_queued_orders

    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    mock_bot = AsyncMock()

    await process_queued_orders(mock_ib, mock_bot, "99999")

    with dbmod.session_scope() as s:
        order = s.get(OrderRow, order_id)

    assert order.state == OrderState.CANCELLED
    assert "Re-validation failed" in (order.detail or "")


async def test_process_queued_orders_calls_execute_for_valid_order(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.secrets.ibkr_account = ""
    mock_cfg.execution.transmit_only_in_rth = False
    monkeypatch.setattr("src.execution.approval.get_config", lambda: mock_cfg)
    monkeypatch.setattr("src.execution.approval._is_rth", lambda: True)

    account_snap = _make_account()
    monkeypatch.setattr(
        "src.execution.approval.get_account_snapshot", lambda ib, acct: account_snap
    )
    monkeypatch.setattr("src.execution.approval.get_positions", lambda ib: [])

    from src.common.schemas import RiskVerdict

    mock_verdict = RiskVerdict(candidate_id="cand-001", verdict=Verdict.PASS, reasons=[])
    monkeypatch.setattr(
        "src.execution.approval.validate_candidates",
        lambda candidates, account, positions: [mock_verdict],
    )

    executed: list[tuple] = []

    async def mock_execute(ib, bot, chat_id, order_id, candidate):
        executed.append((order_id, candidate.candidate_id))

    monkeypatch.setattr("src.execution.approval.execute_candidate", mock_execute)

    candidate = _make_candidate()
    with dbmod.session_scope() as session:
        _insert_candidate_row(session, candidate)
        _, order_id = _insert_queued_order(session, candidate.candidate_id)

    from src.execution.approval import process_queued_orders

    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    mock_bot = AsyncMock()

    await process_queued_orders(mock_ib, mock_bot, "99999")

    assert len(executed) == 1
    assert executed[0][0] == order_id
    assert executed[0][1] == candidate.candidate_id
