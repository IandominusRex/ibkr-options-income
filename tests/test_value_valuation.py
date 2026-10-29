"""Python's fair value, pinned (value book spec §6.5)."""

from __future__ import annotations

import pytest

from src.common.config import ValueValuationCfg
from src.value.valuation import (
    dcf,
    fair_value,
    haircut_growth,
    implied_growth,
    method_a,
    method_b,
    method_c,
    method_d,
    method_ptbv,
)

CFG = ValueValuationCfg()


def test_the_dcf_reproduces_the_specs_googl_growth_value() -> None:
    """Spec §6.5: FCF ~$73B, SBC ~$24B, 12.2B shares, 14% growth, r 8%, half SBC -> ~$151."""
    out = dcf((73 - 12) / 12.2, 0.14, 0.08, 0.025, 10)
    assert out is not None
    assert out.value == pytest.approx(150.5160010022292)
    assert out.terminal_share == pytest.approx(0.629928628446452)
    full_sbc = dcf((73 - 24) / 12.2, 0.14, 0.09, 0.025, 10)
    assert full_sbc is not None and full_sbc.value == pytest.approx(101.33, abs=0.01)


def test_the_dcf_refuses_a_rate_at_or_below_terminal_growth() -> None:
    assert dcf(1.0, 0.1, 0.02, 0.025, 10) is None


def test_implied_growth_round_trips() -> None:
    g = implied_growth(30.0, 2.6, 0.09, 0.025, 10)
    assert g == pytest.approx(-0.0487482551644291)
    out = dcf(2.6, g, 0.09, 0.025, 10)
    assert out is not None and out.value == pytest.approx(30.0)
    assert implied_growth(1e6, 2.6, 0.09, 0.025, 10) is None  # needs more than 100%/yr
    assert implied_growth(1.0, 2.6, 0.09, 0.025, 10) == -0.5
    assert implied_growth(30.0, -1.0, 0.09, 0.025, 10) is None


def test_method_a_is_earnings_power() -> None:
    assert method_a(2.6, CFG).value == pytest.approx(2.6 / 0.07)
    assert method_a(-1.0, CFG).state == "absent"
    assert method_a(None, CFG).state == "absent"


def test_method_b_haircuts_realised_growth() -> None:
    b = method_b(2.6, 0.1474149978141155, CFG)
    assert b.state == "ok"
    assert b.inputs["growth"] == pytest.approx(0.7 * 0.1474149978141155)
    assert b.value == pytest.approx(56.564396041711674)
    assert haircut_growth(0.30, CFG) == pytest.approx(0.105)  # capped at 15% first
    assert haircut_growth(-0.05, CFG) == -0.05  # a decline is not haircut upward


def test_method_b_drops_a_terminal_heavy_valuation() -> None:
    loose = ValueValuationCfg(discount_rate_deep=0.03, g_floor=0.01)
    b = method_b(1.0, 0.1, loose)
    assert b.state == "unreliable"
    assert b.inputs["terminal_share"] == pytest.approx(0.9550167581948823)


def test_method_d_is_the_growth_dcf_capped_at_twenty_percent() -> None:
    d = method_d(2.8, 0.1474149978141155, CFG)
    assert d.value == pytest.approx(86.86667560395772)
    assert method_d(2.8, 0.35, CFG).inputs["growth"] == 0.2
    assert method_d(2.8, -0.01, CFG).state == "absent"


def test_method_c_is_absent_until_point_in_time_prices_exist() -> None:
    assert method_c().state == "absent"


def test_justified_price_to_tangible_book() -> None:
    p = method_ptbv(0.14, 28.0, CFG)
    assert p.value == pytest.approx((0.14 - 0.025) / (0.09 - 0.025) * 28.0)
    assert method_ptbv(0.02, 28.0, CFG).state == "absent"
    assert method_ptbv(None, 28.0, CFG).state == "absent"


def test_fair_value_is_the_median_of_the_methods_present() -> None:
    methods = [method_a(2.6, CFG), method_b(2.6, 0.1474149978141155, CFG), method_c()]
    assert fair_value(methods, ("A", "B", "C")) == pytest.approx(
        (37.142857142857146 + 56.564396041711674) / 2
    )
    assert fair_value([method_c()], ("C",)) is None
