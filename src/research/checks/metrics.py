"""Registered metric functions for the checks engine.

Every function takes ``Mapping[str, float | None]`` and returns ``float | None``. Rules
that hold across every function:

* Return ``None`` on a missing input, a zero denominator, or a denominator whose sign
  would invert the meaning of the ratio (e.g. negative equity making a loss look like a
  strong ROE).
* Capital expenditure arrives from EDGAR as a **positive** outflow, so free cash flow is
  ``operating_cash_flow - capital_expenditure``.
* Dividends paid likewise arrives positive.
* Percentage metrics return percentage points (``15.0`` means 15%), never fractions.
* Multi-year metrics read prefixed series keys (``revenue_y0`` … ``revenue_y4``) that
  ``build_metrics`` flattens out of ``NormalizedFinancials.annual``.

The options-income metrics that need the analytics tier (``est_monthly_cc_yield_pct`` in
particular) are stubbed to ``None`` here and wired to real data sources by Task 5.5.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from src.research.schemas import NormalizedFinancials

MetricFn = Callable[[Mapping[str, float | None]], float | None]


def _num(m: Mapping[str, float | None], key: str) -> float | None:
    """Return the value for ``key`` or ``None`` if absent / None / non-numeric."""
    v = m.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_ratio(
    numerator: float | None,
    denominator: float | None,
) -> float | None:
    """Division guarded against None, zero, and negative denominators.

    A negative denominator inverts the meaning of a ratio (a loss divided by negative
    equity reads as a positive return). Rather than audit which ratios are
    sign-sensitive, every ratio refuses a non-positive denominator.
    """
    if numerator is None or denominator is None:
        return None
    if denominator <= 0:
        return None
    return numerator / denominator


# ── Value ─────────────────────────────────────────────────────────────────────


def _pe_ratio(m: Mapping[str, float | None]) -> float | None:
    price = _num(m, "price")
    eps = _num(m, "eps_diluted")
    if price is None or eps is None:
        return None
    if eps <= 0:
        return None
    return price / eps


def _peg_ratio(m: Mapping[str, float | None]) -> float | None:
    pe = _pe_ratio(m)
    growth = _num(m, "eps_growth_yoy")
    if pe is None or growth is None:
        return None
    if growth <= 0:
        return None
    return pe / growth


def _price_to_book(m: Mapping[str, float | None]) -> float | None:
    price = _num(m, "price")
    shares = _num(m, "shares_diluted")
    equity = _num(m, "stockholders_equity")
    if price is None or shares is None or equity is None:
        return None
    if equity <= 0:
        return None
    return (price * shares) / equity


def _price_to_sales(m: Mapping[str, float | None]) -> float | None:
    price = _num(m, "price")
    shares = _num(m, "shares_diluted")
    revenue = _num(m, "revenue")
    if price is None or shares is None or revenue is None:
        return None
    if revenue <= 0:
        return None
    return (price * shares) / revenue


def _fcf(m: Mapping[str, float | None]) -> float | None:
    ocf = _num(m, "operating_cash_flow")
    capex = _num(m, "capital_expenditure")
    if ocf is None or capex is None:
        return None
    return ocf - capex


def _fcf_yield_pct(m: Mapping[str, float | None]) -> float | None:
    price = _num(m, "price")
    shares = _num(m, "shares_diluted")
    fcf = _fcf(m)
    if price is None or shares is None or fcf is None:
        return None
    market_cap = price * shares
    if market_cap <= 0:
        return None
    return (fcf / market_cap) * 100.0


def _earnings_yield_pct(m: Mapping[str, float | None]) -> float | None:
    price = _num(m, "price")
    eps = _num(m, "eps_diluted")
    if price is None or eps is None:
        return None
    if price <= 0:
        return None
    return (eps / price) * 100.0


# ── Growth ────────────────────────────────────────────────────────────────────


def _yoy_growth_pct(m: Mapping[str, float | None], base: str) -> float | None:
    y0 = _num(m, f"{base}_y0")
    y1 = _num(m, f"{base}_y1")
    if y0 is None or y1 is None:
        return None
    if y1 <= 0:
        return None
    return ((y0 - y1) / y1) * 100.0


def _cagr_pct(m: Mapping[str, float | None], base: str, years: int) -> float | None:
    y0 = _num(m, f"{base}_y0")
    y_n = _num(m, f"{base}_y{years}")
    if y0 is None or y_n is None:
        return None
    if y_n <= 0 or y0 <= 0:
        return None
    return (((y0 / y_n) ** (1.0 / years)) - 1.0) * 100.0


def _revenue_growth_yoy_pct(m: Mapping[str, float | None]) -> float | None:
    return _yoy_growth_pct(m, "revenue")


def _revenue_cagr_3y_pct(m: Mapping[str, float | None]) -> float | None:
    return _cagr_pct(m, "revenue", 3)


def _eps_growth_yoy_pct(m: Mapping[str, float | None]) -> float | None:
    return _yoy_growth_pct(m, "eps_diluted")


def _eps_cagr_3y_pct(m: Mapping[str, float | None]) -> float | None:
    return _cagr_pct(m, "eps_diluted", 3)


def _fcf_growth_yoy_pct(m: Mapping[str, float | None]) -> float | None:
    # Read series keys for prior year
    ocf_y0 = _num(m, "operating_cash_flow_y0")
    capex_y0 = _num(m, "capital_expenditure_y0")
    ocf_y1 = _num(m, "operating_cash_flow_y1")
    capex_y1 = _num(m, "capital_expenditure_y1")
    if ocf_y0 is not None and capex_y0 is not None and ocf_y1 is not None and capex_y1 is not None:
        fcf_y0 = ocf_y0 - capex_y0
        fcf_y1 = ocf_y1 - capex_y1
        if fcf_y1 <= 0:
            return None
        return ((fcf_y0 - fcf_y1) / fcf_y1) * 100.0
    return None


def _net_margin_change_3y_pts(m: Mapping[str, float | None]) -> float | None:
    ni_y0 = _num(m, "net_income_y0")
    rev_y0 = _num(m, "revenue_y0")
    ni_y3 = _num(m, "net_income_y3")
    rev_y3 = _num(m, "revenue_y3")
    if ni_y0 is None or rev_y0 is None or ni_y3 is None or rev_y3 is None:
        return None
    if rev_y0 <= 0 or rev_y3 <= 0:
        return None
    margin_y0 = (ni_y0 / rev_y0) * 100.0
    margin_y3 = (ni_y3 / rev_y3) * 100.0
    return margin_y0 - margin_y3


# ── Past performance ──────────────────────────────────────────────────────────


def _roe_pct(m: Mapping[str, float | None]) -> float | None:
    ni = _num(m, "net_income")
    equity = _num(m, "stockholders_equity")
    ratio = _safe_ratio(ni, equity)
    return ratio * 100.0 if ratio is not None else None


def _roa_pct(m: Mapping[str, float | None]) -> float | None:
    ni = _num(m, "net_income")
    assets = _num(m, "total_assets")
    ratio = _safe_ratio(ni, assets)
    return ratio * 100.0 if ratio is not None else None


def _net_margin_pct(m: Mapping[str, float | None]) -> float | None:
    ni = _num(m, "net_income")
    revenue = _num(m, "revenue")
    ratio = _safe_ratio(ni, revenue)
    return ratio * 100.0 if ratio is not None else None


def _gross_margin_pct(m: Mapping[str, float | None]) -> float | None:
    gp = _num(m, "gross_profit")
    revenue = _num(m, "revenue")
    ratio = _safe_ratio(gp, revenue)
    return ratio * 100.0 if ratio is not None else None


def _count_positive_years(m: Mapping[str, float | None], base: str, n: int) -> float | None:
    """Count of positive years out of the last ``n``. Any missing year → UNKNOWN.

    The other multi-year metrics (``_worst_dividend_drop_5y_pct``, ``_cagr_pct``) return
    ``None`` when any of their ``n`` series values is missing, so a partial history
    reports UNKNOWN rather than a misleading count. This mirrors that contract: a
    company with only three years of filings reporting 3/3 profitable must read
    UNKNOWN, not pass by reading as 3/5.
    """
    count = 0
    for i in range(n):
        v = _num(m, f"{base}_y{i}")
        if v is None:
            return None
        if v > 0:
            count += 1
    return float(count)


def _profitable_years_of_five(m: Mapping[str, float | None]) -> float | None:
    return _count_positive_years(m, "net_income", 5)


def _positive_ocf_years_of_five(m: Mapping[str, float | None]) -> float | None:
    return _count_positive_years(m, "operating_cash_flow", 5)


# ── Financial health ──────────────────────────────────────────────────────────


def _current_ratio(m: Mapping[str, float | None]) -> float | None:
    ca = _num(m, "current_assets")
    cl = _num(m, "current_liabilities")
    return _safe_ratio(ca, cl)


def _debt_to_equity_pct(m: Mapping[str, float | None]) -> float | None:
    debt = _num(m, "long_term_debt")
    equity = _num(m, "stockholders_equity")
    ratio = _safe_ratio(debt, equity)
    return ratio * 100.0 if ratio is not None else None


def _ocf_to_debt_pct(m: Mapping[str, float | None]) -> float | None:
    ocf = _num(m, "operating_cash_flow")
    debt = _num(m, "long_term_debt")
    ratio = _safe_ratio(ocf, debt)
    return ratio * 100.0 if ratio is not None else None


def _cash_to_current_liabilities(m: Mapping[str, float | None]) -> float | None:
    cash = _num(m, "cash_and_equivalents")
    cl = _num(m, "current_liabilities")
    return _safe_ratio(cash, cl)


def _stockholders_equity_value(m: Mapping[str, float | None]) -> float | None:
    return _num(m, "stockholders_equity")


def _assets_minus_liabilities(m: Mapping[str, float | None]) -> float | None:
    assets = _num(m, "total_assets")
    liabilities = _num(m, "total_liabilities")
    if assets is None or liabilities is None:
        return None
    return assets - liabilities


# ── Dividend ──────────────────────────────────────────────────────────────────


def _dividends_paid_value(m: Mapping[str, float | None]) -> float | None:
    return _num(m, "dividends_paid")


def _payout_ratio_pct(m: Mapping[str, float | None]) -> float | None:
    divs = _num(m, "dividends_paid")
    ni = _num(m, "net_income")
    if divs is None or ni is None:
        return None
    if ni <= 0:
        return None
    return (divs / ni) * 100.0


def _dividend_fcf_coverage(m: Mapping[str, float | None]) -> float | None:
    divs = _num(m, "dividends_paid")
    fcf = _fcf(m)
    if divs is None or fcf is None:
        return None
    if divs <= 0:
        return None
    return fcf / divs


def _worst_dividend_drop_5y_pct(m: Mapping[str, float | None]) -> float | None:
    """Largest year-over-year drop as a positive percentage (0 = no drop)."""
    values = [_num(m, f"dividends_paid_y{i}") for i in range(5)]
    if any(v is None for v in values):
        return None
    worst = 0.0
    for i in range(4):
        prev = values[i + 1]
        curr = values[i]
        if prev is not None and curr is not None and prev > 0:
            drop = ((prev - curr) / prev) * 100.0
            if drop > worst:
                worst = drop
    return worst


def _dividend_cagr_5y_pct(m: Mapping[str, float | None]) -> float | None:
    return _cagr_pct(m, "dividends_paid", 4)


def _dividend_yield_pct(m: Mapping[str, float | None]) -> float | None:
    divs = _num(m, "dividends_paid")
    price = _num(m, "price")
    shares = _num(m, "shares_diluted")
    if divs is None or price is None or shares is None:
        return None
    market_cap = price * shares
    if market_cap <= 0:
        return None
    return (divs / market_cap) * 100.0


# ── Fund (ETF) ────────────────────────────────────────────────────────────────


def _expense_ratio_pct(m: Mapping[str, float | None]) -> float | None:
    return _num(m, "expense_ratio")


def _aum_usd(m: Mapping[str, float | None]) -> float | None:
    return _num(m, "total_assets_fund")


def _avg_dollar_volume_usd(m: Mapping[str, float | None]) -> float | None:
    price = _num(m, "price")
    vol = _num(m, "avg_volume")
    if price is None or vol is None:
        return None
    return price * vol


def _years_since_inception(m: Mapping[str, float | None]) -> float | None:
    return _num(m, "years_since_inception")


# ── Options income ────────────────────────────────────────────────────────────
# The simple passthroughs are implemented here; the cross-tier integration
# (populating these from the analytics tier) is Task 5.5's job. The
# ``est_monthly_cc_yield_pct`` metric is left as a stub for 5.5 to wire to
# ``_est_monthly_cc_yield`` in ``src/strategies/buy_candidates.py``.


def _iv_rank(m: Mapping[str, float | None]) -> float | None:
    return _num(m, "iv_rank")


def _vrp_points(m: Mapping[str, float | None]) -> float | None:
    iv = _num(m, "current_iv")
    hv = _num(m, "hv_30")
    if iv is None or hv is None:
        return None
    return iv - hv


def _atm_open_interest(m: Mapping[str, float | None]) -> float | None:
    return _num(m, "atm_open_interest")


def _atm_spread_pct(m: Mapping[str, float | None]) -> float | None:
    return _num(m, "atm_spread_pct")


def _est_monthly_cc_yield_pct(m: Mapping[str, float | None]) -> float | None:
    # A passthrough, like atm_open_interest/atm_spread_pct: build_metrics computes the
    # real value (it holds the IVStats object _est_monthly_cc_yield needs), this just reads it.
    return _num(m, "est_monthly_cc_yield_pct")


def _days_to_earnings(m: Mapping[str, float | None]) -> float | None:
    return _num(m, "days_to_earnings")


METRICS: dict[str, MetricFn] = {
    # value
    "pe_ratio": _pe_ratio,
    "peg_ratio": _peg_ratio,
    "price_to_book": _price_to_book,
    "price_to_sales": _price_to_sales,
    "fcf_yield_pct": _fcf_yield_pct,
    "earnings_yield_pct": _earnings_yield_pct,
    # growth
    "revenue_growth_yoy_pct": _revenue_growth_yoy_pct,
    "revenue_cagr_3y_pct": _revenue_cagr_3y_pct,
    "eps_growth_yoy_pct": _eps_growth_yoy_pct,
    "eps_cagr_3y_pct": _eps_cagr_3y_pct,
    "fcf_growth_yoy_pct": _fcf_growth_yoy_pct,
    "net_margin_change_3y_pts": _net_margin_change_3y_pts,
    # past
    "roe_pct": _roe_pct,
    "roa_pct": _roa_pct,
    "net_margin_pct": _net_margin_pct,
    "gross_margin_pct": _gross_margin_pct,
    "profitable_years_of_five": _profitable_years_of_five,
    "positive_ocf_years_of_five": _positive_ocf_years_of_five,
    # health
    "current_ratio": _current_ratio,
    "debt_to_equity_pct": _debt_to_equity_pct,
    "ocf_to_debt_pct": _ocf_to_debt_pct,
    "cash_to_current_liabilities": _cash_to_current_liabilities,
    "stockholders_equity_value": _stockholders_equity_value,
    "assets_minus_liabilities": _assets_minus_liabilities,
    # dividend
    "dividends_paid_value": _dividends_paid_value,
    "payout_ratio_pct": _payout_ratio_pct,
    "dividend_fcf_coverage": _dividend_fcf_coverage,
    "worst_dividend_drop_5y_pct": _worst_dividend_drop_5y_pct,
    "dividend_cagr_5y_pct": _dividend_cagr_5y_pct,
    "dividend_yield_pct": _dividend_yield_pct,
    # fund
    "expense_ratio_pct": _expense_ratio_pct,
    "aum_usd": _aum_usd,
    "avg_dollar_volume_usd": _avg_dollar_volume_usd,
    "years_since_inception": _years_since_inception,
    # options
    "iv_rank": _iv_rank,
    "vrp_points": _vrp_points,
    "atm_open_interest": _atm_open_interest,
    "atm_spread_pct": _atm_spread_pct,
    "est_monthly_cc_yield_pct": _est_monthly_cc_yield_pct,
    "days_to_earnings": _days_to_earnings,
}


# ── build_metrics ─────────────────────────────────────────────────────────────
# Assembles the flat metrics dict from NormalizedFinancials, a quote, IV stats, and
# fundamentals. The fundamental extraction is implemented here; the options/IV
# integration (reading from the analytics tier and the trading DB) is Task 5.5.


def _line_item_value(period_items: dict[str, Any], name: str) -> float | None:
    """Extract a line item value from one period's items dict."""
    item = period_items.get(name)
    if item is None:
        return None
    if hasattr(item, "value"):
        return item.value
    return item


