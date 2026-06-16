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
    def strict_mid(self) -> float | None:
        """Mid from a genuine two-sided market — never falls back to `last` (N10).

        The strategy generators price a candidate's premium/ROC/yield/score off this so they
        can't be computed from a stale prior-session `last` print when the snapshot has no live
        market. Accepts bid=0 with a positive ask (a thin far-OTM market, matching how the order
        builder prices it); requires the ask to be a real positive quote. Returns None otherwise.
        """
        if self.bid is not None and self.bid >= 0 and self.ask is not None and self.ask > 0:
            return round((self.bid + self.ask) / 2, 4)
        return None

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
    current_iv: float | None = None  # annualised implied vol in percent (72.1 = 72.1%)
    iv_rank: float | None = None  # 0-100, where current sits in 52w range
    iv_percentile: float | None = None  # 0-100, % of days below current
    hv_30: float | None = None  # 30-day realised vol in percent (89.8 = 89.8%)
    vrp: float | None = (
        None  # Volatility Risk Premium = current_iv − hv_30, in percentage points (positive → options rich)
    )
    term_structure_slope: float | None = None  # near vs far IV
    put_call_skew: float | None = None


class MarketConditions(BaseModel):
    """Market-level signals fetched once per scan (not per-symbol)."""

    vix: float | None = None
    captured_at: datetime = Field(default_factory=_utcnow)


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
    # ATR-to-price ratio (a normalised *volatility* measure), not a directional trend strength.
    # Named honestly (N16): the old `trend_strength` label implied ADX, which this never was.
    atr_ratio: float | None = None
    regime: Regime | None = None
    # Where `price` came from this scan: "ibkr" (put-call-parity spot inferred from the live
    # option chain) or "yfinance" (fast_info fallback, used when no chain was fetched/inferrable).
    price_source: str = "yfinance"


class FundamentalStats(BaseModel):
    symbol: str
    next_earnings: date | None = None
    pe_ratio: float | None = None
    free_cash_flow: float | None = None
    debt_to_equity: float | None = None
    dividend_yield: float | None = None  # annual yield as a fraction (0.006 = 0.6%)
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
    # P(option expires OTM) ≈ 1 − |delta| — NOT P(profit) (which would credit the premium
    # cushion and the early-close path). Named honestly per N16.
    prob_otm: float | None = None
    delta: float | None = None
    iv_rank: float | None = None
    vrp: float | None = (
        None  # IV% − HV30% at scan time; positive = options overpriced vs realised vol
    )
    dte: int
    next_earnings: date | None = (
        None  # earnings date within the option's life → blackout (risk engine)
    )
    # Provenance
    scores: ScoreCard
    blended_score: float = 0.0  # weighted 0-100
    rationale_tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    # Data-source attribution for the Telegram footer — matches the generating OptionQuote's
    # greeks_source and the TechnicalStats.price_source at scan time.
    price_source: str = "ibkr"  # "ibkr" | "yfinance"
    greeks_source: str = "ibkr"  # "ibkr" | "black_scholes"


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
    # Net OPTION PREMIUM CASHFLOW for the ET day (SELL credits − BUY debits), NOT a paired
    # realized P&L — assignment stock-leg P&L is not captured here. Surfaced to the user as
    # "premium cashflow" (N13). The field name is retained for JournalRow/back-compat.
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
    rationale: str = ""  # deterministic one-liner from the analytics (see buy_candidates.py)

    # --- Analysis context (populated from the per-symbol analytics, all optional) ---
    price: float | None = None  # latest spot used for the screen
    current_iv: float | None = None  # annualised implied vol in percent (72.1 = 72.1%)
    hv_30: float | None = None  # 30-day realised vol in percent (89.8 = 89.8%)
    vrp: float | None = None  # current_iv − hv_30, in percentage points (positive → options rich)
    rsi_14: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    next_earnings: date | None = None
    dividend_yield: float | None = None  # annual yield as a fraction (0.006 = 0.6%)
    est_monthly_cc_yield: float | None = None  # heuristic ~30-delta 30-DTE CC premium / price
    # Sub-score transparency (each 0-100): how the blended score was composed.
    iv_score: float | None = None
    fundamental_score: float | None = None
    technical_score: float | None = None


# --------------------------------------------------------------------------- #
# Enrichment-layer evaluation: outcome ledger + verdict scoring
#
# These shapes power the *learning loop* around Claude's reviews. They are read
# only by analytics/skill-loop code — NEVER by the risk engine, scoring, or
# sizing. Skills derived from this history influence verdict and ranking only;
# the deterministic gates remain human-edited config (see CLAUDE.md "the fence").
# --------------------------------------------------------------------------- #
class VerdictOutcome(StrEnum):
    STILL_OPEN = "still_open"  # filled and live; no terminal outcome yet
    EXPIRED_WORTHLESS = "expired_worthless"  # short option expired OTM → full premium kept
    ASSIGNED = "assigned"  # expired/exercised ITM → stock leg created/removed
    CLOSED_EARLY = "closed_early"  # bought to close before expiry (roll/risk-off)
    NOT_FILLED = "not_filled"  # surfaced + approved path but never executed
    USER_REJECTED = "user_rejected"  # user declined the approval
    RISK_REJECTED = "risk_rejected"  # second-pass risk gate blocked at send time


