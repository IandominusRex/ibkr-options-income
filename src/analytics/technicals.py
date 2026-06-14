"""Technical indicators: RSI-14, ATR-14, MACD, SMAs, ADX proxy, support/resistance, regime.

All computed from yfinance OHLCV data. No live TWS connection required.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

from src.analytics.price_data import get_ohlcv
from src.common.schemas import Regime, TechnicalStats

_HIGH_VOL_ATR_RATIO = 0.025  # ATR/close > this → HIGH_VOL
_LOW_VOL_ATR_RATIO = 0.008  # ATR/close < this → LOW_VOL
_BULLISH_RSI = 55
_BEARISH_RSI = 45
_SR_WINDOW = 30  # bars for local min/max detection
_SR_LEVELS = 3  # how many support/resistance levels to keep


def get_technical_stats(symbol: str, lookback_days: int = 260) -> TechnicalStats:
    """Return TechnicalStats for *symbol* using the last *lookback_days* of OHLCV."""
    # Settled bars come from the incremental price_history store (only the missing tail is
    # fetched); the live price is fetched fresh and overlaid as today's bar so indicators
    # reflect the current session.
    live_price = _fetch_last_price(symbol)
    df = _working_frame(symbol, live_price)
    if df.empty:
        return TechnicalStats(symbol=symbol, price=live_price or 0.0)

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    # Live quote already fetched above; the working frame's last bar is today's live overlay,
    # so close.iloc[-1] is the current price. Either way the scan-time spot (N17) stays current.
    price = live_price or float(close.iloc[-1])
    rsi = _rsi14(close)
    atr = _atr14(high, low, close)
    macd_line, signal_line = _macd(close)
    sma_20 = _sma(close, 20)
    sma_50 = _sma(close, 50)
    sma_200 = _sma(close, 200)
    atr_ratio = _atr_ratio(atr, price)
    supports, resistances = _support_resistance(close)
    regime = _classify_regime(price, atr, rsi, sma_50, sma_200)

    return TechnicalStats(
        symbol=symbol,
        price=price,
        rsi_14=rsi,
        atr_14=atr,
        macd=macd_line,
        macd_signal=signal_line,
        sma_20=sma_20,
        sma_50=sma_50,
        sma_200=sma_200,
        support_levels=supports,
        resistance_levels=resistances,
        atr_ratio=atr_ratio,
        regime=regime,
    )


# --------------------------------------------------------------------------- #
# Indicator computations
# --------------------------------------------------------------------------- #


def _working_frame(symbol: str, live_price: float | None) -> pd.DataFrame:
    """Settled bars (from the incremental store) plus today's live bar overlaid.

    ``get_ohlcv`` returns only settled sessions (and is day-cached, so the store/yfinance is
    touched at most once per symbol per day). We append a fresh row for the current session
    built from the live price — without mutating the cached frame — so RSI/SMA/regime reflect
    the live quote, matching the prior behaviour where the last 1y bar was today's forming bar.
    """
    settled = get_ohlcv(symbol)
    if live_price is None or live_price <= 0:
        return settled
    today = pd.Timestamp(date.today())
    if not settled.empty and settled.index[-1].normalize() == today.normalize():
        return settled  # already have today (unlikely — store excludes the forming bar)
    today_row = pd.DataFrame(
        {
            "Open": live_price,
            "High": live_price,
            "Low": live_price,
            "Close": live_price,
            "Volume": 0.0,
        },
        index=pd.DatetimeIndex([today]),
    )
    return settled if settled.empty else pd.concat([settled, today_row])


def _fetch_last_price(symbol: str) -> float | None:
    """Cheap live quote via yfinance's fast_info — NOT cached, so it stays current across every
    scan regardless of whether the settled OHLCV history was served from the day cache / store.
    """
    try:
        last = yf.Ticker(symbol).fast_info["lastPrice"]
        return float(last) if last is not None else None
    except Exception:
        return None


def _rsi14(close: pd.Series) -> float | None:
    if len(close) < 15:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rs = gain / loss
    rsi = 100 - 100 / (1 + rs)
    val = float(rsi.iloc[-1])
    return round(val, 2) if np.isfinite(val) else None


def _atr14(high: pd.Series, low: pd.Series, close: pd.Series) -> float | None:
    if len(close) < 15:
        return None
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1
    )
    atr = tr.ewm(com=13, adjust=False).mean()
    val = float(atr.iloc[-1])
    return round(val, 4) if np.isfinite(val) else None


def _macd(close: pd.Series) -> tuple[float | None, float | None]:
    if len(close) < 26:
        return None, None
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    m = float(macd_line.iloc[-1])
    s = float(signal.iloc[-1])
    return (
        round(m, 4) if np.isfinite(m) else None,
        round(s, 4) if np.isfinite(s) else None,
    )


def _sma(close: pd.Series, n: int) -> float | None:
    if len(close) < n:
        return None
    val = float(close.rolling(n).mean().iloc[-1])
    return round(val, 4) if np.isfinite(val) else None


def _atr_ratio(atr: float | None, price: float) -> float | None:
    """Normalised volatility: (ATR / close) × 100. Higher = more volatile (NOT trend strength).

    Renamed from `_adx_proxy` (N16): ATR/price measures range/volatility, not directional trend —
    it was never ADX. Directional regime is classified separately in `_classify_regime`.
    """
    if atr is None or price <= 0:
        return None
    return round(atr / price * 100, 4)


def _support_resistance(close: pd.Series) -> tuple[list[float], list[float]]:
    if len(close) < 50:
        return [], []

    prices: np.ndarray = np.asarray(close.values, dtype=float)
    n = len(prices)
    supports: list[float] = []
    resistances: list[float] = []

    for i in range(_SR_WINDOW, n - _SR_WINDOW):
        window = prices[i - _SR_WINDOW : i + _SR_WINDOW + 1]
        w_min = float(window.min())
        w_max = float(window.max())
        if float(prices[i]) == w_min:
            supports.append(round(float(prices[i]), 2))
        if float(prices[i]) == w_max:
            resistances.append(round(float(prices[i]), 2))

    # Keep the 3 most recent on each side
    return supports[-_SR_LEVELS:], resistances[-_SR_LEVELS:]


def _classify_regime(
    price: float,
    atr: float | None,
    rsi: float | None,
    sma_50: float | None,
    sma_200: float | None,
) -> Regime | None:
    if atr is None:
        return None

    atr_ratio = atr / price if price > 0 else 0

    if atr_ratio > _HIGH_VOL_ATR_RATIO:
        return Regime.HIGH_VOL
    if sma_50 is not None and sma_200 is not None and rsi is not None:
        if price > sma_50 > sma_200 and rsi > _BULLISH_RSI:
            return Regime.BULLISH
        if price < sma_50 < sma_200 and rsi < _BEARISH_RSI:
            return Regime.BEARISH
    if atr_ratio < _LOW_VOL_ATR_RATIO:
        return Regime.LOW_VOL
    return Regime.SIDEWAYS
