"""Phase 1 unit tests — market data layer. No TWS/Gateway required.

All ib_async calls are mocked. Tests verify:
  - Contract builders produce correct objects
  - Expiration/strike filtering respects DTE windows and band
  - _batch_quotes chunks correctly and cancels every line
  - Greeks/OI field mapping is correct
  - qualify_stock raises on failure; qualify_options drops unqualified contracts
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import OptionQuote, OptionRight
from src.ibkr.contracts import (
    build_option,
    build_stock,
    qualify_options,
    qualify_options_async,
    qualify_stock,
)
from src.ibkr.market_data import (
    _await_ready,
    _batch_quotes,
    _bs_fill_spot_async,
    _build_chain_contracts,
    _cap_strikes,
    _close_line,
    _enrich_greeks_from_ibkr_iv,
    _enrich_greeks_yf,
    _filter_expirations,
    _filter_strikes,
    _get_spot,
    _get_spot_async,
    _pick_greeks,
    _quote_ready,
    _resolve_spot_async,
    _safe,
    _safe_int,
    _select_chain,
    _spot_ready,
    _ticker_to_quote,
    drain_market_data_lines,
    probe_market_data_health,
)

# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _make_greeks(
    iv: float = 0.35,
    delta: float = -0.25,
    gamma: float = 0.02,
    theta: float = -0.05,
    vega: float = 0.10,
) -> SimpleNamespace:
    return SimpleNamespace(impliedVol=iv, delta=delta, gamma=gamma, theta=theta, vega=vega)


def _make_ticker(
    bid: float = 1.00,
    ask: float = 1.20,
    last: float = 1.10,
    volume: float = 100.0,
    greeks=None,
    call_oi: float = 500.0,
    put_oi: float = 600.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        bid=bid,
        ask=ask,
        last=last,
        volume=volume,
        modelGreeks=greeks if greeks is not None else _make_greeks(),
        callOpenInterest=call_oi,
        putOpenInterest=put_oi,
    )


def _make_option_contract(
    symbol: str = "QQQ",
    expiry: str = "20261219",
    strike: float = 400.0,
    right: str = "C",
    con_id: int = 12345,
) -> MagicMock:
    c = MagicMock()
    c.symbol = symbol
    c.lastTradeDateOrContractMonth = expiry
    c.strike = strike
    c.right = right
    c.conId = con_id
    return c


# ---------------------------------------------------------------------------
# _safe / _safe_int
# ---------------------------------------------------------------------------


def test_safe_none_returns_none():
    assert _safe(None) is None


def test_safe_nan_returns_none():
    assert _safe(float("nan")) is None


def test_safe_valid_float():
    assert _safe(1.5) == 1.5


def test_safe_int_valid():
    assert _safe_int(500.0) == 500


def test_safe_int_nan_returns_none():
    assert _safe_int(float("nan")) is None


def test_safe_int_none_returns_none():
    assert _safe_int(None) is None


# ---------------------------------------------------------------------------
# build_stock / build_option
# ---------------------------------------------------------------------------


def test_build_stock_fields():
    s = build_stock("AAPL")
    assert s.symbol == "AAPL"
    assert s.exchange == "SMART"
    assert s.currency == "USD"


def test_build_option_fields():
    exp = date(2026, 6, 19)
    opt = build_option("NVDA", exp, 120.0, "P")
    assert opt.symbol == "NVDA"
    assert opt.lastTradeDateOrContractMonth == "20260619"
    assert opt.strike == 120.0
    assert opt.right == "P"
    assert opt.exchange == "SMART"


# ---------------------------------------------------------------------------
# _filter_expirations
# ---------------------------------------------------------------------------


def test_filter_expirations_keeps_window():
    today = date.today()
    d_early = (today + timedelta(days=10)).strftime("%Y%m%d")
    d_in = (today + timedelta(days=30)).strftime("%Y%m%d")
    d_late = (today + timedelta(days=60)).strftime("%Y%m%d")
    result = _filter_expirations({d_early, d_in, d_late}, dte_min=21, dte_max=45)
    assert d_in in result
    assert d_early not in result
    assert d_late not in result


def test_filter_expirations_empty_when_nothing_in_window():
    today = date.today()
    d_close = (today + timedelta(days=5)).strftime("%Y%m%d")
    result = _filter_expirations({d_close}, dte_min=21, dte_max=45)
    assert result == []


def test_filter_expirations_returns_sorted():
    today = date.today()
    exps = {
        (today + timedelta(days=35)).strftime("%Y%m%d"),
        (today + timedelta(days=22)).strftime("%Y%m%d"),
    }
    result = _filter_expirations(exps, dte_min=21, dte_max=45)
    assert result == sorted(result)


# ---------------------------------------------------------------------------
# _filter_strikes
# ---------------------------------------------------------------------------


def test_filter_strikes_band_15pct():
    # Use values clearly inside/outside the band to avoid floating-point boundary edge cases.
    strikes = {70.0, 87.0, 95.0, 100.0, 105.0, 113.0, 130.0}
    result = _filter_strikes(strikes, spot=100.0, band_pct=0.15)
    assert 100.0 in result
    assert 87.0 in result
    assert 113.0 in result
    assert 70.0 not in result
    assert 130.0 not in result


def test_filter_strikes_returns_sorted():
    strikes = {105.0, 95.0, 100.0}
    result = _filter_strikes(strikes, spot=100.0)
    assert result == sorted(result)


# ---------------------------------------------------------------------------
# _cap_strikes (line-leak prevention at the source — bounds the qualify cartesian)
# ---------------------------------------------------------------------------


def test_cap_strikes_keeps_nearest_spot_sorted():
    strikes = [90.0, 95.0, 99.0, 100.0, 101.0, 105.0, 120.0]
    result = _cap_strikes(strikes, spot=100.0, max_strikes=3)
    # The 3 nearest 100 are 99, 100, 101 — returned sorted ascending.
    assert result == [99.0, 100.0, 101.0]


def test_cap_strikes_noop_when_under_cap():
    strikes = [99.0, 100.0, 101.0]
    assert _cap_strikes(strikes, spot=100.0, max_strikes=80) == strikes


def test_cap_strikes_disabled_when_zero():
    strikes = [float(i) for i in range(200)]
    assert _cap_strikes(strikes, spot=100.0, max_strikes=0) == strikes


# ---------------------------------------------------------------------------
# _build_chain_contracts — OTM-only cartesian (skips the ITM half of the band)
# ---------------------------------------------------------------------------


def test_build_chain_contracts_keeps_only_otm_calls_and_puts():
    result = _build_chain_contracts("AAPL", ["20261219"], [90.0, 100.0, 110.0], spot=100.0)
    rights_strikes = {(c.right, c.strike) for c in result}
    # Calls only at/above spot (OTM); puts only at/below spot (OTM). The ITM call@90 and
    # ITM put@110 must never be built — covered_call/cash_secured_put discard them anyway.
    assert rights_strikes == {("C", 100.0), ("C", 110.0), ("P", 90.0), ("P", 100.0)}


def test_build_chain_contracts_cartesian_over_expirations():
    result = _build_chain_contracts("AAPL", ["20261219", "20270116"], [110.0], spot=100.0)
    expiries = {c.lastTradeDateOrContractMonth for c in result}
    assert expiries == {"20261219", "20270116"}
    assert all(c.right == "C" for c in result)  # 110 is OTM for calls only, no puts built


def test_build_chain_contracts_empty_strikes_returns_empty():
    assert _build_chain_contracts("AAPL", ["20261219"], [], spot=100.0) == []


# ---------------------------------------------------------------------------
# _strike_band_pct (N6) — IV-scaled band with per-symbol override
# ---------------------------------------------------------------------------


def test_strike_band_uses_per_symbol_override():
    from src.ibkr.market_data import _strike_band_pct

    # SOXL carries a 0.45 override in universe.yaml; it wins over the floor without touching IV.
    assert _strike_band_pct("SOXL", 30) == pytest.approx(0.45)


def test_strike_band_scales_with_iv(monkeypatch):
    import math

    from src.ibkr.market_data import _strike_band_pct

    # AAPL has no override → band scales with stored IV (0.5), staying below the S8 cap.
    monkeypatch.setattr("src.storage.iv_history.latest_iv", lambda _s: 0.5)
    band = _strike_band_pct("AAPL", 30)
    assert band == pytest.approx(max(0.15, 1.5 * 0.5 * math.sqrt(30 / 365)))
    assert band > 0.15  # high IV genuinely widens the band past the floor


def test_strike_band_capped_at_max(monkeypatch):
    """S8 — a very high IV no longer explodes the band; it's clamped to strike_band_max_pct."""
    from src.common.config import get_config
    from src.ibkr.market_data import _strike_band_pct

    monkeypatch.setattr("src.storage.iv_history.latest_iv", lambda _s: 1.0)  # IV=100%
    # Uncapped this would be ~0.43 at 30 DTE; the cap holds it at strike_band_max_pct.
    assert _strike_band_pct("AAPL", 30) == pytest.approx(
        get_config().market_data.strike_band_max_pct
    )


