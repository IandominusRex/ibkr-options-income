"""`src/ibkr/portfolio.py`'s greeks enrichment must qualify contracts before subscribing.

``build_option`` returns an UNQUALIFIED ``Option`` (``conId=0``). ib_async's own
``Contract.__hash__`` refuses to hash a contract with no ``conId`` — raising ``ValueError`` —
and ``IB.reqMktData`` hashes the contract internally (``Wrapper.startTicker``) before any
network call. This is reproducible with no live IBKR session: a ``MagicMock`` standing in for
``ib`` never raises (its ``reqMktData`` is just an attribute access), which is exactly why this
bug went unnoticed by every test that mocks ``ib`` generically — so this file exercises the
REAL ib_async ``Wrapper``/``Contract`` machinery instead of a generic mock, the only way to
actually catch "was this contract qualified before being subscribed."
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock

from src.common.schemas import OptionRight, PositionSnapshot
from src.ibkr.portfolio import enrich_positions_with_greeks_async


class _RealishIB:
    """Stands in for ``ib_async.IB`` using a genuine ``Wrapper`` for ticker bookkeeping.

    ``reqMktData``/``cancelMktData`` delegate to the real ``Wrapper.startTicker``/``endTicker``
    — the exact code path that raises ``ValueError`` for an unqualified contract — without
    needing a live TWS/Gateway connection (no network round-trip is exercised, only the local
    Python bookkeeping that raises before one would ever be attempted).
    """

    def __init__(self) -> None:
        from ib_async.wrapper import Wrapper

        self.wrapper = Wrapper(None)
        self._next_req_id = 1
        self.qualify_calls: list[Any] = []

    def reqMktData(self, contract: Any, *args: Any, **kwargs: Any) -> Any:
        req_id = self._next_req_id
        self._next_req_id += 1
        return self.wrapper.startTicker(req_id, contract, "mktData")

    def cancelMktData(self, contract: Any) -> None:
        ticker = self.wrapper.tickers.get(hash(contract))
        if ticker is not None:
            self.wrapper.endTicker(ticker, "mktData")

    async def qualifyContractsAsync(self, *contracts: Any) -> list[Any]:
        self.qualify_calls.extend(contracts)
        for i, c in enumerate(contracts):
            c.conId = 999_000 + i
        return list(contracts)


def _short_call_position() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="AAPL  260918C00200000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=2.0,
        right=OptionRight.CALL,
        strike=200.0,
        expiry=date(2026, 9, 18),
        underlying="AAPL",
    )


async def test_enrich_positions_with_greeks_qualifies_before_subscribing(monkeypatch) -> None:
    """Before the fix, ``build_option``'s unqualified contract went straight into
    ``reqMktData`` and every option position's enrichment silently no-op'd (the
    ``except Exception`` around the call swallowed ib_async's ``ValueError``)."""
    monkeypatch.setattr("src.ibkr.portfolio.asyncio.sleep", AsyncMock())

    ib = _RealishIB()
    position = _short_call_position()

    result = await enrich_positions_with_greeks_async(ib, [position])

    assert len(ib.qualify_calls) == 1
    assert result[0].symbol == position.symbol


# --------------------------------------------------------------------------------------------
# Account snapshot currency (2026-10-09): the paper account is SGD-base, and accountSummary
# reports NetLiquidation/AvailableFunds/ExcessLiquidity in SGD. The wheel read them as USD, so
# every %-of-net-liq limit was measured against S$1.02M as if it were US$1.02M (~28% loose).
# --------------------------------------------------------------------------------------------


class _AcctIB:
    def __init__(self, summary: list[tuple[str, str, str]], stream: list[tuple[str, str, str]]):
        from ib_async import AccountValue

        self._summary = [AccountValue("DU1", t, v, c, "") for t, v, c in summary]
        self._stream = [AccountValue("DU1", t, v, c, "") for t, v, c in stream]

    async def accountSummaryAsync(self, account: str = "") -> list[Any]:
        return self._summary

    def accountSummary(self, account: str = "") -> list[Any]:
        return self._summary

    def accountValues(self, account: str = "") -> list[Any]:
        return self._stream


_SGD_SUMMARY = [
    ("NetLiquidation", "1020570.54", "SGD"),
    ("TotalCashValue", "336300.55", "SGD"),
    ("AvailableFunds", "742655.86", "SGD"),
    ("MaintMarginReq", "232286.15", "SGD"),
    ("ExcessLiquidity", "788284.39", "SGD"),
]
_LIVE_RATE = [("$LEDGER-ExchangeRate", "1.00", "BASE"), ("$LEDGER-ExchangeRate", "1.281252", "USD")]


async def test_account_snapshot_converts_a_non_usd_base_account_to_usd() -> None:
    import pytest

    from src.ibkr.portfolio import get_account_snapshot_async

    snap = await get_account_snapshot_async(_AcctIB(_SGD_SUMMARY, _LIVE_RATE), "DU1")
    assert snap.net_liquidation == pytest.approx(1020570.54 / 1.281252)
    assert snap.total_cash == pytest.approx(336300.55 / 1.281252)
    assert snap.buying_power == pytest.approx(742655.86 / 1.281252)
    assert snap.maintenance_margin == pytest.approx(232286.15 / 1.281252)
    assert snap.excess_liquidity == pytest.approx(788284.39 / 1.281252)


def test_sync_account_snapshot_converts_too() -> None:
    import pytest

    from src.ibkr.portfolio import get_account_snapshot

    snap = get_account_snapshot(_AcctIB(_SGD_SUMMARY, [("ExchangeRate", "1.281252", "USD")]), "DU1")
    assert snap.net_liquidation == pytest.approx(1020570.54 / 1.281252)


async def test_usd_base_account_is_left_unchanged() -> None:
    from src.ibkr.portfolio import get_account_snapshot_async

    usd = [(t, v, "USD") for t, v, _ in _SGD_SUMMARY]
    snap = await get_account_snapshot_async(_AcctIB(usd, []), "DU1")
    assert snap.net_liquidation == 1020570.54


async def test_missing_rate_reuses_the_last_known_rate(monkeypatch) -> None:
    """A brief gap in the account stream must not hand the risk engine base-currency figures
    as USD — the last rate this process saw stands in until the stream refills."""
    import pytest

    import src.ibkr.portfolio as P

    monkeypatch.setattr(P, "_LAST_USD_RATE", {})
    await P.get_account_snapshot_async(_AcctIB(_SGD_SUMMARY, _LIVE_RATE), "DU1")
    snap = await P.get_account_snapshot_async(_AcctIB(_SGD_SUMMARY, []), "DU1")
    assert snap.net_liquidation == pytest.approx(1020570.54 / 1.281252)


async def test_no_rate_ever_seen_raises_rather_than_mislabelling(monkeypatch) -> None:
    """With no rate at all, a base-currency figure must never be passed off as USD: raise, and
    every caller's existing account-snapshot failure handling takes over."""
    import pytest

    import src.ibkr.portfolio as P

    monkeypatch.setattr(P, "_LAST_USD_RATE", {})
    with pytest.raises(P.AccountCurrencyError):
        await P.get_account_snapshot_async(_AcctIB(_SGD_SUMMARY, []), "DU1")
