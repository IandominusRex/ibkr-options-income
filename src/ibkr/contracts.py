"""Contract builders and bulk qualification helpers.

All IBKR option/stock objects are constructed here so the rest of the system
never needs to know the raw ib_async constructor signatures.
"""

from __future__ import annotations

from datetime import date
from typing import cast

from ib_async import IB, Option, Stock

from src.common.logging import get_logger

log = get_logger(__name__)


def build_stock(symbol: str) -> Stock:
    return Stock(symbol, "SMART", "USD")


def build_option(symbol: str, expiry: date, strike: float, right: str) -> Option:
    return Option(symbol, expiry.strftime("%Y%m%d"), strike, right, "SMART")


def qualify_stock(ib: IB, symbol: str) -> Stock:
    """Return a qualified Stock contract (conId filled in) or raise ValueError."""
    contract = build_stock(symbol)
    qualified = ib.qualifyContracts(contract)
    if not qualified or not qualified[0].conId:
        raise ValueError(f"Could not qualify stock contract for {symbol!r}")
    return cast(Stock, qualified[0])


def qualify_options(ib: IB, contracts: list[Option]) -> list[Option]:
    """Qualify a list of option contracts in one call; drop any that fail."""
    if not contracts:
        return []
    qualified = ib.qualifyContracts(*contracts)
    ok = cast(list[Option], [c for c in qualified if c.conId])
    log.debug("qualify_options: %d/%d contracts qualified", len(ok), len(contracts))
    return ok
