"""Reddit sentiment scorer: praw → normalized 0-100 score per symbol.

Returns 50 (neutral) whenever credentials are absent, praw is not installed,
or any API call fails — the pipeline never blocks on this module.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

_SUBREDDITS = ("options", "wallstreetbets")
_BULLISH = frozenset(
    {"bull", "bullish", "buy", "call", "calls", "long", "moon", "squeeze", "rally", "breakout"}
)
_BEARISH = frozenset(
    {"bear", "bearish", "put", "puts", "short", "sell", "crash", "dump", "drop", "collapse"}
)
_NEUTRAL = 50.0
_SCORE_CAP = 50.0  # max deviation from neutral in either direction


def _keyword_bias(title: str) -> float:
    """Return -1.0 (bearish) to +1.0 (bullish) from title keywords."""
    words = set(title.lower().split())
    bull = len(words & _BULLISH)
    bear = len(words & _BEARISH)
    total = bull + bear
    return 0.0 if total == 0 else (bull - bear) / total


def _make_reddit(client_id: str, client_secret: str, user_agent: str) -> Any:
    import praw

    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )


def fetch_sentiment(
    symbol: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    user_agent: str = "ibkr-options-scanner/1.0",
    _reddit: Any = None,
) -> float:
    """Fetch Reddit sentiment for *symbol*, returning a 0-100 score (50 = neutral).

    Searches r/options and r/wallstreetbets for posts mentioning *symbol* in the
    last 24h.  Blends upvote ratio with bullish/bearish keyword bias and scales
    by mention volume (log-compressed so 50+ mentions ≈ full weight).

    Returns 50.0 on any error or when credentials are missing.
    """
    if _reddit is None:
        # Only enforce credentials + praw availability when building a real client.
        if not (client_id and client_secret):
            logger.debug("No Reddit credentials — neutral sentiment for %s", symbol)
            return _NEUTRAL
        try:
            import praw  # noqa: F401
        except ImportError:
            logger.warning("praw not installed — neutral sentiment for %s", symbol)
            return _NEUTRAL

    try:
        reddit = (
            _reddit if _reddit is not None else _make_reddit(client_id, client_secret, user_agent)
        )
        sym_pattern = re.compile(rf"\b{re.escape(symbol.upper())}\b")

        mention_count = 0
        upvote_sum = 0.0
        keyword_sum = 0.0

        for sub_name in _SUBREDDITS:
            sub = reddit.subreddit(sub_name)
            for post in sub.search(symbol, sort="new", time_filter="day", limit=100):
                if not sym_pattern.search(post.title.upper()):
                    continue
                mention_count += 1
                upvote_sum += float(post.upvote_ratio)  # 0-1
                keyword_sum += _keyword_bias(post.title)

        if mention_count == 0:
            return _NEUTRAL

        avg_upvote_ratio = upvote_sum / mention_count
        avg_keyword_bias = keyword_sum / mention_count  # -1 to +1

        # Log-compress volume so 50+ mentions gives full weight, 1 mention gives ~17 %
        volume_factor = min(1.0, math.log1p(mention_count) / math.log1p(50))

        # Blend upvote signal (centred at 0.5→0) and keyword bias equally → -1..+1
        signal = (avg_upvote_ratio - 0.5) * 2 * 0.5 + avg_keyword_bias * 0.5
        score = _NEUTRAL + signal * _SCORE_CAP * volume_factor
        return round(max(0.0, min(100.0, score)), 2)

    except Exception as exc:  # network, auth, rate-limit
        logger.warning("Sentiment fetch failed for %s: %s", symbol, exc)
        return _NEUTRAL


class SentimentScorer:
    """Per-run cache wrapper around fetch_sentiment.

    Instantiate once per morning scan; repeated calls for the same symbol
    return the cached value without hitting the Reddit API again.
    """

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        user_agent: str = "ibkr-options-scanner/1.0",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._cache: dict[str, float] = {}
        self._reddit: Any = None

        if client_id and client_secret:
            try:
                import praw  # noqa: F401

                self._reddit = _make_reddit(client_id, client_secret, user_agent)
            except Exception as exc:
                logger.warning("Reddit client init failed: %s — will return neutral", exc)

    def score(self, symbol: str) -> float:
        """Return cached sentiment score for *symbol*, fetching if not yet seen."""
        if symbol not in self._cache:
            self._cache[symbol] = fetch_sentiment(
                symbol,
                client_id=self._client_id,
                client_secret=self._client_secret,
                user_agent=self._user_agent,
                _reddit=self._reddit,
            )
        return self._cache[symbol]
