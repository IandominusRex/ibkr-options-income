"""Book-repair proposals (risk-envelope Task 30; spec §3.7 item 2, rulings E12, E13, P10).

Pure and deterministic, no LLM, no I/O: the EOD run hands in the book (``ShockInputs``), today's
envelope room and the day's covered-call candidates, and gets back `RepairProposal`s, each with
S10_gross and U_ew before and after it beside today's limits L(t). Nothing here places or gates an
order: a proposal is **tap-only at every autonomy level** (P10). A tapped covered-call overlay
goes through the ordinary approval path (the Rules Engine at decision and send time); a tapped
stop-adding writes a ``universe_overrides`` remove; trims and de-lever (Tasks 31-32) go through the
stock order path, gated by ``risk_engine.validate_stock_order`` twice.

* ``cc_overlay``: the best covered call per underlying among the day's candidates (they already
  passed the screen at the ruled floor, ``covered_call.basis_floor``, and the leveraged carve-out),
  with the envelope after the call is written.
* ``stop_adding``: while S10_gross is above L(t), the names that may still take a new put and
  carry the largest share of S10 (at most ``max_stop_adding``).

``shadow_value`` values a proposal from stored closes, tapped or not: what acting on it would have
earned since it was built.

Deterministic tier: imports no enrichment (``tests/test_regime_fence.py``).
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, datetime

from src.analytics.black_scholes import bs_price
from src.analytics.shock import SCENARIOS, line_pnl, measure, name_move
from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs, ShockResult
from src.common.schemas import RepairProposal, TradeCandidate
from src.engine.envelope import without_shares

MAX_STOP_ADDING = 3
MAX_TRIMS = 3


def s10_by_name(inputs: ShockInputs) -> dict[str, float]:
    """Each name's S10_gross loss in percent of NLV (positive = a loss; long options left out,
    H1). A line that cannot be valued contributes nothing here (the total is ``measure``'s)."""
    if not inputs.nlv > 0:
        return {}
    out: dict[str, float] = {}
    for ln in inputs.lines:
        if ln.kind in ("long_put", "long_call"):
            continue
        try:
            move = name_move(ln.symbol, SCENARIOS["S10"]["index"], inputs, scenario="S10")
        except KeyError:
            continue
        pnl = line_pnl(ln, move)
        if pnl is None:
            continue
        out[ln.symbol.upper()] = out.get(ln.symbol.upper(), 0.0) - pnl / inputs.nlv * 100.0
    return out


def _proposal(
    kind: str,
    symbol: str,
    detail: str,
    before: ShockResult,
    after: ShockResult,
    room: EnvelopeRoom,
    now: datetime,
    **extra: object,
) -> RepairProposal:
    return RepairProposal(
        kind=kind,  # type: ignore[arg-type]
        symbol=symbol.upper(),
        detail=detail,
        s10_before=round(before.s10, 2),
        s10_after=round(after.s10, 2),
        uew_before=round(before.uew, 3),
        uew_after=round(after.uew, 3),
        s10_limit=room.s10_limit if room.measured else None,
        uew_limit=room.uew_limit if room.measured else None,
        created_at=now,
        **extra,  # type: ignore[arg-type]
    )


def call_line(cand: TradeCandidate, spot: float | None) -> BookLine:
    """The short-call line a covered call adds (its own quote IV, else the stored one)."""
    iv = cand.quote_iv
    if iv is None and cand.current_iv:
        iv = cand.current_iv / 100.0
    use_spot = spot or cand.underlying_price or (cand.ideal.spot if cand.ideal else None)
    return BookLine(
        symbol=cand.underlying.upper(),
        kind="short_call",
        qty=float(max(0, cand.contracts)),
        spot=float(use_spot or 0.0),
        strike=cand.strike,
        dte=cand.dte,
        iv=iv if iv is not None and iv > 0 else None,
        book="wheel",
    )


def _spot(inputs: ShockInputs, symbol: str) -> float | None:
    for ln in inputs.lines:
        if ln.symbol.upper() == symbol.upper() and ln.spot and ln.spot > 0:
            return ln.spot
    return None


def cc_overlay_proposals(
    inputs: ShockInputs,
    room: EnvelopeRoom,
    candidates: list[TradeCandidate],
    *,
    now: datetime,
    before: ShockResult | None = None,
) -> list[RepairProposal]:
    """One overlay per underlying: its highest-yield covered call among *candidates*."""
    base = before if before is not None else measure(inputs)
    best: dict[str, TradeCandidate] = {}
    for c in candidates:
        if c.strategy.value != "covered_call" or c.contracts < 1:
            continue
        key = c.underlying.upper()
        if key not in best or c.roc_pct > best[key].roc_pct:
            best[key] = c
    out: list[RepairProposal] = []
    for sym, cand in sorted(best.items()):
        spot = _spot(inputs, sym)
        after = measure(replace(inputs, lines=inputs.lines + (call_line(cand, spot),)))
        if not after.measured:
            continue  # no proposal without its numbers
        tag = " (leveraged, below basis: tap-only)" if cand.tap_only else ""
        detail = (
            f"Sell {cand.contracts} {sym} {cand.strike:g}C {cand.expiry:%d %b} at "
            f"{cand.premium:.2f} (delta {abs(cand.delta or 0.0):.2f}){tag}"
        )
        out.append(
            _proposal(
                "cc_overlay",
                sym,
                detail,
                base,
                after,
                room,
                now,
                candidate=cand,
                mark=spot,
            )
        )
    return out


def stop_adding_proposals(
    inputs: ShockInputs,
    room: EnvelopeRoom,
    addable: list[str],
    *,
    now: datetime,
    before: ShockResult | None = None,
    limit: int = MAX_STOP_ADDING,
) -> list[RepairProposal]:
    """While S10_gross is above L(t): the *addable* names (those a new put may still open on)
    with the largest S10 share, largest first. Stopping adds nothing now, so after = before."""
    base = before if before is not None else measure(inputs)
    if not room.measured or not base.measured or base.s10 <= room.s10_limit + 1e-9:
        return []
    shares = s10_by_name(inputs)
    wanted = {s.upper() for s in addable}
    ranked = sorted(
        ((v, s) for s, v in shares.items() if s in wanted and v > 0), key=lambda t: (-t[0], t[1])
    )
    out: list[RepairProposal] = []
    for loss, sym in ranked[: max(0, limit)]:
        detail = (
            f"Stop adding {sym}: no new cash-secured put. It carries {loss:.1f} of the book's "
            f"{base.s10:.1f}% S10 (limit {room.s10_limit:.1f}%)."
        )
        out.append(
            _proposal("stop_adding", sym, detail, base, base, room, now, mark=_spot(inputs, sym))
        )
    return out


def s10_per_share(inputs: ShockInputs, symbol: str) -> float | None:
    """One share of *symbol*'s S10 loss in dollars (its spot x the scenario's move), or None."""
    spot = _spot(inputs, symbol)
    if spot is None:
        return None
    try:
        move = name_move(symbol, SCENARIOS["S10"]["index"], inputs, scenario="S10")
    except KeyError:
        return None
    loss = -spot * move
    return loss if loss > 0 else None


def trim_shares(inputs: ShockInputs, symbol: str, points: float, sellable: float) -> int:
    """Whole shares of *symbol* whose sale takes *points* off S10_gross (rounded up, so the
    trim reaches the stated points), never above *sellable*. 0 when it cannot be sized."""
    per = s10_per_share(inputs, symbol)
    if per is None or not inputs.nlv > 0 or sellable < 1:
        return 0
    need = math.ceil(points / 100.0 * inputs.nlv / per - 1e-9)
    return int(min(max(need, 1), math.floor(sellable + 1e-9)))


def trim_proposals(
    inputs: ShockInputs,
    room: EnvelopeRoom,
    sellable: dict[str, float],
    *,
    now: datetime,
    points: float = 1.0,
    before: ShockResult | None = None,
    limit: int = MAX_TRIMS,
) -> list[RepairProposal]:
    """While S10_gross is above L(t): a trim of the names in *sellable* (the wheel's own shares
    not under a short call, never a value or LES share, never a leveraged ETF: those get a
    de-lever) with the largest S10 share, each sized to take *points* off S10_gross."""
    base = before if before is not None else measure(inputs)
    if not room.measured or not base.measured or base.s10 <= room.s10_limit + 1e-9:
        return []
    shares_s10 = s10_by_name(inputs)
    ranked = sorted(
        (
            (v, s)
            for s, v in shares_s10.items()
            if v > 0 and sellable.get(s, 0.0) >= 1 and s not in inputs.leverage
        ),
        key=lambda t: (-t[0], t[1]),
    )
    out: list[RepairProposal] = []
    for _loss, sym in ranked[: max(0, limit)]:
        qty = trim_shares(inputs, sym, points, sellable[sym])
        if qty < 1:
            continue
        after = measure(without_shares(inputs, sym, qty))
        if not after.measured:
            continue
        spot = _spot(inputs, sym)
        detail = (
            f"Sell {qty:,} {sym} shares (about ${qty * (spot or 0.0):,.0f}): S10 -"
            f"{base.s10 - after.s10:.1f} pts. Only the wheel's own shares not under a call."
        )
        out.append(
            _proposal("trim", sym, detail, base, after, room, now, shares=float(qty), mark=spot)
        )
    return out


def build_proposals(
    *,
    inputs: ShockInputs,
    room: EnvelopeRoom,
    cc_candidates: list[TradeCandidate],
    addable: list[str],
    now: datetime,
    sellable: dict[str, float] | None = None,
    trim_points: float = 1.0,
) -> list[RepairProposal]:
    """Every repair proposal for today, from the book (*inputs*), today's room, the day's
    covered-call candidates and the wheel's sellable shares (*sellable*, for trims). An
    unmeasured book builds nothing: every card must show its numbers."""
    before = measure(inputs)
    if not before.measured:
        return []
    return [
        *cc_overlay_proposals(inputs, room, cc_candidates, now=now, before=before),
        *stop_adding_proposals(inputs, room, addable, now=now, before=before),
        *trim_proposals(inputs, room, sellable or {}, now=now, points=trim_points, before=before),
    ]


def shadow_value(
    proposal: RepairProposal,
    *,
    close: float | None,
    twin_close: float | None = None,
    today: date,
) -> float | None:
    """What acting on *proposal* would have earned since it was built, in dollars, from the
    latest stored close (*close*, and *twin_close* for a de-lever's twin). None when a mark is
    missing.

    * ``cc_overlay``: the premium kept less the call's value now (Black-Scholes on its own IV,
      intrinsic at or past expiry), x 100 x contracts.
    * ``stop_adding``: one 100-share lot not added: ``-(close - mark) x 100``.
    * ``trim``: the shares sold: ``-(close - mark) x shares``.
    * ``delever``: the sold shares as a trim, plus the twin bought: ``(twin_close - twin_mark)
      x twin_shares``.
    """
    if close is None or close <= 0:
        return None
    if proposal.kind == "cc_overlay":
        c = proposal.candidate
        if c is None:
            return None
        left = (c.expiry - today).days
        iv = c.quote_iv if c.quote_iv else (c.current_iv / 100.0 if c.current_iv else None)
        value: float | None
        if left <= 0 or iv is None:
            value = max(0.0, close - c.strike)
        else:
            value = bs_price(close, c.strike, left, iv, "C")
        if value is None:
            return None
        return round((c.premium - value) * 100.0 * c.contracts, 2)
    if proposal.mark is None or proposal.mark <= 0:
        return None
    if proposal.kind == "stop_adding":
        return round(-(close - proposal.mark) * 100.0, 2)
    sold = -(close - proposal.mark) * proposal.shares
    if proposal.kind == "trim":
        return round(sold, 2)
    if proposal.kind == "delever":
        if proposal.twin_shares <= 0:
            return round(sold, 2)
        if twin_close is None or proposal.twin_mark is None or proposal.twin_mark <= 0:
            return None
        return round(sold + (twin_close - proposal.twin_mark) * proposal.twin_shares, 2)
    return None


def _floor(x: float) -> int:
    return max(0, math.floor(x + 1e-9))
