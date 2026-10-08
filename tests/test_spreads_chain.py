from __future__ import annotations

import itertools
import math
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption
from src.spreads.chain import (
    IbkrSpreadsBroker,
    band_strikes,
    next_expiries,
    parity_spot,
    pick_chain,
    to_chain_option,
)

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)
TODAY = date(2026, 10, 7)
CFG = get_config().spreads.model_copy(update={"max_market_data_lines": 30})


def _contract(strike: float, right: str, con_id: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        strike=strike, right=right, lastTradeDateOrContractMonth="20261007", conId=con_id
    )


# Review Focus 2 — IBKR's -1 bid sentinel and NaN asks become None, never a price.
def test_to_chain_option_cleans_sentinels_and_reads_put_oi() -> None:
    ticker = SimpleNamespace(
        bid=-1.0,
        ask=math.nan,
        modelGreeks=SimpleNamespace(impliedVol=0.21, delta=-0.08),
        callOpenInterest=10,
        putOpenInterest=750,
    )
    o = to_chain_option(_contract(680, "P"), ticker)
    assert o.bid is None and o.ask is None and o.mid is None
    assert (o.iv, o.delta, o.open_interest, o.con_id) == (0.21, -0.08, 750, 5)
    assert o.expiry == TODAY and o.right == "P"


# Review C1 — ib_async sets bid to NaN when the bid size is 0 (wrapper.priceSizeTick): with a
# live ask that is a no-bid market, worth 0 to a seller, not a missing quote.
def test_a_nan_bid_beside_a_live_ask_is_a_zero_bid() -> None:
    ticker = SimpleNamespace(
        bid=math.nan, ask=0.01, modelGreeks=None, callOpenInterest=None, putOpenInterest=None
    )
    o = to_chain_option(_contract(650, "P"), ticker)
    assert o.bid == 0.0 and o.ask == 0.01 and o.mid == pytest.approx(0.005)


def test_to_chain_option_without_greeks() -> None:
    ticker = SimpleNamespace(
        bid=0.5, ask=0.6, modelGreeks=None, callOpenInterest=math.nan, putOpenInterest=None
    )
    o = to_chain_option(_contract(700, "C"), ticker)
    assert (
        o.iv is None
        and o.delta is None
        and o.open_interest is None
        and o.mid == pytest.approx(0.55)
    )


def test_chain_helpers() -> None:
    assert band_strikes([660.0, 669.0, 670.0, 690.0, 710.0, 711.0], 690.0, 0.03) == [
        670.0,
        690.0,
        710.0,
    ]
    assert next_expiries(["20261006", "20261009", "20261007", "20261008"], TODAY, 2) == [
        "20261007",
        "20261008",
    ]
    chains = [
        SimpleNamespace(
            exchange="CBOE", tradingClass="SPX", expirations=["20261016"], strikes=[1.0]
        ),
        SimpleNamespace(
            exchange="SMART", tradingClass="SPXW", expirations=["20261007"], strikes=[1.0]
        ),
    ]
    assert pick_chain(chains, "SPXW").tradingClass == "SPXW"
    assert pick_chain(chains, "XSP") is None


def test_parity_spot_uses_the_nearest_fully_quoted_strike() -> None:
    opts = [
        ChainOption(strike=690, right="C", expiry=TODAY, bid=3.0, ask=3.2),
        ChainOption(strike=690, right="P", expiry=TODAY, bid=2.4, ask=2.6),
    ]
    assert parity_spot(opts, 689.0) == pytest.approx(690 + 3.1 - 2.5)
    assert parity_spot([], 689.0) is None


