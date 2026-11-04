"""Claude's fair value, computed and clamped by Python (value book spec §8.2)."""

from __future__ import annotations

import pytest

from src.common.config import ValueCfg, get_config
from src.common.value_ai_types import Drivers
from src.value.claude_valuation import bounds_for, clamp_drivers, claude_fair_value, two_stage_dcf
from src.value.scorecard import build_scorecard
from tests.value_fixtures import BANK, financials, inputs

CFG = get_config().value
RULES = CFG.rules
STEADY = build_scorecard(inputs(close=30.0), CFG)  # deep FV 46.85, growth FV 86.87
HBR = build_scorecard(
    inputs(symbol="HBR", fin=financials(BANK), close=40.0, industry="Diversified Banks"), CFG
)


def test_the_bounds_come_from_the_companys_own_history() -> None:
    deep = bounds_for(STEADY, "deep_value", RULES)
    assert deep is not None and deep.method == "dcf"
    assert deep.growth is not None and deep.margin is not None
    # growth: -10% to the lower of 30% and the realised 14.74% CAGR + 5 points
    assert (deep.growth.lo, deep.growth.hi) == (-0.10, pytest.approx(0.19741499781411548))
    # margin: the 5-year median 15.59% +- 5 points, never above the best (16.25%)
    assert deep.margin.lo == pytest.approx(0.10590551181102363)
    assert deep.margin.hi == pytest.approx(0.1625)
    assert (deep.discount.lo, deep.discount.hi) == (0.09, 0.12)  # never below Python's 9%
    growth = bounds_for(STEADY, "quality_growth", RULES)
    assert growth is not None and growth.discount.lo == 0.08  # the growth list's 8%
    assert growth.margin is not None and growth.margin.hi == pytest.approx(0.175)  # half SBC
    bank = bounds_for(HBR, "deep_value", RULES)
    assert bank is not None and bank.method == "ptbv" and bank.rote is not None
    assert (bank.rote.lo, bank.rote.hi) == (
        pytest.approx(0.10025974025974024),
        pytest.approx(0.18025974025974026),
    )


def test_every_driver_out_of_bounds_is_clamped_and_recorded() -> None:
    bounds = bounds_for(STEADY, "deep_value", RULES)
    assert bounds is not None
    kept, clamps = clamp_drivers(
        Drivers(growth=0.40, terminal=0.03, discount=0.07, margin=0.30), bounds
    )
    assert kept is not None
    assert (kept.growth, kept.terminal, kept.discount, kept.margin) == (
        pytest.approx(0.19741499781411548),
        0.025,
        0.09,
        0.1625,
    )
    assert clamps == [
        "growth 0.4000 -> 0.1974",
        "terminal 0.0300 -> 0.0250",
        "discount 0.0700 -> 0.0900",
        "margin 0.3000 -> 0.1625",
    ]
    missing, _ = clamp_drivers(Drivers(growth=0.1, terminal=0.02, discount=0.09), bounds)
    assert missing is None  # a malformed driver set means no Claude fair value


def test_the_two_stage_dcf() -> None:
    # $1 of FCF, 10% for five years then fading to 2.5% by year 10, at 9%.
    out = two_stage_dcf(1.0, 0.10, 0.09, 0.025)
    assert out is not None
    assert out.value == pytest.approx(24.03334204118441)
    assert out.terminal_share == pytest.approx(0.5827978862700297)
    assert two_stage_dcf(1.0, 0.10, 0.025, 0.025) is None  # rate at terminal growth


def test_a_value_above_one_and_a_half_times_pythons_is_capped_and_the_cap_used() -> None:
    v = claude_fair_value(
        STEADY,
        "deep_value",
        Drivers(growth=0.15, terminal=0.025, discount=0.09, margin=0.16),
        RULES,
    )
    assert v.uncapped == pytest.approx(80.98530915510761)
    assert v.fair_value == pytest.approx(1.5 * 46.853626592284414)  # 70.28
    assert v.clamp_bound is True and v.clamps == []


def test_lowering_is_never_capped() -> None:
    v = claude_fair_value(
        STEADY,
        "quality_growth",
        Drivers(growth=0.12, terminal=0.02, discount=0.09, margin=0.17),
        RULES,
    )
    assert v.fair_value == pytest.approx(69.06334253911646)  # below Python's 86.87
    assert v.clamp_bound is False


def test_a_bank_is_valued_on_claudes_rote() -> None:
    v = claude_fair_value(
        HBR, "deep_value", Drivers(rote=0.12, terminal=0.02, discount=0.10), RULES
    )
    assert v.fair_value == pytest.approx((0.12 - 0.02) / (0.10 - 0.02) * 21.5)  # 26.875


def test_a_terminal_value_above_three_quarters_is_unreliable() -> None:
    loose = ValueCfg(
        ruleset_version="test", rules={"claude": {"terminal_max": 0.08, "discount_max": 0.12}}
    ).rules
    v = claude_fair_value(
        STEADY,
        "deep_value",
        Drivers(growth=0.15, terminal=0.08, discount=0.09, margin=0.16),
        loose,
    )
    assert v.fair_value is None and v.unreliable == "terminal value above 75% of the whole"
    assert v.terminal_share is not None and v.terminal_share > 0.75


def test_without_pythons_fair_value_claudes_cannot_be_used() -> None:
    card = STEADY.model_copy(
        update={
            "lists": {
                "deep_value": STEADY.lists["deep_value"].model_copy(update={"fair_value": None})
            }
        }
    )
    v = claude_fair_value(
        card, "deep_value", Drivers(growth=0.1, terminal=0.02, discount=0.09, margin=0.15), RULES
    )
    assert v.fair_value is None and v.unreliable == "Python has no fair value for this list"
    assert bounds_for(STEADY, "no_such_list", RULES) is None
