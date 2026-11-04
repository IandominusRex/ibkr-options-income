"""The research worker's ``filing_sections`` job (value book spec §8.2, §8.5): slicing a filing
to the sections a filing read needs, the job, the drain, and the readers on the value side."""

from __future__ import annotations

from datetime import date

import pytest

from src.research.ingest import filing_sections as fs

TOC = "Table of Contents Item 1. Business 3 Item 1A. Risk Factors 9 Item 7. MD&A 30 Item 8. 50 "
BODY = (
    "Item 1. Business We make widgets for hospitals and sell them under contract. "
    "Item 1A. Risk Factors Our largest customer accounted for 18% of revenue. "
    "Item 1B. Unresolved Staff Comments None. "
    "Item 7. Management's Discussion Revenue grew 12% to $1,600 million on volume. "
    "Item 8. Financial Statements ..."
)
TEN_K = f"<html><body><p>{TOC}</p><p>{BODY}</p></body></html>"


def test_a_10k_is_cut_into_items_1_1a_and_7_skipping_the_table_of_contents() -> None:
    out = fs.slice_sections(TOC + BODY, "10-K")
    assert sorted(out) == ["Item 1 Business", "Item 1A Risk Factors", "Item 7 MD&A"]
    assert out["Item 1A Risk Factors"].startswith("Item 1A. Risk Factors Our largest customer")
    assert out["Item 1A Risk Factors"].endswith("18% of revenue.")  # stops at Item 1B
    assert "$1,600 million" in out["Item 7 MD&A"] and "Item 8" not in out["Item 7 MD&A"]


def test_caps_amendments_and_forms_without_items() -> None:
    long = "Item 2. Management's Discussion " + "x" * 30_000 + " Item 3. Quantitative"
    out = fs.slice_sections(long, "10-Q/A")
    assert len(out["Item 2 MD&A"]) == 24_000
    assert fs.slice_sections("Annual report under the MJDS", "40-F") == {}


class _Provider:
    def __init__(self, docs: dict[str, str]) -> None:
        self.docs, self.reads = docs, 0

    def get_filing_text(self, cik: str, accn: str, document: str) -> str:
        self.reads += 1
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
    return tmp_path / "research.db"


def _index(*rows: tuple[str, str, date, str]) -> None:
    from src.research.store.models import FilingIndexRow, SymbolRow
    from src.research.store.session import research_session

    with research_session() as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001"))
        for accn, form, filed, doc in rows:
            s.add(
                FilingIndexRow(
                    accn=accn, cik="0000000001", form=form, filed=filed, primary_document=doc
                )
            )


def test_the_job_slices_the_newest_periodic_filing_once(research_db, monkeypatch) -> None:
    from src.research.store.models import FilingSectionRow
    from src.research.store.session import research_session

    _index(
        ("0000000001-26-000001", "10-K", date(2026, 2, 10), "k.htm"),
        ("0000000001-26-000002", "8-K", date(2026, 3, 1), "e.htm"),
    )
    provider = _Provider({"k.htm": TEN_K})
    monkeypatch.setattr(fs, "get_filings_provider", lambda: provider)
    assert fs.ingest_filing_sections("STDY", "0000000001") == 3
    assert fs.ingest_filing_sections("STDY", "0000000001") == 0 and provider.reads == 1
    with research_session() as s:
        assert {r.section for r in s.query(FilingSectionRow)} == {
            "Item 1 Business",
            "Item 1A Risk Factors",
            "Item 7 MD&A",
        }


def test_a_missing_document_raises_so_the_drain_retries(research_db, monkeypatch) -> None:
    _index(("0000000001-26-000001", "10-Q", date(2026, 8, 1), "q.htm"))
    monkeypatch.setattr(fs, "get_filings_provider", lambda: _Provider({}))
    with pytest.raises(RuntimeError, match="No document"):
        fs.ingest_filing_sections("STDY", "0000000001")


def test_the_drain_runs_the_job_and_the_sweep_queues_the_files_names(
    research_db, monkeypatch, tmp_path
) -> None:
    from src.common import value_keep_fresh as kf
    from src.research.ingest import materialize, value_universe

    calls: list[str] = []
    monkeypatch.setattr(materialize, "ingest_filing_sections", lambda s, c: calls.append(s) or 1)
    _index()
    materialize.enqueue("STDY", "filing_sections")
    assert materialize.drain_ingest_jobs() == 1 and calls == ["STDY"]
    monkeypatch.setattr(kf, "FILING_READS_FILE", tmp_path / "reads.json")
    monkeypatch.setattr(kf, "KEEP_FRESH_FILE", tmp_path / "keep.json")
    kf.write_filing_reads(["stdy"])
    assert kf.read_filing_reads() == ["STDY"]
    counts = value_universe.enqueue_value_universe(["STDY"], bars_only=())
    assert counts["filing_sections"] == 1


def test_the_value_side_reads_the_newest_periodic_filing_and_its_sections(
    research_db, monkeypatch
) -> None:
    from src.common import value_inputs as vi
    from src.research.store.models import FilingSectionRow
    from src.research.store.session import research_session

    _index(
        ("0000000001-26-000001", "10-K", date(2026, 2, 10), "k.htm"),
        ("0000000001-26-000003", "10-Q", date(2026, 5, 5), "q.htm"),
        ("0000000001-26-000004", "8-K", date(2026, 6, 1), "e.htm"),
    )
    with research_session() as s:
        s.add(
            FilingSectionRow(
                accn="0000000001-26-000003",
                cik="0000000001",
                form="10-Q",
                section="Item 2 MD&A",
                text="Revenue grew.",
                fetched_at=date(2026, 5, 6),
            )
        )
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(research_db))
    vi.reset_engine()
    with vi.research_read() as rs:
        assert rs is not None
        latest = vi.latest_periodic(rs, ["STDY", "NONE"])
        assert list(latest) == ["STDY"] and latest["STDY"].accn == "0000000001-26-000003"
        (sec,) = vi.filing_sections(rs, "0000000001-26-000003")
        assert (sec.form, sec.section, sec.text) == ("10-Q", "Item 2 MD&A", "Revenue grew.")
        assert vi.filing_sections(rs, "0000000001-26-000001") == []
    vi.reset_engine()
