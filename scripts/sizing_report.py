"""Sizing counterfactual report: did the regime limits, the leveraged-ETF ceiling, the floor lots
and Claude's size cuts pay?

``sizing_actions`` holds one row per trim, block, floor lot or Claude override. The EOD job values
each once it can (``src/claude/eval/sizing_counterfactual.py``); this prints the totals so a human
can decide, before the live cutover, whether the limits and Claude's overrides earned their keep,
and whether ``claude_cut.apply_live`` should be switched on.

Run:
    python -m scripts.sizing_report                  # every action on record
    python -m scripts.sizing_report --since 2026-10-22

Read-only: it reads the trading database and writes nothing (an absent ``sizing_actions`` table is
created empty, as every script here does through ``init_db``).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from src.claude.eval.sizing_counterfactual import summarize
from src.storage.db import init_db

_SPLITS = {"sent_smaller": "sent smaller", "never_sent": "never sent", "pushed_out": "pushed out"}


def _money(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.0f}"


def _label(key: str) -> str:
    if key == "claude_overrides":
        return "Claude's overrides"
    kind, _, split = key.partition(":")
    return f"{kind} · {_SPLITS.get(split, split)}"


def render(summary: dict[str, dict[str, float]], since: date | None) -> str:
    """The report text for a ``summarize`` result."""
    span = f"since {since}" if since else "on record"
    if not summary:
        return f"no sizing actions {span}."
    lines = [
        f"Sizing counterfactual, {span}",
        "A positive P&L is what the withheld contracts would have EARNED: the trim, block or cut cost",
        "that much (for regime_floor_lot the valued contracts are the lots let through, so positive",
        "means letting them through paid).",
        "",
        f"{'action':<44}{'rows':>6}{'valued':>8}{'exact':>7}{'lots':>6}"
        f"{'to expiry':>12}{'exit rules':>12}",
    ]
    rules_missing = 0
    claude: dict[str, float] | None = None
    for key in sorted(summary):
        b = summary[key]
        if key == "claude_overrides":
            claude = b
        count = int(b["count"])
        if "pnl_expiry" not in b:  # counted, not valued (breakout rows a covered call replaced)
            lines.append(f"{_label(key):<44}{count:>6}{'-':>8}{'-':>7}{'-':>6}{'-':>12}{'-':>12}")
            continue
        rules_missing += int(b["rules_missing"])
        lines.append(
            f"{_label(key):<44}{count:>6}{int(b['resolved']):>8}{int(b['exact']):>7}"
            f"{int(b['contracts_withheld']):>6}{_money(b['pnl_expiry']):>12}"
            f"{_money(b['pnl_rules']):>12}"
        )
    if claude is not None:
        lines += [
            "",
            f"Claude's overrides: {int(claude['applied'])} applied, "
            f"{int(claude['unapplied'])} recorded but not applied (live, paper switched off, or the "
            "breaker). Negative totals mean not following the system paid.",
        ]
    lines += [
        "",
        "How the values are made:",
        "  exact  = the contracts that did trade were closed, so the withheld ones are valued at their",
        "           realised P&L per contract (the same accounting rule as the P&L pages).",
        "  shadow = nothing traded: 'to expiry' marks the option at its expiry close; 'exit rules'",
        "           walks the daily closes, prices the option with Black-Scholes at the entry IV, and",
        "           exits at the system's own profit-take line and, for a leveraged ETF, its loss line.",
        "  Rows not yet valued (the expiry has not settled, or a lot is still open) count in 'rows'",
        "  and not in 'valued'. A row whose order never filled is shown with 0 lots withheld.",
    ]
    if rules_missing:
        lines.append(
            f"  {rules_missing} valued row(s) have no entry IV, so no exit-rule mark: their "
            "'exit rules' value is left out."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Did the sizing limits and Claude's cuts pay?")
    ap.add_argument("--since", help="first action day to include, YYYY-MM-DD (default: all)")
    args = ap.parse_args(argv)
    since = date.fromisoformat(args.since) if args.since else None
    init_db()
    print(render(summarize(since or date.min), since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
