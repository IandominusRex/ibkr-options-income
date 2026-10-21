"""Build the `SizingContext` the sizer and the Rules Engine read (deterministic tier).

One context is built per scan (and one per send-time batch, with ``for_send=True``). It carries
what the pure functions in `src/engine/regime_limits.py` need: the persisted effective regimes,
the suspension switch, today's CSP and guaranteed-floor counts per governing index, and the
leveraged-ETF map. Everything is read from the trading database; nothing is fetched from the
network. A scan builds it after the regime refresh, so it sees the regime that scan ran under.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session

from src.common.config import get_config, get_leveraged_sizing_cfg, get_regime_cfg
from src.common.schemas import MarketRegime, OrderState, PositionSnapshot, SizingContext, Strategy
from src.storage.models import OrderRow
from src.storage.regime_state import load_regime_state, regime_suspended

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_DEFAULT_LEVERAGE = 3  # a leveraged ETF missing from the operator's map: the strictest factor

# Names already warned about, so a missing map entry is said once per process, not every scan.
_WARNED_UNMAPPED: set[str] = set()


def _et_date(now: datetime) -> date:
    return now.date() if now.tzinfo is None else now.astimezone(_ET).date()


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """[start, end) of the ET trading day as UTC datetimes (orders are stored in UTC)."""
    nxt = day + timedelta(days=1)
    start = datetime(day.year, day.month, day.day, tzinfo=_ET).astimezone(UTC)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=_ET).astimezone(UTC)
    return start, end


def _todays_csp_snapshots(session: Session, today: date, *, for_send: bool) -> list[dict[str, Any]]:
    """Snapshots of today's CSP opening orders that count toward the day's limits.

    States submitted / partial / filled, plus queued at decision time. At send time the queued
    orders *are* the batch being re-validated, so they are not counted (the gate adds each
    accepted candidate as it walks the batch).
    """
    start, end = _day_bounds_utc(today)
    states = [OrderState.SUBMITTED.value, OrderState.PARTIAL.value, OrderState.FILLED.value]
    if not for_send:
        states.append(OrderState.QUEUED.value)
    rows = (
        session.query(OrderRow.snapshot)
        .filter(
            OrderRow.created_at >= start,
            OrderRow.created_at < end,
            OrderRow.state.in_(states),
            OrderRow.candidate_id.notlike("close:%"),
        )
        .all()
    )
    return [
        snap
        for (snap,) in rows
        if isinstance(snap, dict) and snap.get("strategy") == Strategy.CASH_SECURED_PUT.value
    ]


def _bucket(snapshot: dict[str, Any], tech_linked: list[str]) -> str:
    tech = {t.upper() for t in tech_linked}
    return "QQQ" if str(snapshot.get("underlying", "")).upper() in tech else "SPY"


def csp_opens_counted(
    session: Session, today: date, *, for_send: bool, tech_linked: list[str]
) -> dict[str, int]:
    """Today's CSP opens per governing index (QQQ for a tech-linked name, SPY otherwise)."""
    counts: dict[str, int] = {}
    for snap in _todays_csp_snapshots(session, today, for_send=for_send):
        key = _bucket(snap, tech_linked)
        counts[key] = counts.get(key, 0) + 1
    return counts


def floor_lots_counted(
    session: Session, today: date, *, for_send: bool, tech_linked: list[str]
) -> dict[str, int]:
    """Today's guaranteed-floor lots per governing index (snapshots with ``sizing.floor_lot``)."""
    counts: dict[str, int] = {}
    for snap in _todays_csp_snapshots(session, today, for_send=for_send):
        sizing = snap.get("sizing")
        if isinstance(sizing, dict) and sizing.get("floor_lot"):
            key = _bucket(snap, tech_linked)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _leverage_map() -> dict[str, int]:
    """``universe.leveraged_etfs`` -> daily leverage, from the operator's map (3x if unmapped)."""
    mapping = get_leveraged_sizing_cfg().leverage
    out: dict[str, int] = {}
    for raw in get_config().universe.get("leveraged_etfs") or []:
        symbol = str(raw).upper()
        factor = mapping.get(symbol)
        if factor is None:
            factor = _DEFAULT_LEVERAGE
            if symbol not in _WARNED_UNMAPPED:
                _WARNED_UNMAPPED.add(symbol)
                log.warning(
                    "leveraged_sizing: %s is in universe.leveraged_etfs but missing from "
                    "risk_limits.yaml leveraged_sizing.leverage — treating it as %dx (the "
                    "strictest); add it to the map to set its factor",
                    symbol,
                    _DEFAULT_LEVERAGE,
                )
        out[symbol] = factor
    return out


def build_sizing_context(
    *,
    now: datetime,
    session: Session,
    for_send: bool = False,
    symbols: list[str] | None = None,
    positions: list[PositionSnapshot] | None = None,
    bars: dict[str, pd.DataFrame] | None = None,
) -> SizingContext | None:
    """The sizing context for a scan (or, with ``for_send=True``, a send-time re-gate).

    ``None`` only when every switch that wants a context is off (``regime.enabled`` and
    ``leveraged_sizing.enabled`` today; the covered-call timing switches join them later). The
    regimes are the persisted effective regimes (both NORMAL when none was ever stored). A
    database failure propagates: the callers fail closed (no scan) rather than size without the
    regime.

    *symbols*, *positions* and *bars* are for the scale-in ladder (a later task) and unused here.
    """
    del symbols, positions, bars
    regime_cfg = get_regime_cfg()
    if not regime_cfg.enabled and not get_leveraged_sizing_cfg().enabled:
        return None
    today = _et_date(now)
    state = load_regime_state(session)
    if state is not None:
        regimes = {"SPY": state.spy.effective, "QQQ": state.qqq.effective}
    else:
        regimes = {"SPY": MarketRegime.NORMAL, "QQQ": MarketRegime.NORMAL}
    return SizingContext(
        regimes=regimes,
        tech_linked=list(regime_cfg.tech_linked),
        suspended=regime_suspended(today),
        csp_opens_counted=csp_opens_counted(
            session, today, for_send=for_send, tech_linked=regime_cfg.tech_linked
        ),
        floor_lots_counted=floor_lots_counted(
            session, today, for_send=for_send, tech_linked=regime_cfg.tech_linked
        ),
        leverage=_leverage_map(),
        for_send=for_send,
    )
