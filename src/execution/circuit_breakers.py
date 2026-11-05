"""Circuit breakers for AUTOMATED mode (SYSTEM_REVIEW Phase 2).

The cumulative risk gate bounds *exposure*; these bound *activity* and *losses* — the
standard kit for any auto-trading loop. They are deterministic and read-only except for
auto-tripping the persisted kill switch (`system_settings.set_halted`).

Breakers, all configured under `automation:` in settings.yaml:
  * ``max_auto_trades_per_day`` — refuse to open more than N new-exposure entry orders
    per ET trading day (auto or manual). Buy-to-close orders (`close:` candidate ids)
    don't count — closing risk is always allowed.
  * ``daily_loss_halt_pct`` — auto-engage the kill switch when today's MARK-TO-MARKET
    loss (``mark_based_loss``, today's summed ``unrealized_pnl`` vs. the prior position
    snapshot's) exceeds N% of net liquidation. An income desk always shows a positive
    *cashflow* on a day it sells premium, so the older ``daily_loss_breached``/
    ``realized_cashflow_today`` cashflow measure read a real drawdown as a profit (D3) —
    it's kept only for its existing tests and is no longer wired into the intraday loop.
  * ``drawdown_halt_pct`` — auto-engage the kill switch when net liquidation falls N%
    below its highest level of the last ``drawdown_window_days`` sessions (``drawdown_breached``;
    the level comes from ``portfolio_snapshots.window_high_net_liq`` — a rolling window, not an
    all-time peak, which left a standing drawdown halting every morning).
    Catches the slow bleed that no single day's loss trips.

Nothing here feeds the risk engine, scoring, or sizing — it only gates whether the
order machinery runs, so it stays clear of "the fence" around the deterministic layer.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.schemas import OrderState, PositionSnapshot
from src.storage.db import session_scope
from src.storage.models import FillRow, OrderRow
from src.storage.portfolio_snapshots import window_high_net_liq
from src.storage.positions import load_latest_position_snapshot
from src.storage.system_settings import (
    get_breaker_ack,
    record_breaker_ack,
)

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# Order states that represent a real attempt to open a position (working or done).
_OPENED_STATES = (
    OrderState.SUBMITTED,
    OrderState.FILLED,
    OrderState.PARTIAL,
)


def _et_day_window_utc(today: date | None = None) -> tuple[datetime, datetime]:
    """[start, end) of the ET trading day, as UTC datetimes (fills are stored UTC)."""
    today = today or datetime.now(_ET).date()
    nxt = today + timedelta(days=1)
    start = datetime(today.year, today.month, today.day, tzinfo=_ET).astimezone(UTC)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=_ET).astimezone(UTC)
    return start, end


def entry_orders_today(session: Session) -> int:
    """Count new-exposure entry orders opened today.

    Excludes ``close:`` buy-to-close orders and rolls (a roll swaps one short for another of
    the same size — no new exposure, 2026-10-14).
    """
    start, end = _et_day_window_utc()
    strategy = func.json_extract(OrderRow.snapshot, "$.strategy")
    return int(
        session.execute(
            select(func.count())
            .select_from(OrderRow)
            .where(
                OrderRow.created_at >= start,
                OrderRow.created_at < end,
                OrderRow.state.in_(_OPENED_STATES),
                OrderRow.candidate_id.notlike("close:%"),
                or_(strategy.is_(None), strategy != "roll"),
            )
        ).scalar_one()
    )


def realized_cashflow_today(session: Session) -> float:
    """Net signed option cashflow today: SELL credits (+) minus BUY debits (−), ×100."""
    start, end = _et_day_window_utc()
    fills = session.execute(
        select(FillRow).where(FillRow.filled_at >= start, FillRow.filled_at < end)
    ).scalars()
    return sum(
        (-1.0 if (f.action or "SELL").upper() == "BUY" else 1.0) * f.avg_price * f.filled_qty * 100
        for f in fills
    )


def remaining_entry_allowance(session: Session) -> int | None:
    """Entry orders still permitted today under ``max_auto_trades_per_day``.

    Returns ``None`` when the cap is disabled (0), else ``max(cap - opened_today, 0)``.
    Reads the cap from the live config so the daemon and tests share one source of truth.
    """
    cap = get_config().automation.max_auto_trades_per_day
    if not cap:  # 0 disables
        return None
    return max(cap - entry_orders_today(session), 0)


def daily_loss_breached(session: Session, net_liquidation: float) -> float | None:
    """Return the loss amount (positive number) if today's realized loss breaches the cap.

    Returns ``None`` when the breaker is disabled, net liq is unknown, or no breach.

    Superseded by ``mark_based_loss`` as the breaker wired into the intraday loop (D3):
    this sums FillRow credits/debits, so a day that sells premium into a real drawdown
    reads as a *profit* here and the kill switch never trips. Kept for its existing tests;
    not called from `process_queued_orders` anymore.
    """
    pct = get_config().automation.daily_loss_halt_pct
    if not pct or net_liquidation <= 0:
        return None
    cashflow = realized_cashflow_today(session)
    if cashflow >= 0:
        return None
    loss = -cashflow
    if loss >= (pct / 100.0) * net_liquidation:
        return loss
    return None


def _position_key(p: PositionSnapshot) -> tuple:
    """Identity of a holding across two snapshots (the stored one may predate ``con_id``)."""
    return (p.sec_type, p.symbol, p.right, p.strike, p.expiry)


def _closing_fills_today() -> dict[str, float]:
    """``close:`` candidate id → volume-weighted buy-back price of today's buy-to-close fills."""
    start, end = _et_day_window_utc()
    with session_scope() as s:
        rows = s.execute(
            select(FillRow.candidate_id, FillRow.filled_qty, FillRow.avg_price).where(
                FillRow.filled_at >= start,
                FillRow.filled_at < end,
                FillRow.action == "BUY",
                FillRow.candidate_id.like("close:%"),
            )
        ).all()
    qty: dict[str, float] = {}
    notional: dict[str, float] = {}
    for cid, q, px in rows:
        qty[cid] = qty.get(cid, 0.0) + q
        notional[cid] = notional.get(cid, 0.0) + q * px
    return {cid: notional[cid] / q for cid, q in qty.items() if q > 0}


