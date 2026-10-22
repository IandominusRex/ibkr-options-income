"""Pydantic contracts exchanged between modules.

These are the ONLY data shapes that cross module boundaries. Modules never reach
into each other's internals — they pass these objects. SQLAlchemy models in
storage/models.py persist them; everything in-flight uses these.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import date as _date  # for fields declared after a field named `date`
from enum import StrEnum
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class MarketRegime(StrEnum):
    """The market-wide state the sizing limits follow (not a per-ticker label: see `Regime`).

    Ordered calm to severe: normal, cautious, stressed, crisis. Classified deterministically
    by `src/analytics/regime.py`; turned into limits by `src/engine/regime_limits.py`.
    """

    NORMAL = "normal"
    CAUTIOUS = "cautious"
    STRESSED = "stressed"
    CRISIS = "crisis"


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
    # IBKR contract id (2026-10-11): identifies the exact contract a roll buys back, so two
    # shorts on one underlying and right (GOOGL 330P + 335P) can never be confused.
    con_id: int | None = None


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


class RegimeInputs(BaseModel):
    """Everything one index's regime was classified from (deterministic; see analytics/regime.py).

    ``vol`` is the VIX close for **both** indices (ruling 15), so the VIX thresholds mean the
    same thing for SPY and QQQ. A field that could not be read, or that is a last close served
    as live, is ``None`` and named in ``stale``: it is skipped by the classifier and never read
    as calm.
    """

    vol: float | None = None
    vol_pct_1y: float | None = None  # 0-100
    term_ratio: float | None = None  # VIX / VIX3M; above 1 is backwardation
    contango_streak: int = 0  # consecutive daily closes with term_ratio < 1, most recent first
    index_close: float | None = None
    index_live: float | None = None
    day_change_pct: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    drawdown_52w_pct: float | None = None  # a positive number
    ret_1m_pct: float | None = None
    ret_3m_pct: float | None = None
    rv20: float | None = None
    rv_1y_avg: float | None = None
    live_vol: float | None = None
    stale: list[str] = Field(default_factory=list)


class IndexRegime(BaseModel):
    """One index's persisted regime: the daily base, today's intraday escalation, the result."""

    index: Literal["SPY", "QQQ"]
    base: MarketRegime
    base_date: date  # the ET day the base was last computed
    since: date  # the ET day the *effective* regime last changed
    base_since: date  # the ET day the *base* last changed: the hysteresis clock (ruling 40)
    effective: MarketRegime
    escalated_by: list[str] = Field(default_factory=list)
    eased_by_bottoming: bool = False
    bottoming_cancelled_on: date | None = None
    inputs: RegimeInputs = Field(default_factory=RegimeInputs)


class RegimeChange(BaseModel):
    """An effective-regime change, queued for a Telegram notice until ``sent``."""

    index: Literal["SPY", "QQQ"]
    before: MarketRegime
    after: MarketRegime
    why: list[str] = Field(default_factory=list)
    at: datetime
    sent: bool = False


class RegimeState(BaseModel):
    """The persisted market regime for both indices (written only by the trading process)."""

    as_of: datetime
    spy: IndexRegime
    qqq: IndexRegime
    changes: list[RegimeChange] = Field(default_factory=list)


class PictureFact(BaseModel):
    """One deterministic line of the market picture: a label and a value Python computed."""

    label: str
    value: str


class SeasonalityView(BaseModel):
    """SPY's calendar-month tendency over the years the price provider covers (a weak signal)."""

    month: int
    avg_return_pct: float
    up_share: float  # 0-1: the share of those years the month closed up
    years: int


class PictureStory(BaseModel):
    """A multi-week story the picture is tracking. Identity (id, title, start date) is kept by
    Python; the description is the model's one-sentence tie to the numbered facts."""

    id: int
    title: str
    started_on: date
    description: str = ""
    evidence: list[str] = Field(default_factory=list)


class NoiseSummary(BaseModel):
    """What the triage kept out of the picture in the last 7 days (shown, never overruled)."""

    judged: int = 0  # Claude saw it and called it noise
    not_reviewed: int = 0  # outside the ranked batch: nobody judged it
    promotions: int = 0  # judged noise that the market reaction check promoted late


class PictureRegime(BaseModel):
    """One index's regime as the picture shows it (read from the trading process's record)."""

    index: Literal["SPY", "QQQ"]
    effective: MarketRegime
    base: MarketRegime
    eased_by_bottoming: bool = False
    suspended: bool = False
    as_of: datetime


class MarketPicture(BaseModel):
    """The shared, persistent picture of the market every ``claude -p`` call reads.

    Written only by the news process (``src/news/picture.py``); every number in it is computed by
    Python, the story descriptions are the model's prose and are grounded before they are saved.
    Enrichment: it reaches prompts and cards, never the engine, execution or sizing.
    """

    version: str  # the build time, ISO: a reader compares versions to know a picture is new
    built_at: datetime
    regimes: list[PictureRegime] = Field(default_factory=list)
    regime_source: Literal["trading", "news"] = "trading"
    facts: list[PictureFact] = Field(default_factory=list)
    seasonality: SeasonalityView | None = None
    events: list[str] = Field(default_factory=list)
    stories: list[PictureStory] = Field(default_factory=list)
    noise: NoiseSummary = Field(default_factory=NoiseSummary)
    stale: bool = False  # True when the model call failed and only the deterministic part is fresh


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
    # Next cash dividend $/share (yfinance lastDividendValue, else dividendRate/4). Feeds the
    # roll ex-dividend test: a short call is at risk when its extrinsic is below this.
    dividend_per_share: float | None = None
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
    design, so rolls are scoped out of that gate and bounded by the ``roll:`` config block
    (``min_net_credit`` / ``cc.max_debit``) instead. A ``None`` zone never blocks.
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


