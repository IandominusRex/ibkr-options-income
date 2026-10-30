"""The research worker's EDGAR submissions feed and going-concern read (value book spec §7, §7.1,
§8.5): the client, the parser, the two jobs, the drain."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from src.data.edgar_backend import EdgarClient, EdgarFilingsProvider
from src.research.ingest import going_concern as gc
from src.research.ingest import submissions as sub

FEED = {
    "cik": "320193",
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-26-000010",
                "0000320193-26-000009",
                "0000320193-26-000008",
                "0000320193-25-000001",
                "0000320193-26-000007",
            ],
            "filingDate": ["2026-10-20", "2026-10-02", "2026-08-01", "2025-05-01", "bad"],
            "reportDate": ["2026-10-17", "", "2026-06-28", "2025-03-29", ""],
            "form": ["8-K", "4", "10-Q", "10-Q", "8-K"],
            "items": ["5.02,9.01", "", "", "", "1.03"],
            "primaryDocument": ["a8k.htm", "x.xml", "a10q.htm", "old.htm", "b.htm"],
        }
    },
}


@pytest.fixture(autouse=True)
def _contact(monkeypatch):
    monkeypatch.setattr("src.data.edgar_backend._contact_email", lambda: "t@example.com")


def test_the_client_reads_the_feed_and_a_filing_document() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "submissions" in str(request.url):
            return httpx.Response(200, json=FEED, headers={"ETag": "e1"})
        return httpx.Response(200, text="<p>hello</p>")

    p = EdgarFilingsProvider(client=EdgarClient(transport=httpx.MockTransport(handler)))
    payload, etag = p.get_submissions("320193")
    assert payload["name"] == "Apple Inc." and etag == "e1"
    assert seen[0] == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert p.get_filing_text("0000320193", "0000320193-26-000008", "a10q.htm") == "<p>hello</p>"
    assert seen[1] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000008/a10q.htm"
    assert p.get_filing_text("", "x", "y") == ""


def test_a_failed_document_read_is_empty_not_an_error() -> None:
    p = EdgarFilingsProvider(
        client=EdgarClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(404)), max_retries=0
        )
    )
    assert p.get_filing_text("320193", "0000320193-26-000008", "a10q.htm") == ""
    assert p.get_submissions("320193") == ({}, None)


def test_the_parser_keeps_recent_periodic_and_8k_filings_with_their_items() -> None:
    out = sub.parse_submissions(FEED, since=date(2025, 10, 1))
    assert [(f.accn[-2:], f.form, f.items) for f in out] == [
        ("10", "8-K", ("5.02", "9.01")),
        ("08", "10-Q", ()),
    ]  # a Form 4 is skipped, a filing older than *since* too, and a row with a bad date
    assert out[1].report_date == date(2026, 6, 28) and out[0].primary_document == "a8k.htm"
    assert sub.parse_submissions({}, since=date(2025, 1, 1)) == []


class _Provider:
    def __init__(self, feeds: list[tuple[dict, str | None]], docs: dict[str, str] | None = None):
        self.feeds = feeds
        self.docs = docs or {}
        self.etags: list[str | None] = []

    def get_submissions(self, cik: str, *, etag: str | None = None) -> tuple[dict, str | None]:
        self.etags.append(etag)
        return self.feeds.pop(0)

    def get_filing_text(self, cik: str, accn: str, document: str) -> str:
        return self.docs.get(document, "")


@pytest.fixture()
def research_db(tmp_path, monkeypatch):
    from src.research.store.session import init_research_db

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def _index() -> list[tuple[str, str, str, bool | None]]:
    from src.research.store.models import FilingIndexRow
    from src.research.store.session import research_session

    with research_session() as s:
        return [
            (r.accn[-2:], r.form, r.items, r.going_concern)
            for r in s.query(FilingIndexRow).order_by(FilingIndexRow.accn)
        ]


def test_the_submissions_job_indexes_reuses_the_etag_and_keeps_a_read_flag(
    research_db, monkeypatch
) -> None:
    from src.research.store.models import FilingIndexRow
    from src.research.store.session import research_session

    provider = _Provider([(FEED, "e1"), ({}, "e1"), (FEED, "e2")])
    monkeypatch.setattr(sub, "get_filings_provider", lambda: provider)
    today = date(2026, 10, 30)
    assert sub.ingest_submissions("AAPL", "0000320193", today=today) == 2
    assert _index() == [("08", "10-Q", "", None), ("10", "8-K", "5.02,9.01", None)]
    assert sub.ingest_submissions("AAPL", "0000320193", today=today) == 0  # a 304
    with research_session() as s:
        s.get(FilingIndexRow, "0000320193-26-000008").going_concern = False
    assert sub.ingest_submissions("AAPL", "0000320193", today=today) == 2
    assert provider.etags == [None, "e1", "e1"]
    assert _index()[0] == ("08", "10-Q", "", False)  # a re-read keeps the going-concern read


def test_a_failed_feed_raises_so_the_drain_retries(research_db, monkeypatch) -> None:
    monkeypatch.setattr(sub, "get_filings_provider", lambda: _Provider([({}, None)]))
    with pytest.raises(RuntimeError, match="No submissions feed"):
        sub.ingest_submissions("AAPL", "0000320193", today=date(2026, 10, 30))


AUDITOR = (
    "<html><body><p>The accompanying financial statements have been prepared assuming that the "
    "Company will continue as a going concern. As discussed in Note 1, the Company has suffered "
    "recurring losses from operations that raise substantial doubt about its ability to continue "
    "as a going concern.</p></body></html>"
)
BOILERPLATE = (
    "<p>Management evaluated whether there are conditions that raise substantial doubt about the "
    "Company&#8217;s ability to continue as a going concern. There is no substantial doubt.</p>"
    "<p>A prolonged downturn could raise substantial doubt about our ability to continue as a "
    "going concern.</p><p>These matters have alleviated the substantial doubt that was raised "
    "about our ability to continue as a going concern.</p>"
)


def test_a_going_concern_doubt_is_flagged_only_when_the_filing_asserts_it() -> None:
    found = gc.detect_going_concern(AUDITOR)
    assert found is not None and found.startswith("As discussed in Note 1")
    assert gc.detect_going_concern(BOILERPLATE) is None
    management = "<div>These conditions raise substantial doubt about the Company’s ability to "
    management += "continue as a going concern within one year after the date of issuance.</div>"
    assert gc.detect_going_concern(management) is not None
    assert gc.html_to_text("<script>x</script><b>A&amp;B</b>") == "A&B"


def test_the_going_concern_job_reads_each_unread_periodic_filing_once(
    research_db, monkeypatch
) -> None:
    from src.research.store.models import FilingIndexRow
    from src.research.store.session import research_session

    with research_session() as s:
        for accn, form, filed, doc in (
            ("0000000001-26-000003", "10-Q", date(2026, 8, 1), "q.htm"),
            ("0000000001-26-000002", "8-K", date(2026, 8, 5), "k.htm"),
            ("0000000001-26-000001", "10-K", date(2026, 2, 10), "k10.htm"),
        ):
            s.add(
                FilingIndexRow(
                    accn=accn, cik="0000000001", form=form, filed=filed, primary_document=doc
                )
            )
    provider = _Provider([], docs={"q.htm": AUDITOR, "k10.htm": "<p>All good.</p>"})
    monkeypatch.setattr(gc, "get_filings_provider", lambda: provider)
    assert gc.ingest_going_concern("SICK", "0000000001", today=date(2026, 10, 30)) == 2
    assert gc.ingest_going_concern("SICK", "0000000001", today=date(2026, 10, 30)) == 0
    with research_session() as s:
        flags = {
            r.form: (r.going_concern, r.going_concern_detail is not None)
            for r in s.query(FilingIndexRow)
        }
    assert flags == {"10-Q": (True, True), "10-K": (False, False), "8-K": (None, False)}


def test_a_missing_document_raises_so_the_drain_retries(research_db, monkeypatch) -> None:
    from src.research.store.models import FilingIndexRow
    from src.research.store.session import research_session

    with research_session() as s:
        s.add(
            FilingIndexRow(
                accn="0000000001-26-000003",
                cik="0000000001",
                form="10-Q",
                filed=date(2026, 8, 1),
                primary_document="q.htm",
            )
        )
    monkeypatch.setattr(gc, "get_filings_provider", lambda: _Provider([]))
    with pytest.raises(RuntimeError, match="No document"):
        gc.ingest_going_concern("SICK", "0000000001", today=date(2026, 10, 30))


def test_the_drain_runs_both_new_job_kinds(research_db, monkeypatch) -> None:
    from src.research.ingest import materialize
    from src.research.store.models import IngestJobRow, SymbolRow
    from src.research.store.session import research_session

    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        materialize, "ingest_submissions", lambda s, c: calls.append(("sub", s, c)) or 3
    )
    monkeypatch.setattr(
        materialize, "ingest_going_concern", lambda s, c: calls.append(("gc", s, c)) or 1
    )
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193"))
    materialize.enqueue("AAPL", "submissions")
    materialize.enqueue("AAPL", "going_concern")
    materialize.enqueue("NOCIK", "submissions")
    assert materialize.drain_ingest_jobs() == 2
    assert calls == [("sub", "AAPL", "0000320193"), ("gc", "AAPL", "0000320193")]
    with research_session() as s:
        failed = s.query(IngestJobRow).filter_by(symbol="NOCIK").one()
    assert "Cannot run job kind" in (failed.last_error or "")


def test_a_failed_read_with_a_stored_etag_is_not_a_304(research_db, monkeypatch) -> None:
    """Review I1: a 5xx or an open breaker used to come back as ``(None, etag_in)``, which the job
    stamped as an unchanged feed and did not retry: a filing indexed after its session was
    stepped is never counted. A failure must raise; a real 304 must still only stamp."""
    from src.research.store.models import SubmissionsStateRow
    from src.research.store.session import research_session

    status = {"code": 200}

    def handler(_request: httpx.Request) -> httpx.Response:
        if status["code"] == 200:
            return httpx.Response(200, json=FEED, headers={"ETag": "e1"})
        return httpx.Response(status["code"])

    provider = EdgarFilingsProvider(
        client=EdgarClient(transport=httpx.MockTransport(handler), max_retries=0)
    )
    monkeypatch.setattr(sub, "get_filings_provider", lambda: provider)
    today = date(2026, 10, 30)
    assert sub.ingest_submissions("AAPL", "0000320193", today=today) == 2
    with research_session() as s:
        stamped = s.get(SubmissionsStateRow, "0000320193").fetched_at
    status["code"] = 503
    with pytest.raises(RuntimeError, match="No submissions feed"):
        sub.ingest_submissions("AAPL", "0000320193", today=today)
    with research_session() as s:
        row = s.get(SubmissionsStateRow, "0000320193")
        assert (row.etag, row.fetched_at) == ("e1", stamped)  # nothing was stamped
    status["code"] = 304
    assert sub.ingest_submissions("AAPL", "0000320193", today=today) == 0  # a 304 stamps only
    assert provider.get_submissions("320193", etag="e1") == ({}, "e1")
    status["code"] = 503
    assert provider.get_submissions("320193", etag="e1") == ({}, None)


def test_a_doubt_about_someone_else_or_one_since_resolved_is_not_flagged() -> None:
    third_party = (
        "<p>Losses at the tenant raise substantial doubt about its ability to continue as a "
        "going concern.</p>"
    )
    resolved = (
        "<p>Conditions that previously raised substantial doubt about our ability to continue as "
        "a going concern have been resolved.</p>"
    )
    customers = (
        "<p>Several of our customers report conditions that raise substantial doubt about their "
        "ability to continue as a going concern.</p>"
    )
    assert gc.detect_going_concern(third_party) is None
    assert gc.detect_going_concern(resolved) is None
    assert gc.detect_going_concern(customers) is None
    assert gc.detect_going_concern(AUDITOR) is not None  # the auditor's own paragraph still is
