"""Accessors for the iv_history table — latest IV, daily append, and staleness checks.

`iv_history` powers IV Rank/Percentile (the largest single score weight *and* a hard gate,
`min_iv_rank`) and the IV-scaled strike band (N6). It is bootstrapped once by
`scripts/backfill_iv.py` and kept fresh by a daily append in the EOD run (N4) — without that
appender the trailing-year window ages silently and the rank drifts.

**The sanity flag (risk-envelope Task 10, spec §3.10.8, ruling P7).** On 2026-11-05 QQQ's stored
IV collapsed to 14.6% against a VXN of 38.3 and everything that reads this table took it at face
value. `append_observation` now marks an implausible observation `flagged` (the row is still
written, so the unique (symbol, date) constraint keeps the daily append idempotent), logs a warning
and sends one data alert per symbol per ET day. **Every reader skips flagged rows** (`flagged IS
NOT 1`; `tests/test_iv_sanity.py::test_every_reader_skips_flagged_rows` scans `src/` for a reader
that does not). The rule:

* a symbol in ``iv_sanity.vol_index`` (SPY vs ^VIX, QQQ and TQQQ vs ^VXN) is compared by its ratio
  to that index (IV as a fraction over the index close / 100): outside ``index_ratio_band`` (0.6,
  1.4) x the median of its prior 60 sessions' ratios -> flagged;
* every other symbol is flagged when its IV is outside ``single_band`` (0.5, 2.0) x the median of
  its own prior 20 sessions;
* fewer than ``min_history`` (10) prior unflagged rows, or no vol-index close on or within five
  days before the day, means never flagged.

Every function swallows storage errors and never raises: this is observability/derived data,
and must not take the trading pipeline down.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import get_iv_sanity_cfg
from src.common.market_hours import today_et
from src.storage.db import session_scope
from src.storage.models import IVHistoryRow, PriceHistoryRow

log = logging.getLogger(__name__)

_RATIO_SESSIONS = 60  # prior sessions behind an index ETF's median ratio to its vol index
_SINGLE_SESSIONS = 20  # prior sessions behind a single name's median IV
_VOL_CLOSE_MAX_AGE_DAYS = 5  # a vol-index close older than this does not count for a day

# (symbol, ET day) pairs already alerted this process: one notice per symbol per day.
_ALERTED: set[tuple[str, date]] = set()
_BACKGROUND: set[asyncio.Task[bool]] = set()  # keeps a scheduled notice alive until it finishes


def latest_iv(symbol: str) -> float | None:
    """Most recent stored, unflagged IV (annualised vol as a fraction, e.g. 0.85 = 85%). None if absent."""
    try:
        with session_scope() as sess:
            return sess.execute(
                select(IVHistoryRow.iv)
                .where(IVHistoryRow.symbol == symbol, IVHistoryRow.flagged.is_not(True))
                .order_by(IVHistoryRow.obs_date.desc())
                .limit(1)
            ).scalar_one_or_none()
    except Exception:
        log.debug("latest_iv failed for %s", symbol, exc_info=True)
        return None


def _vol_close(sess: Session, vol_symbol: str, day: date) -> float | None:
    """*vol_symbol*'s close on *day*, else its latest close within the last five days."""
    row = sess.execute(
        select(PriceHistoryRow.close)
        .where(
            PriceHistoryRow.symbol == vol_symbol,
            PriceHistoryRow.obs_date <= day,
            PriceHistoryRow.obs_date >= day - timedelta(days=_VOL_CLOSE_MAX_AGE_DAYS),
        )
        .order_by(PriceHistoryRow.obs_date.desc())
        .limit(1)
    ).first()
    if row is None or row[0] is None or row[0] <= 0:
        return None
    return float(row[0])


