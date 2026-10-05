"""Pydantic contracts exchanged between modules.

These are the ONLY data shapes that cross module boundaries. Modules never reach
into each other's internals — they pass these objects. SQLAlchemy models in
storage/models.py persist them; everything in-flight uses these.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class Phase(StrEnum):
    BASE = "base"
    UPTREND = "uptrend"
    DISTRIBUTION = "distribution"
    DOWNTREND = "downtrend"


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


class AutonomyLevel(StrEnum):
    """How much the system may do without a human tap to OPEN new exposure.

    This ladder governs opening only. Auto-CLOSE (profit-takes and loss-exits) is governed
    entirely by ``automation.auto_close_enabled`` and runs at every rung, including OBSERVE, when
    that switch is on (the default) — closing risk should never wait for a human tap.
    """

    OBSERVE = "observe"  # never opens automatically; a human tap can't act on it either
    MANUAL = "manual"  # human tap required to open
    WHITELIST = "whitelist"  # opens whitelisted symbols automatically
    FULL = "full"  # opens anything that passes the gates


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


class PortfolioSnapshot(BaseModel):
    """One captured portfolio state — positions + account values (P3-P4 M1 Task 1.1).

    The read-side type for `portfolio_snapshots` rows; nothing passes raw ORM rows
    across a module boundary. `source` is which writer produced it: the intraday
    monitor ("monitor"), an operator's `refresh` command ("refresh"), or the EOD
    run ("eod").

    `account` is None only on the API's `eod` fallback rung (read_portfolio), where
    positions come from `position_snapshots` and the account block may be absent
    from the journal payload; every writer supplies it.
    """

    captured_at: datetime
    source: Literal["monitor", "refresh", "eod"]
    account: AccountSnapshot | None = None
    positions: list[PositionSnapshot]


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
    # IBKR's live underlying price from the same option computation (``undPrice``) — the spot
    # the Black-Scholes fallback uses for any sibling quote that lacks a delta. None when IBKR
    # sent no greeks for this contract.
    underlying_price: float | None = None

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
    iv_rv_ratio: float | None = None  # current_iv / realized_vol; ≥1.05 = premium-rich (C1 gate)


class MarketConditions(BaseModel):
    """Market-level signals fetched once per scan (not per-symbol).

    The macro backdrop for a premium seller: how expensive is fear (VIX), is that fear
    front-loaded or termed-out (VIX/VIX3M), what are rates doing (10y level + 5-day change),
    how is the tape trading, and what is the news flow saying. Every field degrades to
    ``None`` independently — no macro source is ever allowed to fail a scan.

    **Enrichment only.** This reaches the Telegram card and the reasoning prompt; it never
    enters scoring, the risk engine, or position sizing.
    """

    vix: float | None = None
    vix3m: float | None = None  # 3-month VIX — the far end of the vol term structure
    # VIX / VIX3M. < 1 = contango (calm, the normal state); > 1 = backwardation, i.e. the
    # market is pricing more risk *now* than in three months — historically a stress signal.
    vix_term_ratio: float | None = None
    ten_year_yield: float | None = None  # US 10-year Treasury yield, percent (^TNX / 10)
    ten_year_change_5d_bp: float | None = None  # 5-session change, basis points
    spy_ret_5d_pct: float | None = None  # broad-tape 5-session % change
    macro_headline_score: float | None = None  # 0-100 VADER read over SPY/QQQ headlines
    macro_headline_count: int = 0
    top_macro_headline: str | None = None
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
    relative_strength: float | None = None
    price_source: str = "yfinance"  # "ibkr" (live) or "yfinance" (fallback)
    phase: Phase | None = None


class SectorContext(BaseModel):
    """Sector/market backdrop for a single-ticker scan — how the name's industry and the broad
    market are trading, so the reasoning layer can place the ticker in context. All fields
    optional: every source (yfinance sector lookup, sector-ETF/SPY returns) degrades gracefully
    to None. Enrichment only — never reaches the deterministic engine."""

    symbol: str
    sector: str | None = None  # yfinance GICS sector (e.g. "Technology")
    industry: str | None = None
    sector_etf: str | None = None  # SPDR proxy for the sector (e.g. "XLK")
    sector_ret_1mo_pct: float | None = None  # sector ETF ~21-session % change
    sector_ret_5d_pct: float | None = None
    spy_ret_1mo_pct: float | None = None  # broad-market benchmark ~21-session % change
    symbol_ret_1mo_pct: float | None = None  # the ticker's own ~21-session % change
    rel_strength_1mo_pct: float | None = None  # symbol_ret_1mo − sector_ret_1mo (relative strength)


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
    # Valuation anchors (yfinance `info`, same dict the fields above are read from — no extra
    # network cost). Used by analytics/fair_value.py to place a share-acquisition level; never
    # a gate. Analyst targets are consensus opinion, not fact — treat as one weak anchor.
    target_mean_price: float | None = None
    target_high_price: float | None = None
    target_low_price: float | None = None
    recommendation_key: str | None = None  # "buy" / "hold" / "underperform" / …
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    # ETF-only fields (M5, Task 5.5). Populated only when yfinance's quoteType == "ETF";
    # None for a stock. Sourced from the same `info` dict the fields above are read from —
    # no extra network cost. NEEDS LIVE VERIFICATION: yfinance's expense-ratio key has
    # varied across library versions and this repo has not yet confirmed which unit a live
    # pull returns for a real ETF (see STATUS.md).
    expense_ratio: float | None = (
        None  # percentage points (0.5 = 0.5%), matching the checks-engine convention
    )
    total_assets: float | None = None  # fund AUM in USD
    avg_volume: float | None = None  # average daily share volume
    inception_date: date | None = None


# --------------------------------------------------------------------------- #
# Scoring & candidates
# --------------------------------------------------------------------------- #
class SentimentDetail(BaseModel):
    """Composite social + news sentiment for one symbol — enrichment only.

    ``overall`` (0-100, 50 = neutral, ``None`` = no data from any source) is the single
    number that feeds scoring via :attr:`ScoreCard.sentiment_score`. The per-source fields,
    counts, 1-day velocity, and headline are surfaced to Claude and the Telegram deep-dive
    card to *explain* the read; they never reach the risk engine or position sizing.
    """

    overall: float | None = None  # 0-100, 50 = neutral; None = no data anywhere
    label: str = "no data"  # Bullish / Lean bullish / Neutral / Lean bearish / Bearish / no data
    delta_1d: float | None = None  # overall vs prior calendar day, in points; + = improving
    stocktwits: float | None = None  # 0-100 from StockTwits self-tags + VADER on untagged
    stocktwits_msgs: int = 0
    news: float | None = None  # 0-100 from VADER over recent headlines
    news_count: int = 0
    reddit: float | None = None  # 0-100 from r/options + r/wallstreetbets (None if creds absent)
    top_headline: str | None = None  # most recent headline, shown in the deep-dive card


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
    relative_strength: float | None = None  # 0-100, 50=neutral; None = not fetched
    sentiment_score: float | None = None  # 0-100, 50=neutral; None = not fetched
    sentiment_detail: SentimentDetail | None = None


class IdealZone(BaseModel):
    """Where a short option *ought* to be written, and for how much.

    Computed deterministically by :mod:`src.analytics.fair_value` from technicals
    (support/resistance, SMAs), IV (expected move) and fundamentals (earnings, ex-div,
    quality, analyst targets). It answers three questions the raw chain does not:

      * **strike_lo/hi/anchor** — the strike band worth writing, not merely the band the
        delta filter admits.
      * **min_credit** — the least credit worth accepting for the contract actually on
        offer: Black-Scholes fair value at *realised* vol plus a required edge, floored by
        the configured ROC/yield gates. Selling below it is selling variance for free.
      * **action_price / buy_below** — the underlying level that makes the write attractive,
        and the level at which acquiring shares is sensible.

    Every field is optional: each input degrades independently and ``confidence`` reports how
    much of the derivation actually had data.

    **Two kinds of field — do not assume the whole zone is inert.** The strike band and the
    action levels are display + optional ranking only (they reach scoring solely through
    ``scoring_weights.yaml``'s ``zone_fit``, which ships at ``0.0``). ``min_credit`` is
    different: since D2 it is a real gate — ``risk_engine.validate_candidates`` rejects an
    **income** candidate (CC/CSP) whose ``premium`` falls below it under
    ``income.require_vrp_edge`` (ships ``true``), reason ``premium_below_fair_value``. On a
    ``Strategy.ROLL`` it is display/audit only: a defensive roll pays under fair value by
    design, so rolls are scoped out of that gate and bounded by ``monitor.roll_defensive``
    (``max_debit`` / ``min_delta_reduction``) instead. A ``None`` zone never blocks.
    ``fair_value.py`` still has no reject path of its own, so the deterministic Rules Engine
    remains the sole path to an order.
    """

    symbol: str
    right: OptionRight
    dte: int
    spot: float
    expected_move: float | None = None  # spot · IV · √(dte/365), in dollars (1σ)
    # Strike zone
    strike_lo: float | None = None
    strike_hi: float | None = None
    strike_anchor: float | None = None  # the single preferred strike within the band
    strike_anchors: list[str] = Field(default_factory=list)  # human-readable drivers
    # Credit floor for the contract on offer
    min_credit: float | None = None  # per share
    credit_anchors: list[str] = Field(default_factory=list)
    # Underlying levels
    action_price: float | None = None  # spot at which strike_anchor sits ~1σ OTM
    action_note: str | None = None
    buy_below: float | None = None  # share-acquisition level
    buy_anchors: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


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
    # IV level (percent, e.g. 28.5) at scan time — distinct from iv_rank, which is a
    # percentile. Required by engine/capital.risk_units to size concentration in risk
    # units rather than raw collateral.
    current_iv: float | None = None
    vrp: float | None = (
        None  # IV% − HV30% at scan time; positive = options overpriced vs realised vol
    )
    iv_rv_ratio: float | None = None  # current_iv / realized_vol; ≥1.05 = premium-rich (C1)
    dte: int
    next_earnings: date | None = (
        None  # earnings date within the option's life → blackout (risk engine)
    )
    # Where this contract *should* sit vs where it does. The band and action levels are
    # enrichment for the card and the reasoning layer, plus an optional (default-off)
    # `zone_fit` ranking term — but `ideal.min_credit` is read by risk_engine's
    # variance-risk-premium gate (`income.require_vrp_edge`), so this field can reject a
    # candidate. Leaving it None is safe: a missing zone never blocks.
    ideal: IdealZone | None = None
    # Provenance
    scores: ScoreCard
    blended_score: float = 0.0  # weighted 0-100
    rationale_tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    # Data-source attribution for the Telegram footer — matches the generating OptionQuote's
    # greeks_source and the TechnicalStats.price_source at scan time.
    price_source: str = "ibkr"  # "ibkr" | "yfinance"
    greeks_source: str = "ibkr"  # "ibkr" | "black_scholes"
    # Quote microstructure behind the liquidity verdict (Task 7) — carried onto the candidate
    # so a granular reject (illiquid_oi_low, illiquid_spread_wide, ...) is auditable after the
    # fact without re-fetching the chain. None on a candidate never re-runs a liquidity gate.
    quote_bid: float | None = None
    quote_ask: float | None = None
    open_interest: int | None = None
    option_volume: int | None = None


class RiskVerdict(BaseModel):
    candidate_id: str
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)  # why pass/reject


class AssessmentStage(StrEnum):
    """How far a contract got before it was set aside.

    Ordered from earliest to latest. Anything other than ``PASSED`` means the contract was
    assessed and not surfaced for approval — the reason codes say why.
    """

    GENERATOR = "generator"  # failed a strategy filter (delta band, DTE, liquidity, ROC/yield)
    RISK_GATE = "risk_gate"  # failed the deterministic Rules Engine
    SCORE_FLOOR = "score_floor"  # cleared the gate but scored below min_candidate_score
    DEDUPE = "dedupe"  # a better strike for the same (underlying, strategy) won
    TOP_N = "top_n"  # good enough, but max_new_positions_per_run was already full
    PASSED = "passed"  # surfaced for approval


class AssessedContract(BaseModel):
    """One contract the scan looked at, and what became of it.

    Every contract the strategy generators price ends up here — approved or not — so a scan
    can always answer "what did you see, and why didn't you take it?" instead of going
    silent. Rejections used to exist only as an aggregate log counter (generator stage) or an
    in-memory verdict discarded at the end of the run (gate stage).
    """

    candidate: TradeCandidate
    stage: AssessmentStage
    reasons: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.stage == AssessmentStage.PASSED


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
    # Plain-English synthesis: a short 2-3 sentence version on the full-universe path, the longer
    # SUMMARY GUIDE variant on the single-ticker /scan deep-dive. Requested for every candidate
    # since Task 10 (previously empty on the full-universe path).
    summary: str = ""
    # F#/N# fact/news ids (from the prompt's FACTS block and, once a news layer exists, NEWS
    # items) the model cited to support its recommendation — the DECISION RUBRIC asks for these
    # explicitly so a verdict is traceable to a concrete, deterministic fact rather than an
    # unstated impression. Empty is valid (older prompts / a model that ignores the rubric) but
    # `scripts/review_eval.py` flags a high empty rate as a quality signal.
    evidence: list[str] = Field(default_factory=list)


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

    @field_validator("roll_target", "rationale", "risks")
    @classmethod
    def _blank_echoed_placeholder(cls, v: str) -> str:
        # The local reviewer sometimes copies the prompt's JSON template verbatim
        # ("<2-3 sentences on key risks>"); a card must not present that as analysis.
        stripped = v.strip()
        return "" if stripped.startswith("<") and stripped.endswith(">") else v


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
    top_movers: list[str] = Field(default_factory=list)  # underlyings with largest unrealized swing
    # underlying → aggregated unrealized P&L, for the top_movers shown as "Drivers" in the report.
    mover_pnl: dict[str, float] = Field(default_factory=dict)
    tomorrow_watchlist: list[str] = Field(default_factory=list)
    # False when tomorrow's watchlist is identical to yesterday's — lets the report collapse the
    # (usually static) 30+ ticker list to a count instead of reprinting it every day.
    watchlist_changed: bool = True


class BuyCandidate(BaseModel):
    """A stock recommended for purchase to build a covered-call position."""

    symbol: str
    score: float  # 0-100 blended
    sector: str | None = None  # from universe.yaml sectors map
    iv_rank: float | None = None  # high IV rank = better future CC premium
    quality_flag: bool | None = None
    technical_regime: Regime | str | None = None  # from Regime enum value (legacy string allowed)

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


# --------------------------------------------------------------------------- #
# P&L engine schemas (P3-P4 M4 Task 4.2) — the read-side types src/reporting/pnl.py
# builds. Same package as VerdictOutcome because PnlLeg.outcome IS a VerdictOutcome:
# the reporting layer and the outcome ledger agree by construction.
# --------------------------------------------------------------------------- #


class PnlLeg(BaseModel):
    """One option contract position, from the fill that opened it to whatever closed it.

    `net_pnl` is None while the leg is open — never 0.0. An open leg has an unrealised
    mark, not a realised result, and a zero in a realised column is a claim.
    """

    candidate_id: str
    campaign_id: str | None = None
    symbol: str
    underlying: str
    strategy: Strategy
    right: OptionRight
    strike: float
    expiry: date
    contracts: int
    opened_at: datetime
    closed_at: datetime | None = None
    credit: float
    debit: float
    commissions: float
    commissions_complete: bool
    net_pnl: float | None = None
    unrealized_pnl: float | None = None
    days_held: int
    roc_pct: float | None = None
    annualized_pct: float | None = None
    outcome: VerdictOutcome
    is_live: bool


class CampaignPnl(BaseModel):
    """A wheel cycle: every option leg on a symbol, plus the stock leg."""

    campaign_id: str
    symbol: str
    status: Literal["open", "closed"]
    opened_date: date
    closed_date: date | None = None
    legs: list[PnlLeg] = Field(default_factory=list)
    option_realized: float = 0.0
    option_unrealized: float | None = None
    stock_realized: float | None = None
    stock_unrealized: float | None = None
    assigned: bool = False
    adjusted_cost_basis: float | None = None
    total_net: float = 0.0


class PnlBucket(BaseModel):
    """Realised performance grouped by one key (a symbol, a strategy)."""

    label: str
    n_closed: int
    realized: float
    win_rate: float | None = None  # None when n_closed is 0, never 0.0
    mean_days_held: float | None = None
    mean_roc_pct: float | None = None


class PnlSummary(BaseModel):
    realized_total: float
    unrealized_total: float | None = None
    commissions_complete: bool
    n_open: int
    n_closed: int
    win_rate: float | None = None
    by_strategy: list[PnlBucket] = Field(default_factory=list)
    by_symbol: list[PnlBucket] = Field(default_factory=list)
    best: PnlLeg | None = None
    worst: PnlLeg | None = None


class EquityPoint(BaseModel):
    entry_date: date
    net_liquidation: float | None = None
    unrealized_pnl: float | None = None
    cumulative_realized: float
    premium_cashflow: float | None = None  # journal.realized_pnl — NOT paired realised P&L


class EquityCurve(BaseModel):
    """Points, and the days between the first and last point that have no point.

    `gaps` exists so the chart can render a gap rather than a straight line across a week
    nobody measured.
    """

    points: list[EquityPoint] = Field(default_factory=list)
    gaps: list[date] = Field(default_factory=list)
    starts_at: date | None = None


# --------------------------------------------------------------------------- #
# Trade ledger — whole-account broker truth
# (docs/superpowers/specs/2026-10-04-trade-ledger-design.md). Read by src/ledger/,
# src/reporting/trade_ledger.py and src/api/ only — never by engine/execution/strategies.
# --------------------------------------------------------------------------- #
LedgerSourceKind = Literal["exec", "order"]
LedgerSource = Literal["csv", "flex", "live"]
LedgerOutcome = Literal[
    "Open",
    "Pending",
    "Expired",
    "Assigned",
    "Called away",
    "Exercised",
    "Bought back",
    "Sold",
    "Rolled",
]


class LedgerContract(BaseModel):
    """A normalized IBKR contract identity, independent of which feed reported it."""

    model_config = ConfigDict(frozen=True)

    underlying: str
    sec_type: Literal["OPT", "STK"]
    currency: str = "USD"
    right: Literal["P", "C"] | None = None
    strike: float | None = None
    expiry: date | None = None
    multiplier: float = 1.0

    @property
    def ident(self) -> str:
        if self.sec_type == "STK":
            return f"STK:{self.underlying}:{self.currency}"
        assert self.expiry is not None and self.strike is not None and self.right is not None
        return (
            f"OPT:{self.underlying}:{self.expiry:%Y%m%d}:{self.right}:"
            f"{self.strike:g}:{self.currency}"
        )


class ParsedExecution(BaseModel):
    """One execution (``exec_id`` set) or one order-level statement row (``exec_id`` None)."""

    contract: LedgerContract
    trade_time: datetime  # timezone-aware UTC
    quantity: float  # signed: + bought, - sold (contracts or shares)
    price: float  # per share
    proceeds: float  # signed cash, contract currency
    commission: float = 0.0  # signed; negative is a cost
    codes: str = ""  # raw IBKR code string, e.g. "A;O", "C;Ep"
    exec_id: str | None = None
    perm_id: int | None = None
    ib_order_id: int | None = None
    account: str | None = None
    ibkr_realized_pnl: float | None = None
    source_kind: LedgerSourceKind
    occurrence_idx: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class ParsedCashEvent(BaseModel):
    event_type: Literal["dividend", "withholding", "deposit", "withdrawal", "fee", "interest"]
    event_date: date
    currency: str
    amount: float  # signed
    description: str
    underlying: str | None = None
    occurrence_idx: int = 0


class ParsedCorporateAction(BaseModel):
    event_date: date
    underlying: str | None
    description: str
    quantity: float
    proceeds: float
    occurrence_idx: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class ParsedFxRate(BaseModel):
    rate_date: date
    currency: str
    usd_rate: float  # USD per 1 unit of `currency`


class LedgerParseError(BaseModel):
    line: int
    section: str
    message: str


class ParsedStatement(BaseModel):
    """What every feed (Activity CSV, Flex XML, live fills) normalises to before ingest."""

    account: str | None = None
    base_currency: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    executions: list[ParsedExecution] = Field(default_factory=list)
    cash_events: list[ParsedCashEvent] = Field(default_factory=list)
    corporate_actions: list[ParsedCorporateAction] = Field(default_factory=list)
    fx_rates: list[ParsedFxRate] = Field(default_factory=list)
    errors: list[LedgerParseError] = Field(default_factory=list)

    @property
    def fatal(self) -> bool:
        """A broken Trades row poisons the whole import; other sections only warn."""
        return any(e.section == "Trades" for e in self.errors)


class LedgerImportResult(BaseModel):
    run_id: int | None
    status: Literal["ok", "failed", "skipped"]
    reason: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[LedgerParseError] = Field(default_factory=list)


class LedgerClose(BaseModel):
    """One closing order's share of a trade (a trade may close in several orders)."""

    order_key: str
    close_date: date
    close_time: datetime
    quantity: float  # contracts closed by this order, positive
    cash: float  # signed proceeds attributable to this close
    commission: float  # signed
    codes: str


class LedgerTrade(BaseModel):
    """One opening option order and everything that closed it (spec §4.2, R3, R4, R9, R10)."""

    order_key: str
    underlying: str
    currency: str
    side: Literal["Sell", "Buy"]
    right: Literal["P", "C"]
    strike: float
    expiry: date
    multiplier: float
    lots: float
    order_date: date
    open_time: datetime
    close_date: date | None
    dte: int
    days_held: int
    premium: float  # gross opening credit (+) / debit (-), contract currency
    open_commission: float
    closes: list[LedgerClose] = Field(default_factory=list)
    outcome: LedgerOutcome
    computed_outcome: LedgerOutcome
    outcome_overridden: bool = False
    mixed_close: bool = False
    capital: float
    pct_profit: float | None  # the sheet's formula, in %; short options only
    net_pnl: float | None  # fully closed only, after all commissions
    return_pct: float | None
    annualised_net_pct: float | None
    stock_gain: float | None = None  # realized stock P&L when this call got the shares called away
    book: Literal["system", "manual"]
    rolled_from: str | None = None
    rolled_to: str | None = None
    ibkr_realized_pnl: float | None = None
    exec_row_ids: list[int] = Field(default_factory=list)
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    exclude_from_stats: bool = False


class LedgerOrphan(BaseModel):
    """A closing order with no opening in the imported history (Review Focus 1)."""

    order_key: str
    underlying: str
    sec_type: Literal["OPT", "STK"]
    contract_ident: str
    currency: str
    trade_date: date
    quantity: float
    price: float
    ibkr_realized_pnl: float | None
