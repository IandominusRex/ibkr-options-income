"""Build the prompt string sent to `claude -p` for candidate review."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.common.schemas import AccountSnapshot, MarketConditions, TradeCandidate

if TYPE_CHECKING:
    from src.storage.models import ClaudeMemoryRow

# Compact universe knowledge injected into every review prompt.
# Full research with sources lives in UNIVERSE_RESEARCH.md at the project root.
_UNIVERSE_CONTEXT = """
=== UNIVERSE CONTEXT (ticker knowledge — use when writing risks/tradeoffs) ===

⚠ PRICES & IV RANKS BELOW WERE RESEARCHED Jun-2026 AND ARE STALE. They are coarse anchors for
qualitative judgement (tier, liquidity, CC-vs-CSP suitability, structural risks) ONLY. For any
current price level, use the SCAN-TIME SPOT PRICES block — never quote these figures as live.

TIER 1 — Core income (fund-manager grade, stable assignment):
  SPY  ~$540  IVR 15-35  CC+CSP  0.8-2.5%/mo   index; ETF, no earnings risk
  QQQ  ~$470  IVR 18-40  CC+CSP  1.0-2.5%/mo   index; tech-heavy
  IWM  ~$200  IVR 20-45  CC+CSP  1.5-3.0%/mo   small-cap index
  SMH  ~$220  IVR 28-55  CC+CSP  2.0-4.0%/mo   semi sector ETF; diversified
  GLD  ~$250  IVR 14-28  CC+CSP  0.8-1.5%/mo   gold; decorrelates from equity
  AAPL ~$211  IVR 18-40  CC+CSP  0.8-1.2%/mo   most liquid chain; low IV
  MSFT ~$413  IVR 15-35  CC+CSP  0.7-1.0%/mo   structurally low IV (~7-8% avg)
  GOOGL~$165  IVR 22-45  CC+CSP  1.0-2.0%/mo   diversified revenue
  JPM  ~$280  IVR 20-40  CC+CSP  1.0-2.0%/mo   financials; dividend payer
  V    ~$324  IVR 12-28  CC+CSP  0.6-1.0%/mo   payments moat; LOW IV, ~$32k collateral
  MA   ~$488  IVR 12-28  CC+CSP  0.6-1.0%/mo   payments moat; LOW IV, ~$49k collateral
  WMT  ~$120  IVR 14-30  CC+CSP  0.7-1.2%/mo   defensive staple; liquid chain
  HD   ~$327  IVR 16-32  CC+CSP  0.8-1.4%/mo   quality retail
  COST ~$975  IVR 12-26  CC*     low           *CC-focused: ~$97k CSP collateral/contract
  LLY  ~$1150 IVR 18-34  CC*     low           *CC-focused: ~$115k CSP collateral/contract; pharma trial risk

DIVERSIFIER ETFs (broaden away from the tech/crypto tilt; defensives are LOW-IV → few signals):
  XLF  ~$52   financials sector; liquid, moderate IV
  XLK  ~$255  tech sector (adds to the tech cap)
  XLE  ~$90   energy; commodity-linked decorrelation, moderate-high IV
  XLV  ~$154  healthcare; defensive, low IV
  XLP  ~$85   consumer staples; very low IV — rarely clears the IV gate
  XLU  ~$44   utilities; rate-sensitive defensive, low IV
  XLI  ~$176  industrials; cyclical, low-moderate IV
  TLT  ~$86   long Treasuries; very low IV — hedge sleeve, few signals
  SLV  ~$60   silver; higher IV than GLD, commodity diversifier

TIER 2 — Active income (elevated IV, real fundamentals):
  TSLA ~$395  IVR 40-70  CC+CSP  2.5-5.0%/mo   deepest single-stock liquidity after AAPL; high premium
  NVDA ~$224  IVR 32-64  CC+CSP  2.0-4.0%/mo   AI leader; IV compressed from 50%+ highs
  AMZN ~$205  IVR 25-45  CC+CSP  1.5-3.0%/mo   AWS + retail + ads
  AMD  ~$130  IVR 35-65  CC+CSP  2.0-4.0%/mo   popular wheel; NVDA competition narrative keeps IV up
  META ~$640  IVR 28-55  CC+CSP  2.0-4.0%/mo   strong FCF since 2023; large CSP collateral
  PLTR ~$158  IVR 47     CC+CSP  3.0-5.0%/mo   AI/defence; IV rank 46.73 verified Jun-2026
  SOFI ~$18   IVR 27     CC+CSP  3.0-6.0%/mo   IVR currently ~27 (below ideal 30+); up 32% YTD
  HOOD ~$90   IVR 45-80  CC+CSP  3.0-6.0%/mo   retail brokerage; crypto-correlated IV
  HIMS ~$35   IVR 55-90  CC+CSP  4.0-8.0%/mo   telehealth; ±16% earnings move; FDA binary risk
  BABA ~$133  IVR 35-55  CC+CSP* 2.0-4.0%/mo   *ADR delisting/geopolitical risk — size small

TIER 3 — Speculative / CC-only leveraged ETFs (NEVER CSP):
  SOXL ~$25   IV 80-140% CC ONLY 182-534% ann  3× semi; -85% in 2022; NAV decay trap on assignment
  LABU ~$20   IV 90-160% CC ONLY extreme       3× biotech + FDA binary risk; never assign
  TSLL ~$15   IV 90-130% CC ONLY very high     2× TSLA; affordable entry; leverage decay
  DPST ~$120  IV 70-110% CC ONLY high          3× regional banks; thin liquidity; verify OI

