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

from src.analytics import regime as regime_data
from src.analytics.scale_in import (
    compute_zone,
    last_broken_support,
    name_drawdown_triggered,
    near_money_short_put,
    recovered,
)
from src.analytics.support_levels import support_levels
from src.analytics.technicals import _atr14, _sma
from src.common.config import (
    RegimeLadderCfg,
    get_config,
    get_leveraged_sizing_cfg,
    get_regime_cfg,
)
from src.common.schemas import (
    MarketRegime,
    OrderState,
    PositionSnapshot,
    ScaleInZone,
    SizingContext,
    Strategy,
)
from src.engine.regime_limits import active, name_regime
from src.regime.anchors import latest_anchor, loss_exits_today, recent_loss_exit_names
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


def _atr(frame: pd.DataFrame) -> float | None:
    if frame is None or frame.empty or not {"High", "Low", "Close"} <= set(frame.columns):
        return None
    return _atr14(frame["High"], frame["Low"], frame["Close"])


def _short_put_names(positions: list[PositionSnapshot]) -> list[str]:
    return sorted(
        {
            (p.underlying or p.symbol).upper()
            for p in positions
            if p.sec_type == "OPT"
            and p.right is not None
            and p.right.value == "P"
            and p.position < 0
        }
    )


def _ladder(
    base: SizingContext,
    *,
    session: Session,
    symbols: list[str],
    positions: list[PositionSnapshot],
    bars: dict[str, pd.DataFrame] | None,
    spots: dict[str, float] | None,
    today: date,
    cfg: RegimeLadderCfg,
) -> tuple[dict[str, list[str]], dict[str, ScaleInZone]]:
    """``(name_triggers, scale_in zones)`` for *symbols* (spec section 6, ruling 37).

    A name is under the ladder when its market regime is one of ``cfg.regimes``, it has fallen
    ``name_drawdown_atr`` ATRs from its recent high, a short put on it is at or near the money,
    or it had a loss exit within ``anchor_survival_days``. Its zone sits below its anchor (the
    last lot); a name with a trigger but no anchor has no zone (the first lot is free) and a
    name whose price has closed ``recovery_closes`` times above its 20-day average and the level
    that last broke, all after the anchor lot, is lifted. With no bars the zone falls back to the
    percentage gap alone (a missing ATR never lifts the ladder). Triggers are returned for every
    name that has one, whether or not it has an anchor: the leveraged-ETF tier reads them.
    """
    frames: dict[str, pd.DataFrame] = dict(bars or {})

    def frame_of(symbol: str) -> pd.DataFrame:
        if symbol not in frames:
            frames[symbol] = regime_data.get_bars(symbol)
        return frames[symbol]

    live: dict[str, float] = dict(spots) if spots is not None else {}
    if spots is None:
        for name in _short_put_names(positions):
            if name in {s.upper() for s in symbols}:
                price = regime_data.last_price(name)
                if price is not None:
                    live[name] = price

    recent_exits = recent_loss_exit_names(session, days=cfg.anchor_survival_days, today=today)
    triggers_out: dict[str, list[str]] = {}
    zones: dict[str, ScaleInZone] = {}
    for symbol in dict.fromkeys(s.upper() for s in symbols):
        frame = frame_of(symbol)
        atr = _atr(frame)
        regime = name_regime(base, symbol)[0] if active(base) else MarketRegime.NORMAL
        trig: list[str] = []
        if regime in cfg.regimes:
            trig.append(f"regime_{regime.value}")
        if atr is not None and name_drawdown_triggered(
            frame, atr, sessions=cfg.name_drawdown_sessions, k_atr=cfg.name_drawdown_atr
        ):
            trig.append("name_drawdown")
        last_close = float(frame["Close"].iloc[-1]) if not frame.empty else None
        spot = live.get(symbol) or last_close
        if (
            atr is not None
            and spot is not None
            and near_money_short_put(positions, symbol, spot, atr, k_atr=cfg.near_money_atr)
        ):
            trig.append("near_money_put")
        if symbol in recent_exits:
            trig.append("recent_loss_exit")
        if not trig:
            continue

        anchor = latest_anchor(
            session,
            symbol,
            positions,
            survival_days=cfg.anchor_survival_days,
            today=today,
            spot=spot,
        )
        if anchor is None:
            triggers_out[symbol] = trig  # the first lot is free, but the tier still reads this
            continue
        price, source, since = anchor
        if atr is not None:
            level = (
                last_broken_support(
                    frame, anchor=price, after=since, atr=atr, broken_atr=cfg.broken_atr
                )
                or price
            )
            if recovered(
                frame,
                sma20=_sma(frame["Close"], 20),
                level=level,
                closes=cfg.recovery_closes,
                after=since,
            ):
                continue  # a confirmed rebound lifts the ladder, whatever its triggers
        supports = (
            support_levels(frame, spot=price, atr=atr, broken_atr=cfg.broken_atr)
            if atr is not None
            else []
        )
        zones[symbol] = compute_zone(
            anchor=price,
            anchor_source=source,
            atr=atr or 0.0,
            supports=supports,
            regime=regime,
            triggers=trig,
            cfg=cfg,
        )
        triggers_out[symbol] = trig
    return triggers_out, zones


def build_sizing_context(
    *,
    now: datetime,
    session: Session,
    for_send: bool = False,
    symbols: list[str] | None = None,
    positions: list[PositionSnapshot] | None = None,
    bars: dict[str, pd.DataFrame] | None = None,
    spots: dict[str, float] | None = None,
) -> SizingContext | None:
    """The sizing context for a scan (or, with ``for_send=True``, a send-time re-gate).

    ``None`` only when every switch that wants a context is off (``regime.enabled`` and
    ``leveraged_sizing.enabled`` today; the covered-call timing switches join them later). The
    regimes are the persisted effective regimes (both NORMAL when none was ever stored). A
    database failure propagates: the callers fail closed (no scan) rather than size without the
    regime.

    *symbols*, *positions*, *bars* and *spots* feed the scale-in ladder (`_ladder`): per-name
    triggers and zones for *symbols*. *bars* maps a symbol to its completed daily bars (default:
    `regime.get_bars`, daily-cached); *spots* maps a symbol to its live price for the
    near-the-money trigger (default: fetched for names with a short put, else the last close).
    ``for_send=True`` fetches no bars: it carries today's loss exits (a cheap query) and leaves
    each card's zone to the order snapshot.
    """
    regime_cfg = get_regime_cfg()
    if not regime_cfg.enabled and not get_leveraged_sizing_cfg().enabled:
        return None
    today = _et_date(now)
    state = load_regime_state(session)
    if state is not None:
        regimes = {"SPY": state.spy.effective, "QQQ": state.qqq.effective}
    else:
        regimes = {"SPY": MarketRegime.NORMAL, "QQQ": MarketRegime.NORMAL}
    ctx = SizingContext(
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
        loss_exit_today=loss_exits_today(session, today=today),
        for_send=for_send,
    )
    if for_send or not symbols:
        return ctx
    triggers, zones = _ladder(
        ctx,
        session=session,
        symbols=symbols,
        positions=positions or [],
        bars=bars,
        spots=spots,
        today=today,
        cfg=regime_cfg.ladder,
    )
    return ctx.model_copy(update={"name_triggers": triggers, "scale_in": zones})