class RollOrigin(BaseModel):
    """The short a ROLL candidate buys back, and where it sits in its roll chain (2026-10-11).

    Stored inside the frozen candidate snapshot, so the executor closes exactly this contract
    and the Rules Engine can enforce the chain's roll and extension limits.
    """

    con_id: int | None = None  # IBKR conId of the short being closed
    candidate_id: str | None = None  # the system candidate that sold it (None: opened outside)
    strike: float
    expiry: date
    right: OptionRight
    contracts: int
    chain_id: str  # the chain's root candidate id (or a synthetic id)
    seq: int  # this roll's number in the chain: 1 = first roll
    original_expiry: date  # expiry of the chain's first leg — the extension cap's anchor
    old_mid: float  # $/sh to buy back the old leg when proposed
    new_mid: float  # $/sh the new leg sold for when proposed
    allow_debit: bool = False  # a keep-shares covered-call roll may pay up to roll.cc.max_debit


class ScaleInZone(BaseModel):
    """Where the next CSP lot on a name may be added while it is under the scale-in ladder.

    Defined with the sizing schemas so `SizingContext` and `SizingNote` need no forward
    reference; the ladder (a later task) fills it. A strike whose spot is above ``zone_high``
    is refused with ``scale_in_zone_not_reached``.
    """

    anchor: float
    anchor_source: Literal["order_snapshot", "price_history", "shares", "position"]
    zone_low: float
    zone_high: float
    support: float | None = None
    min_gap_pct: float
    triggers: list[str] = Field(default_factory=list)
    bottoming_signal: bool = False


class SizingNote(BaseModel):
    """How the market regime and the leveraged-ETF ceiling shaped one CSP's size (card + audit).

    Carried on the candidate (and so in the frozen order snapshot), never read back by the
    sizer or the gate as an input except `scale_in`/`floor_lot`, which the send-time re-gate
    re-checks from the snapshot.
    """

    pre_regime_contracts: int  # what capital alone would have allowed (capped at the hard max)
    regime: MarketRegime
    regime_index: Literal["SPY", "QQQ"]  # the index whose regime governs this name
    per_trade_cap: int
    budget_multiplier: float
    leverage: int | None = None
    leverage_tier: Literal["calm", "stressed"] | None = None
    ceiling_kind: Literal["regime_ceiling", "leveraged_ceiling"] | None = None
    floor_lot: bool = False  # sent under the guaranteed floor (past the scaled budget)
    scale_in: ScaleInZone | None = None
    bottoming: Literal["market", "name"] | None = None
    claude_suggested: int | None = None
    claude_reason: str | None = None


class CcBreakout(BaseModel):
    """An upside breakout on a held name that governs its covered-call strikes for a few sessions.

    Worked out by `src/analytics/breakout.py` from daily bars; the covered-call generator and the
    Rules Engine hold a call on the name to ``floor_strike`` and ``delta_max`` while it lasts
    (`engine/regime_limits.cc_timing_reasons`). It only pushes a strike out: it never skips a
    name, loosens a limit or sizes anything. ``broke_level`` is None when the close was a
    ``high_sessions`` high with no resistance to clear.
    """

    trigger_day: date
    trigger_close: float
    jump_pct: float  # the close-to-close rise on the trigger day, in percent
    volume_ratio: float  # the trigger day's volume over its 20-session average
    broke_level: float | None = None
    floor_strike: float
    delta_max: float
    sessions_left: int


