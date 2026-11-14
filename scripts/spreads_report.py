"""Print spreads performance from data/spreads.db, split by every trade tag.

python -m scripts.spreads_report --mode shadow
python -m scripts.spreads_report --mode paper --csv data/spreads_paper_trades.csv
python -m scripts.spreads_report --mode paper --compare [--csv data/spreads_compare.csv]
python -m scripts.spreads_report --mode paper --day 2026-10-14
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from src.common.config import get_config
from src.common.schemas import SpreadTradeRecord
from src.spreads import store
from src.spreads.report import (
    build_decisions,
    compute_stats,
    decision_rows,
    format_compare,
    format_day,
    format_extras,
    format_stats,
    scope_compare,
    tag_breakdowns,
)


def main() -> None:
    p = argparse.ArgumentParser(description="Daily credit-spread performance")
    p.add_argument("--mode", choices=("shadow", "paper", "baseline"), default="shadow")
    p.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="write every trade (or, with --compare, every decision)",
    )
    p.add_argument(
        "--compare", action="store_true", help="Claude's book (--mode) against the baseline book"
    )
    p.add_argument(
        "--day",
        type=date.fromisoformat,
        default=None,
        help="one day's plan and picks in full (YYYY-MM-DD)",
    )
    a = p.parse_args()
    store.init_spreads_db()
    if a.day is not None:
        if a.mode == "baseline":
            p.error("--day shows --mode shadow|paper picks against the baseline book")
        plan = store.day_plan(a.day)
        plan_text = "day plan: none" if plan is None else f"day plan: {plan.model_dump()}"
        base_log = store.trade_log("baseline")
        print(
            "\n".join(
                format_day(
                    a.day,
                    plan_text,
                    [x for x in store.picks(a.day) if x.book_mode == a.mode],
                    store.trade_log(a.mode),
                    base_log,
                )
            )
        )
        return
    if a.compare:
        if a.mode == "baseline":
            p.error("--compare compares --mode shadow|paper against the baseline book")
        picks, main_log, base_log, since = scope_compare(
            store.picks(), store.trade_log(a.mode), store.trade_log("baseline"), a.mode
        )
        decisions = build_decisions(picks, main_log, base_log)
        from src.spreads.menu import slippage_per_leg

        slip = slippage_per_leg(get_config().spreads)  # the cost standard's per-leg slippage
        print(
            f"scope: --mode {a.mode} picks only, trades opened "
            + (f"since the first pick ({since:%Y-%m-%d %H:%M} UTC)" if since else "(no picks yet)")
            + " — pre-AI trades excluded"
        )
        print("\n".join(format_compare(decisions, main_log, base_log, a.mode, slip)))
        if a.csv:
            rows = decision_rows(decisions)
            a.csv.parent.mkdir(parents=True, exist_ok=True)
            with a.csv.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["pick_id"])
                w.writeheader()
                w.writerows(rows)
            print(f"wrote {len(rows)} decisions to {a.csv}")
        return
    log = store.trade_log(a.mode)
    closed = sorted(
        (t for t in log if t.status == "closed"), key=lambda t: t.closed_at or t.opened_at
    )
    print(format_stats(f"{a.mode} (closed)", compute_stats([t.pnl_usd for t in closed])))
    print("  " + format_extras(closed))
    for name, groups in tag_breakdowns(closed).items():
        for value, s in groups.items():
            print(format_stats(f"  {name}={value}", s))
    if len(log) > len(closed):
        print(f"  {len(log) - len(closed)} spread(s) still open or expiring")
    if a.csv:
        a.csv.parent.mkdir(parents=True, exist_ok=True)
        with a.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(SpreadTradeRecord.model_fields))
            w.writeheader()
            w.writerows(t.model_dump(mode="json") for t in log)
        print(f"wrote {len(log)} trades to {a.csv}")


if __name__ == "__main__":
    main()
