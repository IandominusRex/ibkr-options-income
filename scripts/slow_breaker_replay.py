"""Pick the slow drawdown breaker's threshold by replay (risk-envelope plan Task 28; spec §3.4.5, ruling E14).

    python -m scripts.slow_breaker_replay [--db PATH] [--since DATE] [--dry-run]

Reads the trading database **read-only**. Two net-liquidation series are measured the way the breaker
measures them (``execution/circuit_breakers._slow_raw``: the fall from the highest NLV of the trailing
``envelope.slow_breaker.window_sessions`` (20) sessions):

* the **real** series: the last ``portfolio_snapshots`` reading of each day, which carries the
  Oct-Nov 2026 slide;
* the **synthetic** series: the 2026-11-12 book (today's composition) facing the ``price_history``
  panel's real daily returns (the survivability harness's status-quo path, without the spreads
  book's worst-case month), which carries the panel's first 12 months.

**E14:** the threshold is the lowest of {8, 10, 12, 15}% that **trips in the Oct-Nov 2026 slide** (a
session whose drawdown reaches it, on the real series; the synthetic one stands in when the real
series is too short to cover the slide) and has **at most 2 trip episodes in the panel's first 12
months** (on the synthetic series; an episode is a session at or over the threshold after one under
it); if none qualifies, 15. Writes ``data/envelope_reports/E14.json`` (``switch="slow_breaker"``,
``value_on_pass`` the threshold) and ``E14_report.txt``: the EOD run applies it (paper only; a
threshold you set by hand is never overwritten). Nothing readable, nothing written.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.common.config import get_envelope_cfg
from src.common.schemas import EnvelopeReportResult
from src.reporting import survivability as sv
from src.reporting.replay import (
    drawdown_series,
    load_book_context,
    load_nlv_series,
    make_result,
    open_ro,
    trading_db_path,
    verdict_word,
    write_report,
    write_result,
)

THRESHOLDS = (8, 10, 12, 15)
FALLBACK = 15
SLIDE = (date(2026, 10, 1), date(2026, 11, 30))
MAX_EPISODES = 2
FIRST_MONTHS_DAYS = 365
MIN_SLIDE_SESSIONS = 5  # a real series shorter than this inside the slide is not evidence
CRITERION = (
    "E14: the lowest of {8, 10, 12, 15}% drawdown from the 20-session NLV high that trips in the Oct-Nov 2026 "
    "slide and has <= 2 trip episodes in the panel's first 12 months; if none qualifies, 15%"
)

Series = list[tuple[date, float]]


@dataclass(frozen=True)
class Row:
    threshold: int
    trips_in_slide: bool
    episodes: int
    qualifies: bool


@dataclass(frozen=True)
class Choice:
    value: str
    rows: list[Row]
    slide_basis: str  # "real" | "synthetic"
    fell_back: bool
    slide_peak_pct: float
    first_year_peak_pct: float


def episodes(dd: list[float], threshold: float) -> int:
    """Trip episodes in a drawdown series: sessions at or over *threshold* after one under it (a
    first session already over it counts)."""
    count, over = 0, False
    for v in dd:
        if v >= threshold and not over:
            count += 1
        over = v >= threshold
    return count


def _dd(series: Series, window: int) -> list[tuple[date, float]]:
    return list(
        zip((d for d, _ in series), drawdown_series([v for _, v in series], window), strict=True)
    )


def choose_threshold(
    real: Series,
    synthetic: Series,
    *,
    window: int = 20,
    slide: tuple[date, date] = SLIDE,
    first_days: int = FIRST_MONTHS_DAYS,
) -> Choice | None:
    """The E14 pick from the two series, or None when neither can say (no series at all)."""
    real_dd, synth_dd = _dd(real, window), _dd(synthetic, window)
    in_slide_real = [v for d, v in real_dd if slide[0] <= d <= slide[1]]
    in_slide_synth = [v for d, v in synth_dd if slide[0] <= d <= slide[1]]
    if len(in_slide_real) >= MIN_SLIDE_SESSIONS:
        basis, slide_dd = "real", in_slide_real
    elif in_slide_synth:
        basis, slide_dd = "synthetic", in_slide_synth
    else:
        return None
    if not synth_dd:
        return None
    first_end = synth_dd[0][0] + timedelta(days=first_days)
    first_year = [v for d, v in synth_dd if d < first_end]
    rows = [
        Row(
            t,
            trips_in_slide=max(slide_dd) >= t,
            episodes=episodes(first_year, t),
            qualifies=max(slide_dd) >= t and episodes(first_year, t) <= MAX_EPISODES,
        )
        for t in THRESHOLDS
    ]
    best = next((r.threshold for r in rows if r.qualifies), None)
    return Choice(
        value=str(best if best is not None else FALLBACK),
        rows=rows,
        slide_basis=basis,
        fell_back=best is None,
        slide_peak_pct=max(slide_dd),
        first_year_peak_pct=max(first_year, default=0.0),
    )


def e14_result(choice: Choice | None, *, now: datetime | None = None) -> EnvelopeReportResult:
    """The E14 result file: ``passed`` True with the chosen threshold (the fallback 15 included: E14
    says 15 when none qualifies), or None when there is no series to measure."""
    metrics: dict[str, float | str | None] = {}
    if choice is not None:
        metrics = {
            "threshold": choice.value,
            "fell_back_to_15": "yes" if choice.fell_back else "no",
            "slide_series": choice.slide_basis,
            "slide_peak_drawdown_pct": round(choice.slide_peak_pct, 3),
            "first_year_peak_drawdown_pct": round(choice.first_year_peak_pct, 3),
        }
        for r in choice.rows:
            metrics[f"t{r.threshold}"] = (
                f"trips_in_slide={'yes' if r.trips_in_slide else 'no'} episodes={r.episodes}"
            )
    else:
        metrics["note"] = "no net-liquidation series covering the Oct-Nov 2026 slide"
    return make_result(
        "E14",
        passed=None if choice is None else True,
        criterion=CRITERION,
        metrics=metrics,
        switch="slow_breaker",
        value_on_pass=choice.value if choice is not None else str(FALLBACK),
        now=now,
    )


def run(db_path: Path, *, since: date | None = None) -> tuple[str, EnvelopeReportResult | None]:
    """The report text and the result (None when nothing could be read)."""
    try:
        con = open_ro(db_path)
    except FileNotFoundError:
        return f"No trading database at {db_path}: nothing to replay.", None
    try:
        real = load_nlv_series(con)
        try:
            ctx = load_book_context(con, since=since)
        except LookupError:
            ctx = None
    finally:
        con.close()
    synthetic: Series = []
    note = ""
    if ctx is not None:
        try:
            start = since or ctx.closes["SPY"][0][0]
            path = sv.simulate(
                ctx.inputs,
                ctx.closes,
                ctx.ivs,
                mode="status_quo",
                start=start,
                spreads_month_pct=0.0,
            )
            synthetic = list(zip(path.days, path.nlv, strict=True))
        except (sv.ReplayUnavailable, KeyError) as exc:
            note = f"synthetic series unavailable: {exc}"
    window = get_envelope_cfg().slow_breaker.window_sessions
    choice = choose_threshold(real, synthetic, window=window)
    result = e14_result(choice)
    lines = [
        f"real NLV series: {len(real)} days"
        + (f" ({real[0][0]} .. {real[-1][0]})" if real else ""),
        f"synthetic series (today's book on the panel): {len(synthetic)} sessions"
        + (f" ({synthetic[0][0]} .. {synthetic[-1][0]})" if synthetic else ""),
    ]
    if note:
        lines.append(note)
    if choice is not None:
        lines += [
            f"slide drawdown peak {choice.slide_peak_pct:.2f}% ({choice.slide_basis} series); "
            f"first-12-month peak {choice.first_year_peak_pct:.2f}% (synthetic)",
            f"{'threshold':>9} {'trips in slide':>15} {'episodes':>9}  qualifies",
            *[
                f"{r.threshold:>8}% {'yes' if r.trips_in_slide else 'no':>15} {r.episodes:>9}  "
                f"{'yes' if r.qualifies else 'no'}"
                for r in choice.rows
            ],
            f"-> {choice.value}%" + (" (none qualified: the fallback)" if choice.fell_back else ""),
        ]
    lines.append(f"\nE14: {verdict_word(result.passed)}")
    return "\n".join(lines), result if choice is not None else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E14: pick the slow breaker's threshold by replay")
    ap.add_argument("--db", type=Path, default=None, help="trading DB or a copy (default: config)")
    ap.add_argument("--since", type=date.fromisoformat, default=None, help="panel start")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args(argv)
    text, result = run(args.db or trading_db_path(), since=args.since)
    print(text)
    if result is None:
        return 2
    if not args.dry_run:
        print(f"wrote {write_result(result)} and {write_report('E14', text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
