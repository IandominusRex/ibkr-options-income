"""Tap-only book-repair proposals (risk-envelope Task 30; spec §3.7 item 2, rulings E12, P10).

The builder is pure (``src/engine/repair.py``); the covered-call screen reads the
``cc_basis_floor`` and ``leveraged_cc_auto`` switches; a tap is the only way a proposal acts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs
from src.common.schemas import (
    AutonomyLevel,
    FundamentalStats,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RepairProposal,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.engine.repair import build_proposals, shadow_value

NOW = datetime(2026, 11, 16, 21, 0, tzinfo=UTC)
TODAY = date(2026, 11, 16)


def _inputs(*lines: BookLine, nlv: float = 100_000.0) -> ShockInputs:
    return ShockInputs(
        lines=tuple(lines),
        betas={"AAPL": 1.2, "NVDA": 1.6, "QQQ": 1.1, "SPY": 1.0},
        betas_smh={},
        leverage={"TQQQ": 3},
        governing={"TQQQ": "QQQ"},
        tech_linked=frozenset(),
        semis=frozenset(),
        nlv=nlv,
    )


def _room(s10: float, limit: float, uew: float = 1.0, uew_limit: float = 1.5) -> EnvelopeRoom:
    return EnvelopeRoom(
        s10_gross=s10,
        s10_limit=limit,
        uew=uew,
        uew_limit=uew_limit,
        t20_gross=0.0,
        t20_limit=None,
        enforce="record",
        measured=True,
    )


def _cc(
    underlying: str = "AAPL", *, strike: float = 190.0, contracts: int = 2, **kw
) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=f"cc-{underlying}-{strike:g}",
        strategy=Strategy.COVERED_CALL,
        underlying=underlying,
        right=OptionRight.CALL,
        strike=strike,
        expiry=TODAY + timedelta(days=24),
        contracts=contracts,
        premium=2.2,
        collateral=36_000.0,
        roc_pct=1.2,
        annualized_yield_pct=18.0,
        breakeven=178.0,
        delta=0.28,
        dte=24,
        quote_iv=0.30,
        underlying_price=180.0,
        scores=ScoreCard(
            symbol=underlying,
            iv_score=50,
            technical_score=50,
            fundamental_score=50,
            liquidity_score=50,
            assignment_safety_score=50,
        ),
        **kw,
    )


def test_a_cc_overlay_at_the_floor_is_proposed_with_before_and_after() -> None:
    inputs = _inputs(BookLine("AAPL", "stock", 200.0, 180.0))
    room = _room(4.4, 3.0)
    [p] = build_proposals(inputs=inputs, room=room, cc_candidates=[_cc()], addable=[], now=NOW)
    assert p.kind == "cc_overlay" and p.symbol == "AAPL" and p.candidate is not None
    assert p.s10_after < p.s10_before  # the call's premium cushions the -10% index move
    assert p.uew_after == pytest.approx(p.uew_before)  # a short call adds no exposure (H10)
    assert (p.s10_limit, p.uew_limit) == (3.0, 1.5)  # L(t) on the card
    assert "190C" in p.detail


def test_an_unmeasured_book_builds_no_proposal() -> None:
    inputs = _inputs(BookLine("ZZZZ", "stock", 200.0, 50.0))  # no beta: unmeasured
    assert (
        build_proposals(
            inputs=inputs, room=_room(5.0, 3.0), cc_candidates=[], addable=["ZZZZ"], now=NOW
        )
        == []
    )


# --------------------------------------------------------------------------- #
# The covered-call screen: the floor switch and the leveraged carve-out
# --------------------------------------------------------------------------- #


def _screen(symbol: str, avg_cost: float, strike: float, delta: float):
    from src.strategies.covered_call import screen_cc_candidates

    expiry = date.today() + timedelta(days=24)
    quote = OptionQuote(
        underlying=symbol,
        right=OptionRight.CALL,
        strike=strike,
        expiry=expiry,
        bid=2.10,
        ask=2.30,
        volume=500,
        open_interest=2000,
        iv=0.28,
        delta=delta,
    )
    position = PositionSnapshot(symbol=symbol, sec_type="STK", position=200.0, avg_cost=avg_cost)
    return screen_cc_candidates(
        symbol,
        [quote],
        position,
        IVStats(symbol=symbol, current_iv=28.0, iv_rank=65.0),
        TechnicalStats(symbol=symbol, price=avg_cost * 0.9, rsi_14=55.0),
        FundamentalStats(symbol=symbol, quality_flag=True),
    )


def _reasons(result) -> list[str]:
    return [r for _, rs in result.rejected for r in rs]


def test_the_floor_reads_the_cc_basis_floor_switch(db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.storage.envelope_switches import set_switch
    from src.strategies.covered_call import basis_floor

    at_96 = _screen("AAPL", 200.0, 192.0, 0.28)  # 0.96 x basis, under the default 1.00 floor
    assert not at_96.passed and "strike_below_basis" in _reasons(at_96)
    set_switch("cc_basis_floor", "0.95", source="cli")
    passed = _screen("AAPL", 200.0, 192.0, 0.28)
    assert passed.passed and not passed.passed[0].tap_only
    # the configured value is the ceiling: the switch only ever lowers the floor
    cc = dict(get_config().risk["covered_call"])
    monkeypatch.setitem(get_config().risk, "covered_call", {**cc, "min_strike_vs_basis": 0.90})
    set_switch("cc_basis_floor", "1.00", source="cli")
    assert basis_floor(0.90) == 0.90
    assert basis_floor(1.00) == 1.00


def test_leveraged_cc_below_basis_is_tap_only_at_delta_025(db) -> None:
    ok = _screen("TQQQ", 100.0, 80.0, 0.22)
    assert len(ok.passed) == 1
    call = ok.passed[0]
    assert call.tap_only and "leveraged_below_basis" in call.rationale_tags
    too_far = _screen("TQQQ", 100.0, 80.0, 0.30)
    assert not too_far.passed and "strike_below_basis" in _reasons(too_far)
    # an unleveraged name gets no carve-out at the same delta
    assert not _screen("AAPL", 100.0, 80.0, 0.22).passed


def test_leveraged_cc_auto_switch_lets_it_auto_open(db) -> None:
    from src.storage.envelope_switches import set_switch

    set_switch("leveraged_cc_auto", "on", source="cli")
    [call] = _screen("TQQQ", 100.0, 80.0, 0.22).passed
    assert not call.tap_only


# --------------------------------------------------------------------------- #
# Taps and shadow values
# --------------------------------------------------------------------------- #


def test_stop_adding_proposal_sets_a_universe_override(db) -> None:
    from src.notify.approval_service import _process_repair_button
    from src.storage.models import RepairProposalRow, UniverseOverrideRow
    from src.storage.repair_proposals import save_proposals

    inputs = _inputs(
        BookLine("NVDA", "stock", 400.0, 180.0), BookLine("AAPL", "stock", 50.0, 180.0)
    )
    proposals = build_proposals(
        inputs=inputs, room=_room(12.0, 8.0), cc_candidates=[], addable=["NVDA"], now=NOW
    )
    assert [p.kind for p in proposals] == ["stop_adding"] and proposals[0].symbol == "NVDA"
    [stored] = save_proposals(proposals, TODAY)
    assert stored.id is not None
    text = _process_repair_button(stored.id, "approve")
    assert "Stop adding NVDA" in text
    with db() as s:
        row = s.query(UniverseOverrideRow).filter_by(symbol="NVDA", list_name="would_own").one()
        assert row.action == "remove"
        assert s.get(RepairProposalRow, stored.id).status == "sent"
    assert "Already" in _process_repair_button(stored.id, "approve")  # a second tap acts never


def test_a_cc_overlay_tap_raises_an_ordinary_approval(db) -> None:
    from src.notify.approval_service import _process_repair_button
    from src.storage.models import ApprovalRow, OrderRow
    from src.storage.repair_proposals import save_proposals

    [p] = build_proposals(
        inputs=_inputs(BookLine("AAPL", "stock", 200.0, 180.0)),
        room=_room(4.4, 3.0),
        cc_candidates=[_cc()],
        addable=[],
        now=NOW,
    )
    [stored] = save_proposals([p], TODAY)
    assert stored.id is not None
    _process_repair_button(stored.id, "approve")
    with db() as s:
        approval = s.query(ApprovalRow).filter_by(candidate_id="cc-AAPL-190").one()
        assert approval.status == "approved"
        order = s.query(OrderRow).filter_by(candidate_id="cc-AAPL-190").one()
        assert order.state == "queued"  # the order poll re-gates it on a fresh quote


def test_every_proposal_is_shadow_valued_tapped_or_not(db) -> None:
    from src.storage.models import RepairProposalRow
    from src.storage.repair_proposals import decide, mark_shadow_values, save_proposals

    base = dict(s10_before=5.0, s10_after=4.0, uew_before=1.2, uew_after=1.1, created_at=NOW)
    proposals = [
        RepairProposal(kind="stop_adding", symbol="NVDA", detail="", mark=180.0, **base),
        RepairProposal(kind="cc_overlay", symbol="AAPL", detail="", candidate=_cc(), **base),
        RepairProposal(kind="trim", symbol="HOOD", detail="", shares=30.0, mark=120.0, **base),
    ]
    stored = save_proposals(proposals, TODAY)
    assert len(stored) == 3
    assert decide(stored[1].id or 0, "rejected", by="telegram")
    assert decide(stored[2].id or 0, "approved", by="telegram")
    closes = {"NVDA": 170.0, "AAPL": 185.0, "HOOD": 110.0}
    marked = mark_shadow_values(
        TODAY, lambda p: shadow_value(p, close=closes.get(p.symbol), today=TODAY)
    )
    assert marked == 3
    with db() as s:
        values = {r.symbol: r.shadow_value for r in s.query(RepairProposalRow)}
    assert values["NVDA"] == pytest.approx(1_000.0)  # a lot not added as the name fell $10
    assert values["HOOD"] == pytest.approx(300.0)  # 30 shares sold before a $10 fall
    assert values["AAPL"] is not None  # the rejected overlay is valued too


async def test_a_tap_only_candidate_never_auto_queues(db, monkeypatch) -> None:
    from src.notify import sender
    from src.storage.models import ApprovalRow, OrderRow
    from src.storage.system_settings import set_autonomy_level
    from tests.test_notify import _cc_kwargs, _mock_cfg

    _mock_cfg(monkeypatch)
    set_autonomy_level(AutonomyLevel.FULL)
    instance = AsyncMock()
    instance.send_message.return_value = MagicMock(message_id=7)
    bot_cls = MagicMock()
    bot_cls.return_value.__aenter__ = AsyncMock(return_value=instance)
    bot_cls.return_value.__aexit__ = AsyncMock(return_value=None)
    tap = _cc("TQQQ", strike=80.0, tap_only=True)
    with patch("src.notify.sender.Bot", bot_cls):
        await sender.send_candidates([tap], [], **_cc_kwargs())
    with db() as s:
        assert s.query(OrderRow).count() == 0  # FULL autonomy, yet nothing queued
        approval = s.query(ApprovalRow).filter_by(candidate_id=tap.candidate_id).one()
        assert approval.status == "pending"
    markup = instance.send_message.call_args.kwargs["reply_markup"]
    assert markup is not None  # the human gets Approve / Reject
