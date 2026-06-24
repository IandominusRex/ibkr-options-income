"""Build the EOD journal prompt sent to `claude -p`."""

from __future__ import annotations

from src.common.schemas import EODSummary


def _sign(v: float) -> str:
    return f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"


def _delta_sign(v: float) -> str:
    return f"Δ +${v:.2f}" if v >= 0 else f"Δ -${abs(v):.2f}"


def build_eod_prompt(summary: EODSummary) -> str:
    """Return the prompt string for a narrative end-of-day journal entry."""
    lines: list[str] = [
        "You are a disciplined options income strategist keeping a trading journal. "
        "The figures below are ALREADY shown to the reader in a stats block — do NOT restate them. "
        "Write a concise 1-3 sentence interpretation: explain what changed and *why*, flag anything "
        "that needs attention, and give one concrete action for tomorrow. If nothing material "
        "happened (no fills, no notable move, static positions), say so in a single short sentence "
        "rather than padding.",
        "",
        "=== EOD JOURNAL REQUEST (context — do not parrot these numbers back) ===",
        f"Date:                  {summary.date}",
        f"Premium cashflow today:{_sign(summary.realized_pnl)} (option credits − debits; "
        "NOT a paired realized P&L — assignment stock-leg P&L is excluded)",
        f"Unrealized P&L:        {_sign(summary.unrealized_pnl)} ({_delta_sign(summary.unrealized_pnl_delta)} vs yesterday)",
        f"Fills today:           {summary.fills_today}",
        f"Open positions:        {summary.open_positions}",
        f"Net delta exposure:    {summary.net_delta_exposure:.2f} (effective shares equivalent)",
        f"Account NLV:           ${summary.account.net_liquidation:.2f}",
        f"Buying power:          ${summary.account.buying_power:.2f}",
    ]

    if summary.top_movers:
        lines.append(f"Top movers:            {', '.join(summary.top_movers)}")

    if summary.tomorrow_watchlist:
        lines.append(f"Tomorrow's watchlist:  {', '.join(summary.tomorrow_watchlist)}")

    lines += [
        "",
        "=== YOUR TASK ===",
        "Write a 1-3 sentence journal entry of interpretation, not a recap. Do not repeat the "
        "figures above — the reader already sees them. Explain what drove the move, what changed, "
        "and one actionable observation for tomorrow. On a quiet day, one sentence is correct.",
        "Return a single JSON object — no prose, no markdown fences.",
        "",
        'Schema: {"narrative": "<3-4 sentence journal text>"}',
        "",
        "Return ONLY the JSON object.",
    ]

    return "\n".join(lines)
