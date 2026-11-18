"""The bridge's size rule and default item (risk-envelope Task 36; spec §3.10.5, rulings H3, H5).

Pure: plain data in, plain data out, no I/O and no config read (the caller hands the ``HedgeCfg``).

* **Default item** (H5): over the menu's priced items, the one with the best *minimum* protection
  per premium dollar across {S10, S20, T20, G10, P20}, each scenario's protection being the item's
  gain under ``shock.scenario_loss`` with the item's own lines (full Black-Scholes revaluation,
  long legs counted). The hedge instrument moves as the Nasdaq-100 does: XND takes QQQ's beta and
  both are tech-linked (T20 moves them -20%).
* **Size** (H5): points protected = min(budget-limited points, 0.5 x max(0, S10_gross - target)),
  in contracts rounded down (never a minimum of one), and never so many that the hedge's delta
  exceeds ``max_hedge_delta_share`` (50%) of the book's beta-weighted delta.
* **Budget room** (H3): the least of the net, pace and open-at-cost caps' room.

No hedge creates envelope headroom (H1, H10): nothing here feeds S10_gross, U_ew or any cap.
Deterministic tier: imports no enrichment.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from src.analytics.black_scholes import bs_delta
from src.analytics.shock import name_move, scenario_loss
from src.common.config import HedgeCfg
from src.common.envelope_types import BookLine, ShockInputs
from src.common.schemas import HEDGE_SCENARIOS
from src.hedge.menu import HedgeMenuItem

GAP_SHARE = 0.5  # H5's lambda: half the gap between S10_gross and the target
PROXY = "QQQ"  # the index the instrument tracks; XND borrows its beta


@dataclass(frozen=True, slots=True)
class Pick:
    """The default item with its gain per contract in each scenario (dollars) and its minimum
    protection per premium dollar."""

    item: HedgeMenuItem
    credits: dict[str, float]
    per_dollar: float


def points_needed(s10_gross: float, target: float) -> float:
    """H5: 0.5 x max(0, S10_gross - target), in points of NLV."""
    return GAP_SHARE * max(0.0, s10_gross - target)


def months_elapsed(started_on: date, today: date) -> float:
    """Months since the bridge's first day, as the pace cap counts them."""
    return max(0.0, (today - started_on).days / 30.4375)


def budget_room(
    cfg: HedgeCfg, *, nlv0: float, spent: float, open_at_cost: float, months: float
) -> float:
    """Dollars of new premium the H3 caps still allow: the least of net (1.0% NLV0 - spent), pace
    (0.25% NLV0 x (months + 2) - spent) and open at cost (0.6% NLV0 - open premium); never < 0."""
    net, pace, open_cap = cfg.budget.caps(nlv0, months)
    return max(0.0, min(net - spent, pace - spent, open_cap - open_at_cost))


def instrument_beta(book: ShockInputs, instrument: str) -> float | None:
    b = book.betas.get(instrument.upper())
    if b is None:
        b = book.betas.get(PROXY)
    return float(b) if b is not None else None


def item_inputs(
    item: HedgeMenuItem, instrument: str, spot: float, book: ShockInputs, *, today: date
) -> ShockInputs | None:
    """One contract of *item* as ``ShockInputs`` on the book's betas and NLV, or None when a leg
    has no IV or the instrument has no beta (the item cannot be valued)."""
    inst = instrument.upper()
    beta = instrument_beta(book, inst)
    if beta is None or not book.nlv > 0:
        return None
    lines: list[BookLine] = []
    for side, q in item.legs:
        if q.iv is None or not q.iv > 0:
            return None
        lines.append(
            BookLine(
                symbol=inst,
                kind="long_put" if side == "long" else "short_put",
                qty=1.0,
                spot=spot,
                strike=q.strike,
                dte=(q.expiry - today).days,
                iv=q.iv,
                book="hedge",
            )
        )
    return ShockInputs(
        lines=tuple(lines),
        betas={inst: beta},
        betas_smh={inst: beta},
        leverage={},
        governing={},
        tech_linked=frozenset(book.tech_linked) | {inst, PROXY},
        semis=frozenset(),
        nlv=book.nlv,
    )


