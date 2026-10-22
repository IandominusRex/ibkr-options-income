"""OI-B3: a name-level bottoming signal lot is exempt from the variance-premium floor.

The floor (`premium_below_fair_value`, `income.require_vrp_edge`) rejected 23% of the SOXL/TQQQ
candidates the week of 2026-10-13, and a lot opened on a bottoming signal met it like any other.
The operator decided (2026-10-22) to waive it for **name-level signal lots only** (the lots that
carry the delta cap and the one-lot-per-3-sessions guard) and for nothing else: not an ordinary
ladder lot, not a lot under a market-eased regime, not a covered call or a roll, not when the
regime limits are off. Both places that apply the floor agree (the CSP generator and the gate),
and at send time, where the re-gate has no fresh signals, the gate reads the tag frozen on the
card. Deterministic; nothing an LLM produces reaches any of it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.config import get_config
from src.common.schemas import (
    MarketRegime,
    OptionRight,
    SizingContext,
    SizingNote,
    Strategy,
    TradeCandidate,
    Verdict,
)
from tests.test_bottoming import bottoming_ctx, screen_delta
from tests.test_scale_in_gate import (  # noqa: F401 - _db and _universe are autouse fixtures
    SIZER_ZONE,
    ZONE,
    _db,
    _universe,
    csp,
    ctx,
    gate,
)

N = MarketRegime.NORMAL
S = MarketRegime.STRESSED
FLOOR = "premium_below_fair_value"


def vrp_csp(
    cid: str,
    underlying: str = "BAC",
    *,
    spot: float | None = 50.0,
    min_credit: float = 4.0,
    update: dict | None = None,
    **kw,
) -> TradeCandidate:
    """A BAC put whose credit (3.00 per share) is under the fair-value floor (4.00) by default.

    *kw* goes to the shared candidate builder; *update* sets fields it does not take.
    """
    cand = csp(cid, underlying, spot=spot, **kw)
    if cand.ideal is not None:
        cand.ideal = cand.ideal.model_copy(update={"min_credit": min_credit})
    return cand.model_copy(update=update) if update else cand


def signal(**kw) -> SizingContext:
    """BAC has a zone (45-47), a bottom is forming on it and the market is normal."""
    return bottoming_ctx(**kw)


def reasons_of(cand: TradeCandidate, sizing: SizingContext | None, **kw) -> list[str]:
    return gate([cand], sizing, **kw)[cand.candidate_id].reasons


# --------------------------------------------------------------------------- #
# the gate: the exempt lot
# --------------------------------------------------------------------------- #


def test_a_name_signal_lot_below_fair_value_passes_and_the_waiver_is_recorded():
    cand = vrp_csp("sig", delta=-0.23)
    verdict = gate([cand], signal())["sig"]
    assert verdict.verdict == Verdict.PASS, verdict.reasons
    assert cand.sizing is not None
    assert cand.sizing.bottoming == "name"
    assert cand.sizing.vrp_waived is True


def test_a_signal_lot_that_clears_fair_value_is_not_marked_waived():
    cand = vrp_csp("sig", delta=-0.23, min_credit=2.0)  # credit 3.00 is above the floor
    assert gate([cand], signal())["sig"].verdict == Verdict.PASS
    assert cand.sizing is not None
    assert cand.sizing.bottoming == "name" and cand.sizing.vrp_waived is False


@pytest.mark.parametrize(
    ("label", "kw", "expected"),
    [
        ("roc", {"roc_pct": 0.1}, "roc_below_minimum"),
        ("iv_rank", {"iv_rank": 1.0}, "iv_rank_below_minimum"),
        ("iv_rv", {"update": {"iv_rv_ratio": 0.5}}, "iv_rv_below_minimum"),
        ("dte", {"dte": 400}, "dte_out_of_range"),
        ("delta cap", {"delta": -0.30}, "bottoming_delta_too_high"),
        ("delta band", {"delta": -0.60}, "delta_out_of_range"),
        ("delta missing", {"delta": None}, "delta_missing"),
    ],
)
def test_the_exempt_lot_still_fails_every_other_gate(label, kw, expected):
    """The waiver lifts the one floor; every other gate still refuses the same lot."""
    kw = {"delta": -0.23, **kw}
    cand = vrp_csp("sig", **kw)
    reasons = reasons_of(cand, signal())
    assert expected in reasons, (label, reasons)
    assert FLOOR not in reasons, (label, reasons)


def test_the_exempt_lot_still_meets_the_yield_floor(monkeypatch):
    config = get_config()
    risk = dict(config.risk)
    risk["income"] = {**risk["income"], "min_annualized_yield_pct": 12.0}
    monkeypatch.setattr(config, "risk", risk)
    cand = vrp_csp("y", delta=-0.23, annualized_yield_pct=1.0)
    reasons = reasons_of(cand, signal())
    assert "yield_below_minimum" in reasons and FLOOR not in reasons


def test_the_exempt_lot_still_meets_earnings_the_recent_lot_guard_and_the_regime_limits():
    soon = vrp_csp("e", delta=-0.23)
    soon.next_earnings = date.today() + timedelta(days=3)
    assert "earnings_blackout" in reasons_of(soon, signal())

    recent = signal().model_copy(update={"signal_lot_recent": ["BAC"]})
    assert "bottoming_lot_recent" in reasons_of(vrp_csp("r", delta=-0.23), recent)

    stressed = signal().model_copy(update={"regimes": {"SPY": S, "QQQ": S}})
    big = vrp_csp("big", delta=-0.23, contracts=5)  # a stressed regime's ceiling is 3
    assert "regime_ceiling" in reasons_of(big, stressed)
    used = stressed.model_copy(update={"csp_opens_counted": {"SPY": 3}})  # the day's limit is 3
    assert "regime_daily_limit" in reasons_of(vrp_csp("d", delta=-0.23), used)
    for cid, cand_reasons in (
        ("e", reasons_of(soon, signal())),
        ("big", reasons_of(big, stressed)),
    ):
        assert FLOOR not in cand_reasons, (cid, cand_reasons)


def test_the_exempt_lot_still_meets_the_concentration_limit():
    huge = vrp_csp("huge", delta=-0.23).model_copy(update={"collateral": 5_000_000.0})
    reasons = reasons_of(huge, signal())
    assert any(r in reasons for r in ("concentration_limit", "insufficient_cash")), reasons
    assert FLOOR not in reasons


# --------------------------------------------------------------------------- #
# the gate: nothing else is exempt
# --------------------------------------------------------------------------- #


def test_an_ordinary_ladder_lot_is_still_held_to_the_floor():
    # inside the zone: a ladder lot, not a signal lot (the name has a signal, but the price fell
    # into the zone, so the ladder alone lets it in)
    inside = vrp_csp("in", spot=46.0, delta=-0.23)
    assert FLOOR in reasons_of(inside, signal())
    # and a name under the ladder with no signal, above the zone, is refused twice over
    above = reasons_of(vrp_csp("up", spot=50.0, delta=-0.23), ctx())
    assert FLOOR in above and "scale_in_zone_not_reached" in above


def test_a_lot_with_no_ladder_and_no_signal_is_still_held_to_the_floor():
    plain = ctx(zone=None)
    assert FLOOR in reasons_of(vrp_csp("p", spot=50.0), plain)
    assert FLOOR in reasons_of(vrp_csp("q", spot=50.0), None)  # no context at all


def test_a_market_eased_lot_is_still_held_to_the_floor():
    """The market-level signal only eases the regime; its lots carry the tag "market" and no waiver."""
    eased = ctx(zone=None).model_copy(update={"market_bottoming": {"SPY": True}})
    cand = vrp_csp("mkt", spot=50.0, delta=-0.23)
    assert FLOOR in reasons_of(cand, eased)
    # a market signal on a name that also has a zone and a name-level signal elsewhere changes nothing
    other = signal().model_copy(update={"market_bottoming": {"SPY": True}})
    assert FLOOR in reasons_of(vrp_csp("tq", "TQQQ", spot=50.0, delta=-0.23), other)


def test_a_signal_on_another_name_does_not_exempt_this_one():
    both = signal().model_copy(
        update={"scale_in": {"BAC": ZONE, "TQQQ": ZONE}, "name_bottoming": ["BAC"]}
    )
    assert FLOOR in reasons_of(vrp_csp("tq", "TQQQ", spot=50.0, delta=-0.23), both)


def test_regime_off_means_no_signal_lots_and_so_no_waiver(monkeypatch):
    assert FLOOR in reasons_of(vrp_csp("a", delta=-0.23), signal(suspended=True))  # /regime off
    config = get_config()
    risk = dict(config.risk)
    risk["regime"] = {**risk["regime"], "enabled": False}  # regime.enabled: false
    monkeypatch.setattr(config, "risk", risk)
    assert FLOOR in reasons_of(vrp_csp("b", delta=-0.23), signal())


def forged(cid: str, strategy: Strategy, right: OptionRight, delta: float) -> TradeCandidate:
    """A call or a roll that carries a "name" bottoming tag it could never have earned."""
    cand = vrp_csp(cid, strategy=strategy, right=right, delta=delta)
    cand.sizing = SizingNote(
        pre_regime_contracts=1,
        regime=N,
        regime_index="SPY",
        per_trade_cap=10,
        budget_multiplier=1.0,
        bottoming="name",
    )
    return cand


def test_a_forged_name_tag_on_a_covered_call_waives_nothing():
    for sizing in (signal(), signal(for_send=True)):
        cand = forged("cc", Strategy.COVERED_CALL, OptionRight.CALL, 0.25)
        assert FLOOR in reasons_of(cand, sizing)  # a call is held to the floor as before
        assert cand.sizing is not None and cand.sizing.vrp_waived is False


def test_a_forged_name_tag_on_a_roll_is_never_marked_waived():
    """A roll never meets the floor (it is scoped out of it), so there is nothing to waive."""
    for sizing in (signal(), signal(for_send=True)):
        cand = forged("roll", Strategy.ROLL, OptionRight.PUT, -0.23)
        assert FLOOR not in reasons_of(cand, sizing)
        assert cand.sizing is not None and cand.sizing.vrp_waived is False


# --------------------------------------------------------------------------- #
# the gate at send time: no fresh signals, so the frozen tag decides
# --------------------------------------------------------------------------- #


def frozen(cid: str, tag: str | None, *, bottoming_zone: bool = False, **kw) -> TradeCandidate:
    """A card as the order snapshot froze it: a note with the tag, a below-floor credit."""
    cand = vrp_csp(cid, spot=50.0, delta=-0.23, **kw)
    zone = ZONE.model_copy(update={"bottoming_signal": True}) if bottoming_zone else ZONE
    cand.sizing = SizingNote(
        pre_regime_contracts=1,
        regime=N,
        regime_index="SPY",
        per_trade_cap=10,
        budget_multiplier=1.0,
        scale_in=zone,
        bottoming=tag,  # type: ignore[arg-type]
    )
    return cand


def send_ctx(**kw) -> SizingContext:
    """What `approval._send_context` builds: for_send, no zone and no signal for any name."""
    return ctx(zone=None, for_send=True, **kw)


def test_the_send_time_regate_waives_from_the_tag_frozen_on_the_card():
    cand = frozen("sig", "name", bottoming_zone=True)
    verdict = gate([cand], send_ctx())["sig"]
    assert verdict.verdict == Verdict.PASS, verdict.reasons
    assert cand.sizing is not None
    assert cand.sizing.bottoming == "name" and cand.sizing.vrp_waived is True
    # the zone stays frozen on the card, still marked as a signal lot
    assert cand.sizing.scale_in is not None and cand.sizing.scale_in.bottoming_signal is True


@pytest.mark.parametrize("tag", [None, "market"])
def test_the_send_time_regate_does_not_waive_a_lot_without_the_name_tag(tag):
    cand = frozen("c", tag)
    reasons = gate([cand], send_ctx())["c"].reasons
    assert FLOOR in reasons
    assert cand.sizing is not None and cand.sizing.vrp_waived is False


def test_the_send_time_regate_does_not_waive_when_the_regime_limits_are_off_or_missing():
    assert FLOOR in reasons_of(frozen("a", "name"), send_ctx(suspended=True))
    assert FLOOR in reasons_of(frozen("b", "name"), None)


def test_a_forged_name_tag_on_a_call_waives_nothing_at_send_time():
    cand = frozen("cc", "name", strategy=Strategy.COVERED_CALL, right=OptionRight.CALL)
    cand.delta = 0.25
    assert FLOOR in reasons_of(cand, send_ctx())


def test_at_decision_time_the_fresh_signal_decides_not_a_tag_on_the_card():
    """A "name" tag the fresh context cannot back (no signal on the name now) waives nothing."""
    cand = frozen("stale", "name", bottoming_zone=True)
    assert FLOOR in reasons_of(cand, ctx(zone=ZONE))  # for_send False, no signal on BAC


def test_a_signal_lot_that_clears_fair_value_at_send_time_is_not_marked_waived():
    cand = frozen("ok", "name", bottoming_zone=True, min_credit=2.0)
    assert gate([cand], send_ctx())["ok"].verdict == Verdict.PASS
    assert cand.sizing is not None and cand.sizing.vrp_waived is False


# --------------------------------------------------------------------------- #
# the generator applies the same rule
# --------------------------------------------------------------------------- #


@pytest.fixture
def high_floor(monkeypatch):
    """Every contract's fair-value floor is 5.00 a share: far above the 1.025 mid."""
    monkeypatch.setattr(
        "src.strategies.cash_secured_put.zone_for_contract",
        lambda zone, strike, iv: zone.model_copy(update={"min_credit": 5.0}),
    )


