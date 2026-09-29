"""The autonomy ladder: autonomy is arrived at with evidence, not switched on."""

from __future__ import annotations

import pytest

from src.common.schemas import AutonomyLevel


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)


def test_default_level_is_observe():
    from src.storage.system_settings import get_autonomy_level

    assert get_autonomy_level() == AutonomyLevel.OBSERVE


def test_observe_never_auto_opens():
    from src.storage.system_settings import may_auto_open, set_autonomy_level

    set_autonomy_level(AutonomyLevel.OBSERVE)
    assert may_auto_open("SPY") is False


def test_manual_never_auto_opens():
    from src.storage.system_settings import may_auto_open, set_autonomy_level

    set_autonomy_level(AutonomyLevel.MANUAL)
    assert may_auto_open("SPY") is False


def test_whitelist_opens_only_listed_symbols(monkeypatch):
    from src.storage.system_settings import may_auto_open, set_autonomy_level

    set_autonomy_level(AutonomyLevel.WHITELIST)
    monkeypatch.setattr("src.storage.system_settings._autonomy_whitelist", lambda: {"SPY", "QQQ"})
    assert may_auto_open("SPY") is True
    assert may_auto_open("MARA") is False


def test_full_opens_anything():
    from src.storage.system_settings import may_auto_open, set_autonomy_level

    set_autonomy_level(AutonomyLevel.FULL)
    assert may_auto_open("MARA") is True


def test_halted_blocks_every_level():
    from src.storage.system_settings import may_auto_open, set_autonomy_level, set_halted

    set_autonomy_level(AutonomyLevel.FULL)
    set_halted(True, "test")
    assert may_auto_open("SPY") is False


def test_promotion_is_refused_without_evidence(monkeypatch):
    """A ladder you can skip rungs on is the old binary with more words."""
    from src.common.config import get_config
    from src.storage.system_settings import promotion_blockers, set_autonomy_level

    # Task 12's paper-only bypass ships on in config/settings.yaml for this deployment — turn
    # it off here so this test exercises the evidence gate itself, not the bypass around it.
    monkeypatch.setattr(get_config().automation, "paper_skip_promotion_gate", False)

    set_autonomy_level(AutonomyLevel.MANUAL)
    blockers = promotion_blockers(AutonomyLevel.WHITELIST)
    assert any("fills" in b for b in blockers)
    assert any("close" in b for b in blockers)


def test_demotion_is_always_allowed():
    from src.storage.system_settings import promotion_blockers, set_autonomy_level

    set_autonomy_level(AutonomyLevel.WHITELIST)
    assert promotion_blockers(AutonomyLevel.MANUAL) == []


# --------------------------------------------------------------------------- #
# Task 12: paper-only promotion-gate bypass
#
# automation.paper_skip_promotion_gate lets the paper account skip the evidence gate above
# (>=20 fills, >=60% fill rate, >=1 close) so it can run on FULL to observe end-to-end
# behaviour — but only in paper mode: whenever LIVE_TRADING=true (Config.is_live) the flag is
# ignored (with a warning), so this can never become a live back door. Telegram /autonomy, the
# web set_autonomy drain command, and scripts/autonomy.py all resolve through this same
# promotion_blockers — there is exactly one gate. The `_db` autouse fixture above already
# points system_settings at a throwaway tmp_path DB, so these never touch the real trading DB.
# --------------------------------------------------------------------------- #


def test_paper_bypass_clears_blockers(monkeypatch):
    from src.common.config import get_config
    from src.storage.system_settings import promotion_blockers

    cfg = get_config()
    monkeypatch.setattr(cfg.automation, "paper_skip_promotion_gate", True)
    monkeypatch.setattr(type(cfg), "is_live", property(lambda self: False))
    assert promotion_blockers(AutonomyLevel.FULL) == []


def test_bypass_ignored_when_live(monkeypatch):
    from src.common.config import get_config
    from src.storage.system_settings import promotion_blockers

    cfg = get_config()
    monkeypatch.setattr(cfg.automation, "paper_skip_promotion_gate", True)
    monkeypatch.setattr(type(cfg), "is_live", property(lambda self: True))
    assert promotion_blockers(AutonomyLevel.FULL) != []  # fresh DB: 0 fills → blocked


def test_bypass_off_by_default():
    # Pins the CODE default, not the deployed config/settings.yaml (which sets this true for
    # this paper run) — construct a bare AutomationCfg rather than going through get_config().
    from src.common.config import AutomationCfg

    assert AutomationCfg().paper_skip_promotion_gate is False
