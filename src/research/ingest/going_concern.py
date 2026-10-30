"""The research worker's ``going_concern`` job (value book spec §7: "a going-concern flag in the
filing" is a thesis exit). For the names the value book holds in its shadow record (the keep-fresh
list), each recent 10-K/10-Q's primary document is read once and scanned, deterministically, for a
going-concern doubt that the filing **asserts** (the auditor's paragraph or management's
conclusion), never one it merely mentions: a sentence must say the conditions "raise" substantial
doubt about the ability to continue as a going concern, with no hedge or negation in it ("could",
"may", "if", "whether", "no", "not", "alleviated", ...). Only the flag and the sentence are stored.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import UTC, date, datetime, timedelta

from src.data.factory import get_filings_provider
from src.research.ingest.submissions import KEEP_DAYS, PERIODIC_FORMS
from src.research.store.models import FilingIndexRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

MAX_PER_JOB = 2  # filings read per job (a 10-K can be tens of megabytes)
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_DOUBT = re.compile(r"substantial\s+doubt\b.*\bgoing\s+concern\b", re.I)
_ASSERT = re.compile(r"\braise[sd]?\b", re.I)
_HEDGE = re.compile(
    r"\b(no|not|none|could|can|may|might|would|should|if|whether|unless|absent|absence|"
    r"alleviat\w*|mitigat\w*|evaluat\w*|assess\w*|"
    # someone else's doubt (a tenant, a customer, a borrower ...) is not the filer's
    r"tenants?|customers?|suppliers?|vendors?|borrowers?|lessees?|licensees?|counterpart\w*|"
    # a doubt the filing says is over
    r"resolved|eliminated|removed|overcome)\b|\bno\s+longer\b|\bpreviously\s+raised\b",
    re.I,
)


def html_to_text(raw: str) -> str:
    """Tags out, entities decoded, whitespace collapsed (curly apostrophes made plain)."""
    text = _TAG.sub(" ", _SCRIPT.sub(" ", raw))
    return _SPACE.sub(" ", html.unescape(text)).replace("’", "'").strip()


def detect_going_concern(raw: str) -> str | None:
    """The first sentence asserting substantial doubt about the ability to continue as a going
    concern, cut to 300 characters; None when the filing asserts none."""
    for sentence in _SENTENCE.split(html_to_text(raw)):
        if _DOUBT.search(sentence) and _ASSERT.search(sentence) and not _HEDGE.search(sentence):
            return sentence[:300]
    return None


def ingest_going_concern(symbol: str, cik: str, *, today: date | None = None) -> int:
    """Read the unread recent periodic filings of one filer (newest first, ``MAX_PER_JOB`` at a
    time). Returns how many were read; 0 (no network) when none is unread. A document that does
    not come back raises, so the drain retries the job."""
    today = today or datetime.now(UTC).date()
    since = today - timedelta(days=KEEP_DAYS)
    with research_session() as session:
        todo = [
            (r.accn, r.primary_document)
            for r in session.query(FilingIndexRow)
            .filter(
                FilingIndexRow.cik == cik,
                FilingIndexRow.form.in_(PERIODIC_FORMS),
                FilingIndexRow.going_concern.is_(None),
                FilingIndexRow.primary_document.is_not(None),
                FilingIndexRow.filed >= since,
            )
            .order_by(FilingIndexRow.filed.desc())
            .limit(MAX_PER_JOB)
        ]
    provider = get_filings_provider()
    for accn, document in todo:
        assert document is not None
        text = provider.get_filing_text(cik, accn, document)
        if not text:
            raise RuntimeError(f"No document for {symbol} {accn}")
        found = detect_going_concern(text)
        with research_session() as session:
            row = session.get(FilingIndexRow, accn)
            if row is not None:
                row.going_concern = found is not None
                row.going_concern_detail = found
        if found:
            log.warning("Going-concern doubt in %s %s: %s", symbol, accn, found)
    return len(todo)
