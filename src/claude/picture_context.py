"""The market picture as a prompt block, for the headless Claude calls that read it.

The news process writes the picture to ``data/news.db``; this module only reads it (through
``src.news.store.readonly``, SQLite ``mode=ro``) and renders it with the one neutral function every
reader shares (``src.common.picture_text.render_picture``). Enrichment tier: the block reaches
prompts and nothing else. It is never imported by ``engine/``, ``execution/``, ``strategies/`` or
``spreads/`` (``tests/test_eval_skills.py``, ``tests/test_news_fence.py``).

Never raises: an absent or old ``news.db``, an unreadable row or any other failure reads as "no
picture", and the block says ``(unavailable)`` so the model is told instead of left to assume.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.common.config import get_config
from src.common.picture_text import render_picture
from src.common.schemas import MarketPicture
from src.news.store import queries
from src.news.store.readonly import read_only_session

log = logging.getLogger(__name__)


def load_picture() -> MarketPicture | None:
    """The newest stored picture, or None when there is none (or it cannot be read)."""
    try:
        with read_only_session() as s:
            if s is None:
                return None
            return queries.latest_picture(s)
    except Exception:  # noqa: BLE001 - a reader of an enrichment store must never fail a call
        log.warning("market picture: could not be read", exc_info=True)
        return None


def render_picture_block(picture: MarketPicture | None, *, now: datetime) -> str:
    """*picture* as prompt text (a stale one says so; none reads ``(unavailable)``)."""
    try:
        staleness_hours = get_config().news.picture.staleness_hours
    except Exception:  # noqa: BLE001
        staleness_hours = 26.0
    return render_picture(picture, now=now, staleness_hours=staleness_hours)


def load_picture_block(now: datetime) -> str:
    """The stored picture as a ``=== MARKET PICTURE ===`` block. Never raises."""
    return render_picture_block(load_picture(), now=now)


def picture_key(picture: MarketPicture | None) -> str | None:
    """What a review fingerprint keys on: the picture's version, marked when it is stale.

    A rebuilt picture has a new version; a failed rebuild flips ``stale`` without one, and the
    block the model reads changes then too ("PICTURE IS STALE"), so the key must as well.
    """
    if picture is None:
        return None
    return f"{picture.version}:stale" if picture.stale else picture.version
