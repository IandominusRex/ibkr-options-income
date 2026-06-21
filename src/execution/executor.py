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
from src.execution.order_builder import build_limit_order, reprice_limit
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


def _as_float(val: object, default: float) -> float:
    """Return val as a float, falling back to default for None/non-numeric (e.g. a
    MagicMock config attribute in tests). Keeps the quote-wait deadlines real so the
    greeks loop can never spin against a non-numeric deadline."""
    if isinstance(val, bool) or not isinstance(val, int | float):
        return default
    return float(val)


# Seconds to wait for a live bid/ask tick before giving up on the quote.
# Configurable via execution.quote_timeout_seconds in settings.yaml.
def _quote_timeout() -> float:
    return _as_float(get_config().execution.quote_timeout_seconds, 10.0)


# Fraction of the quote timeout we additionally spend waiting for modelGreeks to stream
# in after bid/ask have arrived. Greeks (delta/IV) populate a beat later than the quote;
# without this wait, entry_iv is stored as None and the live delta re-gate is a no-op.
_GREEKS_WAIT_FRACTION = 0.6

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
    loop = asyncio.get_running_loop()
    # "101" requests open interest; model greeks (delta/IV) stream by default for options
    # and are used for the send-time re-gate and for storing entry IV at fill.
    ticker = ib.reqMktData(
        qualified, genericTickList="101", snapshot=False, regulatorySnapshot=False
    )

    def _has_quote() -> bool:
        # A valid two-sided market requires a non-None ask > 0. Bid may legitimately
        # be $0.00 on far-OTM options; requiring bid > 0 wrongly times out those orders.
        return ticker.bid is not None and ticker.ask is not None and ticker.ask > 0

    def _has_greeks() -> bool:
        g = getattr(ticker, "modelGreeks", None)
        return g is not None and _safe_float(getattr(g, "impliedVol", None)) is not None

    # Phase 1: wait for a usable bid/ask.
    deadline = loop.time() + timeout
    while not _has_quote() and loop.time() < deadline:
        await asyncio.sleep(0.1)

    # Phase 2: bid/ask are in — give modelGreeks a bounded extra window to stream so the
    # live delta re-gate has a delta and entry_iv is captured. Degrade gracefully if they
    # never arrive (entry_iv stays None; the re-gate falls back to the decision-time gate).
    greeks_deadline = loop.time() + timeout * _GREEKS_WAIT_FRACTION
    while _has_quote() and not _has_greeks() and loop.time() < greeks_deadline:
        await asyncio.sleep(0.1)

    ib.cancelMktData(qualified)

    bid = ticker.bid if ticker.bid is not None else None
    ask = ticker.ask if (ticker.ask is not None and ticker.ask > 0) else None

    if ask is None:
        raise ValueError(f"No live ask received for {candidate.candidate_id} within {timeout}s")

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


