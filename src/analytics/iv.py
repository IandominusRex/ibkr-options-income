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

from src.common.cache import daily_cached
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

    # Prefer the LIVE ATM IV (from the chain) over the last stored daily observation so the
    # rank reflects current conditions intraday, not yesterday's close. Falls back to the
    # stored value when no chain is supplied (e.g. analytics-only callers).
    live_iv = _live_atm_iv(quotes) if quotes else None
    current_iv = live_iv if live_iv is not None else history[0]

    sorted_hist = sorted(history)
    min_iv = sorted_hist[0]
    max_iv = sorted_hist[-1]

    iv_rank: float | None = None
    if max_iv != min_iv:
        # Clamp: a live IV can punch through the trailing-year range (rank would exceed 100).
        raw_rank = (current_iv - min_iv) / (max_iv - min_iv) * 100
        iv_rank = round(max(0.0, min(100.0, raw_rank)), 2)

    below = sum(1 for h in history if h < current_iv)
    # Require at least 30 observations for a meaningful percentile rank.
    # With fewer points, percentile moves in large steps (e.g. 20-point jumps
    # with 5 observations) and is not actionable.
    iv_percentile = round(below / len(history) * 100, 2) if len(history) >= 30 else None

    hv_30 = _compute_hv30(symbol)
    term_slope, skew = _chain_stats(symbol, quotes) if quotes else (None, None)

    current_iv_pct = round(current_iv * 100, 4)
    vrp = round(current_iv_pct - hv_30, 4) if hv_30 is not None else None

    return IVStats(
        symbol=symbol,
        current_iv=current_iv_pct,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        hv_30=hv_30,
        vrp=vrp,
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


@daily_cached
def _compute_hv30(symbol: str) -> float | None:
    """30-day historical volatility (annualised %) from yfinance closes.

    Cached per calendar day — HV30 only moves on a new daily close, so the intraday
    loop reuses the day's value instead of re-pulling 3 months of history each cycle.
    """
    try:
        df = yf.Ticker(symbol).history(period="3mo")
        if df.empty or len(df) < 31:
            log.debug("hv30: insufficient history for %s (%d rows)", symbol, len(df))
            return None
        # Log returns are standard for volatility (log-normal assumption matches
        # IBKR's IV model); simple returns overstate HV for high-move names.
        pct = (df["Close"] / df["Close"].shift(1)).apply(math.log).dropna()
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
    """Estimate the underlying spot price from the option chain.

    Uses put-call parity on same-strike/expiry pairs: spot ≈ strike + call_mid − put_mid.
    Takes the median across all available pairs for robustness. Falls back to the
    tightest-spread option's strike only when no call/put pair exists.
    """
    from collections import defaultdict

    pairs: dict[tuple[float, object], dict[OptionRight, float]] = defaultdict(dict)
    for q in quotes:
        if q.mid is not None:
            pairs[(q.strike, q.expiry)][q.right] = q.mid

    parity_spots: list[float] = []
    for (strike, _expiry), sides in pairs.items():
        call_mid = sides.get(OptionRight.CALL)
        put_mid = sides.get(OptionRight.PUT)
        if call_mid is not None and put_mid is not None:
            parity_spots.append(strike + call_mid - put_mid)

    if parity_spots:
        parity_spots.sort()
        return parity_spots[len(parity_spots) // 2]  # median

    # Fallback: no paired strikes — use the tightest-spread option's strike (rough).
    candidates = [q for q in quotes if q.mid is not None and q.spread_pct is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda q: q.spread_pct or 999).strike


def _live_atm_iv(quotes: list[OptionQuote]) -> float | None:
    """Live at-the-money IV from the chain: mean IV of the strikes nearest spot in the
    nearest expiry. Used as the current point for IV rank/percentile. None if uncomputable."""
    if not quotes:
        return None
    spot = _infer_spot(quotes)
    if spot is None:
        return None
    near_dte = min((q.dte for q in quotes if q.dte > 0), default=None)
    if near_dte is None:
        return None
    candidates = [q for q in quotes if q.dte == near_dte and q.iv is not None and q.iv > 0]
    if not candidates:
        return None
    # Take the strikes closest to spot (within the ATM band), average their IVs.
    candidates.sort(key=lambda q: abs(q.strike - spot))
    nearest = candidates[: min(4, len(candidates))]
    return sum(q.iv for q in nearest) / len(nearest)  # type: ignore[misc]


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
