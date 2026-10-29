"""Piotroski, Altman and Beneish on the Steady Co fixture, pinned (value book spec §6.4)."""

from __future__ import annotations

import pytest

from src.value.metrics import build_years
from src.value.scores import altman_z, beneish_m, piotroski
from tests.value_fixtures import financials


def _years(**overrides):
    return build_years(financials(**overrides))[0]


def test_piotroski_scores_eight_of_nine() -> None:
    f = piotroski(_years())
    assert f.value == 8.0
    assert f.parts["gross_margin_rose"] == 0.0  # 60% both years
    assert f.missing == []


def test_piotroski_with_too_much_missing_is_none() -> None:
    f = piotroski(
        _years(
            current_assets=[None] * 5,
            current_liabilities=[None] * 5,
            gross_profit=[None] * 5,
            accounts_receivable=[None] * 5,
            operating_cash_flow=[None] * 5,
        )
    )
    assert f.value is None
    assert set(f.missing) >= {"liquidity_rose", "gross_margin_rose", "ocf_positive", "accruals"}


def test_piotroski_does_not_punish_a_debt_free_company() -> None:
    f = piotroski(_years(long_term_debt=[0, 0, 0, 0, 0]))
    assert f.parts["leverage_fell"] == 1.0


def test_altman_z_pinned() -> None:
    z = altman_z(_years()[0], market_cap=3000.0)
    # 1.2(600/3000) + 1.4(1500/3000) + 3.3(400/3000) + 0.6(3000/1200) + 1600/3000
    assert z.value == pytest.approx(3.4133333333)
    assert altman_z(_years(retained_earnings=[None] * 5)[0], 3000.0).value is None


def test_beneish_m_pinned() -> None:
    m = beneish_m(_years())
    assert m.value == pytest.approx(-2.488221536443591)
    assert m.parts["sgi"] == pytest.approx(1600 / 1420)
    assert m.parts["tata"] == pytest.approx((300 - 380) / 3000)


def test_beneish_needs_its_four_heavy_indices() -> None:
    assert beneish_m(_years(accounts_receivable=[None] * 5)).value is None


def test_beneish_falls_back_to_neutral_for_the_light_indices() -> None:
    m = beneish_m(_years(sga=[None] * 5))
    assert "sgai" in m.missing and m.value is not None
