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
    below its trailing high-water mark (``drawdown_breached`` / `system_settings`'s
    ``get_high_water_mark``/``set_high_water_mark``). Catches the slow bleed that no
    single day's loss trips.

Nothing here feeds the risk engine, scoring, or sizing — it only gates whether the
order machinery runs, so it stays clear of "the fence" around the deterministic layer.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.schemas import OrderState, PositionSnapshot
from src.storage.models import FillRow, OrderRow
from src.storage.positions import load_latest_position_snapshot
from src.storage.system_settings import get_high_water_mark, set_high_water_mark

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
    """Count new-exposure entry orders opened today (excludes `close:` buy-to-close orders)."""
    start, end = _et_day_window_utc()
    return int(
        session.execute(
            select(func.count())
            .select_from(OrderRow)
            .where(
                OrderRow.created_at >= start,
                OrderRow.created_at < end,
                OrderRow.state.in_(_OPENED_STATES),
                OrderRow.candidate_id.notlike("close:%"),
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


def mark_based_loss(positions: list[PositionSnapshot], net_liquidation: float) -> float | None:
    """Today's mark-to-market loss if it breaches ``daily_loss_halt_pct``, else None.

    ``realized_cashflow_today`` sums FillRow credits and debits, so a day that sells premium
    into a 15% drawdown registers as a *profit* and the kill switch stays open while the
    15-minute loop opens more shorts into the same move (D3). This measures what actually
    happened to the book: today's summed ``unrealized_pnl`` against the prior snapshot's.

    Returns the loss as a positive number, or None when the breaker is disabled, no baseline
    exists, or no breach occurred.
    """
    pct = get_config().automation.daily_loss_halt_pct
    if not pct or net_liquidation <= 0:
        return None
    baseline_positions = load_latest_position_snapshot(before=today_et())
    if not baseline_positions:
        baseline_positions = load_latest_position_snapshot()
    if not baseline_positions:
        return None  # no baseline yet — cannot measure a delta
    baseline = sum(p.unrealized_pnl or 0.0 for p in baseline_positions)
    current = sum(p.unrealized_pnl or 0.0 for p in positions)
    delta = current - baseline
    if delta >= 0:
        return None
    loss = -delta
    return loss if loss >= (pct / 100.0) * net_liquidation else None


def drawdown_breached(net_liquidation: float) -> float | None:
    """Drawdown from the trailing net-liquidation high-water mark, if it breaches the cap.

    Catches the slow bleed no single day trips. Advances the high-water mark on a new high
    as a side effect, so the first call after a fresh install simply seeds it.
    """
    pct = getattr(get_config().automation, "drawdown_halt_pct", 0.0)
    if not pct or net_liquidation <= 0:
        return None
    hwm = get_high_water_mark()
    if net_liquidation > hwm:
        set_high_water_mark(net_liquidation)
        return None
    if hwm <= 0:
        set_high_water_mark(net_liquidation)
        return None
    drawdown = hwm - net_liquidation
    return drawdown if drawdown >= (pct / 100.0) * hwm else None
