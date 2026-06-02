"""Pydantic contracts exchanged between modules.

These are the ONLY data shapes that cross module boundaries. Modules never reach
into each other's internals — they pass these objects. SQLAlchemy models in
storage/models.py persist them; everything in-flight uses these.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

_ET = ZoneInfo("America/New_York")


def _utcnow() -> datetime:
    """Timezone-aware UTC now (avoids the deprecated datetime.utcnow)."""
    return datetime.now(UTC)


class Strategy(StrEnum):
    COVERED_CALL = "covered_call"
    CASH_SECURED_PUT = "cash_secured_put"
    ROLL = "roll"


class OptionRight(StrEnum):
    CALL = "C"
    PUT = "P"


class Regime(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"
    HIGH_VOL = "high_volatility"
    LOW_VOL = "low_volatility"


class Verdict(StrEnum):
    PASS = "pass"
    REJECT = "reject"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderState(StrEnum):
    QUEUED = "queued"  # approved, waiting for RTH / re-validation
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# --------------------------------------------------------------------------- #
# Portfolio / account
# --------------------------------------------------------------------------- #
class PositionSnapshot(BaseModel):
    symbol: str
    sec_type: str  # "STK" or "OPT"
    position: float  # signed; negative = short
    avg_cost: float
    market_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    # Option-specific (None for stock):
    right: OptionRight | None = None
    strike: float | None = None
    expiry: date | None = None
    delta: float | None = None
    underlying: str | None = None


class AccountSnapshot(BaseModel):
    account: str
    net_liquidation: float
    total_cash: float
    buying_power: float
    maintenance_margin: float
    excess_liquidity: float
    captured_at: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Market data
# --------------------------------------------------------------------------- #
class OptionQuote(BaseModel):
    """A single option contract's live snapshot."""

    underlying: str
    right: OptionRight
    strike: float
    expiry: date
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    # Greeks / IV — from IBKR model ticks when available, else BS fallback.
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    greeks_source: str = "ibkr"  # "ibkr" | "black_scholes"

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.bid > 0 and self.ask is not None and self.ask > 0:
            return round((self.bid + self.ask) / 2, 4)
        return self.last

    @property
    def spread_pct(self) -> float | None:
        m = self.mid
        if m and self.bid is not None and self.ask is not None and m > 0:
            return round((self.ask - self.bid) / m * 100, 2)
        return None

    @property
    def dte(self) -> int:
        # Use ET (the exchange timezone) so DTE is correct regardless of server timezone.
        # A UTC server at 11 PM would otherwise return tomorrow's date, off by one day.
        return (self.expiry - datetime.now(_ET).date()).days


class IVStats(BaseModel):
    symbol: str
    current_iv: float | None = None
    iv_rank: float | None = None  # 0-100, where current sits in 52w range
    iv_percentile: float | None = None  # 0-100, % of days below current
    hv_30: float | None = None
    term_structure_slope: float | None = None  # near vs far IV
    put_call_skew: float | None = None


class TechnicalStats(BaseModel):
    symbol: str
    price: float
    rsi_14: float | None = None
    atr_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
    trend_strength: float | None = None  # e.g. ADX
    regime: Regime | None = None


class FundamentalStats(BaseModel):
    symbol: str
    next_earnings: date | None = None
    pe_ratio: float | None = None
    free_cash_flow: float | None = None
    debt_to_equity: float | None = None
    dividend_yield: float | None = None
    dividend_safe: bool | None = None
    ex_dividend_date: date | None = None
    quality_flag: bool | None = None  # passes the basic quality screen


# --------------------------------------------------------------------------- #
# Scoring & candidates
# --------------------------------------------------------------------------- #
class ScoreCard(BaseModel):
    """Per-symbol component scores, each normalized 0-100."""

    symbol: str
    iv_score: float = 0.0
    technical_score: float = 0.0
    fundamental_score: float = 0.0
    liquidity_score: float = 0.0
    assignment_safety_score: float = (
        0.0  # 0-100; higher = SAFER (less assignment risk, e.g. lower delta)
    )
    sentiment_score: float | None = None  # 0-100, 50=neutral; None = not fetched


class TradeCandidate(BaseModel):
    """A concrete proposed option sale, fully specified and scored."""

    candidate_id: str  # stable hash of strategy+contract+date
    strategy: Strategy
    underlying: str
    right: OptionRight
    strike: float
    expiry: date
    contracts: int = 1
    # Economics
    premium: float  # credit per share (mid)
    collateral: float  # cash secured (CSP) or shares basis (CC)
    roc_pct: float  # return on capital for the trade
    annualized_yield_pct: float
    breakeven: float
    prob_profit: float | None = None
    delta: float | None = None
    iv_rank: float | None = None
    dte: int
    next_earnings: date | None = (
        None  # earnings date within the option's life → blackout (risk engine)
    )
    # Provenance
    scores: ScoreCard
    blended_score: float = 0.0  # weighted 0-100
    rationale_tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class RiskVerdict(BaseModel):
    candidate_id: str
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)  # why pass/reject


class ClaudeReview(BaseModel):
    """Structured output parsed from `claude -p`. Enrichment only — never gating."""

    candidate_id: str
    priority: int  # 1 = highest
    recommendation: Literal["sell", "wait", "skip"]
    why_attractive: str
    risks: str
    tradeoffs: str
    assignment_considerations: str
    rolling_considerations: str = ""
    confidence: float | None = None  # 0-1


class RollAlert(BaseModel):
    position_symbol: str
    underlying: str
    trigger: str  # "delta_drift" | "iv_spike" | "dte" | "ex_div"
    detail: str
    current_delta: float | None = None
    dte: int | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class RollReview(BaseModel):
    """Claude's structured roll/hold/close decision for a live position."""

    position_symbol: str
    recommendation: str  # "roll" | "hold" | "close"
    roll_target: str  # e.g. "roll to $190 Aug 15 CC at 0.30 delta, $1.85 credit" or ""
    rationale: str
    risks: str
    confidence: float | None = None


class EODSummary(BaseModel):
    """End-of-day metrics passed to Claude + stored in JournalRow.payload."""

    date: date
    realized_pnl: float
    unrealized_pnl: float
    unrealized_pnl_delta: float  # vs yesterday's journal entry
    fills_today: int
    open_positions: int
    net_delta_exposure: float  # sum of delta * position * 100 across all options
    account: AccountSnapshot
    top_movers: list[str] = Field(default_factory=list)  # symbols with largest unrealized change
    tomorrow_watchlist: list[str] = Field(default_factory=list)


class BuyCandidate(BaseModel):
    """A stock recommended for purchase to build a covered-call position."""

    symbol: str
    score: float  # 0-100 blended
    iv_rank: float | None = None  # high IV rank = better future CC premium
    quality_flag: bool | None = None
    technical_regime: str | None = None  # from Regime enum value
    rationale: str = ""  # filled by Claude after scan
