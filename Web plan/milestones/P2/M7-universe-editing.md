# Milestone 7 — Universe Editing

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `would_own` and `watchlist` editable from the browser, as reversible audited deltas
over a YAML file that stays the documented base. Then close out P2.

**Spec:** `Web plan/P2-design.md` §7 in full, §14. **Index:**
`Web plan/P2-IMPLEMENTATION-PLAN.md`. **Depends on:** Milestone 6.

**Read §7.1 before anything else.** `would_own` is read by
`src/strategies/cash_secured_put.py:93` to decide CSP eligibility. Adding a symbol to it from a
browser changes what the system may be assigned shares of. This is not a CRUD screen with a
config file behind it.

**The one thing that keeps this safe is the narrow surface.** `sectors` feeds
`src/engine/risk_engine.py:41`'s concentration limits and is **not overridable**. If you find
yourself widening `list_name` beyond `would_own` and `watchlist`, stop.

---

## Task 7.1 — `UniverseOverrideRow` and its storage helpers `[GLM]`

**Files:**
- Modify: `src/storage/models.py` (add `UniverseOverrideRow`)
- Create: `src/storage/universe_overrides.py`
- Modify: `ARCHITECTURE.md` (`src/storage/` table and data-flow section)
- Test: `tests/test_storage_universe_overrides.py`

**Interfaces:**

```python
class UniverseOverrideRow(Base):
    __tablename__ = "universe_overrides"
    __table_args__ = (
        UniqueConstraint("symbol", "list_name", name="uq_universe_overrides_symbol_list"),
    )

    id: Mapped[int]
    symbol: Mapped[str]              # upper-cased on write, indexed
    list_name: Mapped[str]           # "would_own" | "watchlist" — nothing else, ever
    action: Mapped[str]              # "add" | "remove"
    created_at: Mapped[datetime]
    created_by: Mapped[str]          # user id; the audit trail
```

```python
def set_override(session, *, symbol: str, list_name: str, action: str, created_by: str) -> None:
    """Upsert. A later override for the same (symbol, list_name) replaces the earlier one."""

def clear_override(session, *, symbol: str, list_name: str) -> bool:
    """Revert to the YAML base. Returns True if an override existed."""

def all_overrides(session) -> list[UniverseOverrideRow]: ...
```

**One row per `(symbol, list_name)`, enforced by the unique constraint.** An add followed by a
remove is one row with `action="remove"`, not two rows to reconcile at read time.

Required behaviours, each with a test:
- `set_override` upserts: adding then removing the same symbol leaves one row.
- Symbols are upper-cased on write, so `nvda` and `NVDA` cannot both exist.
- `clear_override` returns `False` when nothing was there.
- `created_by` is stored and returned.

- [ ] Write the tests, implement, run the full suite, update `ARCHITECTURE.md`, commit.

---

## Task 7.2 — `effective_universe()` `[SONNET]`

**The composition layer. Its fallback semantics are the safety property.**

**Context.** `get_config()` is `@functools.lru_cache(maxsize=1)`, so anything composed at config
load is invisible to a running process until it restarts. Composing inside `get_config()` would
also make `src/common/config.py` import a storage module, and `get_config()` is called from the
risk engine. Spec §7.3 explains why a separate accessor is the answer.

**Files:** Create `src/common/universe.py`. Modify `README.md` layout table,
`ARCHITECTURE.md` folder guide. Test `tests/test_effective_universe.py`.

**Interfaces:**

```python
OVERRIDABLE_LISTS: frozenset[str] = frozenset({"would_own", "watchlist"})

def effective_universe() -> dict[str, Any]:
    """config/universe.yaml with universe_overrides composed onto it.

    Only `would_own` and `watchlist` are composed; every other key is passed through from
    the YAML untouched, so sectors (and therefore risk_engine's concentration limits) can
    never be moved from the web. See Web plan/P2-design.md §7.2.

    Cached for `_TTL_SECONDS`. An unreadable overrides table returns the YAML base — the
    safe direction — and logs a warning.
    """

def invalidate_universe_cache() -> None:
    """Called by the drain after applying a universe command, so an edit is visible at once
    in the process that made it rather than up to _TTL_SECONDS later."""
```

