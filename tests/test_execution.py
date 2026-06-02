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

_TODAY = date.today()

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
    delta: float = -0.25,  # negative for PUT (IBKR convention)
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
        expiry=_TODAY + timedelta(days=dte),  # keep expiry consistent with dte at run time
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
        expiry=_TODAY + timedelta(days=30),
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


def test_build_limit_order_penny_tick_below_3():
    """Sub-$3 premium uses $0.01 ticks (penny pilot): mid 1.523 → 1.52."""
    quote = _make_quote(bid=1.446, ask=1.60)  # mid = 1.523
    order = build_limit_order(_make_candidate(), quote)
    assert order.lmtPrice == 1.52


def test_build_limit_order_nickel_tick_at_or_above_3():
    """Premium >= $3 uses $0.05 ticks: mid 3.53 → 3.55."""
    quote = _make_quote(bid=3.51, ask=3.55)  # mid = 3.53
    order = build_limit_order(_make_candidate(), quote)
    assert order.lmtPrice == 3.55


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
    # Live greeks present by default: delta in the CSP range so the send-time re-gate passes,
    # IV available so entry_iv is captured (and the executor's greeks-wait exits immediately).
    # The degradation test overrides modelGreeks=None with a short quote_timeout.
    greeks = MagicMock()
    greeks.delta = -0.20
    greeks.impliedVol = 0.40
    ticker.modelGreeks = greeks
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


def test_record_outcome_sets_and_does_not_clobber(monkeypatch, tmp_path):
    """The learning loop records the eventual outcome and never overwrites a set one."""
    _db_setup(tmp_path, monkeypatch)

    from src.claude.memory import FILLED, USER_REJECTED, record_outcome
    from src.storage.db import session_scope
    from src.storage.models import ClaudeMemoryRow

    with session_scope() as s:
        s.add(
            ClaudeMemoryRow(
                scan_date=date.today(),
                underlying="AAPL",
                strategy_type="covered_call",
                recommendation="sell",
                candidate_id="cand-x",
            )
        )

    record_outcome("cand-x", FILLED)
    with session_scope() as s:
        row = s.query(ClaudeMemoryRow).filter_by(candidate_id="cand-x").one()
        assert row.outcome == "filled"
        assert row.outcome_date == date.today()

    # A later outcome must NOT clobber the recorded one.
    record_outcome("cand-x", USER_REJECTED)
    with session_scope() as s:
        row = s.query(ClaudeMemoryRow).filter_by(candidate_id="cand-x").one()
        assert row.outcome == "filled"

    # Unknown candidate / None are safe no-ops (never raise).
    record_outcome("does-not-exist", FILLED)
    record_outcome(None, FILLED)


async def test_execute_candidate_rejects_roll(monkeypatch, tmp_path):
    """A ROLL candidate must be refused outright — the single-leg executor can't place it."""
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

    mock_ib = _make_mock_ib()
    mock_bot = _make_mock_bot()

    await execute_candidate(
        mock_ib, mock_bot, "99999", order_id, _make_candidate(strategy=Strategy.ROLL)
    )

    with dbmod.session_scope() as s:
        row = s.get(OrderRow, order_id)
    assert row.state == OrderState.REJECTED
    mock_ib.placeOrder.assert_not_called()
    assert "ROLL" in mock_bot.send_message.call_args.kwargs["text"]


async def test_execute_candidate_stores_entry_iv(monkeypatch, tmp_path):
    """When the live quote carries greeks, the fill records entry_iv (IV-spike baseline)."""
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
    greeks = MagicMock()
    greeks.delta = -0.20  # in CSP range → live re-gate passes
    greeks.impliedVol = 0.42
    mock_ib.reqMktData.return_value.modelGreeks = greeks
    mock_bot = _make_mock_bot()

    await execute_candidate(mock_ib, mock_bot, "99999", order_id, _make_candidate())

    with dbmod.session_scope() as s:
        fill = s.execute(select(FillRow).where(FillRow.order_id == order_id)).scalars().one()
    assert fill.entry_iv == pytest.approx(0.42)


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


