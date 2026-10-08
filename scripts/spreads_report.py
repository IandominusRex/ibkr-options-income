"""Print spreads performance from data/spreads.db, split by every trade tag.

python -m scripts.spreads_report --mode shadow
python -m scripts.spreads_report --mode paper --csv data/spreads_paper_trades.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from src.common.schemas import SpreadTradeRecord
from src.spreads import store
from src.spreads.report import compute_stats, format_extras, format_stats, tag_breakdowns


def main() -> None:
    p = argparse.ArgumentParser(description="Daily credit-spread performance")
    p.add_argument("--mode", choices=("shadow", "paper"), default="shadow")
    p.add_argument(
        "--csv", type=Path, default=None, help="write every trade, open or closed, with its tags"
    )
    a = p.parse_args()
    store.init_spreads_db()
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
