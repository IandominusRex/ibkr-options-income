"""Backtest-on-demand for a specific candidate's parameters (C11).

Runs the v2 backtest engine for a symbol using the parameters that would be used
at decision time (delta, DTE, profit-take, IV-rank gate), and prints a compact
result the operator can read before approving a trade. Returns a compact text
summary (4 lines) suitable for manual review or injection into a Claude prompt.

Usage:
    source .venv/bin/activate
    python -m scripts.backtest_candidate --symbol AAPL --strategy covered_call
    python -m scripts.backtest_candidate --symbol MARA --strategy cash_secured_put \\
        --delta 0.25 --dte 21 --profit-take 0.50 --min-iv-rank 30
    python -m scripts.backtest_candidate --symbol AAPL --strategy covered_call --earnings
    python -m scripts.backtest_candidate --symbol AAPL --strategy covered_call \\
        --earnings --vol-crush-dte 14
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import BacktestParams
from src.backtest.on_demand import run_backtest, summarize
from src.backtest.report import compact_report, format_report
from src.common.logging import setup_logging


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="On-demand backtest for a candidate's parameters (C11)."
    )
    parser.add_argument("--symbol", required=True, help="underlying ticker, e.g. AAPL")
    parser.add_argument(
        "--strategy",
        choices=["covered_call", "cash_secured_put"],
        default="cash_secured_put",
    )
    parser.add_argument("--delta", type=float, default=0.30, help="target |delta| for the strike")
    parser.add_argument("--dte", type=int, default=30, help="calendar days to expiry per cycle")
    parser.add_argument("--contracts", type=int, default=1)
    parser.add_argument("--commission", type=float, default=0.65, help="$ per contract on entry")
    parser.add_argument("--start", help="YYYY-MM-DD (default: rolling --period)")
    parser.add_argument("--end", help="YYYY-MM-DD")
    parser.add_argument("--period", default="2y", help="yfinance period when --start omitted")
    parser.add_argument(
        "--profit-take",
        type=float,
        default=None,
        metavar="PCT",
        help="close early at this fraction of premium decay, e.g. 0.50",
    )
    parser.add_argument(
        "--min-iv-rank",
        type=float,
        default=None,
        metavar="RANK",
        help="only open cycles whose entry IV rank >= this (requires stored iv_history)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="print a 4-line compact summary instead of the full report",
    )
    parser.add_argument(
        "--earnings",
        action="store_true",
        help="run the earnings-cycle backtest (C10) instead of the standard simulation",
    )
    parser.add_argument(
        "--blackout-before",
        type=int,
        default=14,
        help="days before earnings to stop entering (earnings mode only)",
    )
    parser.add_argument(
        "--blackout-after",
        type=int,
        default=3,
        help="days after earnings before re-entering (earnings mode only)",
    )
    parser.add_argument(
        "--vol-crush-dte",
        type=int,
        default=None,
        metavar="DTE",
        help="also run a vol-crush entry N days after each earnings (earnings mode only)",
    )
    args = parser.parse_args()

    setup_logging()

    params = BacktestParams(
        strategy=args.strategy,
        target_delta=args.delta,
        dte=args.dte,
        contracts=args.contracts,
        commission_per_contract=args.commission,
        profit_take_pct=args.profit_take,
        min_iv_rank=args.min_iv_rank,
    )

    outcome = run_backtest(
        args.symbol,
        params,
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        period=args.period,
        earnings=args.earnings,
        blackout_before=args.blackout_before,
        blackout_after=args.blackout_after,
        vol_crush_dte=args.vol_crush_dte,
    )

    if outcome.error is not None:
        print(outcome.error)
        sys.exit(1)

    # Standard runs honour --compact / full; earnings runs have a single report form.
    if outcome.result is not None and not args.compact:
        print(format_report(outcome.result))
    elif outcome.result is not None:
        print(compact_report(outcome.result))
    else:
        print(summarize(outcome))


if __name__ == "__main__":
    main()
