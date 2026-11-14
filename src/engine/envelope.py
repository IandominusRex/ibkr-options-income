"""The risk envelope: the glide L(t), the admission test and the daily record (risk-envelope plan
Task 13; spec §3.4.1-3.4.2, §3.4.7, rulings E4, E5, H1, H8, P1, P3, Q4).

Deterministic, no LLM. Nothing here places, prices or sizes an order: ``admits`` returns reasons
and ``max_contracts_under`` a count that a generator or the Rules Engine applies (Tasks 18-20).

* ``room(inputs, *, today)`` -> ``EnvelopeRoom``. ``enforce`` is the ``envelope_enforce`` switch.
  When ``on`` and no glide record exists, the glide is started from this measurement (only when
  the book is fully measured); the limits are then the glide's for *today*. In ``record`` (and
  ``off``) the limits are computed as if the glide started today, so the would-block record
  (P1) has something to compare with. A missing IV, an unreadable glide record or no record
  while ``on`` makes the room unmeasured: every admission then reads ``envelope_unmeasured``.
* ``admits(room, inputs, add)``: ``shock_budget`` when S10_gross after the trade is above L(t)
  **and** the trade raises S10 (spec §3.4.1: while the book is above L(t), only openings that do
  not raise S10 pass, so a covered call is never blocked); ``gross_budget`` likewise for U_ew;
  ``t20_budget`` when the ``t20_limit`` switch is on (H8; T20_gross against the same L(t));
  ``envelope_unmeasured`` first, alone, when anything cannot be valued.
* ``max_contracts_under`` (P3): the largest count of a line that ``admits`` passes, and the
  reason that binds the next contract.
* ``record_snapshot`` writes the measurement record; ``check_t20_trigger`` is H8's one-time
  switch.

Deterministic tier: imports no enrichment (``tests/test_regime_fence.py``).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from typing import Literal

from src.analytics.shock import measure
from src.common.config import get_config, get_envelope_cfg
from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs, ShockResult
from src.storage.envelope_state import (
    limits_on,
    load_glide,
    save_snapshot,
    start_glide,
    start_levels,
)
from src.storage.envelope_switches import get_switch, set_switch, switch_record

log = logging.getLogger(__name__)

SHOCK_BUDGET = "shock_budget"
GROSS_BUDGET = "gross_budget"
T20_BUDGET = "t20_budget"
UNMEASURED = "envelope_unmeasured"
_EPS = 1e-9


def room(
    inputs: ShockInputs,
    *,
    today: date,
    may_start: bool = True,
    result: ShockResult | None = None,
) -> EnvelopeRoom:
    """The book against today's limits. *may_start* False never writes the glide record (the
    stored-IV display snapshot must not start the glide; only the live measurement may)."""
    enforce = get_switch("envelope_enforce")
    res = result if result is not None else measure(inputs)
    cfg = get_envelope_cfg()
    reasons = [f"unmeasured:{s}" for s in res.unmeasured]
    would_be = start_levels(res, s10_target=cfg.s10_target_pct, uew_target=cfg.uew_target)
    glide_ok = True
    if enforce == "on":
        try:
            rec = load_glide()
            if rec is None and may_start and res.measured:
                rec = start_glide(res, today)
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
    t20_lim = s10_lim if get_switch("t20_limit") == "on" else None
    return EnvelopeRoom(
        s10_gross=res.s10,
        s10_limit=s10_lim,
        uew=res.uew,
        uew_limit=uew_lim,
        t20_gross=res.t20,
        t20_limit=t20_lim,
        enforce=enforce,
        measured=res.measured and glide_ok,
        reasons_if_unmeasured=tuple(reasons),
    )


def _above(after: float, limit: float, before: float) -> bool:
    return after > limit + _EPS and after > before + _EPS


def admits(room: EnvelopeRoom, inputs: ShockInputs, add: list[BookLine]) -> list[str]:
    """The envelope reasons the book plus *add* would carry (empty = admitted). The caller
    applies them (``on``) or records them (``record``)."""
    if not room.measured:
        return [UNMEASURED]
    after = measure(replace(inputs, lines=inputs.lines + tuple(add)))
    if not after.measured:
        return [UNMEASURED]
    reasons: list[str] = []
    if _above(after.s10, room.s10_limit, room.s10_gross):
        reasons.append(SHOCK_BUDGET)
    if _above(after.uew, room.uew_limit, room.uew):
        reasons.append(GROSS_BUDGET)
    if room.t20_limit is not None and _above(after.t20, room.t20_limit, room.t20_gross):
        reasons.append(T20_BUDGET)
    return reasons


def max_contracts_under(
    room: EnvelopeRoom, inputs: ShockInputs, line_for_one: BookLine, hard_max: int
) -> tuple[int, str]:
    """P3: the largest n <= *hard_max* for which n x *line_for_one* is admitted, and the reason
    that stops n + 1 (``""`` when *hard_max* fits)."""
    for n in range(1, max(0, hard_max) + 1):
        reasons = admits(room, inputs, [replace(line_for_one, qty=line_for_one.qty * n)])
        if reasons:
            return n - 1, reasons[0]
    return max(0, hard_max), ""


def cash_after_itm_assignment(cash: float, inputs: ShockInputs) -> float:
    """Spec §3.4.7 (E11): the account's cash after every in-the-money short put is assigned
    (strike x 100 x contracts paid out for each put whose strike is above its spot)."""
    owed = sum(
        (ln.strike or 0.0) * 100.0 * abs(ln.qty)
        for ln in inputs.lines
        if ln.kind == "short_put" and ln.strike and ln.spot and ln.strike > ln.spot
    )
    return cash - owed


def record_snapshot(
    result: ShockResult,
    room: EnvelopeRoom,
    source: Literal["stored", "live"],
    *,
    nlv: float | None = None,
    cash_after_itm: float | None = None,
) -> None:
    """Write the measurement record (``envelope_snapshots``). Never raises."""
    save_snapshot(
        result,
        source=source,
        enforce=room.enforce,
        measured=room.measured,
        s10_limit=room.s10_limit,
        uew_limit=room.uew_limit,
        t20_limit=room.t20_limit,
        nlv=nlv,
        cash_after_itm=cash_after_itm,
        reasons=room.reasons_if_unmeasured,
    )


def check_t20_trigger(result: ShockResult) -> str | None:
    """H8: the first measured session on which T20_gross - S10_gross exceeds
    ``envelope.t20_trigger_points`` (3.0) turns the ``t20_limit`` switch on (paper), once.

    Returns the notice text when it does, else None. A switch that already has a record (the
    trigger fired before, or the operator set it by hand) is never touched (P11); nothing fires
    on an unmeasured result or in live.
    """
    if not result.measured:
        return None
    try:
        if get_config().is_live:
            return None
        points = get_envelope_cfg().t20_trigger_points
        gap = result.t20 - result.s10
        if gap <= points or switch_record("t20_limit") is not None:
            return None
        set_switch("t20_limit", "on", source="trigger:t20")
    except Exception:
        log.warning("envelope: the T20 trigger check failed", exc_info=True)
        return None
    return (
        f"Envelope: T20 {result.t20:.1f}% is {gap:.1f} points above S10 {result.s10:.1f}% "
        f"(trigger {points:.1f}). t20_limit -> on (paper; record-only in live): T20_gross <= L(t) "
        "is now an admission test. Reverse: python -m scripts.envelope switch t20_limit off"
    )