**Design points that are not negotiable:**

1. **Only the two overridable lists are composed.** Every other key is a passthrough. A test
   asserts that an override row written directly with `list_name="sectors"` — bypassing the API
   guard entirely — changes nothing about the returned `sectors` map. Defence in depth: the API
   refuses it, the schema refuses it, and the composer ignores it.
2. **An unreadable overrides table returns the YAML base.** Not an exception, not an empty
   universe. If SQLite is locked, the scan must keep working against the file it has always
   had. Log a warning, return the base.
3. **A `remove` for a symbol in `actively_wheeling` is ignored at composition time**, in addition
   to being refused at the API. You cannot stop being willing to own something you are actively
   wheeling.
4. **Ordering is stable.** A composed list returns YAML entries in file order first, then added
   symbols in `created_at` order. A universe list whose order shuffles between calls would make
   scan behaviour non-reproducible.
5. TTL of 60 seconds, from a module constant, not a magic number at the call site.

- [ ] **Step 1: Write the failing test**

```python
"""The YAML is the base. Overrides are deltas. Some things are not overridable at all."""

from __future__ import annotations

from src.common.universe import effective_universe, invalidate_universe_cache


def test_an_add_appears_in_would_own(db_session, yaml_universe) -> None:
    set_override(db_session, symbol="PLTR", list_name="would_own",
                 action="add", created_by="owner")
    invalidate_universe_cache()
    assert "PLTR" in effective_universe()["would_own"]


def test_a_remove_takes_a_symbol_out(db_session, yaml_universe) -> None:
    ...


def test_sectors_can_never_be_overridden(db_session, yaml_universe) -> None:
    """Bypass the API entirely. The composer must still ignore it.

    sectors feeds risk_engine's concentration limits. No web path may move it.
    """
    base = dict(effective_universe()["sectors"])
    db_session.add(UniverseOverrideRow(symbol="NVDA", list_name="sectors",
                                       action="add", created_by="owner"))
    db_session.commit()
    invalidate_universe_cache()
    assert effective_universe()["sectors"] == base


def test_an_unreadable_overrides_table_falls_back_to_the_yaml(monkeypatch, yaml_universe):
    """A locked database must not empty the universe mid-scan."""
    monkeypatch.setattr("src.common.universe._read_overrides",
                        lambda: (_ for _ in ()).throw(OperationalError("locked", None, None)))
    invalidate_universe_cache()
    assert effective_universe()["would_own"] == yaml_universe["would_own"]


def test_removing_an_actively_wheeling_symbol_is_ignored(db_session, yaml_universe) -> None:
    wheeling = yaml_universe["actively_wheeling"][0]
    set_override(db_session, symbol=wheeling, list_name="would_own",
                 action="remove", created_by="owner")
    invalidate_universe_cache()
    assert wheeling in effective_universe()["would_own"]


def test_ordering_is_stable_across_calls(db_session, yaml_universe) -> None:
    set_override(db_session, symbol="PLTR", list_name="would_own",
                 action="add", created_by="owner")
    invalidate_universe_cache()
    assert effective_universe()["would_own"] == effective_universe()["would_own"]


def test_every_non_overridable_key_passes_through_untouched(yaml_universe) -> None:
    eff = effective_universe()
    for key in ("sectors", "leveraged_etfs", "strike_bands", "actively_wheeling"):
        assert eff[key] == yaml_universe[key]
```

- [ ] **Step 2:** Implement. Run the gate, update `README.md` and `ARCHITECTURE.md`, commit.

---

## Task 7.3 — Migrate the universe consumers `[SONNET]`

**Trading-system code, including a strategy generator.**

**Context.** Three trading modules read `cfg.universe` for the two overridable lists. They must
read through `effective_universe()` instead, or an edit does nothing.

**Files:** Modify `src/strategies/cash_secured_put.py`, `src/orchestrator/scan.py`,
`src/orchestrator/eod_report.py`, `src/api/routers/universe.py`,
`src/api/routers/research.py`, `src/research/checks/warnings.py`. Test
`tests/test_universe_consumers.py`.

