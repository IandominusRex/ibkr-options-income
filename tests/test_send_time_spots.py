"""Review fix 3: the envelope's send-time measurements price the book's options against the
live underlying price (from the live-IV subscriptions), never a stale stored close, and a
send-time measurement never starts the glide."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot
from src.ibkr import live_iv

LIVE_SPOT = 123.0


def _put() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="NVDA P",
        sec_type="OPT",
        position=-1,
        avg_cost=1.0,
        right=OptionRight.PUT,
        strike=100.0,
        expiry=date.today() + timedelta(days=30),
        underlying="NVDA",
        con_id=1000,
    )


def _acct() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=100_000.0,
        total_cash=50_000.0,
        buying_power=50_000.0,
        maintenance_margin=0.0,
        excess_liquidity=50_000.0,
    )


@pytest.fixture()
def live(db, monkeypatch):
    """A live read that carries a spot, and a recorder of what build_inputs was handed."""
    import src.analytics.shock_inputs as si

    seen: dict[str, Any] = {}
    real = si.build_inputs

    async def reads(_ib: Any, _positions: Any) -> live_iv.LiveReads:
        return live_iv.LiveReads({1000: 0.40}, {"NVDA": LIVE_SPOT})

    def spy(*a: Any, **k: Any) -> Any:
        seen["spots"] = k.get("spots")
        out = real(*a, **k)
        seen["lines"] = out.lines
        return out

    monkeypatch.setattr(live_iv, "live_option_reads", reads)
    monkeypatch.setattr(si, "build_inputs", spy)
    return seen


def _option_spot(seen: dict[str, Any]) -> float:
    (line,) = [ln for ln in seen["lines"] if ln.kind == "short_put"]
    return float(line.spot)


def test_live_reads_carry_the_underlying_price(monkeypatch) -> None:
    async def qualify(_ib, contracts, **_kw):
        for c in contracts:
            c.conId = 1000
        return contracts

    def fresh(_ib, _c, *args):
        return SimpleNamespace(modelGreeks=SimpleNamespace(impliedVol=0.4, undPrice=LIVE_SPOT))

    monkeypatch.setattr(live_iv, "qualify_options_async", qualify)
    monkeypatch.setattr(live_iv, "req_fresh_mkt_data", fresh)
    ib = SimpleNamespace(cancelMktData=lambda c: None)
    out = asyncio.run(live_iv.live_option_reads(ib, [_put()]))
    assert out.ivs == {1000: 0.40} and out.spots == {"NVDA": LIVE_SPOT}


def test_an_absent_underlying_price_leaves_the_spot_out(monkeypatch) -> None:
    async def qualify(_ib, contracts, **_kw):
        for c in contracts:
            c.conId = 1000
        return contracts

    def fresh(_ib, _c, *args):
        return SimpleNamespace(modelGreeks=SimpleNamespace(impliedVol=0.4, undPrice=float("nan")))

    monkeypatch.setattr(live_iv, "qualify_options_async", qualify)
    monkeypatch.setattr(live_iv, "req_fresh_mkt_data", fresh)
    ib = SimpleNamespace(cancelMktData=lambda c: None)
    out = asyncio.run(live_iv.live_option_reads(ib, [_put()]))
    assert out.ivs == {1000: 0.40} and out.spots == {}


def test_the_send_time_envelope_uses_the_live_spot_and_never_starts_the_glide(
    live, monkeypatch
) -> None:
    import src.engine.envelope as env
    from src.execution.approval import _send_envelope
    from src.storage import envelope_switches as sw

    monkeypatch.setattr(sw, "enforce_mode", lambda: "on")
    started: dict[str, Any] = {}
    real_room = env.room

    def room(inputs: Any, **kw: Any) -> Any:
        started.update(kw)
        return real_room(inputs, **kw)

    monkeypatch.setattr(env, "room", room)
    got = asyncio.run(_send_envelope(object(), _acct(), [_put()]))  # type: ignore[arg-type]
    assert got is not None
    assert live["spots"] == {"NVDA": LIVE_SPOT} and _option_spot(live) == LIVE_SPOT
    assert started.get("may_start") is False


def test_the_stock_buy_envelope_uses_the_live_spot(live) -> None:
    from src.execution.stock_orders import buy_envelope

    got = asyncio.run(buy_envelope(object(), [_put()], _acct(), "NVDA"))
    assert got is not None
    assert live["spots"] == {"NVDA": LIVE_SPOT} and _option_spot(live) == LIVE_SPOT


def test_the_hedge_book_uses_the_live_spot(live, monkeypatch) -> None:
    from src.hedge.context import book_inputs

    monkeypatch.setattr("src.ibkr.portfolio.get_positions", lambda _ib, **k: [_put()])
    got = asyncio.run(book_inputs(object(), 100_000.0))
    assert got is not None
    assert live["spots"] == {"NVDA": LIVE_SPOT} and _option_spot(live) == LIVE_SPOT


def test_the_value_envelope_uses_the_live_spot(live, monkeypatch) -> None:
    from src.storage import envelope_switches as sw
    from src.value.stage3 import value_envelope

    monkeypatch.setattr(sw, "enforce_mode", lambda: "on")
    asyncio.run(
        value_envelope(
            object(), [_put()], _acct(), ["STDY"], now=datetime(2026, 11, 18, 15, tzinfo=UTC)
        )
    )
    assert live["spots"] == {"NVDA": LIVE_SPOT} and _option_spot(live) == LIVE_SPOT
