"""Roll execution as a single two-leg combo (BAG) order.

A roll buys back an existing short option (the *close* leg) and sells a new short at a
later expiry/strike (the *open* leg) in ONE combo order, so both legs fill
together-or-not-at-all — there is no legging risk where the buy-back fills but the
re-sell does not (leaving the account flat and un-hedged), or vice-versa.

This is the executable counterpart to ``strategies/rolling.construct_roll``
(which only *proposes* rolls) and replaces the old alert-only behaviour where
``executor.execute_candidate`` rejected every ``Strategy.ROLL`` outright.

Safety rails mirror ``executor.execute_candidate`` / ``position_manager.close_short_position``:
  * the new (open) leg is re-gated against a FRESH live quote (delta-in-range, and in
    LIVE mode IBKR-sourced greeks) before anything is transmitted — the buy-back leg is
    risk-*reducing* and is not gated, exactly as a standalone close is not;
  * a NET-CREDIT floor rejects the roll if the live net credit collapsed below the
    approved credit (``min_live_premium_ratio``) or went negative (a debit roll);
  * LIVE mode requires a second [CONFIRM LIVE] Telegram tap (reuses the executor's
    confirm-event registry, keyed by ``order_id``);
  * cancel-on-timeout leaves no unmonitored combo resting at the broker;
  * a defensive re-check skips the roll if the short to close is no longer net-short;
  * two FillRows are written — a BUY under the *original short's* candidate_id (so the
    verdict ledger labels it ``closed_early`` and EOD cashflow sees the debit) and a SELL
    under the new candidate's id (so the monitor tracks the new short, with entry IV).

The risk engine is still the only path to *new* exposure: the open leg passes
``validate_live_quote`` before the combo is sent. Nothing here sizes or gates from an LLM.
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

from ib_async import IB, Contract
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from src.claude.memory import FILLED, record_outcome
from src.common.config import get_config
from src.common.schemas import (
    CloseReason,
    OptionQuote,
    OptionRight,
    OrderState,
    PositionSnapshot,
    TradeCandidate,
)
from src.engine.risk_engine import validate_live_quote
from src.execution.executor import (
    _GREEKS_WAIT_FRACTION,
    _as_float,
    _live_confirm_events,
    _quote_timeout,
    _safe_float,
    _two_sided,
    register_live_confirm,
)
from src.execution.order_builder import _round_combo_tick, build_combo_roll_order
from src.ibkr.contracts import build_option
from src.ibkr.market_data import req_fresh_mkt_data
from src.ibkr.portfolio import get_positions
from src.storage.db import session_scope
from src.storage.models import CandidateRow, FillRow, OrderRow
from src.storage.roll_chains import synthetic_close_id

log = logging.getLogger(__name__)


def _resolve_short_to_close(
    positions: list[PositionSnapshot], candidate: TradeCandidate
) -> PositionSnapshot | None:
    """The exact short this roll was proposed for, or None (2026-10-11).

    Matched by conId when both sides carry one, else by the exact contract recorded in
    ``candidate.roll_from``. Never "the nearest-dated short on the same underlying": with
    GOOGL 330P and 335P open together that closed the wrong one. A roll without its origin
    is refused (the Rules Engine rejects it too, ``roll_origin_missing``).
    """
    origin = candidate.roll_from
    if origin is None:
        return None
    shorts = [
        p
        for p in positions
        if p.sec_type == "OPT"
        and p.position < 0
        and (p.underlying or p.symbol) == candidate.underlying
    ]
    if origin.con_id is not None:
        by_id = next((p for p in shorts if p.con_id == origin.con_id), None)
        if by_id is not None:
            return by_id
    return next(
        (
            p
            for p in shorts
            if p.right == origin.right
            and p.expiry == origin.expiry
            and p.strike is not None
            and abs(p.strike - origin.strike) < 1e-3
        ),
        None,
    )


def _walk_targets(start_net: float, *, natural_net: float, floor: float, steps: int) -> list[float]:
    """Net credits ($/sh) to step the combo through after the opening mid (2026-10-11).

    Concedes from the mid toward the natural price (new bid − old ask) in *steps* equal
    steps, never below *floor* — the roll policy's credit floor (or debit cap) and the
    approved-credit collapse floor, whichever is higher. Empty when there is nothing to
    concede or the walk is off.
    """
    lowest = max(natural_net, floor)
    if steps <= 0 or lowest >= start_net:
        return []
    return [round(start_net - (start_net - lowest) * i / steps, 4) for i in range(1, steps + 1)]


def _original_candidate_id(short: PositionSnapshot) -> str:
    """Return the candidate_id of the system short being closed, for ledger attribution.

    Looks up the candidate we actually SOLD on this exact contract (so the verdict-ledger
    reconciler labels the roll a ``closed_early`` of that short). Falls back to a synthetic
    ``roll-close:`` id when the short was not opened by this system — the BUY FillRow is
    still recorded so EOD cashflow includes the debit; only the ledger label is skipped.
    """
    assert short.expiry is not None and short.strike is not None and short.right is not None
    underlying = short.underlying or short.symbol
    with session_scope() as session:
        candidates = (
            session.query(CandidateRow)
            .join(FillRow, FillRow.candidate_id == CandidateRow.candidate_id)
            .filter(
                CandidateRow.underlying == underlying,
                CandidateRow.right == short.right.value,
                CandidateRow.expiry == short.expiry,
                FillRow.action == "SELL",
            )
            .all()
        )
        match = next((c for c in candidates if abs((c.strike or 0.0) - short.strike) < 1e-3), None)
        if match is not None:
            return cast(str, match.candidate_id)
    return synthetic_close_id(underlying, short.expiry, short.strike, short.right.value)


def _close_candidate_id(short: PositionSnapshot, candidate: TradeCandidate) -> str:
    """The candidate the roll's BUY fill is booked under: the short the roll was proposed for
    (``roll_from.candidate_id``) when known — the same id the chain walk follows — else the
    candidate that sold this contract, else the synthetic ``roll-close:`` id."""
    if candidate.roll_from is not None and candidate.roll_from.candidate_id:
        return candidate.roll_from.candidate_id
    return _original_candidate_id(short)


async def _fetch_leg(
    ib: IB,
    underlying: str,
    expiry: object,
    strike: float,
    right: OptionRight,
) -> tuple[OptionQuote, Contract]:
    """Qualify one option leg and snapshot its live bid/ask + greeks.

    Mirrors ``executor._fetch_quote`` but for an arbitrary contract (the roll needs a live
    quote and a qualified conId for *both* legs). Raises ``ValueError`` on qualify failure
    or when no live ask arrives within the quote timeout.
    """
    contract = build_option(underlying, expiry, strike, right.value)  # type: ignore[arg-type]
    qualified_list = await ib.qualifyContractsAsync(contract)
    if not qualified_list or not getattr(qualified_list[0], "conId", None):
        raise ValueError(f"could not qualify {underlying} {right.value} {strike} {expiry}")
    qualified = cast(Contract, qualified_list[0])

    timeout = _quote_timeout()
    loop = asyncio.get_running_loop()
    ticker = req_fresh_mkt_data(
        ib, qualified, genericTickList="101", snapshot=False, regulatorySnapshot=False
    )

    def _has_quote() -> bool:
        return _two_sided(ticker)

    def _has_greeks() -> bool:
        g = getattr(ticker, "modelGreeks", None)
        return g is not None and _safe_float(getattr(g, "impliedVol", None)) is not None

    deadline = loop.time() + timeout
    while not _has_quote() and loop.time() < deadline:
        await asyncio.sleep(0.1)
    greeks_deadline = loop.time() + timeout * _GREEKS_WAIT_FRACTION
    while _has_quote() and not _has_greeks() and loop.time() < greeks_deadline:
        await asyncio.sleep(0.1)

    ib.cancelMktData(qualified)

    bid = _safe_float(ticker.bid)
    ask = _safe_float(ticker.ask)
    ask = ask if ask is not None and ask > 0 else None
    if ask is None:
        raise ValueError(f"no live ask for {underlying} {right.value} {strike} {expiry}")

    greeks = getattr(ticker, "modelGreeks", None)
    quote = OptionQuote(
        underlying=underlying,
        right=right,
        strike=strike,
        expiry=expiry,  # type: ignore[arg-type]
        bid=bid,
        ask=ask,
        delta=_safe_float(getattr(greeks, "delta", None)) if greeks else None,
        iv=_safe_float(getattr(greeks, "impliedVol", None)) if greeks else None,
    )
    return quote, qualified


def _mark_order(order_id: int, state: str, detail: str) -> None:
    with session_scope() as session:
        row = session.get(OrderRow, order_id)
        if row and row.state not in (OrderState.FILLED, OrderState.PARTIAL):
            row.state = state
            row.detail = detail


def _leg_fill_summary(
    trade: object, conid: int, fallback_price: float
) -> tuple[float, float, float | None, str | None]:
    """Aggregate the fills for one combo leg, identified by its contract conId.

    Returns (filled_qty, avg_price, commission, exec_id). Combos fill atomically, so when
    a mock/broker omits per-leg fill granularity the caller supplies the leg's filled qty;
    here we only sum what the trade reports for this conId and fall back to ``fallback_price``
    (the mid the combo was priced at) when no per-leg price is present.
    """
    fills = [
        f
        for f in (getattr(trade, "fills", None) or [])
        if getattr(getattr(f, "contract", None), "conId", None) == conid
    ]
    if not fills:
        return 0.0, fallback_price, None, None
    qty = 0.0
    notional = 0.0
    commission = 0.0
    exec_id: str | None = None
    for f in fills:
        ex = getattr(f, "execution", None)
        shares = float(getattr(ex, "shares", 0.0) or 0.0)
        price = float(getattr(ex, "price", 0.0) or 0.0)
        qty += shares
        notional += price * shares
        exec_id = getattr(ex, "execId", exec_id)
        cr = getattr(f, "commissionReport", None)
        c = getattr(cr, "commission", None) if cr is not None else None
        if c is not None and c > 0:
            commission += c
    avg_price = (notional / qty) if qty > 0 else fallback_price
    return qty, avg_price, (commission or None), exec_id


async def execute_roll(
    ib: IB,
    bot: Bot,
    chat_id: str,
    order_id: int,
    candidate: TradeCandidate,
) -> None:
    """Execute a ROLL candidate as a single two-leg combo: resolve → confirm → quote →
    re-gate → place → monitor → record both fills."""
    cfg = get_config()
    fill_timeout = cfg.execution.fill_timeout_minutes * 60.0

    # 1. Resolve the existing short to buy back (we need its strike/expiry to qualify the
    #    close leg — the roll candidate only carries the NEW leg).
    try:
        positions = get_positions(ib)
    except Exception:
        log.exception("roll: could not load positions for %s", candidate.candidate_id)
        _mark_order(order_id, OrderState.REJECTED, "could not load positions")
        await _notify(
            bot, chat_id, f"Roll NOT placed — could not load positions for {candidate.underlying}."
        )
        return

    short = _resolve_short_to_close(positions, candidate)
    if short is None or short.expiry is None or short.strike is None or short.right is None:
        _mark_order(order_id, OrderState.REJECTED, "no matching short to roll")
        await _notify(
            bot,
            chat_id,
            f"Roll NOT placed — no open short {candidate.right.value} found for "
            f"{candidate.underlying} to roll.",
        )
        return

    if (
        candidate.roll_from is not None
        and int(abs(short.position)) != candidate.roll_from.contracts
    ):
        _mark_order(order_id, OrderState.REJECTED, "position_size_changed")
        await _notify(
            bot,
            chat_id,
            f"Roll NOT placed — the {candidate.underlying} short now holds "
            f"{int(abs(short.position))} contracts, not the {candidate.roll_from.contracts} "
            "the roll was approved for.",
        )
        return

    try:
        # 2. LIVE mode: pre-quote notice + human confirmation before any transmit.
        if cfg.is_live:
            confirm_event = register_live_confirm(order_id)
            from src.notify.formatters import format_live_confirm_request

            confirm_text = format_live_confirm_request(
                underlying=candidate.underlying,
                strike=candidate.strike,
                right=candidate.right.value,
                expiry=candidate.expiry,
                contracts=int(abs(short.position)),
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
                log.warning("roll: live confirmation timed out — order_id=%s", order_id)
                _mark_order(order_id, OrderState.CANCELLED, "Live confirmation timeout")
                await _notify(
                    bot,
                    chat_id,
                    f"Live confirmation timed out for the {candidate.underlying} roll "
                    f"(order_id={order_id}) — NOT placed.",
                )
                return

        # 3. Fresh quotes + qualified contracts for BOTH legs.
        new_quote, open_contract = await _fetch_leg(
            ib, candidate.underlying, candidate.expiry, candidate.strike, candidate.right
        )
        old_quote, close_contract = await _fetch_leg(
            ib, short.underlying or short.symbol, short.expiry, short.strike, short.right
        )
        new_mid, old_mid = new_quote.mid, old_quote.mid
        if new_mid is None or old_mid is None or new_mid <= 0 or old_mid <= 0:
            _mark_order(order_id, OrderState.REJECTED, "no two-sided market on a leg")
            await _notify(
                bot,
                chat_id,
                f"Roll NOT placed — no two-sided market on a {candidate.underlying} leg.",
            )
            return
        live_net_credit = new_mid - old_mid

        # 4. Re-gate. The new leg is checked as the ROLL it is — a two-sided market — not
        #    against the CC/CSP entry delta band: a breached short's roll target sits near
        #    0.5 delta by design. The roll's own send-time rules follow, from the same
        #    RollCfg the generator used: net at or above the floor (min_net_credit, or
        #    -cc.max_debit for a keep-shares call roll), |new delta| not above the old leg's,
        #    live IBKR greeks in LIVE mode, and no collapse below the approved net credit.
        # A roll is never regime- or ladder-limited: explicit sizing=None (a fence test checks it).
        verdict = validate_live_quote(candidate, new_quote, sizing=None)
        reasons = list(verdict.reasons)
        origin = candidate.roll_from
        assert origin is not None  # _resolve_short_to_close refused a roll without one
        roll_floor = (
            -cfg.roll.cc.max_debit if origin.allow_debit else cfg.roll.new_leg.min_net_credit
        )
        if live_net_credit < roll_floor - 1e-9:
            reasons.append("roll_net_below_floor")
        if (
            new_quote.delta is not None
            and old_quote.delta is not None
            and abs(new_quote.delta) > abs(old_quote.delta) + 1e-9
        ):
            reasons.append("roll_delta_increases")
        live_cfg = cfg.risk.get("live_execution", {}) or {}
        if (
            cfg.is_live
            and live_cfg.get("require_ibkr_greeks_when_live", True)
            and (new_quote.delta is None or new_quote.greeks_source != "ibkr")
        ):
            reasons.append("live_greeks_required")
        min_ratio = _as_float(live_cfg.get("min_live_premium_ratio"), 0.0)
        collapse_floor = min_ratio * candidate.premium if candidate.premium > 0 else roll_floor
        if candidate.premium > 0 and min_ratio and live_net_credit < collapse_floor:
            reasons.append("roll_credit_collapse")

        if reasons:
            log.warning("roll: re-gate REJECT order_id=%s reasons=%s", order_id, reasons)
            _mark_order(order_id, OrderState.REJECTED, f"Roll re-validation failed: {reasons}")
            await _notify(
                bot,
                chat_id,
                f"Roll NOT placed — {candidate.underlying} failed re-validation "
                f"({', '.join(reasons)}).",
            )
            return

        # 5. Build + place the combo.
        contracts = int(abs(short.position))
        combo, order = build_combo_roll_order(
            candidate.underlying,
            int(close_contract.conId),
            int(open_contract.conId),
            contracts,
            live_net_credit,
        )
        trade = ib.placeOrder(combo, order)
        log.info(
            "roll combo placed — order_id=%s %s close %.0f @%.2f → open %s %.0f net=%.2f",
            order_id,
            candidate.underlying,
            short.strike,
            old_mid,
            candidate.strike,
            new_mid,
            live_net_credit,
        )
        with session_scope() as session:
            row = session.get(OrderRow, order_id)
            if row:
                row.state = OrderState.SUBMITTED
                row.ib_order_id = trade.order.orderId
                row.limit_price = float(order.lmtPrice) if order.lmtPrice is not None else None

        # 6. Wait for terminal state or timeout — cancel on timeout. Meanwhile walk the net
        #    limit from the mid toward the natural price (new bid − old ask) in
        #    roll.exec.reprice_steps bounded steps, never past the roll floor or the
        #    approved-credit collapse floor (2026-10-11; replaces the mid-chasing repricer).
        natural_net = (new_quote.bid or 0.0) - (old_quote.ask or 0.0)
        walk = _walk_targets(
            live_net_credit,
            natural_net=natural_net,
            floor=max(roll_floor, collapse_floor),
            steps=cfg.roll.exec.reprice_steps,
        )
        reprice_interval = _as_float(getattr(cfg.execution, "reprice_interval_seconds", 45.0), 45.0)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + fill_timeout
        next_reprice_at = loop.time() + reprice_interval
        while not trade.isDone():
            await asyncio.sleep(1)
            now = loop.time()
            if now > deadline:
                log.warning("roll: fill timeout order_id=%s — cancelling", order_id)
                ib.cancelOrder(trade.order)
                await asyncio.sleep(2)
                break
            if walk and now >= next_reprice_at and not trade.isDone():
                next_reprice_at = now + reprice_interval
                target = walk.pop(0)
                order.lmtPrice = _round_combo_tick(-target)
                ib.placeOrder(combo, order)
                log.info(
                    "roll walk %s net-limit -> %.2f (natural %.2f)",
                    candidate.underlying,
                    order.lmtPrice,
                    natural_net,
                )
                with session_scope() as session:
                    row = session.get(OrderRow, order_id)
                    if row:
                        row.limit_price = float(order.lmtPrice)

        filled_qty = float(getattr(trade.orderStatus, "filled", 0.0) or 0.0)
        net_avg = float(getattr(trade.orderStatus, "avgFillPrice", 0.0) or 0.0)
        ib_status = str(getattr(trade.orderStatus, "status", ""))

        if filled_qty > 0:
            _record_roll_fills(
                order_id=order_id,
                candidate=candidate,
                short=short,
                close_conid=int(close_contract.conId),
                open_conid=int(open_contract.conId),
                filled_qty=filled_qty,
                old_mid=old_mid,
                new_mid=new_mid,
                net_avg=net_avg,
                new_quote=new_quote,
                trade=trade,
                cfg=cfg,
            )
            record_outcome(candidate.candidate_id, FILLED)
            from src.notify.formatters import format_roll_fill_confirm

            await bot.send_message(
                chat_id=chat_id,
                text=format_roll_fill_confirm(
                    underlying=candidate.underlying,
                    old_strike=short.strike,
                    old_expiry=short.expiry,
                    new_strike=candidate.strike,
                    new_expiry=candidate.expiry,
                    right=candidate.right.value,
                    contracts=int(filled_qty),
                    net_credit=live_net_credit,
                ),
                parse_mode="MarkdownV2",
            )

        elif ib_status in ("Inactive", "ApiCancelled", "Error"):
            _mark_order(order_id, OrderState.REJECTED, f"IB rejected: {ib_status}")
            await _notify(
                bot, chat_id, f"Roll rejected by IB: {candidate.underlying} ({ib_status})"
            )
        else:
            _mark_order(order_id, OrderState.CANCELLED, f"Cancelled/timeout: {ib_status}")
            log.info("roll cancelled/timed-out — order_id=%s status=%s", order_id, ib_status)

    except Exception:
        log.exception(
            "roll: unexpected error order_id=%s candidate=%s", order_id, candidate.candidate_id
        )
        _mark_order(order_id, OrderState.REJECTED, "Roll execution exception")
        # Do not re-raise — runs inside a background asyncio Task.


def _record_roll_fills(
    *,
    order_id: int,
    candidate: TradeCandidate,
    short: PositionSnapshot,
    close_conid: int,
    open_conid: int,
    filled_qty: float,
    old_mid: float,
    new_mid: float,
    net_avg: float,
    new_quote: OptionQuote,
    trade: object,
    cfg: object,
) -> None:
    """Write the two FillRows for a filled combo and update the OrderRow.

    Combos fill atomically, so each leg's filled qty equals the combo's filled qty.
    Per-leg avg prices are taken from the trade's per-leg fills when present, else from
    the mids the combo was priced at.
    """
    close_id = _close_candidate_id(short, candidate)
    open_qty, open_price, open_comm, _ = _leg_fill_summary(trade, open_conid, new_mid)
    close_qty, close_price, close_comm, _ = _leg_fill_summary(trade, close_conid, old_mid)
    open_fallback, close_fallback = open_qty <= 0, close_qty <= 0
    if open_fallback:
        open_qty, open_price = filled_qty, new_mid
    if close_fallback:
        close_qty, close_price = filled_qty, old_mid
    # Without per-leg fills, the legs were priced at the proposal mids; anchor them to the
    # combo's actual net fill (credit = -net_avg) so a walked concession is not booked as the
    # mid's larger credit (review, 2026-10-11).
    if net_avg and (open_fallback or close_fallback):
        if open_fallback:
            open_price = close_price - net_avg
        else:
            close_price = open_price + net_avg

    is_live = bool(getattr(cfg, "is_live", False))
    with session_scope() as session:
        # SELL the new short — tracked under the roll candidate id, carries entry IV.
        session.add(
            FillRow(
                order_id=order_id,
                candidate_id=candidate.candidate_id,
                action="SELL",
                filled_qty=open_qty,
                avg_price=open_price,
                commission=open_comm,
                entry_iv=new_quote.iv,
                is_live=is_live,
            )
        )
        # BUY back the old short — attributed to the original short so the ledger labels
        # it closed_early and EOD cashflow sees the debit.
        session.add(
            FillRow(
                order_id=order_id,
                candidate_id=close_id,
                action="BUY",
                filled_qty=close_qty,
                avg_price=close_price,
                commission=close_comm,
                close_reason=CloseReason.ROLL.value,
                is_live=is_live,
            )
        )
        row = session.get(OrderRow, order_id)
        if row:
            row.state = (
                OrderState.FILLED if filled_qty >= candidate.contracts else OrderState.PARTIAL
            )
            row.filled_qty = filled_qty
            row.avg_fill_price = net_avg
    # Campaign chaining (C6): both legs belong to the symbol's wheel thread. Never raises.
    from src.storage.campaigns import attach_fill_to_campaign

    attach_fill_to_campaign(candidate.underlying, close_id, "roll", "BUY", close_price, close_qty)
    attach_fill_to_campaign(
        candidate.underlying, candidate.candidate_id, "roll", "SELL", open_price, open_qty
    )
    log.info(
        "roll filled — order_id=%s sell %s %.0f @%.2f / buy-close %s %.0f @%.2f",
        order_id,
        candidate.strike,
        open_qty,
        open_price,
        short.strike,
        close_qty,
        close_price,
    )


async def _notify(bot: Bot, chat_id: str, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        log.exception("roll: Telegram notify failed")
