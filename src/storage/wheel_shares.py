"""The wheel's own share count W (value book spec §9.2, Part 5): every stock execution in the
broker-truth ledger that is not the value book's or the spreads book's — the wheel's fills, its
assignments and exercises, and manual trades — never "broker minus the value book".

Read-only (``session_scope`` reads, no write). Average cost by the average-cost method over the
executions in time order; a forward or reverse split the ledger records as a corporate action
("SPLIT 2 FOR 1", "4 FOR 1", ...) multiplies the count at its date (cost unchanged). A corporate
action it cannot read leaves W unadjusted, so the reconcile flags the name (fail closed). The
ledger starts at its first import, so stock held from before it
reads as unexplained on a ticker the value book shares; import the account's history (Flex or an
Activity CSV) before the first value buy (SETUP §19).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from src.storage.db import session_scope
from src.storage.models import BrokerCorporateActionRow, BrokerExecutionRow

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WheelShares:
    shares: float
    avg_cost: float | None  # None when no buy is recorded


def wheel_shares(symbols: list[str]) -> dict[str, WheelShares]:
    """W per symbol (zero shares when the ledger holds none for it). The value book's, the
    spreads book's and the LES book's executions (``book`` value / spreads / les, risk-envelope
    Task 32a) are not the wheel's."""
    wanted = sorted({s.upper() for s in symbols})
    out = {s: WheelShares(0.0, None) for s in wanted}
    if not wanted:
        return out
    return _count(
        wanted,
        BrokerExecutionRow.book.not_in(("value", "spreads", "les")),
        out,
    )


def les_shares(symbols: list[str] | None = None) -> dict[str, float]:
    """The LES share book's count L per ETF (risk-envelope Task 32a): every stock execution the
    ledger tagged ``book="les"`` (an ``les:<id>`` orderRef), split-adjusted like W. Every ETF
    with an LES execution when *symbols* is None."""
    with session_scope() as s:
        names = (
            sorted({x.upper() for x in symbols})
            if symbols is not None
            else sorted(
                {
                    u
                    for (u,) in s.execute(
                        select(BrokerExecutionRow.underlying).where(
                            BrokerExecutionRow.book == "les", BrokerExecutionRow.sec_type == "STK"
                        )
                    ).all()
                    if u
                }
            )
        )
    if not names:
        return {}
    counted = _count(
        names,
        BrokerExecutionRow.book == "les",
        {n: WheelShares(0.0, None) for n in names},
    )
    return {k: max(0.0, v.shares) for k, v in counted.items()}


def _count(
    wanted: list[str], book_clause: Any, out: dict[str, WheelShares]
) -> dict[str, WheelShares]:
    """The average-cost share count over the stock executions *book_clause* selects."""
    with session_scope() as s:
        rows = s.execute(
            select(
                BrokerExecutionRow.underlying,
                BrokerExecutionRow.trade_time,
                BrokerExecutionRow.quantity,
                BrokerExecutionRow.price,
            ).where(
                BrokerExecutionRow.sec_type == "STK",
                BrokerExecutionRow.superseded_by.is_(None),
                book_clause,
                BrokerExecutionRow.underlying.in_(wanted),
            )
        ).all()
        actions = s.execute(
            select(
                BrokerCorporateActionRow.underlying,
                BrokerCorporateActionRow.event_date,
                BrokerCorporateActionRow.description,
            ).where(BrokerCorporateActionRow.underlying.in_(wanted))
        ).all()
    events: list[tuple[str, datetime, int, float, float]] = [
        (sym, when, 1, qty, price) for sym, when, qty, price in rows
    ]
    for sym, day, description in actions:
        ratio = split_ratio(description or "")
        if sym and ratio:
            events.append((sym, datetime.combine(day, datetime.min.time()), 0, ratio, 0.0))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    state: dict[str, tuple[float, float]] = {}  # symbol -> (shares, cost)
    for symbol, _, kind, qty, price in events:
        shares, cost = state.get(symbol, (0.0, 0.0))
        if kind == 0:
            shares *= qty  # a split: the same cost over more (or fewer) shares
        elif qty > 0:
            shares, cost = shares + qty, cost + qty * price
        elif shares > 0:
            sold = min(-qty, shares)
            cost -= cost / shares * sold
            shares -= -qty
        else:
            shares += qty
        state[symbol] = (shares, max(0.0, cost))
    for symbol, (shares, cost) in state.items():
        out[symbol] = WheelShares(shares, cost / shares if shares > 0 else None)
    return out


_SPLIT = re.compile(r"(\d+(?:\.\d+)?)\s*FOR\s*(\d+(?:\.\d+)?)", re.I)


def split_ratio(description: str) -> float | None:
    """The share multiple of a split corporate action ("... SPLIT 2 FOR 1" -> 2.0, "1 FOR 10"
    -> 0.1), or None when the text names no split."""
    if "SPLIT" not in description.upper():
        return None
    m = _SPLIT.search(description)
    if m is None or float(m.group(2)) == 0:
        return None
    return float(m.group(1)) / float(m.group(2))