def test_the_generator_waives_the_floor_for_a_name_signal_lot(high_floor):
    result = screen_delta("BAC", 60.0, signal(zone=SIZER_ZONE), -0.23)
    assert result.rejected == [], result.rejected
    (cand,) = result.passed
    assert cand.sizing is not None
    assert cand.sizing.bottoming == "name" and cand.sizing.vrp_waived is True


def test_the_generator_still_rejects_every_other_lot_below_the_floor(high_floor, monkeypatch):
    def rejected_for(sizing: SizingContext | None) -> list[str]:
        result = screen_delta("BAC", 60.0, sizing, -0.23)
        reasons = [r for _, rs in result.rejected for r in rs]
        assert result.passed == [], result.passed
        return reasons

    assert FLOOR in rejected_for(ctx(SIZER_ZONE))  # ladder, no signal
    assert FLOOR in rejected_for(ctx(zone=None))  # no ladder at all
    assert FLOOR in rejected_for(None)  # no regime context
    market = ctx(zone=None).model_copy(update={"market_bottoming": {"SPY": True}})
    assert FLOOR in rejected_for(market)
    assert FLOOR in rejected_for(signal(zone=SIZER_ZONE, suspended=True))
    # the same lot inside its zone is an ordinary ladder lot
    inside = screen_delta("BAC", 58.0, signal(zone=SIZER_ZONE), -0.23)
    assert FLOOR in [r for _, rs in inside.rejected for r in rs]


