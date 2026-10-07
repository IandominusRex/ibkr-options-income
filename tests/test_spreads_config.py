"""config/spreads.yaml loads, and config load refuses any wheel/spreads overlap."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.common.config import (
    PRIVATE_CONFIG_FILES,
    Config,
    SpreadsCfg,
    SpreadsEntryCfg,
    SpreadsEventCfg,
    SpreadsScheduleCfg,
    get_config,
)


def _config(**overrides):
    base = get_config()
    fields = {name: getattr(base, name) for name in Config.model_fields}
    fields.update(overrides)
    return Config(**fields)


def test_shipped_config_is_disabled_shadow_spy() -> None:
    cfg = get_config()
    assert cfg.spreads.enabled is False
    assert cfg.spreads.mode == "shadow"
    assert (cfg.spreads.underlying, cfg.spreads.underlying_sec_type, cfg.spreads.exchange) == (
        "SPY",
        "STK",
        "SMART",
    )
    assert (cfg.spreads.gex.symbol, cfg.spreads.gex.sec_type) == ("SPX", "IND")
    assert cfg.spreads.gex.scale_to_underlying is None  # live SPY/SPX ratio
    assert cfg.spreads.exits.let_expire is False  # SPY settles in shares: never held to expiry
    assert cfg.ibkr.client_ids["spreads"] == 30


def test_shipped_sizing_is_ten_percent_of_a_100k_book() -> None:
    r = get_config().spreads.risk
    assert r.starting_capital_usd == 100_000.0
    assert (
        r.max_loss_pct_of_capital,
        r.max_total_risk_pct_of_capital,
        r.max_daily_loss_pct_of_capital,
    ) == (0.10, 0.10, 0.10)
    assert r.max_contracts == 100 and r.ex_dividend_dates == []


def test_risk_percentages_must_be_fractions() -> None:
    from src.common.config import SpreadsRiskCfg

    with pytest.raises(ValidationError):
        SpreadsRiskCfg(max_loss_pct_of_capital=10)  # 10 means 1000%, not 10%
    with pytest.raises(ValidationError):
        SpreadsRiskCfg(starting_capital_usd=0)


def test_client_ids_stay_unique() -> None:
    ids = list(get_config().ibkr.client_ids.values())
    assert len(ids) == len(set(ids))


def test_schedule_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        SpreadsScheduleCfg(entry_start="14:00", entry_end="13:00")


def test_schedule_rejects_unpadded_times() -> None:
    with pytest.raises(ValidationError):
        SpreadsScheduleCfg(map_time="9:45")


def test_traded_underlying_must_be_in_the_book() -> None:
    with pytest.raises(ValidationError):
        SpreadsCfg(underlying="SPY", book_underlyings=["XSP", "SPX"])


def test_book_underlyings_may_not_appear_in_the_wheel_universe() -> None:
    base = get_config()
    universe = {**base.universe, "watchlist": [*(base.universe.get("watchlist") or []), "XSP"]}
    with pytest.raises(ValidationError, match="XSP"):
        _config(universe=universe)


def test_enabled_spreads_must_fit_the_line_budget() -> None:
    base = get_config()
    spreads = base.spreads.model_copy(update={"enabled": True, "max_market_data_lines": 80})
    with pytest.raises(ValidationError, match="market-data"):
        _config(spreads=spreads)


def test_enabled_spreads_need_a_client_id() -> None:
    base = get_config()
    ids = {k: v for k, v in base.ibkr.client_ids.items() if k != "spreads"}
    ibkr = base.ibkr.model_copy(update={"client_ids": ids})
    spreads = base.spreads.model_copy(update={"enabled": True})
    with pytest.raises(ValidationError, match="client_ids.spreads"):
        _config(ibkr=ibkr, spreads=spreads)


def test_db_url_resolves_under_the_project_root() -> None:
    url = get_config().spreads_db_url_abs()
    assert url.startswith("sqlite:////") and url.endswith("/data/spreads.db")


def test_spreads_yaml_is_a_private_config_file() -> None:
    assert "spreads.yaml" in PRIVATE_CONFIG_FILES


def test_shipped_defaults_carry_the_opg_entry_rules() -> None:
    s = get_config().spreads
    assert (s.schedule.map_time, s.schedule.entry_start) == ("09:31", "09:35")
    assert s.entry.trigger == "move" and s.entry.min_move_em == 0.5 and s.entry.stall_minutes == 10
    assert s.gex.negative_gamma_action == "allow"
    assert s.risk.one_side_per_day is True and s.risk.events == []
    assert s.exits.max_hold_minutes == 150


def test_entry_move_band_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        SpreadsEntryCfg(min_move_em=1.0, max_move_em=0.8)
    assert SpreadsEntryCfg(max_move_em=None).max_move_em is None


def test_event_until_must_be_a_padded_time() -> None:
    assert SpreadsEventCfg(day="2026-10-28", label="FOMC").until is None
    with pytest.raises(ValidationError):
        SpreadsEventCfg(day="2026-08-28", until="9:30", label="Jackson Hole")
