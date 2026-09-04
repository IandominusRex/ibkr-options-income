"""Metric functions: known values, plus the five bug classes the rules call out."""

from __future__ import annotations

import pytest

from src.research.checks.metrics import METRICS, build_metrics

_EPS = 1e-9


def _m(**over: float | None) -> dict[str, float | None]:
    base: dict[str, float | None] = {
        "price": 100.0,
        "eps_diluted": 5.0,
        "revenue": 1000.0,
        "net_income": 120.0,
        "shares_diluted": 10.0,
        "stockholders_equity": 500.0,
        "total_assets": 900.0,
        "total_liabilities": 300.0,
        "current_assets": 400.0,
        "current_liabilities": 200.0,
        "long_term_debt": 100.0,
        "cash_and_equivalents": 150.0,
        "gross_profit": 500.0,
        "operating_cash_flow": 200.0,
        "capital_expenditure": 40.0,
        "dividends_paid": 30.0,
        "eps_growth_yoy": 12.0,
    }
    base.update(over)
    return base


def test_pe_ratio() -> None:
    assert METRICS["pe_ratio"](_m()) == pytest.approx(20.0)


def test_peg_ratio() -> None:
    # P/E 20 / growth 12 = 1.666...
    assert METRICS["peg_ratio"](_m()) == pytest.approx(20.0 / 12.0)


def test_price_to_book() -> None:
    # (100 * 10) / 500 = 2.0
    assert METRICS["price_to_book"](_m()) == pytest.approx(2.0)


def test_price_to_sales() -> None:
    # (100 * 10) / 1000 = 1.0
    assert METRICS["price_to_sales"](_m()) == pytest.approx(1.0)


def test_fcf_yield_pct() -> None:
    # FCF = 200 - 40 = 160; market cap = 100*10 = 1000; 16%
    assert METRICS["fcf_yield_pct"](_m()) == pytest.approx(16.0)


def test_earnings_yield_pct() -> None:
    # 5 / 100 * 100 = 5%
    assert METRICS["earnings_yield_pct"](_m()) == pytest.approx(5.0)


def test_roe_pct() -> None:
    # 120 / 500 * 100 = 24%
    assert METRICS["roe_pct"](_m()) == pytest.approx(24.0)


def test_roa_pct() -> None:
    # 120 / 900 * 100 = 13.33%
    assert METRICS["roa_pct"](_m()) == pytest.approx(120.0 / 900.0 * 100.0)


def test_net_margin_pct() -> None:
    # 120 / 1000 * 100 = 12%
    assert METRICS["net_margin_pct"](_m()) == pytest.approx(12.0)


def test_gross_margin_pct() -> None:
    # 500 / 1000 * 100 = 50%
    assert METRICS["gross_margin_pct"](_m()) == pytest.approx(50.0)


def test_current_ratio() -> None:
    # 400 / 200 = 2.0
    assert METRICS["current_ratio"](_m()) == pytest.approx(2.0)


def test_debt_to_equity_pct() -> None:
    # 100 / 500 * 100 = 20%
    assert METRICS["debt_to_equity_pct"](_m()) == pytest.approx(20.0)


def test_ocf_to_debt_pct() -> None:
    # 200 / 100 * 100 = 200%
    assert METRICS["ocf_to_debt_pct"](_m()) == pytest.approx(200.0)


def test_cash_to_current_liabilities() -> None:
    # 150 / 200 = 0.75
    assert METRICS["cash_to_current_liabilities"](_m()) == pytest.approx(0.75)


def test_stockholders_equity_value() -> None:
    assert METRICS["stockholders_equity_value"](_m()) == pytest.approx(500.0)


def test_assets_minus_liabilities() -> None:
    # 900 - 300 = 600
    assert METRICS["assets_minus_liabilities"](_m()) == pytest.approx(600.0)


def test_dividends_paid_value() -> None:
    assert METRICS["dividends_paid_value"](_m()) == pytest.approx(30.0)


def test_payout_ratio_pct() -> None:
    # 30 / 120 * 100 = 25%
    assert METRICS["payout_ratio_pct"](_m()) == pytest.approx(25.0)


def test_dividend_fcf_coverage() -> None:
    # FCF = 160; divs = 30; 160 / 30 = 5.333...
    assert METRICS["dividend_fcf_coverage"](_m()) == pytest.approx(160.0 / 30.0)