def test_the_generator_keeps_the_delta_cap_and_the_other_floors_on_a_waived_lot(high_floor):
    result = screen_delta("BAC", 60.0, signal(zone=SIZER_ZONE), -0.30)
    reasons = [r for _, rs in result.rejected for r in rs]
    assert "bottoming_delta_too_high" in reasons and FLOOR not in reasons
    assert result.passed == []


def test_the_generator_and_the_gate_agree_on_a_signal_lot(high_floor):
    """What the sizer lets through the gate accepts, with the waiver recorded identically."""
    sizing = signal(zone=SIZER_ZONE)
    result = screen_delta("BAC", 60.0, sizing, -0.23)
    (cand,) = result.passed
    assert cand.sizing is not None and cand.sizing.vrp_waived is True
    verdict = gate([cand], sizing)[cand.candidate_id]
    assert verdict.verdict == Verdict.PASS, verdict.reasons
    assert cand.sizing is not None and cand.sizing.vrp_waived is True


# --------------------------------------------------------------------------- #
# schema compatibility
# --------------------------------------------------------------------------- #


def test_an_old_snapshot_without_the_field_reads_as_not_waived():
    note = SizingNote.model_validate(
        {
            "pre_regime_contracts": 2,
            "regime": "normal",
            "regime_index": "SPY",
            "per_trade_cap": 10,
            "budget_multiplier": 1.0,
            "bottoming": "name",
        }
    )
    assert note.vrp_waived is False