def _extract_series(annual: list[Any], line_item: str, n: int) -> dict[str, float | None]:
    """Flatten up to ``n`` most-recent annual periods into ``{base}_y0..y{n-1}`` keys.

    Annual statements are assumed ordered most-recent first (as produced by the EDGAR
    ingest). If fewer than ``n`` periods exist, missing years are ``None``.
    """
    out: dict[str, float | None] = {}
    for i in range(n):
        if i < len(annual):
            out[f"{line_item}_y{i}"] = _line_item_value(annual[i].items, line_item)
        else:
            out[f"{line_item}_y{i}"] = None
    return out


def build_metrics(
    financials: NormalizedFinancials | None = None,
    *,
    price: float | None = None,
    is_etf: bool = False,
    iv_stats: Any | None = None,
    fundamentals: Any | None = None,
) -> dict[str, float | None]:
    """Assemble the flat metrics dict consumed by the check engine.

    Parameters
    ----------
    financials:
        Normalized financial statements from EDGAR. The most-recent annual period
        provides the current-period values (``revenue``, ``net_income``, etc.) and
        up to five periods are flattened into ``{item}_y0..y4`` series keys.
    price:
        Latest trade price.
    is_etf:
        When True, only ETF-relevant inputs are assembled (no XBRL line items).
    iv_stats:
        An ``IVStats``-like object. Task 5.5 populates this from the analytics tier.
    fundamentals:
        A ``FundamentalStats``-like object. Task 5.5 populates this.
    """
    metrics: dict[str, float | None] = {}

    if price is not None:
        metrics["price"] = float(price)

    annual = list(financials.annual) if financials and financials.annual else []

    if annual and not is_etf:
        latest = annual[0]
        items = latest.items
        # Current-period scalars
        for key in (
            "eps_diluted",
            "revenue",
            "net_income",
            "shares_diluted",
            "stockholders_equity",
            "total_assets",
            "total_liabilities",
            "current_assets",
            "current_liabilities",
            "long_term_debt",
            "cash_and_equivalents",
            "gross_profit",
            "operating_cash_flow",
            "capital_expenditure",
            "dividends_paid",
        ):
            metrics[key] = _line_item_value(items, key)

        # Multi-year series for growth and consistency metrics
        for key in (
            "revenue",
            "eps_diluted",
            "net_income",
            "operating_cash_flow",
            "capital_expenditure",
            "dividends_paid",
        ):
            metrics.update(_extract_series(annual, key, 5))

        # Derived: EPS growth YoY (used by PEG)
        eps_y0 = metrics.get("eps_diluted_y0")
        eps_y1 = metrics.get("eps_diluted_y1")
        if eps_y0 is not None and eps_y1 is not None and eps_y1 != 0:
            metrics["eps_growth_yoy"] = ((eps_y0 - eps_y1) / abs(eps_y1)) * 100.0
        else:
            metrics["eps_growth_yoy"] = None

    # Options / IV inputs from the analytics tier (Task 5.5). get_iv_stats degrades to an
    # all-None IVStats for a symbol with no iv_history (off-universe) rather than fabricating
    # a percentile, so these three stay honestly UNKNOWN downstream in that case.
    if iv_stats is not None:
        metrics["iv_rank"] = getattr(iv_stats, "iv_rank", None)
        metrics["current_iv"] = getattr(iv_stats, "current_iv", None)
        metrics["hv_30"] = getattr(iv_stats, "hv_30", None)
        metrics["est_monthly_cc_yield_pct"] = _est_monthly_cc_yield_from_iv_stats(iv_stats)

    if fundamentals is not None:
        # FundamentalStats' field is `next_earnings` (a date), not `next_earnings_date`.
        next_earnings = getattr(fundamentals, "next_earnings", None)
        if next_earnings is not None:
            today = date.today()
            if isinstance(next_earnings, datetime):
                next_earnings = next_earnings.date()
            delta = (next_earnings - today).days
            # A past-due date means the calendar is stale, not that earnings are 0 days
            # out — reporting a negative number here would still fail the >45 check
            # correctly, but None is the honest "we don't actually know" answer, and it
            # can never silently pass as a large sentinel would.
            metrics["days_to_earnings"] = float(delta) if delta >= 0 else None
        else:
            metrics["days_to_earnings"] = None

        # ETF fund-data sourcing (Task 5.5, bundled here per the Task 5.4 handoff note —
        # no other task in the plan owns it). expense_ratio/total_assets/avg_volume/
        # inception_date are ETF-only fields on FundamentalStats, None for a stock.
        if is_etf:
            metrics["expense_ratio"] = getattr(fundamentals, "expense_ratio", None)
            metrics["total_assets_fund"] = getattr(fundamentals, "total_assets", None)
            avg_volume = getattr(fundamentals, "avg_volume", None)
            metrics["avg_volume"] = float(avg_volume) if avg_volume is not None else None
            inception = getattr(fundamentals, "inception_date", None)
            if inception is not None:
                days = (date.today() - inception).days
                metrics["years_since_inception"] = round(days / 365.25, 2) if days >= 0 else None
            else:
                metrics["years_since_inception"] = None

    return metrics


def _est_monthly_cc_yield_from_iv_stats(iv_stats: Any) -> float | None:
    """Percentage-point wrapper around buy_candidates' CC-yield heuristic.

    Reuses ``_est_monthly_cc_yield`` rather than reimplementing it (Task 5.5). That
    function returns a fraction of spot; every other percentage metric in this module is
    in percentage points, so the result is scaled by 100 to match.
    """
    from src.strategies.buy_candidates import _est_monthly_cc_yield

    try:
        fraction = _est_monthly_cc_yield(iv_stats)
    except AttributeError:
        return None
    return fraction * 100.0 if fraction is not None else None