class SizingContext(BaseModel):
    """Everything the sizer and the gate need to apply the regime, built once per scan / send.

    ``None`` (where a function takes ``SizingContext | None``) means no regime behaviour at all.
    Deterministic: the regimes come from the persisted `RegimeState`, the counts from today's
    orders. Keys of the per-index dicts are ``"SPY"`` / ``"QQQ"``: a tech-linked name is
    counted under QQQ, every other name under SPY (ruling 16).
    """

    regimes: dict[str, MarketRegime]  # effective regime per index
    tech_linked: list[str] = Field(default_factory=list)
    suspended: bool = False  # `/regime off` today
    csp_opens_counted: dict[str, int] = Field(default_factory=dict)  # per governing index
    floor_lots_counted: dict[str, int] = Field(default_factory=dict)  # guaranteed-floor lots today
    leverage: dict[str, int] = Field(default_factory=dict)  # leveraged ETF -> factor (2 or 3)
    name_triggers: dict[str, list[str]] = Field(default_factory=dict)  # ladder triggers per name
    for_send: bool = False  # built at send time (queued orders are the batch, not counted)
    scale_in: dict[str, ScaleInZone] = Field(default_factory=dict)
    loss_exit_today: list[str] = Field(default_factory=list)
    spot_at_send: dict[str, float] = Field(default_factory=dict)
    name_bottoming: list[str] = Field(default_factory=list)
    market_bottoming: dict[str, bool] = Field(default_factory=dict)
    signal_lot_recent: list[str] = Field(default_factory=list)
    # Held names in a covered-call breakout (scan time only; the send-time gate reads the
    # candidate's own frozen copy). Not a regime limit: `/regime off` leaves it on.
    cc_breakout: dict[str, CcBreakout] = Field(default_factory=dict)


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
    # ROLL only (2026-10-11): the short this roll closes and its chain position. None on
    # CC/CSP candidates and on roll snapshots frozen before the redesign.
    roll_from: RollOrigin | None = None
    # CSP only: how the market regime / leveraged-ETF ceiling shaped the size (None on rolls,
    # covered calls, and on candidates built without a SizingContext).
    sizing: SizingNote | None = None
    # Covered call only: the breakout in force on the name when the call was priced (the card
    # shows it and the send-time gate re-checks the strike floor and delta cap from it).
    cc_breakout: CcBreakout | None = None


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
    """Structured output parsed from `claude -p`. Enrichment only — never gating, except the
    reduce-only ``max_contracts`` cut (spec section 9; ``engine.regime_limits.claude_cut``)."""

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
    # Claude's optional size cut for an auto-opened CSP (spec section 9): the most contracts it
    # would sell. It only ever reaches the engine package through the one clamped function
    # `engine.regime_limits.claude_cut`, which can lower the deterministic size and never raise it.
    # Anything that is not a plain integer (a bool, a float, text) reads as None here, so a
    # malformed value can never cost the review its other fields.
    max_contracts: int | None = None
    size_reason: str = ""
    # Which backend produced this review. Never taken from the model's output: the parser blanks
    # it and the runner stamps it, so a reused or Ollama-made review is recognisable later.
    backend: Literal["cli", "ollama"] | None = None

    @field_validator("max_contracts", mode="before")
    @classmethod
    def _only_a_real_integer(cls, v: Any) -> int | None:
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    @field_validator("size_reason", mode="before")
    @classmethod
    def _reason_is_short_text(cls, v: Any) -> str:
        return v[:300] if isinstance(v, str) else ""


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


class EODTrade(BaseModel):
    """One thing that happened to a position today, for the EOD report (2026-10-14 rebuild)."""

    action: Literal["opened", "closed", "rolled", "assigned", "expired"]
    label: str  # "SOXL 130P 16 Oct"
    underlying: str
    contracts: int
    price: float | None = None  # per share: the credit for an open, the debit for a close
    pnl: float | None = None  # net realised $ for a close / expiry; None for an open
    reason: str | None = None  # "loss exit", "profit take", "roll", …


class EODDecision(BaseModel):
    """A deterministic roll-policy decision sent today (``roll_alerts`` trigger roll_decision)."""

    label: str
    action: str  # RollAction value
    reason: str
    detail: str | None = None


class EODWatch(BaseModel):
    """A fact the operator should know before the next session opens."""

    kind: Literal["macro", "breach", "expiring", "earnings"]
    text: str


class EODSummary(BaseModel):
    """End-of-day metrics passed to Claude + stored in JournalRow.payload."""

    date: date
    # Net OPTION PREMIUM CASHFLOW for the ET day (SELL credits − BUY debits), NOT a paired
    # realized P&L — assignment stock-leg P&L is not captured here. Surfaced to the user as
    # "premium cashflow" (N13). The field name is retained for JournalRow/back-compat.
    realized_pnl: float
    unrealized_pnl: float
    # vs the previous session's close (``baseline_date``); 0.0 with baseline_date None when no
    # prior close is on record. Before 2026-10-14 this read the *calendar* day before, so every
    # Monday and every day after a missed EOD showed the whole unrealised figure as the change.
    unrealized_pnl_delta: float
    fills_today: int
    open_positions: int
    net_delta_exposure: float  # sum of delta * position * 100 across all options
    account: AccountSnapshot
    top_movers: list[str] = Field(default_factory=list)  # underlyings with the largest swing today
    # underlying → change in unrealised P&L since baseline_date (since 2026-10-14; before that it
    # was the lifetime unrealised figure, which is not what "today's drivers" means).
    mover_pnl: dict[str, float] = Field(default_factory=dict)
    tomorrow_watchlist: list[str] = Field(default_factory=list)
    # False when tomorrow's watchlist is identical to yesterday's — lets the report collapse the
    # (usually static) 30+ ticker list to a count instead of reprinting it every day.
    watchlist_changed: bool = True
    # 2026-10-14 rebuild: the report is built from these facts rather than from totals.
    baseline_date: _date | None = None  # the session the deltas are measured from
    nlv_change: float | None = None  # NLV now − NLV at baseline_date's close
    next_session: _date | None = None
    trades: list[EODTrade] = Field(default_factory=list)
    decisions: list[EODDecision] = Field(default_factory=list)
    watch: list[EODWatch] = Field(default_factory=list)


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


