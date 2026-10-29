"""The dry run's pass funnel (value book spec §17)."""

from __future__ import annotations

from datetime import timedelta

from src.common.config import get_config
from src.value.funnel import build_funnel, render_funnel, render_name
from src.value.scorecard import build_scorecard
from tests.value_fixtures import AS_OF, financials, inputs

CFG = get_config().value


def _cards():
    return [
        build_scorecard(inputs(symbol="READY", close=30.0), CFG),
        build_scorecard(
            inputs(symbol="WATCH", close=30.0, next_earnings=AS_OF + timedelta(days=3)), CFG
        ),
        build_scorecard(inputs(symbol="DEAR", close=60.0), CFG),
        build_scorecard(
            inputs(symbol="DILUTE", fin=financials(shares_diluted=[110, 104, 98, 92, 86])), CFG
        ),
        build_scorecard(inputs(symbol="ETF", is_etf=True), CFG),
        build_scorecard(inputs(symbol="BAD", yf_market_cap=1.0), CFG),
        build_scorecard(inputs(symbol="REIT", industry="Retail REITs"), CFG),
    ]


def test_the_funnel_counts_every_step() -> None:
    f = build_funnel(_cards())
    assert (f.names, f.etf, f.data_quality_pass) == (7, 1, 5)
    assert f.data_quality["dq.market_cap"].unknown == 1
    assert dict(f.not_applicable) == {"REIT: FFO is not reliably tagged": 1}
    assert dict(f.health_states) == {"pass": 3, "fail": 1}
    assert f.health["operating"]["health.dilution"].failed == 1
    deep = f.lists["deep_value"]
    assert (deep.scored, deep.entry_pass, deep.fair_value, deep.mos_pass, deep.timing_pass) == (
        3,
        3,
        3,
        2,
        1,
    )
    assert dict(deep.verdicts) == {"READY": 1, "WATCH": 1, "WAIT": 1, "NO": 1}
    assert f.lists["quality_growth"].mos_pass == 3  # the growth ceiling (78.18) is above 60


def test_the_rendered_funnel_and_name_carry_the_numbers() -> None:
    cards = _cards()
    text = render_funnel(build_funnel(cards), "Test")
    assert "== Test: 7 names ==" in text and "health.dilution" in text
    detail = render_name(cards[0])
    assert detail.startswith("## READY  class=operating  price=30.00")
    assert "[deep_value] READY: fair value 46.85" in detail
    assert "realised FCF/share CAGR 14.7%" in detail
