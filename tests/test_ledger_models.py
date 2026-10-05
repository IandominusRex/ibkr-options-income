"""Ledger tables, config and the generation/account-lock state (spec §3, §8, R8)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

import src.common.config as config_mod


def _row(**kw):
    from src.storage.models import BrokerExecutionRow

    base = dict(
        dedupe_key="exec:1",
        source_kind="exec",
        source="live",
        trade_time=datetime(2025, 7, 1, 14),
        trade_date=date(2025, 7, 1),
        contract_ident="STK:NVDA:USD",
        underlying="NVDA",
        sec_type="STK",
        currency="USD",
        quantity=10,
        price=1.0,
        proceeds=-10.0,
    )
    base.update(kw)
    return BrokerExecutionRow(**base)


def test_dedupe_key_is_unique(db) -> None:
    with db() as s:
        s.add(_row())
    with pytest.raises(IntegrityError), db() as s:
        s.add(_row())


def test_annotation_order_key_is_unique(db) -> None:
    from src.storage.models import TradeAnnotationRow

    with db() as s:
        s.add(TradeAnnotationRow(order_key="a" * 16))
    with pytest.raises(IntegrityError), db() as s:
        s.add(TradeAnnotationRow(order_key="a" * 16))


def test_fx_rate_unique_per_date_and_currency(db) -> None:
    from src.storage.models import FxRateRow

    with db() as s:
        s.add(FxRateRow(rate_date=date(2026, 1, 6), currency="SGD", usd_rate=0.78, source="csv"))
    with pytest.raises(IntegrityError), db() as s:
        s.add(FxRateRow(rate_date=date(2026, 1, 6), currency="SGD", usd_rate=0.79, source="csv"))


def test_ledger_config_defaults() -> None:
    from src.common.config import get_config

    cfg = get_config().ledger
    assert cfg.live_sweep_minutes == 5
    assert cfg.sheets_min_interval_seconds == 60
    assert cfg.upload_max_bytes == 5_242_880
    assert cfg.fx_max_gap_days == 7


@pytest.fixture()
def _restore_config_cache():
    yield
    config_mod.get_config.cache_clear()


def test_ledger_config_values_are_honoured_from_settings(_restore_config_cache) -> None:
    """F1: get_config() must actually build ``ledger`` from settings.yaml's ``ledger`` block,
    not just carry the pydantic defaults. Reload config under a settings dict with a
    non-default ledger section and confirm it is picked up (pattern from
    tests/test_portfolio_snapshot_config.py)."""
    real_load_yaml = config_mod._load_yaml
    settings = dict(real_load_yaml("settings.yaml"))
    settings["ledger"] = dict(
        settings.get("ledger", {}),
        account="U7654321",
        live_sweep_minutes=42,
        sheets_min_interval_seconds=99,
        upload_max_bytes=123,
        flex_poll_timeout_seconds=12.5,
        flex_poll_interval_seconds=3.5,
        fx_max_gap_days=14,
    )

    def fake_load_yaml(name: str) -> dict[str, Any]:
        if name == "settings.yaml":
            return settings
        return real_load_yaml(name)

    config_mod.get_config.cache_clear()
    with patch.object(config_mod, "_load_yaml", side_effect=fake_load_yaml):
        cfg = config_mod.get_config()

    assert cfg.ledger.account == "U7654321"
    assert cfg.ledger.live_sweep_minutes == 42
    assert cfg.ledger.sheets_min_interval_seconds == 99
    assert cfg.ledger.upload_max_bytes == 123
    assert cfg.ledger.flex_poll_timeout_seconds == 12.5
    assert cfg.ledger.flex_poll_interval_seconds == 3.5
    assert cfg.ledger.fx_max_gap_days == 14


def test_generation_counter_increments(db) -> None:
    from src.ledger.state import LEDGER_GENERATION_KEY, bump_generation, read_int_setting

    assert read_int_setting(LEDGER_GENERATION_KEY) == 0
    with db() as s:
        bump_generation(s)
    with db() as s:
        bump_generation(s)
    assert read_int_setting(LEDGER_GENERATION_KEY) == 2


def test_account_lock_prefers_config_then_setting(db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.ledger.state import ledger_account, lock_account

    with db() as s:
        assert ledger_account(s) is None
        lock_account(s, "U1")
    with db() as s:
        assert ledger_account(s) == "U1"
    monkeypatch.setattr(get_config().ledger, "account", "U9")
    with db() as s:
        assert ledger_account(s) == "U9"
