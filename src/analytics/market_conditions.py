"""Market-level (macro) conditions — the backdrop every scan is run against.

Fetched once per scan (not per-symbol) and passed through the pipeline as a
:class:`~src.common.schemas.MarketConditions` snapshot. Four questions, all keyless:

  * **How expensive is fear?** ``^VIX``.
  * **Is that fear front-loaded?** ``^VIX`` vs ``^VIX3M``. A ratio above 1 (backwardation)
    means the market prices more risk now than in three months — premium looks rich but the
    tail is real, which is exactly when a naive IV-rank screen is most misleading.
  * **What are rates doing?** ``^TNX`` level and its 5-session change in basis points.
  * **What is the tape and the news flow saying?** SPY 5-day return plus a VADER read over
    recent SPY/QQQ headlines.

**Enrichment only.** Nothing here reaches scoring, the risk engine, or sizing — it is
rendered on the deep-dive card and injected into the reasoning prompt. Every source is
independently fail-soft: one dead feed degrades a line, never the scan.

Cost discipline: VIX and VIX3M are fetched per scan (cheap, and they move intraday); rates,
the tape and headlines are ``@daily_cached`` so the 15-min loop hits each at most once per
calendar day.
"""

from __future__ import annotations

import logging

from src.common.cache import daily_cached
from src.common.schemas import MarketConditions

log = logging.getLogger(__name__)

# Headline sources for the macro read. SPY + QQQ between them cover broad-tape and
# growth/rates narratives without needing a keyed news API.
_MACRO_HEADLINE_SYMBOLS = ("SPY", "QQQ")


def get_market_conditions() -> MarketConditions:
    """Fetch the current macro backdrop via yfinance.

    Never raises: any field whose source fails comes back ``None`` (``0`` for the headline
    count), so callers only need to handle missing data, not exceptions.
    """
    vix = _fetch_index_level("^VIX")
    vix3m = _fetch_index_level("^VIX3M")
    term_ratio = None
    if vix is not None and vix3m is not None and vix3m > 0:
        term_ratio = round(vix / vix3m, 3)

    ten_year, ten_year_change_bp = _fetch_ten_year()
    headline_score, headline_count, top_headline = _fetch_macro_headlines()

    return MarketConditions(
        vix=vix,
        vix3m=vix3m,
        vix_term_ratio=term_ratio,
        ten_year_yield=ten_year,
        ten_year_change_5d_bp=ten_year_change_bp,
        spy_ret_5d_pct=_fetch_spy_5d_return(),
        macro_headline_score=headline_score,
        macro_headline_count=headline_count,
        top_macro_headline=top_headline,
    )


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def _fetch_index_level(symbol: str) -> float | None:
    """Latest level for an index symbol (e.g. ``^VIX``), or None.

    Tries the price provider's ``get_last_price`` first (cheap live quote); falls back to
    the last settled close from the provider's OHLCV history. Never raises.
    """
    try:
        from src.data.factory import get_price_provider

        provider = get_price_provider()
        price = provider.get_last_price(symbol)
        if price is not None and float(price) > 0:
            return round(float(price), 2)
        # Fallback: last close from history
        hist = provider.get_ohlcv(symbol, lookback_days=5)
        if hist is not None and not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as exc:
        log.warning("market_conditions: %s fetch failed — %s", symbol, exc)
    return None


@daily_cached
def _fetch_ten_year() -> tuple[float | None, float | None]:
    """Return ``(10y yield %, 5-session change in bp)``.

    ``^TNX`` quotes the yield ×10 (43.1 = 4.31%), so both figures are scaled down by 10.
    Rates matter to a premium seller mainly as a regime signal — a fast repricing tends to
    move equity vol and correlation together.
    """
    try:
        from src.data.factory import get_price_provider

        hist = get_price_provider().get_ohlcv("^TNX", lookback_days=30)
        if hist is None or hist.empty:
            return None, None
        closes = hist["Close"].dropna()
        if closes.empty:
            return None, None
        level = round(float(closes.iloc[-1]) / 10.0, 2)
        change_bp = None
        if len(closes) >= 6:
            prior = float(closes.iloc[-6]) / 10.0
            change_bp = round((level - prior) * 100, 1)
        return level, change_bp
    except Exception as exc:
        log.warning("market_conditions: ^TNX fetch failed — %s", exc)
        return None, None


