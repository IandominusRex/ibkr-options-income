"""SPY's calendar-month tendency: the average return of a month and the share of years it closed up.

A **weak signal**, labelled so wherever it is shown (the market picture renders it as
"Seasonality (weak signal)" and the picture prompt forbids using it as a reason). Deterministic
tier: a pure computation over daily bars read through ``src/data``, importing no enrichment
module (``src.claude``, ``src.news``, sentiment, macro). Today only the market picture reads it;
nothing in the engine, execution or sizing does.

The price provider caps a lookback at five years (``yfinance_backend``), so the view reports how
many years it actually covers; most calendar months have four or five completed observations.
"""

from __future__ import annotations

import logging

import pandas as pd

from src.common.cache import daily_cached
from src.common.schemas import SeasonalityView
from src.data.factory import get_price_provider

log = logging.getLogger(__name__)

_SYMBOL = "SPY"
_LOOKBACK_DAYS = 365 * 6  # asks for six years; the provider returns what it holds (five)


def _month_end_closes(bars: pd.DataFrame) -> dict[tuple[int, int], float]:
    """Each completed calendar month's last close, keyed by (year, month), oldest first. The
    month the newest bar falls in is still forming, so it is dropped."""
    if bars is None or bars.empty or "Close" not in bars:
        return {}
    closes = bars["Close"].dropna()
    if closes.empty:
        return {}
    idx = pd.DatetimeIndex(closes.index)
    last_by_month: dict[tuple[int, int], float] = {}
    for ts, close in sorted(zip(idx, closes.to_numpy(), strict=True), key=lambda t: t[0]):
        last_by_month[(ts.year, ts.month)] = float(close)
    newest = max(last_by_month)
    return {k: v for k, v in sorted(last_by_month.items()) if k < newest}


@daily_cached
def month_seasonality(month: int, *, years: int = 5) -> SeasonalityView | None:
    """SPY's average return in calendar *month* over its most recent *years* completed years.

    A month's return is its last close over the previous month's last close, so the earliest
    month in the data (no prior close) never counts. ``years`` in the answer is how many months
    actually contributed. None when the history is missing or holds no completed *month*.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    try:
        bars = get_price_provider().get_ohlcv(_SYMBOL, lookback_days=_LOOKBACK_DAYS)
    except Exception:
        log.warning("seasonality: %s history unavailable", _SYMBOL, exc_info=True)
        return None
    ends = _month_end_closes(bars)
    rets: list[tuple[int, float]] = []  # (year, return %) for this calendar month
    keys = list(ends)
    for prev, cur in zip(keys, keys[1:], strict=False):
        if cur[1] != month:
            continue
        # consecutive months only: a gap in the data would make "the month" span two
        if cur[0] * 12 + cur[1] - (prev[0] * 12 + prev[1]) == 1 and ends[prev] > 0:
            rets.append((cur[0], (ends[cur] / ends[prev] - 1.0) * 100.0))
    values = [r for _y, r in sorted(rets)[-years:]]
    if not values:
        return None
    return SeasonalityView(
        month=month,
        avg_return_pct=round(sum(values) / len(values), 2),
        up_share=round(sum(1 for r in values if r > 0) / len(values), 3),
        years=len(values),
    )
