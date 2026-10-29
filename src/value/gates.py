"""Classification, the data-quality gate and the health gates (spec §6.3-6.5). Pure: no I/O.

Health is hard and a conjunction: any FAIL is NO whatever anyone thinks of the story; an
UNKNOWN (never a silent pass) keeps the name off both lists until the data exists.
"""

from __future__ import annotations

from src.common.config import ValueRulesCfg
from src.common.value_types import ValueInputs
from src.value.metrics import (
    ShareNormalisation,
    Year,
    build_years,
    cagr,
    count_positive,
    median_of,
    stdev_of,
)
from src.value.schemas import Check, CompanyClass
from src.value.scores import altman_z, beneish_m, piotroski


def _industry_in(inputs: ValueInputs, names: list[str]) -> bool:
    industry = (inputs.classification.industry or "").strip().lower()
    return bool(industry) and industry in {n.strip().lower() for n in names}


def classify(inputs: ValueInputs, years: list[Year], rules: ValueRulesCfg) -> CompanyClass:
    """etf -> reit -> bank -> insurer -> cyclical (industry list, or FCF-margin variability
    above the bar) -> operating."""
    c = rules.classification
    if inputs.classification.is_etf:
        return "etf"
    marker = c.reit_marker.lower()
    if marker and marker in (inputs.classification.industry or "").lower():
        return "reit"
    if _industry_in(inputs, c.bank_industries):
        return "bank"
    if _industry_in(inputs, c.insurer_industries):
        return "insurer"
    if _industry_in(inputs, c.cyclical_industries):
        return "cyclical"
    spread = stdev_of([y.fcf_margin for y in years])
    if spread is not None and spread * 100.0 > c.cyclical_fcf_margin_stdev_pts:
        return "cyclical"
    return "operating"


def preprofit(years: list[Year], rules: ValueRulesCfg) -> bool:
    """A net loss in at least ``preprofit_loss_years_min`` of the last five fiscal years."""
    losses = sum(1 for y in years[:5] if y.net_income is not None and y.net_income <= 0)
    return losses >= rules.classification.preprofit_loss_years_min


def edgar_shares(inputs: ValueInputs) -> float | None:
    """Cover-page count, else the newest balance-sheet count, else the newest weighted diluted
    count, quarterly then annual (multi-class filers tag no undimensioned cover count)."""
    fin = inputs.financials
    if fin is None:
        return None
    if fin.cover_shares:
        return fin.cover_shares
    point = fin.latest.get("shares_outstanding")
    if point is not None and point.value > 0:
        return point.value
    if fin.shares_latest:
        return fin.shares_latest
    return fin.annual[0].items.get("shares_diluted") if fin.annual else None


def data_quality(
    inputs: ValueInputs, years: list[Year], shares: ShareNormalisation, rules: ValueRulesCfg
) -> list[Check]:
    """Spec §6.3. Each check is pass or unknown; the gate is their conjunction."""
    dq = rules.data_quality
    fin = inputs.financials
    checks: list[Check] = []
    if fin is None or not fin.has_us_gaap:
        return [Check(id="dq.filings", state="unknown", detail="no us-gaap XBRL facts")]

    n = len(years)
    checks.append(
        Check(
            id="dq.annual_periods",
            state="pass" if n >= dq.min_annual_periods else "unknown",
            actual=float(n),
            threshold=float(dq.min_annual_periods),
        )
    )
    if fin.latest_filed is None:
        checks.append(Check(id="dq.filing_age", state="unknown", detail="no filing date"))
    else:
        age = (inputs.as_of - fin.latest_filed).days
        checks.append(
            Check(
                id="dq.filing_age",
                state="pass" if age <= dq.max_filing_age_days else "unknown",
                actual=float(age),
                threshold=float(dq.max_filing_age_days),
            )
        )
    price = inputs.price
    if price is None or price.sessions < dq.min_price_sessions:
        checks.append(
            Check(
                id="dq.price_history",
                state="unknown",
                actual=float(price.sessions) if price else 0.0,
                threshold=float(dq.min_price_sessions),
            )
        )
    else:
        checks.append(
            Check(
                id="dq.price_history",
                state="pass",
                actual=float(price.sessions),
                threshold=float(dq.min_price_sessions),
            )
        )
    count = edgar_shares(inputs)
    if count is None or price is None or not inputs.yf_market_cap:
        checks.append(
            Check(
                id="dq.market_cap",
                state="unknown",
                detail="EDGAR share count, price or yfinance market cap missing",
            )
        )
    else:
        edgar_cap = count * price.close
        gap = abs(edgar_cap - inputs.yf_market_cap) / inputs.yf_market_cap
        checks.append(
            Check(
                id="dq.market_cap",
                state="pass" if gap <= dq.market_cap_tolerance else "unknown",
                actual=gap,
                threshold=dq.market_cap_tolerance,
                detail=f"EDGAR {edgar_cap / 1e9:.1f}B vs yfinance {inputs.yf_market_cap / 1e9:.1f}B",
            )
        )
    checks.append(
        Check(
            id="dq.share_continuity",
            state="unknown" if shares.unexplained else "pass",
            detail="; ".join(shares.unexplained or shares.adjustments),
        )
    )
    return checks


