"""Backtest the option-income strategies over historical prices.

Deterministic and offline-ish: pulls daily closes from yfinance, synthesises option premiums
with Black-Scholes from trailing realised vol (the system has no historical option chains), and
simulates non-overlapping short-premium cycles. No IBKR connection, no DB writes. See
`src/backtest/engine.py` for the model and its assumptions.

Usage:
    source .venv/bin/activate
    python -m scripts.backtest --symbol MSTY --strategy cash_secured_put
    python -m scripts.backtest --symbol AAPL --strategy covered_call --delta 0.30 --dte 30 \
        --start 2023-01-01 --end 2024-01-01
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.data import load_price_series
from src.backtest.engine import BacktestParams, simulate
from src.backtest.report import format_report
from src.common.logging import setup_logging


def _parse_date(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest CC/CSP income over historical prices.")
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
    args = parser.parse_args()

    setup_logging()
    prices = load_price_series(
        args.symbol, start=_parse_date(args.start), end=_parse_date(args.end), period=args.period
    )
    if not prices:
        print(f"No price history for {args.symbol} — nothing to backtest.")
        sys.exit(1)

    params = BacktestParams(
        strategy=args.strategy,
        target_delta=args.delta,
        dte=args.dte,
        contracts=args.contracts,
        commission_per_contract=args.commission,
    )
    result = simulate(args.symbol, prices, params)
    print(format_report(result))


if __name__ == "__main__":
    main()
