"""The rank score, the filed list and the relative-strength line (value book spec §6.6, §6.8)."""

from __future__ import annotations

import pytest

from src.common.config import get_config
from src.value.rank import filed_lists, percentiles, rank_list, rs_cutoff
from src.value.scorecard import build_scorecard
from tests.value_fixtures import financials, inputs, price

CFG = get_config().value


def test_percentiles_share_ties_and_span_zero_to_one() -> None:
    assert percentiles({"a": 1.0, "b": 2.0, "c": 2.0, "d": 3.0}) == {
        "a": 0.0,
        "b": 0.5,
        "c": 0.5,
        "d": 1.0,
    }
    assert percentiles({"a": 5.0}) == {"a": 0.5}
    assert percentiles({}) == {}


def _cards():
    return [
        build_scorecard(inputs(symbol="CHEAP", close=25.0), CFG),
        build_scorecard(inputs(symbol="MID", close=35.0), CFG),
        build_scorecard(inputs(symbol="DEAR", close=60.0), CFG),
        build_scorecard(inputs(symbol="ETF", is_etf=True), CFG),
        build_scorecard(inputs(symbol="BAD", yf_market_cap=1.0), CFG),
    ]


def test_rank_orders_by_value_then_quality_and_skips_the_unscored() -> None:
    ranks = rank_list(_cards(), "deep_value")
    assert set(ranks) == {"CHEAP", "MID", "DEAR"}
    assert [ranks[s].value_pct for s in ("CHEAP", "MID", "DEAR")] == [1.0, 0.5, 0.0]
    assert ranks["CHEAP"].quality_pct == 0.5  # identical fundamentals: every component ties
    assert ranks["CHEAP"].score == pytest.approx(0.75)


def test_a_name_on_both_lists_is_filed_where_it_ranks_higher() -> None:
    cards = _cards()
    deep, growth = rank_list(cards, "deep_value"), rank_list(cards, "quality_growth")
    filed = filed_lists(cards, deep, growth)
    assert filed["CHEAP"] == "deep_value"  # ties go to deep value
    deep["MID"] = deep["MID"].model_copy(update={"score": 0.1})
    assert filed_lists(cards, deep, growth)["MID"] == "quality_growth"
    assert filed["ETF"] == "deep_value" and filed["BAD"] == "deep_value"


def test_a_name_off_the_growth_list_is_never_filed_there() -> None:
    slow = financials(
        revenue=[1200, 1150, 1100, 1050, 1000],
        operating_cash_flow=[300, 295, 290, 285, 280],
        capital_expenditure=[60, 60, 60, 60, 60],
    )
    cards = [build_scorecard(inputs(symbol="SLOW", fin=slow), CFG)]
    growth = rank_list(cards, "quality_growth")
    deep = {"SLOW": rank_list(cards, "deep_value")["SLOW"].model_copy(update={"score": 0.0})}
    assert filed_lists(cards, deep, growth)["SLOW"] == "deep_value"


def test_the_relative_strength_line_is_the_bottom_thirty_percent() -> None:
    series = [price(30.0, ret_6m=r / 100.0, spy_ret_6m=0.0) for r in range(0, 11)]  # 0..10%
    assert rs_cutoff(series, 30.0) == pytest.approx(0.03)
    assert rs_cutoff(series[:5], 30.0) is None
    assert rs_cutoff([None, *series], 30.0) == pytest.approx(0.03)
