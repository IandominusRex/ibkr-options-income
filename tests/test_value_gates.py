"""Classification, data quality and the health gates (value book spec §6.3-6.5)."""

from __future__ import annotations

from datetime import date

import pytest

from src.common.config import ValueCfg, get_config
from src.value import gates
from src.value.metrics import build_years
from src.value.schemas import combine
from tests.value_fixtures import BANK, financials, inputs, price

RULES = get_config().value.rules


def _years(fin):
    return build_years(fin)


@pytest.mark.parametrize(
    ("industry", "is_etf", "expected"),
    [
        ("Application Software", True, "etf"),
        ("Retail REITs", False, "reit"),
        ("Diversified Banks", False, "bank"),
        ("Banks - Regional", False, "bank"),
        ("Property & Casualty Insurance", False, "insurer"),
        ("Semiconductors", False, "cyclical"),
        ("Application Software", False, "operating"),
    ],
)
def test_classify_by_industry(industry, is_etf, expected) -> None:
    inp = inputs(industry=industry, is_etf=is_etf)
    years, _ = _years(inp.financials)
    assert gates.classify(inp, years, RULES) == expected


def test_a_swinging_fcf_margin_makes_a_cyclical() -> None:
    fin = financials(operating_cash_flow=[500, 80, 400, 60, 300])  # margins 26%, 0%, 26%, -1%, 24%
    inp = inputs(fin=fin)
    years, _ = _years(fin)
    assert gates.classify(inp, years, RULES) == "cyclical"


def test_preprofit_is_three_losses_in_five_years() -> None:
    years, _ = _years(financials(net_income=[-50, -40, -30, 10, 5]))
    assert gates.preprofit(years, RULES) is True
    years, _ = _years(financials(net_income=[-50, -40, 30, 10, 5]))
    assert gates.preprofit(years, RULES) is False


def _dq(inp):
    years, shares = gates.build_years_for(inp)
    return {c.id: c.state for c in gates.data_quality(inp, years, shares, RULES)}


def test_data_quality_passes_on_the_fixture() -> None:
    assert set(_dq(inputs()).values()) == {"pass"}


@pytest.mark.parametrize(
    ("kwargs", "failing"),
    [
        ({"yf_market_cap": 3000.0 * 1.2}, "dq.market_cap"),
        ({"price_series": price(30.0, sessions=150)}, "dq.price_history"),
        ({"fin": financials(filed=date(2025, 6, 1))}, "dq.filing_age"),
        ({"fin": financials(shares_diluted=[100, 37, 37, 37, 37])}, "dq.share_continuity"),
    ],
)
def test_each_data_quality_check_says_unknown(kwargs, failing) -> None:
    assert _dq(inputs(**kwargs))[failing] == "unknown"


def test_too_few_annual_periods_is_unknown() -> None:
    fin = financials()
    fin.annual = fin.annual[:4]
    assert _dq(inputs(fin=fin))["dq.annual_periods"] == "unknown"


def test_a_missing_yfinance_cap_is_unknown_never_a_pass() -> None:
    inp = inputs().model_copy(update={"yf_market_cap": None})
    assert _dq(inp)["dq.market_cap"] == "unknown"


def test_no_us_gaap_facts_is_one_unknown_check() -> None:
    fin = financials()
    fin.has_us_gaap = False
    assert _dq(inputs(fin=fin)) == {"dq.filings": "unknown"}


def _health(inp, *, cyclical=False):
    years, _ = gates.build_years_for(inp)
    checks = gates.operating_health(inp, years, 3000.0, RULES, cyclical=cyclical)
    return {c.id: c for c in checks}


