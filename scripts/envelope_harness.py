"""The survivability harness (risk-envelope plan Task 26; spec §3.4.6, rulings P1, P2).

    python -m scripts.envelope_harness [--db PATH] [--since YYYY-MM-DD] [--attempt-every N] [--dry-run]

Reads the trading database **read-only** (``mode=ro``; point ``--db`` at a copy if you like) and
prints, for today's book on the ``price_history`` panel:

* the analytic worst case: S10, S20, G10, P20, T20 and S-SMH, gross and net of long options, with
  the spreads book's monthly stop (2% of NLV) counted on top;
* the status-quo path (today's composition, rolled daily) beside the always-most-aggressive path
  under the envelope (every CSP the envelope admits at max size, 0.25 delta 30 DTE, on the
  ``actively_wheeling`` names): worst 20-session drawdown, lots opened, and any admission above
  L(t) or L_ew(t);
* the record evidence: the ``envelope_snapshots`` sessions in ``record`` and any P1 defect.

It writes ``data/envelope_reports/harness.json`` (``switch="envelope_enforce"``, ``value_on_pass="on"``)
and ``harness_report.txt``; the EOD run applies a PASS (paper only, a FAIL never turns anything off).
With no database, no snapshot or a book it cannot value, nothing is written and the run says why.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from src.analytics.shock import SCENARIOS
from src.common.config import get_envelope_cfg
from src.common.schemas import EnvelopeReportResult
from src.reporting import survivability as sv
from src.reporting.replay import (
    REPORTS_DIR,
    BookContext,
    load_book_context,
    open_ro,
    trading_db_path,
    verdict_word,
    write_report,
    write_result,
)

__all__ = ["main", "run", "write_result", "REPORTS_DIR"]

DEFAULT_ATTEMPT_EVERY = 5  # a weekly attempt: the harness is a stress path, not a daily agent


def _table(ctx: BookContext, worst: sv.WorstCase) -> list[str]:
    lines = [
        f"Book as of {ctx.captured_at:%Y-%m-%d %H:%M} UTC: NLV ${ctx.account.net_liquidation:,.0f}, "
        f"{len(ctx.inputs.lines)} lines, U_ew {worst.uew:.2f}",
        "",
        f"{'scenario':<8} {'gross %NLV':>11} {'net %NLV':>10}",
    ]
    for name in SCENARIOS:
        mark = "  <- worst" if name == worst.worst_gross else ""
        lines.append(f"{name:<8} {worst.gross[name]:>11.2f} {worst.net[name]:>10.2f}{mark}")
    lines.append(
        f"worst gross {worst.gross[worst.worst_gross]:.2f}% + spreads month {worst.spreads_pct:.1f}% "
        f"= {worst.total_gross_pct:.2f}% of NLV (net: {worst.total_net_pct:.2f}%)"
    )
    return lines


def run(
    db_path: Path,
    *,
    since: date | None = None,
    attempt_every: int = DEFAULT_ATTEMPT_EVERY,
) -> tuple[str, EnvelopeReportResult | None]:
    """The report text and the result (None when nothing could be run)."""
    try:
        con = open_ro(db_path)
    except FileNotFoundError:
        return f"No trading database at {db_path}: nothing to replay.", None
    try:
        try:
            ctx = load_book_context(con, since=since)
        except LookupError as exc:
            return f"{exc}: nothing to replay.", None
        evidence = sv.read_record_evidence(con)
        stored = con.execute(
            "SELECT s10, uew FROM envelope_snapshots WHERE measured = 1 "
            "ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()

    worst = sv.analytic_worst_case(ctx.inputs)
    text = _table(ctx, worst)
    if stored is not None:
        # the replayed book leaves the value book out: a gap here is that, or a stale snapshot
        text.append(
            f"latest stored measurement: S10 {stored[0]:.2f}%, U_ew {stored[1]:.2f} "
            "(this replay's book excludes the value book's stock)"
        )
    if worst.unmeasured:
        text.append(f"\nThe book is not fully measured (no beta, spot or IV: {worst.unmeasured}).")
        return "\n".join(text), None
    cfg = get_envelope_cfg()
    start = since or ctx.closes["SPY"][0][0]
    try:
        base = sv.simulate(ctx.inputs, ctx.closes, ctx.ivs, mode="status_quo", start=start)
        aggressive = sv.simulate(
            ctx.inputs,
            ctx.closes,
            ctx.ivs,
            mode="aggressive",
            start=start,
            names=ctx.names,
            glide_targets=(cfg.s10_target_pct, cfg.uew_target, cfg.glide_weeks),
            attempt_every=attempt_every,
        )
    except sv.ReplayUnavailable as exc:
        text.append(f"\nReplay unavailable: {exc}. Nothing written.")
        return "\n".join(text), None
    except KeyError as exc:
        text.append(f"\nReplay unavailable: no close or beta for {exc}. Nothing written.")
        return "\n".join(text), None

    result = sv.harness_result(
        worst,
        base,
        aggressive,
        record_sessions=evidence.sessions,
        defects=evidence.defects,
    )
    text += [
        "",
        f"Panel {base.days[0]} .. {base.days[-1]} ({len(base.days)} sessions), "
        f"attempt every {attempt_every} sessions",
        f"{'path':<28} {'worst 20-session drawdown':>26}",
        f"{'status quo (rolled daily)':<28} {base.worst20:>25.2f}%",
        f"{'aggressive under envelope':<28} {aggressive.worst20:>25.2f}%",
        f"aggressive: {aggressive.opened_lots} opens, {aggressive.opened_contracts} contracts, "
        f"S10 {aggressive.s10[0]:.1f}% -> {aggressive.s10[-1]:.1f}%, "
        f"U_ew {aggressive.uew[0]:.2f} -> {aggressive.uew[-1]:.2f}",
        f"admissions above L(t) or L_ew(t): {len(aggressive.violations)}",
        *[f"  {v}" for v in aggressive.violations[:10]],
        f"record sessions: {evidence.sessions} (need {sv.MIN_RECORD_SESSIONS}); "
        f"P1 defects: {len(evidence.defects)}",
        *[f"  {d}" for d in evidence.defects[:10]],
        "",
        f"harness: {verdict_word(result.passed)}",
    ]
    if "note" in result.metrics:
        text.append(f"  {result.metrics['note']}")
    return "\n".join(text), result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The survivability harness (P1/P2)")
    ap.add_argument("--db", type=Path, default=None, help="trading DB or a copy (default: config)")
    ap.add_argument("--since", type=date.fromisoformat, default=None, help="panel start")
    ap.add_argument("--attempt-every", type=int, default=DEFAULT_ATTEMPT_EVERY)
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args(argv)
    text, result = run(
        args.db or trading_db_path(), since=args.since, attempt_every=args.attempt_every
    )
    print(text)
    if result is None:
        return 2
    if not args.dry_run:
        print(f"wrote {write_result(result)} and {write_report('harness', text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
