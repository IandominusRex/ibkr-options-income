"""Build the prompt string sent to `claude -p` for candidate review."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.common.schemas import AccountSnapshot, TradeCandidate

if TYPE_CHECKING:
    from src.storage.models import ClaudeMemoryRow


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


def build_prompt(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    history: list[ClaudeMemoryRow] | None = None,
) -> str:
    """Build the full prompt string sent to claude -p.

    Returns an empty string if there are no candidates (caller skips subprocess).
    history: optional list of ClaudeMemoryRow from prior scans for learning injection.
    """
    if not candidates:
        return ""

    lines: list[str] = [
        "You are a disciplined options income strategist reviewing proposed covered call (CC) "
        "and cash-secured put (CSP) trades for an Interactive Brokers account.",
        "",
        "These candidates have already been approved by the deterministic Rules Engine. "
        "Your role is enrichment only: re-rank by priority and explain the risks, tradeoffs, "
        "and assignment considerations so the trader can make an informed final decision. "
        "You cannot place, size, or block orders.",
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
        if c.prob_profit is not None:
            lines.append(f"Prob. Profit:     {c.prob_profit:.1%}")
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
