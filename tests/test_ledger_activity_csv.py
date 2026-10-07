"""Activity Statement CSV parser (spec §5.1; R1, R2, R7, R11; Review Focus 1, 5)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.ledger.activity_csv import NotAnActivityStatement, parse_activity_csv

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


@pytest.fixture(scope="module")
def st():
    return parse_activity_csv(FIXTURE.read_text(encoding="utf-8"))


def test_statement_metadata(st) -> None:
    assert st.account == "U0000001"
    assert st.base_currency == "SGD"
    assert (st.period_start, st.period_end) == (date(2025, 4, 1), date(2026, 4, 1))
    assert st.fatal is False


def test_execution_count_excludes_subtotals_totals_and_forex(st) -> None:
    assert len(st.executions) == 15
    assert all(e.source_kind == "order" and e.exec_id is None for e in st.executions)


def test_option_open_row_fields(st) -> None:
    e = next(
        x
        for x in st.executions
        if x.contract.ident == "OPT:NVDA:20250627:P:138:USD" and x.quantity < 0
    )
    assert (e.quantity, e.price, e.proceeds, e.codes) == (-1.0, 1.31, 131.0, "O")
    assert e.commission == pytest.approx(-1.0446)
    assert e.trade_time == datetime(2025, 6, 17, 14, 2, 11, tzinfo=UTC)


def test_expiry_and_assignment_codes_are_kept(st) -> None:
    exp = next(
        x
        for x in st.executions
        if x.contract.ident.startswith("OPT:AMZN:20250718") and x.quantity > 0
    )
    assert (exp.codes, exp.price) == ("C;Ep", 0.0)
    delivery = next(
        x for x in st.executions if x.contract.ident == "STK:AMZN:USD" and x.quantity > 0
    )
    assert delivery.codes == "A;O"


def test_multiplier_comes_from_instrument_section(st) -> None:
    # Review Focus 5 — OPEN1 is an adjusted contract with multiplier 50.
    e = next(x for x in st.executions if x.contract.underlying == "OPEN1")
    assert e.contract.multiplier == 50.0
    nvda = next(x for x in st.executions if x.contract.underlying == "NVDA")
    assert nvda.contract.multiplier == 100.0


def test_ibkr_realized_pnl_is_kept_for_cross_check(st) -> None:
    sold = next(x for x in st.executions if x.contract.ident == "STK:AMZN:USD" and x.quantity < 0)
    assert sold.ibkr_realized_pnl == pytest.approx(2576.968262)


def test_forex_row_becomes_an_fx_rate(st) -> None:
    assert len(st.fx_rates) == 1
    fx = st.fx_rates[0]
    assert (fx.currency, fx.rate_date) == ("SGD", date(2026, 1, 6))
    assert fx.usd_rate == pytest.approx(1 / 1.2795)


def test_cash_events(st) -> None:
    kinds = sorted((c.event_type, c.currency, c.amount) for c in st.cash_events)
    assert ("deposit", "USD", 45000.0) in kinds
    assert ("withdrawal", "SGD", -6371.24) in kinds
    assert ("dividend", "USD", 29.16) in kinds
    assert ("fee", "SGD", -0.04) in kinds
    assert ("interest", "SGD", 20.73) in kinds
    assert not any(c.currency.startswith("Total") for c in st.cash_events)
    div = next(c for c in st.cash_events if c.event_type == "dividend")
    assert div.underlying == "QDTE"


def test_identical_withholding_lines_get_distinct_occurrences(st) -> None:
    neg = [c for c in st.cash_events if c.event_type == "withholding" and c.amount == -8.75]
    assert sorted(c.occurrence_idx for c in neg) == [0, 1]


def test_corporate_action_parsed_and_total_skipped(st) -> None:
    assert len(st.corporate_actions) == 1
    ca = st.corporate_actions[0]
    assert (ca.event_date, ca.underlying, ca.quantity) == (date(2025, 11, 18), "OPEN", 30.0)


def test_pdf_is_rejected() -> None:
    with pytest.raises(NotAnActivityStatement):
        parse_activity_csv("%PDF-1.7 binary junk")


def test_random_csv_is_rejected() -> None:
    with pytest.raises(NotAnActivityStatement):
        parse_activity_csv("a,b,c\n1,2,3\n")


def test_broken_trades_row_is_fatal() -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace(
        '"2025-06-17, 10:02:11",-1,', '"2025-06-17, 10:02:11",abc,'
    )
    st = parse_activity_csv(text)
    assert st.fatal is True
    assert any(e.section == "Trades" for e in st.errors)


def test_unsupported_asset_category_only_warns() -> None:
    extra = 'Trades,Data,Order,Warrants,USD,OPENW,"2025-11-20, 10:00:00",30,0.2,0.2,-6,0,6,0,0,O\n'
    text = FIXTURE.read_text(encoding="utf-8").replace(
        "Trades,SubTotal", extra + "Trades,SubTotal", 1
    )
    st = parse_activity_csv(text)
    assert st.fatal is False
    assert any(e.section == "Trades:unsupported" for e in st.errors)


@pytest.mark.skipif(
    not os.environ.get("LEDGER_REAL_STATEMENT"),
    reason="set LEDGER_REAL_STATEMENT=/path/to/real/activity.csv to run against the operator's file",
)
def test_operators_real_statement_parses_cleanly() -> None:
    st = parse_activity_csv(
        Path(os.environ["LEDGER_REAL_STATEMENT"]).read_text(encoding="utf-8-sig")
    )
    assert st.fatal is False, [e for e in st.errors if e.section == "Trades"][:5]
    assert len(st.executions) == 608  # 485 option + 123 stock order rows (Apr-2025..Apr-2026 file)
