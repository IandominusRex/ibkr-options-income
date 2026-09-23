"""Cold-tier materialisation: cache-first, partial-when-truly-pending, sanitised reasons."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.research.ingest.fundamentals import ingest_fundamentals
from src.research.ingest.materialize import (
    MAX_ATTEMPTS,
    SectionState,
    drain_ingest_jobs,
    enqueue,
    materialize,
)
from src.research.schemas import LineItemValue, NormalizedFinancials, PeriodStatement
from src.research.store.models import IngestJobRow, QuoteRow, SymbolRow
from src.research.store.session import init_research_db, research_session


def _fin() -> NormalizedFinancials:
    """A stand-in the typed `MaterializeResult.fundamentals` field will accept."""
    return NormalizedFinancials(
        symbol="AAPL",
        cik="0000320193",
        entity_name="Apple Inc.",
        annual=[
            PeriodStatement(
                period_end=date(2024, 12, 31),
                period_type="annual",
                items={"revenue": LineItemValue(line_item="revenue", value=1.0)},
            )
        ],
    )


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


def test_unknown_symbol_is_unavailable_not_pending(db) -> None:
    """A ticker with no directory row will never resolve, so queueing it is a lie."""
    result = materialize("NOPE")
    assert result.fundamentals_state is SectionState.UNAVAILABLE
    assert result.reason


def test_a_warm_cache_hit_is_ready_without_calling_the_ingest(db, monkeypatch) -> None:
    """The defining property of the cache: a warm view serves from rows, not SEC.

    We seed the financials table directly (bypassing the ingest path), then assert
    that materialize returns READY and never calls ingest_fundamentals. A call to
    ingest_fundamentals would be a cache miss and a correctness regression.
    """
    # Seed the cache by ingesting through a fake provider, then clear the provider
    # so any later call would blow up.
    from tests.test_ingest_fundamentals import _FakeProvider, _payload

    provider = _FakeProvider(_payload())
    monkeypatch.setattr("src.research.ingest.fundamentals.get_filings_provider", lambda: provider)
    ingest_fundamentals("AAPL", "0000320193")

    # Now break the network path: if materialize calls ingest, this raises.
    def boom(symbol: str, cik: str):
        raise AssertionError("materialize hit the network on a warm cache")

    monkeypatch.setattr("src.research.ingest.materialize.ingest_fundamentals", boom)

    result = materialize("AAPL")
    assert result.fundamentals_state is SectionState.READY
    assert result.fundamentals is not None
    assert result.fundamentals.symbol == "AAPL"


def test_a_cold_cache_miss_calls_ingest_and_is_ready(db, monkeypatch) -> None:
    """No cached rows: materialize falls through to ingest and returns READY."""
    monkeypatch.setattr(
        "src.research.ingest.materialize.ingest_fundamentals",
        lambda symbol, cik: _fin(),
    )
    result = materialize("AAPL")
    assert result.fundamentals_state is SectionState.READY
    assert result.fundamentals is not None


def test_an_overrun_still_returns_ready_with_data(db, monkeypatch) -> None:
    """A slow ingest that finishes returns READY with its data, not PENDING.

    The old contract returned PENDING with data, which caused the client to poll and
    re-fetch indefinitely. A complete result is READY; a background refresh is queued
    so the NEXT view is instant, but THIS view shows what was built.
    """
    import time

    def slow(symbol: str, cik: str):
        time.sleep(0.05)
        return _fin()

    monkeypatch.setattr("src.research.ingest.materialize.ingest_fundamentals", slow)
    result = materialize("AAPL", budget_seconds=0.01)
    assert result.fundamentals_state is SectionState.READY
    assert result.fundamentals is not None

    # A warm refresh was queued so the next view is instant.
    with research_session() as s:
        assert s.query(IngestJobRow).filter_by(symbol="AAPL", status="pending").count() == 1


def test_a_failing_ingest_is_unavailable_with_a_sanitised_reason(db, monkeypatch) -> None:
    """The reason must be a fixed user-facing string, never str(exc).

    A RuntimeError carrying a CIK or a transport detail must not reach the browser.
    The full error is logged; the user sees a sanitised explanation.
    """

    def boom(symbol: str, cik: str):
        raise RuntimeError("connection reset by peer; CIK 0000320193")

    monkeypatch.setattr("src.research.ingest.materialize.ingest_fundamentals", boom)
    result = materialize("AAPL")
    assert result.fundamentals_state is SectionState.UNAVAILABLE
    assert result.reason is not None
    # The CIK and the transport detail must not leak.
    assert "0000320193" not in result.reason
    assert "connection reset" not in result.reason
    # But the reason is still explanatory.
    assert result.reason


def test_pending_never_carries_fundamentals_data(db, monkeypatch) -> None:
    """PENDING is a true partial state: no data, only a reason.

    There is no code path in materialize that returns PENDING with a populated
    fundamentals field anymore. This test pins that contract.
    """
    # The only way to get PENDING now is to construct it directly; materialize
    # itself never returns PENDING (a finished ingest is READY, even if slow).
    # This test documents the invariant and guards against a regression.
    monkeypatch.setattr(
        "src.research.ingest.materialize.ingest_fundamentals",
        lambda symbol, cik: _fin(),
    )
    result = materialize("AAPL")
    if result.fundamentals_state is SectionState.PENDING:
        assert result.fundamentals is None


def test_no_filer_reason_is_user_facing(db) -> None:
    """The no-filer reason is a fixed string, not an exception or a code."""
    result = materialize("NOPE")
    assert result.reason == "No SEC filer record for this symbol"


def test_a_known_symbol_with_no_cik_still_enriches(db, monkeypatch) -> None:
    """A directory row with no CIK (e.g. TQQQ) only blocks fundamentals, not the rest.

    Unlike an unknown symbol (no row at all, see test_unknown_symbol_is_unavailable_not_pending),
    this symbol is one search/watchlist can already find, so a blank page would be a real
    regression, not an honest "will never resolve" answer.
    """
    with research_session() as s:
        s.add(SymbolRow(symbol="TQQQ", cik=None, name="ProShares UltraPro QQQ", is_etf=True))

    monkeypatch.setattr("src.research.ingest.materialize._technicals", lambda symbol: {"rsi": 50})
    monkeypatch.setattr("src.research.ingest.materialize._sentiment", lambda symbol: None)
    monkeypatch.setattr("src.research.ingest.materialize._news", lambda symbol: [])

    result = materialize("TQQQ")
    assert result.fundamentals_state is SectionState.UNAVAILABLE
    assert result.fundamentals_reason == "No SEC filer record for this symbol"
    assert result.technicals_state is SectionState.READY
    assert result.technicals == {"rsi": 50}
    assert result.checks_state is SectionState.READY


def test_a_missing_quote_is_seeded_on_demand(db, monkeypatch) -> None:
    """The first view of a symbol with no quote row yet must not sit blank for up to 15
    minutes waiting on the next refresh_quotes sweep — materialize() seeds one on
    demand, the same cold-path pattern the /bars route already uses for daily bars.

    Uses a no-CIK symbol (like test_a_known_symbol_with_no_cik_still_enriches) so the
    fundamentals path never touches the real SEC network client — this test is only
    about the quote section.
    """
    with research_session() as s:
        s.add(SymbolRow(symbol="TQQQ", cik=None, name="ProShares UltraPro QQQ", is_etf=True))
    monkeypatch.setattr("src.research.ingest.materialize._technicals", lambda symbol: {"rsi": 50})
    monkeypatch.setattr("src.research.ingest.materialize._sentiment", lambda symbol: None)
    monkeypatch.setattr("src.research.ingest.materialize._news", lambda symbol: [])
    monkeypatch.setattr("src.research.ingest.quotes.ingest_daily_bars", lambda sym: 0)
    monkeypatch.setattr(
        "src.research.ingest.quotes.get_price_provider",
        lambda: type("P", (), {"get_last_price": staticmethod(lambda sym: 68.8)})(),
    )

    result = materialize("TQQQ")
    assert result.quote == 68.8
    assert result.quote_state is SectionState.READY
    with research_session() as s:
        assert s.get(QuoteRow, "TQQQ") is not None


def test_a_warm_quote_is_served_without_a_new_fetch(db, monkeypatch) -> None:
    """A quote row that already exists is read straight from the table — cache-first,
    same as fundamentals; the on-demand path must not fire again."""
    with research_session() as s:
        s.add(SymbolRow(symbol="TQQQ", cik=None, name="ProShares UltraPro QQQ", is_etf=True))
        s.add(
            QuoteRow(
                symbol="TQQQ",
                price=68.8,
                change_pct=1.2,
                as_of=datetime.now(UTC),
                source="yfinance",
            )
        )
    monkeypatch.setattr("src.research.ingest.materialize._technicals", lambda symbol: {"rsi": 50})
    monkeypatch.setattr("src.research.ingest.materialize._sentiment", lambda symbol: None)
    monkeypatch.setattr("src.research.ingest.materialize._news", lambda symbol: [])

    def boom(symbol: str) -> bool:
        raise AssertionError("materialize refetched an already-warm quote")

    monkeypatch.setattr("src.research.ingest.quotes.refresh_quote_for", boom)

    result = materialize("TQQQ")
    assert result.quote == 68.8
    assert result.quote_state is SectionState.READY


def test_enqueue_deduplicates_pending_jobs(db) -> None:
    enqueue("AAPL", "fundamentals")
    enqueue("AAPL", "fundamentals")
    with research_session() as s:
        assert s.query(IngestJobRow).filter_by(symbol="AAPL", status="pending").count() == 1


def test_drain_marks_jobs_done(db, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.research.ingest.materialize.ingest_fundamentals",
        lambda symbol, cik: _fin(),
    )
    enqueue("AAPL", "fundamentals")
    assert drain_ingest_jobs() == 1
    with research_session() as s:
        assert s.query(IngestJobRow).filter_by(status="done").count() == 1


def test_drain_records_the_error_and_increments_attempts(db, monkeypatch) -> None:
    def boom(symbol: str, cik: str):
        raise RuntimeError("nope")

    monkeypatch.setattr("src.research.ingest.materialize.ingest_fundamentals", boom)
    enqueue("AAPL", "fundamentals")
    drain_ingest_jobs()
    with research_session() as s:
        job = s.query(IngestJobRow).filter_by(symbol="AAPL").one()
        assert job.attempts == 1
        assert "nope" in (job.last_error or "")
        assert job.status == "pending"  # retried next drain


def test_drain_gives_up_after_repeated_failures(db, monkeypatch) -> None:
    def boom(symbol: str, cik: str):
        raise RuntimeError("nope")

    monkeypatch.setattr("src.research.ingest.materialize.ingest_fundamentals", boom)
    enqueue("AAPL", "fundamentals")
    for _ in range(MAX_ATTEMPTS):
        drain_ingest_jobs()
    with research_session() as s:
        assert s.query(IngestJobRow).filter_by(symbol="AAPL").one().status == "failed"
