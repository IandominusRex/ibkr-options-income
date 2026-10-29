"""Per-year figures derived from filed line items (spec §6.4-6.5). Pure: no I/O.

Line-item names are the canonical keys of ``config/research_concepts.yaml``. A missing item is
None, never zero, except where a docstring says otherwise and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from statistics import median, pstdev

from src.common.value_types import ValueFinancials

# A ratio between adjacent share counts at or beyond this (or its inverse) is a split, a reverse
# split, or something the scorecard cannot explain (spec §6.3, "share-class mapping applied").
# A ratio inside the band is left alone unless it sits within tolerance of a split factor
# (so the 3-for-2 at 1.5 is reachable; any other sub-1.8 move, e.g. an acquisition, is ignored).
SPLIT_RATIO = 1.8
_SPLIT_FACTORS = (1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0)
_SPLIT_TOLERANCE = 0.05


@dataclass(frozen=True, slots=True)
class Year:
    """One fiscal year, every figure in dollars (shares in shares)."""

    end: date
    revenue: float | None
    gross_profit: float | None
    operating_income: float | None
    net_income: float | None
    net_income_common: float | None
    ocf: float | None
    capex: float | None
    sbc: float | None
    da: float | None
    interest: float | None
    pretax: float | None
    tax: float | None
    sga: float | None
    total_assets: float | None
    total_liabilities: float | None
    equity: float | None
    current_assets: float | None
    current_liabilities: float | None
    long_term_debt: float | None
    debt: float | None  # every interest-bearing line tagged; None when none is
    cash: float | None  # cash + current marketable securities
    receivables: float | None
    ppe: float | None
    retained: float | None
    goodwill: float | None
    intangibles: float | None
    preferred: float | None
    shares: float | None  # split-normalised
    nco: float | None
    loans: float | None
    cet1_pct: float | None
    premiums: float | None
    benefits_losses_expenses: float | None
    # No debt line tagged this year although an older year in the window has one: the debt is
    # untagged here, not zero (unknown is never zero).
    debt_untagged: bool = False

    @property
    def fcf(self) -> float | None:
        if self.ocf is None or self.capex is None:
            return None
        return self.ocf - self.capex

    @property
    def gross_margin(self) -> float | None:
        if self.gross_profit is None or not self.revenue:
            return None
        return self.gross_profit / self.revenue

    @property
    def fcf_margin(self) -> float | None:
        fcf = self.fcf
        if fcf is None or not self.revenue:
            return None
        return fcf / self.revenue

    @property
    def tangible_equity(self) -> float | None:
        """Common equity less goodwill, intangibles and preferred (absent parts count as 0)."""
        if self.equity is None:
            return None
        return (
            self.equity
            - (self.goodwill or 0.0)
            - (self.intangibles or 0.0)
            - (self.preferred or 0.0)
        )


@dataclass(slots=True)
class ShareNormalisation:
    adjustments: list[str] = field(default_factory=list)
    unexplained: list[str] = field(default_factory=list)


def _sum_present(*values: float | None) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _liabilities(items: dict[str, float]) -> float | None:
    """Total liabilities, else total assets less equity (the balance-sheet identity; AMD tags
    no ``Liabilities`` total)."""
    if items.get("total_liabilities") is not None:
        return items["total_liabilities"]
    assets, equity = items.get("total_assets"), items.get("stockholders_equity")
    if assets is None or equity is None:
        return None
    return assets - equity


def _split_factor(ratio: float) -> float | None:
    for f in _SPLIT_FACTORS:
        for candidate in (f, 1.0 / f):
            if abs(ratio / candidate - 1.0) <= _SPLIT_TOLERANCE:
                return candidate
    return None


def normalise_shares(
    newest: float | None, annual: list[float | None], ends: list[date]
) -> tuple[list[float | None], ShareNormalisation]:
    """Rescale older share counts across splits so per-share series are comparable.

    *newest* is the most recent count (a 10-Q filed after the last 10-K, or None); *annual* is
    newest first. Walking back, a ratio between the newer and the older count at or beyond
    ``SPLIT_RATIO`` (either way) that sits within 5% of a whole split factor rescales every older
    year by that factor and is recorded; one that does not is recorded as unexplained, which the
    data-quality gate turns into UNKNOWN.
    """
    out = list(annual)
    note = ShareNormalisation()
    chain: list[tuple[float | None, str]] = [(newest, "latest")] + [
        (v, str(e.year)) for v, e in zip(out, ends, strict=True)
    ]
    for i in range(1, len(chain)):
        newer = next((v for v, _ in reversed(chain[:i]) if v), None)
        older, label = chain[i]
        if not newer or not older:
            continue
        ratio = newer / older
        factor = _split_factor(ratio)
        if factor is None and 1.0 / SPLIT_RATIO < ratio < SPLIT_RATIO:
            continue
        if factor is None:
            note.unexplained.append(f"share count jumps {ratio:.2f}x into FY{label}")
            continue
        for j in range(i, len(chain)):
            v, lab = chain[j]
            chain[j] = (v * factor if v is not None else None, lab)
        note.adjustments.append(f"shares FY{label} and earlier x{factor:g} (split)")
    return [v for v, _ in chain[1:]], note


def build_years(fin: ValueFinancials) -> tuple[list[Year], ShareNormalisation]:
    """Every fiscal year in *fin*, newest first, with split-normalised share counts."""
    raw_shares: list[float | None] = []
    for p in fin.annual:
        it = p.items
        raw_shares.append(it.get("shares_diluted") or it.get("shares_outstanding"))
    newest = fin.shares_latest
    shares, note = normalise_shares(newest, raw_shares, [p.period_end for p in fin.annual])

    years: list[Year] = []
    for p, sh in zip(fin.annual, shares, strict=True):
        it = p.items
        revenue = it.get("revenue")
        gross = it.get("gross_profit")
        if gross is None and revenue is not None and it.get("cost_of_revenue") is not None:
            gross = revenue - it["cost_of_revenue"]
        cet1 = it.get("cet1_ratio")
        if cet1 is not None and cet1 <= 1.0:
            cet1 *= 100.0
        years.append(
            Year(
                end=p.period_end,
                revenue=revenue,
                gross_profit=gross,
                operating_income=it.get("operating_income"),
                net_income=it.get("net_income"),
                net_income_common=it.get("net_income_common", it.get("net_income")),
                ocf=it.get("operating_cash_flow"),
                capex=it.get("capital_expenditure"),
                sbc=it.get("sbc"),
                da=it.get("depreciation_amortization"),
                interest=it.get("interest_expense"),
                pretax=it.get("pretax_income"),
                tax=it.get("income_tax"),
                sga=it.get("sga"),
                total_assets=it.get("total_assets"),
                total_liabilities=_liabilities(it),
                equity=it.get("stockholders_equity"),
                current_assets=it.get("current_assets"),
                current_liabilities=it.get("current_liabilities"),
                long_term_debt=it.get("long_term_debt"),
                debt=_sum_present(
                    it.get("long_term_debt"),
                    it.get("long_term_debt_current"),
                    it.get("commercial_paper"),
                    it.get("short_term_borrowings"),
                ),
                cash=_sum_present(it.get("cash_and_equivalents"), it.get("marketable_securities")),
                receivables=it.get("accounts_receivable"),
                ppe=it.get("ppe_net"),
                retained=it.get("retained_earnings"),
                goodwill=it.get("goodwill"),
                intangibles=it.get("intangibles"),
                preferred=it.get("preferred_equity"),
                shares=sh,
                nco=it.get("net_charge_offs"),
                loans=it.get("loans"),
                cet1_pct=cet1,
                premiums=it.get("premiums_earned"),
                benefits_losses_expenses=it.get("benefits_losses_expenses"),
            )
        )
    for i, y in enumerate(years):
        if y.debt is None and any(o.debt is not None for o in years[i + 1 :]):
            years[i] = replace(y, debt_untagged=True)
    return years, note


# ── series helpers ──────────────────────────────────────────────────────────────────────────


def cagr(series: list[float | None], max_years: int = 5, min_years: int = 4) -> float | None:
    """Compound annual growth from the oldest usable year (at most *max_years* back) to the
    newest. *series* is newest first. None unless both ends are positive and the span is at
    least *min_years* (spec §6.0's "5-year" rates use 4 years when only five periods exist)."""
    if not series or series[0] is None or series[0] <= 0:
        return None
    span = min(max_years, len(series) - 1)
    while span >= min_years:
        base = series[span]
        if base is not None and base > 0:
            return (series[0] / base) ** (1.0 / span) - 1.0
        span -= 1
    return None


def last_n(series: list[float | None], n: int = 5) -> list[float]:
    """The present values among the newest *n*."""
    return [v for v in series[:n] if v is not None]


def median_of(series: list[float | None], n: int = 5) -> float | None:
    vals = last_n(series, n)
    return median(vals) if vals else None


def stdev_of(series: list[float | None], n: int = 5) -> float | None:
    """Population standard deviation of the newest *n* present values (None below 3)."""
    vals = last_n(series, n)
    return pstdev(vals) if len(vals) >= 3 else None


def count_positive(series: list[float | None], n: int = 5) -> int:
    return sum(1 for v in series[:n] if v is not None and v > 0)


def roic(y: Year) -> float | None:
    """NOPAT over year-end invested capital (equity + debt - cash), as a fraction.

    Tax rate = tax / pre-tax income, clamped to [0, 35%]; 21% when either is missing or pre-tax
    income is not positive. None when invested capital is not positive or when the year's debt
    is untagged although an older year's is (untagged debt is not zero)."""
    if y.operating_income is None or y.equity is None or y.debt_untagged:
        return None
    rate = 0.21
    if y.tax is not None and y.pretax is not None and y.pretax > 0:
        rate = min(max(y.tax / y.pretax, 0.0), 0.35)
    invested = y.equity + (y.debt or 0.0) - (y.cash or 0.0)
    if invested <= 0:
        return None
    return y.operating_income * (1.0 - rate) / invested
