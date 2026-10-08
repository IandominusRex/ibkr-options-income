"""Backtest the daily credit-spread rules over ThetaData history (Theta Terminal must be running).

    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --csv data/spreads_bt/june.csv
    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --profit-take 80
    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --trigger always
    python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --negative-gamma skip

Prints overall stats (win rate beside break-even win rate), average hold and MAE, and the same
numbers split by regime, side, trigger, gap day and exit reason, in SPY-equivalent dollars;
optionally writes every trade with its tags to CSV. Run once per setting to compare.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import date
from pathlib import Path

from src.common.config import ROOT, get_config
from src.spreads.backtest.engine import run_backtest, with_overrides
from src.spreads.backtest.thetadata import ThetaDataClient
from src.spreads.report import compute_stats, format_extras, format_stats, tag_breakdowns


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
    a = p.parse_args()
    cfg = with_overrides(
        get_config().spreads,
        profit_take_pct=a.profit_take,
        entry_trigger=a.trigger,
        negative_gamma=a.negative_gamma,
    )
    client = ThetaDataClient(cfg.backtest.thetadata_url, ROOT / cfg.backtest.cache_dir)
    trades = run_backtest(client, cfg, a.start, a.end)
    print(
        f"settings: profit_take {cfg.exits.profit_take_pct:g}% · trigger {cfg.entry.trigger}"
        f" · negative gamma {cfg.gex.negative_gamma_action}"
    )
    print(format_stats(f"backtest {a.start}..{a.end}", compute_stats([t.pnl_usd for t in trades])))
    start_cap = cfg.risk.starting_capital_usd
    end_cap = start_cap + sum(t.pnl_usd for t in trades)
    print(
        f"  capital ${start_cap:,.0f} → ${end_cap:,.0f} ({(end_cap / start_cap - 1) * 100:+.1f}%), compounding at {cfg.risk.max_loss_pct_of_capital:.0%} max loss per trade"
    )
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