async def _refetch_bid_ask(ib: IB, qualified: Contract) -> tuple[float | None, float | None]:
    """Fresh bid/ask for an already-qualified contract — used by the chase loop (N11).

    The reprice loop runs 45–90 s after the order was placed, so the bid/ask captured at
    placement is stale by the time we chase. This pulls the *current* two-sided market (no
    re-qualify, no greeks wait — the chase only needs bid/ask) so each step moves toward the
    live bid, not a price that may no longer exist. Returns (bid, ask); ask is None unless a
    real positive ask arrived within the quote timeout.
    """
    timeout = _quote_timeout()
    loop = asyncio.get_running_loop()
    ticker = ib.reqMktData(
        qualified, genericTickList="101", snapshot=False, regulatorySnapshot=False
    )

    def _has_quote() -> bool:
        return ticker.bid is not None and ticker.ask is not None and ticker.ask > 0

    deadline = loop.time() + timeout
    while not _has_quote() and loop.time() < deadline:
        await asyncio.sleep(0.1)
    ib.cancelMktData(qualified)

    bid = _safe_float(ticker.bid)
    ask = _safe_float(ticker.ask)
    return bid, (ask if ask is not None and ask > 0 else None)


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

    # ROLL is a two-leg combo (buy-to-close + sell-to-open); the single-leg path below would
    # mis-send it as a naked SELL. Delegate to the dedicated combo executor, which qualifies
    # both legs, re-gates the new short, and places one atomic BAG order. (Imported lazily to
    # avoid a circular import — roll_executor reuses helpers from this module.)
    if candidate.strategy == Strategy.ROLL:
        from src.execution.roll_executor import execute_roll

        await execute_roll(ib, bot, chat_id, order_id, candidate)
        return

    try:
        if cfg.is_live:
            # Live mode: send a pre-quote notice, wait for human confirmation,
            # then fetch a FRESH quote immediately before placing the order.
            # This prevents a stale limit price computed before the confirm wait.
            confirm_event = register_live_confirm(order_id)
            from src.notify.formatters import format_live_confirm_request

            confirm_text = format_live_confirm_request(
                underlying=candidate.underlying,
                strike=candidate.strike,
                right=candidate.right.value,
                expiry=candidate.expiry,
                contracts=candidate.contracts,
            )
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("CONFIRM LIVE", callback_data=f"confirm_live:{order_id}")]]
            )
            await bot.send_message(
                chat_id=chat_id, text=confirm_text, parse_mode="MarkdownV2", reply_markup=keyboard
            )
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

        # Fetch a fresh quote now — after confirmation for live mode, immediately
        # for paper mode. This is the price that will be sent to the broker.
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
            from src.notify.sender import send_order_notification

            try:
                await send_order_notification(
                    "failed",
                    candidate=candidate,
                    order_id=order_id,
                    failure_reason=f"Live re-validation failed: {', '.join(live_verdict.reasons)}",
                )
            except Exception:
                log.exception(
                    "Failed to send re-gate failure notification for order_id=%s", order_id
                )
            return

        order = build_limit_order(candidate, quote)

        trade = ib.placeOrder(qualified, order)
        log.info(
            "Order placed — candidate=%s orderId=%s lmtPrice=%.2f",
            candidate.candidate_id,
            trade.order.orderId,
            order.lmtPrice,
        )

        lmt = float(order.lmtPrice) if order.lmtPrice is not None else None
        with session_scope() as session:
            row = session.get(OrderRow, order_id)
            if row:
                row.state = OrderState.SUBMITTED
                row.ib_order_id = trade.order.orderId
                row.limit_price = lmt

        from src.notify.sender import send_order_notification

        option_mid = (
            (quote.bid + quote.ask) / 2
            if quote.bid is not None and quote.ask is not None
            else quote.ask
        )
        try:
            await send_order_notification(
                "placed",
                candidate=candidate,
                order_id=order_id,
                limit_price=lmt,
                underlying_price=None,
                option_mid=option_mid,
            )
        except Exception:
            log.exception("Failed to send placed notification for order_id=%s", order_id)

        # Wait for terminal state or timeout — optionally chasing the fill by repricing the
        # limit toward the bid (config-gated; default off). The premium floor prevents the
        # chase from ever selling below min_live_premium_ratio × approved premium.
        exec_cfg = cfg.execution
        # `is True` (not bool()) so a MagicMock config attribute in tests reads as disabled.
        reprice_enabled = getattr(exec_cfg, "reprice_enabled", False) is True
        reprice_interval = _as_float(getattr(exec_cfg, "reprice_interval_seconds", 45.0), 45.0)
        max_reprices = int(_as_float(getattr(exec_cfg, "max_reprices", 0), 0.0))
        step_pct = _as_float(getattr(exec_cfg, "reprice_step_pct", 0.34), 0.34)
        risk_cfg = getattr(cfg, "risk", {})
        min_ratio = (
            (risk_cfg.get("live_execution", {}) or {}).get("min_live_premium_ratio")
            if isinstance(risk_cfg, dict)
            else None
        )
        min_ratio_f = _as_float(min_ratio, 0.0) if min_ratio is not None else 0.0
        floor = (
            min_ratio_f * candidate.premium if (min_ratio_f > 0 and candidate.premium > 0) else None
        )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + fill_timeout
        next_reprice_at = loop.time() + reprice_interval
        reprices_done = 0
        while not trade.isDone():
            await asyncio.sleep(1)
            now = loop.time()
            if now > deadline:
                log.warning("Fill timeout for order_id=%s — cancelling", order_id)
                ib.cancelOrder(trade.order)
                await asyncio.sleep(2)
                break
            if (
                reprice_enabled
                and reprices_done < max_reprices
                and now >= next_reprice_at
                and not trade.isDone()
            ):
                next_reprice_at = now + reprice_interval
                cur_limit = _safe_float(order.lmtPrice)
                # N11: chase the CURRENT market, not the bid captured before placement.
                fresh_bid, fresh_ask = await _refetch_bid_ask(ib, qualified)
                new_price = (
                    reprice_limit("SELL", cur_limit, fresh_bid, fresh_ask, step_pct, floor=floor)
                    if cur_limit is not None and fresh_bid is not None
                    else None
                )
                if new_price is not None:
                    order.lmtPrice = new_price  # modify in place (same orderId → IB amends)
                    ib.placeOrder(qualified, order)
                    reprices_done += 1
                    log.info(
                        "Reprice %d/%d order_id=%s -> %.2f",
                        reprices_done,
                        max_reprices,
                        order_id,
                        new_price,
                    )
                    with session_scope() as session:
                        row = session.get(OrderRow, order_id)
                        if row:
                            row.limit_price = new_price

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
                    action=order.action,  # "SELL" credit / "BUY" debit → signs EOD cashflow
                    filled_qty=filled_qty,
                    avg_price=avg_price,
                    commission=commission,
                    ib_exec_id=exec_id,
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

            # Campaign chaining (C6): update the wheel P&L thread for this symbol.
            try:
                from src.storage.campaigns import attach_fill_to_campaign

                attach_fill_to_campaign(
                    candidate.underlying,
                    candidate.candidate_id,
                    candidate.strategy.value,
                    order.action,
                    avg_price,
                    filled_qty,
                )
            except Exception:
                log.warning(
                    "Campaign update failed for %s — non-fatal",
                    candidate.candidate_id,
                    exc_info=True,
                )
            from src.notify.formatters import format_fill_confirm
            from src.notify.sender import send_order_notification

            msg = format_fill_confirm(
                underlying=candidate.underlying,
                strategy=candidate.strategy.value,
                strike=candidate.strike,
                right=candidate.right.value,
                expiry=candidate.expiry,
                filled_qty=filled_qty,
                avg_price=avg_price,
            )
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")
            try:
                await send_order_notification(
                    "filled",
                    candidate=candidate,
                    order_id=order_id,
                    limit_price=lmt,
                    filled_qty=filled_qty,
                    avg_price=avg_price,
                )
            except Exception:
                log.exception("Failed to send filled notification for order_id=%s", order_id)

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
            try:
                await send_order_notification(
                    "failed",
                    candidate=candidate,
                    order_id=order_id,
                    limit_price=lmt,
                    failure_reason=f"IB rejected: {ib_status}",
                )
            except Exception:
                log.exception("Failed to send IB-rejection notification for order_id=%s", order_id)

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
            try:
                await send_order_notification(
                    "failed",
                    candidate=candidate,
                    order_id=order_id,
                    limit_price=lmt,
                    failure_reason=f"Order timed out / cancelled ({ib_status})",
                )
            except Exception:
                log.exception("Failed to send timeout notification for order_id=%s", order_id)

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
