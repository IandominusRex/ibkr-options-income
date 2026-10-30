"""Plain input shapes for the value book's scorecard.

docs/superpowers/specs/2026-10-28-value-swing-book-design.md §6.9. Neutral on purpose: this
module imports only the standard library and pydantic, so the pure modules of ``src/value/``,
the loader (``src/common/value_inputs.py``) and, later, the API share one definition without
any of them importing more of ``src.value`` than the fence allows.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class AnnualPeriod(BaseModel):
    """One fiscal year's line items (canonical names from config/research_concepts.yaml)."""

    period_end: date
    items: dict[str, float] = Field(default_factory=dict)
    accns: dict[str, str] = Field(default_factory=dict)


class TtmPoint(BaseModel):
    value: float
    end: date
    basis: Literal["ytd", "fy"]


class InstantPoint(BaseModel):
    value: float
    end: date


class ValueFinancials(BaseModel):
    """Everything the scorecard reads from filings, as known on one date (``as_of``)."""

    entity_name: str = ""
    has_us_gaap: bool = True
    annual: list[AnnualPeriod] = Field(default_factory=list)  # newest first
    ttm: dict[str, TtmPoint] = Field(default_factory=dict)  # duration items
    latest: dict[str, InstantPoint] = Field(default_factory=dict)  # balance-sheet items
    shares_latest: float | None = None  # newest quarterly weighted diluted count
    cover_shares: float | None = None  # dei cover page (absent for multi-class filers)
    latest_accn: str | None = None
    latest_filed: date | None = None


class PriceSeries(BaseModel):
    """Daily closes and the fixed-window technicals the scorecard reads (spec §6.6)."""

    as_of: date  # the last bar's date
    close: float
    sessions: int  # bars available up to as_of
    closes: list[float]  # ascending, at most the last 260
    sma20s: list[float | None]  # aligned with closes
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    atr14: float | None = None
    rsi14: float | None = None
    ret_6m: float | None = None  # 126-session return
    spy_ret_6m: float | None = None
    beta_250: float | None = None
    adv_dollar_20: float | None = None


class DayBar(BaseModel):
    """One settled session for the exit engine and the shadow record (spec §7, §6.8): the bar
    and the technicals measured at its close. Unknown is None, never zero."""

    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float
    sma20: float | None = None
    sma50: float | None = None
    rsi14: float | None = None
    atr14: float | None = None


class FilingEvent(BaseModel):
    """One filing from EDGAR's submissions feed (spec §7.1 trigger 4): a periodic report or an
    8-K with its item tags. ``going_concern`` is the research worker's read of a periodic filing
    (None: not read, or not a periodic filing)."""

    accn: str
    form: str
    filed: date
    items: list[str] = Field(default_factory=list)
    going_concern: bool | None = None


class NewsVolume(BaseModel):
    """Spec §7.1 trigger 5, handed in as plain data by the value process: one name's news items
    over the last 24 hours and its daily median over the 30 days before them."""

    last_24h: int
    daily_median_30d: float


class Classification(BaseModel):
    sector: str | None = None
    industry: str | None = None
    source: Literal["snapshot", "yfinance", "none"] = "none"
    is_etf: bool = False


class MarketFacts(BaseModel):
    """What the caller fetched from yfinance for one name. Never fetched by src/value."""

    market_cap: float | None = None
    sector: str | None = None
    industry: str | None = None
    quote_type: str | None = None
    next_earnings: date | None = None


class ValueInputs(BaseModel):
    """One name's complete scorecard input. ``src/value/scorecard.py`` is a pure function of
    this plus the config."""

    symbol: str
    cik: str | None = None
    as_of: date
    financials: ValueFinancials | None = None
    price: PriceSeries | None = None
    classification: Classification = Field(default_factory=Classification)
    yf_market_cap: float | None = None
    next_earnings: date | None = None
    regime: str = "unknown"  # MarketRegime value, or "unknown"
    rs_cutoff_6m: float | None = None  # the run's 30th percentile of 6-month excess return