def test_strike_band_override_not_clamped_by_cap():
    """An explicit per-symbol override is a deliberate choice — not clamped by the S8 cap."""
    from src.common.config import get_config
    from src.ibkr.market_data import _strike_band_pct

    # SOXL's 0.45 override exceeds the 0.40 default cap, yet is returned as-is.
    assert get_config().market_data.strike_band_max_pct < 0.45
    assert _strike_band_pct("SOXL", 30) == pytest.approx(0.45)


def test_strike_band_falls_back_to_floor_without_iv(monkeypatch):
    from src.ibkr.market_data import _strike_band_pct

    monkeypatch.setattr("src.storage.iv_history.latest_iv", lambda _s: None)
    assert _strike_band_pct("AAPL", 30) == pytest.approx(0.15)


# ---------------------------------------------------------------------------
# _batch_quotes: batching, cancel discipline, field mapping
# ---------------------------------------------------------------------------


def test_batch_quotes_splits_into_correct_batches():
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker()

    contracts = [_make_option_contract(strike=400.0 + i) for i in range(90)]
    _batch_quotes(ib, contracts, batch_size=40, throttle=0.0)

    # 3 batches of 40, 40, 10 → 3 sleep calls
    assert ib.sleep.call_count == 3


def test_batch_quotes_cancels_every_contract():
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker()

    contracts = [_make_option_contract(strike=400.0 + i) for i in range(90)]
    _batch_quotes(ib, contracts, batch_size=40, throttle=0.0)

    assert ib.cancelMktData.call_count == 90


def test_batch_quotes_returns_one_quote_per_contract():
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker()

    contracts = [_make_option_contract(strike=400.0 + i) for i in range(5)]
    quotes = _batch_quotes(ib, contracts, batch_size=40, throttle=0.0)
    assert len(quotes) == 5


def test_batch_quotes_maps_greeks_from_model():
    ib = MagicMock()
    greeks = _make_greeks(iv=0.40, delta=0.30, gamma=0.01, theta=-0.03, vega=0.08)
    ib.reqMktData.return_value = _make_ticker(bid=2.0, ask=2.4, greeks=greeks)

    contracts = [_make_option_contract(right="C")]
    quotes = _batch_quotes(ib, contracts, batch_size=40, throttle=0.0)

    q = quotes[0]
    assert q.iv == pytest.approx(0.40)
    assert q.delta == pytest.approx(0.30)
    assert q.gamma == pytest.approx(0.01)
    assert q.theta == pytest.approx(-0.03)
    assert q.vega == pytest.approx(0.08)
    assert q.bid == pytest.approx(2.0)
    assert q.ask == pytest.approx(2.4)
    assert q.greeks_source == "ibkr"


def test_batch_quotes_none_greeks_leaves_iv_none():
    ib = MagicMock()
    ticker = _make_ticker()
    ticker.modelGreeks = None
    ib.reqMktData.return_value = ticker

    contracts = [_make_option_contract(right="P")]
    quotes = _batch_quotes(ib, contracts, batch_size=40, throttle=0.0)

    q = quotes[0]
    assert q.iv is None
    assert q.delta is None
    assert q.gamma is None
    assert q.theta is None
    assert q.vega is None


def test_batch_quotes_uses_put_oi_for_puts():
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker(call_oi=111.0, put_oi=999.0)

    contracts = [_make_option_contract(right="P")]
    quotes = _batch_quotes(ib, contracts, batch_size=40, throttle=0.0)
    assert quotes[0].open_interest == 999


def test_batch_quotes_uses_call_oi_for_calls():
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker(call_oi=777.0, put_oi=333.0)

    contracts = [_make_option_contract(right="C")]
    quotes = _batch_quotes(ib, contracts, batch_size=40, throttle=0.0)
    assert quotes[0].open_interest == 777


def test_batch_quotes_right_enum_mapped_correctly():
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker()

    call_c = _make_option_contract(right="C")
    put_c = _make_option_contract(right="P")
    quotes = _batch_quotes(ib, [call_c, put_c], batch_size=40, throttle=0.0)

    assert quotes[0].right is OptionRight.CALL
    assert quotes[1].right is OptionRight.PUT


# ---------------------------------------------------------------------------
# _batch_quotes_async: async path runs IB calls on the loop (no worker thread)
# ---------------------------------------------------------------------------


async def test_batch_quotes_async_returns_quotes_and_cancels(monkeypatch):
    from src.ibkr.market_data import _batch_quotes_async

    # Don't actually wait the per-batch settle time.
    monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", AsyncMock())

    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker(bid=2.0, ask=2.4)
    contracts = [_make_option_contract(strike=400.0 + i) for i in range(5)]

    quotes = await _batch_quotes_async(ib, contracts, batch_size=40, throttle=0.0)

    assert len(quotes) == 5
    assert ib.cancelMktData.call_count == 5
    assert quotes[0].bid == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# qualify_stock / qualify_options
# ---------------------------------------------------------------------------


def test_qualify_stock_raises_when_empty_result():
    ib = MagicMock()
    ib.qualifyContracts.return_value = []
    with pytest.raises(ValueError, match="Could not qualify"):
        qualify_stock(ib, "FAKE")


def test_qualify_stock_raises_when_no_con_id():
    ib = MagicMock()
    c = MagicMock()
    c.conId = 0
    ib.qualifyContracts.return_value = [c]
    with pytest.raises(ValueError):
        qualify_stock(ib, "FAKE")


def test_qualify_options_drops_unqualified():
    ib = MagicMock()
    c1, c2 = MagicMock(), MagicMock()
    c1.conId = 99
    c2.conId = 0
    ib.qualifyContracts.return_value = [c1, c2]
    result = qualify_options(ib, [c1, c2])
    assert result == [c1]


def test_qualify_options_empty_input():
    ib = MagicMock()
    result = qualify_options(ib, [])
    assert result == []
    ib.qualifyContracts.assert_not_called()


# ---------------------------------------------------------------------------
# qualify_options_async — chunked, paced, per-chunk timeout-bounded (anti-wedge)
# ---------------------------------------------------------------------------


