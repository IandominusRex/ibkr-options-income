"""Compare assign / roll / close at a strike breach over a symbol's price history (2026-10-11).

Offline: daily closes from the price provider, option prices from Black-Scholes at trailing HV30
(the system has no historical option chains). No IBKR connection, no DB writes. The output is a
reading aid for a human judging the roll policy (config/settings.yaml → roll:) — nothing here
feeds it. See `src/backtest/roll_arms.py` for the model and its assumptions.

Usage:
    source .venv/bin/activate
    python -m scripts.roll_backtest --symbol AAPL --start 2019-01-01 --end 2026-09-30
    python -m scripts.roll_backtest --symbol GOOGL --right C --delta 0.25 --dte 14 --roll-dte 7
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from src.backtest.data import load_price_series
from src.backtest.roll_arms import format_arms_summary, simulate_breach_arms
from src.common.config import get_config
from src.common.logging import setup_logging


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def main() -> None:
    roll = get_config().roll
    parser = argparse.ArgumentParser(description="Assign vs roll vs close at a strike breach.")
    parser.add_argument("--symbol", required=True, help="underlying ticker, e.g. AAPL")
    parser.add_argument(
        "--right", choices=["P", "C"], default="P", help="P = CSP, C = covered call"
    )
    parser.add_argument("--delta", type=float, default=0.25, help="target |delta| at entry")
    parser.add_argument("--dte", type=int, default=14, help="calendar days to expiry per cycle")
    parser.add_argument("--roll-dte", type=int, default=7, help="days a roll adds past expiry")
    parser.add_argument(
        "--breach-dte",
        type=int,
        default=roll.trigger.evaluate_within_dte,
        help="act on a breach only this close to expiry (roll.trigger.evaluate_within_dte)",
    )
    parser.add_argument(
        "--min-net-credit", type=float, default=roll.new_leg.min_net_credit, help="$/sh, puts"
    )
    parser.add_argument("--max-debit", type=float, default=roll.cc.max_debit, help="$/sh, calls")
    parser.add_argument("--commission", type=float, default=0.65, help="$ per contract per leg")
    parser.add_argument("--rate", type=float, default=0.05, help="risk-free rate")
    parser.add_argument("--start", help="YYYY-MM-DD (default: rolling --period)")
    parser.add_argument("--end", help="YYYY-MM-DD")
    parser.add_argument("--period", default="5y", help="provider period when --start omitted")
    args = parser.parse_args()

    setup_logging()
    prices = load_price_series(
        args.symbol, start=_parse_date(args.start), end=_parse_date(args.end), period=args.period
    )
    if not prices:
        print(f"No price history for {args.symbol} — nothing to backtest.")
        sys.exit(1)
    res = simulate_breach_arms(
        [c for _, c in prices],
        [d for d, _ in prices],
        right=args.right,
        target_delta=args.delta,
        dte=args.dte,
        roll_dte=args.roll_dte,
        breach_dte=args.breach_dte,
        min_net_credit=args.min_net_credit,
        max_debit=args.max_debit,
        risk_free_rate=args.rate,
        commission=args.commission,
    )
    print(format_arms_summary(res, symbol=args.symbol))


if __name__ == "__main__":
    main()
