"""Live model IV for the envelope's gates (risk-envelope plan Task 12; spec §3.10.8, H7, Q4).

A mocked IB: subscriptions go through ``req_fresh_mkt_data``, at most ten lines are open at once,
each chunk is cancelled before the next opens, and a missing IV is None and never stored.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from src.common.schemas import OptionRight, PositionSnapshot
from src.ibkr import live_iv


def _put(i: int) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"NVDA P{100 + i}",
        sec_type="OPT",
        position=-1,
        avg_cost=1.0,
        right=OptionRight.PUT,
        strike=100.0 + i,
        expiry=date.today() + timedelta(days=30),
        underlying="NVDA",
        con_id=1000 + i,
    )


class _FakeIB:
    def __init__(self) -> None:
        self.open: set[int] = set()
        self.max_open = 0
        self.cancelled: list[int] = []

    def cancelMktData(self, contract) -> None:  # noqa: N802 - ib_async's name
        self.open.discard(contract.conId)
        self.cancelled.append(contract.conId)


@pytest.fixture()
def ib(monkeypatch):
    fake = _FakeIB()

    async def qualify(_ib, contracts, **_kw):
        for c in contracts:
            c.conId = 1000 + int(c.strike - 100)
        return contracts

    ivs: dict[int, float | None] = {}

    def fresh(_ib, contract, *args):
        fake.open.add(contract.conId)
        fake.max_open = max(fake.max_open, len(fake.open))
        iv = ivs.get(contract.conId, 0.40)
        return SimpleNamespace(modelGreeks=SimpleNamespace(impliedVol=iv) if iv else None)

    async def no_sleep(_s):
        return None

    monkeypatch.setattr(live_iv, "qualify_options_async", qualify)
    monkeypatch.setattr(live_iv, "req_fresh_mkt_data", fresh)
    monkeypatch.setattr(live_iv.asyncio, "sleep", no_sleep)
    fake.ivs = ivs  # type: ignore[attr-defined]
    return fake


def test_live_iv_reads_model_greeks(ib) -> None:
    ib.ivs[1001] = 0.62
    out = asyncio.run(live_iv.live_option_ivs(ib, [_put(0), _put(1)]))
    assert out == {1000: 0.40, 1001: 0.62}


def test_live_iv_missing_is_none_not_stored(ib, db) -> None:
    from sqlalchemy import func, select

    from src.storage.models import IVHistoryRow

    ib.ivs[1001] = None
    ib.ivs[1002] = float("nan")
    out = asyncio.run(live_iv.live_option_ivs(ib, [_put(0), _put(1), _put(2)]))
    assert out == {1000: 0.40, 1001: None, 1002: None}
    with db() as s:
        assert s.execute(select(func.count()).select_from(IVHistoryRow)).scalar_one() == 0


def test_live_iv_chunks_and_cancels_lines(ib) -> None:
    out = asyncio.run(live_iv.live_option_ivs(ib, [_put(i) for i in range(23)]))
    assert len(out) == 23 and all(v == 0.40 for v in out.values())
    assert ib.max_open <= 10
    assert sorted(ib.cancelled) == list(range(1000, 1023)) and not ib.open


def test_live_iv_for_one_contract(ib) -> None:
    from src.ibkr.contracts import build_option

    c = build_option("NVDA", date.today() + timedelta(days=30), 105.0, "P")
    assert asyncio.run(live_iv.live_iv_for(ib, c)) == 0.40
    assert ib.cancelled == [1005]


def test_a_failed_qualify_reads_every_option_unmeasured(ib, monkeypatch) -> None:
    async def boom(*_a, **_k):
        raise RuntimeError("gateway gone")

    monkeypatch.setattr(live_iv, "qualify_options_async", boom)
    assert asyncio.run(live_iv.live_option_ivs(ib, [_put(0)])) == {1000: None}


def test_live_iv_never_calls_req_mkt_data_directly() -> None:
    from pathlib import Path

    text = Path(live_iv.__file__).read_text()
    assert ".reqMktData(" not in text and "req_fresh_mkt_data(" in text
