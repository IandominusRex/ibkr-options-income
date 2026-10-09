"""Index/ticker quotes for alerts and digests. Deterministic; reads src/data only."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel

from src.common.market_hours import today_et
from src.data.factory import get_price_provider


class Quote(BaseModel):
    symbol: str
    last: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None


def prev_close_from(df: pd.DataFrame, today: date) -> float | None:
    if df is None or df.empty or "Close" not in df:
        return None
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    last_day = pd.Timestamp(closes.index[-1]).date()
    if last_day >= today:
        return float(closes.iloc[-2]) if len(closes) >= 2 else None
    return float(closes.iloc[-1])


def quote(symbol: str, *, today: date | None = None) -> Quote:
    p = get_price_provider()
    day = today or today_et()
    try:
        last = p.get_last_price(symbol)
    except Exception:
        last = None
    try:
        prev = prev_close_from(p.get_ohlcv(symbol, lookback_days=10), day)
    except Exception:
        prev = None
    chg = (last / prev - 1) * 100 if last is not None and prev else None
    return Quote(symbol=symbol, last=last, prev_close=prev, change_pct=chg)


def tape(symbols: list[str], *, today: date | None = None) -> dict[str, Quote]:
    return {s: quote(s, today=today) for s in symbols}
