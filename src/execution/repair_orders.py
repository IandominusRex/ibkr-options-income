"""A tapped repair proposal's stock orders (risk-envelope Tasks 31-32; spec §3.7 item 2, P10).

Called only from the Telegram tap (``approval_service._handle_repair_button``): the tap is the
human decision, and nothing here runs without one. Each leg is a ``StockOrderIntent`` with
``source="repair"`` and ``tapped=True``, gated by ``risk_engine.validate_stock_order`` at decision
time (``stock_orders.gate_now``) and again at send time inside ``execute_stock_order`` on a fresh
quote. The proposal's row records what happened (``sent`` / ``failed`` and the result).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.common.schemas import RepairProposal, StockOrderIntent, Verdict
from src.execution.stock_orders import StockOrderResult, execute_stock_order, gate_now
from src.storage.repair_proposals import decide

log = logging.getLogger(__name__)


def _line(res: StockOrderResult) -> str:
    i = res.intent
    if res.status in ("filled", "partial"):
        return f"{i.side} {res.filled:g} of {i.qty} {i.symbol} @ {res.avg_price or 0:.2f} ({res.status})"
    if res.status == "working":
        return f"{i.side} {i.qty} {i.symbol}: cancel not confirmed, check IBKR"
    if res.status == "refused":
        return f"{i.side} {i.qty} {i.symbol} refused: {', '.join(res.reasons)}"
    return f"{i.side} {i.qty} {i.symbol}: {res.status} {', '.join(res.reasons)}".strip()


async def _leg(ib: Any, intent: StockOrderIntent) -> StockOrderResult:
    """One gated leg: the decision-time gate, then ``execute_stock_order`` (the send-time one)."""
    verdict, _quote = await gate_now(ib, intent)
    if verdict.verdict != Verdict.PASS:
        return StockOrderResult("refused", intent, reasons=list(verdict.reasons))
    return await execute_stock_order(ib, intent)


async def execute_trim(ib: Any, proposal: RepairProposal) -> str:
    """Sell the trim's shares (one gated SELL). Returns the line for the card."""
    assert proposal.id is not None
    intent = StockOrderIntent(
        side="SELL",
        symbol=proposal.symbol,
        qty=int(proposal.shares),
        source="repair",
        ref_id=f"{proposal.id}",
        tapped=True,
        reason=f"trim, repair proposal {proposal.id}",
    )
    res = await _leg(ib, intent)
    ok = res.status in ("filled", "partial")
    text = _line(res)
    await asyncio.to_thread(
        decide, proposal.id, "sent" if ok else "failed", by="telegram", result=text
    )
    return text


async def execute_repair(ib: Any, proposal: RepairProposal) -> str:
    """The stock orders of an approved trim (Task 31). Never raises."""
    try:
        if proposal.kind == "trim":
            return await execute_trim(ib, proposal)
        return f"Nothing to send for a {proposal.kind} proposal."
    except Exception:
        log.exception("repair proposal %s: the stock order failed", proposal.id)
        if proposal.id is not None:
            await asyncio.to_thread(
                decide, proposal.id, "failed", by="telegram", result="error; check IBKR"
            )
        return "The stock order failed: check IBKR."
