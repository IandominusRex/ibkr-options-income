"""Unit tests for the analytics layer. No TWS, no live yfinance calls."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.analytics.black_scholes import bs_delta
from src.analytics.fundamentals import get_fundamental_stats
from src.analytics.iv import get_iv_stats
from src.analytics.liquidity import passes_liquidity_gates, score_liquidity
from src.analytics.technicals import get_technical_stats
from src.common.market_hours import today_et
from src.common.schemas import AccountSnapshot, OptionQuote, OptionRight, Regime
from src.engine.capital import Budgets

# --------------------------------------------------------------------------- #
# iv.py tests
# --------------------------------------------------------------------------- #


def _make_iv_history(values: list[float]) -> list:
    """Build mock IVHistoryRow-like scalars for session_scope monkeypatch."""
    return values


def _mock_session_scope(values: list[float]):
    """Context manager that makes session_scope return *values* as scalars."""

    @contextmanager
    def _scope():
        sess = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = values
        sess.execute.return_value = result
        yield sess

    return _scope


class TestIVStats:
    @pytest.fixture(autouse=True)
    def _no_realized_vol_network(self):
        """Suppress compute_realized_vol network calls in all TestIVStats tests."""
        with patch("src.analytics.iv.compute_realized_vol", return_value=None):
            yield

    def test_iv_rank_formula(self):
        # history: [0.30, 0.25, 0.20, 0.15, 0.10] — current=0.30, min=0.10, max=0.30
        history = [0.30, 0.25, 0.20, 0.15, 0.10]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
        ):
            stats = get_iv_stats("TEST")
        # iv_rank = (0.30 - 0.10) / (0.30 - 0.10) * 100 = 100.0
        assert stats.iv_rank == 100.0

    def test_iv_rank_middle(self):
        # current=0.20, min=0.10, max=0.30 → rank = 50
        history = [0.20, 0.30, 0.10]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
        ):
            stats = get_iv_stats("TEST")
        assert stats.iv_rank == 50.0

    def test_iv_percentile_requires_30_observations(self):
        # P1-17: fewer than 30 observations → iv_percentile must be None.
        # With 5 obs it moves in 20-point steps and isn't actionable.
        history = [0.30, 0.25, 0.20, 0.15, 0.10]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
        ):
            stats = get_iv_stats("TEST")
        assert stats.iv_percentile is None

    def test_iv_percentile_formula_with_sufficient_history(self):
        # With >= 30 observations, percentile should be computed correctly.
        # All 30 observations at 0.25, one at 0.30 (current) → 30/31 * 100 ≈ 96.77
        history = [0.30] + [0.25] * 30  # 31 observations, current=0.30
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
        ):
            stats = get_iv_stats("TEST")
        assert stats.iv_percentile is not None
        assert stats.iv_percentile == pytest.approx(30 / 31 * 100, abs=0.1)

    def test_flat_vol_curve_returns_none_rank(self):
        # All values identical → iv_rank must be None (no division by zero)
        history = [0.25, 0.25, 0.25, 0.25]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
        ):
            stats = get_iv_stats("TEST")
        assert stats.iv_rank is None

    def test_empty_history_returns_bare_ivstats(self):
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope([])),
            patch("src.analytics.iv._compute_hv30", return_value=None),
        ):
            stats = get_iv_stats("EMPTY")
        assert stats.symbol == "EMPTY"
        assert stats.iv_rank is None
        assert stats.current_iv is None

    def test_hv30_populated(self):
        history = [0.25, 0.20, 0.15]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=18.5),
        ):
            stats = get_iv_stats("TEST")
        assert stats.hv_30 == 18.5


class TestLiveATMIVInterpolation:
    """`IVStats.current_iv` computed from real quotes, end to end — no monkeypatched IV.

    This one number is the most load-bearing on the deterministic path: it sizes positions
    and seeds the concentration caps (`engine.capital.risk_units`), sets the variance-risk-
    premium floor (`fair_value.compute_ideal_zone` -> `IdealZone.min_credit`), and forms the
    `iv_rv_ratio` gate. Every other `get_iv_stats` test omits `quotes`, and the scan-pipeline
    tests monkeypatch `get_iv_stats` wholesale, so `_atm_iv_at_30d`'s constant-maturity
    interpolation had no test exercising it with a realistic multi-expiry chain.
    """

    @pytest.fixture(autouse=True)
    def _no_realized_vol_network(self):
        with patch("src.analytics.iv.compute_realized_vol", return_value=None):
            yield

    @staticmethod
    def _chain() -> list[OptionQuote]:
        """Three expiries straddling 30 DTE around a $100 spot, with DISTINCT IV per expiry.

        Mids are set so put-call parity recovers spot = 100 exactly at every strike
        (`call_mid - put_mid == 100 - strike`), which is how `infer_spot_from_quotes` finds
        the ATM band. IV is flat within an expiry so the ATM average is exactly that expiry's
        IV, and the three expiries differ (40% / 60% / 80%) so a broken interpolation — taking
        the nearest expiry, or averaging all of them — lands on a different number.
        """
        quotes: list[OptionQuote] = []
        for days, iv in ((21, 0.40), (45, 0.60), (60, 0.80)):
            expiry = today_et() + timedelta(days=days)
            for strike in (90.0, 95.0, 100.0, 105.0, 110.0):
                call_mid = max(0.0, 100.0 - strike) + 2.0
                put_mid = max(0.0, strike - 100.0) + 2.0
                for right, mid in ((OptionRight.CALL, call_mid), (OptionRight.PUT, put_mid)):
                    quotes.append(
                        OptionQuote(
                            underlying="TEST",
                            right=right,
                            strike=strike,
                            expiry=expiry,
                            bid=mid - 0.05,
                            ask=mid + 0.05,
                            iv=iv,
                            volume=250,
                            open_interest=1_000,
                        )
                    )
        return quotes

    def test_current_iv_is_interpolated_to_a_constant_30_day_maturity(self):
        history = [0.30, 0.25, 0.20, 0.15, 0.10]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
        ):
            stats = get_iv_stats("TEST", self._chain())

        # 30 DTE sits between the 21d (40%) and 45d (60%) expiries:
        # 40 + (30-21)/(45-21) x (60-40) = 47.5%. Not 40 (nearest expiry), not 60 (the mean
        # of all three), not the stored history's 30% (which the live value must override).
        assert stats.current_iv == pytest.approx(47.5, abs=0.25)
        # The live value, not the last stored observation, is what ranks.
        assert stats.iv_rank == 100.0

    def test_the_interpolated_iv_produces_a_sane_position_size(self):
        """The same number, consumed by the deterministic sizer it actually feeds."""
        from src.engine.capital import max_contracts, resolve_caps, risk_units

        history = [0.30, 0.25, 0.20, 0.15, 0.10]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
        ):
            stats = get_iv_stats("TEST", self._chain())

        assert stats.current_iv is not None
        # $9,000 of collateral (90 strike x 100) at ~47.5% IV over 30 days.
        units = risk_units(9_000.0, stats.current_iv, 30)
        assert units == pytest.approx(9_000.0 * 0.475 * (30 / 365) ** 0.5, rel=0.01)

        risk = {
            "portfolio": {
                "cash_reserve_pct": 20.0,
                "cash_reserve_absolute": 10_000,
                "max_csp_allocation_pct_of_deployable": 100.0,
                "max_risk_units_per_ticker_pct": 5.0,
                "max_risk_units_per_sector_pct": 25.0,
                "max_collateral_per_ticker_pct": 10.0,
                "max_large_positions": 1,
                "max_pct_per_ticker_large": 25.0,
            }
        }
        account = AccountSnapshot(
            account="DU1",
            net_liquidation=300_000.0,
            total_cash=100_000.0,
            buying_power=100_000.0,
            maintenance_margin=0.0,
            excess_liquidity=100_000.0,
        )
        n, _binding = max_contracts(
            unit_collateral=9_000.0,
            current_iv=stats.current_iv,
            dte=30,
            symbol="TEST",
            sector="tech",
            caps=resolve_caps(account, risk),
            budgets=Budgets(),
            hard_max=10,
        )
        # 15,000 risk-unit cap / ~1,225 units per lot -> a real, bounded, non-zero size.
        assert n >= 1
        assert n * units <= 15_000.0


class TestHV30LogReturns:
    """P1-16: _compute_hv30 must use log returns, not simple pct_change returns."""

    def test_hv_matches_manual_log_return_calculation(self):
        """The function output must equal the manually computed log-return HV.

        We build a known price series and verify that _compute_hv30 returns the
        same value as the reference computation using log returns.
        """
        import math

        import numpy as np

        from src.analytics.iv import _compute_hv30

        # Build a 60-bar series with some known moves so the 30-bar rolling vol is non-zero.
        rng = np.random.default_rng(42)
        log_rets = rng.normal(0.0005, 0.02, 60)  # daily log returns, annualised ~32%
        prices = [100.0]
        for r in log_rets:
            prices.append(prices[-1] * math.exp(r))

        df_data = pd.DataFrame({"Close": prices[:-1]})  # 60 rows
        df_data.index = pd.date_range("2023-01-01", periods=60, freq="B")

        with patch("src.analytics.iv.get_ohlcv", return_value=df_data):
            hv = _compute_hv30("TEST")

        assert hv is not None
        assert hv > 0

        # Reference: compute log returns as the implementation does, then take the
        # last rolling(30) std (pandas default ddof=1), annualise.
        closes = np.array(df_data["Close"])
        log_ret_series = np.log(closes[1:] / closes[:-1])  # 59 returns
        last_30 = log_ret_series[-30:]  # rolling window at the last position
        expected_hv = float(np.std(last_30, ddof=1) * math.sqrt(252) * 100)
        assert hv == pytest.approx(expected_hv, rel=0.05)

    def test_hv_returns_none_when_insufficient_data(self):
        from src.analytics.iv import _compute_hv30

        df_data = pd.DataFrame({"Close": [100.0, 101.0]})
        df_data.index = pd.date_range("2023-01-01", periods=2, freq="B")

        with patch("src.analytics.iv.get_ohlcv", return_value=df_data):
            hv = _compute_hv30("TEST")
        assert hv is None


# --------------------------------------------------------------------------- #
# technicals.py tests
# --------------------------------------------------------------------------- #


def _make_ohlcv(n: int = 260, seed: int = 42) -> pd.DataFrame:
    """Deterministic OHLCV DataFrame of length *n*."""
    rng = np.random.default_rng(seed)
    prices = 100.0 + np.cumsum(rng.normal(0, 1, n))
    prices = np.clip(prices, 1, None)
    high = prices + rng.uniform(0.5, 2.0, n)
    low = prices - rng.uniform(0.5, 2.0, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"Close": prices, "High": high, "Low": low, "Open": prices}, index=idx)


class TestTechnicalStats:
    def _patched(self, df: pd.DataFrame, last_price: float | None = None):
        return patch.multiple(
            "src.analytics.technicals",
            get_ohlcv=MagicMock(return_value=df),
            _fetch_last_price=MagicMock(return_value=last_price),
        )

    def test_empty_df_returns_zero_price(self):
        with self._patched(pd.DataFrame()):
            stats = get_technical_stats("EMPTY")
        assert stats.price == 0.0
        assert stats.rsi_14 is None

    def test_empty_df_falls_back_to_live_price(self):
        with self._patched(pd.DataFrame(), last_price=42.5):
            stats = get_technical_stats("EMPTY")
        assert stats.price == 42.5

    def test_all_fields_populated_with_good_data(self):
        df = _make_ohlcv(260)
        with self._patched(df):
            stats = get_technical_stats("TEST")
        assert stats.price > 0
        assert stats.rsi_14 is not None
        assert 0 < stats.rsi_14 < 100
        assert stats.atr_14 is not None and stats.atr_14 > 0
        assert stats.macd is not None
        assert stats.sma_50 is not None
        assert stats.sma_200 is not None
        assert stats.regime is not None

    def test_live_price_overrides_cached_history_close(self):
        """price comes from _fetch_last_price even when the 1y history is a (cached) hit."""
        df = _make_ohlcv(260)
        with self._patched(df, last_price=999.0):
            stats = get_technical_stats("TEST")
        assert stats.price == 999.0

    def test_live_price_fetch_failure_falls_back_to_history_close(self):
        df = _make_ohlcv(260)
        with self._patched(df, last_price=None):
            stats = get_technical_stats("TEST")
        assert stats.price == float(df["Close"].iloc[-1])

    def test_fetch_last_price_reads_fast_info(self):
        from src.analytics.technicals import _fetch_last_price

        ticker = MagicMock()
        ticker.fast_info = {"lastPrice": 123.45}
        with patch("src.analytics.technicals.yf.Ticker", return_value=ticker):
            assert _fetch_last_price("AAPL") == 123.45

    def test_fetch_last_price_returns_none_on_error(self):
        from src.analytics.technicals import _fetch_last_price

        with patch("src.analytics.technicals.yf.Ticker", side_effect=Exception("network")):
            assert _fetch_last_price("AAPL") is None

    def test_regime_high_vol(self):
        """Force ATR ratio > 2.5% to trigger HIGH_VOL."""
        df = _make_ohlcv(260)
        # Inflate ATR by making each candle ~5% swing
        df["High"] = df["Close"] * 1.04
        df["Low"] = df["Close"] * 0.96
        with self._patched(df):
            stats = get_technical_stats("TEST")
        assert stats.regime == Regime.HIGH_VOL

    def test_regime_low_vol(self):
        """Very tight candles → LOW_VOL (unless other conditions dominate)."""
        df = _make_ohlcv(260)
        df["High"] = df["Close"] * 1.002
        df["Low"] = df["Close"] * 0.998
        with self._patched(df):
            stats = get_technical_stats("TEST")
        # ATR/close will be very small; regime should NOT be HIGH_VOL
        assert stats.regime != Regime.HIGH_VOL

    def test_regime_bullish(self):
        """Trending up: price > sma50 > sma200 and high RSI."""
        # Build a strongly upward-trending series
        n = 260
        prices = np.linspace(50, 150, n)
        high = prices + 0.3
        low = prices - 0.3
        idx = pd.date_range("2023-01-01", periods=n, freq="B")
        df = pd.DataFrame({"Close": prices, "High": high, "Low": low, "Open": prices}, index=idx)
        with self._patched(df):
            stats = get_technical_stats("TEST")
        assert stats.regime == Regime.BULLISH

    def test_regime_bearish(self):
        """Trending down: price < sma50 < sma200 and low RSI."""
        n = 260
        prices = np.linspace(150, 50, n)
        high = prices + 0.3
        low = prices - 0.3
        idx = pd.date_range("2023-01-01", periods=n, freq="B")
        df = pd.DataFrame({"Close": prices, "High": high, "Low": low, "Open": prices}, index=idx)
        with self._patched(df):
            stats = get_technical_stats("TEST")
        assert stats.regime == Regime.BEARISH


# --------------------------------------------------------------------------- #
# fundamentals.py tests
# --------------------------------------------------------------------------- #


def _mock_ticker(info: dict, calendar: dict | None = None):
    t = MagicMock()
    t.info = info
    t.calendar = calendar or {}
    return t


class TestFundamentalStats:
    def test_etf_shortcut(self):
        ticker = _mock_ticker({"quoteType": "ETF"})
        with patch("src.analytics.fundamentals.yf.Ticker", return_value=ticker):
            stats = get_fundamental_stats("SPY")
        assert stats.quality_flag is True
        assert stats.pe_ratio is None

    def test_quality_flag_true(self):
        info = {
            "quoteType": "EQUITY",
            "trailingPE": 15.0,
            "freeCashflow": 5_000_000,
            "debtToEquity": 50.0,
            "dividendYield": 0.02,
            "payoutRatio": 0.30,
        }
        ticker = _mock_ticker(info)
        with patch("src.analytics.fundamentals.yf.Ticker", return_value=ticker):
            stats = get_fundamental_stats("AAPL")
        assert stats.quality_flag is True
        assert stats.dividend_safe is True

    def test_quality_flag_false_negative_fcf(self):
        info = {
            "quoteType": "EQUITY",
            "trailingPE": 15.0,
            "freeCashflow": -1_000_000,
            "debtToEquity": 50.0,
        }
        ticker = _mock_ticker(info)
        with patch("src.analytics.fundamentals.yf.Ticker", return_value=ticker):
            stats = get_fundamental_stats("BAD")
        assert stats.quality_flag is False

    def test_missing_fields_do_not_raise(self):
        ticker = _mock_ticker({"quoteType": "EQUITY"})
        with patch("src.analytics.fundamentals.yf.Ticker", return_value=ticker):
            stats = get_fundamental_stats("SPARSE")
        assert stats.symbol == "SPARSE"
        assert stats.pe_ratio is None
        assert stats.quality_flag is None

    def test_yfinance_exception_returns_bare_stats(self):
        with patch("src.analytics.fundamentals.yf.Ticker", side_effect=Exception("network")):
            stats = get_fundamental_stats("ERR")
        assert stats.symbol == "ERR"
        assert stats.pe_ratio is None

    def test_next_earnings_future_date(self):
        future = pd.Timestamp("2030-12-31")
        ticker = _mock_ticker(
            {"quoteType": "EQUITY"},
            calendar={"Earnings Date": [future]},
        )
        with patch("src.analytics.fundamentals.yf.Ticker", return_value=ticker):
            stats = get_fundamental_stats("AAPL")
        assert stats.next_earnings == date(2030, 12, 31)


# --------------------------------------------------------------------------- #
# liquidity.py tests
# --------------------------------------------------------------------------- #


def _quote(
    spread_pct: float | None = 5.0,
    open_interest: int | None = 500,
    volume: int | None = 50,
) -> OptionQuote:
    """Build a minimal OptionQuote for liquidity tests."""
    bid = 1.0
    # Back-calculate ask from bid and desired spread_pct
    if spread_pct is not None:
        # spread_pct = (ask-bid)/mid * 100, mid = (ask+bid)/2
        # ask = bid * (200 + spread_pct) / (200 - spread_pct)
        ask = bid * (200 + spread_pct) / (200 - spread_pct) if spread_pct < 200 else bid * 3
    else:
        ask = None  # type: ignore[assignment]

    return OptionQuote(
        underlying="TEST",
        right=OptionRight.CALL,
        strike=100.0,
        expiry=date(2025, 12, 19),
        bid=bid,
        ask=ask,
        volume=volume,
        open_interest=open_interest,
        iv=0.25,
        delta=0.30,
    )


class TestLiquidity:
    def test_passes_all_gates(self):
        q = _quote(spread_pct=5.0, open_interest=500, volume=50)
        assert passes_liquidity_gates(q) is True

    def test_fails_spread_gate(self):
        q = _quote(spread_pct=15.0, open_interest=500, volume=50)
        assert passes_liquidity_gates(q) is False

    def test_fails_oi_gate(self):
        q = _quote(spread_pct=5.0, open_interest=10, volume=50)
        assert passes_liquidity_gates(q) is False

    def test_fails_volume_gate(self):
        q = _quote(spread_pct=5.0, open_interest=500, volume=2)
        assert passes_liquidity_gates(q) is False

    def test_volume_gate_skipped_when_not_enforced(self):
        # N19: before the morning cutoff the volume gate is skipped; OI + spread still apply.
        q = _quote(spread_pct=5.0, open_interest=500, volume=2)  # volume below min
        assert passes_liquidity_gates(q, enforce_volume=False) is True
        thin = _quote(spread_pct=5.0, open_interest=10, volume=2)  # OI still fails
        assert passes_liquidity_gates(thin, enforce_volume=False) is False

    def test_volume_gate_active_is_time_aware(self):
        from datetime import time

        from src.analytics.liquidity import volume_gate_active

        # Default cutoff is 10:30 ET (config); before it the gate is inactive, after it active.
        assert volume_gate_active(time(9, 45)) is False
        assert volume_gate_active(time(11, 0)) is True

    def test_none_spread_fails_gate(self):
        q = OptionQuote(
            underlying="TEST",
            right=OptionRight.CALL,
            strike=100.0,
            expiry=date(2025, 12, 19),
            bid=None,
            ask=None,
            volume=100,
            open_interest=1000,
        )
        assert passes_liquidity_gates(q) is False

    def test_perfect_score(self):
        # spread=0% means ask==bid → spread_pct=0, OI=5000, vol=500
        # With log-scale scoring, OI=5000 is high but not capped at 100 (needs OI~1M for 100).
        # vol=500 is above the natural log-cap so vol_score=100. spread_score=100.
        # Overall: avg ≥ 90 for these liquid parameters.
        q = OptionQuote(
            underlying="TEST",
            right=OptionRight.CALL,
            strike=100.0,
            expiry=date(2025, 12, 19),
            bid=1.0,
            ask=1.0,  # spread_pct = 0
            volume=500,
            open_interest=5000,
        )
        score = score_liquidity(q)
        assert score >= 90.0  # high liquidity → high score (log-scale, not necessarily 100)

    def test_score_penalises_wide_spread(self):
        narrow = _quote(spread_pct=1.0, open_interest=1000, volume=100)
        wide = _quote(spread_pct=9.0, open_interest=1000, volume=100)
        assert score_liquidity(narrow) > score_liquidity(wide)

    def test_score_none_oi_penalised(self):
        good = _quote(spread_pct=5.0, open_interest=500, volume=50)
        bad = _quote(spread_pct=5.0, open_interest=None, volume=50)
        assert score_liquidity(good) > score_liquidity(bad)


# --------------------------------------------------------------------------- #
# black_scholes.py — bs_delta tests
# --------------------------------------------------------------------------- #


class TestBsDelta:
    def test_atm_call_near_half(self):
        # ATM call (spot == strike) should have delta close to 0.5
        d = bs_delta(spot=100.0, strike=100.0, dte=30, iv=0.30, right="C")
        assert d is not None
        assert 0.45 <= d <= 0.60

    def test_atm_put_near_neg_half(self):
        d = bs_delta(spot=100.0, strike=100.0, dte=30, iv=0.30, right="P")
        assert d is not None
        assert -0.60 <= d <= -0.40

    def test_deep_itm_call_near_one(self):
        d = bs_delta(spot=150.0, strike=100.0, dte=30, iv=0.30, right="C")
        assert d is not None
        assert d > 0.90

    def test_deep_otm_put_near_zero(self):
        d = bs_delta(spot=150.0, strike=100.0, dte=30, iv=0.30, right="P")
        assert d is not None
        assert -0.10 <= d <= 0.0

    def test_call_put_delta_sum_is_one(self):
        # For European options: call_delta - put_delta = 1 (put-call parity on delta)
        c = bs_delta(spot=100.0, strike=105.0, dte=45, iv=0.25, right="C")
        p = bs_delta(spot=100.0, strike=105.0, dte=45, iv=0.25, right="P")
        assert c is not None and p is not None
        assert abs((c - p) - 1.0) < 1e-6

    def test_degenerate_zero_spot_returns_none(self):
        assert bs_delta(spot=0.0, strike=100.0, dte=30, iv=0.30, right="C") is None

    def test_degenerate_zero_dte_returns_none(self):
        assert bs_delta(spot=100.0, strike=100.0, dte=0, iv=0.30, right="C") is None

    def test_degenerate_zero_iv_returns_none(self):
        assert bs_delta(spot=100.0, strike=100.0, dte=30, iv=0.0, right="C") is None

    def test_degenerate_negative_strike_returns_none(self):
        assert bs_delta(spot=100.0, strike=-1.0, dte=30, iv=0.30, right="C") is None


class TestDailyCaching:
    def test_fundamentals_cached_per_day(self):
        ticker = MagicMock()
        ticker.info = {"quoteType": "ETF"}
        with patch("src.analytics.fundamentals.yf.Ticker", return_value=ticker) as mk:
            get_fundamental_stats("ZZZ")
            get_fundamental_stats("ZZZ")
        # Second call served from the daily cache — yfinance hit only once.
        assert mk.call_count == 1

    # HV30 and the technical OHLCV history now share the incremental price_data.get_ohlcv
    # loader (itself @daily_cached and backed by the price_history store). Its caching /
    # tail-fetch behaviour is covered directly in tests/test_price_data.py.


# --------------------------------------------------------------------------- #
# C1: realized_vol.py — compute_realized_vol
# --------------------------------------------------------------------------- #


class TestComputeRealizedVol:
    """Unit tests for the standalone realized-vol helper (C1)."""

    def _price_df(self, n: int = 60, drift: float = 0.0, vol: float = 0.02) -> pd.DataFrame:
        """Build a deterministic log-normal price series."""
        import math

        rng = np.random.default_rng(7)
        log_rets = rng.normal(drift, vol, n)
        prices = [100.0]
        for r in log_rets:
            prices.append(prices[-1] * math.exp(r))
        df = pd.DataFrame({"Close": prices[:-1]})
        df.index = pd.date_range("2024-01-01", periods=n, freq="B")
        return df

    def test_returns_float_with_sufficient_history(self):
        from src.analytics.realized_vol import compute_realized_vol

        df = self._price_df(60)
        with patch("src.analytics.realized_vol.get_ohlcv", return_value=df):
            rv = compute_realized_vol("TEST", window=20)
        assert rv is not None
        assert rv > 0

    def test_matches_manual_log_return_calculation(self):
        import math

        from src.analytics.realized_vol import compute_realized_vol

        df = self._price_df(60)
        with patch("src.analytics.realized_vol.get_ohlcv", return_value=df):
            rv = compute_realized_vol("TEST", window=20)

        closes = np.array(df["Close"])
        log_rets = np.log(closes[1:] / closes[:-1])
        expected = float(np.std(log_rets[-20:], ddof=1) * math.sqrt(252) * 100)
        assert rv == pytest.approx(expected, rel=0.01)

    def test_returns_none_when_insufficient_data(self):
        from src.analytics.realized_vol import compute_realized_vol

        df = pd.DataFrame({"Close": [100.0, 101.0]})
        with patch("src.analytics.realized_vol.get_ohlcv", return_value=df):
            rv = compute_realized_vol("TEST", window=20)
        assert rv is None

    def test_returns_none_on_empty_dataframe(self):
        from src.analytics.realized_vol import compute_realized_vol

        with patch("src.analytics.realized_vol.get_ohlcv", return_value=pd.DataFrame()):
            rv = compute_realized_vol("TEST", window=20)
        assert rv is None

    def test_returns_none_on_exception(self):
        from src.analytics.realized_vol import compute_realized_vol

        with patch("src.analytics.realized_vol.get_ohlcv", side_effect=Exception("network")):
            rv = compute_realized_vol("TEST", window=20)
        assert rv is None

    def test_configurable_window(self):
        from src.analytics.realized_vol import compute_realized_vol

        df = self._price_df(60)
        with patch("src.analytics.realized_vol.get_ohlcv", return_value=df):
            rv20 = compute_realized_vol("TEST", window=20)
            rv30 = compute_realized_vol("TEST", window=30)
        # Different windows → generally different results (not guaranteed but very likely)
        assert rv20 is not None
        assert rv30 is not None


# --------------------------------------------------------------------------- #
# C1: iv_rv_ratio populated on IVStats
# --------------------------------------------------------------------------- #


class TestIVRVRatio:
    def test_iv_rv_ratio_populated_when_both_available(self):
        history = [0.30, 0.25, 0.20, 0.15, 0.10]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
            patch("src.analytics.iv.compute_realized_vol", return_value=25.0),
        ):
            stats = get_iv_stats("TEST")
        # current_iv = 0.30 → current_iv_pct = 30.0; realized_vol = 25.0
        assert stats.iv_rv_ratio == pytest.approx(30.0 / 25.0, rel=0.001)

    def test_iv_rv_ratio_none_when_realized_vol_unavailable(self):
        history = [0.30, 0.25, 0.20, 0.15, 0.10]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
            patch("src.analytics.iv.compute_realized_vol", return_value=None),
        ):
            stats = get_iv_stats("TEST")
        assert stats.iv_rv_ratio is None

    def test_iv_rv_ratio_none_when_realized_vol_zero(self):
        history = [0.30, 0.25, 0.20, 0.15, 0.10]
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope(history)),
            patch("src.analytics.iv._compute_hv30", return_value=None),
            patch("src.analytics.iv.compute_realized_vol", return_value=0.0),
        ):
            stats = get_iv_stats("TEST")
        assert stats.iv_rv_ratio is None

    def test_iv_rv_ratio_none_when_no_iv_history(self):
        with (
            patch("src.analytics.iv.session_scope", _mock_session_scope([])),
            patch("src.analytics.iv._compute_hv30", return_value=None),
            patch("src.analytics.iv.compute_realized_vol", return_value=25.0),
        ):
            stats = get_iv_stats("TEST")
        # Empty history → no current_iv → iv_rv_ratio must be None
        assert stats.iv_rv_ratio is None


# --------------------------------------------------------------------------- #
# D6: live IV rank must be measured at the same constant maturity as the
# stored iv_history series (~30 days), not at whatever DTE the chain scan
# happens to land on.
# --------------------------------------------------------------------------- #


def _atm_quotes(dte: int, iv: float) -> list[OptionQuote]:
    """Paired call/put OptionQuote list at two strikes bracketing a $100 spot.

    Strikes 95 and 105 each get a call and a put priced so put-call parity
    (strike + call_mid - put_mid) resolves to exactly 100.0 at both strikes,
    letting infer_spot_from_quotes recover the $100 spot deterministically
    from the median of two independent parity estimates.
    """
    expiry = today_et() + timedelta(days=dte)
    quotes: list[OptionQuote] = []
    for strike, call_mid, put_mid in ((95.0, 6.00, 1.00), (105.0, 1.00, 6.00)):
        quotes.append(
            OptionQuote(
                underlying="TEST",
                right=OptionRight.CALL,
                strike=strike,
                expiry=expiry,
                bid=call_mid,
                ask=call_mid,
                iv=iv,
            )
        )
        quotes.append(
            OptionQuote(
                underlying="TEST",
                right=OptionRight.PUT,
                strike=strike,
                expiry=expiry,
                bid=put_mid,
                ask=put_mid,
                iv=iv,
            )
        )
    return quotes


class TestAtmIvAt30d:
    def test_atm_iv_is_interpolated_to_30_days(self):
        """D6: history is a 30-day constant-maturity index; the live value must match it."""
        from src.analytics.iv import _atm_iv_at_30d

        # 21 DTE at 20% and 49 DTE at 30% -> linear in DTE, 30 days sits at ~23.2%
        quotes = _atm_quotes(dte=21, iv=0.20) + _atm_quotes(dte=49, iv=0.30)
        result = _atm_iv_at_30d(quotes)
        assert result == pytest.approx(0.2321, abs=0.005)

    def test_atm_iv_falls_back_to_nearest_expiry_with_one_expiry(self):
        from src.analytics.iv import _atm_iv_at_30d

        quotes = _atm_quotes(dte=21, iv=0.20)
        assert _atm_iv_at_30d(quotes) == pytest.approx(0.20, abs=0.001)

    def test_atm_iv_returns_none_without_usable_quotes(self):
        from src.analytics.iv import _atm_iv_at_30d

        assert _atm_iv_at_30d([]) is None
