"""Seed iv_history with ~1y of daily implied volatility for all universe symbols.

Run once to bootstrap; safe to re-run — existing (symbol, date) pairs are skipped.

Usage:
    source .venv/bin/activate
    python -m scripts.backfill_iv
"""

from __future__ import annotations

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

log = get_logger(__name__)


def _universe_symbols(cfg) -> list[str]:
    u = cfg.universe
    symbols = set(u.get("indexes", [])) | set(u.get("watchlist", [])) | set(u.get("would_own", []))
    return sorted(symbols)


def _existing_dates(session, symbol: str) -> set[date]:
    rows = session.query(IVHistoryRow.obs_date).filter(IVHistoryRow.symbol == symbol).all()
    return {r.obs_date for r in rows}


def run_backfill() -> None:
    cfg = get_config()
    init_db()
    symbols = _universe_symbols(cfg)
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


if __name__ == "__main__":
    run_backfill()
