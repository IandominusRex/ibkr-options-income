"""Contract identity + time helpers shared by every ledger feed (spec §5, R2)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.schemas import LedgerParseError, ParsedStatement
from src.ledger.contracts import (
    et_date,
    parse_et_timestamp,
    parse_ibkr_date,
    parse_number,
    parse_option_symbol,
    stock_contract,
)


def test_parses_activity_statement_option_symbol() -> None:
    c = parse_option_symbol("AMD 29AUG25 157.5 P")
    assert (c.underlying, c.sec_type, c.right, c.strike, c.expiry, c.multiplier) == (
        "AMD",
        "OPT",
        "P",
        157.5,
        date(2025, 8, 29),
        100.0,
    )
    assert c.ident == "OPT:AMD:20250829:P:157.5:USD"


def test_integer_strike_ident_has_no_trailing_zero() -> None:
    assert parse_option_symbol("NVDA 27JUN25 138 P").ident == "OPT:NVDA:20250627:P:138:USD"


def test_multiplier_is_carried_not_assumed() -> None:
    c = parse_option_symbol("OPEN1 19SEP25 3 C", multiplier=50.0)
    assert c.multiplier == 50.0


def test_rejects_garbage_symbol() -> None:
    with pytest.raises(ValueError):
        parse_option_symbol("AMD")


def test_stock_ident_includes_currency() -> None:
    assert stock_contract("A17U", "SGD").ident == "STK:A17U:SGD"


def test_statement_time_is_eastern_summer_and_winter() -> None:
    assert parse_et_timestamp("2025-08-22, 10:11:57") == datetime(
        2025, 8, 22, 14, 11, 57, tzinfo=UTC
    )
    assert parse_et_timestamp("20260106;064936") == datetime(2026, 1, 6, 11, 49, 36, tzinfo=UTC)
    assert parse_et_timestamp("2025-08-22;10:11:57") == datetime(
        2025, 8, 22, 14, 11, 57, tzinfo=UTC
    )


def test_overnight_sgx_trade_keeps_its_eastern_date() -> None:
    # Review Focus 4: 22:30 ET on Nov 2 is 03:30 UTC on Nov 3 — the ET date wins.
    assert et_date(datetime(2025, 11, 3, 3, 30, tzinfo=UTC)) == date(2025, 11, 2)
    assert et_date(parse_et_timestamp("2025-11-02, 22:30:00")) == date(2025, 11, 2)


def test_parse_ibkr_date_accepts_both_formats() -> None:
    assert parse_ibkr_date("2025-06-13") == parse_ibkr_date("20250613") == date(2025, 6, 13)


def test_parse_number_strips_commas_and_rejects_blank() -> None:
    assert parse_number("-1,385.5") == -1385.5
    with pytest.raises(ValueError):
        parse_number(" ")


def test_only_trades_errors_are_fatal() -> None:
    warn = ParsedStatement(errors=[LedgerParseError(line=3, section="Dividends", message="x")])
    bad = ParsedStatement(errors=[LedgerParseError(line=9, section="Trades", message="x")])
    assert warn.fatal is False
    assert bad.fatal is True