def _ttm(inputs: ValueInputs, item: str) -> float | None:
    fin = inputs.financials
    if fin is None:
        return None
    point = fin.ttm.get(item)
    return point.value if point is not None else None


def _latest(inputs: ValueInputs, item: str) -> float | None:
    fin = inputs.financials
    if fin is None:
        return None
    point = fin.latest.get(item)
    return point.value if point is not None else None


def ttm_fcf(inputs: ValueInputs) -> float | None:
    ocf, capex = _ttm(inputs, "operating_cash_flow"), _ttm(inputs, "capital_expenditure")
    if ocf is None or capex is None:
        return None
    return ocf - capex


def gross_debt_latest(inputs: ValueInputs) -> float | None:
    parts = [
        _latest(inputs, k)
        for k in (
            "long_term_debt",
            "long_term_debt_current",
            "commercial_paper",
            "short_term_borrowings",
        )
    ]
    present = [v for v in parts if v is not None]
    return sum(present) if present else None


def net_debt_latest(inputs: ValueInputs) -> float | None:
    """Newest balance sheet: every interest-bearing line tagged, less cash and current
    marketable securities. None when neither debt nor cash is tagged."""
    debt_parts = [
        _latest(inputs, k)
        for k in (
            "long_term_debt",
            "long_term_debt_current",
            "commercial_paper",
            "short_term_borrowings",
        )
    ]
    cash_parts = [_latest(inputs, k) for k in ("cash_and_equivalents", "marketable_securities")]
    if all(v is None for v in debt_parts + cash_parts):
        return None
    return sum(v for v in debt_parts if v is not None) - sum(v for v in cash_parts if v is not None)


def check_at_least(id_: str, actual: float | None, bar: float, detail: str = "") -> Check:
    if actual is None:
        return Check(id=id_, state="unknown", threshold=bar, detail=detail or "not computable")
    return Check(
        id=id_,
        state="pass" if actual >= bar else "fail",
        actual=actual,
        threshold=bar,
        detail=detail,
    )


def check_at_most(id_: str, actual: float | None, bar: float, detail: str = "") -> Check:
    if actual is None:
        return Check(id=id_, state="unknown", threshold=bar, detail=detail or "not computable")
    return Check(
        id=id_,
        state="pass" if actual <= bar else "fail",
        actual=actual,
        threshold=bar,
        detail=detail,
    )


def dilution_pct(years: list[Year]) -> float | None:
    g = cagr([y.shares for y in years])
    return None if g is None else g * 100.0


