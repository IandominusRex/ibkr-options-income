"""XBRL fact parsing and concept resolution.

EDGAR returns facts tagged with us-gaap concepts, and filers disagree about which concept
means the same thing. Without normalisation a comparison between two companies is
meaningless. The map is config (config/research_concepts.yaml), so a missing mapping is a
config fix rather than a code change.
"""

from __future__ import annotations

import functools
import logging
from datetime import date, datetime

import yaml
from pydantic import BaseModel, field_validator

from src.common.config import CONFIG_DIR
from src.research.schemas import Fact

log = logging.getLogger(__name__)


class LineItemSpec(BaseModel):
    statement: str  # income | balance | cash_flow
    kind: str  # duration | instant
    units: list[str]
    concepts: list[str]

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in {"duration", "instant"}:
            raise ValueError(f"kind must be 'duration' or 'instant', got {v!r}")
        return v


@functools.lru_cache(maxsize=1)
def load_concept_map() -> dict[str, LineItemSpec]:
    """Load and cache the canonical line item map."""
    path = CONFIG_DIR / "research_concepts.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {name: LineItemSpec(**spec) for name, spec in (raw.get("line_items") or {}).items()}


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_facts(payload: dict, concept: str, units: list[str]) -> list[Fact]:
    """Every well-formed fact for `concept` in one of `units`.

    Malformed entries are skipped individually. One bad date in a filer's history must not
    cost us the other forty facts.
    """
    try:
        unit_map = payload["facts"]["us-gaap"][concept]["units"]
    except (KeyError, TypeError):
        return []

    facts: list[Fact] = []
    for unit in units:
        for entry in unit_map.get(unit, []) or []:
            end = _parse_date(entry.get("end"))
            filed = _parse_date(entry.get("filed"))
            value = entry.get("val")
            if end is None or filed is None or not isinstance(value, int | float):
                continue
            facts.append(
                Fact(
                    value=float(value),
                    unit=unit,
                    start=_parse_date(entry.get("start")),
                    end=end,
                    accn=str(entry.get("accn") or ""),
                    fy=entry.get("fy") if isinstance(entry.get("fy"), int) else None,
                    fp=str(entry["fp"]) if entry.get("fp") else None,
                    form=str(entry.get("form") or ""),
                    filed=filed,
                )
            )
    return facts


def resolve_line_item(payload: dict, spec: LineItemSpec) -> tuple[str, list[Fact]] | None:
    """First candidate concept that actually has facts. None when none do.

    None is the honest answer for a filer that reports nothing we recognise, and the caller
    renders UNKNOWN rather than a zero.
    """
    for concept in spec.concepts:
        facts = parse_facts(payload, concept, spec.units)
        if facts:
            return concept, facts
    return None
