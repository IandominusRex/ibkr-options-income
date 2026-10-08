from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.config import SpreadsEventCfg, get_config
from src.common.schemas import GexLevels, SpreadCandidate, SpreadRiskContext
from src.spreads.risk import size, validate

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)  # Wed 10:30 EDT
_BASE = get_config().spreads
# Pinned explicitly so a YAML retune never silently changes these tests. The gate's own
# negative-gamma rule is tested under "skip"; the shipped "allow" has its own test below.
CFG = _BASE.model_copy(
    update={
        "enabled": True,
        "schedule": _BASE.schedule.model_copy(
            update={"entry_start": "09:35", "entry_end": "13:30"}
        ),
        "gex": _BASE.gex.model_copy(
            update={"negative_gamma_action": "skip", "flip_buffer_pct": 0.002}
        ),
        "selection": _BASE.selection.model_copy(
            update={
                "width": 5.0,
                "short_delta_max": 0.15,
                "min_credit_pct_of_width": 0.10,
                "max_leg_spread_pct": 0.30,
            }
        ),
        "risk": _BASE.risk.model_copy(
            update={
                "starting_capital_usd": 100_000.0,
                "max_loss_pct_of_capital": 0.10,
                "max_total_risk_pct_of_capital": 0.10,
                "max_daily_loss_pct_of_capital": 0.10,
                "max_contracts": 100,
                "max_open_spreads": 2,
                "max_trades_per_day": 2,
                "one_side_per_day": True,
                "min_excess_liquidity_usd": 10_000.0,
                "max_quote_age_seconds": 20.0,
                "events": [],
                "ex_dividend_dates": [],
            }
        ),
    }
)


def cand(now: datetime = NOW, **kw) -> SpreadCandidate:
    base = dict(
        spread_id="s1",
        side="put",
        expiry=now.astimezone(UTC).date() if "expiry" not in kw else kw["expiry"],
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        credit_mid=0.61,
        credit_natural=0.56,
        short_delta=-0.12,
        short_leg_spread_pct=0.07,
        long_leg_spread_pct=0.18,
        spot=690.0,
        quote_time=now,
    )
    base.update(kw)
    return SpreadCandidate(**base)


def lv(**kw) -> GexLevels:
    base = dict(
        as_of=NOW, spot=690.0, net_gex=1e9, regime="positive", flip=680.0, expected_move=6.0
    )
    base.update(kw)
    return GexLevels(**base)


def ctx(now: datetime = NOW, **kw) -> SpreadRiskContext:
    base = dict(
        now=now,
        levels=lv(),
        open_spreads=0,
        open_risk_usd=0.0,
        trades_today=0,
        realized_pnl_today_usd=0.0,
        excess_liquidity_usd=50_000.0,
        capital_usd=100_000.0,
    )
    base.update(kw)
    return SpreadRiskContext(**base)


def test_a_clean_candidate_passes_sized_to_ten_percent_of_capital() -> None:
    v = validate(cand(), ctx(), CFG)
    assert v.approved and v.reasons == []
    assert v.contracts == 22  # 10% of $100,000 ÷ (5 − 0.61) × 100 = 22.8


def test_size_follows_the_books_capital_and_the_contract_ceiling() -> None:
    assert size(cand(), CFG, 100_000.0) == 22
    assert size(cand(), CFG, 120_000.0) == 27  # capital grew with realized wins
    assert size(cand(), CFG, 90_000.0) == 20  # and shrank after losses
    assert size(cand(), CFG, 4_000.0) == 0  # 10% = $400 cannot cover one $439 max loss
    capped = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"max_contracts": 5})})
    assert size(cand(), capped, 100_000.0) == 5
    assert size(cand(credit_mid=-0.1), CFG, 100_000.0) == 0


@pytest.mark.parametrize(
    ("c_kw", "ctx_kw", "reason"),
    [
        ({}, {"levels": None}, "no_levels"),
        ({}, {"levels": lv(regime="negative")}, "negative_gamma"),
        ({}, {"levels": lv(regime="unknown")}, "regime_unknown"),
        ({}, {"levels": lv(flip=689.0)}, "near_gamma_flip"),
        ({"quote_time": NOW - timedelta(seconds=60)}, {}, "stale_quote"),
        ({"width": 10.0}, {}, "width_mismatch"),
        ({"credit_mid": 0.40}, {}, "credit_below_min"),
        ({"credit_natural": -0.01}, {}, "no_natural_credit"),
        ({"long_leg_spread_pct": 0.9}, {}, "quote_too_wide"),
        ({"short_delta": None}, {}, "no_delta"),
        ({"short_delta": -0.30}, {}, "delta_too_high"),
        ({"expiry": date(2026, 10, 8)}, {}, "not_0dte"),
        ({}, {"open_spreads": 2}, "max_open_spreads"),
        ({}, {"trades_today": 2}, "max_trades_per_day"),
        ({}, {"realized_pnl_today_usd": -10_000.0}, "daily_loss_limit"),
        ({}, {"open_risk_usd": 700.0}, "max_total_risk"),  # 700 + 22 × 439 > 10% of 100k
        ({}, {"capital_usd": 4_000.0}, "max_loss_per_trade"),
        ({}, {"excess_liquidity_usd": None}, "account_unknown"),
        ({}, {"excess_liquidity_usd": 5_000.0}, "excess_liquidity_floor"),
    ],
)
def test_each_gate_rejects(c_kw, ctx_kw, reason) -> None:
    v = validate(cand(**c_kw), ctx(**ctx_kw), CFG)
    assert not v.approved and v.contracts == 0
    assert reason in v.reasons


