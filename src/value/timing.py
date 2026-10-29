"""Entry timing (spec §6.6): strict for deep value, soft for quality growth. Pure: no I/O.

A hard gate on both lists: a READY whose timing does not pass is WATCH.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.common.config import ValueTimingCfg
from src.common.value_types import PriceSeries
from src.value.schemas import Check


def sessions_between(start: date, end: date) -> int:
    """Weekdays in [start, end): the sessions before *end* counting *start* (holidays are not
    known here, so this errs by at most a day or two)."""
    n, d = 0, start
    while d < end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def earnings_check(as_of: date, next_earnings: date | None, cfg: ValueTimingCfg) -> Check:
    """Refused within ``earnings_window_sessions`` sessions before earnings. A missing date,
    or one already past with no newer one, is UNKNOWN, never a pass."""
    window = float(cfg.earnings_window_sessions)
    if next_earnings is None:
        return Check(
            id="timing.earnings", state="unknown", threshold=window, detail="no earnings date"
        )
    if next_earnings < as_of:
        # yfinance returns the last report until the next is announced. A report this recent
        # means the next one is a quarter away, well past the window.
        ago = (as_of - next_earnings).days
        if ago <= cfg.recent_report_days:
            return Check(
                id="timing.earnings",
                state="pass",
                threshold=window,
                detail=f"inferred: reported {ago} days ago ({next_earnings}), next not yet dated",
            )
        return Check(
            id="timing.earnings",
            state="unknown",
            threshold=window,
            detail=f"last known earnings date {next_earnings} has passed",
        )
    n = sessions_between(as_of, next_earnings)
    return Check(
        id="timing.earnings",
        state="fail" if n <= cfg.earnings_window_sessions else "pass",
        actual=float(n),
        threshold=window,
        detail=f"earnings {next_earnings}",
    )


def _low_index(closes: list[float]) -> int:
    """Index of the lowest close (the latest one on a tie)."""
    low = min(closes)
    return max(i for i, c in enumerate(closes) if c == low)


def deep_value_timing(
    price: PriceSeries | None, rs_cutoff: float | None, cfg: ValueTimingCfg
) -> list[Check]:
    """Strict: (above the 200-day SMA, or 6-month relative strength vs SPY not in the bottom
    30% of the run) and has stopped falling (a close above its 20-day SMA after the low of the
    last ``low_lookback_sessions``)."""
    if price is None:
        return [
            Check(id="timing.trend", state="unknown"),
            Check(id="timing.stopped_falling", state="unknown"),
        ]
    checks: list[Check] = []
    if price.sma200 is not None and price.close > price.sma200:
        checks.append(
            Check(
                id="timing.trend",
                state="pass",
                actual=price.close,
                threshold=price.sma200,
                detail="above the 200-day SMA",
            )
        )
    elif price.ret_6m is None or price.spy_ret_6m is None or rs_cutoff is None:
        checks.append(
            Check(
                id="timing.trend",
                state="unknown",
                detail="below or without a 200-day SMA; relative strength not computable",
            )
        )
    else:
        excess = price.ret_6m - price.spy_ret_6m
        checks.append(
            Check(
                id="timing.trend",
                state="pass" if excess >= rs_cutoff else "fail",
                actual=excess,
                threshold=rs_cutoff,
                detail="6-month return less SPY's, against the run's bottom-30% line",
            )
        )
    window = price.closes[-cfg.low_lookback_sessions :]
    smas = price.sma20s[-cfg.low_lookback_sessions :]
    if len(window) < cfg.low_lookback_sessions:
        checks.append(
            Check(id="timing.stopped_falling", state="unknown", detail="too little history")
        )
    else:
        low = _low_index(window)
        after = [
            (c, s) for c, s in zip(window[low + 1 :], smas[low + 1 :], strict=True) if s is not None
        ]
        recovered = any(c > s for c, s in after)
        checks.append(
            Check(
                id="timing.stopped_falling",
                state="pass" if recovered else "fail",
                actual=float(len(window) - 1 - low),
                detail="sessions since the low; passes on a close above the 20-day SMA after it",
            )
        )
    return checks


def growth_timing(price: PriceSeries | None, cfg: ValueTimingCfg) -> list[Check]:
    """Soft: refused only below the 200-day SMA and at a new 52-week low (the lowest close of
    the last 252 sessions set within the last ``new_low_window_sessions``)."""
    if price is None or price.sma200 is None:
        return [Check(id="timing.not_breaking_down", state="unknown")]
    year = price.closes[-252:]
    low = _low_index(year)
    new_low = (len(year) - 1 - low) < cfg.new_low_window_sessions
    below = price.close < price.sma200
    return [
        Check(
            id="timing.not_breaking_down",
            state="fail" if (below and new_low) else "pass",
            actual=price.close,
            threshold=price.sma200,
            detail="below the 200-day SMA and at a new 52-week low"
            if (below and new_low)
            else "not both below the 200-day SMA and at a new 52-week low",
        )
    ]
