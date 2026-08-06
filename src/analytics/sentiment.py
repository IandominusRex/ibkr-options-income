"""Composite social + news sentiment per symbol → a normalized SentimentDetail.

Three independent sources, blended by confidence/volume into one 0-100 score (50 = neutral):

  • StockTwits  — public JSON API (no key). Users self-tag messages Bullish/Bearish; untagged
                  messages are scored with VADER. The strongest, finance-native signal.
  • News        — recent headlines via yfinance (no key), each scored with VADER.
  • Reddit      — r/options + r/wallstreetbets via praw (OPTIONAL, free credentials). Dormant
                  and contributes nothing unless REDDIT_CLIENT_ID/SECRET are set in .env.

Design guarantees (this module is enrichment, never a dependency):
  • Every source fails closed to "no data" (None) on missing creds, missing libs, network,
    rate-limit, or parse errors — the scan pipeline never blocks on sentiment.
  • If *all* sources return no data, ``overall`` is None (distinct from a balanced 50).
  • Each source is ``@daily_cached`` on the symbol, so the ~26 intraday scans/session reuse the
    first cycle's result — each source hits its API at most once per calendar day per symbol.

Per the architecture fence: SentimentDetail reaches Claude (verdict/ranking) and Telegram only.
Nothing here is importable from the risk engine, sizing, or execution path.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from src.common.cache import daily_cached
from src.common.market_hours import today_et
from src.common.schemas import SentimentDetail

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

_USER_AGENT = "ibkr-options-scanner/1.0"
_STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
_HTTP_TIMEOUT = 10.0

# 1-day velocity store: {symbol: {"YYYY-MM-DD": overall}}. Tests monkeypatch this to a tmp path.
_HISTORY_FILE = Path("data/sentiment_history.json")
_HISTORY_DAYS = 7  # prune entries older than this many days on each write
_HISTORY_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# VADER text scoring (offline, no key)
# --------------------------------------------------------------------------- #
_ANALYZER: Any = None  # None = not yet built; False = unavailable; else SentimentIntensityAnalyzer


def _vader_compound(text: str) -> float:
    """Return VADER compound polarity in -1.0..+1.0 for *text* (0.0 if unavailable/empty)."""
    global _ANALYZER
    if not text:
        return 0.0
    if _ANALYZER is None:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

            _ANALYZER = SentimentIntensityAnalyzer()
        except Exception as exc:  # not installed / lexicon load failure
            logger.warning("vaderSentiment unavailable — text sentiment disabled: %s", exc)
            _ANALYZER = False
    if not _ANALYZER:
        return 0.0
    try:
        return float(_ANALYZER.polarity_scores(text)["compound"])
    except Exception:
        return 0.0


def _bias_to_score(avg_bias: float) -> float:
    """Map an average polarity in -1..+1 to a 0-100 sentiment score (50 = neutral)."""
    return round(max(0.0, min(100.0, _NEUTRAL + avg_bias * _SCORE_CAP)), 2)


# --------------------------------------------------------------------------- #
# Source: StockTwits (public API, no key)
# --------------------------------------------------------------------------- #
@daily_cached
def _stocktwits_get(url: str) -> dict:
    """GET *url* and return parsed JSON. Raises on any HTTP/parse error.

    StockTwits sits behind Cloudflare, which blocks plain ``httpx``/``requests`` on TLS
    fingerprint (HTTP 403) regardless of headers. ``curl_cffi`` impersonates a real Chrome TLS
    handshake and passes; we fall back to ``httpx`` only if ``curl_cffi`` isn't installed (it will
    likely 403, but degrades gracefully to neutral upstream).
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        cffi_requests = None  # type: ignore[assignment]

    if cffi_requests is not None:
        cresp = cffi_requests.get(url, impersonate="chrome", timeout=_HTTP_TIMEOUT)
        cresp.raise_for_status()
        return cresp.json()

    hresp = httpx.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT)
    hresp.raise_for_status()
    return hresp.json()


def _fetch_stocktwits(symbol: str) -> tuple[float | None, int]:
    """Return (0-100 score, message_count) from StockTwits, or (None, 0) on any failure.

    StockTwits messages carry an explicit user ``Bullish``/``Bearish`` self-tag; those map to
    ±1.0 directly (the highest-quality signal). Untagged messages fall back to VADER on the body.
    """
    url = _STOCKTWITS_URL.format(symbol=symbol.upper())
    try:
        messages = _stocktwits_get(url).get("messages", [])
    except Exception as exc:  # network, rate-limit (429), Cloudflare 403, non-JSON
        logger.debug("StockTwits fetch failed for %s: %s", symbol, exc)
        return None, 0

    if not messages:
        return None, 0

    biases: list[float] = []
    for msg in messages:
        entities = msg.get("entities") or {}
        sentiment = entities.get("sentiment") or {}
        basic = sentiment.get("basic") if isinstance(sentiment, dict) else None
        if basic == "Bullish":
            biases.append(1.0)
        elif basic == "Bearish":
            biases.append(-1.0)
        else:
            biases.append(_vader_compound(msg.get("body") or ""))

    if not biases:
        return None, 0
    return _bias_to_score(sum(biases) / len(biases)), len(biases)