async def test_qualify_options_async_chunks_and_paces(monkeypatch):
    """A large batch is qualified in chunk_size chunks with a throttle between chunks —
    never one monolithic burst (the SMH 768-contract wedge). Each contract is its own request
    (2026-10-10), so the chunk bounds how many are in flight at once."""
    real_sleep = asyncio.sleep
    sleep = AsyncMock()
    monkeypatch.setattr("src.ibkr.contracts.asyncio.sleep", sleep)

    in_flight = peak = 0

    async def _echo(*cs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await real_sleep(0)
        in_flight -= 1
        return list(cs)

    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(side_effect=_echo)
    contracts = [_make_option_contract(strike=400.0 + i, con_id=1000 + i) for i in range(5)]

    result = await qualify_options_async(
        ib, contracts, chunk_size=2, throttle_seconds=0.25, chunk_timeout_seconds=20
    )

    assert len(result) == 5
    assert ib.qualifyContractsAsync.call_count == 5  # one request per contract
    assert peak == 2  # never more than chunk_size in flight
    assert sleep.await_count == 2  # paced between the 3 chunks, not after the last


async def test_qualify_options_async_skips_timed_out_chunk():
    """A contract whose qualification hangs is dropped instead of hanging the whole symbol —
    this is what prevents the outer symbol_timeout from killing it mid-flight. Its chunk-mates
    that answered are kept (2026-10-10); the stuck request raises TimeoutError."""

    async def _qualify(*cs):
        if any(c.strike == 401.0 for c in cs):
            raise TimeoutError  # a stuck request
        return list(cs)

    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(side_effect=_qualify)

    contracts = [_make_option_contract(strike=400.0 + i, con_id=2000 + i) for i in range(4)]
    result = await qualify_options_async(ib, contracts, chunk_size=2, throttle_seconds=0)

    # 401 times out and is skipped; 400 (its chunk-mate) and the second chunk qualify.
    assert {c.strike for c in result} == {400.0, 402.0, 403.0}


# ---------------------------------------------------------------------------
# Market-data line registry — leak guard
# ---------------------------------------------------------------------------


def test_drain_market_data_lines_reclaims_open_lines():
    """A chain fetch interrupted before its finally-cancel leaves registered lines; drain
    cancels every straggler so it can't eat the next symbol's ~100-line budget."""
    from src.ibkr import market_data as md

    md._OPEN_LINES.clear()
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker()
    # Open 3 lines with distinct conIds but never close them (simulates a cancelled fetch).
    contracts = [_make_option_contract(strike=400.0 + i, con_id=3000 + i) for i in range(3)]
    for c in contracts:
        md._open_line(ib, c, snapshot=True)
    assert len(md._OPEN_LINES) == 3

    reclaimed = drain_market_data_lines(ib)

    assert reclaimed == 3
    assert ib.cancelMktData.call_count == 3
    assert md._OPEN_LINES == {}


def test_drain_market_data_lines_noop_when_clean():
    from src.ibkr import market_data as md

    md._OPEN_LINES.clear()
    ib = MagicMock()
    assert drain_market_data_lines(ib) == 0
    ib.cancelMktData.assert_not_called()


async def test_batch_quotes_async_waits_for_open_interest(monkeypatch):
    """Regression: the readiness check once only waited for bid/ask, so the batch cancelled
    the line the instant a quote appeared — before OI (tick 101) had a chance to stream in.
    That left open_interest None on nearly every quote in production tonight (2026-08-14),
    which passes_liquidity_gates treats as an automatic "illiquid" fail regardless of how
    liquid the option actually is. OI now arrives 2 poll ticks after bid/ask; the batch must
    wait for it rather than returning as soon as bid/ask alone are present."""
    from src.ibkr.market_data import _batch_quotes_async

    real_sleep = asyncio.sleep
    ticker = _make_ticker(bid=2.0, ask=2.4, call_oi=None)
    calls = {"n": 0}

    async def _fast_sleep(_):
        calls["n"] += 1
        if calls["n"] >= 2:
            ticker.callOpenInterest = 500.0  # OI tick "arrives" after bid/ask already did
        await real_sleep(0)  # yield without actually waiting out the test

    monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", _fast_sleep)

    ib = MagicMock()
    ib.reqMktData.return_value = ticker
    contracts = [_make_option_contract(strike=400.0, right="C")]

    quotes = await _batch_quotes_async(ib, contracts, batch_size=40, throttle=0.0)

    assert calls["n"] >= 2  # didn't return on the first bid/ask-only check
    assert quotes[0].open_interest == 500


async def test_batch_quotes_async_times_out_when_oi_never_arrives(monkeypatch):
    """OI staying missing for the whole ceiling must not hang the batch — it should return
    with open_interest=None (exactly as the old bid/ask-only wait did on timeout), leaving the
    liquidity gate to reject it rather than the fetch stalling."""
    from src.ibkr.market_data import _batch_quotes_async

    monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", AsyncMock())
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker(bid=2.0, ask=2.4, call_oi=None, put_oi=None)
    contracts = [_make_option_contract(strike=400.0, right="C")]

    quotes = await _batch_quotes_async(ib, contracts, batch_size=40, throttle=0.0)

    assert len(quotes) == 1
    assert quotes[0].open_interest is None
    assert ib.cancelMktData.call_count == 1


async def test_batch_quotes_async_keeps_quotes_that_arrive_after_two_seconds(monkeypatch):
    """Regression (2026-10-09): on real-time data a 30-40-line batch's bid/ask land at ~2.5-3s
    (live probe: 6/30 NVDA quotes by 2s, 30/30 by 3s), but the batch ceiling was a hard 2s — so
    ~94% of quotes were cancelled empty and rejected as `illiquid_no_quote`, producing zero
    candidates. The ceiling is now `market_data.chain_quote_ceiling_seconds` (default 4s)."""
    from src.ibkr.market_data import _batch_quotes_async

    real_sleep = asyncio.sleep
    ticker = _make_ticker(bid=None, ask=None, call_oi=None)
    polls = {"n": 0}

    async def _fast_sleep(_):
        polls["n"] += 1
        if polls["n"] == 25:  # 2.5s of 0.1s polls — past the old 2s ceiling
            ticker.bid, ticker.ask, ticker.callOpenInterest = 2.0, 2.4, 500.0
        await real_sleep(0)

    monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", _fast_sleep)
    ib = MagicMock()
    ib.reqMktData.return_value = ticker

    quotes = await _batch_quotes_async(
        ib, [_make_option_contract(strike=400.0, right="C")], batch_size=40, throttle=0.0
    )

    assert quotes[0].bid == pytest.approx(2.0)
    assert quotes[0].open_interest == 500


async def test_batch_quotes_async_stops_waiting_for_missing_oi_after_grace(monkeypatch):
    """Some OI ticks never arrive (live probe 2026-10-09: 4/30). Once every line in the batch
    has a bid/ask, the batch waits only `chain_oi_grace_seconds` more for the stragglers rather
    than burning the whole ceiling on every batch."""
    from src.common.config import get_config
    from src.ibkr.market_data import _POLL_INTERVAL_SECONDS, _batch_quotes_async

    sleeps = AsyncMock()
    monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", sleeps)
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker(bid=2.0, ask=2.4, call_oi=None, put_oi=None)

    await _batch_quotes_async(
        ib, [_make_option_contract(strike=400.0, right="C")], batch_size=40, throttle=0.0
    )

    md = get_config().market_data
    grace_polls = int(md.chain_oi_grace_seconds / _POLL_INTERVAL_SECONDS)
    ceiling_polls = int(md.chain_quote_ceiling_seconds / _POLL_INTERVAL_SECONDS)
    assert grace_polls <= sleeps.await_count <= grace_polls + 1 < ceiling_polls


class _ScriptedTickers:
    """Fake poll clock: each ``asyncio.sleep`` is one 0.1s poll; ``arrivals`` maps a poll
    number to the tickers that receive a bid/ask (and OI) on it."""

    def __init__(self, n: int, arrivals: dict[int, list[int]]) -> None:
        self.tickers = [_make_ticker(bid=None, ask=None, call_oi=None) for _ in range(n)]
        self.arrivals = arrivals
        self.polls = 0

    async def sleep(self, _):
        self.polls += 1
        for i in self.arrivals.get(self.polls, []):
            t = self.tickers[i]
            t.bid, t.ask, t.callOpenInterest = 2.0, 2.4, 500.0


async def test_batch_quotes_async_waits_out_the_throttled_send_of_a_later_batch(monkeypatch):
    """Live 2026-10-09 (AMD, 10 batches of 40): ib_async sends at most 45 requests/s, so a
    later batch's 40 cancels + 40 new requests push its first tick to ~1.6-2.9s and its last to
    4-6.4s. A 4s ceiling cut most of those batches off (AMD 153/363 quoted); 8s got 363/363."""
    from src.ibkr.market_data import _batch_quotes_async

    # First tick at 3.0s, then a steady stream to the last at 6.0s.
    script = _ScriptedTickers(4, {30: [0], 40: [1], 50: [2], 60: [3]})
    monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", script.sleep)
    ib = MagicMock()
    ib.reqMktData.side_effect = script.tickers
    contracts = [_make_option_contract(strike=400.0 + i, con_id=7000 + i) for i in range(4)]

    quotes = await _batch_quotes_async(ib, contracts, batch_size=40, throttle=0.0)

    assert all(q.bid == pytest.approx(2.0) for q in quotes)


async def test_batch_quotes_async_stops_once_quotes_stall(monkeypatch):
    """A strike with no market never quotes. Once the rest of the batch has quoted and nothing
    new arrives for `chain_quote_settle_seconds`, the batch returns instead of burning the
    whole ceiling — every illiquid symbol would otherwise pay the full ceiling per batch."""
    from src.common.config import get_config
    from src.ibkr.market_data import _POLL_INTERVAL_SECONDS, _batch_quotes_async

    script = _ScriptedTickers(3, {20: [0], 25: [1]})  # ticker 2 never quotes
    monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", script.sleep)
    ib = MagicMock()
    ib.reqMktData.side_effect = script.tickers
    contracts = [_make_option_contract(strike=400.0 + i, con_id=7100 + i) for i in range(3)]

    quotes = await _batch_quotes_async(ib, contracts, batch_size=40, throttle=0.0)

    md = get_config().market_data
    settle_polls = int(md.chain_quote_settle_seconds / _POLL_INTERVAL_SECONDS)
    assert quotes[0].bid is not None and quotes[1].bid is not None and quotes[2].bid is None
    assert script.polls <= 25 + settle_polls + 1
    assert script.polls < int(md.chain_quote_ceiling_seconds / _POLL_INTERVAL_SECONDS)


async def test_batch_quotes_async_does_not_stall_out_on_a_steady_trickle(monkeypatch):
    """Quotes trickling in (gaps shorter than the settle window) keep the batch waiting."""
    from src.ibkr.market_data import _batch_quotes_async

    script = _ScriptedTickers(3, {10: [0], 20: [1], 30: [2]})  # 1.0s gaps
    monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", script.sleep)
    ib = MagicMock()
    ib.reqMktData.side_effect = script.tickers
    contracts = [_make_option_contract(strike=400.0 + i, con_id=7200 + i) for i in range(3)]

    quotes = await _batch_quotes_async(ib, contracts, batch_size=40, throttle=0.0)

    assert all(q.bid is not None for q in quotes)


async def test_batch_quotes_async_leaves_no_open_lines(monkeypatch):
    """The happy path must register and then deregister every line — no leak after a clean batch."""
    from src.ibkr import market_data as md
    from src.ibkr.market_data import _batch_quotes_async

    md._OPEN_LINES.clear()
    monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", AsyncMock())
    ib = MagicMock()
    ib.reqMktData.return_value = _make_ticker(bid=2.0, ask=2.4)
    contracts = [_make_option_contract(strike=400.0 + i, con_id=4000 + i) for i in range(5)]

    await _batch_quotes_async(ib, contracts, batch_size=40, throttle=0.0)

    assert md._OPEN_LINES == {}
    assert drain_market_data_lines(ib) == 0


# ---------------------------------------------------------------------------
# _enrich_greeks_yf: Black-Scholes fallback for delayed-data paper accounts
# ---------------------------------------------------------------------------


def _make_quote_no_greeks(
    right: str = "C",
    strike: float = 200.0,
    expiry_offset: int = 34,
) -> OptionQuote:
    exp = date.today() + timedelta(days=expiry_offset)
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL if right == "C" else OptionRight.PUT,
        strike=strike,
        expiry=exp,
        bid=1.80,
        ask=2.20,
        delta=None,
        iv=None,
        greeks_source="ibkr",
    )


