"""Seed price_history with ~1y of daily OHLCV for all universe symbols.

Warms the store so the first `/scan` of the day reads settled bars from SQLite instead of
pulling a full 1y history per symbol from yfinance. Run once to bootstrap; safe to re-run —
existing (symbol, date) bars are skipped and only the missing tail is fetched.

Usage:
    source .venv/bin/activate
    python -m scripts.backfill_prices
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.analytics.price_data import get_ohlcv
from src.common.config import get_config
from src.common.logging import get_logger
from src.storage.db import init_db
from src.storage.price_history import latest_bar_date, load_bars

log = get_logger(__name__)


def _universe_symbols(cfg) -> list[str]:
    u = cfg.universe
    symbols = set(u.get("indexes", [])) | set(u.get("watchlist", [])) | set(u.get("would_own", []))
    return sorted(symbols)


def run_backfill() -> None:
    cfg = get_config()
    init_db()
    symbols = _universe_symbols(cfg)
    log.info("Price backfill: %d symbols — %s", len(symbols), symbols)

    for symbol in symbols:
        try:
            df = get_ohlcv(symbol)  # self-healing: fetches the missing tail (1y if empty)
            log.info(
                "%s: %d bars stored (latest %s)",
                symbol,
                len(load_bars(symbol)),
                latest_bar_date(symbol),
            )
            if df.empty:
                log.warning("%s: no OHLCV bars available", symbol)
        except Exception as exc:  # noqa: BLE001
            log.error("%s: price backfill failed — %s", symbol, exc)

    log.info("Price backfill complete.")


if __name__ == "__main__":
    run_backfill()
