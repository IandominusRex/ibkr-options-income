"""Tests for src/strategies/buy_candidates.py — P0-09 coverage."""

from __future__ import annotations

from src.common.schemas import FundamentalStats, IVStats, Regime, TechnicalStats
from src.strategies.buy_candidates import (
    _fundamental_sub_score,
    _iv_sub_score,
    _technical_sub_score,
    generate_buy_candidates,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _iv(rank: float | None = 60.0) -> IVStats:
    return IVStats(symbol="TEST", iv_rank=rank)


def _tech(regime: Regime | None = Regime.BULLISH) -> TechnicalStats:
    return TechnicalStats(symbol="TEST", price=100.0, regime=regime)


def _fund(
    quality_flag: bool | None = True,
    dividend_safe: bool | None = True,
) -> FundamentalStats:
    return FundamentalStats(symbol="TEST", quality_flag=quality_flag, dividend_safe=dividend_safe)


# ---------------------------------------------------------------------------
# Sub-score unit tests
# ---------------------------------------------------------------------------


class TestIVSubScore:
    def test_known_rank_returned_directly(self):
        assert _iv_sub_score(_iv(rank=75.0)) == 75.0

    def test_none_rank_returns_neutral(self):
        assert _iv_sub_score(_iv(rank=None)) == 40.0

    def test_zero_rank(self):
        assert _iv_sub_score(_iv(rank=0.0)) == 0.0

    def test_full_rank(self):
        assert _iv_sub_score(_iv(rank=100.0)) == 100.0


class TestFundamentalSubScore:
    def test_quality_true_dividend_safe(self):
        score = _fundamental_sub_score(_fund(quality_flag=True, dividend_safe=True))
        assert score == min(100.0, 70.0 + 20.0)

    def test_quality_true_dividend_unsafe(self):
        score = _fundamental_sub_score(_fund(quality_flag=True, dividend_safe=False))
        assert score == max(0.0, 70.0 - 10.0)

    def test_quality_false(self):
        score = _fundamental_sub_score(_fund(quality_flag=False, dividend_safe=None))
        assert score == 20.0

    def test_quality_unknown(self):
        score = _fundamental_sub_score(_fund(quality_flag=None, dividend_safe=None))
        assert score == 50.0

    def test_score_capped_at_100(self):
        score = _fundamental_sub_score(_fund(quality_flag=True, dividend_safe=True))
        assert score <= 100.0


class TestTechnicalSubScore:
    def test_bearish_is_low(self):
        assert _technical_sub_score(_tech(Regime.BEARISH)) == 10.0

    def test_bullish_is_high(self):
        assert _technical_sub_score(_tech(Regime.BULLISH)) == 80.0

    def test_sideways(self):
        assert _technical_sub_score(_tech(Regime.SIDEWAYS)) == 75.0

    def test_high_vol(self):
        assert _technical_sub_score(_tech(Regime.HIGH_VOL)) == 70.0

    def test_low_vol(self):
        assert _technical_sub_score(_tech(Regime.LOW_VOL)) == 40.0

    def test_none_regime_neutral(self):
        assert _technical_sub_score(_tech(regime=None)) == 50.0


# ---------------------------------------------------------------------------
# generate_buy_candidates integration
# ---------------------------------------------------------------------------


def _analytics(
    symbol: str = "AMD",
    iv_rank: float | None = 60.0,
    regime: Regime = Regime.BULLISH,
    quality: bool | None = True,
) -> dict:
    return {
        symbol: (
            IVStats(symbol=symbol, iv_rank=iv_rank),
            TechnicalStats(symbol=symbol, price=100.0, regime=regime),
            FundamentalStats(symbol=symbol, quality_flag=quality),
        )
    }


def test_generate_empty_universe():
    result = generate_buy_candidates([], set(), {})
    assert result == []


def test_generate_excludes_holdings():
    analytics = _analytics("AMD")
    result = generate_buy_candidates(["AMD"], {"AMD"}, analytics)
    assert result == []


def test_generate_excludes_bearish_regime():
    analytics = _analytics("AMD", regime=Regime.BEARISH)
    result = generate_buy_candidates(["AMD"], set(), analytics)
    assert result == []


def test_generate_excludes_missing_analytics():
    result = generate_buy_candidates(["AMD"], set(), {})
    assert result == []


def test_generate_returns_candidate_with_score():
    analytics = _analytics("AMD", iv_rank=80.0, regime=Regime.BULLISH, quality=True)
    result = generate_buy_candidates(["AMD"], set(), analytics)
    assert len(result) == 1
    assert result[0].symbol == "AMD"
    assert result[0].score > 0
    assert result[0].iv_rank == 80.0
    assert result[0].quality_flag is True
    assert result[0].technical_regime == Regime.BULLISH.value


def test_generate_sorted_by_score_desc():
    analytics = {
        "AMD": (
            IVStats(symbol="AMD", iv_rank=20.0),
            _tech(Regime.LOW_VOL),
            _fund(quality_flag=False),
        ),
        "NVDA": (
            IVStats(symbol="NVDA", iv_rank=90.0),
            _tech(Regime.BULLISH),
            _fund(quality_flag=True),
        ),
    }
    result = generate_buy_candidates(["AMD", "NVDA"], set(), analytics)
    assert len(result) == 2
    assert result[0].symbol == "NVDA"
    assert result[0].score > result[1].score


def test_generate_score_in_range():
    analytics = _analytics("AMD")
    result = generate_buy_candidates(["AMD"], set(), analytics)
    assert 0.0 <= result[0].score <= 100.0


def test_generate_multiple_symbols_all_valid():
    analytics = {
        "AMD": (IVStats(symbol="AMD", iv_rank=50.0), _tech(Regime.SIDEWAYS), _fund()),
        "MSFT": (IVStats(symbol="MSFT", iv_rank=70.0), _tech(Regime.HIGH_VOL), _fund()),
    }
    result = generate_buy_candidates(["AMD", "MSFT"], set(), analytics)
    assert len(result) == 2


def test_generate_none_iv_rank_uses_neutral():
    analytics = _analytics("AMD", iv_rank=None, regime=Regime.BULLISH, quality=True)
    result = generate_buy_candidates(["AMD"], set(), analytics)
    assert len(result) == 1
    # Should not raise and score should be a reasonable number
    assert result[0].score > 0
