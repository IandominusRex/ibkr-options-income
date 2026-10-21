"""The bottoming signal's pure rules (deterministic tier; spec section 6b).

In a fast drop the system must not simply wait for the slow easing rules. Every scan it looks
for a deterministic sign that a bottom is forming; when one fires it loosens **one notch**:

* `market_bottoming` -- per index, after a VIX spike: the live VIX is well off the spike's peak,
  the curve is back below 1 if it inverted during the spike, and the index holds above the low
  of the selloff's lowest day. The caller (`src/regime/refresh.py`) then eases that index's
  regime one notch.
* `name_bottoming` -- per name already under the scale-in ladder: the price sits at a support
  the ladder would otherwise make it wait past, RSI-14 was oversold lately and has turned up, and
  the last close is above the prior day's high. The caller then lets one lot in at the current
  price (with strict guards, applied by `src/engine/regime_limits.py`).

Plain Python: the signal loosens a limit, so no LLM may produce it. Both functions are pure and
fail closed: a missing live value, a missing history or an unreadable frame is "no signal",
never a guess. Returns ``(fired, reasons)``; the reasons say what held (or the first thing that
did not).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.technicals import rsi14_series
from src.common.config import RegimeBottomingCfg
from src.common.schemas import ScaleInZone


def _closes(frame: pd.DataFrame | None) -> pd.Series | None:
    if frame is None or frame.empty or "Close" not in frame.columns:
        return None
    closes = frame["Close"].astype(float).dropna()
    return closes if len(closes) else None


def market_bottoming(
    *,
    vix: pd.DataFrame,
    vix3m: pd.DataFrame,
    index: pd.DataFrame,
    live_vix: float | None,
    live_index: float | None,
    cfg: RegimeBottomingCfg,
) -> tuple[bool, list[str]]:
    """Whether a market-level bottom is forming for one index (all four conditions must hold).

    1. **A spike**: within the last ``spike_sessions`` VIX closes the peak is at least
       ``vix_spike_pct`` above the lowest close *before* it (a decline from an older peak is not
       a spike).
    2. **A retreat**: ``live_vix`` is at least ``off_peak_pct`` below that peak.
    3. **No inverted curve**: if the VIX/VIX3M ratio was 1 or more on any day in the window,
       the live ratio (``live_vix`` over the last VIX3M close) is below 1. No VIX3M history at
       all is "cannot confirm", i.e. no signal.
    4. **A higher low**: ``live_index`` is above the Low of the window's lowest-close day.
    """
    vix_closes = _closes(vix)
    index_closes = _closes(index)
    if vix_closes is None or index_closes is None:
        return False, ["no VIX or index history"]
    window = vix_closes.iloc[-cfg.spike_sessions :]
    if len(window) < 3:
        return False, ["too little VIX history"]

    values = window.to_numpy()
    peak_pos = int(np.argmax(values))
    peak = float(values[peak_pos])
    base = float(values[: peak_pos + 1].min())
    if peak < base * (1.0 + cfg.vix_spike_pct / 100.0):
        return False, [f"no VIX spike (peak {peak:.1f} vs low {base:.1f} before it)"]

    if live_vix is None:
        return False, ["no live VIX"]
    if live_vix > peak * (1.0 - cfg.off_peak_pct / 100.0):
        return False, [
            f"live VIX {live_vix:.1f} is not {cfg.off_peak_pct:.0f}% under the {peak:.1f} peak"
        ]
    reasons = [
        f"VIX {live_vix:.1f}, {(1.0 - live_vix / peak) * 100.0:.0f}% under its {peak:.1f} spike peak"
    ]

    v3 = _closes(vix3m)
    if v3 is None:
        return False, ["no VIX3M history to confirm the curve"]
    both = pd.concat([window.rename("vix"), v3.rename("v3")], axis=1, join="inner").dropna()
    both = both[both["v3"] > 0]
    if both.empty:
        return False, ["no overlapping VIX and VIX3M closes"]
    if bool((both["vix"] / both["v3"] >= 1.0).any()):
        live_ratio = live_vix / float(v3.iloc[-1])
        if live_ratio >= 1.0:
            return False, [f"VIX/VIX3M still inverted at {live_ratio:.2f}"]
        reasons.append(f"VIX/VIX3M back to {live_ratio:.2f}")

    span = index.loc[index.index >= window.index[0]]
    span_closes = _closes(span)
    if span_closes is None or "Low" not in span.columns:
        return False, ["no index history over the spike window"]
    low_day = span_closes.idxmin()
    low = float(span.loc[low_day, "Low"])
    if live_index is None:
        return False, ["no live index"]
    if live_index <= low:
        return False, [f"index {live_index:.2f} is not above the selloff low {low:.2f}"]
    reasons.append(f"index {live_index:.2f} holding above the {low:.2f} low")
    return True, reasons


def name_bottoming(
    *,
    bars: pd.DataFrame,
    zone: ScaleInZone,
    supports: list[float],
    spot: float,
    atr: float,
    band_atr: float,
    cfg: RegimeBottomingCfg,
) -> tuple[bool, list[str]]:
    """Whether a name-level bottom is forming (all three conditions must hold).

    1. **At a support the ladder would make it wait past**: *spot* is within ``band_atr x atr`` of
       one of *supports* (detected relative to the zone's anchor) that lies **above**
       ``zone.zone_high``. A support at or under the zone top is no signal: the ladder already
       allows a lot there.
    2. **An RSI turn**: RSI-14 was under ``rsi_oversold`` within the last ``rsi_lookback``
       sessions and today's RSI is above yesterday's.
    3. **A reversal bar**: the last completed close is above the prior day's high.
    """
    closes = _closes(bars)
    if closes is None or len(closes) < 16 or "High" not in bars.columns:
        return False, ["too little history"]
    if atr is None or atr <= 0:
        return False, ["no ATR"]
    near = [s for s in supports if s > zone.zone_high and abs(spot - s) <= band_atr * atr]
    if not near:
        return False, [f"{spot:.2f} is not at a support above the {zone.zone_high:.2f} zone top"]
    support = min(near, key=lambda s: abs(spot - s))

    rsi = rsi14_series(closes).dropna()
    if len(rsi) < 2:
        return False, ["no RSI"]
    if float(rsi.iloc[-cfg.rsi_lookback :].min()) >= cfg.rsi_oversold:
        return False, [
            f"RSI was not under {cfg.rsi_oversold:.0f} in the last {cfg.rsi_lookback} sessions"
        ]
    if not float(rsi.iloc[-1]) > float(rsi.iloc[-2]):
        return False, ["RSI has not turned up"]

    last_close = float(closes.iloc[-1])
    prior_high = float(bars["High"].astype(float).iloc[-2])
    if not last_close > prior_high:
        return False, [f"close {last_close:.2f} is not above the prior day's high {prior_high:.2f}"]
    return True, [
        f"at the {support:.2f} support above the {zone.zone_high:.2f} zone top",
        f"RSI turned up from {float(rsi.iloc[-cfg.rsi_lookback :].min()):.0f}",
        f"close {last_close:.2f} above the prior high {prior_high:.2f}",
    ]