class FakeIB:
    """Records how many market-data lines are open at once."""

    def __init__(self, spot: float | None = 690.0) -> None:
        self.spot = spot
        self.session = {"open": math.nan, "high": math.nan, "low": math.nan, "close": math.nan}
        self.open = 0
        self.max_open = 0
        self._ids = itertools.count(1000)
        self.positions_list: list[SimpleNamespace] = []
        self.values: list[SimpleNamespace] = []
        self.priced: list[tuple[str, str]] = []  # (secType, symbol) of every spot/session request
        self.secdef: list[tuple] = []
        self.open_trades: list[SimpleNamespace] = []
        self.subscribed: list[int] = []
        self.qualify_fails = 0

    def reqMktData(self, contract, *args, **kwargs):
        self.subscribed.append(getattr(contract, "conId", 0))
        self.open += 1
        self.max_open = max(self.max_open, self.open)
        if contract.secType in ("IND", "STK"):
            self.priced.append((contract.secType, contract.symbol))
            return SimpleNamespace(last=self.spot if self.spot else math.nan, **self.session)
        return SimpleNamespace(
            bid=0.40,
            ask=0.45,
            modelGreeks=SimpleNamespace(
                impliedVol=0.18, delta=-0.1 if contract.right == "P" else 0.1
            ),
            callOpenInterest=500,
            putOpenInterest=700,
        )

    def cancelMktData(self, contract) -> None:
        self.open -= 1

    async def qualifyContractsAsync(self, *contracts):
        if self.qualify_fails:
            self.qualify_fails -= 1
            return []
        for c in contracts:
            if not c.conId:
                c.conId = next(self._ids)
        return list(contracts)

    async def reqSecDefOptParamsAsync(self, *args):
        self.secdef.append(args)
        return [
            SimpleNamespace(
                exchange="SMART",
                tradingClass=tc,
                expirations=["20261007", "20261008"],
                strikes=[float(k) for k in range(650, 731)],
            )
            for tc in ("XSP", "SPY")
        ]

    def positions(self):
        return self.positions_list

    def openTrades(self):
        return self.open_trades

    def accountValues(self, account: str = ""):
        return self.values


def _broker(ib: FakeIB) -> IbkrSpreadsBroker:
    return IbkrSpreadsBroker(ib, CFG, "DU1", quote_wait_seconds=0.05, now=lambda: NOW)


async def test_fetch_chain_bands_strikes_and_never_exceeds_the_line_budget() -> None:
    ib = FakeIB()
    snap = await _broker(ib).fetch_chain(
        symbol="XSP", trading_class="XSP", exchange="CBOE", expiries=1, band_pct=0.03
    )
    assert snap is not None and snap.spot == 690.0
    assert {o.expiry for o in snap.options} == {TODAY}
    assert (
        min(o.strike for o in snap.options) == 670.0
        and max(o.strike for o in snap.options) == 710.0
    )
    assert len(snap.options) == 41 * 2
    assert ib.max_open <= 30
    assert ib.open == 0  # every line cancelled


async def test_fetch_chain_without_any_spot_returns_none() -> None:
    snap = await _broker(FakeIB(spot=None)).fetch_chain(
        symbol="XSP", trading_class="XSP", exchange="CBOE", expiries=1, band_pct=0.03
    )
    assert snap is None


async def test_fetch_chain_falls_back_to_the_spot_hint() -> None:
    snap = await _broker(FakeIB(spot=None)).fetch_chain(
        symbol="XSP",
        trading_class="XSP",
        exchange="CBOE",
        expiries=1,
        band_pct=0.03,
        spot_hint=690.0,
    )
    assert snap is not None and snap.spot == 690.0


async def test_session_quote_reads_open_high_low_and_prior_close() -> None:
    ib = FakeIB()
    ib.session = {"open": 688.0, "high": 691.0, "low": 686.5, "close": 689.0}
    snap = await _broker(ib).session_quote()
    assert snap is not None and snap.as_of == NOW
    assert (snap.last, snap.open, snap.high, snap.low, snap.prior_close) == (
        690.0,
        688.0,
        691.0,
        686.5,
        689.0,
    )
    assert ib.priced == [("STK", "SPY")]  # SPY is read as a stock, not an index
    assert ib.open == 0  # the line is cancelled
    assert await _broker(FakeIB(spot=None)).session_quote() is None


async def test_session_quote_without_session_stats_still_has_a_price() -> None:
    snap = await _broker(FakeIB()).session_quote()
    assert snap is not None and snap.last == 690.0
    assert (snap.open, snap.high, snap.low, snap.prior_close) == (None, None, None, None)


async def test_a_spy_chain_is_requested_as_a_stock_chain() -> None:
    ib = FakeIB()
    snap = await _broker(ib).fetch_chain(
        symbol="SPY",
        trading_class="SPY",
        exchange="SMART",
        expiries=1,
        band_pct=0.03,
        sec_type="STK",
    )
    assert snap is not None and snap.symbol == "SPY" and snap.spot == 690.0
    assert ib.secdef[-1][2] == "STK" and ("STK", "SPY") in ib.priced