class CloseReason(StrEnum):
    """Why a short option was bought back — stamped on the closing order and its BUY fill.

    `VerdictOutcome.CLOSED_EARLY` says only *that* a leg closed before expiry; this says why,
    so profit-takes can be analysed apart from loss exits, rolls and hand-placed closes.
    """

    PROFIT_TAKE = "profit_take"  # check_profit_takes hit the (DTE-keyed) threshold
    LOSS_EXIT = "loss_exit"  # check_loss_exits hit max_loss_multiple (leveraged ETFs)
    ROLL = "roll"  # the buy-back leg of an executed roll
    MANUAL = "manual"  # closed outside the system; recorded by external-close reconciliation
    DEFENSIVE = "defensive"  # operator tapped Close on a roll-policy `close` decision


RollAction = Literal["roll", "assign", "let_called_away", "close", "hold", "defer"]


class RollDecision(BaseModel):
    """What the deterministic roll policy decided for one breached short (2026-10-11).

    ``reason`` is a stable code (``credit_roll``, ``not_would_own``, ``net_below_floor``…);
    ``rejections`` counts every construction rejection by code, so a decision that proposes
    nothing still says why. ``candidate`` is set only for ``roll``.
    """

    action: RollAction
    reason: str
    candidate: TradeCandidate | None = None
    rejections: dict[str, int] = Field(default_factory=dict)
    detail: str = ""


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
    # The SELL-side (opening) share of `commissions`, so a month's pay can charge each side in
    # the month it was paid; the rest belongs to the close. None when the split is not known.
    open_commissions: float | None = None
    net_pnl: float | None = None
    unrealized_pnl: float | None = None
    days_held: int
    roc_pct: float | None = None
    annualized_pct: float | None = None
    outcome: VerdictOutcome
    # Why a CLOSED_EARLY leg was bought back (the latest BUY fill's reason). None for legs that
    # did not close early, and for closes recorded before the reason was stamped (2026-10-11).
    close_reason: CloseReason | None = None
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


AccountValueRange = Literal["1d", "1w", "1m", "3m", "ytd", "all"]


class AccountValuePoint(BaseModel):
    at: datetime
    value: float


class AccountValueSeries(BaseModel):
    """Account value (net liquidation) over a range, for the Home hero chart.

    1d/1w plot the intraday portfolio snapshots inside the window (retention:
    `storage.portfolio_snapshot_retention_days`); 1m/3m/ytd/all plot one point per EOD journal
    close, at that day's 16:00 ET. `latest` is the newer of the newest known snapshot and the
    newest close, compared as instants (a journal day is a close only once its 16:00 ET has
    passed), so it can be a close. 1m/3m/ytd/all end on `latest` when it is newer than their
    last close; 1d/1w end on it only when `latest_at` falls inside the window. Points ascend in
    time but not strictly: snapshot rows sharing a `captured_at` both appear.
    `previous_close` is the close before the New York day `latest` belongs to; `change_today`
    is None unless that day is today (weekends, before the day's first snapshot). A net
    liquidation of 0 or less is unknown. Every figure is None when unknown - never 0.0.
    """

    range: AccountValueRange
    points: list[AccountValuePoint] = Field(default_factory=list)
    latest: float | None = None
    latest_at: datetime | None = None
    previous_close: float | None = None
    change_today: float | None = None
    change_today_pct: float | None = None


IncomeTargetMode = Literal["off", "fixed", "pct_of_account", "pct_of_amount"]

# The bounds a monthly income target may take. `pct` matches `web.monthly_income_target_pct`.
INCOME_TARGET_MAX_PCT = 20.0
INCOME_TARGET_MAX_USD = 1_000_000.0
INCOME_TARGET_MAX_BASE_USD = 1_000_000_000.0


class IncomeTarget(BaseModel):
    """The monthly income goal behind Home's pay card (web, 2026-10-15). Display only: nothing in
    the trading path reads it.

    ``fixed``: ``amount`` dollars a month. ``pct_of_account``: ``pct`` percent of the account's
    value at the month's start. ``pct_of_amount``: ``pct`` percent of ``base`` dollars the
    operator names (a number that does not move with the account). ``off``: no target. Fields
    that do not belong to the mode must be absent, so a stored row can never disagree with itself.
    """

    model_config = ConfigDict(extra="forbid")

    mode: IncomeTargetMode = "off"
    amount: float | None = None
    pct: float | None = None
    base: float | None = None

    @model_validator(mode="after")
    def _fields_fit_the_mode(self) -> IncomeTarget:
        need = {
            "off": (),
            "fixed": ("amount",),
            "pct_of_account": ("pct",),
            "pct_of_amount": ("pct", "base"),
        }[self.mode]
        for name in ("amount", "pct", "base"):
            value = getattr(self, name)
            if name in need and value is None:
                raise ValueError(f"{self.mode} needs {name}")
            if name not in need and value is not None:
                raise ValueError(f"{self.mode} takes no {name}")
        if self.amount is not None and not 0 < self.amount <= INCOME_TARGET_MAX_USD:
            raise ValueError(f"amount must be > 0 and <= {INCOME_TARGET_MAX_USD:,.0f}")
        if self.pct is not None and not 0 < self.pct <= INCOME_TARGET_MAX_PCT:
            raise ValueError(f"pct must be > 0 and <= {INCOME_TARGET_MAX_PCT:g} (percent a month)")
        if self.base is not None and not 0 < self.base <= INCOME_TARGET_MAX_BASE_USD:
            raise ValueError(f"base must be > 0 and <= {INCOME_TARGET_MAX_BASE_USD:,.0f}")
        return self


