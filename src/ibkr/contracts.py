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
from src.common.config import get_config
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


def _record(store: ContractCache, entries: list[tuple[Key, Any | None]]) -> None:
    if not entries:
        return
    try:
        store.record(entries)
    except Exception:
        log.warning("contract cache write failed — answers not remembered", exc_info=True)


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
    good: list[Key] = [contract_key(c) for c in hits] if store is not None else []
    # Contracts IBKR answered Error 200 ("No security definition") for. ib_async turns EVERY
    # failed request into a None slot (not connected, pacing, a farm blip), so a None alone
    # proves nothing; only a 200 for that very contract object does (review, 2026-10-10).
    # The wrapper emits errorEvent with the request's own contract before the call returns.
    no_definition: set[int] = set()

    def _on_error(_req_id: int, code: int, _msg: str, contract: Any) -> None:
        if code == 200 and contract is not None:
            no_definition.add(id(contract))

    fresh: list[Option] = []
    missing: list[Option] = []
    unconfirmed: list[Key] = []  # Error-200 answers still waiting for a qualified sibling
    # No errorEvent (a bare test double) = no 200s seen = nothing remembered as missing.
    error_event = getattr(ib, "errorEvent", None)
    if error_event is not None:
        error_event += _on_error
    try:
        for i in range(0, len(to_ask), chunk_size):
            chunk = to_ask[i : i + chunk_size]
            lock_path = store.lock_path if store is not None else None
            wait = get_config().market_data.qualify_lock_wait_seconds
            try:
                async with contract_cache.contract_details_slot(lock_path, wait):
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
            chunk_fresh = [
                cast(Option, item)
                for item in items
                if item is not None and getattr(item, "conId", None)
            ]
            fresh.extend(chunk_fresh)
            chunk_missing: list[Option] = []
            if len(items) == len(chunk):  # aligned slots: a None slot is a failed lookup
                chunk_missing = [c for c, item in zip(chunk, items, strict=True) if item is None]
                missing.extend(chunk_missing)
            if store is not None:
                # Recorded per chunk, not once at the end: the scan bounds a whole symbol with
                # symbol_timeout_seconds, and a cancelled symbol must keep what IBKR answered.
                answered = [(asked_keys[id(c)], c) for c in chunk_fresh if id(c) in asked_keys]
                good.extend(k for k, _ in answered)
                unconfirmed.extend(
                    asked_keys[id(c)]
                    for c in chunk_missing
                    if id(c) in no_definition and id(c) in asked_keys
                )
                keep = confirmed_missing(unconfirmed, good)
                unconfirmed = [k for k in unconfirmed if k not in set(keep)]
                _record(store, [*answered, *((k, None) for k in keep)])
            if throttle_seconds > 0 and i + chunk_size < len(to_ask):
                await asyncio.sleep(throttle_seconds)
    finally:
        if error_event is not None:
            error_event -= _on_error

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
