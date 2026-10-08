"""Turns an approved spread into a fill: simulated (shadow) or a laddered paper combo order.

Paper opens are re-gated: the spread is repriced from fresh leg quotes and run through the
caller's ``recheck`` — the same ``risk.validate`` — immediately before the order is sent (the
core invariant's second gate run). An unfilled order is cancelled; a partial fill is reported
as what it is. Shadow fills charge ``shadow_slippage_per_leg`` per leg and the configured
commission so shadow P&L is not flattered by mid-price fills.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from src.common.config import SpreadsCfg
from src.common.schemas import ChainOption, SpreadCandidate, SpreadPosition, SpreadVerdict
from src.spreads.manager import debit_to_close
from src.spreads.orders import (
    build_close_order,
    build_open_order,
    credit_ladder,
    debit_ladder,
    round_tick,
)
from src.spreads.selector import refresh_candidate

log = logging.getLogger(__name__)


class Requoter(Protocol):
    async def requote(self, legs: list[ChainOption]) -> list[ChainOption]: ...


@dataclass(frozen=True)
class FillResult:
    filled_qty: int
    price: float | None  # per share: credit for an open, debit for a close
    commission: float  # positive cost
    perm_id: int | None = None
    ib_order_id: int | None = None
    reason: str | None = None
    order_ref: str = ""


def _right(side: str) -> str:
    return "P" if side == "put" else "C"


def _match(quotes: list[ChainOption], strike: float, right: str) -> ChainOption | None:
    return next((x for x in quotes if x.right == right and abs(x.strike - strike) < 1e-6), None)


def _commission(trade: Any) -> float:
    total = 0.0
    for f in getattr(trade, "fills", []) or []:
        rep = getattr(f, "commissionReport", None)
        try:
            c = float(getattr(rep, "commission", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(c) and abs(c) < 1e9:
            total += abs(c)
    return total


class SpreadExecutor:
    def __init__(
        self,
        ib: Any,
        broker: Requoter,
        cfg: SpreadsCfg,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        poll_seconds: float = 0.25,
    ) -> None:
        self.ib = ib
        self.broker = broker
        self.cfg = cfg
        self.now = now
        self.poll = poll_seconds

    async def open(
        self,
        c: SpreadCandidate,
        contracts: int,
        recheck: Callable[[SpreadCandidate], SpreadVerdict],
    ) -> FillResult:
        x = self.cfg.execution
        ref = f"{self.cfg.order_ref_prefix}{c.spread_id}"
        if self.cfg.mode == "shadow":
            credit = round(c.credit_mid - 2 * x.shadow_slippage_per_leg, 4)
            if credit <= 0:
                return FillResult(0, None, 0.0, reason="shadow_credit_nonpositive", order_ref=ref)
            return FillResult(
                contracts, credit, 2 * contracts * x.commission_per_contract, order_ref=ref
            )

        right = _right(c.side)
        legs = [
            ChainOption(strike=c.short_strike, right=right, expiry=c.expiry, con_id=c.short_con_id),  # type: ignore[arg-type]
            ChainOption(strike=c.long_strike, right=right, expiry=c.expiry, con_id=c.long_con_id),  # type: ignore[arg-type]
        ]
        quotes = await self.broker.requote(legs)
        short_q, long_q = (
            _match(quotes, c.short_strike, right),
            _match(quotes, c.long_strike, right),
        )
        fresh = (
            refresh_candidate(c, short_q, long_q, self.now())
            if short_q is not None and long_q is not None
            else None
        )
        if fresh is None:
            return FillResult(0, None, 0.0, reason="no_fresh_quote", order_ref=ref)
        verdict = recheck(fresh)
        if not verdict.approved:
            return FillResult(
                0, None, 0.0, reason="regate:" + ",".join(verdict.reasons), order_ref=ref
            )
        qty = max(1, min(contracts, verdict.contracts))
        floor = self.cfg.selection.min_credit_pct_of_width * self.cfg.selection.width
        ladder = credit_ladder(
            fresh.credit_mid, fresh.credit_natural, x.reprice_steps, x.reprice_tick, floor
        )
        if not ladder:
            return FillResult(0, None, 0.0, reason="no_price_above_floor", order_ref=ref)
        bag, order = build_open_order(self.cfg.underlying, fresh, qty, ladder[0], ref)
        filled, avg, commission, perm, oid = await self._work(
            bag, order, [-p for p in ladder], x.order_ttl_seconds
        )
        return FillResult(
            filled,
            -avg if avg is not None else None,
            commission,
            perm,
            oid,
            None if filled else "not_filled",
            ref,
        )

    async def close(
        self,
        pos: SpreadPosition,
        short_q: ChainOption | None,
        long_q: ChainOption | None,
        *,
        urgent: bool,
    ) -> FillResult:
        x = self.cfg.execution
        ref = f"{self.cfg.order_ref_prefix}{pos.spread_id}:X"
        mid, nat = debit_to_close(short_q, long_q)
        if self.cfg.mode == "shadow":
            base = mid if mid is not None else nat if nat is not None else pos.width
            debit = (
                min(pos.width, round(base + 2 * x.shadow_slippage_per_leg, 4))
                if base < pos.width
                else pos.width
            )
            return FillResult(
                pos.contracts, debit, 2 * pos.contracts * x.commission_per_contract, order_ref=ref
            )
        start = mid if mid is not None else nat
        if start is None:
            return FillResult(0, None, 0.0, reason="no_quote", order_ref=ref)
        cap = min(pos.width, (nat if nat is not None else start) + x.close_max_concession)
        ladder = debit_ladder(start, x.reprice_steps, x.reprice_tick, cap)
        if urgent and nat is not None and nat <= cap and ladder[-1] < round_tick(nat) - 1e-9:
            ladder.append(round_tick(nat))
        bag, order = build_close_order(self.cfg.underlying, pos, pos.contracts, ladder[0], ref)
        filled, avg, commission, perm, oid = await self._work(
            bag, order, ladder, x.close_ttl_seconds
        )
        return FillResult(filled, avg, commission, perm, oid, None if filled else "not_filled", ref)

    async def _wait_done(self, trade: Any, seconds: float) -> bool:
        deadline = asyncio.get_running_loop().time() + seconds
        while not trade.isDone():
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(self.poll)
        return True

    async def _work(
        self, bag: Any, order: Any, lmt_prices: list[float], ttl: float
    ) -> tuple[int, float | None, float, int | None, int | None]:
        trade = self.ib.placeOrder(bag, order)
        per_step = ttl / max(len(lmt_prices), 1)
        for i, px in enumerate(lmt_prices):
            if i > 0:
                if trade.isDone():
                    break
                order.lmtPrice = px
                trade = self.ib.placeOrder(bag, order)
            if await self._wait_done(trade, per_step):
                break
        if not trade.isDone():
            self.ib.cancelOrder(order)
            await self._wait_done(trade, 5.0)
        filled = int(trade.orderStatus.filled or 0)
        avg = float(trade.orderStatus.avgFillPrice) if filled else None
        perm = int(getattr(trade.order, "permId", 0) or 0) or None
        oid = int(getattr(trade.order, "orderId", 0) or 0) or None
        log.info("spreads order %s: filled %d @ %s", getattr(order, "orderRef", ""), filled, avg)
        return filled, avg, _commission(trade), perm, oid
