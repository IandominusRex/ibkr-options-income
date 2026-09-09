"""Every headline number carries its source and its age, and staleness is derived."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from src.api.models.common import Envelope, Source, Sourced, as_utc, as_utc_opt


def test_sourced_is_generic_over_value_type() -> None:
    price: Sourced[float] = Sourced[float](
        value=191.24, source=Source.YFINANCE, as_of=datetime.now(UTC), stale=False
    )
    assert price.value == 191.24
    assert price.source == Source.YFINANCE


def test_of_marks_fresh_data_not_stale() -> None:
    s = Sourced.of(
        191.24,
        Source.YFINANCE,
        datetime.now(UTC) - timedelta(minutes=5),
        fresh_for=timedelta(minutes=30),
    )
    assert s.stale is False


def test_of_marks_old_data_stale() -> None:
    s = Sourced.of(
        191.24,
        Source.YFINANCE,
        datetime.now(UTC) - timedelta(hours=3),
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
        1.0,
        Source.EDGAR,
        datetime.utcnow() - timedelta(days=2),
        fresh_for=timedelta(days=1),
    )
    assert s.stale is True


def test_naive_as_of_comes_back_tz_aware_not_just_correctly_compared() -> None:
    """A naive as_of must be normalized in the stored value too, not only for the internal
    staleness comparison — otherwise the serialized JSON has no UTC offset, and a browser's
    Date parser reads it as local time, silently shifting the displayed age.
    """
    naive = datetime.utcnow() - timedelta(minutes=45)
    assert naive.tzinfo is None
    s = Sourced.of(1.0, Source.YFINANCE, naive, fresh_for=timedelta(minutes=30))
    assert s.as_of.tzinfo is not None
    assert s.model_dump_json().count("Z") >= 1 or "+00:00" in s.model_dump_json()


def test_envelope_carries_top_level_as_of() -> None:
    class Payload(Envelope):
        symbol: str

    p = Payload(symbol="AAPL", as_of=datetime.now(UTC))
    assert p.symbol == "AAPL"
    assert p.as_of is not None


def test_as_utc_on_naive_returns_same_wall_clock_time_tz_aware_utc() -> None:
    naive = datetime(2026, 9, 9, 12, 0)
    result = as_utc(naive)
    assert result.tzinfo is not None
    assert result == naive.replace(tzinfo=UTC)


def test_an_aware_datetime_survives_unchanged() -> None:
    aware = datetime(2026, 9, 9, 12, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert as_utc(aware) is aware or as_utc(aware) == aware
    assert as_utc(aware).utcoffset() == timedelta(hours=-4)


def test_the_optional_variant_passes_none_through() -> None:
    assert as_utc_opt(None) is None


def test_the_optional_variant_matches_as_utc_for_a_naive_datetime() -> None:
    naive = datetime(2026, 9, 9, 12, 0)
    assert as_utc_opt(naive) == as_utc(naive)


def test_no_module_defines_its_own_as_utc() -> None:
    """Two implementations became two signatures. A third would become three."""
    offenders = [
        str(p)
        for p in Path("src/api").rglob("*.py")
        if "def _as_utc" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"local _as_utc copies remain: {offenders}"