def _mark_delta(positions: list[PositionSnapshot]) -> float | None:
    """Today's change in the book's value against the prior EOD snapshot (negative = loss).

    Like-for-like: a holding in both snapshots contributes the change in its unrealized P&L;
    one opened today contributes its whole unrealized P&L. One that is gone contributes its
    move from the snapshot mark to today's buy-to-close fill when a ``close:`` fill is on file —
    the realized part the old sum threw away, which made a profit-take close read as a loss
    (its unrealized left the sum) and a loss exit read as relief. A holding that vanished with
    no ``close:`` fill (a roll, an assignment, an expiry, a manual trade) contributes nothing:
    unknown is neutral, never a guessed loss or gain. ``None`` when there is no baseline yet.
    """
    baseline = load_latest_position_snapshot(before=today_et())
    if not baseline:
        baseline = load_latest_position_snapshot()
    if not baseline:
        return None  # no baseline yet — cannot measure a delta
    before = {_position_key(p): p for p in baseline}
    now = {_position_key(p): p for p in positions}
    delta = 0.0
    for key, p in now.items():
        b = before.get(key)
        delta += (p.unrealized_pnl or 0.0) - ((b.unrealized_pnl or 0.0) if b else 0.0)
    gone = [b for key, b in before.items() if key not in now]
    if gone:
        from src.execution.position_manager import close_candidate_id

        fills = _closing_fills_today()
        for b in gone:
            if b.sec_type != "OPT" or b.market_price is None or b.expiry is None:
                continue
            if b.strike is None or b.right is None:
                continue
            fill = fills.get(close_candidate_id(b))
            if fill is not None:
                delta += (fill - b.market_price) * b.position * 100.0
    return delta