@daily_cached
def _fetch_spy_5d_return() -> float | None:
    """SPY's 5-session percentage change — the broad tape in one number."""
    try:
        from src.analytics.price_data import get_ohlcv

        df = get_ohlcv("SPY")
        if df is None or df.empty or len(df) < 6:
            return None
        closes = df["Close"].dropna()
        if len(closes) < 6:
            return None
        first, last = float(closes.iloc[-6]), float(closes.iloc[-1])
        if first <= 0:
            return None
        return round((last / first - 1) * 100, 2)
    except Exception as exc:
        log.warning("market_conditions: SPY 5d return failed — %s", exc)
        return None


@daily_cached
def _fetch_macro_headlines() -> tuple[float | None, int, str | None]:
    """VADER read over broad-market headlines: ``(0-100 score, count, top headline)``.

    Reuses ``sentiment._fetch_news`` — the same keyless yfinance headline fetch and VADER
    scoring the per-symbol composite uses — so there is one headline pipeline, not two. The
    per-source day cache there means this adds at most two extra fetches per day.
    """
    try:
        from src.analytics.sentiment import _fetch_news
    except Exception:  # pragma: no cover - import guard
        return None, 0, None

    scores: list[float] = []
    total = 0
    top: str | None = None
    for symbol in _MACRO_HEADLINE_SYMBOLS:
        try:
            score, count, headline = _fetch_news(symbol)
        except Exception as exc:
            log.debug("market_conditions: headlines failed for %s — %s", symbol, exc)
            continue
        if score is None or count <= 0:
            continue
        scores.append(score)
        total += count
        if top is None and headline:
            top = headline
    if not scores:
        return None, 0, None
    return round(sum(scores) / len(scores), 1), total, top


# --------------------------------------------------------------------------- #
# Prompt rendering
# --------------------------------------------------------------------------- #


def render_macro_context(mc: MarketConditions | None) -> str:
    """Render the macro backdrop as a prompt block, mirroring ``render_sector_context``.

    Returns "" when nothing is available, so the caller can inject it unconditionally.
    """
    if mc is None:
        return ""
    rows: list[str] = []
    if mc.vix is not None:
        rows.append(f"VIX: {mc.vix:.1f} ({vix_regime(mc.vix)})")
    if mc.vix_term_ratio is not None:
        shape = (
            "backwardation — near-term risk priced above 3-month"
            if mc.vix_term_ratio > 1
            else "contango (normal)"
        )
        rows.append(f"VIX term (VIX/VIX3M): {mc.vix_term_ratio:.2f} — {shape}")
    if mc.ten_year_yield is not None:
        move = (
            f", {mc.ten_year_change_5d_bp:+.0f}bp over 5 sessions"
            if mc.ten_year_change_5d_bp is not None
            else ""
        )
        rows.append(f"US 10-year: {mc.ten_year_yield:.2f}%{move}")
    if mc.spy_ret_5d_pct is not None:
        rows.append(f"SPY 5-session: {mc.spy_ret_5d_pct:+.1f}%")
    if mc.macro_headline_score is not None and mc.macro_headline_count > 0:
        rows.append(
            f"Macro headlines: {mc.macro_headline_score:.0f}/100 "
            f"({mc.macro_headline_count} headlines across SPY/QQQ)"
        )
        if mc.top_macro_headline:
            rows.append(f"Latest: {mc.top_macro_headline[:140]}")
    if not rows:
        return ""
    return "=== MACRO BACKDROP (the tape this trade is placed into) ===\n" + "\n".join(rows)


def vix_regime(vix: float) -> str:
    """Short plain-English read of a VIX level, shared by the prompt and the Telegram card."""
    if vix < 15:
        return "calm — premiums thin; be selective, favour higher IV-rank names"
    if vix < 20:
        return "normal"
    if vix < 30:
        return "elevated — richer premium but wider moves; mind assignment risk"
    return "stressed — premium is rich but tail risk is high; size down"
