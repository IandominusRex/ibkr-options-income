"""Research touches: the trading side tells the news process which names it just looked at.

A `/scan GOOGL`, a trade review or a roll review learns something about the name (fresh headlines,
the Claude read of them). Until now none of it reached the dossier, which rebuilt only on news the
news process had seen itself, at most every ``prose_min_interval_hours`` and under a daily call
cap (2026-10-27: "5 names wait" in every loop). A *touch* (`briefs.note_researched`, the one call
the trading process makes) puts the name at the front of that queue:

* ``collect`` - the news process pulls fresh headlines for the name (no model call);
* ``researched`` - `dossier_due` reports the name due ``researched_min_interval_min`` after its
  last prose, ahead of the other names, still under ``dossier.max_calls_per_day``;
* the rebuild replaces the story and the reported figures, and ``merge_events`` drops events whose
  date has passed, so what was true last week does not survive beside what is true now;
* the market (symbol ``*``) does the same for the picture, once it is ``picture.touch_min_age_min``
  old and inside ``picture.max_rebuilds_per_day``.

Enrichment tier, news process side: reads and closes rows, never opens one (the trading process
does, through `briefs`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.news.store.models import DossierTouchRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

MARKET = "*"


def touched_since(s: Session, symbol: str, since: datetime) -> bool:
    """An open touch for *symbol* newer than *since* (the name's last prose or picture)."""
    return (
        s.scalar(
            select(DossierTouchRow.id)
            .where(
                DossierTouchRow.symbol == symbol,
                DossierTouchRow.consumed_at.is_(None),
                DossierTouchRow.touched_at > naive_utc(since),
            )
            .limit(1)
        )
        is not None
    )


def consume(s: Session, symbols: list[str], now: datetime) -> None:
    """Close the open touches of *symbols* that were made by *now*."""
    if not symbols:
        return
    s.execute(
        update(DossierTouchRow)
        .where(
            DossierTouchRow.symbol.in_(symbols),
            DossierTouchRow.consumed_at.is_(None),
            DossierTouchRow.touched_at <= naive_utc(now),
        )
        .values(consumed_at=naive_utc(now))
    )


def due_for_collection(now: datetime, *, recollect_min: int = 10) -> list[str]:
    """Names touched since their headlines were last pulled (never the market, never twice in
    ``recollect_min`` minutes)."""
    with news_session() as s:
        rows = s.scalars(
            select(DossierTouchRow).where(
                DossierTouchRow.consumed_at.is_(None), DossierTouchRow.symbol != MARKET
            )
        ).all()
        gap = timedelta(minutes=recollect_min)
        return [
            r.symbol for r in rows if r.collected_at is None or r.touched_at - r.collected_at > gap
        ]


def mark_collected(symbol: str, now: datetime) -> None:
    with news_session() as s:
        s.execute(
            update(DossierTouchRow)
            .where(DossierTouchRow.symbol == symbol, DossierTouchRow.consumed_at.is_(None))
            .values(collected_at=naive_utc(now))
        )


def prune_touches(now: datetime) -> None:
    """Delete touches older than ``dossier.touch_keep_days`` (a name that never gets a dossier -
    not in the universe, not held - would otherwise keep its open touch for ever)."""
    cutoff = naive_utc(now - timedelta(days=get_config().news.dossier.touch_keep_days))
    with news_session() as s:
        s.execute(delete(DossierTouchRow).where(DossierTouchRow.touched_at < cutoff))
