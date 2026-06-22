"""Contract builders and bulk qualification helpers.

All IBKR option/stock objects are constructed here so the rest of the system
never needs to know the raw ib_async constructor signatures.
"""

from __future__ import annotations

import asyncio
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


async def qualify_stock_async(ib: IB, symbol: str) -> Stock:
    """Async variant of qualify_stock — runs on the ib_async loop thread."""
    contract = build_stock(symbol)
    result = await ib.qualifyContractsAsync(contract)
    qualified = result if isinstance(result, list) else [result]
    first = qualified[0] if qualified else None
    if first is None or not getattr(first, "conId", None):
        raise ValueError(f"Could not qualify stock contract for {symbol!r}")
    return cast(Stock, first)


async def qualify_options_async(
    ib: IB,
    contracts: list[Option],
    *,
    chunk_size: int = 40,
    throttle_seconds: float = 0.25,
    chunk_timeout_seconds: float = 20.0,
) -> list[Option]:
    """Async variant of qualify_options — runs on the ib_async loop thread.

    Qualification is **chunked, paced, and per-chunk timeout-bounded** rather than one
    monolithic ``qualifyContractsAsync(*contracts)`` call. A single large burst (e.g. SMH's
    768-contract cartesian on 2026-06-22) floods IBKR with ``reqContractDetails`` for the many
    non-existent (expiration, strike) combos, tripping a pacing lockout that wedges the whole
    session; and if the burst hasn't returned by ``symbol_timeout_seconds`` the outer
    ``asyncio.wait_for`` cancels it mid-flight, which is what leaves the ib_async request
    pipeline unable to service any subsequent symbol. Chunking caps the in-flight request
    count, ``throttle_seconds`` paces between chunks, and a per-chunk ``asyncio.wait_for``
    means a stuck chunk yields whatever qualified and we move on — the symbol is never killed
    mid-qualification.
    """
    if not contracts:
        return []
    if chunk_size <= 0:
        chunk_size = len(contracts)

    ok: list[Option] = []
    for i in range(0, len(contracts), chunk_size):
        chunk = contracts[i : i + chunk_size]
        try:
            result = await asyncio.wait_for(
                ib.qualifyContractsAsync(*chunk), timeout=chunk_timeout_seconds
            )
        except TimeoutError:
            log.warning(
                "qualify_options_async: chunk %d-%d timed out after %.0fs — skipping chunk",
                i,
                i + len(chunk),
                chunk_timeout_seconds,
            )
            continue
        items = result if isinstance(result, list) else [result]
        ok.extend(
            cast(Option, c) for c in items if c is not None and getattr(c, "conId", None)
        )
        if throttle_seconds > 0 and i + chunk_size < len(contracts):
            await asyncio.sleep(throttle_seconds)

    log.debug("qualify_options_async: %d/%d contracts qualified", len(ok), len(contracts))
    return ok
