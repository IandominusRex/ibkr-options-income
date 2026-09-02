"""Every headline number carries its source and its age, and staleness is derived."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.api.models.common import Envelope, Source, Sourced


def test_sourced_is_generic_over_value_type() -> None:
    price: Sourced[float] = Sourced[float](
        value=191.24, source=Source.YFINANCE, as_of=datetime.now(UTC), stale=False
    )
    assert price.value == 191.24
    assert price.source == Source.YFINANCE


def test_of_marks_fresh_data_not_stale() -> None:
    s = Sourced.of(
        191.24, Source.YFINANCE, datetime.now(UTC) - timedelta(minutes=5),
        fresh_for=timedelta(minutes=30),
    )
    assert s.stale is False


def test_of_marks_old_data_stale() -> None:
    s = Sourced.of(
        191.24, Source.YFINANCE, datetime.now(UTC) - timedelta(hours=3),
        fresh_for=timedelta(minutes=30),
    )
    assert s.stale is True


def test_missing_value_is_representable_and_still_carries_provenance() -> None:
    """A number we could not get is None with a source, never a silent zero."""
    s = Sourced.of(None, Source.EDGAR, datetime.now(UTC), fresh_for=timedelta(days=1))
    assert s.value is None
    assert s.source == Source.EDGAR


def test_naive_as_of_is_treated_as_utc() -> None:
    """SQLite hands back naive datetimes; comparing them to an aware now() would raise."""
    s = Sourced.of(
        1.0, Source.EDGAR, datetime.utcnow() - timedelta(days=2),
        fresh_for=timedelta(days=1),
    )
    assert s.stale is True


def test_envelope_carries_top_level_as_of() -> None:
    class Payload(Envelope):
        symbol: str

    p = Payload(symbol="AAPL", as_of=datetime.now(UTC))
    assert p.symbol == "AAPL"
    assert p.as_of is not None
