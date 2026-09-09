"""Two config keys, both defaulted, both honoured, and the EOD run prunes.

`market_data.portfolio_snapshot_interval_minutes` rate-limits the monitor's automatic
snapshot writes; `storage.portfolio_snapshot_retention_days` bounds the intraday history
(pruned by the EOD run's step 8, beside `purge_old_risk_verdicts`).

`get_config()` is `functools.lru_cache(maxsize=1)` — these tests reload config under a
patched `_load_yaml` and clear the cache again on teardown so nothing leaks into other
tests. The end-to-end prune test drives the real `eod_report.run()` through the same
fixture pattern `tests/test_eod_idempotency.py::eod_env` established.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.common.config as config_mod
from src.common.config import get_config
from src.common.schemas import AccountSnapshot
from src.storage.models import Base

_REAL_LOAD_YAML = config_mod._load_yaml


def _settings_without_keys() -> dict[str, Any]:
    """The real settings.yaml minus the two new keys — proves the documented defaults."""
    settings = _REAL_LOAD_YAML("settings.yaml")
    settings = dict(settings)
    md = dict(settings.get("market_data", {}))
    st = dict(settings.get("storage", {}))
    md.pop("portfolio_snapshot_interval_minutes", None)
    st.pop("portfolio_snapshot_retention_days", None)
    settings["market_data"] = md
    settings["storage"] = st
    return settings


@pytest.fixture()
def patched_config(_restore_config_cache):
    """Reload `get_config()` under a patched settings loader; returns a mutator.

    Call the returned factory with a settings dict to swap the cached config for one
    built from those settings. The cache is cleared again on teardown.
    """

    def _reload_with(settings: dict[str, Any]) -> None:
        get_config.cache_clear()

        def fake_load_yaml(name: str) -> dict[str, Any]:
            if name == "settings.yaml":
                return settings
            return _REAL_LOAD_YAML(name)

        with patch.object(config_mod, "_load_yaml", side_effect=fake_load_yaml):
            get_config()

    return _reload_with


@pytest.fixture()
def _restore_config_cache():
    yield
    get_config.cache_clear()


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Isolated in-process SQLite DB wired into src.storage.db (test_eod_idempotency.py)."""
    import src.storage.db as _db_mod

    db_url = f"sqlite:///{tmp_path / 'portfolio_config.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(_db_mod, "_engine", engine)
    monkeypatch.setattr(_db_mod, "_SessionLocal", Session)
    return Session


@pytest.fixture()
def eod_env(db, monkeypatch):
    """The real `eod_report.run()` with every IBKR/network/Claude/Telegram touchpoint patched.

    Mirrors tests/test_eod_idempotency.py::eod_env. The prune calls under test live in
    run()'s step 8 and import inside the function, so they are patched at their source
    modules rather than on eod_report.
    """
    from src.orchestrator import eod_report

    class _FakeConnection:
        def __init__(self, role: str) -> None:
            self.role = role

        async def __aenter__(self):
            return MagicMock(name="ib")

        async def __aexit__(self, *exc_info: object) -> bool:
            return False

    monkeypatch.setattr(eod_report, "IBKRConnection", _FakeConnection)
    monkeypatch.setattr(eod_report, "get_positions", lambda ib: [])
    monkeypatch.setattr(
        eod_report,
        "get_account_snapshot_async",
        AsyncMock(
            return_value=AccountSnapshot(
                account="DU123456",
                net_liquidation=100_000.0,
                total_cash=50_000.0,
                buying_power=80_000.0,
                maintenance_margin=5_000.0,
                excess_liquidity=75_000.0,
            )
        ),
    )
    monkeypatch.setattr(eod_report, "enrich_positions_with_greeks_async", AsyncMock())
    monkeypatch.setattr(eod_report, "_append_daily_iv", AsyncMock(return_value=None))
    monkeypatch.setattr(eod_report, "_append_daily_prices", AsyncMock(return_value=None))
    monkeypatch.setattr(eod_report, "write_journal_narrative", lambda summary: "narrative")
    monkeypatch.setattr(eod_report, "_send_eod_telegram", AsyncMock(return_value=None))
    monkeypatch.setattr("src.storage.maintenance.backup_database", lambda *a, **k: None)
    return eod_report


# ---------------------------------------------------------------------------
# The two keys
# ---------------------------------------------------------------------------


def test_defaults_when_absent(patched_config) -> None:
    patched_config(_settings_without_keys())
    cfg = get_config()
    assert cfg.market_data.portfolio_snapshot_interval_minutes == 15
    assert cfg.storage.portfolio_snapshot_retention_days == 30


def test_values_are_honoured(patched_config) -> None:
    settings = _settings_without_keys()
    settings["market_data"] = dict(
        settings["market_data"], portfolio_snapshot_interval_minutes=5
    )
    settings["storage"] = dict(settings["storage"], portfolio_snapshot_retention_days=7)
    patched_config(settings)
    cfg = get_config()
    assert cfg.market_data.portfolio_snapshot_interval_minutes == 5
    assert cfg.storage.portfolio_snapshot_retention_days == 7


# ---------------------------------------------------------------------------
# The EOD prune wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_eod_run_prunes_portfolio_snapshots(db, eod_env, patched_config) -> None:
    """run()'s step 8 prunes portfolio_snapshots with the configured retention value."""
    settings = _settings_without_keys()
    settings["storage"] = dict(settings["storage"], portfolio_snapshot_retention_days=30)
    patched_config(settings)

    with (
        patch("src.storage.risk_verdicts.purge_old_risk_verdicts") as purge_verdicts,
        patch("src.storage.portfolio_snapshots.prune_portfolio_snapshots") as prune,
    ):
        await eod_env.run()

    prune.assert_called_once()
    assert prune.call_args.args[0] == 30
    purge_verdicts.assert_called_once()