def test_dividend_yield_pct() -> None:
    # 30 / (100 * 10) * 100 = 3%
    assert METRICS["dividend_yield_pct"](_m()) == pytest.approx(3.0)


def test_vrp_points() -> None:
    assert METRICS["vrp_points"]({"current_iv": 45.0, "hv_30": 30.0}) == pytest.approx(15.0)


def test_avg_dollar_volume_usd() -> None:
    assert METRICS["avg_dollar_volume_usd"]({"price": 100.0, "avg_volume": 5.0}) == pytest.approx(
        500.0
    )


def test_expense_ratio_pct_passthrough() -> None:
    assert METRICS["expense_ratio_pct"]({"expense_ratio": 0.12}) == pytest.approx(0.12)


def test_aum_usd_passthrough() -> None:
    assert METRICS["aum_usd"]({"total_assets_fund": 5e9}) == pytest.approx(5e9)


def test_worst_dividend_drop_5y_pct_no_drop() -> None:
    series = {f"dividends_paid_y{i}": 10.0 for i in range(5)}
    assert METRICS["worst_dividend_drop_5y_pct"](series) == pytest.approx(0.0)


def test_worst_dividend_drop_5y_pct_with_drop() -> None:
    # y4=10, y3=10, y2=10, y1=10, y0=8 -> drop of 20% from y1 to y0
    series = {f"dividends_paid_y{i}": 10.0 for i in range(5)}
    series["dividends_paid_y0"] = 8.0
    assert METRICS["worst_dividend_drop_5y_pct"](series) == pytest.approx(20.0)


def test_dividend_cagr_5y_pct() -> None:
    # y4=10, y0=16.1051... -> CAGR ~10% over 4 years
    series = {f"dividends_paid_y{i}": 10.0 for i in range(5)}
    series["dividends_paid_y0"] = 10.0 * (1.1**4)
    assert METRICS["dividend_cagr_5y_pct"](series) == pytest.approx(10.0, rel=1e-3)


def test_revenue_cagr_3y_pct() -> None:
    # y3=1000, y0=1331 -> CAGR = 10%
    series = {"revenue_y0": 1331.0, "revenue_y3": 1000.0}
    assert METRICS["revenue_cagr_3y_pct"](series) == pytest.approx(10.0, rel=1e-3)


def test_revenue_growth_yoy_pct() -> None:
    series = {"revenue_y0": 1100.0, "revenue_y1": 1000.0}
    assert METRICS["revenue_growth_yoy_pct"](series) == pytest.approx(10.0)


def test_eps_growth_yoy_pct() -> None:
    series = {"eps_diluted_y0": 5.5, "eps_diluted_y1": 5.0}
    assert METRICS["eps_growth_yoy_pct"](series) == pytest.approx(10.0)


def test_profitable_years_of_five() -> None:
    series = {f"net_income_y{i}": 10.0 for i in range(5)}
    series["net_income_y2"] = -5.0
    assert METRICS["profitable_years_of_five"](series) == 4.0


def test_profitable_years_of_five_partial_history_is_unknown() -> None:
    """A company with only three years of filings must read UNKNOWN, not pass as 3/5.

    The other multi-year metrics return None on any missing series value; this mirrors
    that contract so a partial history never produces a misleading count.
    """
    series = {f"net_income_y{i}": 10.0 for i in range(3)}  # only y0..y2 present
    assert METRICS["profitable_years_of_five"](series) is None


def test_positive_ocf_years_of_five_partial_history_is_unknown() -> None:
    series = {f"operating_cash_flow_y{i}": 10.0 for i in range(4)}  # missing y4
    assert METRICS["positive_ocf_years_of_five"](series) is None


def test_positive_ocf_years_of_five() -> None:
    series = {f"operating_cash_flow_y{i}": 10.0 for i in range(5)}
    assert METRICS["positive_ocf_years_of_five"](series) == 5.0


def test_net_margin_change_3y_pts() -> None:
    # y3: 100/1000 = 10%; y0: 150/1000 = 15%; change = 5 pts
    series = {
        "net_income_y0": 150.0,
        "revenue_y0": 1000.0,
        "net_income_y3": 100.0,
        "revenue_y3": 1000.0,
    }
    assert METRICS["net_margin_change_3y_pts"](series) == pytest.approx(5.0)


