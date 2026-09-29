"""Build the prompt string sent to `claude -p` for candidate review."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.analytics.market_conditions import render_macro_context
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    MarketConditions,
    OptionRight,
    TechnicalStats,
    TradeCandidate,
)

if TYPE_CHECKING:
    from src.storage.models import ClaudeMemoryRow

# Per-underlying analytics keyed by symbol — the raw technical/fundamental/IV-microstructure
# signals that were previously collapsed into the opaque ScoreCard digits before reaching the
# reasoning layer. Threaded through `review_candidates` from the scan's `analytics_map`.
AnalyticsMap = dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]]

# Compact universe knowledge injected into every review prompt.
# Full research with sources lives in UNIVERSE_RESEARCH.md at the project root.
_UNIVERSE_CONTEXT = """
=== UNIVERSE CONTEXT (ticker knowledge — use when writing risks/tradeoffs) ===

⚠ PRICES & IV RANKS BELOW WERE RESEARCHED Jun-2026 AND ARE STALE. They are coarse anchors for
qualitative judgement (tier, liquidity, CC-vs-CSP suitability, structural risks) ONLY. For any
current price level, use the SCAN-TIME SPOT PRICES block — never quote these figures as live.

Risk tiers: SAFE_BETS (core, fund-manager grade), MODERATE (elevated IV, real fundamentals),
RISKY (speculative / high-IV, assignment is a risk event). Orthogonal to that: `would_own`
names marked ACTIVELY_WHEELING below are the core rotation, scanned every intraday cycle;
DIP-WATCH would_own names are only pulled into a scan on a genuine ≥3% drop — a rally is never
a CSP entry signal for them, so don't treat a DIP-WATCH name's price rise as a reason to expect
a CSP candidate on it.

SAFE_BETS — Core income (fund-manager grade, stable assignment):
  SPY  ~$540  IVR 15-35  CC+CSP  0.8-2.5%/mo   index; ETF, no earnings risk; ACTIVELY_WHEELING
  QQQ  ~$470  IVR 18-40  CC+CSP  1.0-2.5%/mo   index; tech-heavy; ACTIVELY_WHEELING
  IWM  ~$200  IVR 20-45  CC+CSP  1.5-3.0%/mo   small-cap index; DIP-WATCH
  SMH  ~$220  IVR 28-55  CC+CSP  2.0-4.0%/mo   semi sector ETF; diversified; DIP-WATCH
  MAGS ~$55   IVR unk    CC+CSP  unk           Roundhill Magnificent Seven ETF; equal-weight
                                                AAPL/MSFT/GOOGL/AMZN/META/NVDA/TSLA — heavily
                                                overlaps other tech names below; ACTIVELY_WHEELING
  AAPL ~$211  IVR 18-40  CC+CSP  0.8-1.2%/mo   most liquid chain; low IV; DIP-WATCH
  MSFT ~$413  IVR 15-35  CC+CSP  0.7-1.0%/mo   structurally low IV (~7-8% avg); DIP-WATCH
  GOOGL~$165  IVR 22-45  CC+CSP  1.0-2.0%/mo   diversified revenue; ACTIVELY_WHEELING
  NVDA ~$224  IVR 32-64  CC+CSP  2.0-4.0%/mo   AI leader; IV compressed from 50%+ highs; ACTIVELY_WHEELING
  AMZN ~$205  IVR 25-45  CC+CSP  1.5-3.0%/mo   AWS + retail + ads; ACTIVELY_WHEELING
  JPM  ~$280  IVR 20-40  CC+CSP  1.0-2.0%/mo   financials; dividend payer; DIP-WATCH
  V    ~$324  IVR 12-28  CC+CSP  0.6-1.0%/mo   payments moat; LOW IV, ~$32k collateral; DIP-WATCH
  WMT  ~$120  IVR 14-30  CC+CSP  0.7-1.2%/mo   defensive staple; liquid chain; DIP-WATCH
  AMD  held   IVR 30-55  CC      1.5-3.0%/mo   semis; held 300sh — CC income on existing shares
  BAC  held   IVR 20-40  CC+CSP  0.8-1.5%/mo   money-centre bank; held 1000sh — CC income; ACTIVELY_WHEELING

DIVERSIFIER ETFs (broaden away from the tech/crypto tilt; defensives are LOW-IV → few signals;
all DIP-WATCH — pulled in only on a ≥3% drop, never scanned every cycle):
  XLV  ~$154  healthcare; defensive, low IV — thin premium even when it does fetch
  XLP  ~$85   consumer staples; very low IV — rarely clears the IV gate; would_own-eligible but not actively scanned
  TLT  ~$86   long Treasuries; very low IV — hedge sleeve; would_own-eligible but not actively scanned

