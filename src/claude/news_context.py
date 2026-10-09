"""Recent-news context for the Ollama strategist prompt (Task 11 — "news-grounded review").

Builds a numbered ``=== NEWS ===`` block (``N1``...``Nk``) from Google News RSS search
(:mod:`src.data.google_news_backend`, keyless) plus yfinance's existing per-symbol headlines
(:func:`src.data.factory.get_news_provider`), deduped by normalised title, so the strategist
prompt's DECISION RUBRIC — which already asks the model to cite ``F#``/``N#`` ids in
``evidence`` (Task 10) — has real ``N#`` ids to point at. The bounded tool-calling research turn
(:mod:`src.claude.ollama_tools`) continues numbering from wherever this block leaves off, so a
model that searches for one more headline mid-review still cites a valid, unique id.

**Fence (CLAUDE.md).** This module is enrichment tier: it must never be importable from
``src/engine/``, ``src/execution/``, or ``src/strategies/`` — see
``tests/test_eval_skills.py::test_news_and_tool_research_never_reach_the_deterministic_layer``.

Never raises: every fetch degrades independently to an empty contribution, matching
``NewsSearchProvider.search`` and ``NewsProvider.get_headlines``'s own never-raises contracts —
a Google News or yfinance outage must never block a review.
"""

from __future__ import annotations

import logging
import time

from src.common.schemas import TradeCandidate
from src.data.protocols import NewsItem

log = logging.getLogger(__name__)

# The broad-market query blended into every NEWS block alongside the per-candidate symbols
# (Task 11 brief: "plus 3 market headlines for the query 'stock market today'").
_MARKET_QUERY = "stock market today"
_MARKET_HEADLINES = 3
_MAX_TITLE_CHARS = 140


def _normalize_title(title: str) -> str:
    """Case/whitespace-insensitive dedupe key — the same headline is frequently syndicated
    with trivial whitespace differences across a search and a per-symbol headlines fetch."""
    return " ".join(title.lower().split())


def _looks_like_ticker(query: str) -> bool:
    """True for a plain ticker-shaped query (e.g. "AAPL", "BRK.B") — the market-backdrop
    query ("stock market today") and any other free-text query are not symbols, so the
    yfinance per-symbol headlines lookup (which expects an actual ticker) is skipped for them.
    """
    bare = query.replace(".", "").replace("-", "")
    return bool(bare) and query.isupper() and bare.isalpha() and len(query) <= 6


def _news_item_from_yfinance(raw: dict) -> NewsItem | None:
    """Adapt one yfinance headline dict into a `NewsItem`.

    Mirrors `src.analytics.sentiment._fetch_news`'s handling of yfinance's two response shapes
    (the legacy flat dict, and the newer `{"content": {...}}` nesting — see
    `src.data.protocols.NewsProvider`). Returns None if the item has no title.
    """
    content = raw.get("content") if isinstance(raw.get("content"), dict) else raw
    content = content or {}
    title = content.get("title") or raw.get("title")
    if not title:
        return None
    provider = content.get("provider")
    source = provider.get("displayName") if isinstance(provider, dict) else raw.get("publisher")
    url = None
    canonical = content.get("canonicalUrl")
    if isinstance(canonical, dict):
        url = canonical.get("url")
    url = url or raw.get("link")
    return NewsItem(id="", title=str(title), source=source, published=None, url=url)


def _from_store(symbol: str, days: int, limit: int) -> list[NewsItem]:
    """The news service's deduped store first (spec §8) — read-only, never raises."""
    try:
        from datetime import UTC, datetime, timedelta

        from src.news.store.queries import recent_items_for
        from src.news.store.readonly import read_only_session

        with read_only_session() as s:
            if s is None:
                return []
            views = recent_items_for(s, symbol, datetime.now(UTC) - timedelta(days=days), limit)
    except Exception as exc:  # noqa: BLE001 — a store problem must not break the prompt
        log.debug("news_context: store read failed for %s: %s", symbol, exc)
        return []
    return [
        NewsItem(id="", title=v.title, source=v.source, published=v.published_at, url=v.url)
        for v in views
    ]


