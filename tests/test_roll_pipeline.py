"""N20: a roll trigger becomes an approvable candidate → QUEUED ROLL order on approve."""

from __future__ import annotations

from datetime import date, timedelta

from src.common.schemas import IVStats, OptionQuote, OptionRight, PositionSnapshot, TechnicalStats

_TODAY = date.today()
_NEAR = _TODAY + timedelta(days=10)  # existing short, DTE 10 → triggers roll
_FAR = _TODAY + timedelta(days=42)  # new leg, in the CC [21, 45] window


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _quote(strike, expiry, delta, bid, ask) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=strike,
        expiry=expiry,
        bid=bid,
        ask=ask,
        volume=500,
        open_interest=2000,
        delta=delta,
        iv=0.30,
    )


def _short_call() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="AAPL",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.30,
        right=OptionRight.CALL,
        strike=200.0,
        expiry=_NEAR,
        delta=0.55,  # >0.40 → roll trigger
        underlying="AAPL",
    )


def _quotes() -> list[OptionQuote]:
    # Current short (to infer its live mid) + a new further-dated leg with a net credit.
    return [
        _quote(200.0, _NEAR, 0.55, 0.05, 0.15),  # current contract, mid ≈ 0.10
        _quote(205.0, _FAR, 0.28, 3.40, 3.60),  # new leg, mid ≈ 3.50 → credit ≈ 3.40
    ]


def test_queue_roll_for_approval_persists_candidate_and_approval(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from sqlalchemy import select

    from src.execution.roll_pipeline import queue_roll_for_approval
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow, CandidateRow

    iv = IVStats(symbol="AAPL", current_iv=30.0, iv_rank=60.0)
    tech = TechnicalStats(symbol="AAPL", price=198.0, rsi_14=55.0, regime=None)

    result = queue_roll_for_approval(
        _short_call(), _quotes(), iv, tech, chat_id="99999", ttl_minutes=120
    )
    assert result is not None
    approval_id, cand = result
    assert cand.strategy.value == "roll"

    with session_scope() as s:
        crow = s.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == cand.candidate_id)
        ).scalar_one()
        approval = s.get(ApprovalRow, approval_id)
        assert crow.strategy == "roll"
        assert approval.status == "pending"
        assert approval.snapshot is not None  # frozen approved payload (N2a)
        assert approval.snapshot["strategy"] == "roll"


def test_queue_roll_returns_none_without_candidates(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.execution.roll_pipeline import queue_roll_for_approval

    iv = IVStats(symbol="AAPL", current_iv=30.0, iv_rank=60.0)
    tech = TechnicalStats(symbol="AAPL", price=198.0, rsi_14=55.0, regime=None)
    # A long position never rolls → no candidate, no approval.
    long_pos = _short_call().model_copy(update={"position": 1.0})
    assert (
        queue_roll_for_approval(long_pos, _quotes(), iv, tech, chat_id="1", ttl_minutes=120) is None
    )


def test_approving_a_roll_queues_a_roll_order(tmp_path, monkeypatch):
    """End-to-end DB wiring: the approval handler turns the PENDING roll into a QUEUED ROLL
    OrderRow carrying the frozen snapshot — which process_queued_orders routes to execute_roll."""
    _db_setup(tmp_path, monkeypatch)
    from sqlalchemy import select

    from src.execution.roll_pipeline import queue_roll_for_approval
    from src.notify.approval_service import _process_button
    from src.storage.db import session_scope
    from src.storage.models import OrderRow

    iv = IVStats(symbol="AAPL", current_iv=30.0, iv_rank=60.0)
    tech = TechnicalStats(symbol="AAPL", price=198.0, rsi_14=55.0, regime=None)
    approval_id, cand = queue_roll_for_approval(  # type: ignore[misc]
        _short_call(), _quotes(), iv, tech, chat_id="99999", ttl_minutes=120
    )

    found, text, _ = _process_button(approval_id, "approve")
    assert found and "queued" in text.lower()

    with session_scope() as s:
        order = s.execute(
            select(OrderRow).where(OrderRow.candidate_id == cand.candidate_id)
        ).scalar_one()
        assert order.state == "queued"
        assert order.snapshot is not None and order.snapshot["strategy"] == "roll"