MODERATE — Active income (elevated IV, real fundamentals):
  TSLA ~$395  IVR 40-70  CC+CSP  2.5-5.0%/mo   deepest single-stock liquidity after AAPL; high premium; DIP-WATCH
  META ~$640  IVR 28-55  CC+CSP  2.0-4.0%/mo   strong FCF since 2023; large CSP collateral; ACTIVELY_WHEELING
  PLTR ~$158  IVR 47     CC+CSP  3.0-5.0%/mo   AI/defence; IV rank 46.73 verified Jun-2026; ACTIVELY_WHEELING
  SOFI ~$18   IVR 27     CC+CSP  3.0-6.0%/mo   IVR currently ~27 (below ideal 30+); up 32% YTD; ACTIVELY_WHEELING
  HOOD ~$90   IVR 45-80  CC+CSP  3.0-6.0%/mo   retail brokerage; crypto-correlated IV; ACTIVELY_WHEELING
  HIMS ~$35   IVR 55-90  CC+CSP  4.0-8.0%/mo   telehealth; ±16% earnings move; FDA binary risk; ACTIVELY_WHEELING
  BABA ~$133  IVR 35-55  CC+CSP* 2.0-4.0%/mo   *ADR delisting/geopolitical risk — size small; DIP-WATCH
  NBIS ~unk   IVR unk    CC+CSP  unk           Nebius Group; AI infrastructure/cloud; elevated IV; ACTIVELY_WHEELING
  UBER/CRWD — high-IV mobility/cybersecurity names; both DIP-WATCH (would_own-eligible,
      pulled in only on a ≥3% drop). TEM is watchlist/CC-only, not in would_own.

RISKY — leveraged, DELIBERATE would_own exception (TQQQ/UPRO/SOXL confirmed 2026-08-27, DPST
confirmed 2026-09-29 — decay risk on assignment is accepted for these four specifically;
ACTIVELY_WHEELING):
  TQQQ ~unk   IV high    CC+CSP  high          3× Nasdaq-100
  UPRO ~unk   IV high    CC+CSP  high          3× S&P 500
  SOXL ~$25   IV 80-140% CC+CSP 182-534% ann   3× semi; -85% in 2022; decay accepted for this account
  DPST ~$120  IV 70-110% CC+CSP high           3× regional banks; deliberate would_own exception
                                                (2026-09-29); size small, prefer short DTE; verify OI

RISKY — CC-only leveraged ETFs (NEVER would_own — no exception for these):
  LABU ~$20   IV 90-160% CC ONLY extreme       3× biotech + FDA binary risk; never assign
  TSLL ~$15   IV 90-130% CC ONLY very high     2× TSLA; affordable entry; leverage decay

RISKY — Speculative stocks (in would_own, ACTIVELY_WHEELING, hard position limits):
  MARA ~$15   IV 90-130% CC+CSP* 6-12%/mo     *BTC proxy; can lose 70%+ in bear cycle
  RGTI ~$10   IV ~86%    CC+CSP* speculative   *quantum computing; IVR 9.52% (LOW) — wait for IVR>40
  RKLB ~$25   IV 70-110% CC+CSP* speculative   *space launch; pre-profit; cap sizing
  ASTS ~$40   IV 80-120% CC ONLY* speculative  *satellite comms; pre-revenue; now ACTIVELY_WHEELING
  IONQ ~$40   IV 80-120% CC ONLY speculative   quantum (same thesis as RGTI); not in would_own

KEY RULES FOR REVIEW:
- Flag any candidate with IVR < 30 as "thin premium environment"
- Ideal sell zone: IVR ≥ 50 (TastyTrade standard); IVR 30-49 = acceptable
- AAPL/MSFT premiums rarely exceed 1.2%/month — sanity-check yield claims
- Defensive names (V and XLP/XLV/TLT) are LOW-IV — expect few signals; never inflate yield claims for them
- Crypto cluster (MARA) is BTC-correlated
- Leveraged ETFs: every review must note "assignment risk is NAV decay" — even for TQQQ/UPRO/SOXL/DPST,
  which are would_own despite this (a deliberate, accepted exception, not an oversight)
