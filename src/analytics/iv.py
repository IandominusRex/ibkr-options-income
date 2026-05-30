"""IV Rank, IV Percentile, 30-day historical vol, term structure slope, put/call skew.

IV Rank and Percentile are computed from the iv_history table (seeded by scripts/backfill_iv.py),
not from per-contract model Greeks. Term structure and skew require live OptionQuote objects
and are left None when the chain is unavailable.
"""

from __future__ import annotations

import logging
import math

import yfinance as yf
from sqlalchemy import select

from src.common.schemas import IVStats, OptionQuote, OptionRight
from src.storage.db import session_scope
from src.storage.models import IVHistoryRow

log = logging.getLogger(__name__)


def get_iv_stats(symbol: str, quotes: list[OptionQuote] | None = None) -> IVStats:
    """Return IV statistics for *symbol*.

    Reads iv_history for rank/percentile. Computes hv_30 from yfinance closes.
    Optionally enriches term_structure_slope and put_call_skew from *quotes*.
    """
    history = _load_iv_history(symbol)

    if not history:
        return IVStats(symbol=symbol)

    current_iv = history[0]
    sorted_hist = sorted(history)
    min_iv = sorted_hist[0]
    max_iv = sorted_hist[-1]

    iv_rank: float | None = None
    if max_iv != min_iv:
        iv_rank = round((current_iv - min_iv) / (max_iv - min_iv) * 100, 2)

    below = sum(1 for h in history[1:] if h < current_iv)
    iv_percentile = round(below / max(len(history) - 1, 1) * 100, 2) if len(history) > 1 else None

    hv_30 = _compute_hv30(symbol)
    term_slope, skew = _chain_stats(symbol, quotes) if quotes else (None, None)

    return IVStats(
        symbol=symbol,
        current_iv=round(current_iv * 100, 4),  # store as percentage
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        hv_30=hv_30,
        term_structure_slope=term_slope,
        put_call_skew=skew,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _load_iv_history(symbol: str) -> list[float]:
    """Return up to 365 IV values ordered most-recent first."""
    try:
        with session_scope() as sess:
            rows = (
                sess.execute(
                    select(IVHistoryRow.iv)
                    .where(IVHistoryRow.symbol == symbol)
                    .order_by(IVHistoryRow.obs_date.desc())
                    .limit(365)
                )
                .scalars()
                .all()
            )
            return list(rows)
    except Exception:
        return []


def _compute_hv30(symbol: str) -> float | None:
    """30-day historical volatility (annualised %) from yfinance closes."""
    try:
        df = yf.Ticker(symbol).history(period="3mo")
        if df.empty or len(df) < 31:
            log.debug("hv30: insufficient history for %s (%d rows)", symbol, len(df))
            return None
        pct = df["Close"].pct_change().dropna()
        hv = pct.rolling(30).std().iloc[-1] * math.sqrt(252) * 100
        return round(float(hv), 4)
    except Exception as exc:
        log.warning("hv30: failed for %s: %s", symbol, exc)
        return None


def _chain_stats(symbol: str, quotes: list[OptionQuote]) -> tuple[float | None, float | None]:
    """Compute term structure slope and put/call skew from a live option chain."""
    if not quotes:
        return None, None

    # Infer spot from tightest-spread ATM options
    spot = _infer_spot(quotes)
    if spot is None:
        return None, None

    term_slope = _term_structure_slope(quotes, spot)
    skew = _put_call_skew(quotes)
    return term_slope, skew


def _infer_spot(quotes: list[OptionQuote]) -> float | None:
    """Estimate spot from the mid of the tightest-spread near-the-money options."""
    candidates = [q for q in quotes if q.mid is not None and q.spread_pct is not None]
    if not candidates:
        return None
    tightest = min(candidates, key=lambda q: q.spread_pct or 999)
    return tightest.strike  # close enough for ATM selection


def _term_structure_slope(quotes: list[OptionQuote], spot: float) -> float | None:
    """Linear slope of (dte, mean_iv) for near-ATM options. Positive = contango."""
    atm_band = 0.05 * spot
    atm = [q for q in quotes if abs(q.strike - spot) <= atm_band and q.iv is not None and q.dte > 0]
    if not atm:
        return None

    from collections import defaultdict

    by_expiry: dict[int, list[float]] = defaultdict(list)
    for q in atm:
        by_expiry[q.dte].append(q.iv)  # type: ignore[arg-type]

    if len(by_expiry) < 2:
        return None

    xs = [dte for dte in by_expiry]
    ys = [sum(ivs) / len(ivs) for dte, ivs in by_expiry.items()]
    # Simple linear regression slope
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom
    return round(slope, 6)


def _put_call_skew(quotes: list[OptionQuote]) -> float | None:
    """Mean(put IV at ~0.30 delta) - mean(call IV at ~0.30 delta). Positive = put premium."""
    target_delta = 0.30
    delta_tol = 0.10

    puts = [
        q
        for q in quotes
        if q.right == OptionRight.PUT
        and q.delta is not None
        and q.iv is not None
        and abs(abs(q.delta) - target_delta) <= delta_tol
    ]
    calls = [
        q
        for q in quotes
        if q.right == OptionRight.CALL
        and q.delta is not None
        and q.iv is not None
        and abs(abs(q.delta) - target_delta) <= delta_tol
    ]

    if not puts or not calls:
        return None

    mean_put_iv = sum(q.iv for q in puts) / len(puts)  # type: ignore[misc]
    mean_call_iv = sum(q.iv for q in calls) / len(calls)  # type: ignore[misc]
    return round(mean_put_iv - mean_call_iv, 4)
