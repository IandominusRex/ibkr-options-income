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
                    concept=concept,
                )
            )
    return facts


def resolve_line_item(payload: dict, spec: LineItemSpec) -> list[Fact] | None:
    """Every fact for this line item, pooled across every alias concept. None when none report.

    A filer can — and does — switch which us-gaap concept it tags a line item under between
    fiscal years (NVIDIA tags revenue `RevenueFromContractWithCustomerExcludingAssessedTax`
    for FY19-22 and `Revenues` for FY23-26; neither alone covers the company's full history).
    Stopping at the first alias with *any* facts silently drops every other alias's periods,
    which is exactly backwards for a company still actively filing under the second tag. Every
    concept's facts are pooled instead; :func:`select_periods`'s existing "latest filed wins"
    rule already arbitrates a period two aliases both happen to report, so pooling never needs
    its own precedence logic. None is the honest answer for a filer that reports nothing we
    recognise under any alias, and the caller renders UNKNOWN rather than a zero.
    """
    facts = [
        fact for concept in spec.concepts for fact in parse_facts(payload, concept, spec.units)
    ]
    return facts or None


# Duration windows, in days. Filers' fiscal years and quarters are not exactly 365/91 days,
# so these are ranges rather than equalities.
_ANNUAL_DAYS = (300, 400)
_QUARTER_DAYS = (60, 120)

# Forms that carry annual balance-sheet positions.
_ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "40-F"}


def select_periods(
    facts: list[Fact],
    *,
    kind: str,
    period_type: str,
    limit: int,
) -> list[Fact]:
    """Pick one fact per reporting period, newest first.

    Two rules carry the correctness of this function:

    1. `kind` is enforced. A duration fact can never satisfy an instant line item and vice
       versa. Summing four quarterly durations into "total assets", or reading an instant as
       a year of revenue, produces plausible nonsense.
    2. When two filings report the same period, the one filed LATER wins. That is how a
       restatement becomes the current answer instead of silently reverting.
    """
    if kind == "duration":
        lo, hi = _ANNUAL_DAYS if period_type == "annual" else _QUARTER_DAYS
        candidates = [
            f for f in facts if f.start is not None and lo <= (f.end - f.start).days <= hi
        ]
    elif kind == "instant":
        candidates = [f for f in facts if f.start is None]
        if period_type == "annual":
            candidates = [f for f in candidates if f.form in _ANNUAL_FORMS]
    else:
        raise ValueError(f"kind must be 'duration' or 'instant', got {kind!r}")

    # One fact per period_end; the latest filing wins.
    by_period: dict[date, Fact] = {}
    for fact in candidates:
        current = by_period.get(fact.end)
        if current is None or fact.filed > current.filed:
            by_period[fact.end] = fact

    return sorted(by_period.values(), key=lambda f: f.end, reverse=True)[:limit]


SUPPORTED_UNITS = frozenset({"USD", "USD/shares", "shares", "pure"})


def assert_units_supported(spec: LineItemSpec) -> None:
    """Reject units we cannot interpret rather than coercing them.

    A EUR-denominated revenue silently treated as USD is worse than no number at all.
    """
    for unit in spec.units:
        if unit not in SUPPORTED_UNITS:
            raise ValueError(f"Unsupported unit {unit!r}; supported: {sorted(SUPPORTED_UNITS)}")
