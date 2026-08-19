"""Incremental daily OHLCV loader — the single source of settled price history.

Both the technical indicators (`technicals.py`) and HV30 (`iv.py`) need a long daily-bar
history. Previously each pulled a full 1y/3mo yfinance history *per symbol, per scan* — and the
15-min loop runs ~26×/session. This module persists settled bars in `price_history` and, on
each call, fetches **only the missing tail** (or a full year when the store is empty),
appending new settled sessions. Steady state (history already current) makes zero yfinance
history calls.

`get_ohlcv` is `@daily_cached`, so within a long-lived process it resolves once per symbol per
day; the 15-min loop reuses it without even a DB round trip. The *live* price is fetched
separately and uncached (see `technicals._fetch_last_price`) so it stays current intraday.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from src.common.cache import daily_cached
from src.common.market_hours import previous_session, today_et
from src.data.factory import get_price_provider
from src.storage.price_history import Bar, append_bars, load_bars

log = logging.getLogger(__name__)

_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _period_for_gap(last: date | None, target: date) -> str:
    """Smallest lookback window that covers the gap from *last* settled bar to *target*."""
    if last is None:
        return "1y"
    gap = (target - last).days
    if gap <= 5:
        return "5d"
    if gap <= 25:
        return "1mo"
    if gap <= 80:
        return "3mo"
    if gap <= 170:
        return "6mo"
    return "1y"


def _lookback_days_for_gap(last: date | None, target: date) -> int:
    """Calendar-day equivalent of :func:`_period_for_gap` for the provider's lookback_days arg."""
    if last is None:
        return 365
    gap = (target - last).days
    if gap <= 5:
        return 5
    if gap <= 25:
        return 25
    if gap <= 80:
        return 80
    if gap <= 170:
        return 170
    return 365


def _fetch_yf_bars(symbol: str, period: str) -> list[Bar]:
    """Pull daily bars via the active price provider and map to Bar objects (settled + forming).

    *period* is the yfinance-style period string (``"1y"``/``"3mo"``/…) retained for
    backwards-compatible call sites; it is translated to a ``lookback_days`` hint for the
    provider. The provider returns yfinance's ``history`` frame (today's forming bar
    included); this helper preserves the prior behaviour of mapping every row.
    """
    lookback_map = {
        "5d": 5,
        "1mo": 25,
        "3mo": 80,
        "6mo": 170,
        "1y": 365,
    }
    lookback = lookback_map.get(period, 365)
    try:
        df = get_price_provider().get_ohlcv(symbol, lookback_days=lookback)
    except Exception:
        log.warning("price_data: provider history failed for %s", symbol, exc_info=True)
        return []
    if df is None or df.empty:
        return []

    bars: list[Bar] = []
    for idx, row in df.iterrows():
        d = idx.date() if hasattr(idx, "date") else idx
        if not isinstance(d, date):
            continue
        try:
            close = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        if not pd.notna(close):
            continue
        bars.append(
            Bar(
                obs_date=d,
                open=float(row.get("Open", close)),
                high=float(row.get("High", close)),
                low=float(row.get("Low", close)),
                close=close,
                volume=float(row.get("Volume", 0.0) or 0.0),
            )
        )
    return bars


def _to_frame(bars: list[Bar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=_COLUMNS)
    df = pd.DataFrame(
        {
            "Open": [b.open for b in bars],
            "High": [b.high for b in bars],
            "Low": [b.low for b in bars],
            "Close": [b.close for b in bars],
            "Volume": [b.volume for b in bars],
        },
        index=pd.DatetimeIndex([pd.Timestamp(b.obs_date) for b in bars]),
    )
    return df


@daily_cached
def get_ohlcv(symbol: str) -> pd.DataFrame:
    """Return settled daily OHLCV for *symbol* as a DataFrame (ascending, today excluded).

    Reads `price_history`; if the newest stored bar is older than the last completed session
    (or the store is empty), fetches just the missing tail from yfinance and persists the new
    settled bars before returning. The current (forming) session is never stored — callers
    overlay the live price themselves.
    """
    today = today_et()
    target = previous_session(today)  # the latest session that should already be settled

    bars = load_bars(symbol)
    last = bars[-1].obs_date if bars else None

    if last is None or last < target:
        fetched = _fetch_yf_bars(symbol, _period_for_gap(last, target))
        # Persist only settled sessions — the current day's bar is still forming.
        new_settled = [b for b in fetched if b.obs_date < today]
        inserted = append_bars(symbol, new_settled)
        if inserted:
            log.debug("price_data: %s appended %d settled bar(s)", symbol, inserted)
            bars = load_bars(symbol)
        elif not bars:
            # Nothing stored and nothing persisted (e.g. yfinance failed) — fall back to the
            # fetched settled bars in-memory so the scan still has data this run.
            bars = sorted(new_settled, key=lambda b: b.obs_date)

    return _to_frame(bars)
