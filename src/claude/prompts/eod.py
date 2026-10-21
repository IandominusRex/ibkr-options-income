"""Build the EOD journal prompt sent to `claude -p`.

2026-10-14 rebuild: the prompt carries the day's facts (every trade with its P&L, the
roll-policy decisions, the day's movers and what is coming before the next session), not just
totals. With totals alone the model guessed at what had happened ("likely reflects new or
rolled options"); with the facts it can interpret them.
"""

from __future__ import annotations

from src.common.schemas import EODSummary


def _money(v: float) -> str:
    return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"


def build_eod_prompt(summary: EODSummary, *, picture_block: str | None = None) -> str:
    """Return the prompt string for a narrative end-of-day journal entry.

    *picture_block* is the shared market picture, pre-rendered (``picture_context``), so the
    interpretation of the day can be set against the market it happened in."""
    lines: list[str] = [
        "You are the risk-minded strategist of an options-income book (cash-secured puts and "
        "covered calls, paper account). The reader has already seen every fact below in the "
        "report. Write 2-3 sentences of interpretation: what actually mattered today and why, "
        "and the single most important thing to watch or decide before the next session. "
        "Name tickers; do not restate dollar figures or list the trades back. If the day was "
        "quiet, one sentence is correct. Do not speculate about events not listed here.",
        "",
        "=== ACCOUNT ===",
        f"Date: {summary.date:%a %d %b %Y}",
        f"Net liquidation: ${summary.account.net_liquidation:,.0f}"
        + (f" ({_money(summary.nlv_change)} today)" if summary.nlv_change is not None else ""),
        f"Unrealised P&L: {_money(summary.unrealized_pnl)}"
        + (
            f" ({_money(summary.unrealized_pnl_delta)} since {summary.baseline_date:%a %d %b})"
            if summary.baseline_date is not None
            else ""
        ),
        f"Premium cashflow today: {_money(summary.realized_pnl)} (credits − debits)",
        f"Open positions: {summary.open_positions} · net delta {summary.net_delta_exposure:+,.0f} "
        "share-equivalents",
        "",
        "=== TODAY'S TRADES ===",
    ]
    if summary.trades:
        for t in summary.trades:
            bits = [t.action, t.label, f"×{t.contracts}"]
            if t.price is not None:
                bits.append(f"@ {t.price:.2f}")
            if t.reason:
                bits.append(f"({t.reason})")
            if t.pnl is not None:
                bits.append(f"P&L {_money(t.pnl)}")
            lines.append("- " + " ".join(bits))
    else:
        lines.append("- none")

    if picture_block:
        lines += ["", picture_block]

    lines.append("")
    lines.append("=== ROLL-POLICY DECISIONS (deterministic rules, already acted on) ===")
    if summary.decisions:
        for d in summary.decisions:
            lines.append(
                f"- {d.label}: {d.action} ({d.reason}){' — ' + d.detail if d.detail else ''}"
            )
    else:
        lines.append("- none")

    if summary.mover_pnl:
        lines += ["", "=== BIGGEST UNREALISED MOVES TODAY (by underlying) ==="]
        lines += [f"- {sym}: {_money(v)}" for sym, v in summary.mover_pnl.items()]

    lines += ["", "=== BEFORE THE NEXT SESSION ==="]
    if summary.watch:
        lines += [f"- [{w.kind}] {w.text}" for w in summary.watch]
    else:
        lines.append("- nothing scheduled; no shorts in the money or expiring this week")

    lines += [
        "",
        "Return a single JSON object — no prose, no markdown fences.",
        'Schema: {"narrative": "<2-3 sentences>"}',
        "Return ONLY the JSON object.",
    ]
    return "\n".join(lines)