class MonthPay(BaseModel):
    """One month's options income as a pay stub (web Home, DESIGN.md "October pay").

    Months are New York calendar months. `premium_collected` counts credit on legs SOLD in the
    month; `bought_back` counts debit on legs BOUGHT BACK in the month (an expired or assigned
    leg closes on its expiry date). Commissions are charged by side, once each: the sell-side
    commission (`PnlLeg.open_commissions`) in the month the leg was opened, the rest in the
    month it closed; a leg with no known split charges all of them to the month it opened.
    When `strategy` is "all" or "spread" the figures include the book's spread positions: entry
    credit and entry commission in the month opened, the exit debit and exit commission in the
    month the spread finally closed. `target_pct` echoes the setting; `target` and
    `progress_pct` are None - never 0.0 - when there is no target percentage or no month-start
    account value.
    """

    month: date  # first day of the month
    strategy: Literal["all", "csp", "cc", "spread"]
    premium_collected: float
    bought_back: float
    commissions: float
    commissions_complete: bool
    net: float
    n_opened: int
    n_closed: int
    month_start_value: float | None = None
    target_pct: float | None = None
    # How the target is set (IncomeTarget). `target_pct` is the percentage of either pct mode and
    # None for a fixed amount or no target; `target_amount` and `target_base` echo the other
    # inputs. `target_mode` "off" means no target (the pay card says "No target set").
    target_mode: IncomeTargetMode = "off"
    target_amount: float | None = None
    target_base: float | None = None
    target: float | None = None
    progress_pct: float | None = None
    days_left: int


DayTradeAction = Literal["opened", "closed", "rolled"]
DayTradeHow = Literal["bought_back", "expired", "assigned", "called_away", "rolled"]
DayTradeKind = Literal["csp", "cc", "spread", "other"]


class DayReview(BaseModel):
    """Claude's stored review of an opened trade, field for field the API's ClaudeReviewPayload
    (src/api/models/options.py) so the web renders it with the proposal card's Why disclosure."""

    why_attractive: str = ""
    risks: str = ""
    tradeoffs: str = ""
    assignment_considerations: str = ""
    rolling_considerations: str = ""
    recommendation: str | None = None
    priority: int | None = None
    confidence: float | None = None
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)


class DayFact(BaseModel):
    """One line of a closed or rolled trade's reasoning. ``source`` is who said it: ``system``
    lines are worked out from stored fills, alerts and the roll policy's own log; ``claude``
    lines are Claude's stored view, which the web always labels as Claude's."""

    label: str
    text: str
    source: Literal["system", "claude"] = "system"


class DayRolledTo(BaseModel):
    """The leg a roll opened (the buy-back and the new short share one combo order)."""

    candidate_id: str
    strike: float
    expiry: date
    contracts: int
    premium: float | None = None  # credit collected on the new leg, USD for the position
    commissions: float | None = None


class DayTrade(BaseModel):
    """One executed trade on one New York day, as a Home card (web, 2026-10-15).

    Money is USD for the whole position, never per share. ``premium``, ``bought_back`` and
    ``commissions`` are positive numbers; the card signs them. Unknown is None, never 0.0.
    ``net_pnl`` is the realised result after every commission, set only once the trade is
    closed. ``capital`` is the cash held aside (a put), the shares' strike value (a call) or the
    most a spread can lose.
    """

    key: str
    action: DayTradeAction
    how: DayTradeHow | None = None  # closed / rolled: how it ended
    kind: DayTradeKind
    source: Literal["wheel", "spreads"]
    underlying: str
    right: Literal["C", "P"] | None = None
    strike: float
    long_strike: float | None = None  # spreads only
    expiry: date
    contracts: int
    at: datetime  # UTC: the fill (an expiry or assignment: 16:00 New York on its date)
    is_live: bool = False
    premium: float | None = None
    bought_back: float | None = None
    commissions: float | None = None
    commissions_complete: bool = True
    net_pnl: float | None = None
    capital: float | None = None
    roc_pct: float | None = None
    annualized_pct: float | None = None
    pct_kept: float | None = None  # closed: share of the premium kept before commissions
    dte_at_open: int | None = None
    days_held: int | None = None
    reason: str | None = None  # closed / rolled: the headline reason, one sentence
    facts: list[DayFact] = Field(default_factory=list)
    approval_id: int | None = None
    # Who approved the trade this card is about (web overhaul Part 2): an opened card's entry
    # approval, a rolled card's roll approval. A closed card has none (a close is not the
    # opening approval's decision). None when not recorded; never inferred.
    decided_by: Literal["system", "web", "telegram"] | None = None
    review: DayReview | None = None  # opened: Claude's stored review
    rolled_to: DayRolledTo | None = None


class DayCalendarDay(BaseModel):
    """One New York day's realised P&L: what closed that day, after commissions."""

    date: date
    realized: float
    n_closed: int
    complete: bool = True  # False when a closed leg that day has no commission recorded


