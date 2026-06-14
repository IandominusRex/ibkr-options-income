"""Accessors for the price_history table — daily OHLCV bars for the technical layer.

`price_history` backs the technical indicators (RSI/ATR/MACD/SMA/regime/support-resistance)
and HV30. It is bootstrapped once by `scripts/backfill_prices.py` and kept fresh by a daily
append (the EOD run + a self-healing tail-fetch in the scan loader). Without a persistent
store, every `/scan` and 15-min cycle pulled a full 1y (+3mo) yfinance history per symbol;
now scans read settled bars from here and fetch only the missing tail.

Every function swallows storage errors and never raises: this is derived market data and must
not take the trading pipeline down.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select

from src.storage.db import session_scope
from src.storage.models import PriceHistoryRow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bar:
    """One settled daily OHLCV bar."""

    obs_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


def load_bars(symbol: str, limit: int = 400) -> list[Bar]:
    """Return up to *limit* most-recent settled bars for *symbol*, ascending by date.

    400 ≈ 1.5 trading years, enough for the 200-day SMA plus a comfortable margin.
    """
    try:
        with session_scope() as sess:
            rows = (
                sess.execute(
                    select(PriceHistoryRow)
                    .where(PriceHistoryRow.symbol == symbol)
                    .order_by(PriceHistoryRow.obs_date.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            bars = [Bar(r.obs_date, r.open, r.high, r.low, r.close, r.volume or 0.0) for r in rows]
        bars.reverse()  # ascending
        return bars
    except Exception:
        log.debug("load_bars failed for %s", symbol, exc_info=True)
        return []


def latest_bar_date(symbol: str) -> date | None:
    """Most recent settled-bar date stored for *symbol*, or None."""
    try:
        with session_scope() as sess:
            return sess.execute(
                select(func.max(PriceHistoryRow.obs_date)).where(PriceHistoryRow.symbol == symbol)
            ).scalar_one_or_none()
    except Exception:
        log.debug("latest_bar_date failed for %s", symbol, exc_info=True)
        return None


def append_bars(symbol: str, bars: list[Bar], source: str = "yfinance") -> int:
    """Insert bars whose dates aren't already stored. Returns the number inserted.

    Idempotent: existing (symbol, obs_date) rows are left untouched, so a re-run or an
    overlapping tail fetch never duplicates or rewrites a settled bar. Never raises.
    """
    if not bars:
        return 0
    try:
        with session_scope() as sess:
            existing = {
                d
                for (d,) in sess.execute(
                    select(PriceHistoryRow.obs_date).where(PriceHistoryRow.symbol == symbol)
                ).all()
            }
            new_rows = [
                PriceHistoryRow(
                    symbol=symbol,
                    obs_date=b.obs_date,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                    source=source,
                )
                for b in bars
                if b.obs_date not in existing
            ]
            sess.add_all(new_rows)
            return len(new_rows)
    except Exception:
        log.warning("append_bars failed for %s", symbol, exc_info=True)
        return 0
