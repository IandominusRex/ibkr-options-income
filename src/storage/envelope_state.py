"""The envelope's stored state (risk-envelope plan Task 13; spec §3.4.1-3.4.2, rulings E4, E5).

* **The glide record.** JSON in ``system_settings`` key ``envelope_glide``:
  ``{start_date, s10_start, uew_start, weeks, s10_target, uew_target}``. Written once, on the
  first session the ``envelope_enforce`` switch reads ``on`` and the book is fully measured
  (``start_glide`` is idempotent), from S10_gross rounded **up** to a whole percent and U_ew
  rounded up to 0.01 (never below the targets). ``limits_on`` steps the limit down linearly each
  week: ``k = min(weeks, days // 7)``, ``L = start - (start - target) x k / weeks``.
* **The measurement record.** One ``envelope_snapshots`` row per measurement (``save_snapshot``),
  read back as plain ``EnvelopeSnapshot`` data (``latest_snapshot``, ``snapshot_from_row``).
* **Manual buys already reported** (Task 14): the exec ids in ``envelope_manual_buy_seen``.

The pure helpers (``parse_glide``, ``limits_on``, ``glide_end``, ``glide_span``,
``start_levels``, ``snapshot_from_row``) take no session, so the read-only API shares them.
Deterministic tier: imports no enrichment.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from src.common.envelope_types import EnvelopeRoom, EnvelopeSnapshot, GlideSpan, ShockResult
from src.storage.db import session_scope
from src.storage.models import BrokerExecutionRow, EnvelopeSnapshotRow
from src.storage.system_settings import get_setting_strict, set_setting

log = logging.getLogger(__name__)

GLIDE_KEY = "envelope_glide"
MANUAL_BUY_SEEN_KEY = "envelope_manual_buy_seen"
_SEEN_KEEP = 500  # exec ids remembered; older ones fall off (a buy is reported within minutes)


@dataclass(frozen=True, slots=True)
class GlideRecord:
    start_date: date
    s10_start: float
    uew_start: float
    weeks: int
    s10_target: float
    uew_target: float


def round_up(value: float, step: float) -> float:
    """*value* rounded up to a multiple of *step*, tolerant of float noise (1.36 stays 1.36)."""
    return round(math.ceil(round(value / step, 9)) * step, 6)


def start_levels(
    result: ShockResult, *, s10_target: float, uew_target: float
) -> tuple[float, float]:
    """E4/E5: S10_gross rounded up to a whole percent, U_ew up to 0.01, never below a target."""
    return (
        max(round_up(result.s10, 1.0), s10_target),
        max(round_up(result.uew, 0.01), uew_target),
    )


def parse_glide(raw: str) -> GlideRecord:
    """A stored glide record; ``ValueError`` when it is not one."""
    try:
        data = json.loads(raw)
        return GlideRecord(
            start_date=date.fromisoformat(str(data["start_date"])),
            s10_start=float(data["s10_start"]),
            uew_start=float(data["uew_start"]),
            weeks=int(data["weeks"]),
            s10_target=float(data["s10_target"]),
            uew_target=float(data["uew_target"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"unreadable envelope glide record: {raw!r}") from exc


def _dump(rec: GlideRecord) -> str:
    return json.dumps(
        {
            "start_date": rec.start_date.isoformat(),
            "s10_start": rec.s10_start,
            "uew_start": rec.uew_start,
            "weeks": rec.weeks,
            "s10_target": rec.s10_target,
            "uew_target": rec.uew_target,
        }
    )


def load_glide() -> GlideRecord | None:
    """The glide record, or None when none was ever written. Raises when the settings table
    cannot be read or the row is unparseable: the caller fails closed, it never restarts the
    glide over a record it could not read."""
    raw = get_setting_strict(GLIDE_KEY)
    if raw is None:
        return None
    return parse_glide(raw)


def start_glide(result: ShockResult, today: date) -> GlideRecord:
    """Write the glide record from *result* unless one exists (idempotent: the existing record
    is returned unchanged). Refuses (``ValueError``) an unmeasured result."""
    existing = load_glide()
    if existing is not None:
        return existing
    if not result.measured:
        raise ValueError(f"cannot start the glide on an unmeasured book: {result.unmeasured}")
    from src.common.config import get_envelope_cfg

    cfg = get_envelope_cfg()
    s10, uew = start_levels(result, s10_target=cfg.s10_target_pct, uew_target=cfg.uew_target)
    rec = GlideRecord(today, s10, uew, cfg.glide_weeks, cfg.s10_target_pct, cfg.uew_target)
    set_setting(GLIDE_KEY, _dump(rec))
    if load_glide() != rec:
        raise RuntimeError("the envelope glide record did not persist")
    log.warning(
        "envelope: glide started %s, S10 %.1f%% -> %.1f%%, U_ew %.2f -> %.2f over %d weeks",
        today,
        s10,
        rec.s10_target,
        uew,
        rec.uew_target,
        rec.weeks,
    )
    return rec


def _step(rec: GlideRecord, day: date) -> int:
    return max(0, min(rec.weeks, (day - rec.start_date).days // 7))


def limits_on(record: GlideRecord, day: date) -> tuple[float, float]:
    """(S10 limit, U_ew limit) on *day*: linear weekly steps to the targets, then the targets."""
    k = _step(record, day)
    s10 = record.s10_start - (record.s10_start - record.s10_target) * k / record.weeks
    uew = record.uew_start - (record.uew_start - record.uew_target) * k / record.weeks
    return s10, uew


def room_for(
    result: ShockResult,
    *,
    enforce: str,
    t20_on: bool,
    today: date,
    may_start: bool,
) -> EnvelopeRoom:
    """The measured book against *today*'s limits (the body of ``engine.envelope.room``, here so
    the value book can share it without importing ``src.engine``: risk-envelope Task 20, C8).

    ``on``: the glide's limits for today; with no record the glide is started from *result* when
    *may_start* and the book is fully measured, else the room is unmeasured (``no_glide_record``);
    an unreadable record is unmeasured (``glide_unreadable``) and never restarted. ``record`` and
    ``off``: the would-be start-of-glide limits (P1). ``t20_on`` puts T20 under the same L(t) (H8).
    """
    from src.common.config import get_envelope_cfg

    cfg = get_envelope_cfg()
    reasons = [f"unmeasured:{s}" for s in result.unmeasured]
    would_be = start_levels(result, s10_target=cfg.s10_target_pct, uew_target=cfg.uew_target)
    glide_ok = True
    if enforce == "on":
        try:
            rec = load_glide()
            if rec is None and may_start and result.measured:
                rec = start_glide(result, today)
        except Exception:
            log.warning("envelope: the glide record is unreadable; failing closed", exc_info=True)
            rec = None
            reasons.append("glide_unreadable")
        if rec is None:
            glide_ok = False
            if "glide_unreadable" not in reasons:
                reasons.append("no_glide_record")
            s10_lim, uew_lim = would_be
        else:
            s10_lim, uew_lim = limits_on(rec, today)
    else:
        s10_lim, uew_lim = would_be
    return EnvelopeRoom(
        s10_gross=result.s10,
        s10_limit=s10_lim,
        uew=result.uew,
        uew_limit=uew_lim,
        t20_gross=result.t20,
        t20_limit=s10_lim if t20_on else None,
        enforce=enforce,
        measured=result.measured and glide_ok,
        reasons_if_unmeasured=tuple(reasons),
    )


def glide_end(record: GlideRecord) -> date:
    return record.start_date + timedelta(days=7 * record.weeks)


def glide_span(record: GlideRecord, day: date) -> GlideSpan:
    """The glide's start, end and the 1-based week *day* falls in (capped at ``weeks``)."""
    week = min(record.weeks, max(0, (day - record.start_date).days) // 7 + 1)
    return GlideSpan(record.start_date, glide_end(record), week, record.weeks)


# --- the measurement record ---------------------------------------------------------------


def save_snapshot(
    result: ShockResult,
    *,
    source: str,
    enforce: str,
    measured: bool,
    s10_limit: float | None,
    uew_limit: float | None,
    t20_limit: float | None,
    nlv: float | None = None,
    cash_after_itm: float | None = None,
    reasons: tuple[str, ...] = (),
    captured_at: datetime | None = None,
) -> None:
    """Write one ``envelope_snapshots`` row. Never raises (a display record)."""
    try:
        with session_scope() as s:
            s.add(
                EnvelopeSnapshotRow(
                    captured_at=(captured_at or datetime.now(UTC)).replace(tzinfo=None),
                    source=source,
                    enforce=enforce,
                    measured=measured,
                    s10=result.s10,
                    s20=result.s20,
                    g10=result.g10,
                    p20=result.p20,
                    t20=result.t20,
                    s_smh=result.s_smh,
                    s10_vol10=result.s10_vol10,
                    s10_net=result.s10_net,
                    s20_net=result.s20_net,
                    g10_net=result.g10_net,
                    p20_net=result.p20_net,
                    t20_net=result.t20_net,
                    s_smh_net=result.s_smh_net,
                    s10_vol10_net=result.s10_vol10_net,
                    uew=result.uew,
                    unmeasured=list(result.unmeasured),
                    unmeasured_net=list(result.unmeasured_net),
                    s10_limit=s10_limit,
                    uew_limit=uew_limit,
                    t20_limit=t20_limit,
                    nlv=nlv,
                    cash_after_itm=cash_after_itm,
                    reasons=list(reasons),
                )
            )
    except Exception:
        log.warning("envelope: snapshot not saved", exc_info=True)


def snapshot_from_row(row: Any) -> EnvelopeSnapshot:
    """An ``EnvelopeSnapshotRow`` as plain data (shared with the read-only API)."""
    captured = row.captured_at
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    return EnvelopeSnapshot(
        captured_at=captured,
        source="live" if row.source == "live" else "stored",
        result=ShockResult(
            s10=row.s10,
            s20=row.s20,
            g10=row.g10,
            p20=row.p20,
            t20=row.t20,
            s_smh=row.s_smh,
            s10_vol10=row.s10_vol10,
            s10_net=row.s10_net,
            s20_net=row.s20_net,
            g10_net=row.g10_net,
            p20_net=row.p20_net,
            t20_net=row.t20_net,
            s_smh_net=row.s_smh_net,
            s10_vol10_net=row.s10_vol10_net,
            uew=row.uew,
            unmeasured=tuple(row.unmeasured or ()),
            unmeasured_net=tuple(row.unmeasured_net or ()),
        ),
        s10_limit=row.s10_limit,
        uew_limit=row.uew_limit,
        t20_limit=row.t20_limit,
        enforce=row.enforce,
        measured=bool(row.measured),
        nlv=row.nlv,
        cash_after_itm=row.cash_after_itm,
        reasons=tuple(row.reasons or ()),
    )


def latest_snapshot(source: str | None = None) -> EnvelopeSnapshot | None:
    """The newest snapshot (of *source* when given), or None. Never raises."""
    try:
        with session_scope() as s:
            q = select(EnvelopeSnapshotRow).order_by(EnvelopeSnapshotRow.captured_at.desc())
            if source is not None:
                q = q.where(EnvelopeSnapshotRow.source == source)
            row = s.execute(q.limit(1)).scalar_one_or_none()
            return snapshot_from_row(row) if row is not None else None
    except Exception:
        log.warning("envelope: latest snapshot unreadable", exc_info=True)
        return None


# --- manual stock buys (Task 14, E13) -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ManualBuy:
    exec_id: str
    symbol: str
    qty: float
    price: float


def _seen() -> list[str]:
    raw = get_setting_strict(MANUAL_BUY_SEEN_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    return [str(x) for x in data] if isinstance(data, list) else []


def new_manual_buys(day: date) -> list[ManualBuy]:
    """Stock buys the system did not place (ledger ``book="manual"``, ``sec_type="STK"``,
    bought, not superseded) on ET *day* whose exec id has not been reported yet."""
    seen = set(_seen())
    with session_scope() as s:
        rows = s.execute(
            select(BrokerExecutionRow)
            .where(
                BrokerExecutionRow.book == "manual",
                BrokerExecutionRow.sec_type == "STK",
                BrokerExecutionRow.quantity > 0,
                BrokerExecutionRow.trade_date == day,
                BrokerExecutionRow.exec_id.is_not(None),
                BrokerExecutionRow.superseded_by.is_(None),
            )
            .order_by(BrokerExecutionRow.trade_time)
        ).scalars()
        return [
            ManualBuy(str(r.exec_id), r.underlying.upper(), float(r.quantity), float(r.price))
            for r in rows
            if str(r.exec_id) not in seen
        ]


def mark_manual_buys_seen(exec_ids: list[str]) -> None:
    """Remember *exec_ids* as reported (the newest ``_SEEN_KEEP`` are kept)."""
    if not exec_ids:
        return
    merged = [x for x in _seen() if x not in set(exec_ids)] + list(exec_ids)
    set_setting(MANUAL_BUY_SEEN_KEY, json.dumps(merged[-_SEEN_KEEP:]))
