"""Score-vs-outcome analysis (N22): does the blended score (and its components) predict P&L?

The scoring model (`src/engine/scoring.py` + `config/scoring_weights.yaml`) is unvalidated: the
blend is effectively IV-rank + liquidity, and nothing has ever linked `blended_score` to realized
outcomes — even though the verdict ledger stores exactly that. This module reads the closed ledger
rows and reports, per score band, the realized win rate and mean P&L, plus a per-signal correlation.

Strictly read-only enrichment analysis. It informs whether the **human-edited** scoring weights
should change; it never feeds the engine, scoring, or sizing (the fence). Lives under `eval/` and
imports only the ledger + schemas, same as `metrics.py`.
"""

from __future__ import annotations

import math
from datetime import date

from src.claude.eval.ledger import load_records
from src.common.schemas import (
    ScoreBucket,
    ScoreOutcomeReport,
    SignalCorrelation,
    VerdictRecord,
)

# blended_score bands (0–100). A monotone rise in win-rate/mean-P&L across these is the signal
# that the score is doing real work.
_SCORE_BANDS: list[tuple[float, float]] = [(0, 60), (60, 70), (70, 80), (80, 90), (90, 100.01)]

# Per-component scorecard signals (keys under signals["scores"]) to bucket/ correlate.
_COMPONENTS = ("iv", "technical", "fundamental", "liquidity", "assignment_safety", "sentiment")
# Top-level signals worth correlating against P&L directly.
_TOP_SIGNALS = ("blended_score", "iv_rank", "delta", "vrp", "prob_otm", "roc_pct")


def _closed(records: list[VerdictRecord]) -> list[VerdictRecord]:
    return [r for r in records if r.realized_pnl is not None and r.filled]


def _bucket(label: str, trades: list[VerdictRecord]) -> ScoreBucket:
    n = len(trades)
    if n == 0:
        return ScoreBucket(label=label, n=0, win_rate=0.0, mean_pnl=0.0, total_pnl=0.0)
    total = sum(r.realized_pnl or 0.0 for r in trades)
    wins = sum(1 for r in trades if (r.realized_pnl or 0.0) > 0)
    return ScoreBucket(
        label=label,
        n=n,
        win_rate=round(wins / n, 4),
        mean_pnl=round(total / n, 2),
        total_pnl=round(total, 2),
    )


def _signal_value(rec: VerdictRecord, key: str) -> float | None:
    """Pull a numeric signal from the frozen vector. Component scores live under `scores`."""
    sig = rec.signals or {}
    if key in _COMPONENTS:
        val = (sig.get("scores") or {}).get(key)
    else:
        val = sig.get(key)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation; None when undefined (n<2 or zero variance)."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return round(sxy / math.sqrt(sxx * syy), 4)


def _correlate(trades: list[VerdictRecord], key: str) -> SignalCorrelation:
    pairs = [
        (v, r.realized_pnl)
        for r in trades
        if (v := _signal_value(r, key)) is not None and r.realized_pnl is not None
    ]
    n = len(pairs)
    if n == 0:
        return SignalCorrelation(signal=key, n=0)
    xs = [p[0] for p in pairs]
    ys = [float(p[1]) for p in pairs]
    pearson = _pearson(xs, ys)

    # Low/high split on the signal's median — robust contrast that doesn't assume linearity.
    order = sorted(range(n), key=lambda i: xs[i])
    half = n // 2
    low_idx, high_idx = order[:half], order[n - half :]
    low_mean = round(sum(ys[i] for i in low_idx) / len(low_idx), 2) if low_idx else None
    high_mean = round(sum(ys[i] for i in high_idx) / len(high_idx), 2) if high_idx else None
    return SignalCorrelation(
        signal=key,
        n=n,
        pearson_r=pearson,
        low_half_mean_pnl=low_mean,
        high_half_mean_pnl=high_mean,
    )


def score_outcome_report(
    records: list[VerdictRecord] | None = None,
    *,
    since: date | None = None,
    until: date | None = None,
) -> ScoreOutcomeReport:
    """Build the score-vs-outcome report over closed ledger rows (optionally windowed)."""
    if records is None:
        records = load_records(closed_only=True)
    closed = _closed(records)
    if since is not None:
        closed = [r for r in closed if r.outcome_date and r.outcome_date >= since]
    if until is not None:
        closed = [r for r in closed if r.outcome_date and r.outcome_date <= until]

    notes = [
        "Closed (executed+settled) trades only — rejected/unfilled candidates carry no P&L.",
        "Read-only: re-derive scoring_weights.yaml from this evidence by hand (the fence "
        "forbids any automatic feedback into the engine).",
    ]
    if not closed:
        notes.append("No closed trades in window — nothing to correlate yet.")
        return ScoreOutcomeReport(n_closed=0, period_start=since, period_end=until, notes=notes)

    # Blended-score bands.
    blended_buckets: list[ScoreBucket] = []
    for lo, hi in _SCORE_BANDS:
        band = [
            r
            for r in closed
            if (v := _signal_value(r, "blended_score")) is not None and lo <= v < hi
        ]
        if band:
            blended_buckets.append(_bucket(f"{int(lo)}-{int(min(hi, 100))}", band))

    # One coarse high/low bucket per component (median split) so a weak component is visible.
    component_buckets: list[ScoreBucket] = []
    for comp in _COMPONENTS:
        valued = [(v, r) for r in closed if (v := _signal_value(r, comp)) is not None]
        if len(valued) < 2:
            continue
        valued.sort(key=lambda t: t[0])
        half = len(valued) // 2
        low = [r for _, r in valued[:half]]
        high = [r for _, r in valued[len(valued) - half :]]
        component_buckets.append(_bucket(f"{comp}:low", low))
        component_buckets.append(_bucket(f"{comp}:high", high))

    correlations = [_correlate(closed, key) for key in (*_TOP_SIGNALS, *_COMPONENTS)]

    dates = [r.outcome_date for r in closed if r.outcome_date]
    return ScoreOutcomeReport(
        n_closed=len(closed),
        period_start=since or (min(dates) if dates else None),
        period_end=until or (max(dates) if dates else None),
        blended_score_buckets=blended_buckets,
        component_buckets=component_buckets,
        signal_correlations=correlations,
        notes=notes,
    )
