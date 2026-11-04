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


# Part 4 (spec §8.3, §8.5): the names the value book wants a filing read of (held and READY
# names); the research sweep queues a ``filing_sections`` job for each.
FILING_READS_FILE: Path = ROOT / "data" / "value_filing_reads.json"


def _write(path: Path, symbols: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(sorted({s.upper() for s in symbols})), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return sorted({s.upper() for s in data if isinstance(s, str) and s})


def write_keep_fresh(symbols: Iterable[str]) -> None:
    """Replace the list atomically (write a sibling temp file, then rename)."""
    _write(KEEP_FRESH_FILE, symbols)


def read_keep_fresh() -> list[str]:
    """The list, or ``[]`` when the file is missing or unreadable (the sweep then covers the
    universes alone, as before)."""
    return _read(KEEP_FRESH_FILE)


def write_filing_reads(symbols: Iterable[str]) -> None:
    _write(FILING_READS_FILE, symbols)


def read_filing_reads() -> list[str]:
    """The names to slice filings for, or ``[]`` (no file: no filing reads)."""
    return _read(FILING_READS_FILE)