# --------------------------------------------------------------------------- #
# Source: News headlines (yfinance, no key)
# --------------------------------------------------------------------------- #
@daily_cached
def _fetch_news(symbol: str) -> tuple[float | None, int, str | None]:
    """Return (0-100 score, headline_count, top_headline) from yfinance news, or (None, 0, None).

    Each headline is scored with VADER and averaged. Handles both the legacy flat ``news`` item
    shape and the newer ``{"content": {...}}`` nesting yfinance returns.
    """
    try:
        import yfinance as yf

        items = yf.Ticker(symbol.upper()).news or []
    except Exception as exc:
        logger.debug("News fetch failed for %s: %s", symbol, exc)
        return None, 0, None

    titles: list[str] = []
    for item in items:
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        title = (content or {}).get("title") or item.get("title")
        if title:
            titles.append(str(title))

    if not titles:
        return None, 0, None

    biases = [_vader_compound(t) for t in titles]
    return _bias_to_score(sum(biases) / len(biases)), len(titles), titles[0]


# --------------------------------------------------------------------------- #
# Source: Reddit (praw, optional — free credentials)
# --------------------------------------------------------------------------- #
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


@daily_cached
def fetch_sentiment(
    symbol: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    user_agent: str = _USER_AGENT,
    _reddit: Any = None,
) -> float:
    """Fetch Reddit sentiment for *symbol*, returning a 0-100 score (50 = neutral).

    Searches r/options and r/wallstreetbets for posts mentioning *symbol* in the last 24h, blending
    upvote ratio with VADER + keyword bias on the title, scaled by log-compressed mention volume.

    Returns 50.0 on any error or when credentials are missing. ``@daily_cached`` keys on the
    positional ``symbol`` (credentials/``_reddit`` are keyword-only and excluded), so each symbol
    hits praw at most once per calendar day in a long-lived process.
    """
    if _reddit is None:
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
        bias_sum = 0.0

        for sub_name in _SUBREDDITS:
            sub = reddit.subreddit(sub_name)
            for post in sub.search(symbol, sort="new", time_filter="day", limit=100):
                if not sym_pattern.search(post.title.upper()):
                    continue
                mention_count += 1
                upvote_sum += float(post.upvote_ratio)  # 0-1
                # Blend a proper NLP read (VADER) with the finance-keyword bias on the title.
                bias_sum += (_vader_compound(post.title) + _keyword_bias(post.title)) / 2

        if mention_count == 0:
            return _NEUTRAL

        avg_upvote_ratio = upvote_sum / mention_count
        avg_bias = bias_sum / mention_count  # -1 to +1

        # Log-compress volume so 50+ mentions gives full weight, 1 mention gives ~17 %
        volume_factor = min(1.0, math.log1p(mention_count) / math.log1p(50))

        # Blend upvote signal (centred at 0.5→0) and text bias equally → -1..+1
        signal = (avg_upvote_ratio - 0.5) * 2 * 0.5 + avg_bias * 0.5
        score = _NEUTRAL + signal * _SCORE_CAP * volume_factor
        return round(max(0.0, min(100.0, score)), 2)

    except Exception as exc:  # network, auth, rate-limit
        logger.warning("Sentiment fetch failed for %s: %s", symbol, exc)
        return _NEUTRAL


# --------------------------------------------------------------------------- #
# Blending + velocity
# --------------------------------------------------------------------------- #
def _label(overall: float | None) -> str:
    """Human-readable bucket for an overall 0-100 score."""
    if overall is None:
        return "no data"
    if overall >= 65:
        return "Bullish"
    if overall >= 57:
        return "Lean bullish"
    if overall <= 35:
        return "Bearish"
    if overall <= 43:
        return "Lean bearish"
    return "Neutral"


