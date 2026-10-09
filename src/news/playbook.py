"""📘 Playbook — textbook first-reaction priors per US release (spec §6.3). Deterministic.

Reads committed reference data from config/news_playbook.yaml (not an operator-private file).
"""

from __future__ import annotations

import functools
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from src.common.config import CONFIG_DIR

ASSETS = ("stocks", "bonds", "dollar", "gold", "oil", "vol")
Direction = Literal["up", "down", "flat"]
Surprise = Literal["hot", "cold", "inline"]
ARROW = {"up": "🟢", "down": "🔴", "flat": "⚪"}

_PERIOD = re.compile(r"\b(m/m|y/y|q/q|mom|yoy|qoq)\b|\((mom|yoy|qoq)\)", re.I)
_MULT = {"K": 10**3, "M": 10**6, "B": 10**9, "T": 10**12}


def norm_event_title(title: str) -> str:
    t = _PERIOD.sub(" ", title.lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


class PlaybookEntry(BaseModel):
    key: str
    aliases: list[str]
    tolerance: float
    inverse: bool = False
    hot: dict[str, Direction]
    cold: dict[str, Direction]
    rationale_hot: str
    rationale_cold: str


class PlaybookPrior(BaseModel):
    key: str
    direction: Literal["hot", "cold"]
    arrows: dict[str, str]
    rationale: str


class Playbook:
    def __init__(self, entries: list[PlaybookEntry]) -> None:
        self.entries = entries
        self._by_alias = {norm_event_title(a): e for e in entries for a in e.aliases}
        self._rank = {e.key: i for i, e in enumerate(entries)}

    def match(self, title: str) -> PlaybookEntry | None:
        return self._by_alias.get(norm_event_title(title))

    def priority(self, key: str) -> int:
        return self._rank.get(key, len(self._rank))


@functools.lru_cache(maxsize=1)
def load_playbook(path: Path | None = None) -> Playbook:
    p = path or (CONFIG_DIR / "news_playbook.yaml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Playbook([PlaybookEntry.model_validate(e) for e in raw.get("entries", [])])


def parse_value(s: str | None) -> float | None:
    if s is None:
        return None
    t = s.replace("&nbsp;", "").replace("\xa0", "").replace(",", "").replace("$", "").strip()
    if not t:
        return None
    neg = False
    if t.startswith("(") and ")" in t:
        neg, t = True, t.replace("(", "").replace(")", "")
    t = t.rstrip("%").strip()
    mult = 1
    if t and t[-1].upper() in _MULT:
        mult, t = _MULT[t[-1].upper()], t[:-1]
    try:
        # Decimal, not float: 8.28 * 1e9 is 8279999999.999999 in binary floating point.
        v = float(Decimal(t) * mult)
    except (InvalidOperation, ValueError):
        return None
    return -v if neg else v


def surprise_dir(entry: PlaybookEntry, actual: str | None, expected: str | None) -> Surprise | None:
    a, e = parse_value(actual), parse_value(expected)
    if a is None or e is None:
        return None
    diff = (e - a) if entry.inverse else (a - e)
    if diff > entry.tolerance:
        return "hot"
    if diff < -entry.tolerance:
        return "cold"
    return "inline"


def prior_for(entry: PlaybookEntry, direction: Surprise | None) -> PlaybookPrior | None:
    if direction not in ("hot", "cold"):
        return None
    dirs = entry.hot if direction == "hot" else entry.cold
    return PlaybookPrior(
        key=entry.key,
        direction=direction,
        arrows={a: ARROW[dirs[a]] for a in ASSETS},
        rationale=entry.rationale_hot if direction == "hot" else entry.rationale_cold,
    )
