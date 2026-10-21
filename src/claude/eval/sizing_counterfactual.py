"""Counterfactual valuation of sizing actions (market-picture spec section 10).

``sizing_actions`` rows say what the market regime, the leveraged-ETF ceiling, a guaranteed floor
lot or Claude's size cut did to a cash-secured put: the size it would otherwise have been, the size
that was sent, and why. This module says, later, what the difference earned, so a human can decide
whether the limits and Claude's overrides pay before the live cutover (``scripts/sizing_report.py``).

Two kinds of value, kept apart and never blended:

* **Exact** - some contracts of the action's order really traded, so the contracts that were
  withheld are valued at the traded contract's realised P&L per contract (the shared accounting
  rule, ``src.reporting.legs.fill_economics``). Written to both shadow columns.
* **Shadow** - nothing traded for those contracts. ``shadow_pnl_expiry`` marks the option to its
  expiry close (premium less intrinsic value); ``shadow_pnl_rules`` walks the daily closes to
  expiry, prices the option each day with Black-Scholes at the entry IV, and exits at the system's
  own profit-take line (``resolve_profit_take_pct``) or, for a leveraged ETF, its loss-exit line
  (``automation.max_loss_multiple``: every other short is rolled, not closed, at that line, so the
  mark does not invent a stop for it). Marking to expiry alone would flatter every block made in a
  selloff, because it ignores the loss exits.

A positive value is what the withheld contracts would have **earned**: the trim, block or cut cost
that much (for ``regime_floor_lot`` the contracts valued are the lots the floor *let through*, so
positive means letting them through paid).

Enrichment tier, read by a human: nothing here reaches the engine, a gate, a weight or a size (the
fence, ``tests/test_eval_skills.py`` and ``tests/test_regime_fence.py``). The only thing written is
the value columns and ``resolved_at`` of the rows being resolved.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.analytics.black_scholes import bs_price
from src.common.config import get_config
from src.common.schemas import OptionRight
from src.common.universe import is_leveraged_etf
from src.reporting.legs import OPTION_MULTIPLIER, fill_economics
from src.storage.db import session_scope
from src.storage.models import FillRow, OrderRow, PriceHistoryRow, SizingActionRow

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_EPS = 1e-9
_SUGGESTED = re.compile(r"Claude suggested (\d+)")
# How far past an expiry the store must reach for an earlier bar to stand in for it (a holiday).
_HOLIDAY_SLACK_DAYS = 7


@dataclass(frozen=True)
class _Effect:
    """What an action's order did, as far as the valuation is concerned."""

    state: str  # "none" (no order) | "working" | "moot" (never filled) | "traded"
    sent: int  # contracts that actually traded (the row's own `sent` when there is no order)


def _effect(row: SizingActionRow, order: OrderRow | None) -> _Effect:
    if row.order_id is None or order is None:
        return _Effect("none", row.sent_contracts)
    filled = int(order.filled_qty or 0)
    if filled > 0:
        return _Effect("traded", filled)
    if order.state in ("queued", "submitted"):
        return _Effect("working", row.sent_contracts)
    # Cancelled or rejected with nothing filled (a trim the gate later refused keeps its row and
    # its `sent`): nothing was sent, and nothing was prevented from sending by the action.
    return _Effect("moot", 0)


def _withheld(row: SizingActionRow, sent: int) -> int:
    """The contracts whose earnings the action is judged on (see the module docstring)."""
    if row.kind == "regime_floor_lot":
        return max(sent, 0)  # the floor lot itself: what letting it through earned
    if row.kind == "claude_cut_unapplied":
        m = _SUGGESTED.search(row.reason or "")
        return max(row.deterministic_contracts - int(m.group(1)), 0) if m else 0
    return max(row.deterministic_contracts - sent, 0)


def _is_put(row: SizingActionRow) -> bool:
    return row.right == OptionRight.PUT.value


def _intrinsic(row: SizingActionRow, spot: float) -> float:
    return max(row.strike - spot, 0.0) if _is_put(row) else max(spot - row.strike, 0.0)


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #


def _provider_closes(symbol: str, start: date, end: date) -> dict[date, float]:
    """Daily closes from the price provider, for the days the store lacks. Empty on any failure."""
    try:
        from src.analytics.price_data import get_ohlcv

        frame = get_ohlcv(symbol)
        out: dict[date, float] = {}
        for idx, close in frame["Close"].items():
            day = idx.date() if hasattr(idx, "date") else idx
            if start <= day <= end:
                out[day] = float(close)
        return out
    except Exception:  # noqa: BLE001 - a missing provider only leaves the row unresolved
        log.warning("sizing counterfactual: no provider closes for %s", symbol, exc_info=True)
        return {}


def _expiry_close(closes: dict[date, float], expiry: date) -> float | None:
    """The close an option expiring *expiry* settles against, or None when the data cannot say.

    The bar dated on the expiry; failing that, the last bar before it, but only when the store
    also holds a later bar (proof the market was shut on the expiry date, a holiday): a missing
    bar must never be papered over with a stale pre-expiry one.
    """
    if expiry in closes:
        return closes[expiry]
    earlier = [d for d in closes if d < expiry]
    later = [d for d in closes if d > expiry]
    if earlier and later:
        return closes[max(earlier)]
    return None


