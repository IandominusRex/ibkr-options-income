"""Grounded facts (spec §8.2): every fact Claude proposes from a filing is checked here, and any
failure drops it. Pure: no I/O.

- The accession must be one of the filing's the read was given, and the quote must appear
  **verbatim** in that filing's sliced text (whitespace and curly quotes normalised, nothing else).
- A fact with a number must have that number in its quote (the ``src/news/grounding.py::grounded``
  rule, restated here: ``src/value/`` may not import ``src.news``).
- A fact naming a canonical XBRL item that the filing tagged must match companyfacts for that
  accession within 0.5% (after its unit's scale), whatever the quote says.

A grounded fact is stored and read again (the kill triggers ``guidance_cut`` and
``customer_loss``; the display). In Part 4 it adjusts no number (the plan's ruling 9).
"""

from __future__ import annotations

import re

from src.common.value_ai_types import FilingSection, ProposedFact
from src.common.value_types import ValueFinancials

XBRL_TOLERANCE = 0.005
_NUM = re.compile(r"(?<![A-Za-z0-9])[-+]?\d[\d,]*(?:\.(\d+))?")
_SPACE = re.compile(r"\s+")
SCALE = {
    "USD": 1.0,
    "USD_thousands": 1e3,
    "USD_millions": 1e6,
    "USD_billions": 1e9,
}


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"')
    return _SPACE.sub(" ", text.replace("”", '"')).strip()


def numbers_in(text: str) -> list[tuple[float, int]]:
    out: list[tuple[float, int]] = []
    for m in _NUM.finditer(text):
        try:
            out.append((float(m.group(0).replace(",", "")), len(m.group(1) or "")))
        except ValueError:
            continue
    return out


def number_in_quote(value: float, quote: str) -> bool:
    """*value* written in *quote*, to the precision the quote shows (within half a unit of its
    last digit), sign aside."""
    for found, decimals in numbers_in(quote):
        if abs(abs(found) - abs(value)) <= 0.5 * 10.0**-decimals:
            return True
    return False


def xbrl_value(fin: ValueFinancials | None, item: str, accn: str) -> float | None:
    """The value companyfacts carries for *item* from the filing *accn* (an annual period whose
    item that filing reported), or None when the filing did not tag it."""
    if fin is None:
        return None
    for period in fin.annual:
        if period.accns.get(item) == accn and item in period.items:
            return period.items[item]
    return None


def check_fact(
    fact: ProposedFact, sections: list[FilingSection], fin: ValueFinancials | None = None
) -> tuple[bool, str]:
    """(grounded, why not). Why is "" for a grounded fact."""
    text = " ".join(s.text for s in sections if s.accn == fact.accn)
    if not text:
        return False, "the accession is not a filing this read was given"
    if _norm(fact.quote) not in _norm(text):
        return False, "the quote is not in the filing verbatim"
    if fact.value is not None and not number_in_quote(fact.value, fact.quote):
        return False, "the number is not in the quote"
    if fact.item is not None and fact.value is not None:
        tagged = xbrl_value(fin, fact.item, fact.accn)
        scale = SCALE.get(fact.unit)
        if tagged is not None and scale is not None and tagged != 0:
            if abs(fact.value * scale - tagged) / abs(tagged) > XBRL_TOLERANCE:
                return False, f"companyfacts tags {fact.item} {tagged:,.0f} for this filing"
    return True, ""
