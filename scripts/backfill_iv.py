"""Seed/refresh iv_history with daily implied volatility for a symbol list.

Safe to re-run — existing (symbol, date) pairs are skipped.

Usage:
    source .venv/bin/activate
    python -m scripts.backfill_iv                     # universe ∪ currently-held
    python -m scripts.backfill_iv --symbols AMD,BAC    # explicit symbol list
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import get_config
from src.common.logging import get_logger
from src.ibkr.connection import IBKRConnection
from src.ibkr.contracts import qualify_stock
from src.storage.db import init_db, session_scope
from src.storage.models import IVHistoryRow
from src.storage.positions import load_latest_position_snapshot

log = get_logger(__name__)


def _universe_symbols(cfg) -> list[str]:
    u = cfg.universe
    symbols = set(u.get("indexes", [])) | set(u.get("watchlist", [])) | set(u.get("would_own", []))
    return sorted(symbols)


def _default_symbols(cfg) -> list[str]:
    """Universe ∪ currently-held, from the latest `position_snapshots` row.

    Mirrors `eod_report._iv_symbols`'s holdings union so an ad-hoc backfill covers exactly
    what the nightly EOD append would (minus its staleness ordering, which only matters for
    a partial/aborted run — a one-shot backfill runs every symbol to completion).
    """
    held = {p.symbol.upper() for p in load_latest_position_snapshot() if p.sec_type == "STK"}
    return sorted(set(_universe_symbols(cfg)) | held)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.backfill_iv",
        description=(
            "Seed or refresh iv_history with one year of daily implied volatility (via IBKR). "
            "Defaults to the trading universe (indexes + watchlist + would_own) unioned with "
            "whatever stock is currently held, per the latest position_snapshots row."
        ),
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        metavar="SYM,SYM,...",
        help=(
            "Comma-separated symbol list to backfill (e.g. AMD,BAC). Overrides the default "
            "universe ∪ currently-held selection."
        ),
    )
    return parser.parse_args(argv)


def _existing_dates(session, symbol: str) -> set[date]:
    rows = session.query(IVHistoryRow.obs_date).filter(IVHistoryRow.symbol == symbol).all()
    return {r.obs_date for r in rows}


def run_backfill(symbols: list[str] | None = None) -> None:
    cfg = get_config()
    init_db()
    if symbols is None:
        symbols = _default_symbols(cfg)
    log.info("IV backfill: %d symbols — %s", len(symbols), symbols)

    with IBKRConnection("backfill") as ib:
        for symbol in symbols:
            try:
                stock = qualify_stock(ib, symbol)
                bars = ib.reqHistoricalData(
                    stock,
                    endDateTime="",
                    durationStr="1 Y",
                    barSizeSetting="1 day",
                    whatToShow="OPTION_IMPLIED_VOLATILITY",
                    useRTH=True,
                )
                if not bars:
                    log.warning("%s: no IV bars returned", symbol)
                    ib.sleep(0.5)
                    continue

                with session_scope() as session:
                    existing = _existing_dates(session, symbol)
                    new_rows = []
                    for bar in bars:
                        bar_date = bar.date if isinstance(bar.date, date) else bar.date.date()
                        if bar_date not in existing:
                            new_rows.append(
                                IVHistoryRow(
                                    symbol=symbol,
                                    obs_date=bar_date,
                                    iv=float(bar.close),
                                    source="ibkr",
                                )
                            )
                    session.add_all(new_rows)

                log.info(
                    "%s: inserted %d rows (skipped %d existing)",
                    symbol,
                    len(new_rows),
                    len(bars) - len(new_rows),
                )

            except Exception as exc:  # noqa: BLE001
                log.error("%s: backfill failed — %s", symbol, exc)

            ib.sleep(0.5)  # pacing between reqHistoricalData calls

    log.info("IV backfill complete.")


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    )
    run_backfill(symbols)


if __name__ == "__main__":
    main()
