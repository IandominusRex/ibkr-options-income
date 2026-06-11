"""Verdict scoring — calibration + expected value, on held-out periods.

The thing being measured is *the verdict, not the last trade*. Two questions:

1. Calibration. When Claude says it is 0.8 confident, do ~80% of those trades actually win?
   A reliability curve (`CalibrationBucket`) plus a Brier score answer this. A model that wins
   its last trade but is systematically over-confident is worse than a humbler, well-calibrated
   one — calibration is what survives a regime change; a single P&L number does not.

2. Expected value vs the deterministic baseline. The baseline trades the whole engine slate;
   "follow Claude" trades only the slate entries Claude tagged `sell`. If Claude's filter lifts
   mean realized P&L per trade (`edge_per_trade > 0`), the reasoning layer is adding value —
   if not, it is noise dressed as insight.

Honesty caveat baked into every report: only *executed and settled* trades have a realized
outcome. Candidates that were rejected or never filled have no counterfactual P&L, so the EV
comparison is conditioned on trades that happened. Always evaluate a held-out window (and the
per-period breakdown) so the score is not dominated by one lucky stretch.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from src.claude.eval.ledger import load_records
from src.common.schemas import (
    CalibrationBucket,
    PolicyStats,
    VerdictEvaluation,
    VerdictRecord,
)

# Reliability-curve confidence bands.
_BANDS: list[tuple[float, float]] = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]


def _is_win(rec: VerdictRecord) -> bool:
    return rec.realized_pnl is not None and rec.realized_pnl > 0


def _closed(records: list[VerdictRecord]) -> list[VerdictRecord]:
    """Executed-and-settled rows: a realized P&L exists to score."""
    return [r for r in records if r.realized_pnl is not None and r.filled]


def _policy_stats(label: str, trades: list[VerdictRecord]) -> PolicyStats:
    n = len(trades)
    if n == 0:
        return PolicyStats(label=label, n_trades=0, win_rate=0.0, mean_pnl=0.0, total_pnl=0.0)
    total = sum(r.realized_pnl or 0.0 for r in trades)
    wins = sum(1 for r in trades if _is_win(r))
    return PolicyStats(
        label=label,
        n_trades=n,
        win_rate=round(wins / n, 4),
        mean_pnl=round(total / n, 2),
        total_pnl=round(total, 2),
    )


def _calibration(records: list[VerdictRecord]) -> tuple[list[CalibrationBucket], float | None]:
    """Reliability buckets + Brier score over rows that carry a confidence."""
    scored = [r for r in records if r.claude_confidence is not None]
    if not scored:
        return [], None

    sq_error = 0.0
    for r in scored:
        conf = r.claude_confidence or 0.0
        sq_error += (conf - (1.0 if _is_win(r) else 0.0)) ** 2
    brier = sq_error / len(scored)

    buckets: list[CalibrationBucket] = []
    for lo, hi in _BANDS:
        band = [r for r in scored if lo <= (r.claude_confidence or 0.0) < hi]
        if not band:
            continue
        n = len(band)
        mean_conf = sum(r.claude_confidence or 0.0 for r in band) / n
        win_rate = sum(1 for r in band if _is_win(r)) / n
        buckets.append(
            CalibrationBucket(
                lower=lo,
                upper=min(hi, 1.0),
                n=n,
                mean_confidence=round(mean_conf, 4),
                win_rate=round(win_rate, 4),
            )
        )
    return buckets, round(brier, 4)


def evaluate(
    records: list[VerdictRecord] | None = None,
    *,
    since: date | None = None,
    until: date | None = None,
) -> VerdictEvaluation:
    """Score verdicts over a (optionally held-out) window.

    Args:
        records: pre-loaded records; if None, loads closed rows from the ledger.
        since/until: restrict to trades whose outcome settled within the window — pass a
            `since` cutoff to score only the held-out tail the skill loop never trained on.
    """
    if records is None:
        records = load_records(closed_only=True)

    closed = _closed(records)
    if since is not None:
        closed = [r for r in closed if r.outcome_date and r.outcome_date >= since]
    if until is not None:
        closed = [r for r in closed if r.outcome_date and r.outcome_date <= until]

    notes: list[str] = [
        "EV is conditioned on executed+settled trades; rejected/unfilled candidates carry no "
        "realized P&L.",
    ]

    if not closed:
        notes.append("No closed trades in window — score is empty, not zero-skill.")
        return VerdictEvaluation(
            n_closed=0,
            period_start=since,
            period_end=until,
            brier_score=None,
            calibration=[],
            follow_claude=_policy_stats("follow_claude", []),
            baseline=_policy_stats("baseline", []),
            edge_per_trade=None,
            agreement_rate=None,
            notes=notes,
        )

    dates = [r.outcome_date for r in closed if r.outcome_date]
    baseline_trades = [r for r in closed if r.baseline_recommendation == "sell"]
    claude_trades = [r for r in closed if r.claude_recommendation == "sell"]

    baseline_stats = _policy_stats("baseline", baseline_trades)
    claude_stats = _policy_stats("follow_claude", claude_trades)
    edge = (
        round(claude_stats.mean_pnl - baseline_stats.mean_pnl, 2)
        if claude_trades and baseline_trades
        else None
    )

    agreements = [r for r in closed if r.agreement is not None]
    agreement_rate = (
        round(sum(1 for r in agreements if r.agreement) / len(agreements), 4)
        if agreements
        else None
    )

    calibration, brier = _calibration(closed)
    if claude_trades and len(claude_trades) < len(closed):
        notes.append(
            f"Claude traded {len(claude_trades)}/{len(closed)} of the baseline slate "
            "(its skips are the value test)."
        )

    return VerdictEvaluation(
        n_closed=len(closed),
        period_start=since or (min(dates) if dates else None),
        period_end=until or (max(dates) if dates else None),
        brier_score=brier,
        calibration=calibration,
        follow_claude=claude_stats,
        baseline=baseline_stats,
        edge_per_trade=edge,
        agreement_rate=agreement_rate,
        notes=notes,
    )


def evaluate_by_period(
    records: list[VerdictRecord] | None = None,
) -> list[tuple[str, VerdictEvaluation]]:
    """Per-month evaluations (YYYY-MM, ascending) so a single lucky stretch can't dominate."""
    if records is None:
        records = load_records(closed_only=True)
    closed = _closed(records)

    by_month: dict[str, list[VerdictRecord]] = defaultdict(list)
    for r in closed:
        if r.outcome_date:
            by_month[r.outcome_date.strftime("%Y-%m")].append(r)

    return [(month, evaluate(by_month[month])) for month in sorted(by_month)]
