"""Score-vs-outcome report (N22): does blended_score (and its components) predict realized P&L?

Reads the outcome ledger (closed trades only) and prints, per score band, the realized win rate
and mean P&L, plus a per-signal correlation table. Use it to decide — by hand — whether
`config/scoring_weights.yaml` should change. Read-only; no IBKR, no writes, no engine feedback.

Usage:
    source .venv/bin/activate
    python -m scripts.evaluate_scores
    python -m scripts.evaluate_scores --since 2026-05-01
    python -m scripts.evaluate_scores --json
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.claude.eval.score_metrics import score_outcome_report
from src.common.schemas import ScoreOutcomeReport
from src.storage.db import init_db


def _fmt(rep: ScoreOutcomeReport) -> str:
    lines: list[str] = []
    window = ""
    if rep.period_start or rep.period_end:
        window = f"  [{rep.period_start or '…'} → {rep.period_end or '…'}]"
    lines.append(f"Closed trades scored: {rep.n_closed}{window}")
    if rep.n_closed == 0:
        lines.extend(f"  · {n}" for n in rep.notes)
        return "\n".join(lines)

    lines.append("")
    lines.append("Blended-score band → realized outcome (monotone rise ⇒ the score is working):")
    lines.append(f"  {'band':<10}{'n':>5}{'win%':>8}{'mean P&L':>12}{'total P&L':>12}")
    for b in rep.blended_score_buckets:
        lines.append(
            f"  {b.label:<10}{b.n:>5}{b.win_rate:>7.0%}{b.mean_pnl:>12.2f}{b.total_pnl:>12.2f}"
        )

    if rep.component_buckets:
        lines.append("")
        lines.append("Per-component low/high split (high should beat low if the component helps):")
        lines.append(f"  {'component':<22}{'n':>5}{'win%':>8}{'mean P&L':>12}")
        for b in rep.component_buckets:
            lines.append(f"  {b.label:<22}{b.n:>5}{b.win_rate:>7.0%}{b.mean_pnl:>12.2f}")

    lines.append("")
    lines.append("Signal ↔ realized-P&L correlation (Pearson r; low/high-half mean P&L):")
    lines.append(f"  {'signal':<18}{'n':>5}{'r':>8}{'low½':>12}{'high½':>12}")
    for c in rep.signal_correlations:
        r = f"{c.pearson_r:+.2f}" if c.pearson_r is not None else "n/a"
        lo = f"{c.low_half_mean_pnl:.2f}" if c.low_half_mean_pnl is not None else "n/a"
        hi = f"{c.high_half_mean_pnl:.2f}" if c.high_half_mean_pnl is not None else "n/a"
        lines.append(f"  {c.signal:<18}{c.n:>5}{r:>8}{lo:>12}{hi:>12}")

    lines.append("")
    lines.extend(f"  · {n}" for n in rep.notes)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score-vs-outcome evidence report.")
    parser.add_argument("--since", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--until", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    init_db()
    report = score_outcome_report(since=args.since, until=args.until)
    if args.json:
        print(report.model_dump_json(indent=2))
        return

    print("=" * 64)
    print("SCORE-vs-OUTCOME — does blended_score predict realized P&L?")
    print("=" * 64)
    print(_fmt(report))


if __name__ == "__main__":
    main()
