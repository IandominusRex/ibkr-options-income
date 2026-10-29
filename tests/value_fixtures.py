"""Synthetic companies for the value book's tests (Part 1). Values in $ millions, shares in
millions, so per-share figures are dollars."""

from __future__ import annotations

from datetime import date, timedelta

from src.common.value_types import (
    AnnualPeriod,
    Classification,
    InstantPoint,
    PriceSeries,
    TtmPoint,
    ValueFinancials,
    ValueInputs,
)

AS_OF = date(2026, 3, 31)
YEAR_ENDS = [date(y, 12, 31) for y in (2025, 2024, 2023, 2022, 2021)]

# "Steady Co": a healthy grower, newest year first.
STEADY: dict[str, list[float]] = {
    "revenue": [1600, 1420, 1270, 1130, 1000],
    "gross_profit": [960, 852, 762, 678, 600],
    "operating_income": [400, 355, 317.5, 282.5, 250],
    "net_income": [300, 266, 238, 212, 187],
    "operating_cash_flow": [380, 335, 300, 268, 240],
    "capital_expenditure": [80, 75, 70, 66, 60],
    "sbc": [40, 36, 32, 29, 26],
    "depreciation_amortization": [60, 55, 50, 46, 42],
    "interest_expense": [10, 10, 10, 10, 10],
    "pretax_income": [380, 337, 300, 268, 236],
    "income_tax": [80, 71, 62, 56, 49],
    "sga": [300, 270, 240, 215, 190],
    "total_assets": [3000, 2800, 2600, 2450, 2300],
    "total_liabilities": [1200, 1150, 1100, 1060, 1020],
    "stockholders_equity": [1800, 1650, 1500, 1390, 1280],
    "current_assets": [1200, 1100, 1000, 950, 900],
    "current_liabilities": [600, 580, 560, 540, 520],
    "long_term_debt": [400, 420, 440, 460, 480],
    "cash_and_equivalents": [500, 450, 400, 350, 300],
    "accounts_receivable": [200, 180, 160, 145, 130],
    "ppe_net": [900, 850, 800, 760, 720],
    "retained_earnings": [1500, 1300, 1120, 960, 820],
    "shares_diluted": [100, 101, 102, 103, 104],
}

DURATION = {
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "net_income_common",
    "operating_cash_flow",
    "capital_expenditure",
    "sbc",
    "depreciation_amortization",
    "interest_expense",
    "pretax_income",
    "income_tax",
    "sga",
    "shares_diluted",
    "net_charge_offs",
    "premiums_earned",
    "benefits_losses_expenses",
}


def financials(
    table: dict[str, list[float | None]] | None = None,
    *,
    filed: date = date(2026, 2, 10),
    accn: str = "0000000001-26-000001",
    **overrides: list[float | None],
) -> ValueFinancials:
    """A ValueFinancials whose TTM and latest balance sheet equal the newest fiscal year."""
    data: dict[str, list[float | None]] = {k: list(v) for k, v in (table or STEADY).items()}
    data.update(overrides)
    n = max(len(v) for v in data.values())
    annual = []
    for i in range(n):
        items = {k: float(v[i]) for k, v in data.items() if i < len(v) and v[i] is not None}
        annual.append(
            AnnualPeriod(
                period_end=YEAR_ENDS[i] if i < 5 else date(2020 - (i - 5), 12, 31),
                items=items,
                accns={k: accn for k in items},
            )
        )
    newest = annual[0]
    return ValueFinancials(
        entity_name="Steady Co",
        annual=annual,
        ttm={
            k: TtmPoint(value=v, end=newest.period_end, basis="fy")
            for k, v in newest.items.items()
            if k in DURATION
        },
        latest={
            k: InstantPoint(value=v, end=newest.period_end)
            for k, v in newest.items.items()
            if k not in DURATION
        },
        shares_latest=newest.items.get("shares_diluted"),
        cover_shares=newest.items.get("shares_diluted"),
        latest_accn=accn,
        latest_filed=filed,
    )


def price(
    close: float,
    *,
    sma200: float | None = None,
    closes: list[float] | None = None,
    ret_6m: float | None = 0.05,
    spy_ret_6m: float | None = 0.03,
    sessions: int = 400,
) -> PriceSeries:
    """A price series ending at *close*. By default a gentle rise with a dip and recovery
    inside the last 63 sessions (deep-value timing passes) and the close above its 200-day
    average."""
    if closes is None:
        closes = [close * (0.80 + 0.20 * i / 259) for i in range(260)]
        for j in range(200, 230):  # a dip, then a recovery above the 20-day average
            closes[j] *= 0.96
        closes[-1] = close
    sma20s: list[float | None] = [
        None if i < 19 else sum(closes[i - 19 : i + 1]) / 20 for i in range(len(closes))
    ]
    avg200 = sum(closes[-200:]) / 200 if sma200 is None else sma200
    return PriceSeries(
        as_of=AS_OF,
        close=close,
        sessions=sessions,
        closes=closes,
        sma20s=sma20s,
        sma20=sma20s[-1],
        sma50=sum(closes[-50:]) / 50,
        sma200=avg200,
        atr14=close * 0.02,
        rsi14=55.0,
        ret_6m=ret_6m,
        spy_ret_6m=spy_ret_6m,
        beta_250=1.0,
        adv_dollar_20=close * 5_000_000,
    )


def inputs(
    *,
    symbol: str = "STDY",
    fin: ValueFinancials | None = None,
    close: float = 30.0,
    price_series: PriceSeries | None = None,
    industry: str | None = "Application Software",
    is_etf: bool = False,
    yf_market_cap: float | None = None,
    next_earnings: date | None = AS_OF + timedelta(days=60),
    regime: str = "normal",
    rs_cutoff_6m: float | None = -0.10,
) -> ValueInputs:
    fin = fin if fin is not None else financials()
    series = price_series if price_series is not None else price(close)
    shares = fin.cover_shares or fin.shares_latest or 0.0
    return ValueInputs(
        symbol=symbol,
        cik="0000000001",
        as_of=AS_OF,
        financials=fin,
        price=series,
        classification=Classification(
            sector="Information Technology", industry=industry, source="snapshot", is_etf=is_etf
        ),
        yf_market_cap=yf_market_cap if yf_market_cap is not None else shares * series.close,
        next_earnings=next_earnings,
        regime=regime,
        rs_cutoff_6m=rs_cutoff_6m,
    )


# "Harbour Bank": a healthy bank, newest year first (CET1 is not tagged, as at BAC and JPM).
BANK: dict[str, list[float | None]] = {
    "revenue": [100, 96, 92, 88, 85],
    "net_income": [30, 28, 27, 25, 22],
    "net_income_common": [29, 27, 26, 24, 21],
    "total_assets": [3000, 2900, 2800, 2700, 2600],
    "total_liabilities": [2700, 2615, 2530, 2445, 2360],
    "stockholders_equity": [300, 285, 270, 255, 240],
    "goodwill": [60, 60, 60, 60, 60],
    "intangibles": [5, 5, 5, 5, 5],
    "preferred_equity": [20, 20, 20, 20, 20],
    "shares_diluted": [10.0, 10.2, 10.4, 10.6, 10.8],
    "net_charge_offs": [2.0, 1.8, 1.6, 1.4, 1.5],
    "loans": [1000, 950, 900, 850, 800],
    "cash_and_equivalents": [200, 190, 180, 170, 160],
    "long_term_debt": [300, 290, 280, 270, 260],
}