class TestEnrichGreeksYf:
    def _make_chain_df(self, strikes: list[float], iv: float):
        import pandas as pd

        return pd.DataFrame({"strike": strikes, "impliedVolatility": [iv] * len(strikes)})

    def test_skips_when_all_deltas_present(self, monkeypatch):
        quote = OptionQuote(
            underlying="AAPL",
            right=OptionRight.CALL,
            strike=200.0,
            expiry=date.today() + timedelta(days=30),
            delta=0.30,
            greeks_source="ibkr",
        )
        # yfinance must NOT be called
        monkeypatch.setattr(
            "src.ibkr.market_data.yf.Ticker",
            lambda _: (_ for _ in ()).throw(AssertionError("yf called")),
        )
        _enrich_greeks_yf("AAPL", 195.0, [quote])
        assert quote.greeks_source == "ibkr"

    def test_fills_delta_and_sets_source(self, monkeypatch):
        from types import SimpleNamespace

        quote = _make_quote_no_greeks(right="C", strike=200.0, expiry_offset=34)
        exp_str = quote.expiry.strftime("%Y-%m-%d")

        chain = SimpleNamespace(
            calls=self._make_chain_df([200.0], 0.30),
            puts=self._make_chain_df([], 0.30),
        )
        mock_ticker = MagicMock()
        mock_ticker.options = [exp_str]
        mock_ticker.option_chain.return_value = chain
        monkeypatch.setattr("src.ibkr.market_data.yf.Ticker", lambda _: mock_ticker)

        _enrich_greeks_yf("AAPL", 195.0, [quote])

        assert quote.delta is not None
        assert 0.0 < quote.delta < 1.0
        assert quote.greeks_source == "black_scholes"
        assert quote.iv == pytest.approx(0.30, abs=1e-5)

    def test_put_delta_is_negative(self, monkeypatch):
        from types import SimpleNamespace

        quote = _make_quote_no_greeks(right="P", strike=190.0, expiry_offset=34)
        exp_str = quote.expiry.strftime("%Y-%m-%d")

        chain = SimpleNamespace(
            calls=self._make_chain_df([], 0.25),
            puts=self._make_chain_df([190.0], 0.25),
        )
        mock_ticker = MagicMock()
        mock_ticker.options = [exp_str]
        mock_ticker.option_chain.return_value = chain
        monkeypatch.setattr("src.ibkr.market_data.yf.Ticker", lambda _: mock_ticker)

        _enrich_greeks_yf("AAPL", 195.0, [quote])

        assert quote.delta is not None
        assert quote.delta < 0.0

    def test_skips_expiry_not_in_yfinance(self, monkeypatch):
        quote = _make_quote_no_greeks(expiry_offset=34)
        mock_ticker = MagicMock()
        mock_ticker.options = []  # no matching expiry
        monkeypatch.setattr("src.ibkr.market_data.yf.Ticker", lambda _: mock_ticker)

        _enrich_greeks_yf("AAPL", 195.0, [quote])

        assert quote.delta is None
        assert quote.greeks_source == "ibkr"

    def test_does_not_overwrite_existing_iv(self, monkeypatch):
        from types import SimpleNamespace

        exp = date.today() + timedelta(days=34)
        quote = OptionQuote(
            underlying="AAPL",
            right=OptionRight.CALL,
            strike=200.0,
            expiry=exp,
            iv=0.99,  # existing IV — must not be overwritten
            delta=None,
            greeks_source="ibkr",
        )
        exp_str = exp.strftime("%Y-%m-%d")
        chain = SimpleNamespace(
            calls=self._make_chain_df([200.0], 0.30),
            puts=self._make_chain_df([], 0.30),
        )
        mock_ticker = MagicMock()
        mock_ticker.options = [exp_str]
        mock_ticker.option_chain.return_value = chain
        monkeypatch.setattr("src.ibkr.market_data.yf.Ticker", lambda _: mock_ticker)

        _enrich_greeks_yf("AAPL", 195.0, [quote])

        assert quote.iv == pytest.approx(0.99, abs=1e-5)

    def test_swallows_yfinance_exception(self, monkeypatch):
        quote = _make_quote_no_greeks()
        monkeypatch.setattr(
            "src.ibkr.market_data.yf.Ticker",
            lambda _: (_ for _ in ()).throw(RuntimeError("network error")),
        )
        # Must not raise
        _enrich_greeks_yf("AAPL", 195.0, [quote])
        assert quote.delta is None


