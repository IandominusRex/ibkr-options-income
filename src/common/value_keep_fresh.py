"""The "keep fresh" list: names the value book still holds in its shadow record that may no longer
be in either universe (spec §6.9: held and shadow names stay fresh nightly).

Neutral plain data. The value process writes the list after each night; the research worker's
nightly sweep reads it and keeps those names' bars and filings current. A small JSON file under
``data/`` is the whole channel, so ``src/research/`` never imports ``src.value`` or opens
``value.db``, and ``src/value/`` never writes ``research.db``. Stdlib only.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path

from src.common.config import ROOT

log = logging.getLogger(__name__)

KEEP_FRESH_FILE: Path = ROOT / "data" / "value_keep_fresh.json"


def write_keep_fresh(symbols: Iterable[str]) -> None:
    """Replace the list atomically (write a sibling temp file, then rename)."""
    path = KEEP_FRESH_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(sorted({s.upper() for s in symbols})), encoding="utf-8")
    os.replace(tmp, path)


def read_keep_fresh() -> list[str]:
    """The list, or ``[]`` when the file is missing or unreadable (the sweep then covers the
    universes alone, as before)."""
    try:
        data = json.loads(KEEP_FRESH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return sorted({s.upper() for s in data if isinstance(s, str) and s})
