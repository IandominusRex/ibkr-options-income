"""Upside-breakout detector for the covered-call strike floor (deterministic tier).

A held name has **broken out** when, within the last ``lookback_sessions`` sessions, a daily close
rose at least ``jump_atr`` x ATR-14 (of the day before) on at least ``volume_mult`` x its
20-session average volume, and closed above its nearest resistance (or at a ``high_sessions``
high). The breakout governs the name's covered-call strikes until that many sessions have passed
or the price fades (a later close more than ``fade_atr`` x ATR below the breakout close): the
strike must be at or above `cc_floor` and the delta at most ``delta_max``. Spec section 17 and
decision 28.

It is the mirror of the scale-in ladder: it only ever pushes a strike *out*. It does not stop
covered calls on its own (a name where nothing clears the floor simply sells none that scan), is
not a regime limit, and never touches rolls or puts. Pure: no I/O, no config reads, no network;
the caller hands in the bars and the typed block. It imports nothing from the enrichment tier
(`tests/test_regime_fence.py`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.support_levels import resistance_levels
from src.analytics.technicals import atr14_series
from src.common.config import CcBreakoutCfg
from src.common.schemas import CcBreakout

_MIN_BARS = 30  # fewer bars than this and no breakout is claimed
_VOLUME_WINDOW = 20  # sessions in the average the day's volume is compared with
_ATR_BARS = 15  # ATR-14 is trustworthy from the 15th bar on (as `technicals._atr14`)


def _usable(bars: pd.DataFrame | None, columns: set[str]) -> bool:
    return bars is not None and len(bars) > 0 and columns <= set(bars.columns)


def cc_floor(bars: pd.DataFrame, *, cfg: CcBreakoutCfg) -> float | None:
    """The lowest strike a covered call may use while a breakout lasts, or None without an ATR.

    ``max(nearest resistance above the last close, last close + floor_atr x ATR-14)``: a strike
    that clears the next ceiling the stock has to climb through, and in any case sits at least
    one ATR above the price.
    """
    if not _usable(bars, {"High", "Low", "Close"}) or len(bars) < _ATR_BARS:
        return None
    atr = float(atr14_series(bars["High"], bars["Low"], bars["Close"]).iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        return None
    last = float(bars["Close"].iloc[-1])
    candidates = [last + cfg.floor_atr * atr]
    levels = resistance_levels(bars, spot=last, atr=atr)
    if levels:
        candidates.append(levels[0])
    return round(max(candidates), 4)


def breakout(bars: pd.DataFrame, *, cfg: CcBreakoutCfg) -> CcBreakout | None:
    """The breakout in force on the last bar of *bars*, or None.

    *bars* is a daily OHLCV frame (ascending, completed sessions only, with ``Volume``). For each
    of the last ``lookback_sessions`` sessions ``d``, most recent first, ``d`` is a breakout day
    when the close rose at least ``jump_atr`` x ATR-14 of the day before, on at least
    ``volume_mult`` x the mean of the 20 sessions before it, and either closed above the nearest
    resistance (swing highs of the bars before ``d``, seen from the day before's close) or at the
    highest close of the previous ``high_sessions``. The first match is the trigger; it has
    **ended** (None) when any later close is below ``close[d] - fade_atr x ATR[d]``.
    ``sessions_left`` is ``lookback_sessions`` less the sessions since the trigger. Fewer than 30
    bars, or no ``Volume`` column, is no breakout.
    """
    if not _usable(bars, {"High", "Low", "Close", "Volume"}) or len(bars) < _MIN_BARS:
        return None
    high = bars["High"].astype(float).reset_index(drop=True)
    low = bars["Low"].astype(float).reset_index(drop=True)
    close = bars["Close"].astype(float).reset_index(drop=True)
    volume = bars["Volume"].astype(float).reset_index(drop=True)
    atr = atr14_series(high, low, close)
    n = len(close)
    for since in range(cfg.lookback_sessions):
        d = n - 1 - since
        if d < _VOLUME_WINDOW:
            break
        prev_atr = float(atr.iloc[d - 1])
        if not np.isfinite(prev_atr) or prev_atr <= 0:
            continue
        if float(close.iloc[d] - close.iloc[d - 1]) < cfg.jump_atr * prev_atr:
            continue
        avg_volume = float(volume.iloc[d - _VOLUME_WINDOW : d].mean())
        if not np.isfinite(avg_volume) or avg_volume <= 0:
            continue
        if float(volume.iloc[d]) < cfg.volume_mult * avg_volume:
            continue
        levels = resistance_levels(bars.iloc[:d], spot=float(close.iloc[d - 1]), atr=prev_atr)
        cleared = levels[0] if levels and float(close.iloc[d]) > levels[0] else None
        at_high = d >= cfg.high_sessions and float(close.iloc[d]) >= float(
            close.iloc[d - cfg.high_sessions : d].max()
        )
        if cleared is None and not at_high:
            continue
        # This is the trigger. A later close well under it has ended the breakout.
        if (close.iloc[d + 1 :] < close.iloc[d] - cfg.fade_atr * float(atr.iloc[d])).any():
            return None
        floor = cc_floor(bars, cfg=cfg)
        if floor is None:
            return None
        return CcBreakout(
            trigger_day=pd.Timestamp(bars.index[d]).date(),
            trigger_close=float(close.iloc[d]),
            jump_pct=float((close.iloc[d] / close.iloc[d - 1] - 1.0) * 100.0),
            volume_ratio=float(volume.iloc[d]) / avg_volume,
            broke_level=cleared,
            floor_strike=floor,
            delta_max=cfg.delta_max,
            sessions_left=cfg.lookback_sessions - since,
        )
    return None
