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
