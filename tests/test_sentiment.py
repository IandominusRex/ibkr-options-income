"""Tests for src/analytics/sentiment — all praw calls are mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.analytics.sentiment import (
    _NEUTRAL,
    SentimentScorer,
    _keyword_bias,
    fetch_sentiment,
)

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

        def _score(n: int) -> float:
            posts = [_make_post(f"AAPL bull calls rally {i}", upvote_ratio=0.9) for i in range(n)]
            reddit = _make_reddit({"options": posts, "wallstreetbets": []})
            return fetch_sentiment("AAPL", client_id="id", client_secret="s", _reddit=reddit)

        assert _score(1) < _score(10) < _score(50)


# ---------------------------------------------------------------------------
# SentimentScorer — caching
# ---------------------------------------------------------------------------


class TestSentimentScorer:
    def test_returns_neutral_without_credentials(self) -> None:
        scorer = SentimentScorer()
        assert scorer.score("AAPL") == _NEUTRAL

    def test_caches_result(self) -> None:
        posts = [_make_post("AAPL bull calls moon", upvote_ratio=0.9)]
        reddit = _make_reddit({"options": posts, "wallstreetbets": []})

        scorer = SentimentScorer(client_id="id", client_secret="s")
        scorer._reddit = reddit

        first = scorer.score("AAPL")
        # Mutate the mock so a second real fetch would return neutral — cache should win
        reddit.subreddit.side_effect = lambda _: (_ for _ in ()).throw(
            RuntimeError("should not call")
        )
        second = scorer.score("AAPL")

        assert first == second

    def test_different_symbols_fetched_independently(self) -> None:
        aapl_posts = [_make_post("AAPL bull calls", upvote_ratio=0.9)]
        tsla_posts = [_make_post("TSLA bear puts crash", upvote_ratio=0.1)]

        def subreddit(name: str) -> MagicMock:
            sub = MagicMock()
            sub.search.side_effect = lambda sym, **_: aapl_posts if sym == "AAPL" else tsla_posts
            return sub

        reddit = MagicMock()
        reddit.subreddit.side_effect = subreddit

        scorer = SentimentScorer(client_id="id", client_secret="s")
        scorer._reddit = reddit

        aapl_score = scorer.score("AAPL")
        tsla_score = scorer.score("TSLA")
        assert aapl_score > _NEUTRAL
        assert tsla_score < _NEUTRAL


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