class MonthCalendar(BaseModel):
    """A month of daily realised P&L (web, 2026-10-15). Only days something closed appear; a
    missing day is a day with no close, not a day known to be flat."""

    month: date  # first day of the month
    strategy: Literal["all", "csp", "cc", "spread"]
    days: list[DayCalendarDay] = Field(default_factory=list)
    total: float
    n_closed: int
    complete: bool = True


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
    right: Literal["C", "P"] | None = None
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


LedgerBookName = Literal["system", "manual", "spreads"]


class LedgerTrade(BaseModel):
    """One opening option order and everything that closed it (spec §4.2, R3, R4, R9, R10)."""

    order_key: str
    underlying: str
    currency: str
    side: Literal["Sell", "Buy"]
    right: Literal["C", "P"]
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
    book: LedgerBookName
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


# --------------------------------------------------------------------------- #
# Stock lots, ticker roll-ups, FX, portfolio summary (spec §4.3-4.5; Task 6)
# --------------------------------------------------------------------------- #
class LedgerStockLot(BaseModel):
    lot_key: str
    underlying: str
    currency: str
    acquired_date: date
    source: Literal["bought", "assigned", "exercised"]
    quantity: float  # signed quantity originally opened
    remaining: float
    cost_per_share: float  # commission-inclusive


class LedgerStockDisposal(BaseModel):
    lot_key: str
    underlying: str
    currency: str
    disposal_date: date
    quantity: float
    price: float
    realized: float
    codes: str


class LedgerCashItem(BaseModel):
    event_date: date
    event_type: str
    currency: str
    amount: float
    description: str
    underlying: str | None = None


class LedgerTicker(BaseModel):
    symbol: str
    currency: str
    option_premium_gross: float
    option_net_pnl: float
    stock_realized: float
    dividends_net: float
    total_realized: float
    unrealized: float | None
    n_trades: int
    n_open: int
    n_closed: int
    win_rate: float | None
    avg_premium: float | None
    best_trade: float | None
    worst_trade: float | None
    annualised_return_pct: float | None
    shares_held: float
    broker_avg_cost: float | None
    wheel_adjusted_basis: float | None
    first_trade: date | None
    last_trade: date | None


class LedgerBasisPoint(BaseModel):
    point_date: date
    label: str
    basis_per_share: float


class LedgerTickerDetail(BaseModel):
    ticker: LedgerTicker
    trades: list[LedgerTrade]
    lots: list[LedgerStockLot]
    disposals: list[LedgerStockDisposal]
    dividends: list[LedgerCashItem]
    basis_walk: list[LedgerBasisPoint]


class LedgerMonth(BaseModel):
    month: str  # "YYYY-MM"
    premium_usd: float
    realized_usd: float


class LedgerCurvePoint(BaseModel):
    point_date: date
    cumulative_usd: float


class LedgerBucket(BaseModel):
    label: str
    n_closed: int
    realized_usd: float
    win_rate: float | None


class LedgerSummary(BaseModel):
    total_realized_usd: float
    interest_and_fees_usd: float
    contributed_usd: float | None
    capital_utilised_usd: float
    available_usd: float | None
    unrealized_usd: float | None
    win_rate: float | None
    n_trades: int
    n_open: int
    premium_this_month_usd: float
    months: list[LedgerMonth]
    curve: list[LedgerCurvePoint]
    by_strategy: list[LedgerBucket]
    by_book: list[LedgerBucket]
    upcoming: list[LedgerTrade]
    fx_incomplete: bool
    orphan_closes: int
    unreviewed_corporate_actions: int
    marks_as_of: datetime | None


class LedgerBook(BaseModel):
    trades: list[LedgerTrade]
    orphans: list[LedgerOrphan]
    tickers: list[LedgerTicker]
    summary: LedgerSummary
    lots: list[LedgerStockLot]
    disposals: list[LedgerStockDisposal]
    cash: list[LedgerCashItem]


# --------------------------------------------------------------------------- #
# Daily credit spreads (docs/superpowers/plans/2026-10-07-daily-credit-spreads.md)
# --------------------------------------------------------------------------- #

SpreadSide = Literal["put", "call"]
GammaRegime = Literal["positive", "negative", "unknown"]
SpreadExitReason = Literal[
    "profit_take", "stop_loss", "strike_touch", "max_hold", "time_stop", "expire_worthless"
]
EntryTrigger = Literal["move", "always"]


class ChainOption(BaseModel):
    """One option in a spreads chain snapshot (the SPX GEX source or the traded SPY chain)."""

    strike: float
    right: Literal["C", "P"]
    expiry: date
    bid: float | None = None
    ask: float | None = None
    iv: float | None = None  # decimal: 0.18 = 18%
    delta: float | None = None
    open_interest: int | None = None
    con_id: int | None = None

    @property
    def mid(self) -> float | None:
        """None for a missing/negative bid (IBKR's -1 sentinel), a missing ask, or a crossed quote.

        A zero bid is a real quote on a far-OTM 0DTE option and yields ask / 2.
        """
        if self.bid is None or self.ask is None or self.bid < 0 or self.ask <= 0:
            return None
        if self.ask < self.bid:
            return None
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> float | None:
        m = self.mid
        if m is None or m <= 0 or self.bid is None or self.ask is None:
            return None
        return (self.ask - self.bid) / m


