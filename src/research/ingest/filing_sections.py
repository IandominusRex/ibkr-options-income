"""The research worker's ``filing_sections`` job (value book spec §8.2 "Grounded facts", §8.5
"slicing a filing"). For the names the value book wants a filing read of (a plain file the value
process writes, ``src/common/value_keep_fresh.py``), the newest periodic filing's primary document
is fetched once and cut, deterministically, into the sections a reader needs: 10-K Items 1
(Business), 1A (Risk Factors) and 7 (MD&A); 10-Q Item 2 (MD&A); 20-F Items 4 and 5. A 40-F has no
item headings and is not sliced. Each section is capped so a filing read stays at ~15-25K tokens.

The heading match is a heuristic: a filing's table of contents names every item too, so of all
the spans that start at an item's heading and run to the next heading, the longest is kept, and a
span shorter than ``MIN_SECTION_CHARS`` (a table-of-contents line) is no section. Headings that
start a line are preferred, so an in-text "Part II, Item 1A." cross-reference neither starts nor
ends a span; a 10-Q's Item 2 is the one before its "PART II".
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
MIN_SECTION_CHARS = 200  # a table-of-contents line is far shorter than any real section
# "Item 7." / "Item 7 -" / "Item 7 – " / "ITEM 7 MANAGEMENT'S ...": a dash or colon, or a capital.
_HEADING = re.compile(r"\b(?i:item)\s+(\d{1,2}(?i:[A-C])?)(?:\s*[.:\-\u2013\u2014]|(?=\s+[A-Z]))")
_CROSS_REF = re.compile(r"\bPart\s+[IVX]+\s*,\s*$", re.I)  # "see Part II, Item 1A."
_PART = re.compile(r"(?:\bPART\s+(II|I)\b|(?:^|(?<=\n))Part\s+(II|I)\b)(?!\s*,\s*Item)")
_BLOCK = re.compile(r"(?i)</?(?:p|div|br|tr|li|h[1-6]|table)\b[^>]*>")
_BREAK = "\u00b6"


def _base_form(form: str) -> str:
    return form.removesuffix("/A")


def filing_text(raw: str) -> str:
    """A filing's HTML as plain text that keeps its block structure: one line per paragraph,
    table row or heading, so a heading can be told from a cross-reference in running prose."""
    text = html_to_text(_BLOCK.sub(f" {_BREAK} ", raw))
    return re.sub(rf" *{_BREAK}[ {_BREAK}]*", "\n", text).strip()


def _heads(text: str) -> list[tuple[int, str]]:
    """Every item heading, cross-references ("Part II, Item 1A.") left out."""
    out: list[tuple[int, str]] = []
    for m in _HEADING.finditer(text):
        if _CROSS_REF.search(text[max(0, m.start() - 24) : m.start()]):
            continue
        out.append((m.start(), m.group(1).upper()))
    return out


def _parts(text: str) -> list[tuple[int, str]]:
    return [(m.start(), m.group(1) or m.group(2)) for m in _PART.finditer(text)]


def _best_span(
    text: str,
    heads: list[tuple[int, str]],
    item: str,
    ends: list[int],
    *,
    first_part_only: bool,
    parts: list[tuple[int, str]],
) -> str:
    best = ""
    for i, (start, name) in enumerate(heads):
        if name != item:
            continue
        if first_part_only:
            before = [p for pos, p in parts if pos < start]
            if before and before[-1] != "I":
                continue  # a 10-Q's Part II Item 2 is not its MD&A
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        end = min([end, *(e for e in ends if e > start)])
        span = text[start:end].strip()
        if len(span) >= MIN_SECTION_CHARS and len(span) > len(best):
            best = span
    return best


def slice_sections(text: str, form: str) -> dict[str, str]:
    """The sections of *form* found in *text* (plain text, see ``filing_text``), each the longest
    span of at least ``MIN_SECTION_CHARS`` from its heading to the next item heading, capped.
    Headings that start a line win over mid-line ones when the text has line structure; a 10-Q's
    Item 2 is the one in Part I. Missing sections are absent."""
    base = _base_form(form)
    wanted = SECTIONS.get(base, ())
    heads = _heads(text)
    line_heads = [h for h in heads if h[0] == 0 or text[h[0] - 1] == "\n"]
    parts = _parts(text) if base == "10-Q" else []
    part_ii = [pos for pos, p in parts if p == "II"]
    out: dict[str, str] = {}
    for item, label, cap in wanted:
        best = ""
        for pool in ([line_heads] if len(line_heads) >= 2 else []) + [heads]:
            best = _best_span(
                text, pool, item, part_ii, first_part_only=base == "10-Q", parts=parts
            )
            if best:
                break
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
    sections = slice_sections(filing_text(raw), form)
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
