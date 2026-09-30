"""Tests for Phase 3 (Competitive Research Plan) — C7, C8.

C7 — Skipped-trade reasons formatter
C8 — P&L calendar formatter + richer order notification cards
"""

from __future__ import annotations

from datetime import date

from src.notify.formatters import (
    format_order_notification,
    format_pnl_calendar,
    format_skip_reasons,
)

# ---------------------------------------------------------------------------
# C7 — format_skip_reasons
# ---------------------------------------------------------------------------


def test_format_skip_reasons_empty_returns_empty_string():
    assert format_skip_reasons({}) == ""


def test_format_skip_reasons_single_symbol():
    result = format_skip_reasons({"AAPL": ["iv_rank_below_minimum"]})
    assert "AAPL" in result
    assert "iv" in result and "rank" in result  # escaped MarkdownV2 — underscores become \_
    assert "⏸️" in result


def test_format_skip_reasons_multiple_symbols_sorted():
    data = {
        "NVDA": ["delta_out_of_range"],
        "AAPL": ["iv_rank_below_minimum", "earnings_blackout"],
    }
    result = format_skip_reasons(data)
    # AAPL should come before NVDA (alphabetical sort)
    assert result.index("AAPL") < result.index("NVDA")


def test_format_skip_reasons_max_two_reasons_shown():
    result = format_skip_reasons({"MARA": ["r1", "r2", "r3", "r4"]})
    # Only 2 shown inline; rest indicated with "+N more"
    assert "r1" in result
    assert "r2" in result
    assert "r3" not in result
    assert "more" in result


def test_format_skip_reasons_truncates_at_max_symbols():
    data = {f"SYM{i:02d}": ["reason"] for i in range(20)}
    result = format_skip_reasons(data, max_symbols=15)
    assert "more symbols" in result or "more" in result


def test_format_skip_reasons_no_passing_symbol_included():
    # Symbols that passed should not appear (tested via skip-map logic, not formatter)
    data = {"TSLA": ["concentration_limit"]}
    result = format_skip_reasons(data)
    assert "TSLA" in result


# ---------------------------------------------------------------------------
# C8 — format_pnl_calendar
# ---------------------------------------------------------------------------


def test_format_pnl_calendar_empty():
    result = format_pnl_calendar([], days=30)
    assert "No fills" in result


def test_format_pnl_calendar_single_day():
    rows = [{"date": date(2026, 6, 15), "cashflow": 320.0, "fills": 2}]
    result = format_pnl_calendar(rows)
    assert "Jun 15" in result
    assert "320" in result
    assert "2 fills" in result


def test_format_pnl_calendar_negative_cashflow():
    rows = [{"date": date(2026, 6, 10), "cashflow": -150.0, "fills": 1}]
    result = format_pnl_calendar(rows)
    assert "150" in result
    assert "1 fill" in result


def test_format_pnl_calendar_total_shown():
    rows = [
        {"date": date(2026, 6, 15), "cashflow": 200.0, "fills": 1},
        {"date": date(2026, 6, 14), "cashflow": 100.0, "fills": 1},
    ]
    result = format_pnl_calendar(rows)
    assert "Total" in result
    assert "300" in result


# ---------------------------------------------------------------------------
# C8 — format_order_notification (richer cards)
# ---------------------------------------------------------------------------


def test_order_notification_sell_placed():
    result = format_order_notification(
        "placed",
        underlying="AAPL",
        strategy="covered_call",
        strike=190.0,
        right="C",
        expiry=date(2026, 7, 17),
        contracts=1,
        order_id=42,
        action="SELL",
    )
    assert "📬" in result
    assert "AAPL" in result
    assert "Close" not in result


def test_order_notification_keeps_half_dollar_strikes():
    """$13.5 used to render as "$14" — a different, real, listed strike."""
    result = format_order_notification(
        "failed",
        underlying="MARA",
        strategy="covered_call",
        strike=13.5,
        right="C",
        expiry=date(2026, 10, 9),
        contracts=10,
        order_id=10,
    )
    assert "$13.5 Call" in result
    assert "$14" not in result


def test_order_notification_whole_strike_has_no_decimals():
    result = format_order_notification(
        "failed",
        underlying="AMZN",
        strategy="cash_secured_put",
        strike=235.0,
        right="P",
        expiry=date(2026, 10, 16),
        contracts=4,
        order_id=12,
    )
    assert "$235 Put" in result


def test_order_notification_buy_placed_shows_close():
    result = format_order_notification(
        "placed",
        underlying="AAPL",
        strategy="covered_call",
        strike=190.0,
        right="C",
        expiry=date(2026, 7, 17),
        contracts=1,
        order_id=42,
        action="BUY",
    )
    assert "Close" in result


def test_order_notification_sell_filled_shows_opened():
    result = format_order_notification(
        "filled",
        underlying="AAPL",
        strategy="covered_call",
        strike=190.0,
        right="C",
        expiry=date(2026, 7, 17),
        contracts=1,
        order_id=42,
        action="SELL",
        filled_qty=1.0,
        avg_price=2.50,
    )
    assert "Opened" in result


def test_order_notification_buy_filled_shows_closed():
    result = format_order_notification(
        "filled",
        underlying="AAPL",
        strategy="covered_call",
        strike=190.0,
        right="C",
        expiry=date(2026, 7, 17),
        contracts=1,
        order_id=42,
        action="BUY",
        filled_qty=1.0,
        avg_price=1.25,
    )
    assert "Closed" in result


def test_order_notification_default_action_is_sell():
    result = format_order_notification(
        "filled",
        underlying="AAPL",
        strategy="covered_call",
        strike=190.0,
        right="C",
        expiry=date(2026, 7, 17),
        contracts=1,
        order_id=42,
        filled_qty=1.0,
        avg_price=2.50,
    )
    assert "Opened" in result  # default action="SELL"