# ---------------------------------------------------------------------------
# _get_spot / _get_spot_async: marketPrice -> previous close -> bounded
# reqHistoricalData fallback chain
# ---------------------------------------------------------------------------


def _make_spot_ticker(market_price: float, close: float = float("nan")) -> SimpleNamespace:
    t = SimpleNamespace(close=close)
    t.marketPrice = lambda: market_price
    return t


def _make_bar(close: float) -> SimpleNamespace:
    return SimpleNamespace(close=close)


class TestGetSpot:
    def test_uses_market_price_when_available(self):
        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=123.45)
        assert _get_spot(ib, MagicMock()) == pytest.approx(123.45)
        ib.reqHistoricalData.assert_not_called()

    def test_falls_back_to_previous_close_without_extra_request(self):
        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=float("nan"), close=99.0)
        assert _get_spot(ib, MagicMock()) == pytest.approx(99.0)
        ib.reqHistoricalData.assert_not_called()

    def test_falls_back_to_bounded_historical_bar(self):
        from src.common.config import get_config

        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=float("nan"))
        ib.reqHistoricalData.return_value = [_make_bar(50.0)]

        assert _get_spot(ib, MagicMock()) == pytest.approx(50.0)

        _, kwargs = ib.reqHistoricalData.call_args
        assert kwargs["timeout"] == get_config().market_data.spot_history_timeout_seconds

    def test_raises_when_no_price_available_anywhere(self):
        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=float("nan"))
        ib.reqHistoricalData.return_value = []
        stock = MagicMock()
        stock.symbol = "ZZZ"
        with pytest.raises(ValueError, match="Could not get spot price"):
            _get_spot(ib, stock)


class TestGetSpotAsync:
    @pytest.mark.asyncio
    async def test_uses_market_price_when_available(self, monkeypatch):
        monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", AsyncMock())
        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=123.45)
        ib.reqHistoricalDataAsync = AsyncMock()
        assert await _get_spot_async(ib, MagicMock()) == pytest.approx(123.45)
        ib.reqHistoricalDataAsync.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_previous_close_without_extra_request(self, monkeypatch):
        monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", AsyncMock())
        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=float("nan"), close=99.0)
        ib.reqHistoricalDataAsync = AsyncMock()
        assert await _get_spot_async(ib, MagicMock()) == pytest.approx(99.0)
        ib.reqHistoricalDataAsync.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_bounded_historical_bar(self, monkeypatch):
        from src.common.config import get_config

        monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", AsyncMock())
        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=float("nan"))
        ib.reqHistoricalDataAsync = AsyncMock(return_value=[_make_bar(50.0)])

        assert await _get_spot_async(ib, MagicMock()) == pytest.approx(50.0)

        _, kwargs = ib.reqHistoricalDataAsync.call_args
        assert kwargs["timeout"] == get_config().market_data.spot_history_timeout_seconds

    @pytest.mark.asyncio
    async def test_raises_when_no_price_available_anywhere(self, monkeypatch):
        monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", AsyncMock())
        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=float("nan"))
        ib.reqHistoricalDataAsync = AsyncMock(return_value=[])
        stock = MagicMock()
        stock.symbol = "ZZZ"
        with pytest.raises(ValueError, match="Could not get spot price"):
            await _get_spot_async(ib, stock)


# ---------------------------------------------------------------------------
# S3 — _resolve_spot_async prefers the cached daily close (no extra snapshot)
# ---------------------------------------------------------------------------


def _close_df(close: float):
    import pandas as pd

    return pd.DataFrame({"Close": [close - 1.0, close]})


class TestResolveSpotAsync:
    @pytest.mark.asyncio
    async def test_uses_cached_close_without_reqmktdata(self, monkeypatch):
        """Cached path: get_ohlcv has a close → no reqMktData snapshot is issued (S3)."""
        monkeypatch.setattr("src.ibkr.market_data.get_ohlcv", lambda _sym: _close_df(187.5))
        ib = MagicMock()
        spot = await _resolve_spot_async(ib, MagicMock(), "AAPL")
        assert spot == pytest.approx(187.5)
        ib.reqMktData.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_snapshot_when_cache_empty(self, monkeypatch):
        """No cached close → fall back to the live snapshot chain (46a21bf preserved)."""
        import pandas as pd

        monkeypatch.setattr("src.ibkr.market_data.get_ohlcv", lambda _sym: pd.DataFrame())
        monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", AsyncMock())
        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=200.0)
        ib.reqHistoricalDataAsync = AsyncMock()
        spot = await _resolve_spot_async(ib, MagicMock(), "AAPL")
        assert spot == pytest.approx(200.0)
        ib.reqMktData.assert_called_once()

    @pytest.mark.asyncio
    async def test_falls_back_when_get_ohlcv_raises(self, monkeypatch):
        def _boom(_sym):
            raise RuntimeError("yfinance down")

        monkeypatch.setattr("src.ibkr.market_data.get_ohlcv", _boom)
        monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", AsyncMock())
        ib = MagicMock()
        ib.reqMktData.return_value = _make_spot_ticker(market_price=150.0)
        ib.reqHistoricalDataAsync = AsyncMock()
        spot = await _resolve_spot_async(ib, MagicMock(), "AAPL")
        assert spot == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# S7 — event-driven wait: returns as soon as ticks populate, ceiling-bounded
# ---------------------------------------------------------------------------


