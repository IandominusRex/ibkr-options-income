"""config/spreads.yaml loads, and config load refuses any wheel/spreads overlap."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.common.config import (
    PRIVATE_CONFIG_FILES,
    Config,
    SpreadsAiCfg,
    SpreadsCfg,
    SpreadsEntryCfg,
    SpreadsEventCfg,
    SpreadsScheduleCfg,
    SpreadsSelectionCfg,
    get_config,
)

ROOT = Path(__file__).resolve().parents[1]


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


def test_shipped_sizing_is_in_shares_of_net_liquidation() -> None:
    """Risk envelope Task 4 (ruling E2): 0.5% of NLV per trade and in total, 1% a day, 2% a
    month, an excess-liquidity floor at 40% of NLV. starting_capital_usd only feeds the report."""
    r = get_config().spreads.risk
    assert (
        r.max_loss_pct_of_nlv,
        r.max_total_risk_pct_of_nlv,
        r.max_daily_loss_pct_of_nlv,
        r.max_monthly_loss_pct_of_nlv,
        r.min_excess_liquidity_pct_of_nlv,
    ) == (0.005, 0.005, 0.01, 0.02, 0.40)
    assert r.starting_capital_usd == 100_000.0
    assert r.max_contracts == 100 and r.ex_dividend_dates == []


def test_the_example_no_longer_carries_the_capital_caps() -> None:
    text = (ROOT / "config" / "examples" / "spreads.yaml").read_text(encoding="utf-8")
    for legacy in (
        "max_loss_pct_of_capital",
        "max_total_risk_pct_of_capital",
        "max_daily_loss_pct_of_capital",
        "min_excess_liquidity_usd",
    ):
        assert f"{legacy}:" not in text, legacy


def test_a_private_copy_with_the_legacy_keys_still_loads() -> None:
    from src.common.config import SpreadsRiskCfg

    r = SpreadsRiskCfg(
        max_loss_pct_of_capital=0.10,
        max_total_risk_pct_of_capital=0.10,
        max_daily_loss_pct_of_capital=0.10,
        min_excess_liquidity_usd=10_000.0,
    )
    assert r.max_loss_pct_of_nlv == 0.005  # the legacy keys are read and ignored


def test_risk_percentages_must_be_fractions() -> None:
    from src.common.config import SpreadsRiskCfg

    with pytest.raises(ValidationError):
        SpreadsRiskCfg(max_loss_pct_of_capital=10)  # 10 means 1000%, not 10%
    with pytest.raises(ValidationError):
        SpreadsRiskCfg(starting_capital_usd=0)
    with pytest.raises(ValidationError):
        SpreadsRiskCfg(max_loss_pct_of_nlv=0.5 * 100)  # 50 means 5000%, not 0.5%
    with pytest.raises(ValidationError):
        SpreadsRiskCfg(min_excess_liquidity_pct_of_nlv=0)


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


# Review minor — the budget is the configured cap, and the wheel monitor's standing lines count.
def test_the_line_budget_counts_the_monitor_against_the_configured_cap() -> None:
    base = get_config()
    fits = base.spreads.model_copy(update={"enabled": True})
    _config(spreads=fits)  # 40 + 30 + 20 = 90, the shipped max_concurrent_lines
    over = fits.model_copy(update={"reserved_monitor_lines": 21})
    with pytest.raises(ValidationError, match="max_concurrent_lines"):
        _config(spreads=over)


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


def test_shipped_ai_block_is_off_with_opus() -> None:
    sc = get_config().spreads
    ai = sc.ai
    assert ai.enabled is False
    # The day plan runs Opus at medium (operator ruling 2026-10-14); the pick stays high.
    assert (ai.brief_model, ai.brief_effort, ai.pick_model, ai.pick_effort) == (
        "claude-opus-5-5",
        "medium",
        "claude-opus-5-5",
        "high",
    )
    assert (ai.brief_timeout_seconds, ai.pick_timeout_seconds) == (120.0, 45.0)
    assert (ai.max_pick_calls_per_day, ai.max_headlines, ai.workdir) == (
        4,
        20,
        "~/.cache/ibkr-spreads-ai",
    )
    assert sc.selection.menu_size == 4


def test_ai_needs_spreads_enabled() -> None:
    with pytest.raises(ValidationError, match="ai.enabled"):
        SpreadsCfg(enabled=False, ai=SpreadsAiCfg(enabled=True))


def test_pick_timeout_must_fit_inside_an_entry_check() -> None:
    with pytest.raises(ValidationError, match="pick_timeout_seconds"):
        SpreadsCfg(
            enabled=True,
            ai=SpreadsAiCfg(enabled=True, pick_timeout_seconds=300),
            schedule=SpreadsScheduleCfg(entry_check_minutes=5),
        )
    SpreadsCfg(enabled=True, ai=SpreadsAiCfg(enabled=True, pick_timeout_seconds=45))


def test_menu_size_cap_and_timeouts_are_positive() -> None:
    with pytest.raises(ValidationError):
        SpreadsSelectionCfg(menu_size=0)
    with pytest.raises(ValidationError):
        SpreadsSelectionCfg(menu_size=14)  # 2 sides x 14 > 26 letters
    assert SpreadsSelectionCfg(menu_size=13).menu_size == 13
    with pytest.raises(ValidationError):
        SpreadsAiCfg(max_pick_calls_per_day=0)
    with pytest.raises(ValidationError):
        SpreadsAiCfg(pick_timeout_seconds=0)
    with pytest.raises(ValidationError):
        SpreadsAiCfg(pick_effort="extreme")


def test_ai_workdir_defaults_outside_the_repo() -> None:
    p = get_config().spreads_ai_workdir()
    assert p.is_absolute() and p != ROOT and ROOT not in p.parents
    assert p == Path.home() / ".cache" / "ibkr-spreads-ai"


def test_ai_workdir_expands_home_passes_absolute_and_roots_relative() -> None:
    cfg = get_config()

    def resolved(workdir: str) -> Path:
        c = cfg.model_copy(deep=True)
        c.spreads.ai.workdir = workdir
        return c.spreads_ai_workdir()

    assert resolved("~/x") == Path.home() / "x"
    assert resolved("/abs/x") == Path("/abs/x")
    assert resolved("data/spreads_ai") == ROOT / "data" / "spreads_ai"  # legacy, not recommended


def test_a_relative_ai_workdir_stays_gitignored() -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "data/spreads_ai/scratch.txt"], cwd=ROOT, check=False
    )
    assert ignored.returncode == 0
