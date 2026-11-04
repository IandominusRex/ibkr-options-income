"""The VALUE NOTE as a prompt block for the wheel's headless reviews (Part 6, ruling 9).

Reads what the value book knows of the reviewed names through the one read-only window onto
value.db (``src.common.value_view``, SQLite ``mode=ro``) and renders it with the neutral
renderer (``src.common.value_text``). This module is the **only** place under ``src/claude/``
that may touch either: nothing here imports ``src.value`` (``tests/test_value_fence.py``).

Enrichment tier, prompt text only. The note reaches the trade review, the roll review and
``/scan NAME`` (ruling 18: never the spreads picker, the EOD narrative, the news process or the
value book's own Claude reads). The only thing a prompt can do with it is the existing clamped,
reduce-only ``max_contracts`` cut on an auto-opened CSP; it never moves the Rules Engine.

Never raises: a missing or unreadable value.db, or any other failure, is "no note".
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.common import value_view
from src.common.config import get_config
from src.common.value_text import render_value_notes

log = logging.getLogger(__name__)


def enabled() -> bool:
    """``value.prompt_note.enabled`` (ships true); a config that cannot be read means off."""
    try:
        return bool(get_config().value.prompt_note.enabled)
    except Exception:  # noqa: BLE001 - a prompt reader must never fail a call
        return False


def load_value_block(symbols: list[str], now: datetime) -> str | None:
    """The ``=== VALUE NOTE ===`` block for *symbols*, or ``None`` when the note is off, the
    value book knows none of them, or value.db cannot be read. Never raises."""
    del now  # the note shows the book as stored; kept so every context reader has one signature
    if not symbols or not enabled():
        return None
    try:
        notes = value_view.read_notes(symbols)
        if not notes:
            return None
        return render_value_notes(symbols, notes) or None
    except Exception:  # noqa: BLE001
        log.warning("value note: could not be built", exc_info=True)
        return None
