"""The research worker's ``submissions`` job (value book spec §7.1 trigger 4, §8.5): each filer's
EDGAR ``submissions/CIK##########.json`` feed, read daily, kept as one ``filing_index`` row per
recent filing with its form, dates and 8-K item tags. No text is read here: the item tags come
with the feed.

The research worker owns every SEC fetch (spec §6.9); the value process reads ``filing_index``
read-only through ``src/common/value_inputs.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from src.data.factory import get_filings_provider
from src.research.store.models import FilingIndexRow, SubmissionsStateRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

KEEP_DAYS = 400  # a filing older than this is dropped from the index
PERIODIC_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
EVENT_FORMS = ("8-K", "8-K/A")
FORMS = (*PERIODIC_FORMS, *EVENT_FORMS)


@dataclass(frozen=True, slots=True)
class ParsedFiling:
    accn: str
    form: str
    filed: date
    report_date: date | None
    items: tuple[str, ...]
    primary_document: str | None


def _date(raw: object) -> date | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def parse_submissions(payload: dict, *, since: date) -> list[ParsedFiling]:
    """The periodic and 8-K filings in the feed's ``filings.recent`` block filed on or after
    *since*. The block is column arrays of equal length; a malformed row is skipped."""
    recent = (payload.get("filings") or {}).get("recent") or {}
    accns = recent.get("accessionNumber") or []
    out: list[ParsedFiling] = []
    for i, accn in enumerate(accns):

        def col(name: str, i: int = i) -> object:
            values = recent.get(name) or []
            return values[i] if i < len(values) else None

        form = col("form")
        filed = _date(col("filingDate"))
        if not isinstance(accn, str) or form not in FORMS or filed is None or filed < since:
            continue
        items = col("items")
        doc = col("primaryDocument")
        out.append(
            ParsedFiling(
                accn=accn,
                form=str(form),
                filed=filed,
                report_date=_date(col("reportDate")),
                items=tuple(
                    t.strip() for t in (items if isinstance(items, str) else "").split(",") if t
                ),
                primary_document=doc if isinstance(doc, str) and doc else None,
            )
        )
    return out


def ingest_submissions(symbol: str, cik: str, *, today: date | None = None) -> int:
    """Read the feed (ETag-reused) and upsert the index. Returns rows written. A 304 only
    stamps the read; a failure raises so the drain retries the job."""
    today = today or datetime.now(UTC).date()
    with research_session() as session:
        state = session.get(SubmissionsStateRow, cik)
        etag_in = state.etag if state is not None else None
    payload, etag = get_filings_provider().get_submissions(cik, etag=etag_in)
    now = datetime.now(UTC).replace(tzinfo=None)
    if not payload:
        if etag_in is not None and etag == etag_in:
            with research_session() as session:
                seen = session.get(SubmissionsStateRow, cik)
                if seen is not None:
                    seen.fetched_at = now
            return 0
        raise RuntimeError(f"No submissions feed for {symbol} (CIK {cik})")
    since = today - timedelta(days=KEEP_DAYS)
    filings = parse_submissions(payload, since=since)
    with research_session() as session:
        for f in filings:
            row = session.get(FilingIndexRow, f.accn)
            if row is None:
                session.add(
                    FilingIndexRow(
                        accn=f.accn,
                        cik=cik,
                        form=f.form,
                        filed=f.filed,
                        report_date=f.report_date,
                        items=",".join(f.items),
                        primary_document=f.primary_document,
                    )
                )
            else:  # the feed's facts may be corrected; a going-concern read is kept
                row.form, row.filed, row.report_date = f.form, f.filed, f.report_date
                row.items, row.primary_document = ",".join(f.items), f.primary_document
        session.query(FilingIndexRow).filter(
            FilingIndexRow.cik == cik, FilingIndexRow.filed < since
        ).delete()
        state = session.get(SubmissionsStateRow, cik)
        if state is None:
            session.add(SubmissionsStateRow(cik=cik, etag=etag, fetched_at=now))
        else:
            state.etag, state.fetched_at = etag, now
    log.info("Submissions for %s: %d filings indexed", symbol, len(filings))
    return len(filings)
