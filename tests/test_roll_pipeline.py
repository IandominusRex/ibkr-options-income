"""N20 + roll redesign: a constructed roll becomes a PENDING approval → QUEUED ROLL order."""

from __future__ import annotations

from datetime import date, timedelta

from src.common.schemas import OptionRight, RollOrigin, ScoreCard, Strategy, TradeCandidate

_TODAY = date.today()
_OLD = _TODAY + timedelta(days=4)
_NEW = _TODAY + timedelta(days=11)


def _cand() -> TradeCandidate:
    return TradeCandidate(
        candidate_id="roll-aapl-195",
        strategy=Strategy.ROLL,
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=195.0,
        expiry=_NEW,
        contracts=1,
        premium=0.10,
        collateral=19_500.0,
        roc_pct=0.0,
        annualized_yield_pct=0.0,
        breakeven=194.9,
        dte=11,
        scores=ScoreCard(symbol="AAPL"),
        roll_from=RollOrigin(
            con_id=8,
            candidate_id="c0",
            strike=200.0,
            expiry=_OLD,
            right=OptionRight.PUT,
            contracts=1,
            chain_id="c0",
            seq=1,
            original_expiry=_OLD,
            old_mid=5.5,
            new_mid=5.6,
        ),
    )


def test_queue_roll_candidate_persists_candidate_and_frozen_approval(db) -> None:
    from sqlalchemy import select

    from src.execution.roll_pipeline import queue_roll_candidate
    from src.storage.models import ApprovalRow, CandidateRow

    approval_id = queue_roll_candidate(_cand(), chat_id="9", ttl_minutes=120)
    assert approval_id is not None
    with db() as s:
        crow = s.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == "roll-aapl-195")
        ).scalar_one()
        approval = s.get(ApprovalRow, approval_id)
        assert crow.strategy == "roll"
        assert approval.status == "pending"
        assert approval.snapshot["roll_from"]["con_id"] == 8  # frozen payload (N2a)


def test_approving_a_roll_queues_a_roll_order(db) -> None:
    """The approval handler turns the PENDING roll into a QUEUED ROLL OrderRow carrying the
    frozen snapshot — which process_queued_orders routes to execute_roll."""
    from sqlalchemy import select

    from src.execution.roll_pipeline import queue_roll_candidate
    from src.notify.approval_service import _process_button
    from src.storage.models import OrderRow

    approval_id = queue_roll_candidate(_cand(), chat_id="9", ttl_minutes=120)
    assert approval_id is not None
    found, text, _ = _process_button(approval_id, "approve")
    assert found and "queued" in text.lower()
    with db() as s:
        order = s.execute(
            select(OrderRow).where(OrderRow.candidate_id == "roll-aapl-195")
        ).scalar_one()
        assert order.state == "queued"
        assert order.snapshot["roll_from"]["con_id"] == 8


def test_a_working_roll_order_blocks_a_second_queue(db) -> None:
    from src.execution.roll_pipeline import queue_roll_candidate
    from src.notify.approval_service import _process_button

    first = queue_roll_candidate(_cand(), chat_id="9", ttl_minutes=120)
    assert first is not None
    _process_button(first, "approve")
    assert queue_roll_candidate(_cand(), chat_id="9", ttl_minutes=120) is None


def test_a_partial_roll_order_is_not_a_pending_roll(db) -> None:
    """`partial` is final (the executor cancels the remainder at its timeout), so the monitor may
    re-evaluate the position. 2026-10-23: HIMS rolled 3 of 10 and sat as `partial`."""
    from src.common.schemas import OrderState, PositionSnapshot
    from src.execution.roll_pipeline import pending_roll_approval_for, queue_roll_candidate
    from src.notify.approval_service import _process_button
    from src.storage.db import session_scope
    from src.storage.models import OrderRow

    pos = PositionSnapshot(
        symbol="AAPL",
        sec_type="OPT",
        position=-1,
        avg_cost=5.0,
        right=OptionRight.PUT,
        strike=200.0,
        expiry=_OLD,
        underlying="AAPL",
        con_id=8,
    )
    first = queue_roll_candidate(_cand(), chat_id="9", ttl_minutes=120)
    assert first is not None
    _process_button(first, "approve")
    assert pending_roll_approval_for(pos) is not None  # queued, still pending
    with session_scope() as s:
        for order in s.query(OrderRow).all():
            order.state = OrderState.PARTIAL
    assert pending_roll_approval_for(pos) is None
