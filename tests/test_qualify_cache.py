"""qualify_options_async consults the contract cache before asking IBKR."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from ib_async import Option

from src.ibkr.contract_cache import ContractCache
from src.ibkr.contracts import qualify_options_async


def _cache(tmp_path) -> ContractCache:
    return ContractCache(f"sqlite:///{tmp_path / 'c.db'}", today=lambda: date(2026, 10, 12))


def _opt(strike: float, expiry: str = "20261023") -> Option:
    return Option("AMD", expiry, strike, "P", "SMART", tradingClass="AMD")


def _ib(missing: set[float] = frozenset(), *, raise_timeout: bool = False) -> MagicMock:
    """Fake IBKR: qualifies every strike except *missing* (returns None in its slot, as
    ib_async does for an unknown contract). conId = strike * 10."""

    async def _qualify(*cs):
        if raise_timeout:
            raise TimeoutError
        out = []
        for c in cs:
            if c.strike in missing:
                out.append(None)
            else:
                c.conId = int(c.strike * 10)
                out.append(c)
        return out

    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(side_effect=_qualify)
    return ib


async def test_second_call_hits_the_cache_and_keeps_input_order(tmp_path) -> None:
    cache = _cache(tmp_path)
    await qualify_options_async(_ib(), [_opt(600.0), _opt(605.0)], cache=cache, throttle_seconds=0)

    ib = _ib()
    again = [_opt(605.0), _opt(600.0)]
    result = await qualify_options_async(ib, again, cache=cache, throttle_seconds=0)

    ib.qualifyContractsAsync.assert_not_called()
    assert result == again and [c.conId for c in again] == [6050, 6000]


async def test_known_missing_strike_is_not_asked_again_today(tmp_path) -> None:
    cache = _cache(tmp_path)
    await qualify_options_async(
        _ib(missing={602.5}), [_opt(600.0), _opt(602.5)], cache=cache, throttle_seconds=0
    )

    ib = _ib()
    result = await qualify_options_async(
        ib, [_opt(600.0), _opt(602.5)], cache=cache, throttle_seconds=0
    )

    ib.qualifyContractsAsync.assert_not_called()
    assert [c.strike for c in result] == [600.0]


async def test_whole_expiry_missing_is_not_cached(tmp_path) -> None:
    """Every contract of an expiry coming back None is a transient failure, not a fact."""
    cache = _cache(tmp_path)
    await qualify_options_async(
        _ib(missing={600.0, 605.0}), [_opt(600.0), _opt(605.0)], cache=cache, throttle_seconds=0
    )

    ib = _ib()
    await qualify_options_async(ib, [_opt(600.0), _opt(605.0)], cache=cache, throttle_seconds=0)
    assert ib.qualifyContractsAsync.await_count == 1  # asked again, not remembered as missing


async def test_timed_out_chunk_records_nothing(tmp_path) -> None:
    cache = _cache(tmp_path)
    await qualify_options_async(
        _ib(raise_timeout=True), [_opt(600.0)], cache=cache, throttle_seconds=0
    )

    ib = _ib()
    result = await qualify_options_async(ib, [_opt(600.0)], cache=cache, throttle_seconds=0)
    assert ib.qualifyContractsAsync.await_count == 1 and len(result) == 1


async def test_cache_failure_falls_back_to_ibkr(tmp_path) -> None:
    broken = MagicMock(spec=ContractCache)
    broken.lookup.side_effect = RuntimeError("database is locked")
    broken.record.side_effect = RuntimeError("database is locked")
    broken.lock_path = tmp_path / "c.lock"

    result = await qualify_options_async(_ib(), [_opt(600.0)], cache=broken, throttle_seconds=0)
    assert [c.conId for c in result] == [6000]


async def test_short_result_list_records_no_missing(tmp_path) -> None:
    """A result list that doesn't line up with the chunk (a mock or a future ib_async that
    returns only the qualified) must never mislabel a real contract as missing."""
    cache = _cache(tmp_path)

    async def _only_qualified(*cs):
        cs[0].conId = 6000
        return [cs[0]]

    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(side_effect=_only_qualified)
    await qualify_options_async(ib, [_opt(600.0), _opt(605.0)], cache=cache, throttle_seconds=0)

    assert cache.lookup([_opt(605.0)]).misses != []


async def test_chain_fetch_reports_trading_classes_to_the_cache(monkeypatch, tmp_path) -> None:
    """get_option_chain_quotes_async hands every trading class from reqSecDefOptParams to the
    cache, so a corporate action (a new class) drops the symbol's stale entries that cycle."""
    from types import SimpleNamespace

    import src.ibkr.contract_cache as cc
    import src.ibkr.market_data as md

    seen: list[tuple[str, list[str]]] = []
    fake = SimpleNamespace(
        note_trading_classes=lambda sym, classes: seen.append((sym, sorted(classes))) or False
    )
    monkeypatch.setattr(cc, "get_contract_cache", lambda: fake)

    stock = SimpleNamespace(symbol="AMD", secType="STK", conId=1)
    monkeypatch.setattr(md, "qualify_stock_async", AsyncMock(return_value=stock))
    monkeypatch.setattr(md, "_resolve_spot_async", AsyncMock(return_value=600.0))
    monkeypatch.setattr(md, "_select_chain", lambda chains, sym: None)  # stop right after
    ib = MagicMock()
    ib.reqSecDefOptParamsAsync = AsyncMock(
        return_value=[SimpleNamespace(tradingClass="AMD"), SimpleNamespace(tradingClass="2AMD")]
    )

    assert await md.get_option_chain_quotes_async(ib, "AMD") == []
    assert seen == [("AMD", ["2AMD", "AMD"])]


async def test_default_cache_comes_from_the_process_factory(monkeypatch, tmp_path) -> None:
    import src.ibkr.contract_cache as cc

    cache = _cache(tmp_path)
    monkeypatch.setattr(cc, "get_contract_cache", lambda: cache)
    await qualify_options_async(_ib(), [_opt(600.0)], throttle_seconds=0)

    assert cache.lookup([_opt(600.0)]).hits != []
