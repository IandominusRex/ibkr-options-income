"""Phase 1 unit tests — market data layer. No TWS/Gateway required.

All ib_async calls are mocked. Tests verify:
  - Contract builders produce correct objects
  - Expiration/strike filtering respects DTE windows and band
  - _batch_quotes chunks correctly and cancels every line
  - Greeks/OI field mapping is correct
  - qualify_stock raises on failure; qualify_options drops unqualified contracts
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import OptionQuote, OptionRight
from src.ibkr.contracts import (
    build_option,
    build_stock,
    qualify_options,
    qualify_stock,
)
from src.ibkr.market_data import (
    _await_ready,
    _batch_quotes,
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
    _spot_ready,
    _ticker_to_quote,
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
# _strike_band_pct (N6) — IV-scaled band with per-symbol override
# ---------------------------------------------------------------------------


def test_strike_band_uses_per_symbol_override():
    from src.ibkr.market_data import _strike_band_pct

    # SOXL carries a 0.45 override in universe.yaml; it wins over the floor without touching IV.
    assert _strike_band_pct("SOXL", 30) == pytest.approx(0.45)


def test_strike_band_scales_with_iv(monkeypatch):
    import math

    from src.ibkr.market_data import _strike_band_pct

    # AAPL has no override → band scales with the stored IV (patched to 100%).
    monkeypatch.setattr("src.storage.iv_history.latest_iv", lambda _s: 1.0)
    band = _strike_band_pct("AAPL", 30)
    assert band == pytest.approx(max(0.15, 1.5 * 1.0 * math.sqrt(30 / 365)))
    assert band > 0.15  # high IV genuinely widens the band past the floor


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
        monkeypatch.setattr("src.ibkr.market_data.yf.Ticker", lambda _: (_ for _ in ()).throw(AssertionError("yf called")))
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

    def test_skips_quotes_with_existing_delta(self):
        q = self._quote(iv=0.30, delta=0.25)
        n = _enrich_greeks_from_ibkr_iv("AAPL", 200.0, [q])
        assert n == 0
        assert q.greeks_source == "ibkr"  # untouched

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
