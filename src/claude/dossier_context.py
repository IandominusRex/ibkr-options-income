"""The ticker dossiers as a prompt block, for the headless Claude calls that read them.

The news process builds a dossier for every name the book cares about and stores it in
``data/news.db``; this module only reads them (through ``src.news.store.readonly``, SQLite
``mode=ro``) and renders them with the one neutral function every reader shares
(``src.common.dossier_text``). The trade review gets a compact note for each reviewed name
(capped, in the candidates' priority order); a ``/scan TICKER`` deep-dive and a roll review get
the full note for their one name. Enrichment tier: the block reaches prompt text and the
review-reuse fingerprint (``prose_key``) and nothing else. It is never imported by ``engine/``,
``execution/``, ``strategies/`` or ``spreads/`` (``tests/test_eval_skills.py``,
``tests/test_news_fence.py``).

Never raises: an absent or old ``news.db``, an unreadable row or any other failure reads as "no
notes", and a prompt with no notes simply has no ``NAME NOTES`` block.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.common.config import get_config
from src.common.dossier_text import render_dossiers
from src.common.schemas import TickerDossier
from src.news.store import queries
from src.news.store.readonly import read_only_session

log = logging.getLogger(__name__)

_DEFAULT_STALENESS_HOURS = 26.0


def load_dossiers(symbols: list[str]) -> dict[str, TickerDossier]:
    """The newest stored dossier of each of *symbols* that has one; ``{}`` when there is none or
    the store cannot be read."""
    if not symbols:
        return {}
    try:
        with read_only_session() as s:
            if s is None:
                return {}
            return queries.latest_dossiers(s, symbols)
    except Exception:  # noqa: BLE001 - a reader of an enrichment store must never fail a call
        log.warning("dossiers: could not be read", exc_info=True)
        return {}


def _staleness_hours() -> float:
    try:
        return get_config().news.dossier.staleness_hours
    except Exception:  # noqa: BLE001
        return _DEFAULT_STALENESS_HOURS


def dossier_block(
    symbols: list[str],
    dossiers: dict[str, TickerDossier],
    *,
    now: datetime,
    compact: bool,
    max_names: int,
) -> str:
    """The ``=== NAME NOTES ===`` block for the first *max_names* of *symbols* (upper-cased, each
    once, in the order given), then ``(N more names without notes in this prompt)`` when any were
    cut. Empty when there are no names or no dossier at all: a prompt without notes carries no
    block (a name with no dossier beside others that have one reads ``(no notes yet)``)."""
    names = list(dict.fromkeys(s.upper() for s in symbols))
    if not names or not dossiers:
        return ""
    shown = names[:max_names]
    text = render_dossiers(
        [(n, dossiers.get(n)) for n in shown],
        now=now,
        staleness_hours=_staleness_hours(),
        compact=compact,
    )
    if len(names) > len(shown):
        text += f"\n({len(names) - len(shown)} more names without notes in this prompt)"
    return text


def load_dossier_block(symbols: list[str], now: datetime, *, compact: bool) -> str:
    """Read *symbols*' dossiers and render their block, with no cap. Never raises."""
    return dossier_block(
        symbols, load_dossiers(symbols), now=now, compact=compact, max_names=max(1, len(symbols))
    )


def prose_key(d: TickerDossier | None) -> str | None:
    """What a review fingerprint keys a name's notes on: when its prose was written and its
    events (id and date), marked when the prose is stale; ``None`` for no dossier.

    Deliberately **not** the dossier's ``version``: that changes on every hourly numbers refresh,
    which would defeat review reuse. A reused review is therefore never older than the prose and
    events it read; the numbers it read are at most an hour old (ruling 43). A failed prose
    rebuild flips ``stale`` without a new ``prose_at``, and the note the model reads then carries
    a stale label, so the key changes with it.
    """
    if d is None:
        return None
    events = ";".join(sorted(f"{e.id}:{e.on.isoformat()}" for e in d.events))
    when = d.prose_at.isoformat() if d.prose_at is not None else "-"
    return f"{when}|{events}" + (":stale" if d.stale else "")
