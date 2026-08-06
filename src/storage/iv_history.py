"""Accessors for the iv_history table — latest IV, daily append, and staleness checks.

`iv_history` powers IV Rank/Percentile (the largest single score weight *and* a hard gate,
`min_iv_rank`) and the IV-scaled strike band (N6). It is bootstrapped once by
`scripts/backfill_iv.py` and kept fresh by a daily append in the EOD run (N4) — without that
appender the trailing-year window ages silently and the rank drifts.

Every function swallows storage errors and never raises: this is observability/derived data,
and must not take the trading pipeline down.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select

from src.common.market_hours import today_et
from src.storage.db import session_scope
from src.storage.models import IVHistoryRow

log = logging.getLogger(__name__)


def latest_iv(symbol: str) -> float | None:
    """Most recent stored IV (annualised vol as a fraction, e.g. 0.85 = 85%). None if absent."""
    try:
        with session_scope() as sess:
            return sess.execute(
                select(IVHistoryRow.iv)
                .where(IVHistoryRow.symbol == symbol)
                .order_by(IVHistoryRow.obs_date.desc())
                .limit(1)
            ).scalar_one_or_none()
    except Exception:
        log.debug("latest_iv failed for %s", symbol, exc_info=True)
        return None


def append_observation(symbol: str, obs_date: date, iv: float | None, source: str = "ibkr") -> bool:
    """Insert one daily IV observation. Skips if (symbol, obs_date) already exists or iv is
    non-positive. Returns True only when a row was inserted. Never raises."""
    if iv is None or iv <= 0:
        return False
    try:
        with session_scope() as sess:
            exists = sess.execute(
                select(IVHistoryRow.id).where(
                    IVHistoryRow.symbol == symbol, IVHistoryRow.obs_date == obs_date
                )
            ).first()
            if exists is not None:
                return False
            sess.add(IVHistoryRow(symbol=symbol, obs_date=obs_date, iv=float(iv), source=source))
            return True
    except Exception:
        log.warning("append_observation failed for %s", symbol, exc_info=True)
        return False


def latest_obs_dates(symbols: list[str]) -> dict[str, date]:
    """Map each symbol with any history to its most recent obs_date (one grouped query)."""
    if not symbols:
        return {}
    try:
        with session_scope() as sess:
            rows = sess.execute(
                select(IVHistoryRow.symbol, func.max(IVHistoryRow.obs_date))
                .where(IVHistoryRow.symbol.in_(symbols))
                .group_by(IVHistoryRow.symbol)
            ).all()
            return {sym: d for sym, d in rows if d is not None}
    except Exception:
        log.debug("latest_obs_dates failed", exc_info=True)
        return {}


def stale_symbols(symbols: list[str], max_age_days: int) -> list[tuple[str, int | None]]:
    """Symbols whose newest IV observation is older than *max_age_days* (or missing entirely).

    Returns (symbol, age_in_days) pairs; age is None when the symbol has no history at all.
    Sorted oldest/most-missing first so a `/health` warning surfaces the worst offenders.
    """
    today = today_et()
    latest = latest_obs_dates(symbols)
    out: list[tuple[str, int | None]] = []
    for sym in symbols:
        d = latest.get(sym)
        if d is None:
            out.append((sym, None))
        else:
            age = (today - d).days
            if age > max_age_days:
                out.append((sym, age))
    # Missing (None) first, then largest age.
    out.sort(key=lambda t: (t[1] is not None, -(t[1] or 0)))
    return out
