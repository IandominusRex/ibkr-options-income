"""Timing and the scorecard's baseline verdicts (value book spec §6.6-6.7, §6.9)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.config import ValueCfg, get_config
from src.value.scorecard import build_scorecard
from src.value.timing import (
    deep_value_timing,
    earnings_check,
    growth_timing,
    sessions_between,
)
from tests.value_fixtures import AS_OF, BANK, financials, inputs, price

CFG = get_config().value
TIMING = CFG.rules.timing


def test_sessions_count_weekdays() -> None:
    assert sessions_between(date(2026, 3, 30), date(2026, 4, 6)) == 5  # Monday to Monday


@pytest.mark.parametrize(
    ("next_earnings", "state"),
    [
        (AS_OF + timedelta(days=7), "fail"),  # 5 sessions
        (AS_OF + timedelta(days=30), "pass"),
        (None, "unknown"),
        (AS_OF - timedelta(days=20), "pass"),  # reported recently: next is a quarter away
        (AS_OF - timedelta(days=100), "unknown"),
    ],
)
def test_the_earnings_window(next_earnings, state) -> None:
    assert earnings_check(AS_OF, next_earnings, TIMING).state == state


def _falling(n: int = 260) -> list[float]:
    return [100.0 - 0.2 * i for i in range(n)]


def test_deep_value_needs_trend_and_a_stop_in_the_fall() -> None:
    up = {c.id: c.state for c in deep_value_timing(price(30.0), -0.10, TIMING)}
    assert up == {"timing.trend": "pass", "timing.stopped_falling": "pass"}
    down = price(48.2, closes=_falling(), ret_6m=-0.30, spy_ret_6m=0.05)
    checks = {c.id: c.state for c in deep_value_timing(down, -0.10, TIMING)}
    assert checks == {"timing.trend": "fail", "timing.stopped_falling": "fail"}


def test_relative_strength_rescues_a_name_below_its_200_day_average() -> None:
    below = price(48.2, closes=_falling(), ret_6m=0.02, spy_ret_6m=0.05)
    trend = deep_value_timing(below, -0.10, TIMING)[0]
    assert (trend.state, trend.actual) == ("pass", pytest.approx(-0.03))
    assert deep_value_timing(below, None, TIMING)[0].state == "unknown"


def test_growth_is_refused_only_below_the_average_and_at_a_new_low() -> None:
    assert growth_timing(price(48.2, closes=_falling()), TIMING)[0].state == "fail"
    dip = [100.0 - 0.2 * i for i in range(250)] + [51.0 + i for i in range(10)]
    assert growth_timing(price(60.0, closes=dip), TIMING)[0].state == "pass"


# ── the scorecard ───────────────────────────────────────────────────────────────────────────


def test_a_healthy_cheap_grower_is_ready_on_both_lists() -> None:
    card = build_scorecard(inputs(close=30.0), CFG)
    assert (card.company_class, card.data_quality, card.health) == ("operating", "pass", "pass")
    deep, growth = card.lists["deep_value"], card.lists["quality_growth"]
    assert deep.verdict == "READY" and growth.verdict == "READY"
    assert deep.fair_value == pytest.approx(46.853626592284414)
    assert deep.margin_of_safety == pytest.approx(0.3597080486200778)
    assert deep.entry_ceiling == pytest.approx(35.140219944213314)
    assert growth.fair_value == pytest.approx(86.86667560395772)
    assert growth.mos_review is True  # a 65% margin goes to a human (spec §9.4)
    assert card.reverse_dcf_implied_growth == pytest.approx(-0.0487482551644291)
    assert card.realised_fcf_ps_cagr == pytest.approx(0.1474149978141155)


@pytest.mark.parametrize(
    ("close", "regime", "deep", "growth"),
    [
        (32.0, "normal", "READY", "READY"),
        (32.0, "stressed", "WAIT", "READY"),  # 35% required: ceiling 30.45
        (40.0, "normal", "WAIT", "READY"),
        (90.0, "normal", "WAIT", "WAIT"),
    ],
)
def test_the_regime_sets_how_demanding_the_entry_is(close, regime, deep, growth) -> None:
    card = build_scorecard(inputs(close=close, regime=regime), CFG)
    assert (card.lists["deep_value"].verdict, card.lists["quality_growth"].verdict) == (
        deep,
        growth,
    )


def test_cheap_with_timing_failing_is_watch() -> None:
    card = build_scorecard(inputs(close=30.0, next_earnings=AS_OF + timedelta(days=3)), CFG)
    assert card.lists["deep_value"].verdict == "WATCH"
    assert card.lists["deep_value"].reasons == ["cheap enough; timing fail"]


def test_a_failed_health_gate_is_no_on_every_list() -> None:
    card = build_scorecard(inputs(fin=financials(shares_diluted=[110, 104, 98, 92, 86])), CFG)
    assert card.health == "fail"
    for ev in card.lists.values():
        assert ev.verdict == "NO" and ev.reasons == ["health gate failed: health.dilution"]


def test_a_slow_grower_is_off_the_growth_list_but_still_valued_as_deep_value() -> None:
    slow = financials(
        revenue=[1200, 1150, 1100, 1050, 1000],
        operating_cash_flow=[300, 295, 290, 285, 280],
        capital_expenditure=[60, 60, 60, 60, 60],
    )
    card = build_scorecard(inputs(fin=slow), CFG)
    growth = card.lists["quality_growth"]
    assert growth.entry == "fail" and growth.verdict == "NO"
    assert card.lists["deep_value"].verdict in ("READY", "WATCH", "WAIT")


def test_a_data_quality_failure_is_unknown_and_never_reaches_the_lists() -> None:
    card = build_scorecard(inputs(yf_market_cap=6000.0), CFG)
    assert card.data_quality == "unknown" and card.lists == {}
    assert card.verdict_for("deep_value") == "UNKNOWN"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"is_etf": True}, "ETF"),
        ({"industry": "Retail REITs"}, "REIT: FFO is not reliably tagged"),
        (
            {
                "fin": financials(
                    net_income=[-50, -40, -30, 10, 5], operating_cash_flow=[-20, -10, 5, 30, 30]
                )
            },
            "pre-profit",
        ),
    ],
)
def test_names_the_scorecard_does_not_cover_are_not_applicable(kwargs, reason) -> None:
    card = build_scorecard(inputs(**kwargs), CFG)
    assert card.not_applicable_reason == reason
    assert card.verdict_for("deep_value") == card.verdict_for("quality_growth") == "NOT_APPLICABLE"


def test_a_bank_is_valued_on_tangible_book_and_held_unknown_without_cet1() -> None:
    card = build_scorecard(
        inputs(symbol="HBR", fin=financials(BANK), close=40.0, industry="Diversified Banks"), CFG
    )
    assert card.company_class == "bank" and list(card.lists) == ["deep_value"]
    deep = card.lists["deep_value"]
    assert deep.fair_value == pytest.approx(38.12437562437562)
    assert deep.verdict == "UNKNOWN"
    off = ValueCfg(ruleset_version="test", rules={"banks": {"require_cet1": False}})
    assert (
        build_scorecard(
            inputs(symbol="HBR", fin=financials(BANK), close=40.0, industry="Diversified Banks"),
            off,
        )
        .lists["deep_value"]
        .verdict
        == "WAIT"
    )


def test_the_fingerprint_names_the_inputs_and_moves_with_the_price() -> None:
    a = build_scorecard(inputs(close=30.0), CFG)
    b = build_scorecard(inputs(close=30.5), CFG)
    assert a.fingerprint.latest_accn == "0000000001-26-000001"
    assert a.fingerprint.price_close == 30.0 and a.fingerprint.regime == "normal"
    assert a.fingerprint.key() != b.fingerprint.key()


def test_the_scorecard_is_a_pure_function_of_its_inputs() -> None:
    assert (
        build_scorecard(inputs(), CFG).model_dump_json()
        == build_scorecard(inputs(), CFG).model_dump_json()
    )
