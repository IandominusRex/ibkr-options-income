"""config/value.yaml: the typed model, its committed example and the ruleset hash (Parts 1-3)."""

from __future__ import annotations

import hashlib
import json

import pytest
import yaml
from pydantic import ValidationError

from src.common.config import CONFIG_DIR, PRIVATE_CONFIG_FILES, ValueCfg, get_config
from src.common.schemas import MarketRegime
from src.value.ruleset import FROZEN, ruleset_hash, ruleset_id


def test_value_yaml_is_a_private_file_with_a_committed_example() -> None:
    assert "value.yaml" in PRIVATE_CONFIG_FILES
    assert (CONFIG_DIR / "examples" / "value.yaml").exists()


def test_the_example_spells_out_exactly_the_model_defaults() -> None:
    raw = yaml.safe_load((CONFIG_DIR / "examples" / "value.yaml").read_text(encoding="utf-8"))
    assert ValueCfg(**raw).model_dump() == ValueCfg().model_dump()


def test_get_config_loads_the_value_block() -> None:
    cfg = get_config().value
    assert cfg.ruleset_version == "v3"
    assert cfg.rules.margin_of_safety.deep_value[MarketRegime.NORMAL] == 25.0
    assert cfg.rules.margin_of_safety.quality_growth[MarketRegime.CRISIS] == 25.0
    assert cfg.rules.valuation.discount_rate_growth == 0.08
    assert get_config().value_db_url_abs().endswith("/data/value.db")


def test_a_misspelt_rule_is_refused_not_ignored() -> None:
    with pytest.raises(ValidationError):
        ValueCfg(**{"rules": {"health": {"piotroski_minimum": 7}}})


def test_a_margin_table_missing_a_regime_is_refused() -> None:
    with pytest.raises(ValidationError):
        ValueCfg(**{"rules": {"margin_of_safety": {"deep_value": {"normal": 25.0}}}})


def test_a_discount_rate_at_or_below_terminal_growth_is_refused() -> None:
    with pytest.raises(ValidationError):
        ValueCfg(**{"rules": {"valuation": {"discount_rate_growth": 0.025}}})


def test_the_ruleset_hash_is_stable_and_moves_with_any_rule() -> None:
    base = ValueCfg()
    assert ruleset_hash(base.rules) == ruleset_hash(ValueCfg().rules)
    assert len(ruleset_hash(base.rules)) == 12
    moved = ValueCfg(**{"rules": {"health": {"piotroski_min": 7}}})
    assert ruleset_hash(moved.rules) != ruleset_hash(base.rules)


def test_non_rule_keys_do_not_move_the_hash() -> None:
    other = ValueCfg(**{"ticker_file": {"follow_days": 90}, "research_sweep": {"enabled": True}})
    assert ruleset_hash(other.rules) == ruleset_hash(ValueCfg().rules)


def test_a_frozen_version_refuses_rules_that_no_longer_match(monkeypatch) -> None:
    monkeypatch.setitem(FROZEN, "v9", "000000000000")
    with pytest.raises(ValueError, match="frozen"):
        ruleset_id(ValueCfg(ruleset_version="v9"))
    assert ruleset_id(ValueCfg()) == ("v3", ruleset_hash(ValueCfg().rules))


def _hash_without(*blocks: str) -> str:
    rules = ValueCfg().rules.model_dump(mode="json")
    for block in blocks:
        del rules[block]
    blob = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def test_v1_and_v2_stay_pinned_and_v3_is_frozen() -> None:
    """Part 1 froze v1 (the entry rules); Part 2 froze v2 = v1 + the exit rules; Part 3 froze
    v3 = v2 + the re-evaluation rules, before the first re-evaluation (spec §7.1)."""
    assert FROZEN["v1"] == "e1a1b3b096b1" and FROZEN["v2"] == "d07717fe5348"
    assert FROZEN["v3"] == ruleset_hash(ValueCfg().rules)
    assert ruleset_id(get_config().value) == ("v3", FROZEN["v3"])


def test_v3_changes_no_entry_rule_and_no_exit_threshold() -> None:
    """Without the reevaluation block the rules hash exactly as v2's; without exits too, as
    v1's: no verdict and no exit threshold moves. Part 3's exit-engine changes are code, carried
    by the version bump (an exit-logic change after the first live row needs one)."""
    assert _hash_without("reevaluation") == FROZEN["v2"]
    assert _hash_without("reevaluation", "exits") == FROZEN["v1"]


def test_the_reevaluation_rules_are_in_the_ruleset() -> None:
    """Spec §7.1: every re-evaluation threshold is under the ruleset version."""
    cfg = ValueCfg()
    assert cfg.rules.reevaluation.sector_etfs["Information Technology"] == "XLK"
    for change in ({"abnormal_z": 2.5}, {"major_8k_items": ["1.03"]}, {"quiet_days": 60}):
        moved = ValueCfg(**{"rules": {"reevaluation": change}})
        assert ruleset_hash(moved.rules) != ruleset_hash(cfg.rules)


def test_nonsense_reevaluation_keys_are_refused() -> None:
    for bad in (
        {"abnormal_z": 0.0},
        {"drift_sessions": 1},
        {"min_history_sessions": 30},
        {"beta_sessions": 100},
        {"minor_8k_items": ["1.03"]},
        {"regime_states": ["panic"]},
        {"sigma_window": 60},
    ):
        with pytest.raises(ValidationError):
            ValueCfg(**{"rules": {"reevaluation": bad}})


def test_the_exit_rules_are_in_the_ruleset() -> None:
    """Spec §7: changing an exit rule, or the live policy, is a version bump."""
    cfg = ValueCfg()
    assert cfg.rules.exits.live_policy == "value"
    for change in ({"live_policy": "full"}, {"catastrophe_stop_pct": 25.0}):
        moved = ValueCfg(**{"rules": {"exits": change}})
        assert ruleset_hash(moved.rules) != ruleset_hash(cfg.rules)


def test_nonsense_exit_and_service_keys_are_refused() -> None:
    for bad in (
        {"rules": {"exits": {"live_policy": "hold6"}}},
        {"rules": {"exits": {"half_sell_pct": 0.5e3}}},
        {"rules": {"exits": {"peak_rsi_cross": 80.0}}},
        {"service": {"run_hour_et": 24}},
        {"service": {"poll_seconds": 5}},
    ):
        with pytest.raises(ValidationError):
            ValueCfg(**bad)


def test_part_2_turns_the_research_sweep_on() -> None:
    assert ValueCfg().research_sweep.enabled is True
    assert ValueCfg().service.run_hour_et == 6
