"""The sheet-format row (one shape for CSV export + Google Sheet) and trade filters (spec §6, §7)."""

from __future__ import annotations

from datetime import date

from src.reporting.trade_ledger import (
    SHEET_HEADER,
    build_option_trades,
    filter_trades,
    group_orders,
    sheet_row,
)
from tests.test_trade_ledger_trades import ex


def _trades():
    trades, _ = build_option_trades(
        group_orders(
            [
                ex("NVDA 27JUN25 138 P", "2025-06-17, 10:02:11", -1, 1.31, codes="O"),
                ex("NVDA 27JUN25 138 P", "2025-06-27, 11:09:57", 1, 0.01, codes="C"),
                ex("AMZN 18JUL25 207.5 P", "2025-06-25, 13:17:15", -1, 3.25, codes="O"),
                ex("AMZN 18JUL25 207.5 P", "2025-07-18, 16:20:00", 1, 0.0, comm=0.0, codes="C;Ep"),
                ex("GOOGL 01AUG25 197.5 C", "2025-07-28, 10:00:00", -1, 0.67, codes="O"),
            ]
        ),
        today=date(2025, 7, 30),
    )
    return trades


def test_sheet_header_starts_with_the_operators_columns() -> None:
    assert SHEET_HEADER[:13] == [
        "Sell/Buy",
        "Put/Call",
        "Order Date",
        "Expiration Date",
        "Ticker",
        "Lots",
        "Strike Price",
        "Premium",
        "Outcome",
        "Capital",
        "DTE",
        "% Profit",
        "Notes",
    ]


def test_sheet_row_values() -> None:
    nvda = next(t for t in _trades() if t.underlying == "NVDA")
    row = sheet_row(nvda)
    assert row[:9] == [
        "Sell",
        "Put",
        "2025-06-17",
        "2025-06-27",
        "NVDA",
        1,
        138,
        131.0,
        "Bought back",
    ]
    assert row[10] == 10 and row[11] == "34.65%"


def test_filters_and_sort() -> None:
    trades = _trades()
    assert [t.underlying for t in filter_trades(trades, symbol="amzn")] == ["AMZN"]
    assert [t.underlying for t in filter_trades(trades, outcome="Expired")] == ["AMZN"]
    assert [t.underlying for t in filter_trades(trades, right="C")] == ["GOOGL"]
    assert [
        t.underlying
        for t in filter_trades(trades, since=date(2025, 6, 20), until=date(2025, 6, 30))
    ] == ["AMZN"]
    assert [t.underlying for t in filter_trades(trades, sort="order_date")] == [
        "NVDA",
        "AMZN",
        "GOOGL",
    ]
    by_pct = filter_trades(trades, sort="-pct_profit")
    assert by_pct[0].pct_profit >= by_pct[1].pct_profit
