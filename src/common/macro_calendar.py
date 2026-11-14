"""The static macro calendar: FOMC decision days and the US data releases (risk-envelope Task 2).

Reads ``config/macro_calendar.yaml`` (committed reference data, dates taken from federalreserve.gov,
bls.gov and bea.gov; each row names its source). The spreads book's ``risk.events`` blocks read it
(Task 3), and it is the Mastermind's D19 source. Standard library, yaml and pydantic only.
"""

from __future__ import annotations

import functools
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from src.common.config import ROOT

CALENDAR_PATH = ROOT / "config" / "macro_calendar.yaml"


class MacroEvent(BaseModel):
    """One scheduled release. ``day`` is the ET calendar date, ``time_et`` the HH:MM ET print."""

    model_config = ConfigDict(frozen=True)

    day: date
    kind: Literal["FOMC", "CPI", "PPI", "NFP", "PCE"]
    time_et: str
    source: str


@functools.lru_cache(maxsize=4)
def _load(path: Path) -> tuple[MacroEvent, ...]:
    raw = yaml.safe_load(path.read_text()) or []
    events = tuple(MacroEvent.model_validate(row) for row in raw)
    return tuple(sorted(events, key=lambda e: (e.day, e.kind)))


def load_calendar(path: Path | None = None) -> tuple[MacroEvent, ...]:
    """Every event in the file, sorted by day then kind. Cached per path."""
    return _load(path if path is not None else CALENDAR_PATH)


def events_on(day: date, path: Path | None = None) -> list[MacroEvent]:
    """The events scheduled on *day* (empty on an ordinary day)."""
    return [e for e in load_calendar(path) if e.day == day]


def events_between(start: date, end: date, path: Path | None = None) -> list[MacroEvent]:
    """Events with ``start <= day <= end``, in date order."""
    return [e for e in load_calendar(path) if start <= e.day <= end]
