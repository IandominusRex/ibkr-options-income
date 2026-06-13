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
        "Write a concise 3-4 sentence narrative summarizing today's performance, "
        "what changed in the portfolio, and any notable observations for tomorrow.",
        "",
        "=== EOD JOURNAL REQUEST ===",
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
        "Write a 3-4 sentence journal entry. Be specific about numbers. "
        "Note what worked, what changed, and one actionable observation for tomorrow.",
        "Return a single JSON object — no prose, no markdown fences.",
        "",
        'Schema: {"narrative": "<3-4 sentence journal text>"}',
        "",
        "Return ONLY the JSON object.",
    ]

    return "\n".join(lines)