def test_disabled_config_rejects() -> None:
    v = validate(cand(), ctx(), CFG.model_copy(update={"enabled": False}))
    assert "spreads_disabled" in v.reasons


def test_negative_gamma_allowed_when_configured() -> None:
    allow = CFG.model_copy(
        update={"gex": CFG.gex.model_copy(update={"negative_gamma_action": "allow"})}
    )
    assert validate(cand(), ctx(levels=lv(regime="negative")), allow).approved


def test_negative_gamma_is_traded_by_default() -> None:
    assert _BASE.gex.negative_gamma_action == "allow"
    shipped = CFG.model_copy(update={"gex": _BASE.gex})
    assert validate(cand(), ctx(levels=lv(regime="negative")), shipped).approved


def test_whole_day_events_block_entries() -> None:
    fomc = [SpreadsEventCfg(day=date(2026, 10, 7), label="FOMC")]
    ev = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"events": fomc})})
    assert "event_day" in validate(cand(), ctx(), ev).reasons


def test_timed_events_block_only_until_their_time() -> None:
    speech = [SpreadsEventCfg(day=date(2026, 10, 7), until="10:45", label="Fed chair speech")]
    ev = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"events": speech})})
    assert "event_window" in validate(cand(), ctx(), ev).reasons  # NOW is 10:30
    eleven = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
    assert validate(cand(eleven), ctx(eleven), ev).approved
    other_day = [SpreadsEventCfg(day=date(2026, 10, 8), label="FOMC")]
    assert validate(
        cand(),
        ctx(),
        CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"events": other_day})}),
    ).approved


def test_no_call_spreads_around_an_ex_dividend_date() -> None:
    call = cand(side="call", short_strike=701.0, long_strike=706.0, short_delta=0.11)
    on_the_day = CFG.model_copy(
        update={"risk": CFG.risk.model_copy(update={"ex_dividend_dates": [date(2026, 10, 7)]})}
    )
    day_before = CFG.model_copy(
        update={"risk": CFG.risk.model_copy(update={"ex_dividend_dates": [date(2026, 10, 8)]})}
    )
    assert "ex_dividend_window" in validate(call, ctx(), on_the_day).reasons
    assert "ex_dividend_window" in validate(call, ctx(), day_before).reasons
    assert validate(cand(), ctx(), day_before).approved  # put spreads are unaffected
    later = CFG.model_copy(
        update={"risk": CFG.risk.model_copy(update={"ex_dividend_dates": [date(2026, 10, 9)]})}
    )
    assert validate(call, ctx(), later).approved


def test_one_side_per_day() -> None:
    assert "other_side_traded_today" in validate(cand(), ctx(sides_today=["call"]), CFG).reasons
    assert validate(cand(), ctx(sides_today=["put"]), CFG).approved
    off = CFG.model_copy(update={"risk": CFG.risk.model_copy(update={"one_side_per_day": False})})
    assert validate(cand(), ctx(sides_today=["call"]), off).approved


def test_opening_entries_start_at_0935() -> None:
    t0934 = datetime(2026, 10, 7, 13, 34, tzinfo=UTC)
    t0936 = datetime(2026, 10, 7, 13, 36, tzinfo=UTC)
    assert "outside_entry_window" in validate(cand(t0934), ctx(t0934), CFG).reasons
    assert validate(cand(t0936), ctx(t0936), CFG).approved


# Review Focus 5 — the ET clock for an operator in SGT.
def test_entry_window_tracks_et_across_dst() -> None:
    december_1030 = datetime(2026, 12, 2, 15, 30, tzinfo=UTC)  # EST: 10:30
    december_0930 = datetime(2026, 12, 2, 14, 30, tzinfo=UTC)  # EST: 09:30
    assert validate(cand(december_1030), ctx(december_1030), CFG).approved
    early = validate(cand(december_0930), ctx(december_0930), CFG)
    assert "outside_entry_window" in early.reasons


def test_holiday_and_early_close_days_are_skipped() -> None:
    thanksgiving = datetime(2026, 11, 26, 15, 30, tzinfo=UTC)
    black_friday = datetime(2026, 11, 27, 15, 30, tzinfo=UTC)
    assert "not_trading_day" in validate(cand(thanksgiving), ctx(thanksgiving), CFG).reasons
    assert "early_close_day" in validate(cand(black_friday), ctx(black_friday), CFG).reasons


def test_after_entry_end_is_outside_the_window() -> None:
    late = datetime(2026, 10, 7, 17, 31, tzinfo=UTC)  # 13:31 EDT
    assert "outside_entry_window" in validate(cand(late), ctx(late), CFG).reasons
