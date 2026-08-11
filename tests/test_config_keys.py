"""Guard: every tunable in risk_limits.yaml must actually be read by the code.

The dangerous pattern (SYSTEM_REVIEW "unenforced-config-key"): a knob sits in
risk_limits.yaml looking enforced but nothing reads it, so a user tuning it gets silent
nothing. This test asserts every leaf key is referenced somewhere in src/, with an explicit
allowlist of the keys that are *knowingly* not enforced (documented in STATUS.md). Adding a
new key that nothing reads — or wiring up an allowlisted one — fails this test by design.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"

# Keys deliberately present-but-unenforced. Each must be documented in STATUS.md.
# NOTE: `max_correlated_exposure_pct`, `max_pct_per_sector`, `max_csp_allocation_pct`, and
# `min_buying_power_buffer_pct` (D1, Task 4) were retired by the risk-units concentration
# model (Task 9) and deleted from risk_limits.yaml entirely — see
# test_retired_collateral_keys_are_gone. Do not re-add a key here without also adding it back
# to the YAML: test_allowlist_entries_exist_in_config asserts every entry below is a real,
# present leaf key, so a retired key left in this set would be caught rather than silently
# lying about what's still configurable.
_KNOWN_UNENFORCED = {
    "ex_dividend_assignment_guard",  # ex-div guard fires in monitor/triggers without this flag
}


def _leaf_keys(node: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, dict):
                keys |= _leaf_keys(v)
            else:
                keys.add(k)
    return keys


def _src_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py"))


def test_every_risk_limit_key_is_read_or_allowlisted() -> None:
    limits = yaml.safe_load((_ROOT / "config" / "risk_limits.yaml").read_text(encoding="utf-8"))
    keys = _leaf_keys(limits)
    src = _src_text()

    unread = {k for k in keys if f'"{k}"' not in src and f"'{k}'" not in src}
    truly_unread = unread - _KNOWN_UNENFORCED

    assert not truly_unread, (
        f"risk_limits.yaml keys read by no source file: {sorted(truly_unread)}. "
        "Wire them into the engine/strategies or add to _KNOWN_UNENFORCED (and document in STATUS.md)."
    )


def test_allowlist_stays_accurate() -> None:
    """If an allowlisted key becomes read (someone wired it up), drop it from the allowlist."""
    src = _src_text()
    still_unread = {k for k in _KNOWN_UNENFORCED if f'"{k}"' not in src and f"'{k}'" not in src}
    assert still_unread == _KNOWN_UNENFORCED, (
        "These allowlisted keys are now referenced in src/ — remove them from _KNOWN_UNENFORCED: "
        f"{sorted(_KNOWN_UNENFORCED - still_unread)}"
    )


def test_allowlist_entries_exist_in_config() -> None:
    """Catches the mirror-image bug: a key deleted from the YAML but left allowlisted.

    `test_allowlist_stays_accurate` only checks that allowlisted keys stay unread in src/ — it
    says nothing about whether they still exist in risk_limits.yaml at all. A retired key
    removed from the YAML but forgotten here would satisfy that test forever while quietly
    lying about what's actually configurable (Task 9's config sweep).
    """
    limits = yaml.safe_load((_ROOT / "config" / "risk_limits.yaml").read_text(encoding="utf-8"))
    present = _leaf_keys(limits)
    stale = _KNOWN_UNENFORCED - present
    assert not stale, (
        f"_KNOWN_UNENFORCED entries no longer present in risk_limits.yaml: {sorted(stale)}. "
        "Remove them from the allowlist (and their STATUS.md notes)."
    )


# settings.yaml keys map to Pydantic fields (attribute access), not quoted dict lookups, so the
# detection is a whole-word identifier match. This catches an orphan key — a typo or a key with
# no schema field that silently does nothing (N15 extends the guard to settings.yaml). The
# `max_concurrent_lines` enforcement (a MarketDataCfg validator) keeps that key from being dead.
def test_every_settings_key_is_referenced_in_src() -> None:
    settings = yaml.safe_load((_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    keys = _leaf_keys(settings)
    src = _src_text()
    unread = sorted(k for k in keys if not re.search(rf"\b{re.escape(k)}\b", src))
    assert not unread, (
        f"settings.yaml keys referenced by no source file: {unread}. "
        "Wire them into the config models/usage or remove them."
    )


def test_market_data_line_budget_enforced() -> None:
    """N15: `max_concurrent_lines` now constrains `chain_batch_size` (was read by nothing)."""
    from pydantic import ValidationError

    from src.common.config import MarketDataCfg

    MarketDataCfg(chain_batch_size=40, max_concurrent_lines=90)  # within budget — ok
    with pytest.raises(ValidationError):
        MarketDataCfg(chain_batch_size=120, max_concurrent_lines=90)


def test_portfolio_block_has_the_risk_unit_keys() -> None:
    from src.common.config import get_config

    p = get_config().risk["portfolio"]
    for key in (
        "cash_reserve_pct",
        "cash_reserve_absolute",
        "max_csp_allocation_pct_of_deployable",
        "max_risk_units_per_ticker_pct",
        "max_risk_units_per_sector_pct",
        "max_collateral_per_ticker_pct",
        "max_large_positions",
        "max_pct_per_ticker_large",
    ):
        assert key in p, f"missing risk_limits.yaml portfolio key: {key}"


def test_retired_collateral_keys_are_gone() -> None:
    from src.common.config import get_config

    p = get_config().risk["portfolio"]
    for key in (
        "max_pct_per_ticker",
        "max_pct_per_sector",
        "max_csp_allocation_pct",
        "min_buying_power_buffer_pct",
        "max_correlated_exposure_pct",
    ):
        assert key not in p, f"retired key still present: {key}"
