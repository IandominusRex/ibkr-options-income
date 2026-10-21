"""The enrichment inputs the spreads picker gathers itself: macro backdrop, SPY daily
technicals, and recent market/macro headlines plus today's scheduled prints from news.db.

Synchronous (yfinance, SQLite) — the picker runs it in a thread. Never raises: each source
degrades on its own and is named in ``unavailable`` so the prompt says what is missing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

from src.analytics.market_conditions import get_market_conditions
from src.analytics.realized_vol import compute_realized_vol
from src.analytics.technicals import get_technical_stats
from src.common.config import get_config
from src.common.picture_text import render_picture
from src.common.schemas import SpreadMarketSnapshot
from src.news.store.queries import clusters_since, econ_events_between, latest_picture
from src.news.store.readonly import read_only_session
from src.spreads_ai.parse import clean

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_HEADLINE_HOURS = 6


def _pct_from(price: float, ref: float | None) -> float | None:
    return None if not ref else (price / ref - 1.0) * 100.0


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _news(now: datetime, limit: int) -> tuple[list[str], float | None, list[str], bool]:
    """(headline lines, mean deterministic tone, today's scheduled prints, source ok)."""
    if limit <= 0:
        return [], None, [], True
    try:
        with read_only_session() as s:
            if s is None:
                return [], None, [], False
            since = now - timedelta(hours=_HEADLINE_HOURS)
            clusters = [
                *clusters_since(s, since, category="macro", limit=limit),
                *clusters_since(s, since, category="markets", limit=limit),
            ]
            clusters.sort(key=lambda c: c.last_seen, reverse=True)
            lines: list[str] = []
            tones: list[float] = []
            for c in clusters[:limit]:
                sents = [i.det_sentiment for i in c.items if i.det_sentiment is not None]
                tone = mean(sents) if sents else None
                if tone is not None:
                    tones.append(tone)
                lines.append(
                    f"{_aware(c.last_seen).astimezone(ET):%H:%M} ET · {clean(c.headline, 200)} · "
                    f"{c.source_count} source(s)" + ("" if tone is None else f" · tone {tone:+.2f}")
                )
            start = datetime.combine(now.astimezone(ET).date(), time(0), tzinfo=ET)
            econ = [
                f"{_aware(e.scheduled_at).astimezone(ET):%H:%M} ET · {clean(e.title, 120)} · "
                f"impact {e.impact}"
                + (f" · consensus {e.consensus}" if e.consensus else "")
                + (f" · actual {e.actual}" if e.actual else "")
                for e in econ_events_between(s, start, start + timedelta(days=1))
            ]
            return lines, (mean(tones) if tones else None), econ, True
    except Exception as exc:  # noqa: BLE001 — enrichment degrades, never raises
        log.warning("spreads_ai: news read failed: %s", exc)
        return [], None, [], False


def _picture_text(now: datetime) -> str | None:
    """The stored market picture as prompt text, its regime lines labelled "as of <built_at>"
    (this process never fetches a regime of its own: ruling 11). None when there is no picture or
    it cannot be read; a source that is merely absent is not an error."""
    try:
        with read_only_session() as s:
            if s is None:
                return None
            picture = latest_picture(s)
        if picture is None:
            return None
        return render_picture(
            picture,
            now=now,
            staleness_hours=get_config().news.picture.staleness_hours,
            regime_as_of=True,
        )
    except Exception as exc:  # noqa: BLE001 - enrichment degrades, never raises
        log.warning("spreads_ai: picture read failed: %s", exc)
        return None


def market_snapshot(now: datetime, *, symbol: str, max_headlines: int) -> SpreadMarketSnapshot:
    fields: dict[str, float | None] = {}
    unavailable: list[str] = []
    try:
        mc = get_market_conditions()
        fields.update(
            vix=mc.vix,
            vix_term_ratio=mc.vix_term_ratio,
            ten_year_yield=mc.ten_year_yield,
            ten_year_change_5d_bp=mc.ten_year_change_5d_bp,
            spy_ret_5d_pct=mc.spy_ret_5d_pct,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("spreads_ai: macro backdrop failed: %s", exc)
        unavailable.append("macro")
    try:
        t = get_technical_stats(symbol)
        fields.update(
            spy_vs_sma20_pct=_pct_from(t.price, t.sma_20),
            spy_vs_sma50_pct=_pct_from(t.price, t.sma_50),
            rsi14=t.rsi_14,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("spreads_ai: technicals failed: %s", exc)
        unavailable.append("technicals")
    try:
        hv30 = compute_realized_vol(symbol, 30)  # annualised, in percent; None = no history
        if hv30 is None:
            unavailable.append("realized_vol")
        fields["hv30"] = hv30
    except Exception as exc:  # noqa: BLE001
        log.warning("spreads_ai: realized vol failed: %s", exc)
        unavailable.append("realized_vol")
    headlines, tone, econ, ok = _news(now, max_headlines)
    if not ok:
        unavailable.append("news")
    return SpreadMarketSnapshot(
        **fields,
        headline_count=len(headlines),
        headline_sentiment_mean=tone,
        headlines=headlines,
        econ_today=econ,
        picture_text=_picture_text(now),
        unavailable=unavailable,
    )
