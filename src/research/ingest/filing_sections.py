"""The research worker's ``filing_sections`` job (value book spec §8.2 "Grounded facts", §8.5
"slicing a filing"). For the names the value book wants a filing read of (a plain file the value
process writes, ``src/common/value_keep_fresh.py``), the newest periodic filing's primary document
is fetched once and cut, deterministically, into the sections a reader needs: 10-K Items 1
(Business), 1A (Risk Factors) and 7 (MD&A); 10-Q Item 2 (MD&A); 20-F Items 4 and 5. A 40-F has no
item headings and is not sliced. Each section is capped so a filing read stays at ~15-25K tokens.

The heading match is a heuristic: a filing's table of contents names every item too, so of all
the spans that start at an item's heading and run to the next heading, the longest is kept.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from src.data.factory import get_filings_provider
from src.research.ingest.going_concern import html_to_text
from src.research.store.models import FilingIndexRow, FilingSectionRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

SECTIONS: dict[str, tuple[tuple[str, str, int], ...]] = {
    # form -> (item, label, character cap)
    "10-K": (
        ("1", "Item 1 Business", 24_000),
        ("1A", "Item 1A Risk Factors", 16_000),
        ("7", "Item 7 MD&A", 24_000),
    ),
    "10-Q": (("2", "Item 2 MD&A", 24_000),),
    "20-F": (("4", "Item 4 The Company", 24_000), ("5", "Item 5 Operating Review", 24_000)),
}
_HEADING = re.compile(r"\bItem\s+(\d{1,2}[A-C]?)\s*[.:\-—]", re.I)


def _base_form(form: str) -> str:
    return form.removesuffix("/A")


def slice_sections(text: str, form: str) -> dict[str, str]:
    """The sections of *form* found in *text* (plain text), each the longest span from its
    heading to the next item heading, capped. Missing sections are absent."""
    wanted = SECTIONS.get(_base_form(form), ())
    heads = [(m.start(), m.group(1).upper()) for m in _HEADING.finditer(text)]
    out: dict[str, str] = {}
    for item, label, cap in wanted:
        best = ""
        for i, (start, name) in enumerate(heads):
            if name != item:
                continue
            end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
            span = text[start:end].strip()
            if len(span) > len(best):
                best = span
        if best:
            out[label] = best[:cap]
    return out


def ingest_filing_sections(symbol: str, cik: str) -> int:
    """Slice the filer's newest periodic filing if it has not been sliced. Returns sections
    stored; 0 (no network) when there is nothing new. A document that does not come back raises,
    so the drain retries the job."""
    with research_session() as session:
        newest = (
            session.query(FilingIndexRow)
            .filter(
                FilingIndexRow.cik == cik,
                FilingIndexRow.form.in_([f for base in SECTIONS for f in (base, base + "/A")]),
                FilingIndexRow.primary_document.is_not(None),
            )
            .order_by(FilingIndexRow.filed.desc(), FilingIndexRow.accn.desc())
            .first()
        )
        if newest is None:
            return 0
        accn, form, document = newest.accn, newest.form, newest.primary_document
        done = session.query(FilingSectionRow.id).filter(FilingSectionRow.accn == accn).first()
    if done is not None:
        return 0
    assert document is not None
    raw = get_filings_provider().get_filing_text(cik, accn, document)
    if not raw:
        raise RuntimeError(f"No document for {symbol} {accn}")
    sections = slice_sections(html_to_text(raw), form)
    now = datetime.now(UTC).replace(tzinfo=None)
    with research_session() as session:
        for label, text in sections.items():
            session.add(
                FilingSectionRow(
                    accn=accn, cik=cik, form=form, section=label, text=text, fetched_at=now
                )
            )
        if not sections:  # remember the read: an empty marker row, so it is not refetched
            session.add(
                FilingSectionRow(accn=accn, cik=cik, form=form, section="", text="", fetched_at=now)
            )
    log.info("Filing sections for %s %s: %s", symbol, accn, sorted(sections) or "none found")
    return len(sections)