def test_fcf_growth_yoy_pct() -> None:
    # y1: OCF 200 - capex 40 = 160; y0: OCF 240 - capex 40 = 200; growth = 25%
    series = {
        "operating_cash_flow_y0": 240.0,
        "capital_expenditure_y0": 40.0,
        "operating_cash_flow_y1": 200.0,
        "capital_expenditure_y1": 40.0,
    }
    assert METRICS["fcf_growth_yoy_pct"](series) == pytest.approx(25.0)


# ── The five behaviours the spec calls out ────────────────────────────────────


def test_division_by_zero_yields_none_not_inf() -> None:
    assert METRICS["roe_pct"]({"net_income": 10.0, "stockholders_equity": 0.0}) is None


def test_negative_equity_does_not_flip_the_sign_of_roe() -> None:
    """A negative denominator would make a loss look like a strong return."""
    assert METRICS["roe_pct"]({"net_income": -10.0, "stockholders_equity": -50.0}) is None


def test_fcf_subtracts_capex_as_a_positive_outflow() -> None:
    """EDGAR reports PaymentsToAcquirePropertyPlantAndEquipment as a POSITIVE number."""
    m = {
        "operating_cash_flow": 200.0,
        "capital_expenditure": 40.0,
        "price": 100.0,
        "shares_diluted": 10.0,
    }
    assert METRICS["fcf_yield_pct"](m) == pytest.approx(16.0)  # (200-40)/1000 * 100


def test_payout_ratio_uses_the_absolute_dividend_outflow() -> None:
    m = {"dividends_paid": 30.0, "net_income": 120.0}
    assert METRICS["payout_ratio_pct"](m) == pytest.approx(25.0)


def test_a_missing_input_returns_none_rather_than_raising() -> None:
    for name, fn in METRICS.items():
        assert fn({}) is None, name


def test_every_metric_named_in_yaml_is_registered() -> None:
    from src.research.checks.definitions import load_checks

    missing = {c.fn for c in load_checks()} - set(METRICS)
    assert not missing, f"Metric functions missing: {missing}"


def test_build_metrics_extracts_current_period_values() -> None:
    from datetime import date

    from src.research.schemas import LineItemValue, NormalizedFinancials, PeriodStatement

    items = {
        "revenue": LineItemValue(line_item="revenue", value=1000.0),
        "net_income": LineItemValue(line_item="net_income", value=120.0),
        "eps_diluted": LineItemValue(line_item="eps_diluted", value=5.0),
    }
    period = PeriodStatement(period_end=date(2025, 12, 31), period_type="annual", items=items)
    fin = NormalizedFinancials(symbol="TEST", cik="0000000000", annual=[period])

    metrics = build_metrics(fin, price=100.0)
    assert metrics["price"] == 100.0
    assert metrics["revenue"] == 1000.0
    assert metrics["net_income"] == 120.0
    assert metrics["eps_diluted"] == 5.0


def test_build_metrics_flattens_series_keys() -> None:
    from datetime import date

    from src.research.schemas import LineItemValue, NormalizedFinancials, PeriodStatement

    annual = [
        PeriodStatement(
            period_end=date(2025, 12, 31),
            period_type="annual",
            items={"revenue": LineItemValue(line_item="revenue", value=1100.0)},
        ),
        PeriodStatement(
            period_end=date(2024, 12, 31),
            period_type="annual",
            items={"revenue": LineItemValue(line_item="revenue", value=1000.0)},
        ),
    ]
    fin = NormalizedFinancials(symbol="TEST", cik="0000000000", annual=annual)
    metrics = build_metrics(fin, price=100.0)
    assert metrics["revenue_y0"] == 1100.0
    assert metrics["revenue_y1"] == 1000.0
    assert metrics["revenue_y2"] is None


def test_build_metrics_is_etf_skips_xbrl() -> None:
    from datetime import date

    from src.research.schemas import LineItemValue, NormalizedFinancials, PeriodStatement

    period = PeriodStatement(
        period_end=date(2025, 12, 31),
        period_type="annual",
        items={"revenue": LineItemValue(line_item="revenue", value=1000.0)},
    )
    fin = NormalizedFinancials(symbol="SPY", cik="0000000000", annual=[period])
    metrics = build_metrics(fin, price=400.0, is_etf=True)
    assert "revenue" not in metrics or metrics.get("revenue") is None
    assert metrics["price"] == 400.0
