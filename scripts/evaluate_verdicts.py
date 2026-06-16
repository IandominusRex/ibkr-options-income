"""Score Claude's verdicts: calibration + EV vs the deterministic baseline.

Reads the outcome ledger (closed trades only) and prints a held-out evaluation plus a
per-month breakdown. Read-only; no IBKR, no writes.

Usage:
    source .venv/bin/activate
    python -m scripts.evaluate_verdicts
    python -m scripts.evaluate_verdicts --since 2026-05-01   # held-out tail only
    python -m scripts.evaluate_verdicts --json               # machine-readable
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.claude.eval.metrics import evaluate, evaluate_by_period
from src.common.schemas import VerdictEvaluation
from src.storage.db import init_db


def _fmt(ev: VerdictEvaluation) -> str:
    lines: list[str] = []
    window = ""
    if ev.period_start or ev.period_end:
        window = f"  [{ev.period_start or '…'} → {ev.period_end or '…'}]"
    lines.append(f"Closed trades scored: {ev.n_closed}{window}")
    if ev.n_closed == 0:
        lines.extend(f"  · {n}" for n in ev.notes)
        return "\n".join(lines)

    brier = f"{ev.brier_score:.4f}" if ev.brier_score is not None else "n/a"
    lines.append(f"Brier score (lower = better calibrated): {brier}")
    if ev.calibration:
        lines.append("Calibration (confidence band → realized win rate):")
        for b in ev.calibration:
            bar = "█" * round(b.win_rate * 20)
            lines.append(
                f"  {b.lower:.1f}-{b.upper:.1f}  n={b.n:<3}  "
                f"conf≈{b.mean_confidence:.2f}  win={b.win_rate:.0%}  {bar}"
            )

    b, c = ev.baseline, ev.follow_claude
    lines.append("")
    lines.append(f"{'Policy':<16}{'trades':>8}{'win%':>8}{'mean P&L':>12}{'total P&L':>12}")
    for p in (b, c):
        lines.append(
            f"{p.label:<16}{p.n_trades:>8}{p.win_rate:>7.0%}{p.mean_pnl:>12.2f}{p.total_pnl:>12.2f}"
        )
    if ev.edge_per_trade is not None:
        verdict = "Claude adds edge" if ev.edge_per_trade > 0 else "no edge from Claude"
        lines.append(
            f"Edge per trade (follow_claude − baseline): {ev.edge_per_trade:+.2f}  → {verdict}"
        )
    if ev.agreement_rate is not None:
        lines.append(f"Claude/baseline agreement: {ev.agreement_rate:.0%}")
    lines.append("")
    lines.extend(f"  · {n}" for n in ev.notes)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Claude verdicts.")
    parser.add_argument("--since", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--until", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args()

    init_db()
    overall = evaluate(since=args.since, until=args.until)

    if args.json:
        print(overall.model_dump_json(indent=2))
        return

    print("=" * 64)
    print("VERDICT EVALUATION — calibration + EV vs deterministic baseline")
    print("=" * 64)
    print(_fmt(overall))
    print()
    print("Per-month (so one lucky stretch can't carry the score):")
    by_period = evaluate_by_period()
    if not by_period:
        print("  (no closed trades yet)")
    for month, ev in by_period:
        edge = f"{ev.edge_per_trade:+.2f}" if ev.edge_per_trade is not None else "n/a"
        brier = f"{ev.brier_score:.3f}" if ev.brier_score is not None else "n/a"
        print(f"  {month}:  n={ev.n_closed:<3}  edge/trade={edge:>8}  brier={brier}")


if __name__ == "__main__":
    main()
