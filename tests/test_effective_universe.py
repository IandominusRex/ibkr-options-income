"""``effective_universe()`` — the composition layer (M7 Task 7.2).

The YAML is the base. ``universe_overrides`` rows are deltas layered on top of it. Only
``would_own`` and ``watchlist`` are overridable; every other key (``indexes``, ``sectors``,
``strike_bands``, ``leveraged_etfs``, ``actively_wheeling``) is a pure passthrough — the
composer must ignore an override row for any other ``list_name``, even one written directly to
the table, bypassing the API entirely. An unreadable overrides table must never raise or empty
the universe — it must fall back to the YAML base and log a warning. A ``remove`` for a symbol
in ``actively_wheeling`` is ignored when composing ``would_own``. Results are cached for
``_TTL_SECONDS`` and are deterministic within a single computation (YAML file order, then adds
in ``created_at`` order).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import OperationalError

from src.common.config import get_config
from src.common.universe import effective_universe, invalidate_universe_cache
from src.storage.models import UniverseOverrideRow
from src.storage.universe_overrides import set_override


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """A fresh trading DB session, matching the pattern in test_storage_app_commands.

    ``effective_universe()`` reads overrides through ``src.storage.db.session_scope()``
    internally, not through this fixture's session directly — but since both are bound to the
    same monkeypatched ``dbmod._engine``/``_SessionLocal``, a write committed via this session is
    visible to ``effective_universe()``'s own session without any extra patching.
    """
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    session = dbmod._SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def yaml_universe():
    """The real, unmodified config/universe.yaml content — this project's established
    convention (see tests/test_api_universe.py) is to test against the real file, not a mock."""
    return get_config().universe


@pytest.fixture(autouse=True)
def _reset_universe_cache():
    """Every test starts and ends with a clean module-level cache — tests run in one pytest
    process and would otherwise leak a computed result (or lack of one) across each other."""
    invalidate_universe_cache()
    yield
    invalidate_universe_cache()


# ---------------------------------------------------------------------------
# Adds and removes
# ---------------------------------------------------------------------------


def test_an_add_appears_in_would_own(db_session, yaml_universe) -> None:
    assert "ZZZZ" not in yaml_universe["would_own"]  # not already there — the add is meaningful
    set_override(db_session, symbol="ZZZZ", list_name="would_own", action="add", created_by="owner")
    db_session.commit()
    invalidate_universe_cache()
    assert "ZZZZ" in effective_universe()["would_own"]


def test_an_add_appears_in_watchlist(db_session, yaml_universe) -> None:
    assert "ZZZY" not in yaml_universe["watchlist"]
    set_override(db_session, symbol="ZZZY", list_name="watchlist", action="add", created_by="owner")
    db_session.commit()
    invalidate_universe_cache()
    assert "ZZZY" in effective_universe()["watchlist"]


def test_a_remove_takes_a_symbol_out(db_session, yaml_universe) -> None:
    # AAPL is would_own but not actively_wheeling — a plain, unguarded remove.
    symbol = "AAPL"
    assert symbol in yaml_universe["would_own"]
    assert symbol not in yaml_universe["actively_wheeling"]
    set_override(
        db_session, symbol=symbol, list_name="would_own", action="remove", created_by="owner"
    )
    db_session.commit()
    invalidate_universe_cache()
    assert symbol not in effective_universe()["would_own"]


def test_a_remove_only_affects_its_own_list_name(db_session, yaml_universe) -> None:
    """AAPL is in both would_own and watchlist in the base YAML. A remove scoped to
    list_name="would_own" must not touch the watchlist copy."""
    symbol = "AAPL"
    assert symbol in yaml_universe["would_own"]
    assert symbol in yaml_universe["watchlist"]
    set_override(
        db_session, symbol=symbol, list_name="would_own", action="remove", created_by="owner"
    )
    db_session.commit()
    invalidate_universe_cache()
    eff = effective_universe()
    assert symbol not in eff["would_own"]
    assert symbol in eff["watchlist"]


# ---------------------------------------------------------------------------
# Design point 1 — only would_own/watchlist are composed
# ---------------------------------------------------------------------------


def test_sectors_can_never_be_overridden(db_session, yaml_universe) -> None:
    """Bypass the API entirely. The composer must still ignore it.

    sectors feeds risk_engine's concentration limits. No web path may move it.
    """
    base = dict(effective_universe()["sectors"])
    db_session.add(
        UniverseOverrideRow(symbol="NVDA", list_name="sectors", action="add", created_by="owner")
    )
    db_session.commit()
    invalidate_universe_cache()
    assert effective_universe()["sectors"] == base


def test_every_non_overridable_key_passes_through_untouched(db_session, yaml_universe) -> None:
    eff = effective_universe()
    for key in ("indexes", "sectors", "leveraged_etfs", "strike_bands", "actively_wheeling"):
        assert eff[key] == yaml_universe[key]


def test_passthrough_containers_are_copies_not_aliases(db_session, yaml_universe) -> None:
    """M7 final-review Fix 5: `effective_universe()` must not hand back the literal same
    dict/list objects `get_config().universe` holds — `sectors` in particular feeds
    risk_engine's concentration limits and is a single process-wide, lru_cache-shared
    object. Nothing mutates the returned containers today, but object identity, not just
    equality, is the property that makes that true by construction rather than by luck.
    """
    eff = effective_universe()
    cfg_universe = get_config().universe

    assert eff["sectors"] is not cfg_universe["sectors"]
    assert eff["sectors"] == cfg_universe["sectors"]

    assert eff["indexes"] is not cfg_universe["indexes"]
    assert eff["indexes"] == cfg_universe["indexes"]

    assert eff["actively_wheeling"] is not cfg_universe["actively_wheeling"]
    assert eff["actively_wheeling"] == cfg_universe["actively_wheeling"]


# ---------------------------------------------------------------------------
# Design point 2 — fail-safe on a broken overrides read
# ---------------------------------------------------------------------------


def test_an_unreadable_overrides_table_falls_back_to_the_yaml(
    monkeypatch, yaml_universe, caplog
) -> None:
    """A locked database must not empty the universe mid-scan."""
    monkeypatch.setattr(
        "src.common.universe._read_overrides",
        lambda: (_ for _ in ()).throw(OperationalError("locked", None, None)),
    )
    invalidate_universe_cache()
    with caplog.at_level(logging.WARNING, logger="src.common.universe"):
        eff = effective_universe()
    assert eff["would_own"] == yaml_universe["would_own"]
    assert eff["watchlist"] == yaml_universe["watchlist"]
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_an_unreadable_overrides_table_does_not_raise(monkeypatch, yaml_universe) -> None:
    """Broader than OperationalError — design point 2 says 'unreadable... table' broadly."""
    monkeypatch.setattr(
        "src.common.universe._read_overrides",
        lambda: (_ for _ in ()).throw(RuntimeError("table missing")),
    )
    invalidate_universe_cache()
    effective_universe()  # must not raise


# ---------------------------------------------------------------------------
# Design point 3 — actively_wheeling remove-guard
# ---------------------------------------------------------------------------


def test_removing_an_actively_wheeling_symbol_is_ignored(db_session, yaml_universe) -> None:
    wheeling = yaml_universe["actively_wheeling"][0]
    set_override(
        db_session, symbol=wheeling, list_name="would_own", action="remove", created_by="owner"
    )
    db_session.commit()
    invalidate_universe_cache()
    assert wheeling in effective_universe()["would_own"]


def test_the_actively_wheeling_guard_does_not_apply_to_watchlist(db_session, yaml_universe) -> None:
    """The guard is would_own-specific — a wheeling symbol can still be removed from watchlist."""
    wheeling = yaml_universe["actively_wheeling"][0]
    assert wheeling in yaml_universe["watchlist"]
    set_override(
        db_session, symbol=wheeling, list_name="watchlist", action="remove", created_by="owner"
    )
    db_session.commit()
    invalidate_universe_cache()
    assert wheeling not in effective_universe()["watchlist"]
    assert wheeling in effective_universe()["would_own"]  # untouched


# ---------------------------------------------------------------------------
# Design point 4 — stable, deterministic ordering
# ---------------------------------------------------------------------------


def test_ordering_is_stable_across_calls(db_session, yaml_universe) -> None:
    set_override(db_session, symbol="ZZZZ", list_name="would_own", action="add", created_by="owner")
    db_session.commit()
    invalidate_universe_cache()
    assert effective_universe()["would_own"] == effective_universe()["would_own"]


def test_added_symbols_are_appended_in_created_at_order(db_session, yaml_universe) -> None:
    """Insertion order and alphabetical order both disagree with created_at order here, so a
    composer that (incorrectly) relies on DB return order or symbol name would fail this."""
    later = datetime(2026, 1, 2, tzinfo=UTC)
    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add(
        UniverseOverrideRow(
            symbol="AAA", list_name="would_own", action="add", created_by="owner", created_at=later
        )
    )
    db_session.add(
        UniverseOverrideRow(
            symbol="BBB",
            list_name="would_own",
            action="add",
            created_by="owner",
            created_at=earlier,
        )
    )
    db_session.commit()
    invalidate_universe_cache()
    would_own = effective_universe()["would_own"]
    assert would_own[-2:] == ["BBB", "AAA"]


def test_base_entries_keep_yaml_file_order(db_session, yaml_universe) -> None:
    set_override(db_session, symbol="ZZZZ", list_name="would_own", action="add", created_by="owner")
    db_session.commit()
    invalidate_universe_cache()
    would_own = effective_universe()["would_own"]
    base = list(yaml_universe["would_own"])
    assert would_own[: len(base)] == base
    assert would_own[len(base) :] == ["ZZZZ"]


# ---------------------------------------------------------------------------
# Design point 5 — TTL cache + invalidate_universe_cache()
# ---------------------------------------------------------------------------


def test_cache_serves_a_stale_result_until_invalidated(db_session, yaml_universe) -> None:
    baseline = effective_universe()["would_own"]
    assert "ZZZZ" not in baseline

    set_override(db_session, symbol="ZZZZ", list_name="would_own", action="add", created_by="owner")
    db_session.commit()  # no invalidate — the cached result must still be served

    assert effective_universe()["would_own"] == baseline
    assert "ZZZZ" not in effective_universe()["would_own"]

    invalidate_universe_cache()
    assert "ZZZZ" in effective_universe()["would_own"]


def test_cache_recomputes_after_ttl_expires(db_session, yaml_universe, monkeypatch) -> None:
    import src.common.universe as universe_mod

    clock = {"t": 1_000.0}
    monkeypatch.setattr(universe_mod.time, "monotonic", lambda: clock["t"])

    invalidate_universe_cache()
    assert "ZZZZ" not in effective_universe()["would_own"]

    set_override(db_session, symbol="ZZZZ", list_name="would_own", action="add", created_by="owner")
    db_session.commit()

    # still inside the TTL window — cache reused, override not yet visible
    clock["t"] += universe_mod._TTL_SECONDS - 1
    assert "ZZZZ" not in effective_universe()["would_own"]

    # TTL elapsed — recomputes on its own, no explicit invalidate needed
    clock["t"] += 2
    assert "ZZZZ" in effective_universe()["would_own"]
