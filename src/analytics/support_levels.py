"""Support levels from swing lows on daily lows (deterministic tier).

The scale-in ladder (`src/analytics/scale_in.py`) and the bottoming signal
(`src/analytics/bottoming.py`) need "the nearest support below this price". The older
`technicals._support_resistance` cannot carry that: it works on closes, needs +-30-bar local
minima (a level appears about six weeks after it forms), keeps the three most *recent* levels
rather than the nearest below the price, and after a fresh selloff returns the uptrend's higher
lows, all above spot. This module is the replacement for gating; the old function stays for its
display uses.

Algorithm (spec section 6, pinned):

1. For each window ``w`` in *windows*, a bar ``i`` with ``w <= i <= len - 1 - w`` is a **swing
   low** when ``Low[i] == min(Low[i - w : i + w + 1])``; its level is that low.
2. Levels closer than ``merge_atr x ATR`` are merged (the lower one is kept).
3. A level is **broken** and dropped when a later daily close is below
   ``level - broken_atr x ATR`` (`broken`).
4. Levels at or above *spot* are dropped; the rest are returned nearest first, at most
   *max_levels* of them.

Pure: no I/O, no config, no network. Reads only the bars it is handed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.technicals import _atr14


def broken(level: float, closes_after: pd.Series, atr: float, broken_atr: float) -> bool:
    """True when any close in *closes_after* is more than ``broken_atr x atr`` under *level*."""
    if closes_after is None or len(closes_after) == 0:
        return False
    return bool((closes_after.astype(float) < level - broken_atr * atr).any())


def _swing_lows(lows: np.ndarray, windows: tuple[int, ...]) -> dict[int, float]:
    """``{bar index: level}`` for every swing low at any of *windows* (first window wins a tie)."""
    found: dict[int, float] = {}
    n = len(lows)
    for w in windows:
        if w < 1 or n < 2 * w + 1:
            continue
        for i in range(w, n - w):
            if not np.isfinite(lows[i]):
                continue
            if lows[i] == np.nanmin(lows[i - w : i + w + 1]):
                found.setdefault(i, float(lows[i]))
    return found


def support_levels(
    bars: pd.DataFrame,
    *,
    spot: float,
    windows: tuple[int, ...] = (3, 5, 10),
    merge_atr: float = 0.5,
    atr: float | None = None,
    max_levels: int = 5,
    broken_atr: float = 1.0,
) -> list[float]:
    """Support levels strictly below *spot*, nearest first, broken levels excluded.

    *bars* is a daily OHLC frame (ascending, with ``Low`` and ``Close``). *atr* defaults to the
    ATR-14 of *bars*; with too little history to compute one, no level is claimed (``[]``).
    *broken_atr* is ``regime.ladder.broken_atr`` (callers pass the configured value; 1.0 is the
    shipped default).
    """
    if bars is None or len(bars) == 0 or "Low" not in bars.columns or "Close" not in bars.columns:
        return []
    if atr is None:
        atr = _atr14(bars["High"], bars["Low"], bars["Close"]) if "High" in bars.columns else None
    if atr is None or not np.isfinite(atr) or atr <= 0:
        return []

    lows = bars["Low"].astype(float).to_numpy()
    closes = bars["Close"].astype(float).reset_index(drop=True)
    swings = sorted(_swing_lows(lows, windows).items(), key=lambda kv: (kv[1], kv[0]))

    merged: list[tuple[int, float]] = []
    for idx, level in swings:  # ascending by level: the lower one of a close pair is met first
        if merged and level - merged[-1][1] < merge_atr * atr:
            continue
        merged.append((idx, level))

    kept = [
        level
        for idx, level in merged
        if level < spot and not broken(level, closes.iloc[idx + 1 :], atr, broken_atr)
    ]
    return sorted(kept, reverse=True)[:max_levels]