def mark_based_loss(positions: list[PositionSnapshot], net_liquidation: float) -> float | None:
    """Today's mark-to-market loss if it breaches ``daily_loss_halt_pct``, else None.

    ``realized_cashflow_today`` sums FillRow credits and debits, so a day that sells premium
    into a 15% drawdown registers as a *profit* and the kill switch stays open while the
    15-minute loop opens more shorts into the same move (D3). This measures what actually
    happened to the book (``_mark_delta``): today's P&L against the prior snapshot's.

    Returns the loss as a positive number, or None when the breaker is disabled, no baseline
    exists, or no breach occurred.
    """
    pct = get_config().automation.daily_loss_halt_pct
    if not pct or net_liquidation <= 0:
        return None
    delta = _mark_delta(positions)
    if delta is None or delta >= 0:
        return None
    loss = -delta
    return loss if loss >= (pct / 100.0) * net_liquidation else None


def _drawdown_raw(net_liquidation: float) -> tuple[float, float] | None:
    """``(drawdown, window high)``, or None when the breaker is off, net liq is unknown, no
    snapshot history exists yet, or net liq is at or above the window's high.

    The high is read from the monitor's portfolio snapshots (``window_high_net_liq``), so it
    needs no breaker run to stay current."""
    cfg = get_config().automation
    pct = getattr(cfg, "drawdown_halt_pct", 0.0)
    if not pct or net_liquidation <= 0:
        return None
    hwm = window_high_net_liq(cfg.drawdown_window_days)
    if hwm <= 0 or net_liquidation >= hwm:
        return None
    return hwm - net_liquidation, hwm


def drawdown_breached(net_liquidation: float) -> float | None:
    """Drawdown from the rolling-window net-liquidation high, if it breaches the cap.

    Catches the slow bleed no single day trips.
    """
    raw = _drawdown_raw(net_liquidation)
    if raw is None:
        return None
    drawdown, hwm = raw
    pct = get_config().automation.drawdown_halt_pct
    return drawdown if drawdown >= (pct / 100.0) * hwm else None


def _breach(
    amount: float, line: float, acked: float | None, armed: bool
) -> tuple[bool, float | None]:
    """One breaker's verdict under the operator's acknowledgement → ``(trip, ack level to store)``.

    ``acked`` is the level the operator resumed through (None until measured); ``armed`` says a
    resume left an ack to be measured. A breach that was just acknowledged records its level
    and does not trip; after that it takes a further full ``line`` of loss to trip again, so
    /resume buys a real window instead of a 30-second one. Below the line nothing trips, and
    an armed ack is stored as 0 (no head-room beyond the normal line).
    """
    if amount < line:
        return False, (0.0 if armed else acked)
    if armed:
        return False, amount
    if acked is not None and amount < acked + line:
        return False, acked
    return True, acked


def evaluate_breakers(positions: list[PositionSnapshot], net_liquidation: float) -> str | None:
    """The reason to trip the kill switch (daily loss, then drawdown), or None.

    Honours the operator's /resume acknowledgement of today's breach (``system_settings``
    ``breaker_ack``, one ET day): the level they resumed through, plus a further full
    threshold, is needed to halt again. Stores the level the first time it measures after a
    resume. The deterministic measures are unchanged; only the re-trip rule is new.
    """
    cfg = get_config().automation
    if net_liquidation <= 0:
        return None
    today = today_et()
    ack = get_breaker_ack(today, keep_days=cfg.drawdown_window_days)
    new_loss = ack["loss"] if ack else None
    new_dd = ack["drawdown"] if ack else None
    reason: str | None = None

    loss_pct = cfg.daily_loss_halt_pct
    delta = _mark_delta(positions) if loss_pct else None
    if delta is not None:
        loss = max(-delta, 0.0)
        trip, new_loss = _breach(
            loss,
            (loss_pct / 100.0) * net_liquidation,
            new_loss,
            ack is not None and new_loss is None,
        )
        if trip:
            reason = f"Daily mark-to-market loss ${loss:,.0f}"

    raw = _drawdown_raw(net_liquidation)
    if raw is not None:
        drawdown, hwm = raw
        trip, new_dd = _breach(
            drawdown,
            (cfg.drawdown_halt_pct / 100.0) * hwm,
            new_dd,
            ack is not None and new_dd is None,
        )
        if trip and reason is None:
            reason = f"Drawdown ${drawdown:,.0f} from the {cfg.drawdown_window_days}-session high"

    if ack is not None and (new_loss, new_dd) != (ack["loss"], ack["drawdown"]):
        record_breaker_ack(today, loss=new_loss, drawdown=new_dd)
    return reason