def _closes(session: Session, symbol: str, start: date, expiry: date) -> dict[date, float]:
    """Daily closes from *start* through just past *expiry*: the store first, the provider for gaps."""
    end = expiry + timedelta(days=_HOLIDAY_SLACK_DAYS)
    rows = (
        session.query(PriceHistoryRow.obs_date, PriceHistoryRow.close)
        .filter(
            PriceHistoryRow.symbol == symbol,
            PriceHistoryRow.obs_date >= start,
            PriceHistoryRow.obs_date <= end,
        )
        .all()
    )
    closes = {d: float(c) for d, c in rows}
    if _expiry_close(closes, expiry) is None:
        for d, c in _provider_closes(symbol, start, end).items():
            closes.setdefault(d, c)
    return closes


# --------------------------------------------------------------------------- #
# Valuation
# --------------------------------------------------------------------------- #


def _traded_per_contract(
    session: Session, order: OrderRow, row: SizingActionRow, today: date
) -> float | None:
    """The realised P&L per contract of the traded lot, or None while it is still open.

    A lot bought back in full is valued at what the fills earned (credit - debit - commissions).
    A lot that ran to its expiry is valued at its actual entry premium less the intrinsic value at
    the expiry close, so an assignment's stock leg is marked at that close rather than ignored
    (``fill_economics`` alone would call it "premium kept").
    """
    fills = session.query(FillRow).filter(FillRow.candidate_id == order.candidate_id).all()
    econ = fill_economics(fills)
    if econ.entry_qty <= 0:
        return None
    bought = sum(f.filled_qty for f in fills if (f.action or "SELL").upper() == "BUY")
    if bought + _EPS >= econ.entry_qty:
        return (econ.credit - econ.debit - econ.commissions) / econ.entry_qty
    if row.expiry >= today:
        return None
    close = _expiry_close(_closes(session, row.underlying, row.action_day, row.expiry), row.expiry)
    if close is None:
        return None
    return (econ.entry_premium - _intrinsic(row, close)) * OPTION_MULTIPLIER - (
        econ.commissions / econ.entry_qty
    )


def _rules_mark(
    row: SizingActionRow, closes: dict[date, float], expiry_pnl: float, withheld: int
) -> float | None:
    """The exit-rule value of *withheld* contracts, or None without an entry IV to price with."""
    if not row.entry_iv or row.entry_iv <= 0:
        return None
    from src.execution.profit_take import resolve_profit_take_pct  # lazy: the trading path's rule

    cfg = get_config()
    right = OptionRight.PUT if _is_put(row) else OptionRight.CALL
    profit_pct = resolve_profit_take_pct(cfg.scheduler, right, (row.expiry - row.action_day).days)
    loss_multiple = (
        float(getattr(cfg.automation, "max_loss_multiple", 0.0) or 0.0)
        if is_leveraged_etf(row.underlying)
        else 0.0
    )
    iv = row.entry_iv / 100.0
    for day in sorted(d for d in closes if row.action_day <= d <= row.expiry):
        spot = closes[day]
        dte = (row.expiry - day).days
        value = (
            bs_price(spot, row.strike, dte, iv, right.value) if dte > 0 else _intrinsic(row, spot)
        )
        if value is None:
            continue
        if value <= (1 - profit_pct / 100.0) * row.premium:
            return (row.premium - value) * OPTION_MULTIPLIER * withheld
        if loss_multiple > 0 and value >= loss_multiple * row.premium:
            return (row.premium - value) * OPTION_MULTIPLIER * withheld
    return expiry_pnl


def _resolve_one(session: Session, row: SizingActionRow, today: date, now: datetime) -> bool:
    """Value one row if it can be valued now. True when it was (and ``resolved_at`` is set)."""
    order = session.get(OrderRow, row.order_id) if row.order_id is not None else None
    effect = _effect(row, order)
    if effect.state == "working":
        return False

    def done(expiry_value: float, rules_value: float | None, per_contract: float | None) -> bool:
        row.realized_pnl_per_contract = per_contract
        row.shadow_pnl_expiry = expiry_value
        row.shadow_pnl_rules = rules_value
        row.resolved_at = now
        return True

    withheld = _withheld(row, effect.sent)
    if effect.state == "moot" or withheld <= 0:
        return done(0.0, 0.0, None)

    if effect.state == "traded" and order is not None:
        per_contract = _traded_per_contract(session, order, row, today)
        if per_contract is None:
            return False  # the traded lot is still open
        value = per_contract * withheld
        return done(value, value, per_contract)

    if row.expiry >= today:
        return False  # not yet settled
    closes = _closes(session, row.underlying, row.action_day, row.expiry)
    close = _expiry_close(closes, row.expiry)
    if close is None:
        return False  # no settled price yet: try again at the next EOD
    expiry_pnl = (row.premium - _intrinsic(row, close)) * OPTION_MULTIPLIER * withheld
    return done(expiry_pnl, _rules_mark(row, closes, expiry_pnl, withheld), None)