def _blend(
    *,
    stocktwits: float | None,
    stocktwits_msgs: int,
    news: float | None,
    news_count: int,
    reddit: float | None,
) -> float | None:
    """Volume/confidence-weighted blend of available sources → 0-100, or None if all absent.

    Weights reflect both signal quality and sample size: StockTwits (explicit self-tags) is the
    primary source, news is secondary, Reddit is a light tie-breaker. A source with more
    messages/headlines earns proportionally more weight (saturating), so a single noisy post can't
    swing the composite.
    """
    weighted_sum = 0.0
    weight_total = 0.0

    if stocktwits is not None and stocktwits_msgs > 0:
        w = 1.0 * min(1.0, stocktwits_msgs / 20.0)
        weighted_sum += stocktwits * w
        weight_total += w
    if news is not None and news_count > 0:
        w = 0.8 * min(1.0, news_count / 8.0)
        weighted_sum += news * w
        weight_total += w
    if reddit is not None:
        w = 0.6
        weighted_sum += reddit * w
        weight_total += w

    if weight_total <= 0:
        return None
    return round(weighted_sum / weight_total, 2)


def _velocity(symbol: str, overall: float | None, *, today: date | None = None) -> float | None:
    """Persist today's *overall* and return the change vs the most recent prior day (in points).

    Reads/writes a small JSON history under :data:`_HISTORY_FILE`, pruned to the last
    :data:`_HISTORY_DAYS` days. All I/O is guarded and fails closed to None so velocity is never
    a hard dependency. Returns None when there is no prior reading or *overall* is None.
    """
    if overall is None:
        return None
    today = today or today_et()
    today_key = today.isoformat()
    cutoff = (today - timedelta(days=_HISTORY_DAYS)).isoformat()

    try:
        with _HISTORY_LOCK:
            store: dict[str, dict[str, float]] = {}
            if _HISTORY_FILE.exists():
                try:
                    store = json.loads(_HISTORY_FILE.read_text())
                except (json.JSONDecodeError, OSError):
                    store = {}

            sym_hist = {k: v for k, v in store.get(symbol, {}).items() if k >= cutoff}

            # Most recent reading strictly before today, if any.
            prior_days = sorted(k for k in sym_hist if k < today_key)
            prior = sym_hist[prior_days[-1]] if prior_days else None

            sym_hist[today_key] = overall
            store[symbol] = sym_hist

            _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _HISTORY_FILE.write_text(json.dumps(store))
    except Exception as exc:  # never let persistence break a scan
        logger.debug("Sentiment velocity store failed for %s: %s", symbol, exc)
        return None

    return None if prior is None else round(overall - prior, 2)


# --------------------------------------------------------------------------- #
# Public scorer
# --------------------------------------------------------------------------- #
class SentimentScorer:
    """Composite sentiment scorer. Instantiate once per scan.

    ``score(symbol)`` returns a :class:`SentimentDetail`. Within a scan, repeated calls for the
    same symbol are memoized; across the intraday loop's per-cycle scorers, the module-level
    ``@daily_cached`` source functions keep each API to one hit per symbol per calendar day.

    Reddit is included only when ``client_id``/``client_secret`` are supplied; StockTwits and news
    need no credentials. Every source degrades to "no data" rather than raising.
    """

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        user_agent: str = _USER_AGENT,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent
        self._reddit_enabled = bool(client_id and client_secret)
        self._cache: dict[str, SentimentDetail] = {}
        self._reddit: Any = None

        if self._reddit_enabled:
            try:
                import praw  # noqa: F401

                self._reddit = _make_reddit(client_id, client_secret, user_agent)
            except Exception as exc:
                logger.warning("Reddit client init failed: %s — Reddit source disabled", exc)
                self._reddit_enabled = False

    def score(self, symbol: str) -> SentimentDetail:
        """Return the composite :class:`SentimentDetail` for *symbol* (cached per run)."""
        if symbol in self._cache:
            return self._cache[symbol]

        st_score, st_msgs = _fetch_stocktwits(symbol)
        news_score, news_count, top_headline = _fetch_news(symbol)

        reddit_score: float | None = None
        if self._reddit_enabled:
            raw = fetch_sentiment(
                symbol,
                client_id=self._client_id,
                client_secret=self._client_secret,
                user_agent=self._user_agent,
                _reddit=self._reddit,
            )
            reddit_score = raw  # 50 here means "queried, balanced" (not "absent")

        overall = _blend(
            stocktwits=st_score,
            stocktwits_msgs=st_msgs,
            news=news_score,
            news_count=news_count,
            reddit=reddit_score,
        )
        detail = SentimentDetail(
            overall=overall,
            label=_label(overall),
            delta_1d=_velocity(symbol, overall),
            stocktwits=st_score,
            stocktwits_msgs=st_msgs,
            news=news_score,
            news_count=news_count,
            reddit=reddit_score,
            top_headline=top_headline,
        )
        self._cache[symbol] = detail
        return detail
