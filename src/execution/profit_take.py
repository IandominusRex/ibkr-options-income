"""Profit-take orchestration — extracted from the notify layer (N23).

The 50%-profit-take check is trading control flow (it reads positions, prices the cost-to-close,
and either auto-buys-to-close or alerts), so it belongs in `src/execution/`, not in the Telegram
service. `approval_service` re-exports these names and the intraday loop calls `check_profit_takes`;
the Telegram sends go through the passed `bot` (a thin notifier), keeping this module's trading
logic independent of the notify layer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

from ib_async import IB
from ib_async import Contract as IBContract
from sqlalchemy import select
from sqlalchemy.orm import Session
from telegram import Bot

from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.schemas import PositionSnapshot
from src.execution.position_manager import close_short_position
from src.ibkr.contracts import build_option
from src.storage.db import session_scope
from src.storage.models import CandidateRow, FillRow
from src.storage.system_settings import is_automated_mode

log = logging.getLogger(__name__)


def net_entry_credit_per_share(
    session: Session,
    underlying: str,
    strike: float,
    expiry: object,
    right: str,
) -> float | None:
    """Qty-weighted average SELL credit for a contract, net of entry commission (F8).

    Returns None when no SELL fills exist (position opened outside the system) or the net
    credit is non-positive. Commission (a total $ figure per fill) is spread per share so the
    profit-take threshold reflects the round-trip cost rather than the raw premium.
    """
    rows = (
        session.execute(
            select(FillRow)
            .join(CandidateRow, CandidateRow.candidate_id == FillRow.candidate_id)
            .where(
                CandidateRow.underlying == underlying,
                CandidateRow.strike == strike,
                CandidateRow.expiry == expiry,
                CandidateRow.right == right,
                FillRow.action == "SELL",
            )
        )
        .scalars()
        .all()
    )
    total_qty = sum(r.filled_qty for r in rows)
    if total_qty <= 0:
        return None
    gross_dollars = sum(r.avg_price * r.filled_qty * 100 for r in rows)
    commission = sum(r.commission or 0.0 for r in rows)
    net_per_share = (gross_dollars - commission) / (total_qty * 100)
    return net_per_share if net_per_share > 0 else None


async def _quote_short(ib_scan: IB, pos: PositionSnapshot) -> tuple[float, float | None]:
    """Live (bid, ask) for a short option position. Returns (0.0, None) on failure.

    Polls in 0.1 s steps and returns as soon as a two-sided market arrives rather than
    burning the full quote timeout per position (N14).
    """
    cfg = get_config()
    assert pos.expiry is not None and pos.strike is not None and pos.right is not None
    try:
        contract = build_option(
            pos.underlying or pos.symbol, pos.expiry, pos.strike, pos.right.value
        )
        qualified_list = await ib_scan.qualifyContractsAsync(contract)
        if not qualified_list:
            return 0.0, None
        qualified = cast(IBContract, qualified_list[0])
        ticker = ib_scan.reqMktData(qualified, "101", False, False)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + float(cfg.execution.quote_timeout_seconds)

        def _two_sided(t: object = ticker) -> bool:
            b, a = getattr(t, "bid", None), getattr(t, "ask", None)
            try:
                return b is not None and a is not None and float(a) > 0
            except (TypeError, ValueError):
                return False

        while not _two_sided() and loop.time() < deadline:
            await asyncio.sleep(0.1)
        ib_scan.cancelMktData(qualified)

        raw_bid, raw_ask = ticker.bid, ticker.ask
        bid = float(raw_bid) if raw_bid is not None and float(raw_bid) > 0 else 0.0
        ask = float(raw_ask) if raw_ask is not None and float(raw_ask) > 0 else None
        return bid, ask
    except Exception:
        log.exception("quote fetch failed for %s", pos.symbol)
        return 0.0, None


async def _send_profit_alert(
    pos: PositionSnapshot,
    entry_price: float,
    current_mid: float,
    profit_pct: float,
    bot: Bot,
    chat_id: str,
) -> None:
    from src.notify.formatters import format_profit_alert

    text = format_profit_alert(
        underlying=pos.underlying or pos.symbol,
        strike=pos.strike or 0.0,
        right=pos.right or "C",
        expiry=pos.expiry or today_et(),
        entry_price=entry_price,
        current_mid=current_mid,
        profit_pct=profit_pct,
    )
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
    except Exception:
        log.exception("Failed to send profit alert for %s", pos.symbol)


async def _auto_close_position(
    ib_exec: IB,
    pos: PositionSnapshot,
    bid: float,
    ask: float,
    bot: Bot,
    chat_id: str,
) -> None:
    """Buy-to-close a short option that hit its profit target, then notify Telegram.

    Trading logic + the OrderRow/FillRow lifecycle + cancel-on-timeout + idempotency live in
    ``position_manager.close_short_position`` (SYSTEM_REVIEW F1). This function is just the notify
    glue: delegate, then format the result for Telegram.
    """
    from src.execution.position_manager import close_short_position
    from src.notify.formatters import format_auto_close_result

    result = await close_short_position(ib_exec, pos, bid, ask)

    if result.status == "skipped":
        # A close is already working for this contract — no duplicate, no extra message.
        log.info("Auto-close skipped for %s (%s)", pos.symbol, result.detail)
        return

    if result.status == "error":
        from src.notify.formatters import _md, contract_label

        label = _md(
            contract_label(
                pos.underlying or pos.symbol,
                pos.strike or 0.0,
                pos.right or "C",
                pos.expiry or today_et(),
            )
        )
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Auto\\-close error for {label} — check IBKR manually\\.",
                parse_mode="MarkdownV2",
            )
        except Exception:
            log.exception("Failed to send auto-close error for %s", pos.symbol)
        return

    text = format_auto_close_result(
        underlying=pos.underlying or pos.symbol,
        strike=pos.strike or 0.0,
        right=pos.right or "C",
        expiry=pos.expiry or today_et(),
        qty=result.qty,
        limit_price=result.limit_price,
        filled_qty=result.filled_qty,
        avg_price=result.avg_price,
    )
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
    except Exception:
        log.exception("Failed to send auto-close result for %s", pos.symbol)


async def check_profit_takes(
    ib_scan: IB,
    ib_exec: IB | None,
    bot: Bot,
    chat_id: str,
) -> None:
    """Detect short option positions that have reached the profit-take threshold.

    Uses ib_scan for market-data quotes and ib_exec for placing BUY-to-close orders in automated
    mode; sends a Telegram alert in manual mode.
    """
    cfg = get_config()
    threshold = cfg.scheduler.profit_take_pct / 100.0

    from src.ibkr.portfolio import get_positions

    try:
        positions = get_positions(ib_scan)
    except Exception:
        log.exception("profit-take: failed to load positions")
        return

    short_opts = [
        p
        for p in positions
        if p.sec_type == "OPT"
        and p.position < 0
        and p.expiry is not None
        and p.strike is not None
        and p.right is not None
    ]

    for pos in short_opts:
        # All three are non-None by the short_opts filter above.
        assert pos.expiry is not None and pos.strike is not None and pos.right is not None
        right_value = pos.right.value

        # Entry credit = qty-weighted average of ALL SELL fills for this contract, net of the
        # entry commission (SYSTEM_REVIEW F8) — not just the last fill's price.
        with session_scope() as s:
            entry_price = net_entry_credit_per_share(
                s, pos.underlying or pos.symbol, pos.strike, pos.expiry, right_value
            )

        if entry_price is None or entry_price <= 0:
            continue

        bid, ask = await _quote_short(ib_scan, pos)
        if ask is None:
            continue

        mid = (bid + ask) / 2 if bid > 0 else ask
        profit_pct = 1.0 - (mid / entry_price)

        if profit_pct < threshold:
            continue

        log.info(
            "Profit target reached: %s — entry=%.2f mid=%.2f profit=%.0f%%",
            pos.symbol,
            entry_price,
            mid,
            profit_pct * 100,
        )

        if is_automated_mode() and ib_exec is not None:
            await _auto_close_position(ib_exec, pos, bid, ask, bot, chat_id)
        else:
            await _send_profit_alert(pos, entry_price, mid, profit_pct, bot, chat_id)


async def check_loss_exits(
    ib_scan: IB,
    ib_exec: IB | None,
    bot: Bot,
    chat_id: str,
) -> None:
    """Buy to close any short whose cost-to-close has reached ``max_loss_multiple`` x credit.

    The system previously had no loss-side exit at all: the only ways out were the 50% profit
    take, expiry, assignment, and alert-only roll triggers. Short premium's entire risk lives
    in the left tail, so an unattended loop that can only add risk and harvest winners is the
    one configuration that can genuinely hurt the account (D3).

    Closing risk is always permitted, so this runs on ``automation.auto_close_enabled``
    independently of the autonomy level — that setting governs *opening* exposure.
    """
    cfg = get_config()
    if not getattr(cfg.automation, "auto_close_enabled", True):
        return
    multiple = float(getattr(cfg.automation, "max_loss_multiple", 0.0) or 0.0)
    if multiple <= 0 or ib_exec is None:
        return

    from src.ibkr.portfolio import get_positions

    try:
        positions = get_positions(ib_scan)
    except Exception:
        log.exception("loss-exit: failed to load positions")
        return

    for pos in positions:
        if not (
            pos.sec_type == "OPT"
            and pos.position < 0
            and pos.expiry is not None
            and pos.strike is not None
            and pos.right is not None
        ):
            continue

        with session_scope() as s:
            entry = net_entry_credit_per_share(
                s, pos.underlying or pos.symbol, pos.strike, pos.expiry, pos.right.value
            )
        if entry is None or entry <= 0:
            continue

        bid, ask = await _quote_short(ib_scan, pos)
        if ask is None:
            continue
        mid = (bid + ask) / 2 if bid > 0 else ask
        if mid < multiple * entry:
            continue

        log.warning(
            "Loss exit triggered: %s — entry=%.2f mid=%.2f (%.1fx)",
            pos.symbol,
            entry,
            mid,
            mid / entry,
        )
        result = await close_short_position(ib_exec, pos, bid, ask)

        if result.status == "skipped":
            # A close is already working for this contract — no duplicate, no extra message.
            log.info("Loss-exit skipped for %s (%s)", pos.symbol, result.detail)
            continue

        from src.notify.formatters import _md, contract_label

        label = _md(
            contract_label(
                pos.underlying or pos.symbol, pos.strike, pos.right.value, pos.expiry
            )
        )

        if result.status == "error":
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Loss-exit error for {label} — check IBKR manually\\.",
                    parse_mode="MarkdownV2",
                )
            except Exception:
                log.exception("Failed to send loss-exit error for %s", pos.symbol)
            continue

        # Check if the order actually filled. status="working" can mean timeout/cancel with zero fill.
        if result.filled_qty <= 0:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"⚠️ *Loss-exit did not fill* — {label}\n"
                        f"Order placed but did not fill — check IBKR manually\\."
                    ),
                    parse_mode="MarkdownV2",
                )
            except Exception:
                log.exception("Failed to send loss-exit did-not-fill message for %s", pos.symbol)
            continue

        # Send result with actual fill information (only when filled_qty > 0)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🛑 *Loss exit closed* — {label}\n"
                    f"Entry credit {_md(f'${entry:.2f}')}, closed at "
                    f"{_md(f'${result.avg_price:.2f}')} · {result.filled_qty} filled"
                ),
                parse_mode="MarkdownV2",
            )
        except Exception:
            log.exception("Failed to send loss-exit result for %s", pos.symbol)
