"""Contract builders and bulk qualification helpers.

All IBKR option/stock objects are constructed here so the rest of the system
never needs to know the raw ib_async constructor signatures.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Final, cast

from ib_async import IB, Option, Stock

import src.ibkr.contract_cache as contract_cache
from src.common.logging import get_logger
from src.ibkr.contract_cache import ContractCache, Key, confirmed_missing, contract_key

log = get_logger(__name__)


def build_stock(symbol: str) -> Stock:
    return Stock(symbol, "SMART", "USD")


def build_option(
    symbol: str, expiry: date, strike: float, right: str, trading_class: str = ""
) -> Option:
    """SMART-routed option. *trading_class* disambiguates when IBKR lists an adjusted chain
    (e.g. ``2AMD`` after a corporate action) beside the standard one; empty = let IBKR pick."""
    return Option(
        symbol, expiry.strftime("%Y%m%d"), strike, right, "SMART", tradingClass=trading_class
    )


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


class _UseDefault:
    pass


USE_DEFAULT: Final = _UseDefault()


async def qualify_options_async(
    ib: IB,
    contracts: list[Option],
    *,
    chunk_size: int = 40,
    throttle_seconds: float = 0.25,
    chunk_timeout_seconds: float = 20.0,
    cache: ContractCache | None | _UseDefault = USE_DEFAULT,
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

    **Contract cache (2026-10-10).** Contracts already looked up (by any process, any time
    before expiry) are filled from ``data/contracts.db`` without asking IBKR; strikes IBKR
    said don't exist are skipped for the rest of the ET day. Only misses are sent, in the same
    chunked, paced, timeout-bounded way. Any cache error falls back to asking IBKR. Returns the
    qualified input contracts in input order, each filled in place.
    """
    if not contracts:
        return []
    if chunk_size <= 0:
        chunk_size = len(contracts)
    store = contract_cache.get_contract_cache() if isinstance(cache, _UseDefault) else cache

    to_ask: list[Option] = list(contracts)
    hits: list[Option] = []
    known_missing = 0
    if store is not None:
        try:
            found = store.lookup(contracts)
            hits, to_ask, known_missing = found.hits, found.misses, found.known_missing
        except Exception:
            log.warning("contract cache lookup failed — asking IBKR for all", exc_info=True)

    asked_keys: dict[int, Key] = (
        {id(c): contract_key(c) for c in to_ask} if store is not None else {}
    )
    fresh: list[Option] = []
    missing: list[Option] = []
    for i in range(0, len(to_ask), chunk_size):
        chunk = to_ask[i : i + chunk_size]
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
        for item in items:
            if item is not None and getattr(item, "conId", None):
                fresh.append(cast(Option, item))
        if len(items) == len(chunk):  # aligned slots: a None slot is IBKR's "no such contract"
            missing.extend(c for c, item in zip(chunk, items, strict=True) if item is None)
        if throttle_seconds > 0 and i + chunk_size < len(to_ask):
            await asyncio.sleep(throttle_seconds)

    if store is not None and (fresh or missing):
        good = [contract_key(c) for c in hits] + [
            asked_keys[id(c)] for c in fresh if id(c) in asked_keys
        ]
        keep = set(confirmed_missing([asked_keys[id(c)] for c in missing], good))
        entries: list[tuple[Key, Any | None]] = [
            (asked_keys[id(c)], c) for c in fresh if id(c) in asked_keys
        ] + [(k, None) for k in keep]
        try:
            store.record(entries)
        except Exception:
            log.warning("contract cache write failed — answers not remembered", exc_info=True)
    if store is not None:
        log.info(
            "qualify: %d cached, %d known-missing skipped, %d asked IBKR (%d qualified, %d missing)",
            len(hits),
            known_missing,
            len(to_ask),
            len(fresh),
            len(missing),
        )

    good_ids = {id(c) for c in hits} | {id(c) for c in fresh}
    return [c for c in contracts if id(c) in good_ids]
