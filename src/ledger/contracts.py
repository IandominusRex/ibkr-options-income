"""Contract identity and time helpers shared by every ledger feed (CSV, Flex, live)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from src.common.schemas import LedgerContract

ET = ZoneInfo("America/New_York")

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
        start=1,
    )
}
_OPT_RE = re.compile(
    r"^(?P<und>\S+) (?P<day>\d{2})(?P<mon>[A-Z]{3})(?P<yy>\d{2}) "
    r"(?P<strike>\d+(?:\.\d+)?) (?P<right>[PC])$"
)
_TIMESTAMP_FORMATS = ("%Y-%m-%d, %H:%M:%S", "%Y%m%d;%H%M%S", "%Y-%m-%d;%H:%M:%S", "%Y%m%d")
_DATE_FORMATS = ("%Y-%m-%d", "%Y%m%d")


def parse_option_symbol(
    symbol: str, *, currency: str = "USD", multiplier: float = 100.0
) -> LedgerContract:
    """``"AMD 29AUG25 157.5 P"`` -> an OPT contract. Raises ValueError on anything else."""
    m = _OPT_RE.match(symbol.strip())
    if m is None:
        raise ValueError(f"unrecognised option symbol {symbol!r}")
    month = _MONTHS.get(m["mon"])
    if month is None:
        raise ValueError(f"unrecognised month in option symbol {symbol!r}")
    return LedgerContract(
        underlying=m["und"],
        sec_type="OPT",
        currency=currency,
        right="P" if m["right"] == "P" else "C",
        strike=float(m["strike"]),
        expiry=date(2000 + int(m["yy"]), month, int(m["day"])),
        multiplier=multiplier,
    )


def stock_contract(symbol: str, currency: str) -> LedgerContract:
    return LedgerContract(underlying=symbol.strip(), sec_type="STK", currency=currency.strip())


def parse_et_timestamp(value: str) -> datetime:
    """An IBKR statement timestamp (US/Eastern wall clock) -> timezone-aware UTC."""
    v = value.strip()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            naive = datetime.strptime(v, fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=ET).astimezone(UTC)
    raise ValueError(f"unrecognised timestamp {value!r}")


def parse_ibkr_date(value: str) -> date:
    v = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}")


def et_date(ts: datetime) -> date:
    """The US/Eastern calendar date of a timestamp — the ledger's one trade-date definition."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(ET).date()


def parse_number(value: str) -> float:
    """``"1,385"`` -> 1385.0. Blank raises — callers decide whether blank is allowed."""
    v = value.strip().replace(",", "")
    if not v:
        raise ValueError("blank number")
    return float(v)