# --------------------------------------------------------------------------- #
# where the waiver shows: the card's size line, and what the reviewer is told
# --------------------------------------------------------------------------- #


def _waived_note(**kw) -> SizingNote:
    base: dict = dict(
        pre_regime_contracts=1,
        regime=N,
        regime_index="SPY",
        per_trade_cap=10,
        budget_multiplier=1.0,
        bottoming="name",
        vrp_waived=True,
    )
    base.update(kw)
    return SizingNote(**base)


def _card_text(cand: TradeCandidate) -> str:
    from src.notify.formatters import format_candidate

    return format_candidate(cand, None).replace("\\", "")


def test_the_card_says_the_fair_value_floor_was_waived():
    cand = vrp_csp("card", delta=-0.23)
    cand.sizing = _waived_note()
    assert "Size 1 (bottoming-signal lot: fair-value floor waived)" in _card_text(cand)
    # a signal lot that cleared the floor is not cut and not waived: no size line at all
    quiet = vrp_csp("quiet", delta=-0.23)
    quiet.sizing = _waived_note(vrp_waived=False)
    assert "Size " not in _card_text(quiet)
    # a trimmed lot keeps its reason and adds the waiver
    trimmed = vrp_csp("trim", delta=-0.23)
    trimmed.sizing = _waived_note(pre_regime_contracts=3, regime=S, per_trade_cap=1)
    trimmed.contracts = 1
    text = _card_text(trimmed)
    assert "Size 1 of 3 (SPY stressed; bottoming-signal lot: fair-value floor waived)" in text


def test_the_reviewer_is_not_told_a_waived_lot_passed_the_fair_value_gate():
    from src.claude.prompts.strategist import _candidate_facts

    plain = vrp_csp("plain", delta=-0.23)
    plain.sizing = _waived_note(vrp_waived=False)
    assert any("fair value" in f for f in _candidate_facts(plain, 50.0) if f.startswith("F7"))
    waived = vrp_csp("waived", delta=-0.23)
    waived.sizing = _waived_note()
    f7 = next(f for f in _candidate_facts(waived, 50.0) if f.startswith("F7"))
    assert "fair value, " not in f7  # not in the list of gates it passed
    assert "waived" in f7 and "bottoming" in f7
