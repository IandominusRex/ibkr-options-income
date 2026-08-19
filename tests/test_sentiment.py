"""Tests for src/analytics/sentiment — all praw calls are mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.analytics.sentiment as sentiment_mod
from src.analytics.sentiment import (
    _NEUTRAL,
    SentimentScorer,
    _blend,
    _fetch_news,
    _fetch_stocktwits,
    _keyword_bias,
    _label,
    _velocity,
    fetch_sentiment,
)
from src.common.cache import clear_all
from src.common.schemas import SentimentDetail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_post(title: str, upvote_ratio: float = 0.75) -> MagicMock:
    post = MagicMock()
    post.title = title
    post.upvote_ratio = upvote_ratio
    return post


def _make_reddit(posts_by_sub: dict[str, list[MagicMock]]) -> MagicMock:
    """Return a mock praw.Reddit whose subreddits yield the given post lists."""
    reddit = MagicMock()

    def subreddit(name: str) -> MagicMock:
        sub = MagicMock()
        sub.search.return_value = posts_by_sub.get(name, [])
        return sub

    reddit.subreddit.side_effect = subreddit
    return reddit


# ---------------------------------------------------------------------------
# _keyword_bias
# ---------------------------------------------------------------------------


class TestKeywordBias:
    def test_bullish_title(self) -> None:
        score = _keyword_bias("AAPL bull call breakout rally")
        assert score > 0

    def test_bearish_title(self) -> None:
        score = _keyword_bias("AAPL put short crash dump")
        assert score < 0

    def test_neutral_title(self) -> None:
        score = _keyword_bias("AAPL earnings report tomorrow")
        assert score == 0.0

    def test_mixed_title_equal(self) -> None:
        score = _keyword_bias("AAPL buy but also puts")
        # "buy" bullish, "puts" bearish → 1 each → 0
        assert score == 0.0

    def test_empty_title(self) -> None:
        assert _keyword_bias("") == 0.0


# ---------------------------------------------------------------------------
# fetch_sentiment — no credentials
# ---------------------------------------------------------------------------


class TestFetchSentimentNoCredentials:
    def test_missing_client_id_returns_neutral(self) -> None:
        assert fetch_sentiment("AAPL", client_id="", client_secret="secret") == _NEUTRAL

    def test_missing_client_secret_returns_neutral(self) -> None:
        assert fetch_sentiment("AAPL", client_id="id", client_secret="") == _NEUTRAL

    def test_both_missing_returns_neutral(self) -> None:
        assert fetch_sentiment("AAPL") == _NEUTRAL


# ---------------------------------------------------------------------------
# fetch_sentiment — praw not installed
# ---------------------------------------------------------------------------


class TestFetchSentimentNoPraw:
    def test_import_error_returns_neutral(self) -> None:
        with patch.dict("sys.modules", {"praw": None}):
            result = fetch_sentiment("AAPL", client_id="id", client_secret="secret")
        assert result == _NEUTRAL


# ---------------------------------------------------------------------------
# fetch_sentiment — mocked Reddit
# ---------------------------------------------------------------------------


class TestFetchSentimentMocked:
    def test_no_matching_posts_returns_neutral(self) -> None:
        reddit = _make_reddit({"options": [], "wallstreetbets": []})
        result = fetch_sentiment("AAPL", client_id="id", client_secret="s", _reddit=reddit)
        assert result == _NEUTRAL

    def test_non_matching_ticker_in_title_skipped(self) -> None:
        # Posts mentioning a different ticker should be ignored
        posts = [_make_post("TSLA bull run today", upvote_ratio=0.9)]
        reddit = _make_reddit({"options": posts, "wallstreetbets": []})
        result = fetch_sentiment("AAPL", client_id="id", client_secret="s", _reddit=reddit)
        assert result == _NEUTRAL

    def test_bullish_posts_score_above_neutral(self) -> None:
        posts = [
            _make_post("AAPL bull call breakout", upvote_ratio=0.9),
            _make_post("Buying AAPL calls for moon shot", upvote_ratio=0.85),
            _make_post("AAPL rally incoming bull", upvote_ratio=0.88),
        ]
        reddit = _make_reddit({"options": posts, "wallstreetbets": []})
        result = fetch_sentiment("AAPL", client_id="id", client_secret="s", _reddit=reddit)
        assert result > _NEUTRAL

    def test_bearish_posts_score_below_neutral(self) -> None:
        posts = [
            _make_post("AAPL puts crash incoming bear", upvote_ratio=0.2),
            _make_post("AAPL dump bear puts short", upvote_ratio=0.15),
            _make_post("AAPL collapse short puts", upvote_ratio=0.18),
        ]
        reddit = _make_reddit({"options": posts, "wallstreetbets": []})
        result = fetch_sentiment("AAPL", client_id="id", client_secret="s", _reddit=reddit)
        assert result < _NEUTRAL

    def test_result_always_in_0_100(self) -> None:
        # Extreme bullish signal should never exceed 100
        posts = [
            _make_post(f"AAPL bull calls moon rally {i}", upvote_ratio=1.0) for i in range(200)
        ]
        reddit = _make_reddit({"options": posts, "wallstreetbets": []})
        result = fetch_sentiment("AAPL", client_id="id", client_secret="s", _reddit=reddit)
        assert 0.0 <= result <= 100.0

    def test_aggregates_across_subreddits(self) -> None:
        options_posts = [_make_post("AAPL calls bullish", upvote_ratio=0.8)]
        wsb_posts = [_make_post("AAPL to the moon rally", upvote_ratio=0.85)]
        reddit = _make_reddit({"options": options_posts, "wallstreetbets": wsb_posts})
        result = fetch_sentiment("AAPL", client_id="id", client_secret="s", _reddit=reddit)
        assert result > _NEUTRAL

    def test_api_exception_returns_neutral(self) -> None:
        reddit = MagicMock()
        reddit.subreddit.side_effect = RuntimeError("rate limited")
        result = fetch_sentiment("AAPL", client_id="id", client_secret="s", _reddit=reddit)
        assert result == _NEUTRAL

    def test_volume_factor_increases_with_more_posts(self) -> None:
        """More mentions of the same quality should push score further from neutral."""
        from src.common.cache import clear_all

        def _score(n: int) -> float:
            # fetch_sentiment is @daily_cached on `symbol`; clear so each call re-fetches.
            clear_all()
            posts = [_make_post(f"AAPL bull calls rally {i}", upvote_ratio=0.9) for i in range(n)]
            reddit = _make_reddit({"options": posts, "wallstreetbets": []})
            return fetch_sentiment("AAPL", client_id="id", client_secret="s", _reddit=reddit)

        assert _score(1) < _score(10) < _score(50)


# ---------------------------------------------------------------------------
# _label — score → human bucket
# ---------------------------------------------------------------------------


class TestLabel:
    def test_buckets(self) -> None:
        assert _label(None) == "no data"
        assert _label(80) == "Bullish"
        assert _label(60) == "Lean bullish"
        assert _label(50) == "Neutral"
        assert _label(40) == "Lean bearish"
        assert _label(20) == "Bearish"


# ---------------------------------------------------------------------------
# _blend — volume/confidence-weighted composite
# ---------------------------------------------------------------------------


class TestBlend:
    def test_all_sources_absent_returns_none(self) -> None:
        assert (
            _blend(stocktwits=None, stocktwits_msgs=0, news=None, news_count=0, reddit=None) is None
        )

    def test_single_source_passes_through(self) -> None:
        # Only StockTwits present (full weight at 20+ msgs) → composite == StockTwits score.
        out = _blend(stocktwits=80.0, stocktwits_msgs=30, news=None, news_count=0, reddit=None)
        assert out == pytest.approx(80.0)

    def test_stocktwits_outweighs_news_at_equal_volume(self) -> None:
        # StockTwits (weight 1.0) should pull the blend nearer its value than news (weight 0.8).
        out = _blend(stocktwits=90.0, stocktwits_msgs=20, news=10.0, news_count=8, reddit=None)
        midpoint = 50.0
        assert out > midpoint  # StockTwits-bullish wins the tug-of-war

    def test_low_volume_source_earns_less_weight(self) -> None:
        # 1 StockTwits msg (weight ~0.05) vs 8 news headlines (full 0.8) → news dominates.
        out = _blend(stocktwits=100.0, stocktwits_msgs=1, news=20.0, news_count=8, reddit=None)
        assert out < 50.0


# ---------------------------------------------------------------------------
# _fetch_stocktwits — public API parsing (httpx mocked)
# ---------------------------------------------------------------------------


def _patch_httpx_json(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    # _stocktwits_get returns parsed JSON (curl_cffi or httpx under the hood) — patch at that seam.
    monkeypatch.setattr(sentiment_mod, "_stocktwits_get", lambda url: payload)


def _st_msg(basic: str | None, body: str = "") -> dict:
    sentiment = {"basic": basic} if basic else None
    return {"body": body, "entities": {"sentiment": sentiment}}


class TestFetchStockTwits:
    def test_self_tags_drive_score(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_all()
        _patch_httpx_json(
            monkeypatch,
            {"messages": [_st_msg("Bullish"), _st_msg("Bullish"), _st_msg("Bearish")]},
        )
        score, count = _fetch_stocktwits("NVDA")
        assert count == 3
        assert score is not None and score > _NEUTRAL  # 2 bull vs 1 bear → net bullish

    def test_empty_messages_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_all()
        _patch_httpx_json(monkeypatch, {"messages": []})
        assert _fetch_stocktwits("NVDA") == (None, 0)

    def test_network_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_all()

        def _boom(url):
            raise RuntimeError("429 rate limited")

        monkeypatch.setattr(sentiment_mod, "_stocktwits_get", _boom)
        assert _fetch_stocktwits("NVDA") == (None, 0)

    def test_untagged_falls_back_to_vader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_all()
        _patch_httpx_json(
            monkeypatch,
            {"messages": [_st_msg(None, "this is going to crash and collapse, terrible")]},
        )
        score, count = _fetch_stocktwits("NVDA")
        assert count == 1
        assert score is not None and score < _NEUTRAL


# ---------------------------------------------------------------------------
# _fetch_news — yfinance headlines + VADER (yfinance mocked)
# ---------------------------------------------------------------------------


class TestFetchNews:
    def _patch_news(self, monkeypatch: pytest.MonkeyPatch, items: list[dict]) -> None:
        from src.data import factory as data_factory

        provider = MagicMock()
        provider.get_headlines.return_value = items
        # Clear the lru_cache before patching so the new mock takes effect.
        data_factory.get_news_provider.cache_clear()
        monkeypatch.setattr("src.data.factory.get_news_provider", lambda: provider)

    def test_positive_headlines_score_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_all()
        self._patch_news(
            monkeypatch,
            [{"content": {"title": "Shares surge to record high on stellar profit beat"}}],
        )
        score, count, top = _fetch_news("NVDA")
        assert count == 1
        assert score is not None and score > _NEUTRAL
        assert top is not None

    def test_legacy_flat_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_all()
        self._patch_news(monkeypatch, [{"title": "Company wins major award, analysts upgrade"}])
        score, count, top = _fetch_news("NVDA")
        assert count == 1 and score is not None

    def test_no_news_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clear_all()
        self._patch_news(monkeypatch, [])
        assert _fetch_news("NVDA") == (None, 0, None)


# ---------------------------------------------------------------------------
# _velocity — 1-day change, persisted to a tmp history file
# ---------------------------------------------------------------------------


class TestVelocity:
    def test_first_reading_has_no_velocity(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import date

        monkeypatch.setattr(sentiment_mod, "_HISTORY_FILE", tmp_path / "hist.json")
        assert _velocity("NVDA", 70.0, today=date(2026, 6, 24)) is None

    def test_second_day_diffs_against_prior(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import date

        monkeypatch.setattr(sentiment_mod, "_HISTORY_FILE", tmp_path / "hist.json")
        _velocity("NVDA", 60.0, today=date(2026, 6, 23))
        assert _velocity("NVDA", 70.0, today=date(2026, 6, 24)) == pytest.approx(10.0)

    def test_none_overall_returns_none(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sentiment_mod, "_HISTORY_FILE", tmp_path / "hist.json")
        assert _velocity("NVDA", None) is None


# ---------------------------------------------------------------------------
# SentimentScorer — composite + caching (sources mocked, no network)
# ---------------------------------------------------------------------------


class TestSentimentScorer:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        # Keyless sources off by default; velocity writes to a tmp file. Tests opt sources in.
        monkeypatch.setattr(sentiment_mod, "_HISTORY_FILE", tmp_path / "hist.json")
        monkeypatch.setattr(sentiment_mod, "_fetch_stocktwits", lambda s: (None, 0))
        monkeypatch.setattr(sentiment_mod, "_fetch_news", lambda s: (None, 0, None))
        clear_all()

    def test_no_data_anywhere_yields_none_overall(self) -> None:
        detail = SentimentScorer().score("AAPL")
        assert isinstance(detail, SentimentDetail)
        assert detail.overall is None
        assert detail.label == "no data"

    def test_returns_sentiment_detail_with_sources(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sentiment_mod, "_fetch_stocktwits", lambda s: (80.0, 25))
        monkeypatch.setattr(sentiment_mod, "_fetch_news", lambda s: (70.0, 6, "Big beat"))
        detail = SentimentScorer().score("AAPL")
        assert detail.overall is not None and detail.overall > _NEUTRAL
        assert detail.stocktwits == pytest.approx(80.0)
        assert detail.news == pytest.approx(70.0)
        assert detail.top_headline == "Big beat"
        assert detail.label in ("Bullish", "Lean bullish")

    def test_caches_within_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = {"n": 0}

        def _st(symbol: str) -> tuple[float | None, int]:
            calls["n"] += 1
            return 75.0, 20

        monkeypatch.setattr(sentiment_mod, "_fetch_stocktwits", _st)
        scorer = SentimentScorer()
        first = scorer.score("AAPL")
        second = scorer.score("AAPL")
        assert first == second
        assert calls["n"] == 1  # second call served from the per-run cache

    def test_different_symbols_independent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            sentiment_mod,
            "_fetch_stocktwits",
            lambda s: (90.0, 25) if s == "AAPL" else (15.0, 25),
        )
        scorer = SentimentScorer()
        assert scorer.score("AAPL").overall > _NEUTRAL  # type: ignore[operator]
        assert scorer.score("TSLA").overall < _NEUTRAL  # type: ignore[operator]

    def test_reddit_disabled_without_credentials(self) -> None:
        # No creds → Reddit source contributes nothing (stays None in the detail).
        monkeypatch_free = SentimentScorer()
        assert monkeypatch_free.score("AAPL").reddit is None


# ---------------------------------------------------------------------------
# Integration: ScoreCard accepts sentiment_score
# ---------------------------------------------------------------------------


class TestScoreCardSentiment:
    def test_sentiment_score_defaults_to_none(self) -> None:
        from src.common.schemas import ScoreCard

        sc = ScoreCard(symbol="AAPL")
        assert sc.sentiment_score is None

    def test_sentiment_score_stored(self) -> None:
        from src.common.schemas import ScoreCard

        sc = ScoreCard(symbol="AAPL", sentiment_score=67.5)
        assert sc.sentiment_score == pytest.approx(67.5)


# ---------------------------------------------------------------------------
# Integration: scoring.py blends sentiment when weight > 0
# ---------------------------------------------------------------------------


class TestScoringBlendsSentiment:
    def test_high_sentiment_increases_blended_score(self) -> None:
        from datetime import date

        from src.common.schemas import OptionRight, ScoreCard, Strategy, TradeCandidate
        from src.engine.scoring import score_candidates

        def _candidate(sentiment: float | None, candidate_id: str) -> TradeCandidate:
            return TradeCandidate(
                candidate_id=candidate_id,
                strategy=Strategy.COVERED_CALL,
                underlying="AAPL",
                right=OptionRight.CALL,
                strike=185.0,
                expiry=date(2026, 7, 17),
                contracts=1,
                premium=1.50,
                collateral=18_000.0,
                roc_pct=0.83,
                annualized_yield_pct=18.5,
                breakeven=183.50,
                dte=48,
                scores=ScoreCard(
                    symbol="AAPL",
                    iv_score=70.0,
                    technical_score=70.0,
                    fundamental_score=70.0,
                    liquidity_score=70.0,
                    assignment_safety_score=70.0,
                    sentiment_score=sentiment,
                ),
            )

        low_sent = score_candidates([_candidate(10.0, "low")])[0]
        high_sent = score_candidates([_candidate(90.0, "high")])[0]
        assert high_sent.blended_score > low_sent.blended_score

    def test_none_sentiment_treated_as_neutral(self) -> None:
        from datetime import date

        from src.common.schemas import OptionRight, ScoreCard, Strategy, TradeCandidate
        from src.engine.scoring import score_candidates

        def _candidate(sentiment: float | None, candidate_id: str) -> TradeCandidate:
            return TradeCandidate(
                candidate_id=candidate_id,
                strategy=Strategy.COVERED_CALL,
                underlying="AAPL",
                right=OptionRight.CALL,
                strike=185.0,
                expiry=date(2026, 7, 17),
                contracts=1,
                premium=1.50,
                collateral=18_000.0,
                roc_pct=0.83,
                annualized_yield_pct=18.5,
                breakeven=183.50,
                dte=48,
                scores=ScoreCard(
                    symbol="AAPL",
                    iv_score=70.0,
                    technical_score=70.0,
                    fundamental_score=70.0,
                    liquidity_score=70.0,
                    assignment_safety_score=70.0,
                    sentiment_score=sentiment,
                ),
            )

        neutral = score_candidates([_candidate(50.0, "neutral")])[0]
        none_sent = score_candidates([_candidate(None, "none")])[0]
        assert neutral.blended_score == pytest.approx(none_sent.blended_score, abs=0.01)
