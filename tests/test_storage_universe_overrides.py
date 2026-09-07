"""universe_overrides upsert semantics: one row per (symbol, list_name), symbol upper-cased."""

from __future__ import annotations

import pytest

from src.storage.universe_overrides import all_overrides, clear_override, set_override


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """A fresh trading DB session, matching the pattern in test_storage_app_commands."""
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


def test_set_override_inserts_a_new_row(db_session) -> None:
    set_override(db_session, symbol="AAPL", list_name="watchlist", action="add", created_by="owner")
    db_session.commit()
    rows = all_overrides(db_session)
    assert len(rows) == 1
    assert rows[0].symbol == "AAPL"
    assert rows[0].list_name == "watchlist"
    assert rows[0].action == "add"


def test_set_override_upserts_add_then_remove_leaves_one_row(db_session) -> None:
    """The required behaviour: adding then removing the same symbol leaves one row."""
    set_override(db_session, symbol="NVDA", list_name="would_own", action="add", created_by="owner")
    db_session.commit()
    set_override(
        db_session, symbol="NVDA", list_name="would_own", action="remove", created_by="owner"
    )
    db_session.commit()
    rows = all_overrides(db_session)
    assert len(rows) == 1
    assert rows[0].action == "remove"


def test_set_override_upserts_repeatedly_still_one_row(db_session) -> None:
    """Add, remove, add again — still exactly one row, reflecting the latest action."""
    set_override(db_session, symbol="TSLA", list_name="watchlist", action="add", created_by="a")
    db_session.commit()
    set_override(db_session, symbol="TSLA", list_name="watchlist", action="remove", created_by="b")
    db_session.commit()
    set_override(db_session, symbol="TSLA", list_name="watchlist", action="add", created_by="c")
    db_session.commit()
    rows = all_overrides(db_session)
    assert len(rows) == 1
    assert rows[0].action == "add"
    assert rows[0].created_by == "c"


def test_symbols_are_upper_cased_lowercase_and_uppercase_collide(db_session) -> None:
    """nvda and NVDA cannot both exist — they must collide into one row."""
    set_override(db_session, symbol="nvda", list_name="watchlist", action="add", created_by="owner")
    db_session.commit()
    set_override(
        db_session, symbol="NVDA", list_name="watchlist", action="remove", created_by="owner"
    )
    db_session.commit()
    rows = all_overrides(db_session)
    assert len(rows) == 1
    assert rows[0].symbol == "NVDA"
    assert rows[0].action == "remove"


def test_same_symbol_different_list_name_is_two_rows(db_session) -> None:
    """The unique constraint is (symbol, list_name), not symbol alone."""
    set_override(db_session, symbol="MSFT", list_name="watchlist", action="add", created_by="owner")
    set_override(db_session, symbol="MSFT", list_name="would_own", action="add", created_by="owner")
    db_session.commit()
    rows = all_overrides(db_session)
    assert len(rows) == 2
    list_names = {row.list_name for row in rows}
    assert list_names == {"watchlist", "would_own"}


def test_clear_override_returns_false_when_nothing_was_there(db_session) -> None:
    result = clear_override(db_session, symbol="GOOG", list_name="watchlist")
    db_session.commit()
    assert result is False
    assert all_overrides(db_session) == []


def test_clear_override_returns_true_and_removes_the_row(db_session) -> None:
    set_override(db_session, symbol="AMD", list_name="watchlist", action="add", created_by="owner")
    db_session.commit()
    result = clear_override(db_session, symbol="AMD", list_name="watchlist")
    db_session.commit()
    assert result is True
    assert all_overrides(db_session) == []


def test_clear_override_is_case_insensitive(db_session) -> None:
    set_override(db_session, symbol="AMD", list_name="watchlist", action="add", created_by="owner")
    db_session.commit()
    result = clear_override(db_session, symbol="amd", list_name="watchlist")
    db_session.commit()
    assert result is True
    assert all_overrides(db_session) == []


def test_clear_override_only_affects_the_matching_list_name(db_session) -> None:
    set_override(db_session, symbol="AMD", list_name="watchlist", action="add", created_by="owner")
    set_override(db_session, symbol="AMD", list_name="would_own", action="add", created_by="owner")
    db_session.commit()
    result = clear_override(db_session, symbol="AMD", list_name="watchlist")
    db_session.commit()
    assert result is True
    rows = all_overrides(db_session)
    assert len(rows) == 1
    assert rows[0].list_name == "would_own"


def test_created_by_is_stored_and_returned(db_session) -> None:
    set_override(
        db_session,
        symbol="IBM",
        list_name="would_own",
        action="add",
        created_by="ian@example.com",
    )
    db_session.commit()
    rows = all_overrides(db_session)
    assert len(rows) == 1
    assert rows[0].created_by == "ian@example.com"


def test_all_overrides_returns_every_row(db_session) -> None:
    set_override(db_session, symbol="A", list_name="watchlist", action="add", created_by="x")
    set_override(db_session, symbol="B", list_name="would_own", action="add", created_by="x")
    db_session.commit()
    rows = all_overrides(db_session)
    assert len(rows) == 2
    symbols = {row.symbol for row in rows}
    assert symbols == {"A", "B"}
