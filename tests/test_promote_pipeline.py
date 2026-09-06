"""M4 Task 4.2: a fresh candidate becomes an approvable PENDING proposal, once."""

from __future__ import annotations

from datetime import date, timedelta

from src.common.schemas import (
    OptionRight,
    OrderState,
    ScoreCard,
    Strategy,
    TradeCandidate,
)

_EXPIRY = date.today() + timedelta(days=30)


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _candidate(
    candidate_id: str = "nvda-csp-1",
    *,
    underlying: str = "NVDA",
    strategy: Strategy = Strategy.CASH_SECURED_PUT,
    strike: float = 180.0,
    premium: float = 2.50,
    blended_score: float = 77.0,
) -> TradeCandidate:
    scores = ScoreCard(symbol=underlying, iv_score=70.0, technical_score=65.0)
    return TradeCandidate(
        candidate_id=candidate_id,
        strategy=strategy,
        underlying=underlying,
        right=OptionRight.PUT if strategy == Strategy.CASH_SECURED_PUT else OptionRight.CALL,
        strike=strike,
        expiry=_EXPIRY,
        contracts=1,
        premium=premium,
        collateral=18_000.0,
        roc_pct=1.4,
        annualized_yield_pct=17.0,
        breakeven=strike - premium,
        prob_otm=0.75,
        delta=-0.25,
        iv_rank=60.0,
        current_iv=32.0,
        dte=30,
        scores=scores,
        blended_score=blended_score,
    )


def test_queue_promoted_for_approval_persists_candidate_and_approval(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from sqlalchemy import select

    from src.execution.promote_pipeline import queue_promoted_for_approval
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow, CandidateRow

    cand = _candidate()
    approval_id = queue_promoted_for_approval(cand, chat_id="99999", ttl_minutes=60)
    assert approval_id is not None

    with session_scope() as s:
        crow = s.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == cand.candidate_id)
        ).scalar_one()
        approval = s.get(ApprovalRow, approval_id)
        assert crow.strategy == "cash_secured_put"
        assert crow.run_id.startswith("promote-")
        assert approval.status == "pending"
        assert approval.chat_id == "99999"
        assert approval.snapshot is not None  # frozen approved payload (N2a)
        assert approval.snapshot["premium"] == 2.50
        assert approval.snapshot["strategy"] == "cash_secured_put"


def test_queue_promoted_for_approval_never_creates_an_approved_approval(tmp_path, monkeypatch):
    """A promote raises a proposal. Approving it is a separate human act."""
    _db_setup(tmp_path, monkeypatch)
    from src.execution.promote_pipeline import queue_promoted_for_approval
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow, OrderRow

    cand = _candidate()
    approval_id = queue_promoted_for_approval(cand, chat_id="99999", ttl_minutes=60)
    assert approval_id is not None

    with session_scope() as s:
        approval = s.get(ApprovalRow, approval_id)
        assert approval.status != "approved"
        order = s.query(OrderRow).filter(OrderRow.approval_id == approval_id).one_or_none()
        assert order is None


def test_queue_promoted_for_approval_upserts_the_candidate_row(tmp_path, monkeypatch):
    """A second promote of the same candidate_id replaces, not duplicates, the CandidateRow."""
    _db_setup(tmp_path, monkeypatch)
    from sqlalchemy import select

    from src.execution.promote_pipeline import queue_promoted_for_approval
    from src.storage.db import session_scope
    from src.storage.models import CandidateRow

    cand = _candidate(premium=2.50)
    queue_promoted_for_approval(cand, chat_id="1", ttl_minutes=60)

    # A fresh run repriced the same contract at a different premium.
    reprice = _candidate(premium=2.75)
    queue_promoted_for_approval(reprice, chat_id="1", ttl_minutes=60)

    with session_scope() as s:
        rows = s.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == cand.candidate_id)
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload["premium"] == 2.75


def test_queue_promoted_for_approval_returns_none_when_an_order_is_already_active(
    tmp_path, monkeypatch
):
    """Idempotent against a replayed drain: an active order blocks a second approval."""
    _db_setup(tmp_path, monkeypatch)
    from datetime import UTC, datetime

    from src.execution.promote_pipeline import queue_promoted_for_approval
    from src.storage.db import session_scope
    from src.storage.models import OrderRow

    cand = _candidate()
    with session_scope() as s:
        s.add(
            OrderRow(
                candidate_id=cand.candidate_id,
                approval_id=1,
                state=OrderState.QUEUED,
                snapshot=cand.model_dump(mode="json"),
                created_at=datetime.now(UTC),
            )
        )

    assert queue_promoted_for_approval(cand, chat_id="1", ttl_minutes=60) is None
