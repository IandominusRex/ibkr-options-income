"""Unit tests for the analytics layer. No TWS, no live yfinance calls."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.analytics.fundamentals import get_fundamental_stats
from src.analytics.iv import get_iv_stats
from src.analytics.liquidity import passes_liquidity_gates, score_liquidity
from src.analytics.technicals import get_technical_stats
from src.common.schemas import OptionQuote, OptionRight, Regime

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

        with patch("src.analytics.iv.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = df_data
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

        with patch("src.analytics.iv.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = df_data
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
    def _patched(self, df: pd.DataFrame):
        return patch("src.analytics.technicals._fetch", return_value=df)

    def test_empty_df_returns_zero_price(self):
        with self._patched(pd.DataFrame()):
            stats = get_technical_stats("EMPTY")
        assert stats.price == 0.0
        assert stats.rsi_14 is None

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