**The call sites, from the design's §7.3 diagram:**

| File | Line | Reads | Change |
|---|---|---|---|
| `src/strategies/cash_secured_put.py` | 93 | `cfg.universe["would_own"]` | `effective_universe()["would_own"]` |
| `src/orchestrator/scan.py` | 1117 | `cfg.universe.get("would_own")` | same |
| `src/orchestrator/eod_report.py` | 106, 354 | `cfg.universe.get("watchlist")` | same |
| `src/api/routers/universe.py` | 49 | `cfg.universe` | same |
| `src/api/routers/research.py` | 196, 366 | `cfg.universe` | same |
| `src/research/checks/warnings.py` | 34, 40 | `leveraged_etfs`, `would_own` | `would_own` only |

**`src/engine/risk_engine.py:41` and `:82` are NOT changed.** They read `sectors`, which is not
overridable. Leaving them on `get_config()` is the point: the risk engine keeps reading the file
and nothing else. A test asserts `risk_engine.py` does not import `effective_universe`.

**Do not change `src/orchestrator/scan.py:1118`'s `actively_wheeling` read** or
`src/ibkr/market_data.py:536`'s `strike_bands` read. Neither list is overridable.

- [ ] **Step 1: Write the failing test**

```python
"""An override changes what the system does. Except where it must not."""

def test_a_would_own_add_makes_a_symbol_csp_eligible(db_session, yaml_universe) -> None:
    """The single most consequential edit in the system. It must actually work."""
    from src.strategies.cash_secured_put import generate_cash_secured_puts
    # PLTR is not in the YAML would_own; assert it generates nothing, add the override,
    # assert it now generates.


def test_a_would_own_remove_makes_a_symbol_csp_ineligible(db_session, yaml_universe) -> None:
    ...


def test_the_risk_engine_still_reads_the_file(monkeypatch) -> None:
    """sectors is not overridable, so risk_engine must not go through the accessor."""
    text = (ROOT / "src" / "engine" / "risk_engine.py").read_text(encoding="utf-8")
    assert "effective_universe" not in text


def test_strike_bands_and_actively_wheeling_still_read_the_file() -> None:
    ...
```

- [ ] **Step 2:** Migrate the call sites. Keep the diff minimal: one import and one expression per
  site. Do not refactor anything else in these files.

- [ ] **Step 3: Run the full suite.** This changes a strategy generator's eligibility check.
  Every pre-existing CSP, scan and EOD test must still pass. If one fails, the migration is wrong
  and the test is right.

- [ ] **Step 4:** Verify the fence is still green: `src/strategies/` must still not import
  `src.api` or `src.research`. `src/common/universe.py` is neither, so this is fine, but confirm
  rather than assume. Commit.

---

## Task 7.4 — The `universe_add` and `universe_remove` handlers `[SONNET]`

**Enforces the narrow override surface at the boundary.**

**Files:** Modify `src/notify/command_drain.py`, `src/api/routers/commands.py`,
`src/api/routers/universe.py`, `docs/web/commands.md`. Test `tests/test_drain_universe.py`.

**Interfaces:**

```
POST   /universe/{list_name}/{symbol}    → creates a universe_add intent
DELETE /universe/{list_name}/{symbol}    → creates a universe_remove intent
```

Both are thin wrappers over `POST /commands`, provided because they are the natural REST shape
for the UI. They perform the same validation and return the same `CommandStatus`.

Required behaviours, each with a test:
- **`list_name` outside `{would_own, watchlist}` is `422`**, and no command row is created. One
  test per rejected name: `sectors`, `leveraged_etfs`, `strike_bands`, `actively_wheeling`.
- **Removing a symbol that is in `actively_wheeling` is `409`** with a reason the UI can render:
  you cannot stop being willing to own something you are actively wheeling.
- An unknown symbol is `404`, checked against the research symbol directory, so an override
  cannot name a ticker that does not exist.
- The handler calls `invalidate_universe_cache()` after applying, so the edit is visible
  immediately in `approval_service` rather than up to 60 seconds later.