async def test_requote_keeps_known_con_ids() -> None:
    ib = FakeIB()
    legs = [ChainOption(strike=679, right="P", expiry=TODAY, con_id=42)]
    (q,) = await _broker(ib).requote(legs)
    assert q.con_id == 42 and q.bid == 0.40


def test_broker_legs_only_count_this_accounts_spreads_options() -> None:
    ib = FakeIB()
    ib.positions_list = [
        SimpleNamespace(
            account="DU1",
            contract=SimpleNamespace(symbol="XSP", secType="OPT", conId=1),
            position=-1.0,
        ),
        SimpleNamespace(
            account="DU1",
            contract=SimpleNamespace(symbol="XSP", secType="OPT", conId=2),
            position=1.0,
        ),
        SimpleNamespace(
            account="DU1",
            contract=SimpleNamespace(symbol="UPRO", secType="OPT", conId=3),
            position=-1.0,
        ),
        SimpleNamespace(
            account="DU2",
            contract=SimpleNamespace(symbol="XSP", secType="OPT", conId=4),
            position=-1.0,
        ),
    ]
    assert _broker(ib).broker_legs() == {1: -1.0, 2: 1.0}


async def test_excess_liquidity_prefers_usd() -> None:
    ib = FakeIB()
    ib.values = [
        SimpleNamespace(account="DU1", tag="ExcessLiquidity", value="80000", currency="BASE"),
        SimpleNamespace(account="DU1", tag="ExcessLiquidity", value="60000", currency="USD"),
    ]
    assert await _broker(ib).excess_liquidity() == 60000.0
    ib.values = []
    assert await _broker(ib).excess_liquidity() is None


# Review I3 — a contract repeated in one batch is subscribed once (a second reqMktData would
# overwrite the first's reqId and leak its line for the life of the connection).
async def test_a_repeated_leg_is_subscribed_once_and_fanned_back_out() -> None:
    ib = FakeIB()
    legs = [
        ChainOption(strike=679, right="P", expiry=TODAY, con_id=42),
        ChainOption(strike=674, right="P", expiry=TODAY, con_id=43),
        ChainOption(strike=679, right="P", expiry=TODAY, con_id=42),
    ]
    quotes = await _broker(ib).requote(legs)
    assert [q.con_id for q in quotes] == [42, 43, 42]
    assert sorted(ib.subscribed) == [42, 43] and ib.open == 0


# Review minor — a failed qualification is retried, not cached with conId=0 for the session.
async def test_a_failed_qualification_is_retried_next_time() -> None:
    ib = FakeIB()
    ib.qualify_fails = 1
    broker = _broker(ib)
    assert await broker.spot() is None
    assert await broker.spot() == 690.0


# Review minor — during regular hours yesterday's close is never the live spot.
async def test_the_prior_close_is_not_a_spot_during_regular_hours() -> None:
    ib = FakeIB(spot=None)
    ib.session = {"open": math.nan, "high": math.nan, "low": math.nan, "close": 688.0}
    assert await _broker(ib).spot() is None
    evening = IbkrSpreadsBroker(
        ib,
        CFG,
        "DU1",
        quote_wait_seconds=0.05,
        now=lambda: datetime(2026, 10, 7, 23, 0, tzinfo=UTC),
    )
    assert await evening.spot() == 688.0


# Review minor — a non-USD base account reports excess liquidity in its base currency.
async def test_excess_liquidity_converts_a_non_usd_base_currency() -> None:
    ib = FakeIB()
    ib.values = [
        SimpleNamespace(account="DU1", tag="ExcessLiquidity", value="133000", currency="SGD"),
        SimpleNamespace(account="DU1", tag="ExchangeRate", value="1.33", currency="USD"),
    ]
    assert await _broker(ib).excess_liquidity() == pytest.approx(100_000.0)
    ib.values = ib.values[:1]  # no rate to convert with: unknown, never a mislabelled number
    assert await _broker(ib).excess_liquidity() is None


def test_working_refs_lists_only_spreads_orders() -> None:
    ib = FakeIB()
    ib.open_trades = [
        SimpleNamespace(order=SimpleNamespace(orderRef="CS:s1:X")),
        SimpleNamespace(order=SimpleNamespace(orderRef="wheel-123")),
        SimpleNamespace(order=SimpleNamespace(orderRef="")),
    ]
    assert _broker(ib).working_refs() == {"CS:s1:X"}
