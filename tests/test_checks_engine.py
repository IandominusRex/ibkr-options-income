"""Four states, and the arithmetic that keeps 3-of-6 from looking like 3-of-4."""

from __future__ import annotations

from src.research.checks.engine import CheckState, evaluate, summarize


def _metrics(**over: float | None) -> dict[str, float | None]:
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


def test_a_passing_metric_is_pass() -> None:
    results = {r.id: r for r in evaluate(_metrics(), is_etf=False)}
    assert results["health.current_ratio"].state is CheckState.PASS
    assert results["health.current_ratio"].actual == 2.0


def test_a_failing_metric_is_fail() -> None:
    results = {r.id: r for r in evaluate(_metrics(current_assets=100.0), is_etf=False)}
    assert results["health.current_ratio"].state is CheckState.FAIL


def test_a_missing_input_is_unknown_never_fail() -> None:
    """The single most important behaviour in this milestone."""
    results = {r.id: r for r in evaluate(_metrics(current_assets=None), is_etf=False)}
    assert results["health.current_ratio"].state is CheckState.UNKNOWN
    assert results["health.current_ratio"].actual is None


def test_an_absent_input_key_is_also_unknown() -> None:
    metrics = _metrics()
    del metrics["current_assets"]
    results = {r.id: r for r in evaluate(metrics, is_etf=False)}
    assert results["health.current_ratio"].state is CheckState.UNKNOWN


def test_between_is_inclusive_of_its_bounds() -> None:
    r = {x.id: x for x in evaluate(_metrics(dividends_paid=0.0), is_etf=False)}
    # payout ratio 0% sits on the lower bound of [0, 90] and must pass.
    assert r["dividend.payout_sustainable"].state is CheckState.PASS


def test_an_etf_gets_not_applicable_for_the_fundamental_categories() -> None:
    results = {r.id: r for r in evaluate(_metrics(), is_etf=True)}
    assert results["past.roe"].state is CheckState.NOT_APPLICABLE
    assert results["value.pe_reasonable"].state is CheckState.NOT_APPLICABLE


def test_not_applicable_is_distinct_from_unknown() -> None:
    """One means the data is missing, the other means the question does not apply.
    Conflating them makes a serious ETF look like a data failure."""
    results = {r.id: r for r in evaluate({}, is_etf=True)}
    assert results["past.roe"].state is CheckState.NOT_APPLICABLE
    assert results["fund.expense_ratio"].state is CheckState.UNKNOWN


def test_options_checks_are_evaluated_for_an_etf() -> None:
    results = {r.id: r for r in evaluate(_metrics(iv_rank=45.0), is_etf=True)}
    assert results["options.iv_rank"].state is CheckState.PASS


def test_summary_counts_evaluable_separately_from_total() -> None:
    results = evaluate(_metrics(current_assets=None), is_etf=False)
    health = next(c for c in summarize(results) if c.category == "health")
    assert health.total == 6
    assert health.unknown == 1
    assert health.evaluable == health.passed + health.failed
    assert health.evaluable == 5


def test_summary_excludes_not_applicable_categories(recwarn) -> None:
    cats = {c.category for c in summarize(evaluate(_metrics(), is_etf=True))}
    assert "fund" in cats
    assert "options" in cats
    assert "past" not in cats


def test_every_result_carries_its_statement_and_threshold() -> None:
    for r in evaluate(_metrics(), is_etf=False):
        assert r.statement.endswith("?")
        if r.state in (CheckState.PASS, CheckState.FAIL):
            assert r.threshold is not None


def test_options_earnings_clear_evaluates_on_days_to_earnings() -> None:
    """requires must name the key the metric reads, not a source field.

    `options.earnings_clear` reads `days_to_earnings` (populated by build_metrics from
    the fundamentals next-earnings date). Its `requires` must name `days_to_earnings`,
    otherwise the check is permanently UNKNOWN even when the data is present.
    """
    results = {r.id: r for r in evaluate({"days_to_earnings": 60.0}, is_etf=False)}
    assert results["options.earnings_clear"].state is CheckState.PASS
    assert results["options.earnings_clear"].actual == 60.0


def test_fund_track_record_evaluates_on_years_since_inception() -> None:
    """`fund.track_record` reads `years_since_inception`, not `inception_date`."""
    results = {r.id: r for r in evaluate({"years_since_inception": 5.0}, is_etf=True)}
    assert results["fund.track_record"].state is CheckState.PASS
    assert results["fund.track_record"].actual == 5.0


def test_profitable_5y_partial_history_is_unknown_not_fail() -> None:
    """A company with only three years of filings must read UNKNOWN, not pass as 3/5.

    `_count_positive_years` returns None when any of the five series values is missing,
    so a partial history reports UNKNOWN rather than a misleading count that would
    FAIL the `gte 5.0` threshold.
    """
    metrics = {f"net_income_y{i}": 10.0 for i in range(3)}  # only y0..y2
    metrics["net_income"] = 10.0  # current-period present so the check is attempted
    results = {r.id: r for r in evaluate(metrics, is_etf=False)}
    assert results["past.profitable_5y"].state is CheckState.UNKNOWN
