"""IV Rank, IV Percentile, 30-day historical vol, term structure slope, put/call skew.

IV Rank and Percentile are computed from the iv_history table (seeded by scripts/backfill_iv.py),
not from per-contract model Greeks. Term structure and skew require live OptionQuote objects
and are left None when the chain is unavailable.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict

from sqlalchemy import select

from src.analytics.price_data import get_ohlcv
from src.analytics.realized_vol import compute_realized_vol
from src.common.config import get_config
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
    live_iv = _atm_iv_at_30d(quotes) if quotes else None
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

    iv_cfg = get_config().risk.get("iv", {})
    rv_window = int(iv_cfg.get("realized_vol_window", 20))
    realized_vol = compute_realized_vol(symbol, rv_window)
    iv_rv_ratio = (
        round(current_iv_pct / realized_vol, 4)
        if realized_vol is not None and realized_vol > 0
        else None
    )

    return IVStats(
        symbol=symbol,
        current_iv=current_iv_pct,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        hv_30=hv_30,
        vrp=vrp,
        term_structure_slope=term_slope,
        put_call_skew=skew,
        iv_rv_ratio=iv_rv_ratio,
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
    """30-day historical volatility (annualised %) from the settled-close history.

    Reads the shared incremental OHLCV store (`price_data.get_ohlcv`, itself day-cached), so
    HV30 no longer re-pulls 3 months of yfinance history per symbol per scan — it derives from
    the same settled bars the technicals use.
    """
    try:
        df = get_ohlcv(symbol)
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
    spot = infer_spot_from_quotes(quotes)
    if spot is None:
        return None, None

    term_slope = _term_structure_slope(quotes, spot)
    skew = _put_call_skew(quotes)
    return term_slope, skew


def infer_spot_from_quotes(
    quotes: list[OptionQuote], *, require_parity: bool = False
) -> float | None:
    """Estimate the underlying spot price from the option chain.

    Uses put-call parity on same-strike/expiry pairs: spot ≈ strike + call_mid − put_mid.
    Takes the median across all available pairs for robustness. Falls back to the
    tightest-spread option's strike only when no call/put pair exists.

    ``require_parity`` (2026-08-28) returns ``None`` instead of taking that fallback. The
    fallback returns a *strike*, not a price — it is quantized to the chain's strike increment
    ($2.50 on a $150 name), so it can be off by half an increment, ~0.8%. Two classes of caller
    need very different things from this:

    * **Loose** (default) — ``_chain_stats`` / ``_atm_iv_30d`` use spot only to rank strikes by
      ``abs(strike - spot)`` and bucket them. Half a strike increment changes nothing there, and
      returning ``None`` would needlessly drop term-structure slope, skew, and 30-day ATM IV.
    * **Strict** (``require_parity=True``) — callers feeding ``spot_override`` into
      ``get_technical_stats``, whose ``TechnicalStats.price`` becomes the **materiality baseline**
      (``scan_state.last_spot``). There, a strike-quantized value is worse than useless: the
      intraday gate compares that baseline against a fresh yfinance probe, so an ~0.8% quantization
      error swamps the 0.5% ``intraday_rescan_move_pct`` threshold and manufactures phantom moves
      (or masks real ones). ``None`` makes the caller fall through to the yfinance price it already
      holds — which also puts baseline and probe on the *same* source, removing the cross-source
      mismatch entirely.

    This became load-bearing when the chain builder went OTM-only (``_build_chain_contracts``,
    2026-08-28): calls are built only at ``strike >= spot`` and puts only at ``strike <= spot``,
    so a strike carrying **both** rights — the only kind parity can use — no longer exists except
    in the measure-zero case where spot lands exactly on a strike. Parity went from abundant to
    structurally impossible, silently demoting every strict caller to the fallback.
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
    if require_parity:
        return None
    candidates = [q for q in quotes if q.mid is not None and q.spread_pct is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda q: q.spread_pct or 999).strike


_TARGET_DTE = 30  # matches IBKR's OPTION_IMPLIED_VOLATILITY constant-maturity index


def _atm_iv_at_30d(quotes: list[OptionQuote]) -> float | None:
    """Live ATM IV interpolated to a constant 30-day maturity.

    ``iv_history`` stores IBKR's ``OPTION_IMPLIED_VOLATILITY`` daily bar, which is a ~30-day
    constant-maturity ATM index. Ranking the *nearest scanned expiry* (~21-25 DTE, since the
    chain is filtered to the 21-45 DTE window) against that series compares two different
    measurements: in contango it biases IV rank down, and in backwardation it biases it up —
    loosening the gate exactly when the term structure inverts (D6). IV rank is both the
    largest score weight (0.30) and a hard gate, so the two must be the same measurement.

    Linear in DTE between the two expiries bracketing 30 days. With a single expiry, or when
    30 days sits outside the scanned range, returns that expiry's ATM IV unextrapolated.
    """
    if not quotes:
        return None
    spot = infer_spot_from_quotes(quotes)
    if spot is None:
        return None

    by_dte: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for q in quotes:
        if q.dte > 0 and q.iv is not None and q.iv > 0:
            by_dte[q.dte].append((abs(q.strike - spot), q.iv))

    atm_by_dte: dict[int, float] = {}
    for dte, entries in by_dte.items():
        entries.sort(key=lambda e: e[0])  # nearest spot first
        nearest = entries[: min(4, len(entries))]
        atm_by_dte[dte] = sum(iv for _, iv in nearest) / len(nearest)

    if not atm_by_dte:
        return None
    dtes = sorted(atm_by_dte)
    if len(dtes) == 1:
        return atm_by_dte[dtes[0]]

    below = [d for d in dtes if d <= _TARGET_DTE]
    above = [d for d in dtes if d >= _TARGET_DTE]
    if not below:
        return atm_by_dte[above[0]]
    if not above:
        return atm_by_dte[below[-1]]
    lo, hi = below[-1], above[0]
    if lo == hi:
        return atm_by_dte[lo]
    weight = (_TARGET_DTE - lo) / (hi - lo)
    return atm_by_dte[lo] + weight * (atm_by_dte[hi] - atm_by_dte[lo])


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
