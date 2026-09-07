"""The override surface is two lists wide, and that is the safety property.

`POST /universe/{list_name}/{symbol}` and `DELETE /universe/{list_name}/{symbol}` are thin
wrappers over `POST /commands` (M7 Task 7.4): they create `universe_add`/`universe_remove`
intents, applied later by the drain's `_universe_add`/`_universe_remove` handlers
(`src/notify/command_drain.py`). All real validation happens at the API boundary, before a
command row can exist — a `list_name` outside `{would_own, watchlist}` is `422` (enforced by
`Literal` typing on the path parameter, before the route body runs), removing an
`actively_wheeling` symbol from `would_own` is `409`, and an unknown symbol is `404` against
the research symbol directory. A command that reaches the drain is therefore always valid and
always applies — `applied`, never `failed`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.common.config import get_config
from src.research.store.models import SymbolRow
from src.research.store.session import init_research_db, research_session

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

REFUSED_LISTS = ("sectors", "leveraged_etfs", "strike_bands", "actively_wheeling")


@pytest.fixture()
def yaml_universe() -> dict[str, object]:
    """The real, unmodified config/universe.yaml content."""
    return get_config().universe


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A full stack: research DB (symbol directory), trading/storage DB (overrides, commands),
    and the write-scoped command engine — all reset to a fresh tmp_path DB, mirroring the
    composite pattern in tests/test_api_watchlist.py (research + trading) and
    tests/test_promote_guard.py (trading + command engine)."""
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)

    # Research DB — the symbol directory the 404 check reads.
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()

    # Trading/storage DB — universe_overrides, app_commands.
    trading_db = tmp_path / "income_system.db"
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())
    monkeypatch.setattr("src.api.trading_db._cmd_engine", None)
    monkeypatch.setattr("src.api.trading_db._cmd_session_factory", None)

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()

    with research_session() as s:
        s.add_all(
            [
                SymbolRow(symbol="NVDA", cik="1", name="NVIDIA Corp"),
                SymbolRow(symbol="AAPL", cik="2", name="Apple Inc."),
                SymbolRow(symbol="GOOGL", cik="3", name="Alphabet Inc."),
                SymbolRow(symbol="ZZZZ", cik="4", name="Test Filer"),
            ]
        )

    return TestClient(create_app())


@pytest.fixture()
def count_commands():
    """Count rows in `app_commands`, through the read-only engine (test_promote_guard's pattern)."""
    from sqlalchemy import func, select

    from src.api.trading_db import trading_session
    from src.storage.models import AppCommandRow

    def _count() -> int:
        with trading_session() as s:
            return s.execute(select(func.count()).select_from(AppCommandRow)).scalar_one()

    return _count


# ---------------------------------------------------------------------------
# The narrow override surface — non-overridable lists and the wheeling guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("list_name", REFUSED_LISTS)
def test_a_non_overridable_list_is_refused(client, count_commands, list_name) -> None:
    before = count_commands()
    r = client.post(f"/universe/{list_name}/NVDA", headers=AUTH)
    assert r.status_code == 422
    assert count_commands() == before


def test_removing_an_actively_wheeling_symbol_is_refused(client, yaml_universe) -> None:
    wheeling = yaml_universe["actively_wheeling"][0]
    r = client.delete(f"/universe/would_own/{wheeling}", headers=AUTH)
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "actively_wheeling"


def test_removing_the_same_symbol_from_watchlist_is_not_refused(client, yaml_universe) -> None:
    """The guard is would_own-only: removing an actively_wheeling symbol from watchlist is
    harmless and must not 409. NVDA is actively_wheeling and is seeded into the research DB
    by the `client` fixture, so this does not 404 first."""
    wheeling = "NVDA"
    assert wheeling in yaml_universe["actively_wheeling"]
    r = client.delete(f"/universe/watchlist/{wheeling}", headers=AUTH)
    assert r.status_code in (200, 201)


def test_an_unknown_symbol_is_refused(client) -> None:
    assert client.post("/universe/watchlist/ZZZZZZ", headers=AUTH).status_code == 404


def test_an_unknown_symbol_is_refused_on_delete_too(client) -> None:
    assert client.delete("/universe/watchlist/ZZZZZZ", headers=AUTH).status_code == 404


# ---------------------------------------------------------------------------
# The routes create commands, not synchronous mutations
# ---------------------------------------------------------------------------


