"""Combo (BAG) orders for a credit vertical, and the price ladders that work them.

IBKR combo convention — the same one ``execution.order_builder.build_combo_roll_order`` uses:
the parent order BUYs the bag and ``lmtPrice`` is the net DEBIT per share, so a credit is a
negative limit. Opening legs: SELL the short, BUY the long. Closing legs: BUY the short, SELL
the long, at a positive limit. **Not yet verified on a live paper session** — run
``scripts/spreads_combo_check.py`` (plan Task 11 Step 9) before trusting paper mode;
STATUS.md tracks it.
"""

from __future__ import annotations

from ib_async import ComboLeg, Contract, LimitOrder

from src.common.schemas import SpreadCandidate, SpreadPosition


def round_tick(price: float, tick: float = 0.01) -> float:
    return round(round(price / tick) * tick, 2)


def _bag(symbol: str, legs: list[ComboLeg]) -> Contract:
    return Contract(symbol=symbol, secType="BAG", currency="USD", exchange="SMART", comboLegs=legs)


def build_open_order(
    symbol: str, c: SpreadCandidate, contracts: int, credit: float, order_ref: str
) -> tuple[Contract, LimitOrder]:
    if contracts < 1:
        raise ValueError(f"spread order needs >= 1 contract, got {contracts}")
    if not c.short_con_id or not c.long_con_id:
        raise ValueError(f"{c.spread_id}: both legs must be qualified (conIds) before an order")
    if credit <= 0:
        raise ValueError(f"{c.spread_id}: an opening credit must be positive, got {credit}")
    bag = _bag(
        symbol,
        [
            ComboLeg(conId=c.short_con_id, ratio=1, action="SELL", exchange="SMART"),
            ComboLeg(conId=c.long_con_id, ratio=1, action="BUY", exchange="SMART"),
        ],
    )
    order = LimitOrder("BUY", contracts, round_tick(-credit), tif="DAY", orderRef=order_ref)
    return bag, order


def build_close_order(
    symbol: str, pos: SpreadPosition, contracts: int, debit: float, order_ref: str
) -> tuple[Contract, LimitOrder]:
    if contracts < 1:
        raise ValueError(f"close needs >= 1 contract, got {contracts}")
    if not pos.short_con_id or not pos.long_con_id:
        raise ValueError(f"{pos.spread_id}: missing leg conIds")
    if debit <= 0:
        raise ValueError(f"{pos.spread_id}: a closing debit must be positive, got {debit}")
    bag = _bag(
        symbol,
        [
            ComboLeg(conId=pos.short_con_id, ratio=1, action="BUY", exchange="SMART"),
            ComboLeg(conId=pos.long_con_id, ratio=1, action="SELL", exchange="SMART"),
        ],
    )
    order = LimitOrder("BUY", contracts, round_tick(debit), tif="DAY", orderRef=order_ref)
    return bag, order


def credit_ladder(mid: float, natural: float, steps: int, tick: float, floor: float) -> list[float]:
    """Mid credit, then one tick worse per step, never below max(natural, floor)."""
    bottom = max(natural, floor)
    start = round_tick(mid, tick)
    out: list[float] = []
    for i in range(max(steps, 1)):
        px = round_tick(start - i * tick, tick)
        if px < bottom - 1e-9:
            break
        out.append(px)
    return out


def debit_ladder(mid: float, steps: int, tick: float, cap: float) -> list[float]:
    """Mid debit, then one tick worse per step, never above *cap*."""
    start = round_tick(max(mid, tick), tick)
    out: list[float] = []
    for i in range(max(steps, 1)):
        px = round_tick(start + i * tick, tick)
        if px > cap + 1e-9:
            break
        out.append(px)
    return out or [round_tick(min(start, cap), tick)]
