"""Normalisation assembles periods, persistence is idempotent, and the cache is warm."""

from __future__ import annotations

from datetime import date

import pytest

from src.research.ingest.fundamentals import ingest_fundamentals, load_cached_financials, normalize
from src.research.store.models import CompanyFactsRawRow, FinancialRow, SymbolRow
from src.research.store.session import init_research_db, research_session


def _payload() -> dict:
    def dur(y: int, val: float) -> dict:
        return {
            "start": f"{y}-01-01",
            "end": f"{y}-12-31",
            "val": val,
            "accn": f"acc-{y}",
            "fy": y,
            "fp": "FY",
            "form": "10-K",
            "filed": f"{y + 1}-02-01",
        }

    def inst(y: int, val: float) -> dict:
        return {
            "end": f"{y}-12-31",
            "val": val,
            "accn": f"acc-{y}",
            "fy": y,
            "fp": "FY",
            "form": "10-K",
            "filed": f"{y + 1}-02-01",
        }

    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [dur(2022, 100.0), dur(2023, 120.0)]}},
                "NetIncomeLoss": {"units": {"USD": [dur(2022, 10.0), dur(2023, 15.0)]}},
                "Assets": {"units": {"USD": [inst(2022, 500.0), inst(2023, 550.0)]}},
            }
        },
    }


class _FakeProvider:
    """Drop-in filings provider returning a fixed payload with a recorded etag.

    Simulates a 304 on the second call by returning an empty payload and the same
    etag, which is the contract EdgarFilingsProvider honours on a real 304.
    """

    def __init__(self, payload: dict, etag: str = "v1") -> None:
        self._payload = payload
        self._etag = etag
        self.calls: list[str | None] = []

    def get_company_facts(self, cik: str, *, etag: str | None = None) -> tuple[dict, str | None]:
        self.calls.append(etag)
        if etag == self._etag:
            # 304: empty payload, same etag.
            return {}, self._etag
        return self._payload, self._etag


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc."))


def test_normalize_builds_annual_periods_newest_first() -> None:
    fin = normalize(_payload(), "AAPL")
    assert fin.symbol == "AAPL"
    assert fin.entity_name == "Apple Inc."
    assert [p.period_end for p in fin.annual] == [date(2023, 12, 31), date(2022, 12, 31)]


def test_normalize_carries_filing_traceability() -> None:
    fin = normalize(_payload(), "AAPL")
    rev = fin.annual[0].items["revenue"]
    assert rev.value == 120.0
    assert rev.concept == "Revenues"
    assert rev.accn == "acc-2023"
    assert rev.filed == date(2024, 2, 1)
    assert rev.form == "10-K"


def test_normalize_mixes_duration_and_instant_into_one_period() -> None:
    fin = normalize(_payload(), "AAPL")
    period = fin.annual[0]
    assert period.items["revenue"].value == 120.0  # duration
    assert period.items["total_assets"].value == 550.0  # instant


def test_unmapped_line_items_are_absent_not_zero() -> None:
    """A line item the filer does not report must not appear as 0.0."""
    fin = normalize(_payload(), "AAPL")
    assert "dividends_paid" not in fin.annual[0].items


def test_normalize_on_an_empty_payload_yields_no_periods() -> None:
    fin = normalize({}, "XYZ")
    assert fin.annual == []
    assert fin.quarterly == []


def test_ingest_persists_rows_and_caches_the_raw_payload(db, monkeypatch) -> None:
    provider = _FakeProvider(_payload())
    monkeypatch.setattr("src.research.ingest.fundamentals.get_filings_provider", lambda: provider)
    fin = ingest_fundamentals("AAPL", "0000320193")
    assert fin is not None

    with research_session() as s:
        raw = s.get(CompanyFactsRawRow, "0000320193")
        assert raw is not None
        assert raw.etag == "v1"
        rows = s.query(FinancialRow).filter_by(symbol="AAPL", line_item="revenue").all()
        assert {r.value for r in rows} == {100.0, 120.0}
        # form is persisted so the cache can rebuild LineItemValue fully.
        assert all(r.form == "10-K" for r in rows)


def test_ingest_is_idempotent(db, monkeypatch) -> None:
    provider = _FakeProvider(_payload())
    monkeypatch.setattr("src.research.ingest.fundamentals.get_filings_provider", lambda: provider)
    ingest_fundamentals("AAPL", "0000320193")
    ingest_fundamentals("AAPL", "0000320193")

    with research_session() as s:
        rows = s.query(FinancialRow).filter_by(symbol="AAPL", line_item="revenue").all()
        assert len(rows) == 2  # two periods, not four


def test_ingest_reuses_cached_payload_on_304(db, monkeypatch) -> None:
    """A 304 must not be treated as 'no facts'. The cached raw payload is reused."""
    provider = _FakeProvider(_payload(), etag="v1")
    monkeypatch.setattr("src.research.ingest.fundamentals.get_filings_provider", lambda: provider)

    # First call: full fetch, caches the payload with etag v1.
    first = ingest_fundamentals("AAPL", "0000320193")
    assert first is not None
    assert provider.calls == [None]

    # Second call: provider returns 304 (empty payload, same etag). The cached
    # payload must be reused, so the result is identical.
    second = ingest_fundamentals("AAPL", "0000320193")
    assert second is not None
    assert provider.calls == [None, "v1"]
    assert [p.period_end for p in second.annual] == [p.period_end for p in first.annual]
    assert second.annual[0].items["revenue"].value == 120.0


def test_ingest_returns_none_when_the_filer_has_no_facts(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.fundamentals.get_filings_provider",
        lambda: type(
            "P", (), {"get_company_facts": staticmethod(lambda cik, *, etag=None: ({}, None))}
        )(),
    )
    assert ingest_fundamentals("XYZ", "0000000001") is None


def test_load_cached_financials_returns_none_when_no_rows(db) -> None:
    """A symbol that has never been ingested has no cached financials."""
    assert load_cached_financials("AAPL") is None


def test_load_cached_financials_rebuilds_from_rows_without_a_network_call(db, monkeypatch) -> None:
    """The warm path: after an ingest, load_cached_financials returns the same payload
    without calling the filings provider. A cache hit must never touch SEC."""
    provider = _FakeProvider(_payload())
    monkeypatch.setattr("src.research.ingest.fundamentals.get_filings_provider", lambda: provider)

    ingest_fundamentals("AAPL", "0000320193")
    provider.calls.clear()  # reset the call log

    cached = load_cached_financials("AAPL")
    assert cached is not None
    assert cached.symbol == "AAPL"
    assert cached.entity_name == "Apple Inc."
    assert [p.period_end for p in cached.annual] == [date(2023, 12, 31), date(2022, 12, 31)]
    rev = cached.annual[0].items["revenue"]
    assert rev.value == 120.0
    assert rev.concept == "Revenues"
    assert rev.accn == "acc-2023"
    assert rev.form == "10-K"
    # The cache read must not have called the provider.
    assert provider.calls == []