- The handler applies with `ib is None`.
- `GET /universe` returns `editable: true`, and each list reports its own
  `overridable: bool`. Non-overridable lists render read-only with a note; they are not hidden.
- An overridden entry is returned with `overridden: true`, `created_by` and `created_at`, so the
  UI can show provenance and offer a revert.

- [ ] **Step 1: Write the failing test**

```python
"""The override surface is two lists wide, and that is the safety property."""

import pytest

REFUSED_LISTS = ("sectors", "leveraged_etfs", "strike_bands", "actively_wheeling")


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


def test_an_unknown_symbol_is_refused(client) -> None:
    assert client.post("/universe/watchlist/ZZZZZZ", headers=AUTH).status_code == 404


@pytest.mark.asyncio
async def test_applying_an_override_invalidates_the_cache(drain_env) -> None:
    """An edit must be live in this process at once, not in 60 seconds."""
    ...


def test_the_universe_route_reports_which_lists_are_editable(client) -> None:
    body = client.get("/universe", headers=AUTH).json()
    editable = {lst["name"] for lst in body["lists"] if lst["overridable"]}
    assert editable == {"would_own", "watchlist"}
```

- [ ] **Step 2:** Implement, run the full suite, update `docs/web/commands.md` and
  `docs/web/api.md`, commit.

---

## Task 7.5 — The universe edit UI `[GLM]`

**Files:** Modify `web/app/universe/page.tsx`. Create
`web/components/universe/{UniverseList,OverrideBadge,AddSymbol}.tsx`. Test
`web/components/universe/UniverseList.test.tsx`.

**Interfaces:** consumes `GET /universe`, `POST /universe/{list}/{symbol}`,
`DELETE /universe/{list}/{symbol}`, plus M3's `CommandReceipt` and `ConfirmAction`.

Required behaviours, each with a test:
- Add and remove controls render **only** on lists whose `overridable` is true. Non-overridable
  lists render with a note saying they are managed in `config/universe.yaml`. A test asserts no
  control exists on the `sectors` list.
- **Adding to `would_own` carries a distinct confirmation** stating plainly that the system may
  sell cash-secured puts on this symbol and may therefore be assigned its shares. Adding to
  `watchlist` does not need that; it is a reporting list. A test asserts the two confirmation
  texts differ.
- An overridden entry renders an `OverrideBadge` with its author and timestamp, plus a revert
  control. The YAML base value stays visible underneath.
- The symbol input searches the existing research symbol directory rather than accepting free
  text, so a typo cannot become a `404`.
- Every mutation renders a `CommandReceipt` and stops polling at a terminal state.
- No em dashes in any of the copy.

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Task 7.6 — Fence test extension `[SONNET]`

**Files:** Modify `tests/test_web_fence.py`.

- [ ] Add:

```python
# ---------------------------------------------------------------------------
# P2 M7 — universe overrides are human-edited config, and only a human writes them.
# See Web plan/P2-design.md §7.4.
# ---------------------------------------------------------------------------


def test_no_enrichment_layer_can_write_a_universe_override() -> None:
    """An override changes CSP eligibility. Only an authenticated human may create one."""
    offenders = [
        str(p.relative_to(ROOT))
        for d in ("claude/eval", "research")
        for p in sorted((ROOT / "src" / d).rglob("*.py"))
        if "universe_overrides" in p.read_text(encoding="utf-8")
        or "set_override" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"an enrichment layer can write the universe: {offenders}"


def test_the_risk_engine_never_reads_an_override() -> None:
    """sectors feeds concentration limits and is deliberately not overridable."""
    text = (ROOT / "src" / "engine" / "risk_engine.py").read_text(encoding="utf-8")
    assert "effective_universe" not in text
    assert "universe_overrides" not in text


def test_the_overridable_set_matches_the_spec_exactly() -> None:
    """A future edit that widens this must fail here first."""
    from src.common.universe import OVERRIDABLE_LISTS
    assert OVERRIDABLE_LISTS == frozenset({"would_own", "watchlist"})
```

- [ ] Run the full suite. Commit.

