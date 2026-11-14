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
* ``candidate_line`` turns an opening cash-secured put into the ``BookLine`` the admission test
  adds; ``with_added`` returns the room and inputs with an accepted lot in them, so the next
  candidate of a batch is measured against a book that already holds it (Task 18).

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
from src.common.schemas import TradeCandidate
from src.storage.envelope_state import room_for, save_snapshot
from src.storage.envelope_switches import enforce_mode, get_switch, set_switch, switch_record

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
    stored-IV display snapshot must not start the glide; only the live measurement may). The
    arithmetic is ``envelope_state.room_for``, which the value book shares (Task 20)."""
    res = result if result is not None else measure(inputs)
    return room_for(
        res,
        enforce=enforce_mode(),
        t20_on=get_switch("t20_limit") == "on",
        today=today,
        may_start=may_start,
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
    that stops n + 1 (``""`` when *hard_max* fits).

    A short line's loss and U_ew grow with its size, so admission is monotone in n and a binary
    search finds the same n as counting up, in about log2(hard_max) measurements (the generator
    runs this for every viable strike of every scan, Task 19)."""
    top = max(0, hard_max)
    if top == 0:
        return 0, ""

    def refused(n: int) -> list[str]:
        return admits(room, inputs, [replace(line_for_one, qty=line_for_one.qty * n)])

    stop = refused(top)
    if not stop:
        return top, ""
    ok, bad = 0, top  # ok is admitted (0 trivially), bad is refused with *stop*
    while bad - ok > 1:
        mid = (ok + bad) // 2
        found = refused(mid)
        if found:
            bad, stop = mid, found
        else:
            ok = mid
    return ok, stop[0]


def candidate_line(
    cand: TradeCandidate, *, iv: float | None = None, spot: float | None = None
) -> BookLine:
    """The short-put ``BookLine`` an opening CSP adds to the book (Tasks 18-19).

    IV (a decimal) is *iv* when the caller has a fresher one (the send-time quote), else the
    option's own IBKR IV frozen on the card (``quote_iv``); the spot is *spot*, else
    ``underlying_price``, else the ideal zone's spot. A missing IV or spot leaves the line
    unmeasured, so the admission test refuses it (never valued at zero)."""
    use_spot = spot or cand.underlying_price or (cand.ideal.spot if cand.ideal else None)
    use_iv = iv if iv is not None else cand.quote_iv
    return BookLine(
        symbol=cand.underlying.upper(),
        kind="short_put",
        qty=float(max(0, cand.contracts)),
        spot=float(use_spot or 0.0),
        strike=cand.strike,
        dte=cand.dte,
        iv=use_iv if use_iv is not None and use_iv > 0 else None,
        book="wheel",
    )


def with_added(
    room: EnvelopeRoom, inputs: ShockInputs, add: list[BookLine]
) -> tuple[EnvelopeRoom, ShockInputs]:
    """*room* and *inputs* with *add* in the book: the measures move to the book after the trade,
    the limits stay. Used after a lot is accepted, so later lots of the same batch see it."""
    new_inputs = replace(inputs, lines=inputs.lines + tuple(add))
    after = measure(new_inputs)
    return (
        replace(room, s10_gross=after.s10, uew=after.uew, t20_gross=after.t20),
        new_inputs,
    )


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


def without_shares(inputs: ShockInputs, symbol: str, qty: float) -> ShockInputs:
    """*inputs* with *qty* shares of *symbol* taken out of its non-value stock lines (the book
    before a manual buy, E13), never below zero. The value book's lines are left alone."""
    left = qty
    lines: list[BookLine] = []
    for ln in inputs.lines:
        if left > 0 and ln.kind == "stock" and ln.book != "value" and ln.symbol == symbol.upper():
            take = min(left, max(0.0, ln.qty))
            left -= take
            if ln.qty - take > 0:
                lines.append(replace(ln, qty=ln.qty - take))
            continue
        lines.append(ln)
    return replace(inputs, lines=tuple(lines))
