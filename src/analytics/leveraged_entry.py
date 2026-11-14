"""The Leveraged Entry Signal, LES (deterministic tier; risk-envelope Task 10a; spec §3.5.1).

Pure and fail-closed: price bars and breadth in, a `LesSignal` out. It is computed per governing
index G (QQQ for TQQQ, SOXX for SOXL) on each completed daily close. No LLM output reaches it and
nothing in `engine/`, `execution/` or `strategies/` reads it yet: the plan's Task 23 (the sleeve)
and Task 32a (LES shares) will, behind the `leveraged_entry` switch (ships `record`).

| Part | Rule (ruling L1) |
|---|---|
| trend gate | G's close > its 200-day simple average |
| pullback | trend gate and (RSI(2) < 5 or close < the 50-day average) |
| washout | pullback and the Nasdaq-100 breadth oscillator <= -40 on any of the last 5 sessions, with a count dated the last session |
| trend break | the last 2 closes each under that day's 200-day average |

`tier_pct` (ruling L4) is 6.0 with the washout, 3.0 on a pullback, else 0.0. The 1.5 tier below the
200-day is not returned here: no LES share is bought below the trend and the sleeve applies it
only on the bottoming path (`regime_limits`, Task 23).

Fail closed: fewer than ``sma_trend + break_closes - 1`` bars (201 by default, the first bar a
200-day average and the break test both exist), or a missing close in that window, is no signal.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.common.config import LesCfg
from src.common.schemas import LesSignal


def rsi_series(close: pd.Series, n: int) -> pd.Series:
    """Wilder-style RSI over *n* bars for every bar of *close* (``com = n - 1``, i.e. alpha = 1/n).

    Same smoothing as `technicals.rsi14_series`, with the period a parameter. Defined from the first
    bar on; callers that need a trustworthy value check the history length themselves.
    """
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=n - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=n - 1, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def _as_date(ts: object) -> date | None:
    if isinstance(ts, pd.Timestamp):
        return ts.date()
    if isinstance(ts, date):
        return ts
    return None


def _no_signal(index: str, asof: date | None, reason: str) -> LesSignal:
    return LesSignal(
        asof=asof,
        index=index,
        trend_up=False,
        pullback=False,
        washout=False,
        trend_break=False,
        tier_pct=0.0,
        reasons=[reason],
    )


def les_signal(
    bars: pd.DataFrame | None,
    osc_recent: list[tuple[date, float]],
    cfg: LesCfg,
    *,
    index: str = "",
) -> LesSignal:
    """The signal for one governing index.

    *bars*: daily bars ascending, a ``Close`` column and a date-like index (a ``get_ohlcv`` frame).
    *osc_recent*: ``(date, oscillator)`` pairs, the newest breadth readings (warm-up rows omitted).
    """
    if bars is None or bars.empty or "Close" not in bars.columns:
        return _no_signal(index, None, "no price history")
    close = bars["Close"].astype(float)
    asof = _as_date(bars.index[-1])
    need = cfg.sma_trend + cfg.break_closes - 1
    if len(close) < need:
        return _no_signal(index, asof, f"history: {len(close)} bars, need {need} for the 200-day")
    window = close.iloc[-need:]
    if window.isna().any() or not np.isfinite(window.to_numpy()).all():
        return _no_signal(index, asof, "missing close in the last sessions: no signal")

    sma_trend = close.rolling(cfg.sma_trend).mean()
    last, trend = float(close.iloc[-1]), float(sma_trend.iloc[-1])
    trend_up = last > trend
    reasons: list[str] = []
    if trend_up:
        reasons.append(f"trend: close {last:.2f} above the 200-day {trend:.2f}")
    else:
        reasons.append(f"trend: close {last:.2f} not above the 200-day {trend:.2f}: no LES entry")

    # trend break: the last `break_closes` closes each under that day's own 200-day average
    tail_close = close.iloc[-cfg.break_closes :]
    tail_sma = sma_trend.iloc[-cfg.break_closes :]
    trend_break = bool((tail_close < tail_sma).all())
    if trend_break:
        reasons.append(f"trend break: {cfg.break_closes} closes under the 200-day")

    pullback = False
    washout = False
    if trend_up:
        rsi = float(rsi_series(close, cfg.rsi_n).iloc[-1])
        sma_pull = float(close.rolling(cfg.sma_pullback).mean().iloc[-1])
        if np.isfinite(rsi) and rsi < cfg.rsi_max:
            pullback = True
            reasons.append(f"pullback: RSI({cfg.rsi_n}) {rsi:.1f} under {cfg.rsi_max:g}")
        if last < sma_pull:
            pullback = True
            reasons.append(f"pullback: close {last:.2f} under the 50-day {sma_pull:.2f}")
        if pullback:
            washout, why = _washout(bars, osc_recent, cfg)
            reasons.append(why)
        else:
            reasons.append("no pullback: RSI and the 50-day both hold")

    if washout:
        tier = cfg.tiers.washout
    elif pullback:
        tier = cfg.tiers.pullback
    else:
        tier = 0.0
    return LesSignal(
        asof=asof,
        index=index,
        trend_up=trend_up,
        pullback=pullback,
        washout=washout,
        trend_break=trend_break,
        tier_pct=tier,
        reasons=reasons,
    )


def _washout(
    bars: pd.DataFrame, osc_recent: list[tuple[date, float]], cfg: LesCfg
) -> tuple[bool, str]:
    """Whether the breadth washout holds, and the reason either way."""
    if not osc_recent:
        return False, "washout: no breadth count, pullback tier only"
    sessions = [d for d in (_as_date(ts) for ts in bars.index[-cfg.washout_sessions :]) if d]
    asof = sessions[-1]
    newest = max(d for d, _ in osc_recent)
    if newest < asof:
        return False, (
            f"washout: breadth stale (last count {newest}, need {asof}), pullback tier only"
        )
    within = [(d, v) for d, v in osc_recent if d in set(sessions)]
    hits = [(d, v) for d, v in within if v <= cfg.washout_osc]
    if hits:
        d, v = min(hits, key=lambda p: p[1])
        return True, f"washout: breadth oscillator {v:.1f} <= {cfg.washout_osc:g} on {d}"
    low = min((v for _, v in within), default=None)
    seen = f"low {low:.1f}" if low is not None else "no reading"
    return (
        False,
        f"washout: breadth {seen} in the last {cfg.washout_sessions} sessions, not <= {cfg.washout_osc:g}",
    )