def _fetch(query: str, days: int, limit: int) -> list[NewsItem]:
    """The store's deduped clusters for a ticker, else Google News RSS search plus (for an
    actual ticker) yfinance headlines.

    Never raises: each source degrades independently to an empty contribution so a single
    provider's outage never drops the whole NEWS block. Monkeypatched wholesale in
    ``tests/test_news_context.py`` to isolate `build_news_block`'s numbering/dedupe logic from
    any provider.
    """
    if _looks_like_ticker(query):
        stored = _from_store(query, days, limit)
        if stored:
            return stored

    items: list[NewsItem] = []
    try:
        from src.data.factory import get_news_search_provider

        items.extend(get_news_search_provider().search(query, days=days, limit=limit))
    except Exception as exc:  # noqa: BLE001 — a search failure must not break the prompt
        log.debug("news_context: google news search failed for %r: %s", query, exc)

    if _looks_like_ticker(query):
        try:
            from src.data.factory import get_news_provider

            raw_items = get_news_provider().get_headlines(query, limit=limit) or []
        except Exception as exc:  # noqa: BLE001
            log.debug("news_context: yfinance headlines failed for %r: %s", query, exc)
            raw_items = []
        for raw in raw_items:
            item = _news_item_from_yfinance(raw)
            if item is not None:
                items.append(item)

    return items


def _ordered_underlyings(candidates: list[TradeCandidate]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c.underlying not in seen:
            seen.add(c.underlying)
            out.append(c.underlying)
    return out


def build_news_block(
    symbols: list[str],
    *,
    per_symbol: int,
    days: int,
    max_items: int = 25,
    deadline: float | None = None,
) -> tuple[str, dict[str, NewsItem]]:
    """Render the ``=== NEWS ===`` block and its id -> `NewsItem` index.

    One `_fetch` call per distinct symbol (order-preserving), plus one for the broad-market
    query, combined and deduped globally by normalised title, capped at `max_items`, and
    numbered ``N1``...``Nk`` in that order. Returns ``("", {})`` when nothing was found — the
    caller (`strategist.build_prompt`) simply omits the block, matching every other optional
    context block's fail-soft pattern.

    *deadline* (final review I2, a ``time.monotonic()`` value): no new query starts once it has
    passed — the NEWS fetch is the first slice of the review's single shared deadline
    (``ollama_runner.review_candidates``), and 11 sequential queries at up to ~8s each were
    otherwise unbounded. A query already in flight is not preempted (each provider call has its
    own timeout); whatever was fetched before the cut-off is still rendered.
    """
    seen_titles: set[str] = set()
    combined: list[NewsItem] = []
    queries = [(sym, per_symbol) for sym in symbols] + [(_MARKET_QUERY, _MARKET_HEADLINES)]

    for n_done, (query, limit) in enumerate(queries):
        if deadline is not None and time.monotonic() >= deadline:
            log.info(
                "news_context: NEWS fetch budget exhausted after %d/%d queries — skipping the rest",
                n_done,
                len(queries),
            )
            break
        for item in _fetch(query, days, limit):
            norm = _normalize_title(item.title)
            if not norm or norm in seen_titles:
                continue
            seen_titles.add(norm)
            combined.append(item)

    combined = combined[:max_items]
    if not combined:
        return "", {}

    index: dict[str, NewsItem] = {}
    lines = ["=== NEWS (recent headlines — cite as N# in evidence) ==="]
    for i, item in enumerate(combined, 1):
        nid = f"N{i}"
        title = item.title[:_MAX_TITLE_CHARS]
        numbered = item.model_copy(update={"id": nid, "title": title})
        index[nid] = numbered
        src = f"[{numbered.source}] " if numbered.source else ""
        pub = f" ({numbered.published.date()})" if numbered.published else ""
        lines.append(f"{nid} {src}{title}{pub}")

    return "\n".join(lines), index


def news_block_for_candidates(
    candidates: list[TradeCandidate],
    *,
    per_symbol: int,
    days: int,
    max_items: int,
    deadline: float | None = None,
) -> tuple[str, dict[str, NewsItem]]:
    """Convenience wrapper: the distinct underlyings in *candidates* -> `build_news_block`.

    Never raises — returns ``("", {})`` on any failure (including a bad config value) so a
    news-layer bug can never block a review; ``ollama_runner.review_candidates`` calls this
    directly rather than `build_news_block`.
    """
    try:
        symbols = _ordered_underlyings(candidates)
        return build_news_block(
            symbols, per_symbol=per_symbol, days=days, max_items=max_items, deadline=deadline
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("news_context: news_block_for_candidates failed: %s", exc)
        return "", {}
