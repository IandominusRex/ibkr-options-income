"""Refresh the persisted market regime from the classifier (trading process only).

``refresh_regime`` is the one function that moves the regime. The scan calls it at the start of
every cycle; the order poll calls ``refresh_regime_cached`` so a regime that escalated between a
card and its send is seen at send time. Rules (pinned in the plan, Task 2, rulings 40-41):

1. **Daily base** — recomputed once per ET trading day (when ``base_date`` is not today) with
   ``classify_base``. The new day starts from *yesterday's base*, never yesterday's effective
   regime, so an intraday escalation expires at the close. A stricter classification takes effect
   at once; easing is one notch at a time and only after ``ease_contango_days`` consecutive
   contango closes *and* ``min_days_in_regime`` days since the base last changed.
2. **Intraday** — ``effective = stricter(base, today's escalation, the previous effective if it
   is the same ET day)``: one-way within the day, and only within the day.
3. **Missing inputs** — when the daily fetch yields nothing for an index the previous
   ``IndexRegime`` is kept unchanged (a warning is logged and the fetch is retried next call);
   with no previous state the index is NORMAL, flagged ``no_data``. A regime that cannot be
   computed never reads as calmer than the last one known, and never blocks closing risk.
4. A change of ``effective`` appends an unsent ``RegimeChange`` and sets ``since``; the base
   moving sets ``base_since``.
5. Every write goes through ``update_regime_state`` (one lock around load-modify-save).

Network I/O (the two fetchers) happens *outside* that lock; the rules above are then applied to
whatever the latest persisted state is.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd

from src.analytics.regime import (
    ORDER,
    classify_base,
    ease_one,
    fetch_daily_inputs,
    fetch_live_inputs,
    get_bars,
    intraday_escalation,
    stricter,
)
from src.common.config import RegimeThresholdsCfg, get_regime_cfg
from src.common.market_hours import is_trading_day
from src.common.schemas import (
    IndexRegime,
    MarketRegime,
    RegimeChange,
    RegimeInputs,
    RegimeState,
)
from src.storage.regime_state import load_regime_state, update_regime_state

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
IndexName = Literal["SPY", "QQQ"]
INDICES: tuple[IndexName, ...] = ("SPY", "QQQ")
_LIVE_FIELDS = ("index_live", "day_change_pct", "live_vol")
_MAX_CHANGES = 50

DailyFetch = Callable[[IndexName], RegimeInputs]
LiveFetch = Callable[..., dict[str, Any]]

_cache_lock = threading.Lock()
_cache: tuple[float, RegimeState] | None = None


def _rank(r: MarketRegime) -> int:
    return ORDER.index(r)


def _et_date(now: datetime) -> date:
    """The ET calendar date of *now* (a naive datetime is taken as ET, like ``is_rth``)."""
    if now.tzinfo is None:
        return now.date()
    return now.astimezone(_ET).date()


def _empty(inp: RegimeInputs | None) -> bool:
    """True when the daily fetch produced nothing usable for the classifier."""
    return inp is None or (inp.index_close is None and inp.vol is None and inp.term_ratio is None)


def clear_regime_cache() -> None:
    """Forget the cached refresh (tests; a restart does it anyway)."""
    global _cache
    with _cache_lock:
        _cache = None


# --------------------------------------------------------------------------- #
# the rules
# --------------------------------------------------------------------------- #


def _next_base(
    prev: IndexRegime | None,
    cls: MarketRegime,
    inp: RegimeInputs,
    today: date,
    th: RegimeThresholdsCfg,
) -> tuple[MarketRegime, date, bool]:
    """Rule 1: ``(base, base_since, eased)`` for a freshly classified day."""
    if prev is None:
        return cls, today, False
    if _rank(cls) > _rank(prev.base):
        return cls, today, False  # stricter: at once
    if _rank(cls) < _rank(prev.base):
        long_enough = (today - prev.base_since).days >= th.min_days_in_regime
        if inp.contango_streak >= th.ease_contango_days and long_enough:
            return ease_one(prev.base), today, True  # one notch only
    return prev.base, prev.base_since, False


def _next_index(
    index: IndexName,
    prev: IndexRegime | None,
    daily: RegimeInputs | None,
    live: dict[str, Any] | None,
    now: datetime,
    today: date,
    th: RegimeThresholdsCfg,
) -> tuple[IndexRegime, RegimeChange | None]:
    new_day = prev is None or prev.base_date != today
    base_why: list[str] = []
    eased = False

    if new_day:
        if prev is not None and not is_trading_day(today):
            # The market is closed: nothing new to classify. The day rolls over, so the last
            # session's intraday escalation expires.
            base, base_since = prev.base, prev.base_since
            daily_inputs = prev.inputs
            carry: MarketRegime | None = None
        elif _empty(daily):
            if prev is not None:
                log.warning("regime: no daily inputs for %s — keeping the last known regime", index)
                return prev, None
            # Never computed and no data: NORMAL, flagged. base_date stays "yesterday" so the
            # next refresh retries the daily fetch instead of treating the day as done.
            inputs = daily if daily is not None else RegimeInputs()
            return (
                IndexRegime(
                    index=index,
                    base=MarketRegime.NORMAL,
                    base_date=today - timedelta(days=1),
                    since=today,
                    base_since=today,
                    effective=MarketRegime.NORMAL,
                    escalated_by=["no_data"],
                    inputs=inputs,
                ),
                None,
            )
        else:
            assert daily is not None
            cls, base_why = classify_base(daily, th)
            base, base_since, eased = _next_base(prev, cls, daily, today, th)
            daily_inputs = daily
            carry = None
    else:
        assert prev is not None
        base, base_since = prev.base, prev.base_since
        daily_inputs = prev.inputs
        carry = prev.effective  # one-way within the day

    # Merge today's live fields; a missing live fetch is stale, never calm.
    daily_stale = [s for s in daily_inputs.stale if s not in _LIVE_FIELDS]
    if live is None:
        live = {name: None for name in _LIVE_FIELDS} | {"stale": list(_LIVE_FIELDS)}
    inp = daily_inputs.model_copy(
        update={
            "index_live": live.get("index_live"),
            "day_change_pct": live.get("day_change_pct"),
            "live_vol": live.get("live_vol"),
            "stale": list(dict.fromkeys([*daily_stale, *live.get("stale", [])])),
        }
    )

    esc, esc_why = intraday_escalation(index, inp, th)
    effective = stricter(base, esc)
    if carry is not None:
        effective = stricter(effective, carry)

    triggers = [w for w in esc_why if not w.startswith("stale:")]
    if _rank(effective) <= _rank(base):
        escalated_by: list[str] = []
    elif triggers:
        escalated_by = triggers
    else:
        escalated_by = list(prev.escalated_by) if prev is not None and carry is not None else []

    before = prev.effective if prev is not None else MarketRegime.NORMAL
    changed = effective != before
    change: RegimeChange | None = None
    if changed:
        if _rank(effective) > _rank(before):
            why = escalated_by if _rank(effective) > _rank(base) and escalated_by else base_why
        elif eased:
            why = [f"easing after {daily_inputs.contango_streak} days of contango", *base_why]
        else:
            why = ["intraday escalation ended"]
        change = RegimeChange(
            index=index, before=before, after=effective, why=why or ["base regime changed"], at=now
        )

    return (
        IndexRegime(
            index=index,
            base=base,
            base_date=today,
            since=today if changed or prev is None else prev.since,
            base_since=base_since,
            effective=effective,
            escalated_by=escalated_by,
            eased_by_bottoming=prev.eased_by_bottoming if prev else False,
            bottoming_cancelled_on=prev.bottoming_cancelled_on if prev else None,
            inputs=inp,
        ),
        change,
    )


def _apply(
    cur: RegimeState | None,
    now: datetime,
    today: date,
    fetched: dict[IndexName, tuple[RegimeInputs | None, dict[str, Any] | None]],
    th: RegimeThresholdsCfg,
) -> RegimeState:
    changes = list(cur.changes) if cur else []
    out: dict[IndexName, IndexRegime] = {}
    for index in INDICES:
        prev = (cur.spy if index == "SPY" else cur.qqq) if cur else None
        daily, live = fetched[index]
        new, change = _next_index(index, prev, daily, live, now, today, th)
        out[index] = new
        if change is not None:
            changes.append(change)
    return RegimeState(as_of=now, spy=out["SPY"], qqq=out["QQQ"], changes=changes[-_MAX_CHANGES:])


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #


def refresh_regime(
    now: datetime,
    *,
    fetch_daily: DailyFetch = fetch_daily_inputs,
    fetch_live: LiveFetch = fetch_live_inputs,
    fetch_bars: Callable[[str], pd.DataFrame] = get_bars,
) -> RegimeState:
    """Bring the persisted regime up to date for *now* and return it.

    The daily inputs are fetched only when an index's ``base_date`` is not today; the live
    inputs on every call. Never raises for a data problem (a failed fetch keeps the last known
    regime); a database failure propagates, and the callers log it and carry on.

    ``fetch_bars`` is the bar source for the bottoming signal (a later task); the classifier
    itself reads bars through ``fetch_daily``.
    """
    del fetch_bars  # used by the bottoming signal (Task 7); accepted now so callers need not change
    th = get_regime_cfg().thresholds
    today = _et_date(now)
    prev = load_regime_state()

    fetched: dict[IndexName, tuple[RegimeInputs | None, dict[str, Any] | None]] = {}
    for index in INDICES:
        p = (prev.spy if index == "SPY" else prev.qqq) if prev else None
        # A closed market has nothing new to classify, so only a trading day (or the very first
        # run) pays for the daily fetch.
        needs_daily = p is None or (p.base_date != today and is_trading_day(today))
        daily: RegimeInputs | None = None
        if needs_daily:
            try:
                daily = fetch_daily(index)
            except Exception:
                log.warning("regime: daily inputs for %s failed", index, exc_info=True)
            if _empty(daily):
                fetched[index] = (daily, None)  # nothing to classify: no live fetch either
                continue
            base_inputs = daily
        else:
            assert p is not None
            base_inputs = p.inputs
        assert base_inputs is not None
        live: dict[str, Any] | None = None
        try:
            live = fetch_live(
                index, base_inputs.index_close, now=now, prior_vol_close=base_inputs.vol
            )
        except Exception:
            log.warning("regime: live inputs for %s failed", index, exc_info=True)
        fetched[index] = (daily, live)

    return update_regime_state(lambda cur: _apply(cur, now, today, fetched, th))


def refresh_regime_cached(now: datetime, max_age_s: float = 60.0) -> RegimeState | None:
    """``refresh_regime`` with a short cache, for the ~30 s order poll.

    Returns the cached state when it is younger than *max_age_s*. If the refresh itself fails
    (a locked database), the last persisted state is returned (None when there is none): the
    regime never blocks closing risk and never raises into the send path.
    """
    global _cache
    mono = time.monotonic()
    with _cache_lock:
        if _cache is not None and mono - _cache[0] < max_age_s:
            return _cache[1]
    try:
        state = refresh_regime(now)
    except Exception:
        log.warning("regime: refresh failed — using the last known regime", exc_info=True)
        return load_regime_state()
    with _cache_lock:
        _cache = (mono, state)
    return state


__all__ = [
    "INDICES",
    "clear_regime_cache",
    "refresh_regime",
    "refresh_regime_cached",
]
