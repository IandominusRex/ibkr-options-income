"""N20: a roll trigger becomes an approvable candidate → QUEUED ROLL order on approve."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.market_hours import today_et
from src.common.schemas import (
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    Regime,
    TechnicalStats,
)

_TODAY = date.today()
_NEAR = _TODAY + timedelta(days=10)  # existing short, DTE 10 → triggers roll
_FAR = _TODAY + timedelta(days=26)  # new leg, in the CC [7, 28] window

_ET_TODAY = today_et()


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _pipeline_quote(strike, expiry, delta, bid, ask) -> OptionQuote:
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


def _pipeline_short_call() -> PositionSnapshot:
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
        _pipeline_quote(200.0, _NEAR, 0.55, 0.05, 0.15),  # current contract, mid ≈ 0.10
        _pipeline_quote(205.0, _FAR, 0.28, 3.40, 3.60),  # new leg, mid ≈ 3.50 → credit ≈ 3.40
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
        _pipeline_short_call(), _quotes(), iv, tech, chat_id="99999", ttl_minutes=120
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
    long_pos = _pipeline_short_call().model_copy(update={"position": 1.0})
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
        _pipeline_short_call(), _quotes(), iv, tech, chat_id="99999", ttl_minutes=120
    )

    found, text, _ = _process_button(approval_id, "approve")
    assert found and "queued" in text.lower()

    with session_scope() as s:
        order = s.execute(
            select(OrderRow).where(OrderRow.candidate_id == cand.candidate_id)
        ).scalar_one()
        assert order.state == "queued"
        assert order.snapshot is not None and order.snapshot["strategy"] == "roll"


# --------------------------------------------------------------------------------------- #
# D4: generate_roll_candidates defensive-vs-income economics + the today_et() date bug.
# Named `_short_call`/`_quote` below (distinct from `_pipeline_short_call`/`_pipeline_quote`
# above, which are keyword-positional and shaped for the queue_roll_for_approval tests) since
# these exercise `src.strategies.rolling.generate_roll_candidates` directly with a keyword-only
# signature matching the plan brief.
# --------------------------------------------------------------------------------------- #


def _short_call(*, delta: float, strike: float, dte: int) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="AAPL  CALL",
        sec_type="OPT",
        position=-1,
        avg_cost=100.0,
        right=OptionRight.CALL,
        strike=strike,
        expiry=_ET_TODAY + timedelta(days=dte),
        underlying="AAPL",
        delta=delta,
    )


def _quote(*, strike: float, dte: int, mid: float, delta: float) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=strike,
        expiry=_ET_TODAY + timedelta(days=dte),
        bid=round(mid - 0.05, 2),
        ask=round(mid + 0.05, 2),
        delta=delta,
        iv=0.30,
        open_interest=500,
        volume=100,
    )


def _roll_chain(
    *, current_mid: float, new_mid: float, new_delta: float, new_dte: int
) -> list[OptionQuote]:
    """The position's own contract (so _infer_current_mid resolves) plus one roll target."""
    return [
        _quote(strike=100.0, dte=10, mid=current_mid, delta=-0.62),
        _quote(strike=105.0, dte=new_dte, mid=new_mid, delta=new_delta),
    ]


def _iv() -> IVStats:
    return IVStats(symbol="AAPL", current_iv=30.0, iv_rank=55.0, hv_30=25.0)


def _tech() -> TechnicalStats:
    return TechnicalStats(symbol="AAPL", price=100.0, regime=Regime.SIDEWAYS)


def test_defensive_roll_allows_a_bounded_debit():
    """D4: a challenged 0.60-delta short cannot be rolled out for a credit."""
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.62, strike=100.0, dte=10)
    quotes = _roll_chain(current_mid=8.00, new_mid=7.70, new_delta=-0.30, new_dte=20)
    cands = generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=True)
    assert cands, "a defensive roll costing $0.30 must be offered"
    assert cands[0].premium == pytest.approx(-0.30, abs=0.01)


def test_defensive_roll_rejects_a_debit_above_the_cap():
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.62, strike=100.0, dte=10)
    quotes = _roll_chain(current_mid=8.00, new_mid=7.00, new_delta=-0.30, new_dte=20)
    assert not generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=True)


def test_defensive_roll_requires_delta_reduction():
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.62, strike=100.0, dte=10)
    quotes = _roll_chain(current_mid=8.00, new_mid=8.20, new_delta=-0.60, new_dte=20)
    assert not generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=True)


def test_defensive_roll_rejects_when_position_delta_is_unknown():
    """Fail-closed (code review finding, fix-round-1): the delta-reduction safety check must not
    be silently skipped just because the position snapshot carries no delta reading.
    `PositionSnapshot.delta` is `float | None`, and a monitor snapshot with no live delta must not
    let a defensive roll through unverified — the Interfaces spec requires the new leg to reduce
    |delta| by at least `min_delta_reduction` unconditionally, not only when delta is known.
    Otherwise identical to test_defensive_roll_allows_a_bounded_debit, which *would* qualify if
    delta were known — proving the rejection is specifically about the missing delta, not the
    debit or DTE."""
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.62, strike=100.0, dte=10).model_copy(update={"delta": None})
    quotes = _roll_chain(current_mid=8.00, new_mid=7.70, new_delta=-0.30, new_dte=20)
    # Unknown on the snapshot AND on the short's own chain quote — still fail-closed.
    quotes[0] = quotes[0].model_copy(update={"delta": None})
    assert not generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=True)


def test_defensive_roll_reads_position_delta_from_the_chain():
    """2026-10-02: get_positions carries no greeks, so every monitor-built position had
    delta=None and no defensive roll ever qualified (0 approvable roll alerts in production).
    The short's own contract in the chain supplies the delta."""
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.62, strike=100.0, dte=10).model_copy(update={"delta": None})
    quotes = _roll_chain(current_mid=8.00, new_mid=7.70, new_delta=-0.30, new_dte=20)
    assert generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=True)


def test_income_roll_still_requires_a_credit_and_roc():
    from src.strategies.rolling import generate_roll_candidates

    pos = _short_call(delta=-0.30, strike=100.0, dte=15)
    quotes = _roll_chain(current_mid=1.00, new_mid=0.90, new_delta=-0.28, new_dte=22)
    assert not generate_roll_candidates(pos, quotes, _iv(), _tech(), defensive=False)


def test_roll_dte_uses_et_not_local_date(monkeypatch):
    """D4: rolling.py:39 used date.today(), firing a day early in UTC+8."""
    import src.strategies.rolling as rolling

    called = {}
    monkeypatch.setattr(rolling, "today_et", lambda: called.setdefault("hit", True) and _ET_TODAY)
    generate_roll_candidates = rolling.generate_roll_candidates
    generate_roll_candidates(_short_call(delta=-0.30, strike=100.0, dte=15), [], _iv(), _tech())
    assert called.get("hit"), "generate_roll_candidates must use today_et()"
