"""What ``validate_hedge`` reads, read from the broker and the books now (risk-envelope Tasks 34-36;
spec §3.10.3, §3.10.6, §3.10.9, rulings H3, H5, H6, H9).

``build_context(ib, ...)`` returns the ``HedgeContext`` for one decision (and again at send time):

* the account truth (``get_positions(include_value=True, include_hedge=True)``): every other
  book's option contracts (``conId`` and identity, the contract clash) and the names any other book
  holds a share or a short option in (the QQQ-route rule);
* the hedge book (``src/common/hedge_view.py``): premium spent, open premium at cost, the contracts
  held per position;
* the stress block's closes (``price_history``: the last ^VIX close, the last ^VXN close and its
  90th percentile over ``hedge.stress.vxn_window_sessions``), the account halt and the slow breaker;
* the book's beta-weighted delta (``sizing.book_beta_delta``) on live IBKR IV (H7), which a caller
  may pass in (*book*) so the send-time re-gate does not read it twice.

``send_time_gate(ib, ...)`` is ``validate_hedge`` on a context read now. Nothing here reads an LLM
output. Deterministic tier: imports no enrichment.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from src.common.config import HedgeCfg, get_config
from src.common.envelope_types import ShockInputs
from src.common.schemas import HedgeCandidate, HedgeContext, RiskVerdict

log = logging.getLogger(__name__)

MIN_VXN_SESSIONS = 126  # fewer stored VXN closes than half the window: the percentile is unknown


@dataclass(frozen=True, slots=True)
class Stress:
    vix_close: float | None
    vxn_close: float | None
    vxn_p90: float | None


def percentile(values: list[float], pct: float) -> float | None:
    """The *pct* percentile of *values* by linear interpolation; None for an empty list."""
    xs = sorted(values)
    if not xs:
        return None
    k = (len(xs) - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def read_stress(cfg: HedgeCfg) -> Stress:
    """The last ^VIX and ^VXN closes and VXN's 1-year 90th percentile from ``price_history``.
    Missing data is None (the gate then refuses new size: fail closed)."""
    from src.storage.price_history import load_bars

    vix = load_bars("^VIX", limit=1)
    vxn = load_bars("^VXN", limit=cfg.stress.vxn_window_sessions)
    closes = [b.close for b in vxn if b.close > 0]
    p90 = percentile(closes, cfg.stress.vxn_percentile) if len(closes) >= MIN_VXN_SESSIONS else None
    return Stress(
        vix_close=vix[-1].close if vix and vix[-1].close > 0 else None,
        vxn_close=closes[-1] if closes else None,
        vxn_p90=p90,
    )


async def book_inputs(ib: Any, nlv: float) -> ShockInputs | None:
    """The book (every book but the hedge's) on live IBKR IV, as ``ShockInputs``; None when it
    cannot be read."""
    from src.analytics.shock_inputs import build_inputs
    from src.common.books import les_by_name_for_envelope, value_exposure
    from src.ibkr.live_iv import live_option_reads
    from src.ibkr.portfolio import get_positions

    try:
        positions = get_positions(ib)
        exposure = value_exposure()
        value_by_name = dict(exposure.by_name) if exposure.active and exposure.readable else {}
        live = await live_option_reads(ib, positions)
        return await asyncio.to_thread(
            build_inputs,
            positions,
            nlv=nlv,
            value_by_name=value_by_name,
            les_by_name=les_by_name_for_envelope(),
            ivs=live.ivs,
            spots=live.spots,
        )
    except Exception:
        log.warning("hedge: the book could not be measured", exc_info=True)
        return None


def other_books(positions: list[Any], hedge_ids: frozenset[int]) -> dict[str, Any]:
    """From the account truth: every non-hedge option contract (``conId`` and identity) and the
    names held as stock or as a short option outside the hedge book."""
    con_ids: list[int] = []
    keys: list[tuple[str, str, float, date]] = []
    names: set[str] = set()
    from src.common.books import is_hedge_underlying

    for p in positions:
        sym = (p.underlying or p.symbol).upper()
        if p.con_id is not None and p.con_id in hedge_ids:
            continue
        if is_hedge_underlying(sym):
            continue
        if p.sec_type == "STK" and p.position:
            names.add(sym)
        elif p.sec_type == "OPT" and p.position:
            if p.con_id:
                con_ids.append(int(p.con_id))
            if p.strike is not None and p.expiry is not None and p.right is not None:
                keys.append((sym, p.right.value, round(float(p.strike), 4), p.expiry))
            if p.position < 0:
                names.add(sym)
    return {"con_ids": con_ids, "keys": keys, "names": sorted(names)}


async def build_context(
    ib: Any,
    *,
    cfg: HedgeCfg,
    now: datetime,
    nlv0: float,
    months: float,
    book: ShockInputs | None,
    instrument_beta: float | None,
    hedge_beta_delta: float = 0.0,
) -> HedgeContext:
    """The context ``validate_hedge`` reads, from the broker and the books now."""
    from src.common import hedge_view
    from src.hedge.sizing import book_beta_delta
    from src.ibkr.portfolio import get_positions
    from src.storage import slow_breaker
    from src.storage.system_settings import is_halted

    # The spreads book's contracts are left out on purpose: its underlyings (SPY, SPX, XSP) can
    # never be a hedge underlying (``Config._hedge_isolated``), so no contract of it can clash.
    truth = get_positions(ib, include_value=True, include_hedge=True)
    hedges = hedge_view.open_hedges()
    ids = hedge_view.hedge_con_ids() or frozenset()
    other = other_books(truth, ids)
    stress = await asyncio.to_thread(read_stress, cfg)
    held: dict[str, float] = {}
    broker_qty = {int(p.con_id): p.position for p in truth if p.con_id}
    for h in hedges or []:
        long_ids = [leg.con_id for leg in h.legs if leg.action == "BUY" and leg.con_id]
        at_broker = min((broker_qty.get(i, 0.0) for i in long_ids), default=h.contracts)
        held[h.hedge_id] = max(0.0, min(h.contracts, at_broker))  # never sell what IBKR lacks
    return HedgeContext(
        is_live=get_config().is_live,
        now=now,
        nlv0=nlv0,
        months_elapsed=months,
        net_premium_spent=hedge_view.spend() or 0.0,
        open_premium_at_cost=sum(h.cost for h in hedges or []),
        halted=is_halted(),
        slow_breaker_tripped=slow_breaker.blocks_new_entries(),
        vix_close=stress.vix_close,
        vxn_close=stress.vxn_close,
        vxn_p90=stress.vxn_p90,
        book_beta_delta=book_beta_delta(book) if book is not None else None,
        hedge_beta_delta=hedge_beta_delta,
        instrument_beta=instrument_beta,
        other_books_con_ids=other["con_ids"],
        other_books_contracts=other["keys"],
        wheel_underlyings=other["names"],
        held_contracts=held,
        hedge_book_readable=hedges is not None,
    )


def gate(ctx: HedgeContext, cand: HedgeCandidate) -> RiskVerdict:
    """The Rules Engine's check on *cand* under *ctx* (the one path to a hedge order)."""
    from src.engine.risk_engine import validate_hedge

    return validate_hedge(cand, ctx)