def operating_health(
    inputs: ValueInputs,
    years: list[Year],
    market_cap: float | None,
    rules: ValueRulesCfg,
    *,
    cyclical: bool,
) -> list[Check]:
    """Spec §6.4: financial health, earnings quality and dilution. Cyclicals are judged across
    the cycle: counts of five years instead of TTM, and 5-year median EBITDA and EBIT."""
    h = rules.health
    checks: list[Check] = []
    f = piotroski(years)
    checks.append(
        check_at_least("health.piotroski", f.value, float(h.piotroski_min), ", ".join(f.missing))
    )
    z = altman_z(years[0], market_cap) if years else None
    z_value = z.value if z else None
    checks.append(
        Check(
            id="health.altman_z",
            state="unknown"
            if z_value is None
            else ("pass" if z_value > h.altman_z_min else "fail"),
            actual=z_value,
            threshold=h.altman_z_min,
            detail=", ".join(z.missing) if z else "no fiscal year",
        )
    )

    min_profitable = h.cyclical_profitable_years_min if cyclical else h.profitable_years_min
    ni = [y.net_income for y in years]
    checks.append(
        check_at_least(
            "health.profitable_years",
            float(count_positive(ni)) if len(years) >= 5 else None,
            float(min_profitable),
        )
    )
    min_fcf_years = h.cyclical_fcf_positive_years_min if cyclical else h.fcf_positive_years_min
    fcf_years = [y.fcf for y in years]
    checks.append(
        check_at_least(
            "health.fcf_positive_years",
            float(count_positive(fcf_years)) if len(years) >= 5 else None,
            float(min_fcf_years),
        )
    )
    if not cyclical:
        fcf = ttm_fcf(inputs)
        checks.append(
            Check(
                id="health.fcf_ttm_positive",
                state="unknown" if fcf is None else ("pass" if fcf > 0 else "fail"),
                actual=fcf,
                threshold=0.0,
            )
        )

    nd = net_debt_latest(inputs)
    ebit_ttm, da_ttm = _ttm(inputs, "operating_income"), _ttm(inputs, "depreciation_amortization")
    if cyclical:
        ebitda = median_of(
            [
                None if y.operating_income is None else y.operating_income + (y.da or 0.0)
                for y in years
            ]
        )
        ebit = median_of([y.operating_income for y in years])
        basis = "5-year median"
    else:
        ebitda = None if ebit_ttm is None else ebit_ttm + (da_ttm or 0.0)
        ebit = ebit_ttm
        basis = "TTM"
    if nd is not None and nd <= 0:
        checks.append(
            Check(
                id="health.net_debt_to_ebitda",
                state="pass",
                actual=0.0,
                threshold=h.net_debt_to_ebitda_max,
                detail="net cash",
            )
        )
    elif nd is None or ebitda is None:
        checks.append(
            Check(
                id="health.net_debt_to_ebitda", state="unknown", threshold=h.net_debt_to_ebitda_max
            )
        )
    elif ebitda <= 0:
        checks.append(
            Check(
                id="health.net_debt_to_ebitda",
                state="fail",
                threshold=h.net_debt_to_ebitda_max,
                detail=f"net debt with non-positive {basis} EBITDA",
            )
        )
    else:
        checks.append(
            check_at_most(
                "health.net_debt_to_ebitda",
                nd / ebitda,
                h.net_debt_to_ebitda_max,
                f"{basis} EBITDA" + ("" if da_ttm is not None or cyclical else ", D&A not tagged"),
            )
        )

    interest = _ttm(inputs, "interest_expense")
    if interest is not None and interest > 0:
        checks.append(
            check_at_least(
                "health.interest_coverage",
                None if ebit is None else ebit / interest,
                h.interest_coverage_min,
                f"{basis} EBIT",
            )
        )
    elif nd is not None and nd <= 0:
        checks.append(
            Check(
                id="health.interest_coverage",
                state="pass",
                threshold=h.interest_coverage_min,
                detail="no material interest expense (net cash)",
            )
        )
    else:
        # Apple stopped tagging InterestExpense after FY2023. Coverage implied by charging the
        # gross debt a conservative rate, labelled as implied.
        debt = gross_debt_latest(inputs)
        implied = None if ebit is None or not debt else ebit / (debt * h.assumed_interest_rate)
        checks.append(
            check_at_least(
                "health.interest_coverage",
                implied,
                h.interest_coverage_min,
                f"implied: interest expense not tagged; gross debt charged "
                f"{h.assumed_interest_rate:.0%}",
            )
        )

    m = beneish_m(years)
    checks.append(check_at_most("health.beneish_m", m.value, h.beneish_m_max, ", ".join(m.missing)))
    checks.append(check_at_most("health.dilution", dilution_pct(years), h.dilution_max_pct))
    return checks


def rote_series(years: list[Year]) -> list[float | None]:
    """Return on average tangible common equity, newest first (a fraction)."""
    out: list[float | None] = []
    for i, y in enumerate(years):
        prev = years[i + 1] if i + 1 < len(years) else None
        tce = y.tangible_equity
        if tce is None or y.net_income_common is None:
            out.append(None)
            continue
        base = (
            tce
            if prev is None or prev.tangible_equity is None
            else (tce + prev.tangible_equity) / 2
        )
        out.append(y.net_income_common / base if base > 0 else None)
    return out


def _combined_ratio_pct(y: Year) -> float | None:
    """Approximate combined ratio: total benefits, losses and expenses less interest, over
    earned premiums (XBRL tags no combined ratio)."""
    if not y.premiums or y.benefits_losses_expenses is None:
        return None
    return (y.benefits_losses_expenses - (y.interest or 0.0)) / y.premiums * 100.0


def tbv_per_share(y: Year) -> float | None:
    if y.tangible_equity is None or not y.shares:
        return None
    return y.tangible_equity / y.shares