def _sanity_flag(sess: Session, symbol: str, obs_date: date, iv: float) -> tuple[bool, str]:
    """Whether *iv* is implausible for *symbol* on *obs_date* (P7), and the reason when it is."""
    cfg = get_iv_sanity_cfg()
    vol_symbol = cfg.vol_index.get(symbol)
    if vol_symbol is not None:
        today_vol = _vol_close(sess, vol_symbol, obs_date)
        if today_vol is None:
            return False, ""
        prior = sess.execute(
            select(IVHistoryRow.obs_date, IVHistoryRow.iv)
            .where(
                IVHistoryRow.symbol == symbol,
                IVHistoryRow.obs_date < obs_date,
                IVHistoryRow.flagged.is_not(True),
            )
            .order_by(IVHistoryRow.obs_date.desc())
            .limit(_RATIO_SESSIONS)
        ).all()
        ratios: list[float] = []
        for d, prior_iv in prior:
            v = _vol_close(sess, vol_symbol, d)
            if v is not None:
                ratios.append(float(prior_iv) / (v / 100.0))
        if len(ratios) < cfg.min_history:
            return False, ""
        median = statistics.median(ratios)
        ratio = iv / (today_vol / 100.0)
        lo, hi = cfg.index_ratio_band
        if ratio < lo * median or ratio > hi * median:
            return True, (
                f"IV {iv * 100:.1f}% against {vol_symbol} {today_vol:.1f} is a ratio of {ratio:.2f}; "
                f"its {len(ratios)}-session median is {median:.2f} (band {lo:g}-{hi:g}x)"
            )
        return False, ""
    prior_ivs = [
        float(v)
        for (v,) in sess.execute(
            select(IVHistoryRow.iv)
            .where(
                IVHistoryRow.symbol == symbol,
                IVHistoryRow.obs_date < obs_date,
                IVHistoryRow.flagged.is_not(True),
            )
            .order_by(IVHistoryRow.obs_date.desc())
            .limit(_SINGLE_SESSIONS)
        ).all()
    ]
    if len(prior_ivs) < cfg.min_history:
        return False, ""
    median = statistics.median(prior_ivs)
    lo, hi = cfg.single_band
    if iv < lo * median or iv > hi * median:
        return True, (
            f"IV {iv * 100:.1f}% against its {len(prior_ivs)}-session median {median * 100:.1f}% "
            f"(band {lo:g}-{hi:g}x)"
        )
    return False, ""


def _announce(symbol: str, obs_date: date, detail: str) -> None:
    """One data alert per symbol per ET day, from sync code. Never raises."""
    key = (symbol, today_et())
    if key in _ALERTED:
        return
    _ALERTED.add(key)
    try:
        from src.notify.notices import send_notice

        text = (
            f"IV data alert: {symbol} {obs_date} flagged as implausible and excluded "
            f"from IV rank and every other reader. {detail}"
        )
        coro = send_notice(text)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
        else:
            task = loop.create_task(coro)
            _BACKGROUND.add(task)
            task.add_done_callback(_BACKGROUND.discard)
    except Exception:
        log.warning("IV data alert not sent for %s", symbol, exc_info=True)


def append_observation(symbol: str, obs_date: date, iv: float | None, source: str = "ibkr") -> bool:
    """Insert one daily IV observation. Skips if (symbol, obs_date) already exists or iv is
    non-positive. Returns True only when a row was inserted. Never raises.

    An implausible observation (see the module docstring) is still inserted, marked ``flagged``;
    that is the one reader that must see flagged rows too, because the unique (symbol, date)
    constraint holds for them.
    """
    if iv is None or iv <= 0:
        return False
    flagged, detail = False, ""
    try:
        with session_scope() as sess:
            exists = sess.execute(
                select(IVHistoryRow.id).where(
                    IVHistoryRow.symbol == symbol, IVHistoryRow.obs_date == obs_date
                )
            ).first()
            if exists is not None:
                return False
            try:
                flagged, detail = _sanity_flag(sess, symbol, obs_date, float(iv))
            except Exception:
                log.warning("IV sanity check failed for %s", symbol, exc_info=True)
            sess.add(
                IVHistoryRow(
                    symbol=symbol, obs_date=obs_date, iv=float(iv), source=source, flagged=flagged
                )
            )
    except Exception:
        log.warning("append_observation failed for %s", symbol, exc_info=True)
        return False
    if flagged:
        log.warning("IV observation flagged: %s %s: %s", symbol, obs_date, detail)
        _announce(symbol, obs_date, detail)
    return True


def latest_obs_dates(symbols: list[str]) -> dict[str, date]:
    """Map each symbol with any unflagged history to its most recent obs_date (one grouped query)."""
    if not symbols:
        return {}
    try:
        with session_scope() as sess:
            rows = sess.execute(
                select(IVHistoryRow.symbol, func.max(IVHistoryRow.obs_date))
                .where(IVHistoryRow.symbol.in_(symbols), IVHistoryRow.flagged.is_not(True))
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
