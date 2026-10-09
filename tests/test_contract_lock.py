"""contract_details_slot — one process at a time talks to IBKR's contract-details service."""

from __future__ import annotations

import asyncio
import time
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from ib_async import Option

from src.ibkr.contract_cache import ContractCache, contract_details_slot
from src.ibkr.contracts import qualify_options_async


async def test_second_holder_waits_for_the_first(tmp_path) -> None:
    lock = tmp_path / "c.lock"
    order: list[str] = []

    async def first() -> None:
        async with contract_details_slot(lock, 5.0):
            order.append("first in")
            await asyncio.sleep(0.2)
            order.append("first out")

    async def second() -> None:
        await asyncio.sleep(0.05)
        async with contract_details_slot(lock, 5.0) as got:
            assert got is True
            order.append("second in")

    await asyncio.gather(first(), second())
    assert order == ["first in", "first out", "second in"]


async def test_waiting_too_long_proceeds_unlocked(tmp_path) -> None:
    lock = tmp_path / "c.lock"
    async with contract_details_slot(lock, 5.0):
        started = time.monotonic()
        async with contract_details_slot(lock, 0.2) as got:
            assert got is False
        assert time.monotonic() - started < 1.0


async def test_no_lock_path_means_no_lock() -> None:
    async with contract_details_slot(None, 0.0) as got:
        assert got is False


async def test_chunk_timeout_starts_after_the_lock_is_acquired(tmp_path) -> None:
    """Another process holding the lock for longer than chunk_timeout_seconds must not make
    this process's chunk time out — the wait isn't the chunk's fault."""
    cache = ContractCache(f"sqlite:///{tmp_path / 'c.db'}", today=lambda: date(2026, 10, 12))

    async def _qualify(*cs):
        for c in cs:
            c.conId = 1
        return list(cs)

    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(side_effect=_qualify)

    async def holder() -> None:
        async with contract_details_slot(cache.lock_path, 5.0):
            await asyncio.sleep(0.4)

    async def asker() -> list:
        await asyncio.sleep(0.05)
        return await qualify_options_async(
            ib,
            [Option("AMD", "20261023", 600.0, "P", "SMART", tradingClass="AMD")],
            cache=cache,
            throttle_seconds=0,
            chunk_timeout_seconds=0.2,
        )

    _, result = await asyncio.gather(holder(), asker())
    assert len(result) == 1