def financial_health(
    inputs: ValueInputs, years: list[Year], rules: ValueRulesCfg, *, insurer: bool
) -> list[Check]:
    """Spec §6.4, banks and insurers: no FCF, coverage, Piotroski, Altman or Beneish."""
    b = rules.banks
    checks: list[Check] = []
    ni = [y.net_income for y in years]
    checks.append(
        check_at_least(
            "bank.profitable_years",
            float(count_positive(ni)) if len(years) >= 5 else None,
            float(b.profitable_years_min),
        )
    )
    rote = rote_series(years)
    med = median_of(rote)
    checks.append(
        check_at_least(
            "bank.rote_median", None if med is None else med * 100.0, b.rote_median_min_pct
        )
    )
    sd = stdev_of(rote)
    checks.append(
        check_at_most("bank.rote_stdev", None if sd is None else sd * 100.0, b.rote_stdev_max_pts)
    )
    tbv_now = tbv_per_share(years[0]) if years else None
    tbv_then = tbv_per_share(years[min(5, len(years) - 1)]) if len(years) >= 5 else None
    if tbv_now is None or tbv_then is None:
        checks.append(Check(id="bank.tbv_growth", state="unknown"))
    else:
        checks.append(
            Check(
                id="bank.tbv_growth",
                state="pass" if tbv_now > tbv_then else "fail",
                actual=tbv_now,
                threshold=tbv_then,
                detail="tangible book per share now vs five years earlier",
            )
        )
    if insurer:
        checks.append(Check(id="bank.nco", state="not_applicable"))
        checks.append(Check(id="bank.cet1", state="not_applicable"))
        if _industry_in(inputs, rules.classification.combined_ratio_industries):
            ratios = [_combined_ratio_pct(y) for y in years[:5]]
            present = [r for r in ratios if r is not None]
            good = sum(1 for r in present if r <= b.combined_ratio_max_pct)
            checks.append(
                Check(
                    id="bank.combined_ratio",
                    state="unknown"
                    if len(present) < 5
                    else ("pass" if good >= b.combined_ratio_years_min else "fail"),
                    actual=float(good),
                    threshold=float(b.combined_ratio_years_min),
                    detail="years at or under 100% (approximate: total benefits, losses and "
                    "expenses less interest, over earned premiums)",
                )
            )
        else:
            checks.append(Check(id="bank.combined_ratio", state="not_applicable"))
    else:
        nco_ratios = [None if y.nco is None or not y.loans else y.nco / y.loans for y in years[:5]]
        med_nco = median_of(nco_ratios)
        if nco_ratios[0] is None or med_nco is None:
            checks.append(Check(id="bank.nco", state="unknown", threshold=b.nco_multiple_max))
        elif med_nco == 0:
            checks.append(
                Check(
                    id="bank.nco",
                    state="pass" if nco_ratios[0] == 0 else "fail",
                    actual=nco_ratios[0],
                    threshold=b.nco_multiple_max,
                )
            )
        else:
            checks.append(
                check_at_most(
                    "bank.nco",
                    nco_ratios[0] / med_nco,
                    b.nco_multiple_max,
                    "NCO/loans vs own 5-year median",
                )
            )
        cet1 = years[0].cet1_pct if years else None
        if not b.require_cet1:
            checks.append(
                Check(id="bank.cet1", state="not_applicable", detail="disabled by config")
            )
        else:
            checks.append(
                check_at_least(
                    "bank.cet1",
                    cet1,
                    b.cet1_min_pct,
                    "" if cet1 is not None else "CET1 not tagged in XBRL",
                )
            )
        checks.append(Check(id="bank.combined_ratio", state="not_applicable"))
    checks.append(
        check_at_most("bank.dilution", dilution_pct(years), rules.health.dilution_max_pct)
    )
    return checks


def build_years_for(inputs: ValueInputs) -> tuple[list[Year], ShareNormalisation]:
    if inputs.financials is None:
        return [], ShareNormalisation()
    return build_years(inputs.financials)


def latest_tbv_per_share(inputs: ValueInputs, years: list[Year]) -> float | None:
    """Tangible book per share from the newest balance sheet (a 10-Q's when newer than the
    10-K), else the last fiscal year's."""
    equity = _latest(inputs, "stockholders_equity")
    count = inputs.financials.shares_latest if inputs.financials else None
    if equity is not None and count:
        tangible = equity - sum(
            v or 0.0
            for v in (_latest(inputs, k) for k in ("goodwill", "intangibles", "preferred_equity"))
        )
        return tangible / count
    return tbv_per_share(years[0]) if years else None
