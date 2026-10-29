"""config/value.yaml: the typed model, its committed example and the ruleset hash (Part 1)."""

from __future__ import annotations

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
    assert cfg.ruleset_version == "v1"
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
    assert ruleset_id(ValueCfg()) == ("v1", ruleset_hash(ValueCfg().rules))


def test_v1_is_frozen() -> None:
    """Part 1, Task 16: the operator froze value_rules v1 after the calibration dry run."""
    assert FROZEN["v1"] == ruleset_hash(ValueCfg().rules)
    assert ruleset_id(get_config().value) == ("v1", FROZEN["v1"])