class TestAwaitReady:
    @pytest.mark.asyncio
    async def test_returns_immediately_when_ready(self):
        calls = {"sleep": 0}

        async def _no_sleep(_):
            calls["sleep"] += 1

        import src.ibkr.market_data as md

        orig = md.asyncio.sleep
        md.asyncio.sleep = _no_sleep  # type: ignore[assignment]
        try:
            await _await_ready(lambda: True, ceiling=2.0)
        finally:
            md.asyncio.sleep = orig
        assert calls["sleep"] == 0  # predicate true on first check → no waiting

    @pytest.mark.asyncio
    async def test_bounded_by_ceiling_when_never_ready(self, monkeypatch):
        calls = {"sleep": 0}

        async def _count_sleep(_):
            calls["sleep"] += 1

        monkeypatch.setattr("src.ibkr.market_data.asyncio.sleep", _count_sleep)
        await _await_ready(lambda: False, ceiling=2.0)
        # ceiling / 0.1s poll interval = 20 iterations, then gives up (no spin).
        assert calls["sleep"] == 20

    def test_quote_ready_true_with_ask_only(self):
        assert _quote_ready(SimpleNamespace(bid=float("nan"), ask=2.4)) is True

    def test_quote_ready_false_when_bid_is_sentinel_and_no_ask(self):
        assert _quote_ready(SimpleNamespace(bid=-1.0, ask=float("nan"))) is False

    def test_quote_ready_false_when_right_given_and_oi_missing(self):
        """Regression: without the OI check, a batch would race ahead the instant bid/ask
        populated and cancel the line before the OI tick (101) arrived — leaving
        open_interest None on most quotes and failing the liquidity gate near-universally."""
        ticker = SimpleNamespace(bid=2.0, ask=2.4, callOpenInterest=None, putOpenInterest=None)
        assert _quote_ready(ticker, right="C") is False

    def test_quote_ready_true_when_right_given_and_oi_present(self):
        ticker = SimpleNamespace(bid=2.0, ask=2.4, callOpenInterest=500.0, putOpenInterest=None)
        assert _quote_ready(ticker, right="C") is True

    def test_quote_ready_checks_matching_side_oi(self):
        """A call's OI tick populating must not satisfy readiness for a put on the same
        ticker, and vice versa."""
        ticker = SimpleNamespace(bid=2.0, ask=2.4, callOpenInterest=500.0, putOpenInterest=None)
        assert _quote_ready(ticker, right="P") is False

    def test_quote_ready_ignores_oi_when_no_market_yet(self):
        ticker = SimpleNamespace(
            bid=float("nan"), ask=float("nan"), callOpenInterest=500.0, putOpenInterest=600.0
        )
        assert _quote_ready(ticker, right="C") is False

    def test_spot_ready_true_with_marketprice(self):
        assert _spot_ready(_make_spot_ticker(market_price=100.0)) is True

    def test_spot_ready_true_with_close_only(self):
        assert _spot_ready(_make_spot_ticker(market_price=float("nan"), close=99.0)) is True

    def test_spot_ready_false_when_empty(self):
        assert _spot_ready(_make_spot_ticker(market_price=float("nan"))) is False


# ---------------------------------------------------------------------------
# S2 — IBKR-first greeks: per-contract computation fallback + IBKR-IV Black-Scholes
# ---------------------------------------------------------------------------


class TestPickGreeks:
    def test_prefers_model_greeks(self):
        ticker = SimpleNamespace(
            modelGreeks=_make_greeks(delta=-0.25),
            lastGreeks=_make_greeks(delta=-0.40),
        )
        assert _pick_greeks(ticker).delta == pytest.approx(-0.25)

    def test_falls_back_to_last_then_ask_then_bid(self):
        # model absent, last present → use last
        ticker = SimpleNamespace(
            modelGreeks=None,
            lastGreeks=_make_greeks(delta=-0.30),
            askGreeks=_make_greeks(delta=-0.31),
            bidGreeks=_make_greeks(delta=-0.32),
        )
        assert _pick_greeks(ticker).delta == pytest.approx(-0.30)

        # model + last absent → use ask
        ticker.lastGreeks = None
        assert _pick_greeks(ticker).delta == pytest.approx(-0.31)

    def test_returns_none_when_no_computation_has_delta(self):
        ticker = SimpleNamespace(modelGreeks=None)
        assert _pick_greeks(ticker) is None

    def test_ticker_to_quote_uses_fallback_computation(self):
        # No modelGreeks, but askGreeks carries real IBKR greeks → genuine IBKR delta.
        ticker = _make_ticker(greeks=None)
        ticker.modelGreeks = None
        ticker.askGreeks = _make_greeks(iv=0.42, delta=0.28)
        c = _make_option_contract(right="C", strike=400.0)
        q = _ticker_to_quote(c, ticker)
        assert q.delta == pytest.approx(0.28)
        assert q.iv == pytest.approx(0.42)
        assert q.greeks_source == "ibkr"

    def test_ticker_to_quote_captures_underlying_iv_when_no_greeks(self):
        # No per-contract greeks at all, but generic-tick-106 underlying IV is present.
        ticker = _make_ticker(greeks=None)
        ticker.modelGreeks = None
        ticker.impliedVolatility = 0.55
        c = _make_option_contract(right="P", strike=380.0)
        q = _ticker_to_quote(c, ticker)
        assert q.delta is None  # no delta yet — BS step fills it later
        assert q.iv == pytest.approx(0.55)


class TestEnrichGreeksFromIbkrIv:
    def _quote(self, *, iv, delta=None, right="C", strike=200.0):
        return OptionQuote(
            underlying="AAPL",
            right=OptionRight.CALL if right == "C" else OptionRight.PUT,
            strike=strike,
            expiry=date.today() + timedelta(days=34),
            iv=iv,
            delta=delta,
            greeks_source="ibkr",
        )

    def test_fills_delta_from_ibkr_iv_and_labels_black_scholes(self):
        q = self._quote(iv=0.30)
        n = _enrich_greeks_from_ibkr_iv("AAPL", 200.0, [q])
        assert n == 1
        assert q.delta is not None
        assert q.greeks_source == "black_scholes"

    def test_put_delta_negative(self):
        q = self._quote(iv=0.30, right="P", strike=190.0)
        _enrich_greeks_from_ibkr_iv("AAPL", 200.0, [q])
        assert q.delta is not None and q.delta < 0.0

    def test_skips_quotes_with_all_greeks(self):
        """Phase 1: a quote carrying delta AND gamma AND theta AND vega is left untouched —
        nothing left to compute from the IBKR IV."""
        q = self._quote(iv=0.30, delta=0.25)
        q.gamma = 0.01
        q.theta = -5.0
        q.vega = 0.2
        n = _enrich_greeks_from_ibkr_iv("AAPL", 200.0, [q])
        assert n == 0
        assert q.greeks_source == "ibkr"  # untouched

    def test_fills_missing_greeks_when_delta_present(self):
        """Phase 1: a quote with delta but missing gamma/theta/vega gets those filled from
        the IBKR IV via Black-Scholes (enriched), rather than being skipped as before."""
        q = self._quote(iv=0.30, delta=0.25)
        n = _enrich_greeks_from_ibkr_iv("AAPL", 200.0, [q])
        assert n == 1
        assert q.gamma is not None
        assert q.theta is not None
        assert q.vega is not None
        assert q.greeks_source == "black_scholes"

    def test_skips_quotes_without_iv(self):
        q = self._quote(iv=None)
        n = _enrich_greeks_from_ibkr_iv("AAPL", 200.0, [q])
        assert n == 0
        assert q.delta is None

    def test_yahoo_skipped_when_ibkr_iv_filled_everything(self, monkeypatch):
        # After the IBKR-IV BS step fills delta, _enrich_greeks_yf must not call yfinance.
        q = self._quote(iv=0.30)
        _enrich_greeks_from_ibkr_iv("AAPL", 200.0, [q])
        monkeypatch.setattr(
            "src.ibkr.market_data.yf.Ticker",
            lambda _: (_ for _ in ()).throw(AssertionError("yfinance must not be called")),
        )
        _enrich_greeks_yf("AAPL", 200.0, [q])  # no missing → short-circuits before yf


