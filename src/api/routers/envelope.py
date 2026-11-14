"""GET /envelope: the risk envelope as the trading process last measured it (risk-envelope plan
Task 14; spec §3.4, §3.4.7).

Read-only, owner-only. Everything comes from the trading database through the API's read-only
session: the latest ``envelope_snapshots`` rows (live IV and stored IV), the glide record and the
switches from ``system_settings`` (resolved with the trading process's own rule,
``envelope_switches.resolve_switch``, so a live account reads every switch's default here too),
and the latest Leveraged Entry Signal rows with the newest breadth reading. Nothing is computed
from market data and nothing is written. With no snapshot the measures are ``null``, never 0.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import OwnerUser, TradingDb
from src.api.models.envelope import (
    RiskEnvelopeGlide,
    RiskEnvelopeLes,
    RiskEnvelopeLimits,
    RiskEnvelopeResponse,
    RiskEnvelopeSnapshot,
    RiskEnvelopeSwitch,
)
from src.api.settings_read import read_setting
from src.common.config import get_config, get_envelope_cfg
from src.common.envelope_types import EnvelopeSnapshot
from src.storage.envelope_state import (
    GLIDE_KEY,
    glide_span,
    limits_on,
    parse_glide,
    snapshot_from_row,
)
from src.storage.envelope_switches import KEY_PREFIX, SWITCHES, parse_record, resolve_switch
from src.storage.models import BreadthCountRow, EnvelopeSnapshotRow, LesSignalRow

router = APIRouter(tags=["envelope"])

_ET = ZoneInfo("America/New_York")
_LES_INDICES = ("QQQ", "SOXX")


def _now() -> datetime:
    return datetime.now(UTC)


def _latest(db: Session, source: str) -> EnvelopeSnapshot | None:
    row = db.execute(
        select(EnvelopeSnapshotRow)
        .where(EnvelopeSnapshotRow.source == source)
        .order_by(EnvelopeSnapshotRow.captured_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return snapshot_from_row(row) if row is not None else None


def _out(snap: EnvelopeSnapshot | None) -> RiskEnvelopeSnapshot | None:
    if snap is None:
        return None
    r = snap.result
    return RiskEnvelopeSnapshot(
        captured_at=snap.captured_at,
        source=snap.source,
        measured=snap.measured,
        enforce=snap.enforce,
        s10=r.s10,
        s10_net=r.s10_net,
        s10_vol10=r.s10_vol10,
        s10_vol10_net=r.s10_vol10_net,
        s20=r.s20,
        s20_net=r.s20_net,
        g10=r.g10,
        g10_net=r.g10_net,
        p20=r.p20,
        p20_net=r.p20_net,
        t20=r.t20,
        t20_net=r.t20_net,
        s_smh=r.s_smh,
        s_smh_net=r.s_smh_net,
        uew=r.uew,
        nlv=snap.nlv,
        unmeasured=list(r.unmeasured),
        reasons=list(snap.reasons),
    )


def _pick(
    live: EnvelopeSnapshot | None, stored: EnvelopeSnapshot | None
) -> EnvelopeSnapshot | None:
    """The live measurement when it is from the same ET day as (or newer than) the stored one."""
    if live is None:
        return stored
    if stored is None:
        return live
    same_or_newer = (
        live.captured_at.astimezone(_ET).date() >= stored.captured_at.astimezone(_ET).date()
    )
    return live if same_or_newer else stored


def _switches(db: Session, live: bool) -> list[RiskEnvelopeSwitch]:
    out: list[RiskEnvelopeSwitch] = []
    for name, (default, _allowed) in SWITCHES.items():
        rec = parse_record(read_setting(db, f"{KEY_PREFIX}{name}"))
        out.append(
            RiskEnvelopeSwitch(
                name=name,
                value=resolve_switch(name, rec, live=live),
                default=default,
                source=str(rec.get("source")) if rec and rec.get("source") else "default",
                set_at=str(rec.get("set_at")) if rec and rec.get("set_at") else None,
            )
        )
    return out


def _les(db: Session) -> list[RiskEnvelopeLes]:
    osc = db.execute(
        select(BreadthCountRow.day, BreadthCountRow.osc)
        .where(BreadthCountRow.osc.is_not(None))
        .order_by(BreadthCountRow.day.desc())
        .limit(1)
    ).first()
    out: list[RiskEnvelopeLes] = []
    for index in _LES_INDICES:
        row = db.execute(
            select(LesSignalRow)
            .where(LesSignalRow.index_symbol == index)
            .order_by(LesSignalRow.asof.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            continue
        out.append(
            RiskEnvelopeLes(
                index=row.index_symbol,
                asof=row.asof,
                trend_up=row.trend_up,
                pullback=row.pullback,
                washout=row.washout,
                trend_break=row.trend_break,
                tier_pct=row.tier_pct,
                reasons=list(row.reasons or []),
                breadth_osc=float(osc[1]) if osc is not None else None,
                breadth_asof=osc[0] if osc is not None else None,
            )
        )
    return out


@router.get("/envelope", response_model=RiskEnvelopeResponse)
def get_envelope(_user: OwnerUser, db: TradingDb) -> RiskEnvelopeResponse:
    now = _now()
    cfg = get_envelope_cfg()
    live_acct = get_config().is_live
    live = _latest(db, "live")
    stored = _latest(db, "stored")
    snap = _pick(live, stored)
    switches = _switches(db, live_acct)
    enforce = next(s.value for s in switches if s.name == "envelope_enforce")

    glide = None
    raw = read_setting(db, GLIDE_KEY)
    if raw:
        try:
            rec = parse_glide(raw)
        except ValueError:
            rec = None
        if rec is not None:
            today = now.astimezone(_ET).date()
            span = glide_span(rec, today)
            s10_today, uew_today = limits_on(rec, today)
            glide = RiskEnvelopeGlide(
                start=span.start,
                end=span.end,
                week=span.week,
                weeks=span.weeks,
                s10_start=rec.s10_start,
                uew_start=rec.uew_start,
                s10_today=s10_today,
                uew_today=uew_today,
            )

    return RiskEnvelopeResponse(
        as_of=snap.captured_at if snap is not None else now,
        snapshot=_out(snap),
        live=_out(live),
        stored=_out(stored),
        limits=RiskEnvelopeLimits(
            s10=snap.s10_limit if snap is not None else None,
            uew=snap.uew_limit if snap is not None else None,
            t20=snap.t20_limit if snap is not None else None,
            s10_target=cfg.s10_target_pct,
            uew_target=cfg.uew_target,
        ),
        enforce=enforce,
        glide=glide,
        switches=switches,
        cash_after_itm_assignment=snap.cash_after_itm if snap is not None else None,
        les=_les(db),
    )
