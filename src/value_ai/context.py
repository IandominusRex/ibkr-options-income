"""What Claude reads beside the scorecard (spec §8.3): the name's dossier when one exists, the
news clusters the news process filed in pile 1 or 2, and its earnings dates, from news.db through
the read-only engine. Synchronous (SQLite); never raises: a missing source is named in
``unavailable`` so the prompt says what is missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.common.config import get_config
from src.common.dossier_text import render_dossier
from src.news.store.queries import earnings_between, latest_dossier, piled_clusters_for
from src.news.store.readonly import read_only_session

log = logging.getLogger(__name__)
NEWS_DAYS = 30
EARNINGS_BACK_DAYS = 120
EARNINGS_AHEAD_DAYS = 90


@dataclass(slots=True)
class AnalystContext:
    dossier: str = ""
    headlines: list[str] = field(default_factory=list)
    earnings: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)


def _clean(text: str, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def gather(symbol: str, now: datetime, max_headlines: int) -> AnalystContext:
    out = AnalystContext()
    try:
        with read_only_session() as s:
            if s is None:
                out.unavailable.append("news")
                return out
            dossier = latest_dossier(s, symbol)
            if dossier is not None:
                out.dossier = render_dossier(
                    dossier,
                    symbol=symbol,
                    now=now,
                    staleness_hours=get_config().news.dossier.staleness_hours,
                    compact=False,
                )
            for c in piled_clusters_for(s, symbol, now - timedelta(days=NEWS_DAYS))[:max_headlines]:
                out.headlines.append(
                    f"{_aware(c.last_seen):%Y-%m-%d} · {_clean(c.headline, 200)} · "
                    f"{c.source_count} source(s)"
                )
            today = now.date()
            for e in earnings_between(
                s,
                today - timedelta(days=EARNINGS_BACK_DAYS),
                today + timedelta(days=EARNINGS_AHEAD_DAYS),
                {symbol.upper()},
            ):
                surprise = (
                    f" · EPS {e.eps_actual} vs {e.eps_est} est"
                    if e.eps_actual is not None and e.eps_est is not None
                    else ""
                )
                out.earnings.append(f"{e.report_date} ({e.status}){surprise}")
    except Exception as exc:  # noqa: BLE001 - enrichment degrades, never raises
        log.warning("value_ai: news read failed for %s: %s", symbol, exc)
        out.unavailable.append("news")
    return out