- BABA: every review must note ADR/geopolitical risk
- MARA/RGTI/RKLB/ASTS and other RISKY names: every review must note speculative nature and cap sizing reminder
- HIMS: flag FDA calendar risk near any earnings or regulatory announcement date
- MAGS: flag the overlap with GOOGL/NVDA/AMZN when sizing — it's not independent exposure
""".strip()


def _format_history(memory: list[ClaudeMemoryRow]) -> list[str]:
    """Format prior recommendation history for injection into the prompt."""
    if not memory:
        return []

    lines = ["", "=== YOUR PRIOR RECOMMENDATIONS (learn from these outcomes) ==="]
    for row in memory:
        outcome = row.outcome or "pending (no outcome yet)"
        confidence_str = f" confidence={row.confidence:.2f}" if row.confidence is not None else ""
        lines.append(
            f"[{row.scan_date}] {row.underlying} {row.strategy_type}: "
            f'"{row.recommendation}"{confidence_str} → outcome: {outcome.upper()}'
        )
        if row.rationale:
            lines.append(f"  Rationale: {row.rationale[:200]}")
    lines.append("")
    return lines


def _backtest_line(cand: TradeCandidate) -> str:
    """Compact on-demand backtest for one candidate, gated by `claude.backtest_in_prompt` (C11).

    Fail-soft and OFF by default: when disabled or on any error, returns an empty string so a
    yfinance hiccup can never break prompt building. Enrichment only — reaches Claude solely
    through this prompt, never the engine (CLAUDE.md fence).
    """
    from src.common.config import get_config

    if not get_config().claude.backtest_in_prompt:
        return ""
    try:
        from src.backtest.on_demand import backtest_candidate

        summary = backtest_candidate(cand)
        return f"Backtest:         {summary}" if summary else ""
    except Exception:
        return ""


def _spot_prices_block(
    candidates: list[TradeCandidate], spot_prices: dict[str, float] | None
) -> list[str]:
    """Render scan-time spot prices for the candidates' underlyings (N17).

    These are the *current* levels; the static universe block's prices are stale Jun-2026
    anchors. Only symbols actually under review are listed, deduped, in candidate order.
    """
    if not spot_prices:
        return []
    seen: set[str] = set()
    rows: list[str] = []
    for c in candidates:
        if c.underlying in seen:
            continue
        seen.add(c.underlying)
        price = spot_prices.get(c.underlying)
        if price is not None:
            rows.append(f"  {c.underlying:<6} ${price:,.2f}")
    if not rows:
        return []
    return [
        "=== SCAN-TIME SPOT PRICES (authoritative — use these, NOT the stale figures above) ===",
        *rows,
        "",
    ]


def _compact_money(v: float) -> str:
    """Render a (possibly large) dollar figure compactly with an explicit sign — e.g. +$12.4B."""
    sign = "+" if v >= 0 else "-"
    a = abs(v)
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.0f}M"
    return f"{sign}${a:,.0f}"


def _analytics_lines(c: TradeCandidate, analytics: AnalyticsMap | None) -> list[str]:
    """Render the raw technical / fundamental / IV-microstructure signals for a candidate's
    underlying.

    These are computed every scan but were previously collapsed into the opaque ScoreCard digits
    (Tech=NN, Fund=NN) before reaching the reasoning layer — so the model was asked to explain a
    name's risks while only seeing a bare composite number. Surfacing the signals lets it reason
    from momentum/trend/regime, leverage/dividend timing, and the IV term-structure/skew, and
    makes the single-ticker SUMMARY GUIDE's request to interpret "RSI/trend" actually satisfiable.

    Enrichment only — like the rest of this prompt these never reach the engine (CLAUDE.md fence).
    """
    if not analytics:
        return []
    triple = analytics.get(c.underlying)
    if triple is None:
        return []
    iv, tech, fund = triple
    lines: list[str] = []

    # Technicals: momentum, regime, trend position vs the SMAs, realised-move magnitude.
    tbits: list[str] = []
    if tech.rsi_14 is not None:
        tbits.append(f"RSI {tech.rsi_14:.0f}")
    if tech.regime is not None:
        tbits.append(f"regime {tech.regime.value}")
    if tech.price > 0:
        if tech.sma_50 is not None:
            tbits.append("above 50d" if tech.price >= tech.sma_50 else "below 50d")
        if tech.sma_200 is not None:
            tbits.append("above 200d" if tech.price >= tech.sma_200 else "below 200d")
    if tech.atr_ratio is not None:
        tbits.append(f"ATR/px {tech.atr_ratio:.1f}%")
    if tbits:
        lines.append(f"Technicals:       {' · '.join(tbits)}")

    # Fundamentals: quality, leverage, free cash flow, and dividend/ex-div (early-assignment
    # timing matters for covered calls — a deep-ITM call can be assigned around the ex-date).
    fbits: list[str] = []
    if fund.pe_ratio is not None:
        fbits.append(f"P/E {fund.pe_ratio:.1f}")
    if fund.debt_to_equity is not None:
        fbits.append(f"D/E {fund.debt_to_equity:.0f}")
    if fund.free_cash_flow is not None:
        fbits.append(f"FCF {_compact_money(fund.free_cash_flow)}")
    if fund.dividend_yield:
        safe = "" if fund.dividend_safe is None else (" safe" if fund.dividend_safe else " unsafe")
        fbits.append(f"div {fund.dividend_yield * 100:.1f}%{safe}")
    if fund.ex_dividend_date is not None:
        fbits.append(f"ex-div {fund.ex_dividend_date}")
    if fbits:
        lines.append(f"Fundamentals:     {' · '.join(fbits)}")

    # IV microstructure: percentile (complements rank), the IV/RV edge, term-structure shape,
    # and put/call skew — the premium-selling edge and tail-pricing the composite IV score hides.
    ibits: list[str] = []
    if iv.current_iv is not None:
        ibits.append(f"IV {iv.current_iv:.1f}%")
    if iv.hv_30 is not None:
        ibits.append(f"HV30 {iv.hv_30:.1f}%")
    if iv.iv_percentile is not None:
        ibits.append(f"IV%ile {iv.iv_percentile:.0f}")
    if iv.iv_rv_ratio is not None:
        ibits.append(f"IV/RV {iv.iv_rv_ratio:.2f}")
    if iv.term_structure_slope is not None:
        shape = "contango" if iv.term_structure_slope > 0 else "backwardation"
        ibits.append(f"term {iv.term_structure_slope:+.4f} ({shape})")
    if iv.put_call_skew is not None:
        ibits.append(f"skew {iv.put_call_skew:+.2f}")
    if ibits:
        lines.append(f"IV structure:     {' · '.join(ibits)}")

    return lines


def _ideal_zone_lines(c: TradeCandidate) -> list[str]:
    """Render the deterministic ideal zone for a candidate.

    Gives the model a *reference point* rather than an isolated quote: the strike band the
    technicals and IV imply, the credit below which the trade carries no variance-risk
    premium, and the underlying level that would restore the intended cushion. The model's job
    is to reconcile the offered contract with these, not to recompute them — the numbers are
    produced by ``analytics.fair_value`` in deterministic Python.

    Enrichment only — never reaches the engine (CLAUDE.md fence).
    """
    zone = c.ideal
    if zone is None:
        return []
    lines: list[str] = []
    if zone.strike_lo is not None and zone.strike_hi is not None:
        placement = "inside" if zone.strike_lo <= c.strike <= zone.strike_hi else "OUTSIDE"
        anchor = f" (anchor ${zone.strike_anchor:.2f})" if zone.strike_anchor is not None else ""
        lines.append(
            f"Ideal strike:     ${zone.strike_lo:.2f}-${zone.strike_hi:.2f}{anchor};"
            f" this contract's ${c.strike:.2f} is {placement}"
        )
    if zone.strike_anchors:
        lines.append(f"Zone drivers:     {' · '.join(zone.strike_anchors)}")
    if zone.min_credit is not None:
        verdict = "below" if c.premium < zone.min_credit else "above"
        lines.append(
            f"Ideal credit:     >= ${zone.min_credit:.2f}/sh"
            f" (offered ${c.premium:.2f} is {verdict} it)"
        )
    if zone.credit_anchors:
        lines.append(f"Credit basis:     {' · '.join(zone.credit_anchors)}")
    if zone.action_note:
        lines.append(f"Action level:     {zone.action_note}")
    if zone.buy_below is not None:
        lines.append(f"Share entry:      buy below ${zone.buy_below:.2f}")
    if lines:
        lines.append(f"Zone confidence:  {zone.confidence} (how much data the zone had)")
    return lines


def _iv_bucket(rank: float) -> str:
    """TastyTrade-style IV rank bucket used by F5 below: <30 thin, 30-60 normal, >60 rich."""
    if rank > 60:
        return "RICH"
    if rank < 30:
        return "THIN"
    return "NORMAL"


def _candidate_facts(
    c: TradeCandidate, spot: float | None, *, gate_passed: bool = True
) -> list[str]:
    """Numbered, deterministic FACTS about one candidate — computed in Python so the model
    never has to derive moneyness, cushion, or earnings timing itself (Task 10: the local
    Ollama reviewer was misreading an out-of-the-money put as "in the money" and treating a
    post-expiry earnings date as event risk when left to work that out from raw numbers).

    Consumed as an ``F1``-``F7`` block in the prompt; the DECISION RUBRIC asks the model to cite
    these ids (plus any future ``N#`` news ids) in ``evidence`` rather than re-deriving or
    inventing numbers. Every line degrades independently — a candidate missing spot, earnings,
    an ideal zone, IV rank, or IV/RV just omits that fact instead of guessing at it.

    ``gate_passed`` (Task 10 fix round 1): ``F7`` claims the deterministic Rules Engine passed
    this specific candidate, which is only true on the full-universe path — the single-ticker
    deep-dive (``build_prompt(..., single_ticker=True)``) can review a near-miss that failed
    every gate (``scan.py``'s ``cc_near_miss``/``csp_near_miss`` fallback when nothing cleared).
    Callers pass ``gate_passed=False`` for that path so ``F7`` is omitted rather than asserting a
    pass that didn't happen — a plan-mandated defect the review caught: printing "F7 Passed every
    deterministic gate" for a candidate the gate actually rejected would hand the model a false
    premise to reason from.
    """
    facts: list[str] = []
    is_put = c.right == OptionRight.PUT
    right_word = "put" if is_put else "call"

    if spot:
        strike_pct = abs(spot - c.strike) / spot * 100
        direction = "BELOW" if c.strike < spot else "ABOVE"
        # OTM: a put's strike sits below spot; a call's strike sits above spot.
        otm = (is_put and c.strike < spot) or (not is_put and c.strike > spot)
        moneyness = "out-of-the-money" if otm else "in-the-money"
        facts.append(
            f"F1 Strike ${c.strike:.2f} is {strike_pct:.1f}% {direction} spot ${spot:.2f} "
            f"→ {moneyness} {right_word}"
        )

        be_direction = "below spot" if c.breakeven <= spot else "above spot"
        be_pct = abs(spot - c.breakeven) / spot * 100
        facts.append(f"F2 Breakeven ${c.breakeven:.2f} = {be_pct:.1f}% cushion {be_direction}")

    if c.next_earnings is not None:
        if c.next_earnings > c.expiry:
            facts.append(
                f"F3 Earnings {c.next_earnings} is AFTER expiry {c.expiry} → no earnings "
                "inside this trade"
            )
        else:
            days_before = (c.expiry - c.next_earnings).days
            facts.append(
                f"F3 Earnings {c.next_earnings} is INSIDE this trade ({days_before} days "
                "before expiry) → event risk"
            )

    if c.ideal is not None and c.ideal.min_credit:
        floor = c.ideal.min_credit
        edge_pct = (c.premium - floor) / floor * 100
        if edge_pct >= 0:
            facts.append(
                f"F4 Credit ${c.premium:.2f} vs fair-value floor ${floor:.2f} → "
                f"+{edge_pct:.0f}% edge over the variance-risk-premium floor"
            )
        else:
            facts.append(
                f"F4 Credit ${c.premium:.2f} vs fair-value floor ${floor:.2f} → "
                f"{edge_pct:.0f}% UNDER the variance-risk-premium floor"
            )

    # Task 9 gave a missing IV rank a neutral score + an `iv_rank_unavailable` tag rather than
    # inventing a bucket — F5 must say the same thing plainly instead of guessing a bucket.
    if c.iv_rank is not None:
        facts.append(
            f"F5 IV rank {c.iv_rank:.0f} → premium is {_iv_bucket(c.iv_rank)} vs its own year"
        )
    else:
        facts.append("F5 IV rank unavailable (no IV history) → premium richness unknown")

    if c.iv_rv_ratio is not None:
        note = (
            "options priced above realised movement"
            if c.iv_rv_ratio >= 1.0
            else "options priced at/below realised movement"
        )
        facts.append(f"F6 IV/RV {c.iv_rv_ratio:.2f} → {note}")

    if gate_passed:
        facts.append(
            "F7 Passed every deterministic gate (delta, liquidity, fair value, IV, earnings "
            "blackout, concentration)"
        )

    return facts


def _vix_context(vix: float | None) -> str:
    """One-line macro-vol regime hint derived from the VIX level.

    Delegates to ``analytics.market_conditions.vix_regime``. The Telegram card
    (``formatters._vix_regime``) keeps its own terser phrasing for message-length reasons but
    uses the same 15/20/30 thresholds — keep them in step if either is retuned.
    """
    if vix is None:
        return "VIX: unavailable"
    from src.analytics.market_conditions import vix_regime

    return f"VIX: {vix:.1f} ({vix_regime(vix)})"


def build_prompt(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    history: list[ClaudeMemoryRow] | None = None,
    market_conditions: MarketConditions | None = None,
    spot_prices: dict[str, float] | None = None,
    sector_context: str | None = None,
    single_ticker: bool = False,
    analytics: AnalyticsMap | None = None,
    news_block: str | None = None,
) -> str:
    """Build the full prompt string sent to the reasoning backend.

    Returns an empty string if there are no candidates (caller skips the call).
    history: optional list of ClaudeMemoryRow from prior scans for learning injection.
    market_conditions: optional macro snapshot (VIX) so the reasoning layer can weigh the
        vol regime. Enrichment only — it never changes the deterministic gates.
    spot_prices: optional scan-time {symbol: spot} so the model reasons from current levels
        rather than the stale Jun-2026 anchors baked into the static universe block (N17).
    sector_context: optional pre-rendered SECTOR & MARKET BACKDROP block (single-ticker scans
        only) so the model can place the name against its industry and the broad market.
    single_ticker: when True, this is a `/scan TICKER` deep-dive — the task asks for a plain-
        English ``summary`` that *explains what each metric means* and synthesizes the overall
        sentiment. The full-universe path leaves it False to keep the buy-list cards concise.
    analytics: optional {symbol: (IVStats, TechnicalStats, FundamentalStats)} so each candidate
        is annotated with the raw technical/fundamental/IV-microstructure signals — not just the
        opaque ScoreCard composites. Enrichment only (CLAUDE.md fence).
    news_block: optional pre-rendered ``=== NEWS ===`` block (Task 10, ``N#`` ids —
        :func:`src.claude.news_context.build_news_block`) so the DECISION RUBRIC's "cite a
        FACT (F#) or NEWS item (N#)" instruction has real news to point at, on both the
        full-universe and single-ticker paths. Precomputed by the caller — like every other
        optional context block here, `build_prompt` itself performs no I/O — and omitted
        entirely when `None`/empty, matching every other block's fail-soft pattern.
    """
    if not candidates:
        return ""

    vix = market_conditions.vix if market_conditions else None
    # The full-universe path always reviews gate-approved candidates, so it can state that
    # plainly. The single-ticker deep-dive may also review the closest *near-miss* when nothing
    # cleared the gate (so the card still gets a Read), so its framing stays neutral about gate
    # status — the card itself shows each contract's pass/fail and reason.
    if single_ticker:
        role = (
            "These candidates were surfaced by the deterministic screen for a single-ticker "
            "deep-dive (they may not all have cleared every risk gate — the card shows each "
            "contract's status). Your role is enrichment only: explain the risks, tradeoffs, and "
            "assignment considerations and synthesize an overall read. You cannot place, size, or "
            "block orders."
        )
    else:
        role = (
            "These candidates have already been approved by the deterministic Rules Engine. "
            "Your role is enrichment only: re-rank by priority and explain the risks, tradeoffs, "
            "and assignment considerations so the trader can make an informed final decision. "
            "You cannot place, size, or block orders."
        )
    lines: list[str] = [
        "You are a disciplined options income strategist reviewing proposed covered call (CC) "
        "and cash-secured put (CSP) trades for an Interactive Brokers account.",
        "",
        role,
        "",
        _UNIVERSE_CONTEXT,
        "",
    ]

    # Scan-time spot prices override the stale static anchors (N17).
    lines += _spot_prices_block(candidates, spot_prices)

    # Single-ticker deep-dive: the sector/market backdrop so the model judges the name in context.
    if single_ticker and sector_context:
        lines += [sector_context, ""]

    lines += [
        "=== MARKET CONTEXT ===",
        _vix_context(vix),
        "",
    ]

    # Macro backdrop: VIX term structure, rates, the tape and broad-market news flow. Only the
    # single-ticker deep-dive gets it — the full-universe prompt is shared across ~10 candidates
    # and must stay compact enough for the local model's context window.
    if single_ticker:
        macro_block = render_macro_context(market_conditions)
        if macro_block:
            lines += [macro_block, ""]

    # Recent news (Task 11) — same block on both the full-universe and single-ticker paths, so
    # the DECISION RUBRIC's "cite a FACT (F#) or NEWS item (N#)" instruction always has real
    # N# ids available when news was fetched. Precomputed by the caller (enrichment; no I/O here).
    if news_block:
        lines += [news_block, ""]

    lines += [
        "=== PORTFOLIO SUMMARY ===",
        f"Net Liquidation: ${account.net_liquidation:,.0f}",
        f"Buying Power:    ${account.buying_power:,.0f}",
        f"Maint. Margin:   ${account.maintenance_margin:,.0f}",
        f"Excess Liquidity:${account.excess_liquidity:,.0f}",
        "",
        "=== TRADE CANDIDATES ===",
    ]

    if history:
        lines.extend(_format_history(history))

    for i, c in enumerate(candidates, 1):
        lines.append(f"\n--- Candidate {i} ---")
        lines.append(f"ID:               {c.candidate_id}")
        lines.append(f"Strategy:         {c.strategy.value.replace('_', ' ').upper()}")
        lines.append(f"Symbol:           {c.underlying}  ({c.right.value})")
        lines.append(f"Strike / Expiry:  ${c.strike:.2f}  {c.expiry}  ({c.dte} DTE)")
        lines.append(f"Premium ($/share):{c.premium:.4f}   Contracts: {c.contracts}")
        lines.append(
            f"ROC:              {c.roc_pct:.2f}%   Ann. Yield: {c.annualized_yield_pct:.1f}%"
        )
        lines.append(f"Breakeven:        ${c.breakeven:.2f}")
        if c.delta is not None:
            lines.append(f"Delta:            {c.delta:.3f}")
        if c.iv_rank is not None:
            lines.append(f"IV Rank:          {c.iv_rank:.1f}/100")
        if c.vrp is not None:
            lines.append(f"VRP (IV−HV30):    {c.vrp:+.1f}%  (positive = options rich vs realised)")
        if c.prob_otm is not None:
            lines.append(f"Prob. OTM (≈1−|Δ|): {c.prob_otm:.1%}  (P expire OTM, not P profit)")
        lines.append(f"Blended Score:    {c.blended_score:.1f}/100")
        backtest_line = _backtest_line(c)
        if backtest_line:
            lines.append(backtest_line)
        lines.append(f"Rationale Tags:   {', '.join(c.rationale_tags) or 'none'}")
        lines.append(
            f"ScoreCard:        IV={c.scores.iv_score:.0f}  Tech={c.scores.technical_score:.0f}  "
            f"Fund={c.scores.fundamental_score:.0f}  Liq={c.scores.liquidity_score:.0f}  "
            f"AsnRisk={c.scores.assignment_safety_score:.0f}"
        )
        # Raw signals behind the Tech/Fund/IV composites above (enrichment — never gates).
        lines += _analytics_lines(c, analytics)
        # Where this contract *should* sit, per deterministic technicals + IV. Gives the model a
        # reference to reconcile the offered strike/credit against instead of judging in a vacuum.
        lines += _ideal_zone_lines(c)
        # Deterministic FACTS (Task 10) — moneyness, cushion, earnings timing, fair-value edge,
        # IV rank/RV bucket, and (full-universe only — see gate_passed docstring) the gate-pass
        # line, all computed in Python so the model reads them instead of deriving (and
        # sometimes misreading) them itself.
        candidate_spot = spot_prices.get(c.underlying) if spot_prices else None
        lines.append("FACTS:")
        lines += [
            f"  {fact}"
            for fact in _candidate_facts(c, candidate_spot, gate_passed=not single_ticker)
        ]
        if c.next_earnings is not None:
            lines.append(f"Next Earnings:    {c.next_earnings}  (event risk — see sentiment below)")
        _sd = c.scores.sentiment_detail
        if _sd is not None and _sd.overall is not None:
            parts = [f"overall {_sd.overall:.0f}/100 ({_sd.label})"]
            if _sd.delta_1d is not None:
                parts.append(f"Δ1d {_sd.delta_1d:+.0f}")
            if _sd.stocktwits is not None:
                parts.append(f"StockTwits {_sd.stocktwits:.0f} [{_sd.stocktwits_msgs} msgs]")
            if _sd.news is not None:
                parts.append(f"News {_sd.news:.0f} [{_sd.news_count} hdl]")
            if _sd.reddit is not None:
                parts.append(f"Reddit {_sd.reddit:.0f}")
            lines.append(f"Sentiment:        {'  '.join(parts)}")
            if _sd.top_headline:
                lines.append(f"Top Headline:     {_sd.top_headline[:120]}")

    candidate_ids = [c.candidate_id for c in candidates]
    # `summary` is requested on every path (Task 10). The single-ticker deep-dive's job is to
    # *teach* — explain what the metrics mean and synthesize the sentiment — so it points at the
    # longer SUMMARY GUIDE below; the full-universe buy-list asks for a short 2-3 sentence
    # synthesis directly in the schema so its cards stay scannable.
    summary_schema_line = (
        '  "summary": "<see SUMMARY GUIDE below>",'
        if single_ticker
        else '  "summary": "<2-3 sentence plain-English synthesis>",'
    )
    summary_guide: list[str] = []
    if single_ticker:
        summary_guide = [
            "",
            "=== SUMMARY GUIDE (single-ticker deep-dive) ===",
            "Write `summary` for a smart trader who is NOT an options expert. In 4-6 sentences, "
            "plain English, no jargon dumps:",
            "  1. Translate the key numbers into meaning — IV rank/percentile (is option premium "
            "rich or cheap vs this name's own history?), VRP and IV/RV (are options overpriced vs "
            "realised movement — the premium-selling edge?), delta (rough assignment odds), "
            "RSI/regime/trend-vs-SMAs (momentum and direction), term structure and put/call skew "
            "(timing and tail pricing), days-to-earnings and ex-dividend (event/early-assignment "
            "risk). Say what each *implies*, don't just restate the number; skip any that aren't "
            "shown.",
            "  2. Read the backdrop: the VIX regime, the MACRO BACKDROP (VIX term structure — "
            "backwardation means near-term risk is priced above 3-month, so premium that looks "
            "rich may be fairly priced for a real event; the 10-year level and its 5-day move; the "
            "SPY tape; broad-market headline tone) and the SECTOR & MARKET BACKDROP — is the "
            "sector leading or lagging, is the name out/under-performing it, what does all of it "
            "imply for selling premium here right now?",
            "  3. Address the IDEAL STRIKE / IDEAL CREDIT lines directly. They are computed "
            "deterministically from support/resistance, the expected move, earnings timing and "
            "Black-Scholes fair value at *realised* vol — treat them as the reference, not as a "
            "suggestion to re-derive. If the offered strike sits OUTSIDE the zone or the offered "
            "credit is BELOW the ideal, say plainly what that costs the seller (less cushion, or "
            "no variance-risk premium for the risk taken) and whether the rest of the setup "
            "justifies it anyway. If both are comfortably met, say so — that is the strongest "
            "single argument for the trade.",
            "  4. Factor in the SENTIMENT line if present: it blends StockTwits self-tags, recent "
            "news headlines, and (if available) Reddit into one 0-100 read. Weigh it by its sample "
            "size (msgs/hdl counts) and its 1-day change (Δ1d) — a sharp swing or a fresh headline "
            "matters more than a stale flat reading. Sentiment is MOST decision-relevant when "
            "earnings are near (see Next Earnings): bullish crowd + imminent earnings = elevated "
            "gap risk for a premium seller; treat it as event risk, not a green light.",
            "  5. Synthesize: pull it together into one clear sentiment read on the ticker and "
            "whether this is a good moment to sell premium on it — and why. If it is not, say "
            "what would have to change (a level, a credit, an IV rank) to make it one.",
            "Be specific to THIS ticker's actual numbers; never invent data not shown above. If the "
            "Sentiment line is absent, say sentiment data was unavailable rather than guessing.",
        ]
    # Task 10 fix round 1: the rubric's opening line must not claim a gate pass on the
    # single-ticker path, which can review a near-miss that failed every gate (scan.py's
    # cc_near_miss/csp_near_miss fallback) alongside — or instead of — a genuinely passed
    # candidate in the same call. Since the model can't tell which is which from the framing
    # alone, the single-ticker intro stays neutral for every candidate in that call, not just
    # the near-misses. The sell/wait/skip definitions and the evidence instruction are unchanged
    # either way.
    if single_ticker:
        rubric_intro = [
            "These candidates may not have passed every deterministic gate; judge them on the "
            'FACTS and NEWS below rather than assuming a pass. Default to "sell" only when '
            "nothing here argues against it — cite a specific FACT (F#) or NEWS item (N#):",
        ]
    else:
        rubric_intro = [
            "Every candidate below already PASSED the deterministic Rules Engine (F7). Default "
            'to "sell"',
            "unless you can cite a specific FACT (F#) or NEWS item (N#) that argues otherwise:",
        ]
    lines += [
        *summary_guide,
        "",
        "=== DECISION RUBRIC ===",
        *rubric_intro,
        "  sell — no concrete red flag inside this trade's window. Most gate-passing trades are "
        '"sell".',
        "  wait — a dated catalyst falls INSIDE this trade (earnings per F3, a scheduled event "
        "in NEWS)",
        "         that should pass first. Name it.",
        "  skip — NEWS shows a thesis-breaking development (guidance cut, fraud, delisting, M&A) "
        "that",
        "         makes being assigned undesirable. Name it.",
        'Put the F#/N# ids you relied on in "evidence". Do not restate numbers that are not in '
        "FACTS.",
        "Earnings dated AFTER expiry are NOT a risk to this trade.",
        "",
        "=== YOUR TASK ===",
        f'Review all {len(candidates)} candidates above and return {{"reviews": [ … ]}} — one '
        "object per candidate, ordered by your recommended priority (1 = best to trade first).",
        "",
        "Each object must match this exact schema:",
        "{",
        '  "candidate_id": "<string — copy from candidate ID above>",',
        '  "priority": <integer, 1 = highest>,',
        '  "recommendation": "<sell | wait | skip>",',
        '  "why_attractive": "<2-3 sentences>",',
        '  "risks": "<2-3 sentences>",',
        '  "tradeoffs": "<2-3 sentences>",',
        '  "assignment_considerations": "<2-3 sentences>",',
        '  "rolling_considerations": "<2-3 sentences or empty string>",',
        summary_schema_line,
        '  "evidence": ["<F# or N# id you relied on>", ...],',
        '  "confidence": <float 0.0-1.0>',
        "}",
        "",
        f"Candidate IDs to include (all {len(candidates)}): {candidate_ids}",
        "",
        'Return ONLY {"reviews": [ … one object per candidate … ]} — no prose, no markdown '
        "fences, no commentary.",
        "Be concise: this output is sent directly to Telegram.",
    ]

    return "\n".join(lines)