async def test_process_queued_orders_cumulative_regate_rejects_second(monkeypatch, tmp_path):
    """Two same-ticker QUEUED orders are re-validated as a BATCH: the first fits the per-ticker
    cap, the second breaches it cumulatively and is cancelled (cumulative-aware send-time gate)."""
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.secrets.ibkr_account = ""
    mock_cfg.execution.transmit_only_in_rth = False
    monkeypatch.setattr("src.execution.approval.get_config", lambda: mock_cfg)
    monkeypatch.setattr("src.execution.approval._is_rth", lambda: True)

    # net-liq 100k → 5% ticker cap = 5000. Two AAPL CSPs @ 4000 collateral each: first fits,
    # together (8000) they breach the cap. Use the REAL risk engine (not a monkeypatched stub).
    account_snap = AccountSnapshot(
        account="DU1",
        net_liquidation=100_000.0,
        total_cash=100_000.0,
        buying_power=90_000.0,
        maintenance_margin=0.0,
        excess_liquidity=90_000.0,
    )
    monkeypatch.setattr(
        "src.execution.approval.get_account_snapshot", lambda ib, acct: account_snap
    )
    monkeypatch.setattr("src.execution.approval.get_positions", lambda ib: [])

    executed: list[int] = []

    async def mock_execute(ib, bot, chat_id, order_id, candidate):
        executed.append(order_id)

    monkeypatch.setattr("src.execution.approval.execute_candidate", mock_execute)

    c1 = _make_candidate("c1", underlying="AAPL", collateral=4_000.0).model_copy(
        update={"blended_score": 90.0}
    )
    c2 = _make_candidate("c2", underlying="AAPL", collateral=4_000.0).model_copy(
        update={"blended_score": 80.0}
    )
    with dbmod.session_scope() as session:
        _insert_candidate_row(session, c1)
        _insert_candidate_row(session, c2)
        _, oid1 = _insert_queued_order(session, "c1")
        _, oid2 = _insert_queued_order(session, "c2")

    from src.execution.approval import process_queued_orders

    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU1"]
    mock_bot = AsyncMock()

    await process_queued_orders(mock_ib, mock_bot, "99999")

    # Highest-score order executes; the second is cancelled for the cumulative breach.
    assert executed == [oid1]
    with dbmod.session_scope() as s:
        assert s.get(OrderRow, oid2).state == OrderState.CANCELLED
        assert "Re-validation failed" in (s.get(OrderRow, oid2).detail or "")


async def test_execute_candidate_no_greeks_entry_iv_none(monkeypatch, tmp_path):
    """When model greeks never stream in, the order still fills (degradation) and entry_iv
    is recorded as None rather than blocking."""
    _db_setup(tmp_path, monkeypatch)

    from sqlalchemy import select

    import src.storage.db as dbmod

    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.execution.quote_timeout_seconds = 0.2  # short greeks wait → fast degradation
    mock_cfg.is_live = False
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)

    with dbmod.session_scope() as session:
        order = OrderRow(candidate_id="cand-001", state=OrderState.QUEUED)
        session.add(order)
        session.flush()
        order_id = order.id

    from src.execution.executor import execute_candidate

    mock_ib = _make_mock_ib(filled=True)
    mock_ib.reqMktData.return_value.modelGreeks = None  # greeks never arrive
    mock_bot = _make_mock_bot()

    await execute_candidate(mock_ib, mock_bot, "99999", order_id, _make_candidate())

    with dbmod.session_scope() as s:
        fill = s.execute(select(FillRow).where(FillRow.order_id == order_id)).scalars().one()
    assert fill.entry_iv is None
    assert fill.action == "SELL"


# --------------------------------------------------------------------------- #
# order_builder — bid=0 / ask>0 (P1-04)
# --------------------------------------------------------------------------- #


def test_build_limit_order_bid_zero_ask_positive():
    """bid=0.00 on a far-OTM option is valid; mid should be computed as ask/2."""
    from src.execution.order_builder import build_limit_order

    quote = _make_quote(bid=0.0, ask=0.10)
    order = build_limit_order(_make_candidate(), quote)
    # mid = (0.0 + 0.10) / 2 = 0.05, tick-rounded to 0.05
    assert order.lmtPrice == pytest.approx(0.05)
    assert order.action == "SELL"


def test_build_limit_order_none_bid_still_works():
    """bid=None with a valid ask should use 0 as the effective bid."""
    from src.execution.order_builder import build_limit_order

    quote = _make_quote(bid=None, ask=0.20)
    order = build_limit_order(_make_candidate(), quote)
    assert order.lmtPrice == pytest.approx(0.10)


# --------------------------------------------------------------------------- #
# approval — concurrent double-execution prevention (P0-11)
# --------------------------------------------------------------------------- #


async def test_process_button_concurrent_calls_produce_one_order(monkeypatch, tmp_path):
    """Two concurrent _process_button calls for the same PENDING approval must result in
    exactly one OrderRow — not two. This is the TOCTOU double-execution bug (P0-01).

    We simulate the race by calling _process_button twice in sequence (SQLite won't let two
    true concurrent writers in a unit test), but the UniqueConstraint on OrderRow.approval_id
    prevents the second insert from succeeding even when both reads see PENDING.
    """
    _db_setup(tmp_path, monkeypatch)

    import src.storage.db as dbmod
    from src.storage.models import ApprovalRow

    # Insert a PENDING approval.
    with dbmod.session_scope() as session:
        approval = ApprovalRow(
            candidate_id="double-exec",
            status=ApprovalStatus.PENDING,
            chat_id="99999",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(approval)
        session.flush()
        approval_id = approval.id

    from src.notify.approval_service import _process_button

    # First call — should succeed and create an OrderRow.
    found1, text1, _ = _process_button(approval_id, "approve")
    assert found1 is True
    assert "QUEUED" in text1

    # Second call — approval is now APPROVED, must be idempotent.
    found2, text2, _ = _process_button(approval_id, "approve")
    assert found2 is True
    assert "Already" in text2

    # Exactly one OrderRow must exist for this approval.
    with dbmod.session_scope() as s:
        from sqlalchemy import select

        orders = (
            s.execute(select(OrderRow).where(OrderRow.approval_id == approval_id)).scalars().all()
        )
    assert len(orders) == 1
    assert orders[0].state == OrderState.QUEUED
