"""Tests for Phase 3 (Competitive Research Plan) — C7, C8, C9.

C7 — Skipped-trade reasons formatter
C8 — P&L calendar formatter + richer order notification cards
C9 — Named trading profiles (deep-merge, overlay, get_effective_risk/weights)
"""

from __future__ import annotations

from datetime import date

from src.common.profile import (
    VALID_PROFILES,
    _deep_merge,
    activate,
    active,
    get_effective_risk,
    get_effective_weights,
)
from src.notify.formatters import (
    format_order_notification,
    format_pnl_calendar,
    format_profile_status,
    format_skip_reasons,
)

# ---------------------------------------------------------------------------
# C9 — Profile: deep_merge
# ---------------------------------------------------------------------------


def test_deep_merge_top_level():
    base = {"a": 1, "b": 2}
    overlay = {"b": 99, "c": 3}
    result = _deep_merge(base, overlay)
    assert result == {"a": 1, "b": 99, "c": 3}


def test_deep_merge_nested():
    base = {
        "risk": {"covered_call": {"delta_max": 0.35, "dte_min": 21}, "income": {"min_roc_pct": 1.0}}
    }
    overlay = {"risk": {"covered_call": {"delta_max": 0.25}}}
    result = _deep_merge(base, overlay)
    assert result["risk"]["covered_call"]["delta_max"] == 0.25
    assert result["risk"]["covered_call"]["dte_min"] == 21  # preserved
    assert result["risk"]["income"]["min_roc_pct"] == 1.0  # preserved


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"x": 1}}
    overlay = {"a": {"x": 99}}
    _deep_merge(base, overlay)
    assert base["a"]["x"] == 1  # original unchanged


# ---------------------------------------------------------------------------
# C9 — Profile: activate / active / valid_profiles
# ---------------------------------------------------------------------------


def test_activate_default():
    activate("default")
    assert active() == "default"


def test_activate_conservative():
    activate("conservative")
    assert active() == "conservative"
    activate("default")  # reset


def test_activate_unknown_falls_back_to_default():
    activate("ultrarisky")
    assert active() == "default"


def test_valid_profiles_set():
    assert {"default", "conservative", "balanced", "aggressive"} == VALID_PROFILES


# ---------------------------------------------------------------------------
# C9 — Profile: get_effective_risk / get_effective_weights with overlay
# ---------------------------------------------------------------------------


def test_get_effective_risk_default_passes_through():
    activate("default")
    risk = get_effective_risk()
    # Should return the base risk dict unchanged — check a known key
    assert "covered_call" in risk
    assert "cash_secured_put" in risk


def test_get_effective_risk_conservative_tightens_delta():
    activate("conservative")
    risk = get_effective_risk()
    cc = risk["covered_call"]
    assert cc["delta_max"] <= 0.30, "Conservative should tighten delta_max below default 0.35"
    activate("default")


def test_get_effective_risk_aggressive_widens_delta():
    activate("aggressive")
    risk = get_effective_risk()
    cc = risk["covered_call"]
    assert cc["delta_max"] >= 0.35, "Aggressive should widen delta_max to at least default 0.35"
    activate("default")


def test_get_effective_weights_default_unchanged():
    activate("default")
    weights = get_effective_weights()
    assert "covered_call" in weights
    assert "cash_secured_put" in weights


def test_get_effective_weights_conservative_raises_score_floor():
    activate("conservative")
    weights = get_effective_weights()
    base_floor = 55  # default min_candidate_score in scoring_weights.yaml
    assert weights.get("min_candidate_score", base_floor) >= base_floor
    activate("default")


def test_get_effective_weights_aggressive_lowers_score_floor():
    activate("aggressive")
    weights = get_effective_weights()
    base_floor = 55
    assert weights.get("min_candidate_score", base_floor) <= base_floor
    activate("default")


# ---------------------------------------------------------------------------
# C9 — Profile: invalid profile YAML falls back gracefully
# ---------------------------------------------------------------------------


def test_get_effective_risk_missing_profile_falls_back():
    """A profile with no file returns the base dict unmodified."""
    activate("balanced")  # balanced.yaml has empty risk: {}
    risk = get_effective_risk()
    # Should be identical to default (no overlay keys)
    activate("default")
    default_risk = get_effective_risk()
    # Both should have the same top-level keys
    assert set(risk.keys()) == set(default_risk.keys())
    activate("default")


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


# ---------------------------------------------------------------------------
# C9 — format_profile_status
# ---------------------------------------------------------------------------


def test_format_profile_status_default():
    result = format_profile_status("default")
    assert "default" in result
    assert "📐" in result


def test_format_profile_status_conservative():
    result = format_profile_status("conservative")
    assert "conservative" in result


def test_format_profile_status_aggressive():
    result = format_profile_status("aggressive")
    assert "aggressive" in result


def test_format_profile_status_unknown():
    result = format_profile_status("mystery")
    assert "mystery" in result
