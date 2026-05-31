"""Place, monitor, and confirm option orders via ib_async.

Receives a pre-approved, pre-validated TradeCandidate and an OrderRow id.
Qualifies the contract, fetches a fresh live quote, builds a LimitOrder at mid,
places it, and monitors until filled or the fill timeout expires. Records the
result in FillRow + OrderRow and sends a Telegram confirmation.

Live mode adds a second human confirmation step: the user must tap [CONFIRM LIVE]
in Telegram before the order is transmitted. This prevents stale morning approvals
from auto-executing without a second touch. If no confirmation arrives within
fill_timeout_minutes, the order is cancelled and a timeout alert is sent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

from ib_async import IB, Contract
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from src.claude.memory import FILLED, record_outcome
from src.common.config import get_config
from src.common.schemas import OptionQuote, OrderState, Strategy, TradeCandidate, Verdict
from src.engine.risk_engine import validate_live_quote
from src.execution.order_builder import build_limit_order
from src.ibkr.contracts import build_option
from src.storage.db import session_scope
from src.storage.models import FillRow, OrderRow

log = logging.getLogger(__name__)


def _safe_float(val: object) -> float | None:
    """Coerce an ib_async tick value to float, treating None/NaN/non-numeric as None."""
    if val is None:
        return None
    try:
        f = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN check

# Seconds to wait for a live bid/ask tick before giving up on the quote.
# Configurable via execution.quote_timeout_seconds in settings.yaml.
def _quote_timeout() -> float:
    return get_config().execution.quote_timeout_seconds

# Pending live-order confirmation events keyed by order_id.
# Populated by execute_candidate; resolved by the Telegram callback handler.
_live_confirm_events: dict[int, asyncio.Event] = {}


def register_live_confirm(order_id: int) -> asyncio.Event:
    """Create and register a confirmation event for a pending live order."""
    event = asyncio.Event()
    _live_confirm_events[order_id] = event
    return event


def resolve_live_confirm(order_id: int) -> bool:
    """Signal live confirmation for order_id. Called by the Telegram callback handler.

    Returns True if an event existed and was set; False if already expired/resolved.
    """
    event = _live_confirm_events.pop(order_id, None)
    if event:
        event.set()
        return True
    return False


async def _fetch_quote(ib: IB, candidate: TradeCandidate) -> tuple[OptionQuote, Contract]:
    """Qualify the option contract and fetch a live bid/ask snapshot.

    Returns (OptionQuote, qualified_contract).
    Raises ValueError if qualification or quote acquisition fails.
    """
    contract = build_option(
        candidate.underlying,
        candidate.expiry,
        candidate.strike,
        candidate.right.value,
    )
    qualified_list = await ib.qualifyContractsAsync(contract)
    if not qualified_list or not getattr(qualified_list[0], "conId", None):
        raise ValueError(f"Could not qualify option contract for {candidate.candidate_id}")
    qualified = cast(Contract, qualified_list[0])

    timeout = _quote_timeout()
    # "101" requests open interest; model greeks (delta/IV) stream by default for options
    # and are used for the send-time re-gate and for storing entry IV at fill.
    ticker = ib.reqMktData(qualified, genericTickList="101", snapshot=False, regulatorySnapshot=False)
    deadline = asyncio.get_running_loop().time() + timeout
    while (
        ticker.bid is None or ticker.bid <= 0 or ticker.ask is None or ticker.ask <= 0
    ) and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.1)
    ib.cancelMktData(qualified)

    bid = ticker.bid if (ticker.bid is not None and ticker.bid > 0) else None
    ask = ticker.ask if (ticker.ask is not None and ticker.ask > 0) else None

    if bid is None and ask is None:
        raise ValueError(
            f"No live bid/ask received for {candidate.candidate_id} within {timeout}s"
        )

    greeks = getattr(ticker, "modelGreeks", None)
    quote = OptionQuote(
        underlying=candidate.underlying,
        right=candidate.right,
        strike=candidate.strike,
        expiry=candidate.expiry,
        bid=bid,
        ask=ask,
        delta=_safe_float(getattr(greeks, "delta", None)) if greeks else None,
        iv=_safe_float(getattr(greeks, "impliedVol", None)) if greeks else None,
    )
    return quote, qualified


async def execute_candidate(
    ib: IB,
    bot: Bot,
    chat_id: str,
    order_id: int,
    candidate: TradeCandidate,
) -> None:
    """Execute a single pre-validated TradeCandidate: qualify → quote → place → monitor → confirm."""
    cfg = get_config()
    fill_timeout = cfg.execution.fill_timeout_minutes * 60.0

    # ROLL is a two-leg combo (buy-to-close + sell-to-open); this single-leg executor
    # would mis-send it as a naked SELL. Rolls are alert-only — refuse outright.
    if candidate.strategy == Strategy.ROLL:
        log.error(
            "ROLL candidate %s reached the executor — rolls are alert-only; rejecting",
            candidate.candidate_id,
        )
        with session_scope() as session:
            row = session.get(OrderRow, order_id)
            if row:
                row.state = OrderState.REJECTED
                row.detail = "ROLL is not executable via the single-leg order builder"
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"Order NOT placed — {candidate.underlying} is a ROLL. "
                f"Rolls are alert-only and cannot be auto-executed."
            ),
        )
        return

    try:
        quote, qualified = await _fetch_quote(ib, candidate)

        # Second Rules Engine pass — against the FRESH live quote (delta drift / collapsed mid).
        live_verdict = validate_live_quote(candidate, quote)
        if live_verdict.verdict != Verdict.PASS:
            log.warning(
                "Live re-gate REJECT — order_id=%s candidate=%s reasons=%s",
                order_id,
                candidate.candidate_id,
                live_verdict.reasons,
            )
            with session_scope() as session:
                row = session.get(OrderRow, order_id)
                if row:
                    row.state = OrderState.REJECTED
                    row.detail = f"Live re-validation failed: {live_verdict.reasons}"
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"Order NOT placed — {candidate.underlying} failed live re-validation "
                    f"({', '.join(live_verdict.reasons)})."
                ),
            )
            return

        order = build_limit_order(candidate, quote)

        if cfg.is_live:
            confirm_event = register_live_confirm(order_id)
            confirm_text = (
                f"⚠️ [CONFIRM LIVE] About to place LIVE order:\n"
                f"{candidate.underlying} ${candidate.strike:.0f} {candidate.right.value} "
                f"— {candidate.contracts} contract(s) @ ~${order.lmtPrice:.2f}\n"
                f"Tap to confirm or let it time out to cancel."
            )
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("CONFIRM LIVE", callback_data=f"confirm_live:{order_id}")]]
            )
            await bot.send_message(chat_id=chat_id, text=confirm_text, reply_markup=keyboard)
            try:
                await asyncio.wait_for(confirm_event.wait(), timeout=fill_timeout)
            except TimeoutError:
                _live_confirm_events.pop(order_id, None)
                log.warning(
                    "Live confirmation timed out — order NOT placed: order_id=%s candidate=%s",
                    order_id,
                    candidate.candidate_id,
                )
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"Live confirmation timed out for {candidate.underlying} "
                        f"(order_id={order_id}) — order NOT placed."
                    ),
                )
                with session_scope() as session:
                    row = session.get(OrderRow, order_id)
                    if row:
                        row.state = OrderState.CANCELLED
                        row.detail = "Live confirmation timeout"
                return

        trade = ib.placeOrder(qualified, order)
        log.info(
            "Order placed — candidate=%s orderId=%s lmtPrice=%.2f",
            candidate.candidate_id,
            trade.order.orderId,
            order.lmtPrice,
        )

        with session_scope() as session:
            row = session.get(OrderRow, order_id)
            if row:
                row.state = OrderState.SUBMITTED
                row.ib_order_id = trade.order.orderId
                row.limit_price = float(order.lmtPrice) if order.lmtPrice is not None else None

        # Wait for terminal state or timeout.
        deadline = asyncio.get_running_loop().time() + fill_timeout
        while not trade.isDone():
            await asyncio.sleep(1)
            if asyncio.get_running_loop().time() > deadline:
                log.warning("Fill timeout for order_id=%s — cancelling", order_id)
                ib.cancelOrder(trade.order)
                await asyncio.sleep(2)
                break

        filled_qty: float = getattr(trade.orderStatus, "filled", 0.0) or 0.0
        avg_price: float = getattr(trade.orderStatus, "avgFillPrice", 0.0) or 0.0
        ib_status: str = getattr(trade.orderStatus, "status", "")

        if filled_qty > 0:
            # Collect exec id and commission from fills if available.
            exec_id: str | None = None
            commission: float | None = None
            if trade.fills:
                exec_id = getattr(getattr(trade.fills[-1], "execution", None), "execId", None)
                total_comm = 0.0
                for f in trade.fills:
                    cr = getattr(f, "commissionReport", None)
                    if cr is not None:
                        c = getattr(cr, "commission", None)
                        if c is not None and c > 0:
                            total_comm += c
                commission = total_comm if total_comm > 0 else None

            new_state = (
                OrderState.FILLED if filled_qty >= candidate.contracts else OrderState.PARTIAL
            )
            with session_scope() as session:
                fill_row = FillRow(
                    order_id=order_id,
                    candidate_id=candidate.candidate_id,
                    ib_exec_id=exec_id,
                    filled_qty=filled_qty,
                    avg_price=avg_price,
                    commission=commission,
                    entry_iv=quote.iv,  # IV at execution → monitor's IV-spike baseline
                    is_live=cfg.is_live,
                )
                session.add(fill_row)
                row = session.get(OrderRow, order_id)
                if row:
                    row.state = new_state
                    row.filled_qty = filled_qty
                    row.avg_fill_price = avg_price

            record_outcome(candidate.candidate_id, FILLED)
            log.info(
                "Fill recorded — candidate=%s qty=%.0f @ %.2f state=%s",
                candidate.candidate_id,
                filled_qty,
                avg_price,
                new_state,
            )
            strategy_label = candidate.strategy.value.replace("_", " ").title()
            msg = (
                f"Filled: {candidate.underlying} {strategy_label} "
                f"${candidate.strike:.0f} — {filled_qty:.0f} contract(s) @ ${avg_price:.2f}"
            )
            await bot.send_message(chat_id=chat_id, text=msg)

        elif ib_status in ("Inactive", "ApiCancelled", "Error"):
            with session_scope() as session:
                row = session.get(OrderRow, order_id)
                if row:
                    row.state = OrderState.REJECTED
                    row.detail = f"IB rejected: {ib_status}"
            log.warning(
                "Order rejected by IB — candidate=%s status=%s", candidate.candidate_id, ib_status
            )
            await bot.send_message(
                chat_id=chat_id,
                text=f"Order rejected by IB: {candidate.underlying} ({ib_status})",
            )

        else:
            with session_scope() as session:
                row = session.get(OrderRow, order_id)
                if row and row.state == OrderState.SUBMITTED:
                    row.state = OrderState.CANCELLED
                    row.detail = f"Cancelled/timeout: {ib_status}"
            log.info(
                "Order cancelled/timed-out — candidate=%s status=%s",
                candidate.candidate_id,
                ib_status,
            )

    except Exception:
        log.exception(
            "Unexpected error executing order_id=%s candidate=%s", order_id, candidate.candidate_id
        )
        with session_scope() as session:
            row = session.get(OrderRow, order_id)
            if row and row.state not in (OrderState.FILLED, OrderState.PARTIAL):
                row.state = OrderState.REJECTED
                row.detail = "Execution exception"
        # Do not re-raise — this runs inside a background asyncio Task; re-raising
        # would silently kill the task and stop all future order processing.
