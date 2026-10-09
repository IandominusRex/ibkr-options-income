"""src/ibkr/contract_cache.py — the shared option-contract lookup cache."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ib_async import Option

from src.ibkr.contract_cache import ContractCache, confirmed_missing, contract_key

TODAY = date(2026, 10, 12)


def _cache(tmp_path: Path, today: date = TODAY) -> ContractCache:
    return ContractCache(f"sqlite:///{tmp_path / 'contracts.db'}", today=lambda: today)


def _opt(strike: float, right: str = "P", expiry: str = "20261023", tc: str = "AMD") -> Option:
    return Option("AMD", expiry, strike, right, "SMART", tradingClass=tc)


def _qualified(strike: float, con_id: int, **kw) -> Option:
    o = _opt(strike, **kw)
    o.conId, o.multiplier, o.currency, o.localSymbol = con_id, "100", "USD", f"AMD x {strike}"
    return o


def test_a_recorded_contract_is_a_hit_in_a_fresh_instance(tmp_path) -> None:
    """Survives a restart: a second ContractCache on the same file sees the first's answers,
    and a hit fills the caller's own contract object in place (callers rely on that)."""
    asked = _opt(600.0)
    _cache(tmp_path).record([(contract_key(asked), _qualified(600.0, 111))])

    again = _opt(600.0)
    found = _cache(tmp_path).lookup([again])

    assert found.hits == [again] and found.misses == [] and found.known_missing == 0
    assert again.conId == 111 and again.multiplier == "100" and again.localSymbol == "AMD x 600.0"


def test_a_missing_contract_is_skipped_today_and_asked_again_tomorrow(tmp_path) -> None:
    asked = _opt(602.5)
    _cache(tmp_path).record([(contract_key(asked), None)])

    today = _cache(tmp_path).lookup([_opt(602.5)])
    assert today.hits == [] and today.misses == [] and today.known_missing == 1

    tomorrow = _cache(tmp_path, today=date(2026, 10, 13)).lookup([_opt(602.5)])
    assert len(tomorrow.misses) == 1 and tomorrow.known_missing == 0


def test_an_expired_contract_is_a_miss_and_is_pruned(tmp_path) -> None:
    asked = _opt(600.0, expiry="20261009")
    _cache(tmp_path).record([(contract_key(asked), _qualified(600.0, 5, expiry="20261009"))])

    cache = _cache(tmp_path)
    assert len(cache.lookup([_opt(600.0, expiry="20261009")]).misses) == 1
    assert cache.prune() == 1


def test_key_is_the_requested_trading_class(tmp_path) -> None:
    """IBKR fills tradingClass in on qualification ("" → "AMD"). The cache keys on what the
    caller ASKED, so a caller that always asks with "" (portfolio greeks) still hits."""
    asked = _opt(600.0, tc="")
    _cache(tmp_path).record([(contract_key(asked), _qualified(600.0, 7, tc="AMD"))])

    assert _cache(tmp_path).lookup([_opt(600.0, tc="")]).hits != []
    assert _cache(tmp_path).lookup([_opt(600.0, tc="AMD")]).misses != []


def test_recording_twice_updates_in_place(tmp_path) -> None:
    key = contract_key(_opt(600.0))
    cache = _cache(tmp_path)
    cache.record([(key, None)])
    cache.record([(key, _qualified(600.0, 9))])

    assert cache.lookup([_opt(600.0)]).hits[0].conId == 9


def test_confirmed_missing_needs_a_good_sibling_in_the_same_expiry() -> None:
    gone = contract_key(_opt(602.5))
    other_expiry_gone = contract_key(_opt(602.5, expiry="20261030"))
    good = contract_key(_opt(600.0))

    assert confirmed_missing([gone, other_expiry_gone], [good]) == [gone]


def test_a_new_trading_class_drops_the_symbols_entries(tmp_path) -> None:
    """A corporate action shows up as a NEW trading class in reqSecDefOptParams; the symbol's
    cached conIds may now belong to the adjusted contracts, so they are all dropped."""
    cache = _cache(tmp_path)
    assert cache.note_trading_classes("AMD", ["AMD", "2AMD"]) is False  # first sight: baseline
    cache.record([(contract_key(_opt(600.0)), _qualified(600.0, 1))])
    assert cache.note_trading_classes("AMD", ["2AMD", "AMD"]) is False  # same set, any order
    assert cache.lookup([_opt(600.0)]).hits != []

    assert cache.note_trading_classes("AMD", ["AMD", "2AMD", "3AMD"]) is True
    assert cache.lookup([_opt(600.0)]).misses != []


def test_a_class_disappearing_drops_nothing(tmp_path) -> None:
    """An old adjusted class expiring away is routine, not a corporate action."""
    cache = _cache(tmp_path)
    cache.note_trading_classes("AMD", ["AMD", "2AMD"])
    cache.record([(contract_key(_opt(600.0)), _qualified(600.0, 1))])

    assert cache.note_trading_classes("AMD", ["AMD"]) is False
    assert cache.lookup([_opt(600.0)]).hits != []


def test_engine_uses_wal_and_a_busy_timeout(tmp_path) -> None:
    """Two processes (scan + spreads) write this file; WAL + busy_timeout make a concurrent
    write wait briefly instead of raising 'database is locked'."""
    cache = _cache(tmp_path)
    with cache._engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() >= 5000


def test_unusable_cache_path_disables_the_cache(monkeypatch, tmp_path) -> None:
    import src.ibkr.contract_cache as cc
    from src.common.config import Config

    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    monkeypatch.setattr(
        Config, "contract_cache_url_abs", lambda self: f"sqlite:///{blocker / 'contracts.db'}"
    )
    monkeypatch.setattr(cc, "_CACHE", None)
    monkeypatch.setattr(cc, "_CACHE_FAILED", False)

    assert cc.get_contract_cache() is None
    assert cc.get_contract_cache() is None  # remembered: no retry storm, one warning


def test_losing_the_create_tables_race_still_opens_the_cache(monkeypatch, tmp_path) -> None:
    """Review finding (2026-10-10): `./ibkr restart` starts every process at once against a
    brand-new data/contracts.db. A process whose create_all races another's CREATE TABLE gets
    'table already exists'; it must still open the cache, not run the day without it."""
    from sqlalchemy.exc import OperationalError

    import src.ibkr.contract_cache as cc

    real = cc.ContractCacheBase.metadata.create_all
    calls = {"n": 0}

    def _racy(bind, *a, **kw):
        calls["n"] += 1
        real(bind, *a, **kw)  # the other process won: the tables now exist
        if calls["n"] == 1:
            raise OperationalError("CREATE TABLE option_contracts", {}, Exception("already exists"))

    monkeypatch.setattr(cc.ContractCacheBase.metadata, "create_all", _racy)

    cache = _cache(tmp_path)
    cache.record([(contract_key(_opt(600.0)), _qualified(600.0, 1))])
    assert cache.lookup([_opt(600.0)]).hits != []
