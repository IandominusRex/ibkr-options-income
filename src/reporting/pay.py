"""The month's pay stub — read-only, from the same PnlLeg list every P&L surface uses.

Imports nothing from the enrichment layer or the API package (tests/test_web_fence.py greps
for the names). Spread positions arrive as plain `SpreadPayInput` values the API builds from
data/spreads.db, so this module never touches the spreads package either; the value book's
realised sales arrive the same way, as plain `ValuePayInput` values the API builds from
data/value.db (this module imports nothing from `src.value`).
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from src.common.income_target import target_value
from src.common.schemas import IncomeTarget, MonthPay, PnlLeg, VerdictOutcome

_ET = ZoneInfo("America/New_York")
OPTION_MULTIPLIER = 100

PayStrategy = Literal["all", "csp", "cc", "spread", "value"]


@dataclass(frozen=True)
class SpreadPayInput:
    opened_at: datetime
    closed_at: datetime | None
    entry_credit: float  # per share
    exit_debit: float | None  # per share, qty-weighted
    contracts_opened: int
    contracts_open: int
    entry_commission: float
    exit_commission: float


@dataclass(frozen=True)
class ValuePayInput:
    """One value-book sale's realised P&L (Part 6, ruling 25), by the date it closed."""

    closed_at: datetime  # naive UTC, as value.db stores it
    symbol: str
    realised_usd: float  # proceeds less the shares' average cost, before commissions
    commissions_usd: float | None  # None: value.db holds none (unknown, never 0.0)


def leg_kind(leg: PnlLeg) -> Literal["csp", "cc"] | None:
    s, r = str(leg.strategy), str(leg.right)
    if s == "cash_secured_put" or (s == "roll" and r == "P"):
        return "csp"
    if s == "covered_call" or (s == "roll" and r == "C"):
        return "cc"
    return None


def et_date(dt: datetime | None) -> date | None:
    if dt is None:
        return None
    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return aware.astimezone(_ET).date()


def close_day(leg: PnlLeg) -> date | None:
    """The New York day a leg closed. build_legs stamps an expired or assigned leg with naive
    midnight ON its expiry date - a calendar date, not a UTC instant like a fill time - so read
    as UTC it would slide into the previous ET day (an expiry on the 1st into last month)."""
    if leg.outcome in (VerdictOutcome.EXPIRED_WORTHLESS, VerdictOutcome.ASSIGNED):
        return leg.expiry
    return et_date(leg.closed_at)


def build_month_pay(
    legs: Iterable[PnlLeg],
    spreads: Iterable[SpreadPayInput],
    values: Iterable[ValuePayInput] = (),
    *,
    month: date,
    strategy: PayStrategy,
    month_start_value: float | None,
    target: IncomeTarget,
    today: date,
) -> MonthPay:
    first = month.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])

    def in_month(dt: datetime | None) -> bool:
        return on_day_in_month(et_date(dt))

    def on_day_in_month(d: date | None) -> bool:
        return d is not None and first <= d <= last

    premium = bought = commissions = 0.0
    complete = True
    n_opened = n_closed = 0

    if strategy not in ("spread", "value"):
        for leg in legs:
            kind = leg_kind(leg)
            if kind is None or (strategy != "all" and kind != strategy):
                continue
            opened, closed = in_month(leg.opened_at), on_day_in_month(close_day(leg))
            # Each side's commission in the month it was paid; a leg with no known split
            # charges all of it to the open month, so no commission is ever counted twice.
            open_commissions = (
                leg.open_commissions if leg.open_commissions is not None else leg.commissions
            )
            if opened:
                premium += leg.credit
                commissions += open_commissions
                n_opened += 1
            if closed:
                bought += leg.debit
                commissions += leg.commissions - open_commissions
                n_closed += 1
            if opened or closed:
                complete = complete and leg.commissions_complete

    if strategy in ("all", "spread"):
        for s in spreads:
            if in_month(s.opened_at):
                premium += s.entry_credit * OPTION_MULTIPLIER * s.contracts_opened
                commissions += s.entry_commission
                n_opened += 1
            if in_month(s.closed_at):
                closed_qty = s.contracts_opened - s.contracts_open
                bought += (s.exit_debit or 0.0) * OPTION_MULTIPLIER * closed_qty
                commissions += s.exit_commission
                n_closed += 1

    value_realised: float | None = None
    value_commissions: float | None = None
    value_complete = True
    n_value = 0
    if strategy in ("all", "value"):
        for v in values:
            if not in_month(v.closed_at):
                continue
            value_realised = (value_realised or 0.0) + v.realised_usd
            n_value += 1
            if v.commissions_usd is None:
                value_complete = False
            else:
                value_commissions = (value_commissions or 0.0) + v.commissions_usd

    net = premium - bought - commissions
    if strategy == "value":
        # Only value lines: its realised result less the commissions known for it. The options
        # figures above are zero because no options line was counted.
        net = (value_realised or 0.0) - (value_commissions or 0.0)
    target_dollars = target_value(target, month_start_value)
    return MonthPay(
        month=first,
        strategy=strategy,
        premium_collected=premium,
        bought_back=bought,
        commissions=commissions,
        commissions_complete=complete,
        net=net,
        n_opened=n_opened,
        n_closed=n_closed,
        month_start_value=month_start_value,
        target_pct=target.pct,
        target_mode=target.mode,
        target_amount=target.amount,
        target_base=target.base,
        target=target_dollars,
        # The target is the wheel's options-income wage (ruling 26): a value-only month has no
        # progress against it, and "all" counts options and spreads only.
        progress_pct=(net / target_dollars * 100)
        if target_dollars and strategy != "value"
        else None,
        days_left=(last - today).days if first <= today <= last else 0,
        value_realised=value_realised,
        value_commissions=value_commissions,
        value_commissions_complete=value_complete,
        value_n_closed=n_value,
    )