def test_the_steady_fixture_passes_every_operating_gate() -> None:
    h = _health(inputs())
    assert {k: v.state for k, v in h.items()} == {
        "health.piotroski": "pass",
        "health.altman_z": "pass",
        "health.profitable_years": "pass",
        "health.fcf_positive_years": "pass",
        "health.fcf_ttm_positive": "pass",
        "health.net_debt_to_ebitda": "pass",
        "health.interest_coverage": "pass",
        "health.beneish_m": "pass",
        "health.dilution": "pass",
    }
    assert h["health.net_debt_to_ebitda"].detail == "net cash"  # 400 debt, 500 cash
    assert h["health.interest_coverage"].actual == 40.0


def test_net_debt_over_ebitda_and_coverage_with_debt() -> None:
    fin = financials(long_term_debt=[1500, 420, 440, 460, 480])
    h = _health(inputs(fin=fin))
    assert h["health.net_debt_to_ebitda"].actual == pytest.approx(1000 / 460)
    assert h["health.net_debt_to_ebitda"].state == "pass"


def test_coverage_is_implied_when_interest_is_untagged_and_debt_is_net() -> None:
    fin = financials(long_term_debt=[1500, 420, 440, 460, 480])
    fin.ttm.pop("interest_expense")
    h = _health(inputs(fin=fin))
    assert h["health.interest_coverage"].actual == pytest.approx(400 / (1500 * 0.08))
    assert h["health.interest_coverage"].detail.startswith("implied")


def test_a_cyclical_is_judged_across_the_cycle() -> None:
    fin = financials(
        operating_income=[-50, 355, 317.5, 282.5, 250], operating_cash_flow=[30, 335, 300, 268, 240]
    )
    h = _health(inputs(fin=fin), cyclical=True)
    assert "health.fcf_ttm_positive" not in h
    assert h["health.fcf_positive_years"].state == "pass"  # 4 of 5 positive
    assert h["health.interest_coverage"].detail == "5-year median EBIT"
    assert h["health.interest_coverage"].actual == pytest.approx(282.5 / 10)


def test_enough_positive_years_pass_even_with_a_missing_year() -> None:
    fin = financials(
        net_income=[300, 266, 238, None, 187], capital_expenditure=[80, 75, 70, None, None]
    )
    h = _health(inputs(fin=fin))
    assert h["health.profitable_years"].state == "pass"  # 4 positive, bar 4
    assert h["health.fcf_positive_years"].state == "pass"  # 3 positive, bar 3


def test_missing_years_that_could_have_cleared_the_bar_are_unknown() -> None:
    fin = financials(
        net_income=[300, 266, None, None, 187], capital_expenditure=[80, 75, None, None, None]
    )
    h = _health(inputs(fin=fin))
    assert h["health.profitable_years"].state == "unknown"  # 3 positive + 2 missing >= 4
    assert "2023" in h["health.profitable_years"].detail
    assert "2022" in h["health.profitable_years"].detail
    assert h["health.fcf_positive_years"].state == "unknown"  # 2 positive + 3 missing >= 3
    assert "2021" in h["health.fcf_positive_years"].detail


def test_too_few_positive_years_fail_even_counting_the_missing_ones() -> None:
    fin = financials(net_income=[300, -10, -5, None, -3])
    h = _health(inputs(fin=fin))
    assert h["health.profitable_years"].state == "fail"  # 1 positive + 1 missing < 4


def test_a_bank_with_missing_profit_years_is_unknown_not_failed() -> None:
    c = _bank(net_income=[30, 28, None, None, 22])
    assert c["bank.profitable_years"].state == "unknown"  # 3 positive + 2 missing >= 4


def test_untagged_debt_in_the_latest_year_is_unknown_not_net_cash() -> None:
    fin = financials(long_term_debt=[None, 420, 440, 460, 480])
    h = _health(inputs(fin=fin))
    assert h["health.net_debt_to_ebitda"].state == "unknown"
    assert "untagged" in h["health.net_debt_to_ebitda"].detail
    assert gates.net_debt_latest(inputs(fin=fin)) is None


def test_untagged_debt_leaves_implied_coverage_unknown() -> None:
    fin = financials(long_term_debt=[None, 420, 440, 460, 480])
    fin.ttm.pop("interest_expense")
    h = _health(inputs(fin=fin))
    assert h["health.interest_coverage"].state == "unknown"
    assert "untagged" in h["health.interest_coverage"].detail