# ---------------------------------------------------------------------------
# probe_market_data_health — half-dead-socket pre-scan guard
# ---------------------------------------------------------------------------


class _StockTicker:
    """Minimal stand-in for an ib_async stock ticker that _spot_ready understands."""

    def __init__(self, price: float = 0.0, close: float = 0.0) -> None:
        self._price = price
        self.close = close

    def marketPrice(self) -> float:
        return self._price


@pytest.mark.asyncio
async def test_probe_healthy_when_tick_arrives(monkeypatch):
    monkeypatch.setattr(
        "src.ibkr.market_data.qualify_stock_async",
        AsyncMock(return_value=MagicMock(symbol="SPY")),
    )
    ib = MagicMock()
    ib.reqMktData.return_value = _StockTicker(price=500.0)

    probe = await probe_market_data_health(ib, timeout=0.5)
    assert probe.healthy is True
    assert bool(probe) is True  # truthiness contract for legacy call sites


@pytest.mark.asyncio
async def test_probe_unhealthy_when_no_tick(monkeypatch):
    """Qualify succeeds but the snapshot never produces a price/close — a half-dead farm.

    No error codes arrive, so the diagnosis is the generic half-dead state, with an
    action hint pointing at the forced reconnect (2026-09-09 diagnosis fix)."""
    monkeypatch.setattr(
        "src.ibkr.market_data.qualify_stock_async",
        AsyncMock(return_value=MagicMock(symbol="SPY")),
    )
    ib = MagicMock()
    ib.reqMktData.return_value = _StockTicker(price=float("nan"), close=0.0)

    probe = await probe_market_data_health(ib, timeout=0.2)
    assert probe.healthy is False
    assert bool(probe) is False
    assert probe.error_codes == []
    assert probe.probe_symbol == "SPY"
    assert probe.probe_timeout == 0.2
    assert "no specific error" in probe.diagnosis
    assert probe.action_hint  # the operator message always names a next step
    # The probe must always reclaim its line, even on failure.
    ib.cancelMktData.assert_called()


@pytest.mark.asyncio
async def test_probe_diagnoses_error_1100(monkeypatch):
    """A 1100 arriving during the probe window names the classic half-dead socket:
    Gateway lost its upstream link; the hint points at the Gateway window."""
    monkeypatch.setattr(
        "src.ibkr.market_data.qualify_stock_async",
        AsyncMock(return_value=MagicMock(symbol="SPY")),
    )
    ib = MagicMock()
    listeners = []
    ib.errorEvent.__iadd__.side_effect = lambda fn: listeners.append(fn) or ib.errorEvent
    ib.errorEvent.__isub__.side_effect = lambda fn: listeners.remove(fn) or ib.errorEvent

    def _emit_1100(contract, **kwargs):
        for fn in listeners:
            fn(-1, 1100, "Connectivity between IBKR and TWS has been lost", contract)
        return _StockTicker(price=float("nan"), close=0.0)

    ib.reqMktData.side_effect = _emit_1100
    probe = await probe_market_data_health(ib, timeout=0.05)
    assert probe.healthy is False
    assert probe.error_codes == [1100]
    assert "1100" in probe.diagnosis
    assert "lost its upstream link" in probe.diagnosis
    assert "Gateway" in probe.action_hint
    assert listeners == []


@pytest.mark.asyncio
async def test_probe_diagnoses_error_10197_competing_session(monkeypatch):
    """10197 must NOT be labelled a half-dead socket — the fix is closing the other login,
    and the action hint must say a reconnect won't help (2026-09-08 misdiagnosis fix)."""
    monkeypatch.setattr(
        "src.ibkr.market_data.qualify_stock_async",
        AsyncMock(return_value=MagicMock(symbol="SPY")),
    )
    ib = MagicMock()
    ib.reqMktData.return_value = _StockTicker(price=float("nan"), close=0.0)
    # _await_ready polls with real sleeps; make the probe's wait instant by having the
    # error land synchronously when reqMktData opens the line.
    listeners = []
    ib.errorEvent.__iadd__.side_effect = lambda fn: listeners.append(fn) or ib.errorEvent
    ib.errorEvent.__isub__.side_effect = lambda fn: listeners.remove(fn) or ib.errorEvent

    def _emit_10197(contract, **kwargs):
        for fn in listeners:
            fn(4, 10197, "No market data during competing live session", contract)
        return _StockTicker(price=float("nan"), close=0.0)

    ib.reqMktData.side_effect = _emit_10197
    probe = await probe_market_data_health(ib, timeout=0.05)
    assert probe.healthy is False
    assert probe.error_codes == [10197]
    assert "10197" in probe.diagnosis
    assert "competing live session" in probe.diagnosis
    assert "reconnect will NOT fix" in probe.action_hint
    # The listener must be unhooked after the probe, win or lose.
    assert listeners == []


@pytest.mark.asyncio
async def test_probe_diagnoses_no_subscription_codes(monkeypatch):
    """354/10089-10091 mean an entitlement problem, not a socket problem."""
    monkeypatch.setattr(
        "src.ibkr.market_data.qualify_stock_async",
        AsyncMock(return_value=MagicMock(symbol="SPY")),
    )
    ib = MagicMock()
    ib.reqMktData.return_value = _StockTicker(price=float("nan"), close=0.0)
    listeners = []
    ib.errorEvent.__iadd__.side_effect = lambda fn: listeners.append(fn) or ib.errorEvent
    ib.errorEvent.__isub__.side_effect = lambda fn: listeners.remove(fn) or ib.errorEvent

    def _emit_354(contract, **kwargs):
        for fn in listeners:
            fn(4, 354, "Requested market data is not subscribed", contract)
        return _StockTicker(price=float("nan"), close=0.0)

    ib.reqMktData.side_effect = _emit_354
    probe = await probe_market_data_health(ib, timeout=0.05)
    assert probe.healthy is False
    assert probe.error_codes == [354]
    assert "subscription" in probe.diagnosis
    assert listeners == []


@pytest.mark.asyncio
async def test_probe_diagnoses_connectivity_flap(monkeypatch):
    """1102 (connectivity restored) during the window means the link is being rebuilt —
    the hint should say transient, not tell the operator to restart things."""
    monkeypatch.setattr(
        "src.ibkr.market_data.qualify_stock_async",
        AsyncMock(return_value=MagicMock(symbol="SPY")),
    )
    ib = MagicMock()
    ib.reqMktData.return_value = _StockTicker(price=float("nan"), close=0.0)
    listeners = []
    ib.errorEvent.__iadd__.side_effect = lambda fn: listeners.append(fn) or ib.errorEvent
    ib.errorEvent.__isub__.side_effect = lambda fn: listeners.remove(fn) or ib.errorEvent

    def _emit_1102(contract, **kwargs):
        for fn in listeners:
            fn(-1, 1102, "Connectivity between IBKR and TWS has been restored", contract)
        return _StockTicker(price=float("nan"), close=0.0)

    ib.reqMktData.side_effect = _emit_1102
    probe = await probe_market_data_health(ib, timeout=0.05)
    assert probe.healthy is False
    assert probe.error_codes == [1102]
    assert "flapping" in probe.diagnosis
    assert "transient" in probe.action_hint
    assert listeners == []


@pytest.mark.asyncio
async def test_probe_diagnoses_hung_qualify_with_codes(monkeypatch):
    """A half-dead socket can hang qualify itself — the probe stays bounded, returns
    unhealthy, and still reports any codes the socket managed to emit."""
    monkeypatch.setattr(
        "src.ibkr.market_data.qualify_stock_async",
        AsyncMock(side_effect=TimeoutError()),
    )
    ib = MagicMock()
    listeners = []
    ib.errorEvent.__iadd__.side_effect = lambda fn: listeners.append(fn) or ib.errorEvent
    ib.errorEvent.__isub__.side_effect = lambda fn: listeners.remove(fn) or ib.errorEvent

    probe = await probe_market_data_health(ib, timeout=0.1)
    assert probe.healthy is False
    assert "qualify" in probe.diagnosis
    assert probe.action_hint
    assert listeners == []