class BaselineDecision(BaseModel):
    """What the deterministic Rules+Scoring layer would do WITHOUT Claude — the counterfactual.

    A candidate is `sell` if the engine surfaced it as tradeable (passed the risk gate and the
    score floor and was selected into the top-N); otherwise `skip`. `rank` is its 1-based
    position by blended_score among the surfaced slate. Pure Python — no LLM.
    """

    candidate_id: str
    recommendation: Literal["sell", "skip"]
    rank: int | None = None
    score: float = 0.0


class VerdictRecord(BaseModel):
    """One immutable ledger entry: the signals Claude saw, its verdict, the deterministic
    baseline counterfactual, and (back-filled on close) the realized trade outcome.

    Cross-boundary shape for the ledger ↔ reconciler ↔ metrics ↔ skill-loop modules so none
    of them import the SQLAlchemy ORM directly. Enrichment-layer only.
    """

    candidate_id: str
    run_id: str
    scan_date: date
    underlying: str
    strategy: Strategy
    right: OptionRight
    strike: float
    expiry: date
    dte: int
    # The full signal vector Claude saw at decision time (blended_score, iv_rank, delta,
    # vrp, prob_otm, roc_pct, annualized_yield_pct, scorecard components, vix, tags).
    signals: dict = Field(default_factory=dict)
    # Claude's verdict (enrichment output)
    claude_recommendation: str  # "sell" | "wait" | "skip" | "none" (no review returned)
    claude_priority: int | None = None
    claude_confidence: float | None = None
    claude_rationale: str = ""
    # Deterministic baseline counterfactual
    baseline_recommendation: str  # "sell" | "skip"
    baseline_rank: int | None = None
    baseline_score: float = 0.0
    agreement: bool | None = None  # did Claude's sell/not-sell match the baseline's?
    # Realized outcome — back-filled by the reconciler when the position closes
    outcome: VerdictOutcome = VerdictOutcome.STILL_OPEN
    outcome_date: date | None = None
    realized_pnl: float | None = None  # option-leg P&L in account currency (premium − close cost)
    filled: bool = False
    entry_premium: float | None = None  # per-share credit actually received
    contracts: int | None = None


class CalibrationBucket(BaseModel):
    """One confidence band of the reliability curve: how Claude's stated confidence compares
    to the realized win rate of the trades it expressed that confidence on."""

    lower: float  # band lower bound (e.g. 0.6)
    upper: float  # band upper bound (e.g. 0.8)
    n: int
    mean_confidence: float
    win_rate: float  # realized fraction of profitable trades in the band


class PolicyStats(BaseModel):
    """Realized performance of one decision policy over the evaluated trades."""

    label: str  # "follow_claude" | "baseline"
    n_trades: int
    win_rate: float
    mean_pnl: float
    total_pnl: float


class VerdictEvaluation(BaseModel):
    """Held-out scoring of Claude's verdicts: calibration + EV vs the deterministic baseline.

    Computed on *closed* trades only (realized outcomes), optionally restricted to a held-out
    date window so the score reflects out-of-sample skill, not the last trade's luck.
    """

    n_closed: int
    period_start: date | None = None
    period_end: date | None = None
    brier_score: float | None = None  # mean squared (confidence − win); lower is better
    calibration: list[CalibrationBucket] = Field(default_factory=list)
    follow_claude: PolicyStats
    baseline: PolicyStats
    edge_per_trade: float | None = None  # follow_claude.mean_pnl − baseline.mean_pnl
    agreement_rate: float | None = None  # fraction where Claude and baseline agreed
    notes: list[str] = Field(default_factory=list)


class ScoreBucket(BaseModel):
    """Realized performance of the closed trades whose signal value fell in one band.

    Used by the score-vs-outcome report (N22) to check whether a higher `blended_score` — or a
    higher per-component score — actually corresponds to better realized P&L / win rate. If it
    doesn't, the scoring weights are not earning their keep and should be re-derived from this
    evidence (human-edited config, per the fence)."""

    label: str  # e.g. "70-80" or "iv≥50"
    n: int
    win_rate: float
    mean_pnl: float
    total_pnl: float


class SignalCorrelation(BaseModel):
    """How one signal relates to realized P&L over closed trades.

    `pearson_r` is the linear correlation of the signal with realized P&L; the low/high split
    contrasts mean P&L for the bottom vs top half of the signal's range — a coarse, robust
    read that doesn't assume linearity."""

    signal: str
    n: int
    pearson_r: float | None = None
    low_half_mean_pnl: float | None = None
    high_half_mean_pnl: float | None = None


class ScoreOutcomeReport(BaseModel):
    """Score-vs-outcome evidence (N22): does the blended score / its components predict P&L?

    Closed trades only (executed + settled). Read-only analysis that informs whether
    `scoring_weights.yaml` should change — it never feeds the engine."""

    n_closed: int
    period_start: date | None = None
    period_end: date | None = None
    blended_score_buckets: list[ScoreBucket] = Field(default_factory=list)
    component_buckets: list[ScoreBucket] = Field(default_factory=list)
    signal_correlations: list[SignalCorrelation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SkillProposal(BaseModel):
    """A Claude-drafted reasoning skill, awaiting human review before promotion.

    Skills are playbooks injected into the *strategist/roll* prompts only. They shape verdict
    and ranking — never gates, weights, or sizing (those stay human-edited config).
    """

    name: str  # kebab-case slug → filename
    description: str  # one-line; shown in the prompt's skill index
    body: str  # the markdown playbook injected into the reasoning prompt
    rationale: str = ""  # why Claude proposed it (not injected; for the human reviewer)
    supporting_stats: dict = Field(default_factory=dict)  # ledger evidence behind the proposal