class ChainSnapshot(BaseModel):
    symbol: str
    spot: float
    as_of: datetime  # timezone-aware UTC
    options: list[ChainOption] = Field(default_factory=list)

    def find(self, strike: float, right: str, expiry: date) -> ChainOption | None:
        for o in self.options:
            if o.right == right and o.expiry == expiry and abs(o.strike - strike) < 1e-6:
                return o
        return None


class GexLevels(BaseModel):
    """The day's action zones, in traded-underlying (SPY) units except ``net_gex``."""

    as_of: datetime
    spot: float
    net_gex: float  # dealer $-gamma per 1% move, GEX-source units
    regime: GammaRegime
    flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    expected_move: float | None = None  # points
    scale: float = 0.1  # GEX-source level × scale = traded level (live SPY/SPX ratio for SPY)


class SpreadCandidate(BaseModel):
    spread_id: str
    side: SpreadSide
    expiry: date
    short_strike: float
    long_strike: float
    width: float
    short_con_id: int | None = None
    long_con_id: int | None = None
    credit_mid: float  # per share
    credit_natural: float  # short bid - long ask
    short_delta: float | None = None
    short_leg_spread_pct: float | None = None
    long_leg_spread_pct: float | None = None
    spot: float
    quote_time: datetime

    @property
    def max_loss_per_contract(self) -> float:
        return (self.width - self.credit_mid) * 100.0


class SpreadRiskContext(BaseModel):
    now: datetime
    levels: GexLevels | None
    open_spreads: int
    open_risk_usd: float
    trades_today: int
    realized_pnl_today_usd: float
    excess_liquidity_usd: float | None
    capital_usd: float  # the book's capital: starting capital + realized P&L (sizing basis)
    sides_today: list[SpreadSide] = Field(default_factory=list)  # sides opened this ET day


class SpreadVerdict(BaseModel):
    spread_id: str
    approved: bool
    contracts: int = 0
    reasons: list[str] = Field(default_factory=list)


# "baseline" is the simulated book that always takes the deterministic pick when Claude picks
# for the main book (docs/superpowers/specs/2026-10-12-spreads-claude-picker-design.md §3).
SpreadBookMode = Literal["shadow", "paper", "baseline"]


class SpreadPosition(BaseModel):
    spread_id: str
    mode: SpreadBookMode
    side: SpreadSide
    expiry: date
    short_strike: float
    long_strike: float
    width: float
    contracts: int  # still open
    entry_credit: float  # per share
    opened_at: datetime
    short_con_id: int | None = None
    long_con_id: int | None = None
    pick_id: int | None = None  # the spread_picks row that opened it (main book, ai.enabled)
    episode_key: str | None = None  # the trigger episode it was opened in (both books, ai.enabled)


class SpreadExit(BaseModel):
    spread_id: str
    reason: SpreadExitReason
    close: bool  # False = leave the cash-settled spread to expire


class SessionSnapshot(BaseModel):
    """One read of the traded index: the price now plus IBKR's session stats (ticks 14/6/7/9)."""

    as_of: datetime
    last: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prior_close: float | None = None


class SpreadTrigger(BaseModel):
    """Which sides the entry trigger allows right now. ``reason`` is "armed" or "always" when it fires."""

    sides: list[SpreadSide] = Field(default_factory=list)
    reason: str
    move_em: float | None = None  # the move that armed it, in units of the day's expected move


class SpreadEntryContext(BaseModel):
    """What the market looked like when a spread opened — stored with the position for analysis."""

    trigger: EntryTrigger
    move_em: float | None = None
    gap_pct: float | None = None  # today's open / prior close − 1
    gap_day: bool = False
    regime: GammaRegime
    net_gex: float
    flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    expected_move: float | None = None
    day_em: float | None = None
    spot: float
    minutes_after_open: int


class SpreadTradeRecord(BaseModel):
    """One spread in the trade log (open or closed), with its entry tags and its outcome so far."""

    spread_id: str
    mode: SpreadBookMode
    side: SpreadSide
    status: str  # open | expiring | closed
    opened_at: datetime
    closed_at: datetime | None = None
    short_strike: float
    long_strike: float
    width: float
    contracts: int  # opened
    entry_credit: float
    exit_debit: float | None = None
    exit_reason: str | None = None
    pnl_usd: float  # realized so far, after commissions
    regime: str
    trigger: str
    move_em: float | None = None
    gap_pct: float | None = None
    gap_day: bool = False
    minutes_after_open: int | None = None
    hold_minutes: float | None = None
    mae_usd: float | None = None  # worst mark against the position while open, >= 0
    pick_id: int | None = None  # the spread_picks row that opened it (main book, ai.enabled)
    episode_key: str | None = None  # the trigger episode it was opened in (both books, ai.enabled)


# --- Claude picks the spread (docs/superpowers/specs/2026-10-12-spreads-claude-picker-design.md)

SpreadMenuPosition = Literal["inside", "baseline", "outer"]
PlanBias = Literal["bullish", "neutral", "bearish"]