def resolve_actions(now: datetime) -> int:
    """Value every unresolved ``sizing_actions`` row that can be valued now; the count resolved.

    Safe to run daily (the EOD job does): a resolved row is never touched again, a row whose
    order is still working, whose traded lot is still open, or whose expiry has not settled waits,
    and one row's failure leaves the others untouched. Never raises.
    """
    aware = now if now.tzinfo else now.replace(tzinfo=UTC)
    today = aware.astimezone(_ET).date()
    resolved = 0
    try:
        with session_scope() as s:
            rows = (
                s.query(SizingActionRow)
                .filter(SizingActionRow.resolved_at.is_(None))
                .order_by(SizingActionRow.id)
                .all()
            )
            for row in rows:
                try:
                    with s.begin_nested():
                        if _resolve_one(s, row, today, aware):
                            resolved += 1
                except Exception:  # noqa: BLE001 - one bad row must not stop the rest
                    log.warning("sizing counterfactual: row %s not valued", row.id, exc_info=True)
    except Exception:  # noqa: BLE001
        log.warning("sizing counterfactual: resolution failed", exc_info=True)
    if resolved:
        log.info("sizing counterfactual: valued %d action(s)", resolved)
    return resolved


# --------------------------------------------------------------------------- #
# The summary
# --------------------------------------------------------------------------- #


def _et_day_bounds(day: date) -> tuple[datetime, datetime]:
    """[start, end) of an ET day as naive UTC datetimes (the DB's convention)."""
    nxt = day + timedelta(days=1)
    start = datetime(day.year, day.month, day.day, tzinfo=_ET).astimezone(UTC)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=_ET).astimezone(UTC)
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


def _covered_call_sold(session: Session, underlying: str, day: date) -> bool:
    """True when a covered-call order on *underlying* was created on the ET day *day*."""
    start, end = _et_day_bounds(day)
    return (
        session.query(OrderRow.id)
        .filter(
            OrderRow.created_at >= start,
            OrderRow.created_at < end,
            func.json_extract(OrderRow.snapshot, "$.underlying") == underlying,
            func.json_extract(OrderRow.snapshot, "$.strategy") == "covered_call",
        )
        .first()
        is not None
    )


def _bucket() -> dict[str, float]:
    return {
        "count": 0,
        "contracts_withheld": 0,
        "resolved": 0,
        "exact": 0,
        "pnl_expiry": 0.0,
        "pnl_rules": 0.0,
        "rules_missing": 0,
    }


def summarize(since: date) -> dict[str, dict[str, float]]:
    """Per action kind, what the actions since *since* withheld and what that would have earned.

    Groups (the key is ``<kind>:<split>``): ``sent_smaller`` (``sent_contracts > 0``),
    ``never_sent`` (``sent_contracts == 0``) and, for ``cc_breakout_floor``, ``pushed_out`` (a
    covered call was still sold on the name that ET day: counted, not valued). ``claude_cut`` and
    ``claude_cut_unapplied`` rows are reported together under ``claude_overrides`` with
    ``applied`` / ``unapplied`` counts, the question being whether not following the system paid.

    Per group: ``count``; ``contracts_withheld``; ``resolved`` (rows valued); ``exact`` (valued at
    the traded contract's realised P&L, the rest are shadow values); ``pnl_expiry`` and
    ``pnl_rules`` (the sums of the two marks, positive = the action cost that much); and
    ``rules_missing`` (resolved rows with no exit-rule mark, for want of an entry IV). Rows that
    are not resolved yet count and are not valued.
    """
    out: dict[str, dict[str, float]] = {}
    with session_scope() as s:
        rows = (
            s.query(SizingActionRow)
            .filter(SizingActionRow.action_day >= since)
            .order_by(SizingActionRow.id)
            .all()
        )
        for row in rows:
            order = s.get(OrderRow, row.order_id) if row.order_id is not None else None
            effect = _effect(row, order)
            withheld = _withheld(row, effect.sent) if effect.state != "moot" else 0
            if row.kind in ("claude_cut", "claude_cut_unapplied"):
                key = "claude_overrides"
            elif row.kind == "cc_breakout_floor" and _covered_call_sold(
                s, row.underlying, row.action_day
            ):
                out.setdefault("cc_breakout_floor:pushed_out", {"count": 0})["count"] += 1
                continue
            else:
                split = "sent_smaller" if row.sent_contracts > 0 else "never_sent"
                key = f"{row.kind}:{split}"
            b = out.setdefault(key, _bucket())
            if key == "claude_overrides":
                for name in ("applied", "unapplied"):
                    b.setdefault(name, 0)
                b["applied" if row.kind == "claude_cut" else "unapplied"] += 1
            b["count"] += 1
            b["contracts_withheld"] += withheld
            if row.resolved_at is not None:
                b["resolved"] += 1
                if row.realized_pnl_per_contract is not None:
                    b["exact"] += 1
                b["pnl_expiry"] += row.shadow_pnl_expiry or 0.0
                if row.shadow_pnl_rules is None:
                    b["rules_missing"] += 1
                else:
                    b["pnl_rules"] += row.shadow_pnl_rules
    return out