def test_a_company_that_never_tagged_debt_still_reads_as_net_cash() -> None:
    fin = financials(long_term_debt=[None, None, None, None, None])
    assert gates.net_debt_latest(inputs(fin=fin)) == -500.0
    assert _health(inputs(fin=fin))["health.net_debt_to_ebitda"].state == "pass"


def test_net_debt_with_negative_ebitda_fails() -> None:
    fin = financials(
        long_term_debt=[1500, 420, 440, 460, 480],
        operating_income=[-200, 355, 317.5, 282.5, 250],
        depreciation_amortization=[60, 55, 50, 46, 42],
    )
    h = _health(inputs(fin=fin))
    assert h["health.net_debt_to_ebitda"].state == "fail"


def _bank(cfg: ValueCfg | None = None, **overrides):
    rules = (cfg or ValueCfg()).rules
    inp = inputs(
        symbol="HBR", fin=financials(BANK, **overrides), close=40.0, industry="Diversified Banks"
    )
    years, _ = gates.build_years_for(inp)
    return {c.id: c for c in gates.financial_health(inp, years, rules, insurer=False)}


def test_a_bank_without_tagged_cet1_is_unknown_never_a_silent_pass() -> None:
    h = _bank()
    assert h["bank.cet1"].state == "unknown"
    assert h["bank.rote_median"].actual == pytest.approx(14.025974025974024)
    assert h["bank.nco"].actual == pytest.approx((2.0 / 1000) / (1.5 / 800))
    assert combine(list(h.values())) == "unknown"


def test_the_operator_may_switch_the_cet1_check_off() -> None:
    h = _bank(ValueCfg(rules={"banks": {"require_cet1": False}}))
    assert h["bank.cet1"].state == "not_applicable"
    assert combine(list(h.values())) == "pass"


def test_a_tagged_cet1_is_checked() -> None:
    assert _bank(cet1_ratio=[0.118, None, None, None, None])["bank.cet1"].state == "pass"
    assert _bank(cet1_ratio=[0.05, None, None, None, None])["bank.cet1"].state == "fail"


def test_a_credit_turn_fails_the_charge_off_gate() -> None:
    assert _bank(net_charge_offs=[4.0, 1.8, 1.6, 1.4, 1.5])["bank.nco"].state == "fail"


def test_an_insurer_reads_its_combined_ratio() -> None:
    table = dict(
        BANK, premiums_earned=[80, 78, 76, 74, 72], benefits_losses_expenses=[76, 70, 80, 72, 68]
    )
    inp = inputs(
        symbol="INS", fin=financials(table), close=40.0, industry="Property & Casualty Insurance"
    )
    years, _ = gates.build_years_for(inp)
    h = {c.id: c for c in gates.financial_health(inp, years, RULES, insurer=True)}
    assert h["bank.combined_ratio"].actual == 4.0  # 2023's 105% is the one bad year
    assert h["bank.combined_ratio"].state == "pass"
    assert h["bank.cet1"].state == "not_applicable" and h["bank.nco"].state == "not_applicable"


def test_edgar_shares_fall_back_for_a_multi_class_filer() -> None:
    """META, GOOGL and HOOD tag no undimensioned cover-page count (checked 2026-10-29)."""
    from src.common.value_types import InstantPoint

    fin = financials()
    fin.cover_shares = None
    fin.latest["shares_outstanding"] = InstantPoint(value=99.0, end=date(2025, 12, 31))
    assert gates.edgar_shares(inputs(fin=fin)) == 99.0
    fin.latest.pop("shares_outstanding")
    assert gates.edgar_shares(inputs(fin=fin)) == 100.0  # the newest weighted diluted count
    fin.shares_latest = None
    assert gates.edgar_shares(inputs(fin=fin)) == 100.0  # the last fiscal year's