@pytest.mark.asyncio
async def test_probe_unhealthy_when_qualify_hangs(monkeypatch):
    """A half-dead socket can hang qualify itself — the probe stays bounded and returns False."""
    import asyncio

    async def _hangs(ib, symbol):
        await asyncio.sleep(3600)

    monkeypatch.setattr("src.ibkr.market_data.qualify_stock_async", _hangs)
    ib = MagicMock()

    probe = await asyncio.wait_for(probe_market_data_health(ib, timeout=0.1), timeout=2.0)
    assert probe.healthy is False


# ---------------------------------------------------------------------------
# _select_chain — standard chain vs. IBKR's post-corporate-action adjusted class
# ---------------------------------------------------------------------------


def _chain(tc: str, exps: set[str], strikes: set[float], exchange: str = "SMART"):
    return SimpleNamespace(exchange=exchange, tradingClass=tc, expirations=exps, strikes=strikes)


def test_select_chain_prefers_standard_class_over_adjusted_regardless_of_order():
    adjusted = _chain("2AMD", {"20261002"}, {443.0})
    standard = _chain("AMD", {"20261009", "20261016"}, {600.0, 630.0, 660.0})
    assert _select_chain([adjusted, standard], "AMD") is standard
    assert _select_chain([standard, adjusted], "AMD") is standard


def test_select_chain_prefers_smart_among_same_class():
    cboe = _chain("AMD", {"20261009"}, {600.0}, exchange="CBOE")
    smart = _chain("AMD", {"20261009"}, {600.0})
    assert _select_chain([cboe, smart], "AMD") is smart


def test_select_chain_falls_back_to_richest_chain_when_no_class_matches():
    thin = _chain("XYZ1", {"20261002"}, {10.0})
    rich = _chain("XYZ2", {"20261009", "20261016"}, {10.0, 11.0})
    assert _select_chain([thin, rich], "ABC") is rich


def test_select_chain_none_when_nothing_has_expirations():
    assert _select_chain([_chain("AMD", set(), set())], "AMD") is None


def test_build_chain_contracts_sets_trading_class():
    exp = (date.today() + timedelta(days=14)).strftime("%Y%m%d")
    contracts = _build_chain_contracts("AMD", [exp], [600.0, 660.0], 630.0, trading_class="AMD")
    assert contracts and all(c.tradingClass == "AMD" for c in contracts)


# ---------------------------------------------------------------------------
# req_fresh_mkt_data — ib_async keeps one Ticker per contract across cancel/re-subscribe
# (2026-09-30: scan quotes 15-30 min stale, every approved order rejected at send time)
# ---------------------------------------------------------------------------


def _offline_ib():
    """A real ib_async IB whose client never touches a socket — so the real wrapper's
    ticker cache (the thing under test) is exercised, not a MagicMock stand-in."""
    import itertools

    from ib_async import IB

    ib = IB()
    ib.client.reqMktData = MagicMock()
    ib.client.cancelMktData = MagicMock()
    ids = itertools.count(1)
    ib.client.getReqId = lambda: next(ids)
    return ib


def _stock_contract(con_id: int = 1):
    from ib_async import Stock

    c = Stock("XYZ", "SMART", "USD")
    c.conId = con_id
    return c


def test_plain_reqmktdata_reuses_the_stale_ticker():
    """Documents the ib_async behaviour the helper exists for — if this ever starts failing,
    the library changed and req_fresh_mkt_data may no longer be needed."""
    ib = _offline_ib()
    c = _stock_contract()
    first = ib.reqMktData(c)
    first.bid = 1.23
    ib.cancelMktData(c)
    again = ib.reqMktData(c)
    assert again is first and again.bid == 1.23


def test_req_fresh_mkt_data_starts_empty_after_a_cancelled_subscription():
    from src.ibkr.market_data import req_fresh_mkt_data

    ib = _offline_ib()
    c = _stock_contract()
    first = req_fresh_mkt_data(ib, c)
    first.bid = 1.23
    first.ask = 1.30
    ib.cancelMktData(c)

    again = req_fresh_mkt_data(ib, c)
    assert again is not first
    assert _safe(again.bid) is None and _safe(again.ask) is None
    # And it is the ticker ib_async now routes ticks + cancels to.
    assert ib.ticker(c) is again
    assert ib.cancelMktData(c) is True


def test_req_fresh_mkt_data_leaves_an_active_subscription_alone():
    """A still-streaming ticker is current, and replacing it would orphan its line
    (cancelMktData resolves the ticker by contract hash)."""
    from src.ibkr.market_data import req_fresh_mkt_data

    ib = _offline_ib()
    c = _stock_contract()
    live = ib.reqMktData(c)
    live.bid = 1.23
    assert req_fresh_mkt_data(ib, c) is live


def test_quote_ready_is_false_on_a_resubscribed_contract_until_new_ticks_arrive():
    from src.ibkr.market_data import _open_line

    ib = _offline_ib()
    c = _stock_contract()
    t = _open_line(ib, c)
    t.bid, t.ask, t.putOpenInterest = 1.0, 1.1, 500.0
    _close_line(ib, c)

    t2 = _open_line(ib, c)
    assert not _quote_ready(t2, right="P")


# ---------------------------------------------------------------------------
# Black-Scholes fill spot — live underlying, never the cached prior close
# ---------------------------------------------------------------------------


def test_ticker_to_quote_captures_ibkr_underlying_price():
    g = SimpleNamespace(
        impliedVol=0.6, delta=-0.2, gamma=0.01, theta=-0.02, vega=0.05, undPrice=79.2
    )
    q = _ticker_to_quote(_make_option_contract(right="P"), _make_ticker(greeks=g))
    assert q.underlying_price == pytest.approx(79.2)


async def test_bs_fill_spot_prefers_ibkr_underlying_price_over_cached_close():
    quotes = [
        OptionQuote(
            underlying="TQQQ",
            right=OptionRight.PUT,
            strike=k,
            expiry=date(2026, 10, 9),
            underlying_price=p,
        )
        for k, p in ((70.0, 79.1), (72.0, 79.3), (74.0, None))
    ]
    ib = MagicMock()
    spot = await _bs_fill_spot_async(ib, MagicMock(), quotes, fallback=77.46)
    assert spot == pytest.approx(79.2)


async def test_bs_fill_spot_takes_a_live_snapshot_when_no_underlying_price(monkeypatch):
    import src.ibkr.market_data as md

    monkeypatch.setattr(md, "_get_spot_async", AsyncMock(return_value=11.805))
    quotes = [
        OptionQuote(
            underlying="MARA", right=OptionRight.CALL, strike=13.5, expiry=date(2026, 10, 9)
        )
    ]
    assert await _bs_fill_spot_async(MagicMock(), MagicMock(), quotes, fallback=11.99) == 11.805


async def test_bs_fill_spot_falls_back_to_cached_close_when_snapshot_fails(monkeypatch):
    import src.ibkr.market_data as md

    monkeypatch.setattr(md, "_get_spot_async", AsyncMock(side_effect=ValueError("no tick")))
    quotes = [
        OptionQuote(
            underlying="MARA", right=OptionRight.CALL, strike=13.5, expiry=date(2026, 10, 9)
        )
    ]
    assert await _bs_fill_spot_async(MagicMock(), MagicMock(), quotes, fallback=11.99) == 11.99