def credits(
    item: HedgeMenuItem, instrument: str, spot: float, book: ShockInputs, *, today: date
) -> dict[str, float] | None:
    """The item's gain per contract in dollars, per scenario in ``HEDGE_SCENARIOS``."""
    inputs = item_inputs(item, instrument, spot, book, today=today)
    if inputs is None:
        return None
    out: dict[str, float] = {}
    for name in HEDGE_SCENARIOS:
        loss, missing = scenario_loss(inputs, name, include_long=True)
        if missing:
            return None
        out[name] = -loss / 100.0 * inputs.nlv
    return out


def default_item(
    items: Iterable[HedgeMenuItem], instrument: str, spot: float, book: ShockInputs, *, today: date
) -> Pick | None:
    """The priced item with the best minimum protection per premium dollar (ties: the lower debit,
    then the key). None when no item can be priced and valued."""
    best: tuple[float, float, str] | None = None
    pick: Pick | None = None
    for it in items:
        if it.debit is None or not it.debit > 0:
            continue
        c = credits(it, instrument, spot, book, today=today)
        if c is None:
            continue
        per_dollar = min(c.values()) / (it.debit * 100.0)
        if per_dollar <= 0:
            continue
        rank = (-per_dollar, it.debit, it.item_key)
        if best is None or rank < best:
            best, pick = rank, Pick(it, c, per_dollar)
    return pick


def leg_beta_delta(delta: float | None, spot: float, beta: float, *, short: bool) -> float | None:
    """One contract's beta-weighted delta in SPY-dollars (a long put's is negative)."""
    if delta is None:
        return None
    return (-delta if short else delta) * 100.0 * spot * beta


def item_beta_delta(item: HedgeMenuItem, spot: float, beta: float) -> float | None:
    """One contract of *item*'s beta-weighted delta (negative: a put structure is short delta)."""
    total = 0.0
    for side, q in item.legs:
        d = leg_beta_delta(q.delta, spot, beta, short=side == "short")
        if d is None:
            return None
        total += d
    return total


def book_beta_delta(inputs: ShockInputs) -> float | None:
    """The book's beta-weighted delta in SPY-dollars, the hedge book's lines left out: stock is
    ``qty x spot x beta``, an option ``BS delta x 100 x signed qty x spot x beta``, a leveraged ETF
    at leverage x its governing index's beta (the S10 move per unit of index move). None when a
    line cannot be valued (fail closed)."""
    total = 0.0
    for line in inputs.lines:
        if line.book == "hedge":
            continue
        try:
            beta = name_move(line.symbol, 1.0, inputs, scenario="S10")
        except KeyError:
            return None
        if line.spot is None or not line.spot > 0:
            return None
        if line.kind == "stock":
            total += line.qty * line.spot * beta
            continue
        if line.strike is None or line.dte is None or line.iv is None:
            return None
        right = "P" if line.kind in ("short_put", "long_put") else "C"
        d = bs_delta(line.spot, line.strike, max(1, line.dte), line.iv, right)
        if d is None:
            return None
        sign = -1.0 if line.kind.startswith("short") else 1.0
        total += d * 100.0 * abs(line.qty) * sign * line.spot * beta
    return total


def contracts_for(
    pick: Pick,
    *,
    points: float,
    nlv: float,
    budget_left: float,
    per_contract_delta: float | None,
    book_delta: float | None,
    hedge_delta: float,
    max_delta_share: float,
) -> int:
    """H5's size in whole contracts, rounded down: the fewer of the contracts that protect *points*
    of NLV under S10 and those the budget affords, then cut so the hedge's delta stays within
    *max_delta_share* of the book's (no book delta, no size: fail closed)."""
    s10 = pick.credits.get("S10", 0.0)
    debit = pick.item.debit or 0.0
    if points <= 0 or s10 <= 0 or debit <= 0 or nlv <= 0:
        return 0
    need = points / 100.0 * nlv / s10
    afford = budget_left / (debit * 100.0)
    n = math.floor(min(need, afford) + 1e-9)
    if book_delta is None or book_delta <= 0 or per_contract_delta is None:
        return 0
    if per_contract_delta < 0:
        room = max_delta_share * book_delta - abs(min(0.0, hedge_delta))
        n = min(n, math.floor(room / abs(per_contract_delta) + 1e-9))
    return max(0, n)