---

## Task 7.7 — Close out P2 `[GLM]`

**Files:** `STATUS.md`, `README.md`, `SETUP.md`, `ARCHITECTURE.md`, `CLAUDE.md`,
`docs/web/*`, `Web plan/P2-IMPLEMENTATION-PLAN.md`.

- [ ] **Update `STATUS.md`.** Replace the "P2 — Options console: Deliberately not built" row with
  what was built, in the style M5 and M6 of P0/P1 used: the modules, the routes, the invariants,
  the rulings made along the way, and the test counts. State explicitly what is **not** built:
  no order ticket (spec §4.3), no Tailscale, no `sectors` override, and P3 through P5 still
  deferred.

- [ ] **Update root `CLAUDE.md`** with the three P2 facts, and no more than three, so the file
  does not double:
  1. The API reads the trading database read-only and writes exactly one table,
     `app_commands`, through `src/api/commands.py`.
  2. Every web action is an intent drained by `approval_service`; `_process_button` is called,
     never reimplemented; the Rules Engine remains the only path to an order.
  3. Universe overrides cover `would_own` and `watchlist` only; `sectors` stays file-only so the
     risk engine is unreachable from the web.

  Add a doc-update trigger row: **new command kind → `docs/web/commands.md`**.

- [ ] **Update `README.md`** layout table with `src/api/commands.py`,
  `src/common/universe.py`, `src/execution/promote_pipeline.py`,
  `src/notify/command_drain.py`, and `web/app/options/`.

- [ ] **Update `SETUP.md`** with the `API_TOKEN` change from Task 1.7 and a short section on
  using the options console, mirroring the existing "Using the Telegram bot" section's shape.

- [ ] **Verify `docs/web/commands.md` is complete.** Every kind from 1.3 has a section with its
  payload, dedupe key, what applies it, every failure reason it can return, and what an operator
  should do about each. Cross-check against every `reason` string in `command_drain.py`:

```bash
grep -o 'reason="[a-z_]*"' src/notify/command_drain.py | sort -u
grep -o '^| `[a-z_]*`' docs/web/commands.md | sort -u
```

  Every reason in the first list must appear in the second.

- [ ] **Regenerate the schema and client types:**

```bash
python -c "import json;from src.api.main import create_app;print(json.dumps(create_app().openapi(),indent=2))" > docs/web/openapi.json
cd web && npm run gen:api
```

- [ ] **Add the implementation log** to `Web plan/P2-IMPLEMENTATION-PLAN.md` in the style of
  `milestones/P0-P1/M6-options-recommendations.md`: what each model shipped, what was escalated,
  and every ruling made along the way.

- [ ] **Final gate, all six:**

```bash
python -m pytest -q && ruff check . && mypy src
cd web && npx vitest run && npm run lint && npm run build
```

- [ ] Commit.

---

## Milestone 7 acceptance

- [ ] `would_own` and `watchlist` are editable from the browser, and the edit changes CSP
  eligibility within a minute, verified by a real test against
  `generate_cash_secured_puts`.
- [ ] `sectors` cannot be overridden through the API, through the schema, or through the
  composer, even when a row is inserted directly into the table.
- [ ] `src/engine/risk_engine.py` still reads `get_config()` and imports nothing from the
  override path.
- [ ] Removing an `actively_wheeling` symbol is refused at the API and ignored by the composer.
- [ ] An unreadable overrides table falls back to the YAML base rather than emptying the
  universe.
- [ ] Adding to `would_own` carries a confirmation that names the actual consequence: the system
  may be assigned shares.
- [ ] No enrichment layer can write an override.
- [ ] Every command reason in the code appears in `docs/web/commands.md`.
- [ ] `STATUS.md` records P2 as built and P3 through P5 as still deferred.
- [ ] Full gate green, all six commands.

---

## After P2

Before running any of this with `LIVE_TRADING=true`, work through the four verification steps in
`Web plan/P2-IMPLEMENTATION-PLAN.md` § "Verification before live" and record the results in
`STATUS.md`, the way M4 of P0/P1 recorded its live browser verification.
