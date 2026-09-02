"""Shared response primitives: provenance envelope and the response base.

Design §4.5: every headline number ships as {value, source, as_of, stale}, and every
response carries a top-level as_of. `stale` is DERIVED from as_of, never passed in by a
caller who might guess wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel


class Source(StrEnum):
    """Where a number came from. A Black-Scholes delta must not look like an IBKR one."""

    EDGAR = "edgar"
    YFINANCE = "yfinance"
    STOOQ = "stooq"
    IBKR = "ibkr"
    COMPUTED = "computed"


def _as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes. Treat naive as UTC rather than raising."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class Sourced[T](BaseModel):
    """One value with its provenance. `value` is None when the data was unavailable."""

    value: T | None = None
    source: Source
    as_of: datetime
    stale: bool = False

    @classmethod
    def of(
        cls,
        value: T | None,
        source: Source,
        as_of: datetime,
        *,
        fresh_for: timedelta,
    ) -> Sourced[T]:
        """Build a Sourced, deriving `stale` from how old `as_of` is."""
        age = datetime.now(UTC) - _as_utc(as_of)
        return cls(value=value, source=source, as_of=as_of, stale=age > fresh_for)


class Envelope(BaseModel):
    """Base for every response body. Carries the payload-level freshness stamp."""

    as_of: datetime