def test_adding_a_symbol_creates_a_command_and_returns_its_status(client, count_commands) -> None:
    before = count_commands()
    r = client.post("/universe/watchlist/NVDA", headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "universe_add"
    assert body["status"] == "pending"
    assert count_commands() == before + 1


def test_removing_a_symbol_creates_a_command(client, count_commands) -> None:
    before = count_commands()
    r = client.delete("/universe/watchlist/NVDA", headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "universe_remove"
    assert body["status"] == "pending"
    assert count_commands() == before + 1


def test_a_repeat_add_dedupes_to_200(client) -> None:
    first = client.post("/universe/watchlist/NVDA", headers=AUTH)
    assert first.status_code == 201
    second = client.post("/universe/watchlist/NVDA", headers=AUTH)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_viewer_role_cannot_post(client, monkeypatch) -> None:
    """Owner-only, unlike watchlist.py's single-symbol routes — universe edits move CSP
    eligibility."""
    from src.api.auth import Role, User

    def fake_auth(token: str | None):
        if token == TOKEN:
            return User(id="owner", role=Role.OWNER)
        if token == "viewer-token":
            return User(id="viewer", role=Role.VIEWER)
        return None

    monkeypatch.setattr("src.api.deps.authenticate", fake_auth)
    monkeypatch.setattr("src.api.auth.authenticate", fake_auth)

    r = client.post(
        "/universe/watchlist/NVDA", headers={"Authorization": "Bearer viewer-token"}
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# The drain handlers
# ---------------------------------------------------------------------------


@pytest.fixture
def drain_env(monkeypatch, tmp_path):
    """A temp trading DB + fake bot, mirroring tests/test_drain_controls.py's fixture. Only
    the two universe handlers are re-exposed (HANDLERS is saved/restored so a registration
    in one test cannot leak)."""
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()

    from unittest.mock import AsyncMock

    from src.notify.command_drain import HANDLERS
    from src.storage.app_commands import enqueue_command
    from src.storage.models import AppCommandRow

    saved_handlers = dict(HANDLERS)
    HANDLERS.clear()
    HANDLERS.update(
        {k: v for k, v in saved_handlers.items() if k in ("universe_add", "universe_remove")}
    )

    bot = AsyncMock()
    bot.send_message = AsyncMock()

    def enqueue(kind: str, payload: dict, *, requested_by: str = "test") -> int:
        with dbmod.session_scope() as s:
            row, _ = enqueue_command(
                s,
                kind=kind,
                payload=payload,
                requested_by=requested_by,
            )
            return row.id

    def status(cid: int) -> str:
        with dbmod.session_scope() as s:
            row = s.get(AppCommandRow, cid)
            assert row is not None
            return row.status

    def result(cid: int) -> dict:
        with dbmod.session_scope() as s:
            row = s.get(AppCommandRow, cid)
            assert row is not None
            return row.result or {}

    class _DrainEnv:
        pass

    env = _DrainEnv()
    env.bot = bot
    env.enqueue = enqueue
    env.status = status
    env.result = result
    yield env

    HANDLERS.clear()
    HANDLERS.update(saved_handlers)


@pytest.mark.asyncio
async def test_applying_an_override_invalidates_the_cache(drain_env) -> None:
    """An edit must be live in this process at once, not in 60 seconds — proving the
    HANDLER calls invalidate_universe_cache(), not the test itself."""
    from src.common.universe import effective_universe, invalidate_universe_cache
    from src.notify.command_drain import drain_once

    invalidate_universe_cache()
    assert "ZZZZ" not in effective_universe()["would_own"]

    cid = drain_env.enqueue("universe_add", {"symbol": "ZZZZ", "list_name": "would_own"})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    # No explicit invalidate_universe_cache() call here — the handler must have done it.
    assert "ZZZZ" in effective_universe()["would_own"]


@pytest.mark.asyncio
async def test_universe_add_applies_with_no_broker_connection(drain_env) -> None:
    from src.notify.command_drain import drain_once

    cid = drain_env.enqueue("universe_add", {"symbol": "ZZZZ", "list_name": "watchlist"})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"


@pytest.mark.asyncio
async def test_universe_add_upserts_an_add_override(drain_env) -> None:
    from src.storage.db import session_scope
    from src.storage.universe_overrides import all_overrides

    cid = drain_env.enqueue("universe_add", {"symbol": "zzzz", "list_name": "would_own"})

    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    with session_scope() as s:
        rows = [r for r in all_overrides(s) if r.symbol == "ZZZZ"]
    assert len(rows) == 1
    assert rows[0].action == "add"
    assert rows[0].list_name == "would_own"


@pytest.mark.asyncio
async def test_universe_remove_upserts_a_remove_override_not_clear(drain_env) -> None:
    """A remove is always an upserted 'remove' row, never clear_override — deleting the row
    would silently do nothing for a YAML-base symbol."""
    from src.storage.db import session_scope
    from src.storage.universe_overrides import all_overrides

    cid = drain_env.enqueue("universe_remove", {"symbol": "AAPL", "list_name": "would_own"})

    from src.notify.command_drain import drain_once

    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    with session_scope() as s:
        rows = [r for r in all_overrides(s) if r.symbol == "AAPL" and r.list_name == "would_own"]
    assert len(rows) == 1
    assert rows[0].action == "remove"


@pytest.mark.asyncio
async def test_universe_handlers_send_no_telegram_notification(drain_env) -> None:
    """Unlike halt/resume/set_autonomy, a universe edit is reversible non-urgent config."""
    from src.notify.command_drain import drain_once

    drain_env.enqueue("universe_add", {"symbol": "ZZZZ", "list_name": "watchlist"})
    drain_env.enqueue("universe_remove", {"symbol": "AAPL", "list_name": "watchlist"})
    await drain_once(None, drain_env.bot, "chat")

    drain_env.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_repeating_a_universe_add_is_applied_not_an_error(drain_env) -> None:
    """Idempotency shape matches halt/resume/set_autonomy."""
    from src.notify.command_drain import drain_once

    drain_env.enqueue("universe_add", {"symbol": "ZZZZ", "list_name": "watchlist"})
    await drain_once(None, drain_env.bot, "chat")
    cid = drain_env.enqueue("universe_add", {"symbol": "ZZZZ", "list_name": "watchlist"})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"


# ---------------------------------------------------------------------------
# GET /universe — the reshaped response
# ---------------------------------------------------------------------------


def test_the_universe_route_reports_which_lists_are_editable(client) -> None:
    body = client.get("/universe", headers=AUTH).json()
    editable = {lst["name"] for lst in body["lists"] if lst["overridable"]}
    assert editable == {"would_own", "watchlist"}


def test_the_universe_route_lists_exactly_four_in_order(client) -> None:
    body = client.get("/universe", headers=AUTH).json()
    names = [lst["name"] for lst in body["lists"]]
    assert names == ["indexes", "watchlist", "would_own", "actively_wheeling"]


def test_indexes_and_actively_wheeling_are_never_overridable(client) -> None:
    body = client.get("/universe", headers=AUTH).json()
    by_name = {lst["name"]: lst for lst in body["lists"]}
    assert by_name["indexes"]["overridable"] is False
    assert by_name["actively_wheeling"]["overridable"] is False


@pytest.mark.asyncio
async def test_an_overridden_would_own_entry_shows_provenance(client, yaml_universe) -> None:
    """A genuinely new addition (not in the YAML base) shows overridden=True with
    created_by/created_at."""
    assert "ZZZZ" not in yaml_universe["would_own"]
    r = client.post("/universe/would_own/ZZZZ", headers=AUTH)
    assert r.status_code == 201

    from src.notify.command_drain import HANDLERS, drain_once

    assert "universe_add" in HANDLERS  # sanity: the real handler is registered at import time

    await drain_once(None, AsyncMock(), "chat")

    body = client.get("/universe", headers=AUTH).json()
    would_own = next(lst for lst in body["lists"] if lst["name"] == "would_own")
    entry = next((e for e in would_own["entries"] if e["symbol"] == "ZZZZ"), None)
    assert entry is not None
    assert entry["overridden"] is True
    assert entry["removed"] is False
    assert entry["created_by"] == "owner"
    assert entry["created_at"] is not None


@pytest.mark.asyncio
async def test_a_removed_yaml_base_entry_shows_removed_true(client, yaml_universe) -> None:
    """AAPL is would_own but not actively_wheeling — a plain, unguarded remove."""
    symbol = "AAPL"
    assert symbol in yaml_universe["would_own"]
    assert symbol not in yaml_universe["actively_wheeling"]

    r = client.delete(f"/universe/would_own/{symbol}", headers=AUTH)
    assert r.status_code == 201

    from src.notify.command_drain import drain_once

    await drain_once(None, AsyncMock(), "chat")

    body = client.get("/universe", headers=AUTH).json()
    would_own = next(lst for lst in body["lists"] if lst["name"] == "would_own")
    entry = next((e for e in would_own["entries"] if e["symbol"] == symbol), None)
    assert entry is not None
    assert entry["overridden"] is True
    assert entry["removed"] is True
    assert entry["created_by"] == "owner"


def test_indexes_never_carry_override_metadata_even_with_a_stray_row(client) -> None:
    """Defence in depth, mirroring test_effective_universe's test_sectors_can_never_be_overridden
    — a stray override row naming an index symbol must not leak into the indexes list's entries."""
    from src.storage.db import session_scope
    from src.storage.models import UniverseOverrideRow

    with session_scope() as s:
        s.add(
            UniverseOverrideRow(
                symbol="SPY", list_name="indexes", action="add", created_by="owner"
            )
        )

    body = client.get("/universe", headers=AUTH).json()
    indexes = next(lst for lst in body["lists"] if lst["name"] == "indexes")
    entry = next(e for e in indexes["entries"] if e["symbol"] == "SPY")
    assert entry["overridden"] is False
    assert entry["created_by"] is None
    assert entry["created_at"] is None


def test_actively_wheeling_never_carries_override_metadata_even_with_a_stray_row(client) -> None:
    from src.storage.db import session_scope
    from src.storage.models import UniverseOverrideRow

    with session_scope() as s:
        s.add(
            UniverseOverrideRow(
                symbol="NVDA", list_name="actively_wheeling", action="remove", created_by="owner"
            )
        )

    body = client.get("/universe", headers=AUTH).json()
    wheeling = next(lst for lst in body["lists"] if lst["name"] == "actively_wheeling")
    entry = next(e for e in wheeling["entries"] if e["symbol"] == "NVDA")
    assert entry["overridden"] is False
    assert entry["removed"] is False
