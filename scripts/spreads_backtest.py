"""Backtest the daily credit-spread rules over ThetaData history (Theta Terminal must be running).

    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --csv data/spreads_bt/june.csv
    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --profit-take 80
    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --trigger always
    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --negative-gamma skip

    python -m scripts.spreads_backtest --start 2023-01-03 --end 2026-11-13 --report

Prints overall stats (win rate beside break-even win rate), average hold and MAE, and the same
numbers split by regime, side, trigger, gap day and exit reason, in SPY-equivalent dollars;
optionally writes every trade with its tags to CSV. Run once per setting to compare.

Sizing and costs follow the live rules (risk-envelope Tasks 4, 5, 7): every cap is a share of
``--nlv`` (default: the latest net liquidation in the trading DB's ``portfolio_snapshots``, read
read-only), and fills pay the cost standard. ``--report`` writes the spreads paper bar (ruling
P8) to ``data/envelope_reports/spreads_paper.json``; the EOD run applies it, and a PASS turns
the ``spreads_paper`` switch on (paper only).
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

from src.common.config import ROOT, get_config
from src.common.schemas import EnvelopeReportResult
from src.spreads.backtest.engine import run_backtest, with_overrides
from src.spreads.backtest.thetadata import ThetaDataClient
from src.spreads.report import (
    compute_stats,
    format_extras,
    format_stats,
    paper_bar,
    tag_breakdowns,
)

REPORTS_DIR = ROOT / "data" / "envelope_reports"


def latest_nlv() -> float | None:
    """The newest ``portfolio_snapshots`` net liquidation (USD), opened ``mode=ro``; None when
    the trading DB or a snapshot is missing."""
    url = get_config().db_url_abs()
    if not url.startswith("sqlite:///"):
        return None
    path = Path(url[len("sqlite:///") :])
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT account FROM portfolio_snapshots ORDER BY captured_at DESC, id DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    nlv = json.loads(row[0]).get("net_liquidation")
    return float(nlv) if nlv else None


def write_report(result: EnvelopeReportResult, directory: Path = REPORTS_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result.id}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest the daily credit-spread rules")
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--csv", type=Path, default=None)
    p.add_argument(
        "--profit-take",
        type=float,
        default=None,
        help="override exits.profit_take_pct, e.g. 50 or 80",
    )
    p.add_argument(
        "--trigger", choices=("move", "always"), default=None, help="override entry.trigger"
    )
    p.add_argument(
        "--negative-gamma",
        choices=("allow", "skip"),
        default=None,
        help="override gex.negative_gamma_action",
    )
    p.add_argument(
        "--nlv",
        type=float,
        default=None,
        help="the stated net liquidation (USD) every cap is a share of; default: the latest "
        "portfolio snapshot's",
    )
    p.add_argument(
        "--report",
        action="store_true",
        help="write the paper bar (P8) to data/envelope_reports/spreads_paper.json",
    )
    a = p.parse_args()
    cfg = with_overrides(
        get_config().spreads,
        profit_take_pct=a.profit_take,
        entry_trigger=a.trigger,
        negative_gamma=a.negative_gamma,
    )
    nlv = a.nlv if a.nlv is not None else latest_nlv()
    if nlv is None or nlv <= 0:
        p.error("no net liquidation in the trading DB's portfolio_snapshots: pass --nlv")
    client = ThetaDataClient(cfg.backtest.thetadata_url, ROOT / cfg.backtest.cache_dir)
    skipped: list[tuple[date, str]] = []
    sessions: list[date] = []
    trades = run_backtest(client, cfg, a.start, a.end, skipped, nlv_usd=nlv, sessions=sessions)
    for day, why in skipped:
        print(f"  skipped {day}: {why}")
    print(
        f"settings: profit_take {cfg.exits.profit_take_pct:g}% · trigger {cfg.entry.trigger}"
        f" · negative gamma {cfg.gex.negative_gamma_action}"
    )
    print(format_stats(f"backtest {a.start}..{a.end}", compute_stats([t.pnl_usd for t in trades])))
    end_nlv = nlv + sum(t.pnl_usd for t in trades)
    print(
        f"  NLV ${nlv:,.0f} → ${end_nlv:,.0f} ({(end_nlv / nlv - 1) * 100:+.2f}%) over "
        f"{len(sessions)} sessions, {cfg.risk.max_loss_pct_of_nlv:.1%} of NLV max loss per trade"
    )
    bar = paper_bar(trades, sessions, nlv)
    m = bar.metrics
    verdict = {True: "PASS", False: "FAIL", None: "INSUFFICIENT DATA"}[bar.passed]
    print(
        f"  paper bar: {verdict} · mean/session {m['mean_pnl_per_session']} · bootstrap p5 "
        f"{m['bootstrap_p5_mean']} · worst day {m['worst_day']} · worst 20 sessions "
        f"{m['worst_20_sessions']} (limit {m['worst_20_limit']})"
    )
    if a.report:
        print(f"  wrote {write_report(bar)}")
    print("  " + format_extras(trades))
    for name, groups in tag_breakdowns(trades).items():
        for value, s in groups.items():
            print(format_stats(f"  {name}={value}", s))
    if a.csv and trades:
        a.csv.parent.mkdir(parents=True, exist_ok=True)
        with a.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(asdict(trades[0])))
            w.writeheader()
            w.writerows(asdict(t) for t in trades)
        print(f"wrote {len(trades)} trades to {a.csv}")


if __name__ == "__main__":
    main()