TIER 3 — Speculative stocks (in would_own with hard position limits):
  MARA ~$15   IV 90-130% CC+CSP* 6-12%/mo     *BTC proxy; can lose 70%+ in bear cycle
  RGTI ~$10   IV ~86%    CC+CSP* speculative   *quantum computing; IVR 9.52% (LOW) — wait for IVR>40
  CRCL ~$113  IV ~173%   CC ONLY              IPO 2025; -57% from ATH; thin liquidity; not in would_own
  COIN ~$162  IV 60-100% CC+CSP* high          *liquid crypto-equity; cleaner than miners; crypto gap risk
  MSTR ~$125  IV 80-130% CC ONLY very high     leveraged-BTC proxy; not in would_own
  RKLB ~$25   IV 70-110% CC+CSP* speculative   *space launch; pre-profit; cap sizing
  ASTS ~$40   IV 80-120% CC ONLY speculative   satellite comms; pre-revenue; not in would_own
  IONQ ~$40   IV 80-120% CC ONLY speculative   quantum (same thesis as RGTI); not in would_own

KEY RULES FOR REVIEW:
- Flag any candidate with IVR < 30 as "thin premium environment"
- Ideal sell zone: IVR ≥ 50 (TastyTrade standard); IVR 30-49 = acceptable
- AAPL/MSFT premiums rarely exceed 1.2%/month — sanity-check yield claims
- Defensive names (V/MA/COST/LLY and XLP/XLU/XLV/TLT) are LOW-IV — expect few signals; never inflate yield claims for them
- COST (~$975) / LLY (~$1,150) are CC-focused: one CSP contract locks ~$100k+ collateral
- Crypto cluster (COIN/MSTR/MARA/CRCL/BITO) is all BTC-correlated — treat as one bet for concentration
- Leveraged ETFs: every review must note "CC-only; assignment risk is NAV decay"
- BABA: every review must note ADR/geopolitical risk
- MARA/RGTI/RKLB and other Tier-3 names: every review must note speculative nature and cap sizing reminder
- HIMS: flag FDA calendar risk near any earnings or regulatory announcement date
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


def _active_skills_block() -> str:
    """Render the human-promoted reasoning skills for prompt injection.

    Gated by config (`claude.skills_enabled`) and fail-soft: any error → empty string, so a
    bad skill file can never break a review. This is the sole injection point for skills.
    """
    from src.common.config import get_config

    if not get_config().claude.skills_enabled:
        return ""
    try:
        from src.claude.skills.registry import render_active_skills

        return render_active_skills()
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


def _vix_context(vix: float | None) -> str:
    """One-line macro-vol regime hint derived from the VIX level."""
    if vix is None:
        return "VIX: unavailable"
    if vix < 15:
        regime = "calm — premiums thin; be selective, favour higher IV-rank names"
    elif vix < 20:
        regime = "normal"
    elif vix < 30:
        regime = "elevated — richer premium but wider moves; mind assignment risk"
    else:
        regime = "stressed — premium is rich but tail risk is high; size down"
    return f"VIX: {vix:.1f} ({regime})"


def build_prompt(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    history: list[ClaudeMemoryRow] | None = None,
    market_conditions: MarketConditions | None = None,
    spot_prices: dict[str, float] | None = None,
) -> str:
    """Build the full prompt string sent to claude -p.

    Returns an empty string if there are no candidates (caller skips subprocess).
    history: optional list of ClaudeMemoryRow from prior scans for learning injection.
    market_conditions: optional macro snapshot (VIX) so the reasoning layer can weigh the
        vol regime. Enrichment only — it never changes the deterministic gates.
    spot_prices: optional scan-time {symbol: spot} so Claude reasons from current levels
        rather than the stale Jun-2026 anchors baked into the static universe block (N17).
    """
    if not candidates:
        return ""

    vix = market_conditions.vix if market_conditions else None
    lines: list[str] = [
        "You are a disciplined options income strategist reviewing proposed covered call (CC) "
        "and cash-secured put (CSP) trades for an Interactive Brokers account.",
        "",
        "These candidates have already been approved by the deterministic Rules Engine. "
        "Your role is enrichment only: re-rank by priority and explain the risks, tradeoffs, "
        "and assignment considerations so the trader can make an informed final decision. "
        "You cannot place, size, or block orders.",
        "",
        _UNIVERSE_CONTEXT,
        "",
    ]

    # Scan-time spot prices override the stale static anchors (N17).
    lines += _spot_prices_block(candidates, spot_prices)

    # Human-promoted reasoning skills (verdict + ranking only — never gates). Enrichment, and
    # the only path a skill reaches Claude; the engine never sees this text.
    skills_block = _active_skills_block()
    if skills_block:
        lines += [skills_block, ""]

    lines += [
        "=== MARKET CONTEXT ===",
        _vix_context(vix),
        "",
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
        lines.append(f"Rationale Tags:   {', '.join(c.rationale_tags) or 'none'}")
        lines.append(
            f"ScoreCard:        IV={c.scores.iv_score:.0f}  Tech={c.scores.technical_score:.0f}  "
            f"Fund={c.scores.fundamental_score:.0f}  Liq={c.scores.liquidity_score:.0f}  "
            f"AsnRisk={c.scores.assignment_safety_score:.0f}"
        )

    candidate_ids = [c.candidate_id for c in candidates]
    lines += [
        "",
        "=== YOUR TASK ===",
        f"Review all {len(candidates)} candidates above and return a JSON array — one object per "
        "candidate — ordered by your recommended priority (1 = best to trade first).",
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
        '  "confidence": <float 0.0-1.0>',
        "}",
        "",
        f"Candidate IDs to include (all {len(candidates)}): {candidate_ids}",
        "",
        "Return ONLY the JSON array — no prose, no markdown fences, no commentary.",
        "Be concise: this output is sent directly to Telegram.",
    ]

    return "\n".join(lines)