class SpreadMenuItem(BaseModel):
    """One gate-approved spread on the pick menu. Every number is computed by
    ``src/spreads/menu.py``; the prompt only formats them."""

    letter: str
    position: SpreadMenuPosition
    candidate: SpreadCandidate
    contracts: int  # set by risk.validate — never by Claude
    credit_after_costs: float  # per share, mid credit less round-trip slippage + commission
    cost_pct_of_credit: float | None
    max_loss_per_contract_usd: float
    dist_spot_pts: float  # short strike's distance from spot, SPY points (positive = OTM)
    dist_em_multiple: float | None  # the same in units of the expected move
    beyond_wall_pts: float | None  # + = short strike beyond its wall (put below, call above)
    dist_flip_pts: float | None = None  # + = short strike beyond the gamma flip, on the OTM side
    be_full_loss: float | None  # break-even win rate if every loss is a full max loss
    be_nominal_exits: float | None  # break-even win rate under the configured profit take / stop


class SpreadTapeStats(BaseModel):
    prior_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    last: float | None = None
    high_at: datetime | None = None
    low_at: datetime | None = None
    move_em: float | None = None  # the move the triggered side sells against, in expected moves
    stall_minutes: float | None = None
    gap_pct: float | None = None
    day_em: float | None = None


class SpreadBookStats(BaseModel):
    mode: str
    closed_trades: int
    win_rate: float | None = None
    breakeven_win_rate: float | None = None
    expectancy_usd: float | None = None
    total_pnl_usd: float = 0.0


class SpreadExitRules(BaseModel):
    profit_take_pct: float
    stop_debit_multiple: float
    close_on_short_strike_touch: bool
    max_hold_minutes: int | None
    force_close: str  # HH:MM ET


class SpreadDayPlan(BaseModel):
    bias: PlanBias
    risk_flags: list[str] = Field(default_factory=list)
    skip_conditions: list[str] = Field(default_factory=list)
    preferred_distance: str = ""
    summary: str = ""


class SpreadMarketSnapshot(BaseModel):
    """The enrichment inputs src/spreads_ai gathers itself. Every field degrades to None."""

    vix: float | None = None
    vix_term_ratio: float | None = None
    ten_year_yield: float | None = None
    ten_year_change_5d_bp: float | None = None
    spy_ret_5d_pct: float | None = None
    spy_vs_sma20_pct: float | None = None
    spy_vs_sma50_pct: float | None = None
    rsi14: float | None = None
    hv30: float | None = None  # 30-day annualised realised vol, percent (18.5 = 18.5%)
    headline_count: int = 0
    headline_sentiment_mean: float | None = None
    headlines: list[str] = Field(default_factory=list)
    econ_today: list[str] = Field(default_factory=list)
    # The shared market picture (src/common/picture_text.render_picture, regime lines labelled "as
    # of <built_at>"), read from news.db. None when there is no picture; prompt text only.
    picture_text: str | None = None
    unavailable: list[str] = Field(default_factory=list)  # sources that failed this call


class SpreadLlmCall(BaseModel):
    model: str
    effort: str
    latency_ms: int | None = None
    cost_usd: float | None = None  # notional, from the CLI envelope
    prompt_text: str = ""
    raw_response: str | None = None
    error: str | None = None


class SpreadBriefRequest(BaseModel):
    """Deterministic inputs the spreads service hands the picker (it owns all of them)."""

    now: datetime
    levels: GexLevels
    tape: SpreadTapeStats
    events: list[str] = Field(default_factory=list)
    ex_dividend_window: bool = False
    exits: SpreadExitRules
    books: list[SpreadBookStats] = Field(default_factory=list)


class SpreadPickRequest(SpreadBriefRequest):
    sides: list[SpreadSide]
    menu: list[SpreadMenuItem]
    plan: SpreadDayPlan | None = None
    round_trip_cost_per_share: float


class SpreadBriefResult(BaseModel):
    plan: SpreadDayPlan | None  # None = the brief failed (call.error says why)
    market: SpreadMarketSnapshot
    call: SpreadLlmCall


class SpreadPick(BaseModel):
    """The picker's answer. ``choice`` is validated against the menu by the service, never here."""

    choice: str  # a menu letter or "skip"
    reason: str = ""
    fallback_reason: str | None = (
        None  # timeout | cli_missing | cli_error | bad_envelope | unparseable | picker_error
    )
    market: SpreadMarketSnapshot
    call: SpreadLlmCall


class SpreadPickSnapshot(BaseModel):
    """The deterministic conditions stored with every pick, for the comparison report."""

    regime: str
    flip_distance_pct: float | None = None  # (spot - flip) / spot
    expected_move: float | None = None
    move_em: float | None = None
    stall_minutes: float | None = None
    gap_pct: float | None = None
    gap_day: bool = False
    side: str = ""
    event_flag: bool = False
    plan_bias: str | None = None


class SpreadPickRecord(BaseModel):
    pick_id: int
    created_at: datetime
    day: date
    episode_key: str
    book_mode: str
    menu: list[SpreadMenuItem]
    choice: str
    reason: str
    fallback_reason: str | None
    executed_letter: str | None
    send_rejected: bool
    send_reasons: list[str]
    filled: bool
    model: str
    effort: str
    latency_ms: int | None
    cost_usd: float | None
    snapshot: SpreadPickSnapshot
    market: SpreadMarketSnapshot
    prompt_text: str
    raw_response: str | None
