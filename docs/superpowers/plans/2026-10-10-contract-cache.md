# Contract Lookup Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ask IBKR to look up each option contract once a day, not every 15 minutes. Remember the answer on disk so restarts don't repeat it. Stop the wheel scan and the spreads GEX build from timing each other out. Make a restart mid-session stop forcing a full rescan.

**Architecture:** A new neutral module, `src/ibkr/contract_cache.py`, owns a small SQLite file, `data/contracts.db`. It records every lookup answer: the conId, or "IBKR has no such contract". It also provides a cross-process file lock that lets one lookup chunk at a time reach Gateway. `src/ibkr/contracts.py::qualify_options_async`, the single lookup path every process already uses (scan, monitor, portfolio greeks, spreads), consults the cache first and asks IBKR only for misses. Separately, the approval service's "full sweep on the first cycle after process start" becomes "full sweep on the first cycle of the ET trading day", and its retry queue is persisted.

**Tech Stack:** Python 3.12, ib_async 2.1.0, SQLAlchemy 2 + SQLite (WAL), `fcntl` file locks, pytest (+ pytest-asyncio auto mode), ruff, mypy.

**Spec:** No separate spec. The "Background" section below is the design; it came out of the 2026-10-09/10 log review (see `STATUS.md` → "Bugs fixed (2026-10-09 — RTH log review …)", the "Open: contract qualification is slow" bullet).

## Progress log

| Task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| 1. Cache store | done | 0148284 | pytest 3255 passed/1 skipped · ruff ✓ · mypy ✓ | 2026-10-10 | `prune()` reads `rowcount` via `getattr` (repo idiom, mypy sees ORM `Result`); docs rows deferred to Task 2, which owns them; plan file itself first committed here |
| 2. Cache in `qualify_options_async` | done | 4a2d3c8 | pytest 3263 passed/1 skipped · ruff ✓ · mypy ✓ | 2026-10-10 | `src/ibkr/market_data.py` added to the commit (the step's `git add` list omitted it); ARCHITECTURE `settings.yaml` config row also gained the two Task 1 keys (doc-update rule for new config keys) |
| 3. Cross-process lookup lock | done | f1f7052, ae4d228 | pytest 3267 passed/1 skipped · ruff ✓ · mypy ✓ | 2026-10-10 | `data/contracts.lock` was not git-ignored → `data/*.lock` added (ae4d228) |
| 4. Full sweep once per ET day; persisted retry queue | done | c9c1f36 | pytest 3269 passed/1 skipped · ruff ✓ · mypy ✓ | 2026-10-10 | Step 4's mtime check was confounded by the live services writing the same DB; a throwaway pytest spy found 9 existing tests (8 in test_notify.py, 1 in test_buy_list_cadence.py) writing the new keys to the real `data/income_system.db` — they now take the `db` fixture (re-run: zero real-DB writes). Also reworded the remaining "at startup" full-sweep phrasing in `How the scan works.md` and the `_run_intraday_scan` docstring |
| 5. Live verification + docs close-out | partial (cold-cache day) | 687d192 merge | 3 RTH cycles measured 2026-10-09 ET | 2026-10-10 | Merged to `main` (687d192) and restarted 14:11 ET mid-session. **Step 3 ✓:** the post-restart cycle used the normal gate (15/32 material, no forced sweep). **Cache ✓:** spreads re-quotes went to 92 cached / 0 asked; by 14:52 ET `contracts.db` held 1,650 contracts across 16 symbols (310 known-missing). **Step 2 ✗ (not yet):** every wheel symbol scanned so far was a first-time (cold) lookup, so no warm cycle has been seen; budget still exhausted (12/15, 9/13, 5/11 deferred). **Chunk timeouts persist:** 14:15 ET 0 of 416 qualified (every chunk timed out, lock busy twice); 14:30 none; 14:45 PLTR 13/136, SOXL 134/320. A timed-out chunk discards every answer inside it (ib_async gathers the chunk) — follow-up proposed, not built. **Step 4 n/a:** the GEX map can't build (no SPX/SPY index price, Error 354; pre-existing since 01:59 SGT on the old code), so no overlap to measure. |


**Final review (2026-10-10, fresh reviewer over 447352a..c9c1f36): "with fixes".** Fixed in one pass, each RED→GREEN:
- A `None` slot is remembered as missing only when IBKR answered **Error 200** for that contract (`errorEvent`), on top of the sibling rule. ib_async turns *every* failed request into `None`, and once an expiry has cached hits the sibling rule alone would remember a transient failure for the day. (Dropping cached siblings from the rule instead, as first suggested, would re-ask every non-existent strike every cycle from day 2.) `test_failed_request_beside_a_cached_sibling_is_not_cached`, `test_no_security_definition_beside_a_cached_sibling_is_cached`.
- Answers are recorded after every chunk, so a symbol cancelled by `symbol_timeout_seconds` keeps them. `test_answers_are_kept_when_the_symbol_is_cancelled_mid_qualification`.
- Losing the create-tables race on a brand-new `contracts.db` (every process starts at once) no longer disables the cache for the process. `test_losing_the_create_tables_race_still_opens_the_cache`.
- The operator's in-progress universe doc edits, swept into f1f7052/c9c1f36 by `git add`, were backed out of the branch (6db353d) and left in the working tree.

---

## Background — the problem, and why this fixes it

### What "qualifying" a contract is

Before the system can request a price for an option, IBKR needs that option's **conId**, its permanent internal ID. Looking it up (`reqContractDetails`, wrapped by ib_async as `qualifyContractsAsync`) is a separate round trip per contract. An option's conId **never changes** between listing and expiry.

### What happens today

Every 15-minute scan cycle builds, for each material symbol, every (expiry × strike × right) combination in its strike band. For AMD that's about 480 combinations; for GOOGL about 240. It then asks IBKR to look **all of them** up again, even though nothing about them changed since the last cycle. About a quarter of them don't exist: the strike list from `reqSecDefOptParams` is the union across all expiries, and weeklies have fewer strikes. Those come back as `Error 200: No security definition` (the "Unknown contract" log spam) and are asked again the next cycle, and the next.

Since the evening of 2026-10-09, IBKR's contract-lookup latency has been erratic: about 0.1 s per contract at 21:30 SGT, 0.5 s at 01:09, and one 10-contract batch didn't answer within 60 s. Lookups are processed roughly one at a time, so a 40-contract chunk takes up to ~20 s, exactly the per-chunk timeout. A timed-out chunk is dropped entirely. Result, in the 2026-10-10 01:00 scan:

- GOOGL: 120 s of lookups, **0 contracts qualified**
- AMD and AMZN: hit `symbol_timeout_seconds` (150 s)
- the 350 s cycle budget ran out after **3 of 20** symbols → CC=0 CSP=0

The spreads service makes it worse. Its GEX map looks up a few hundred SPX options at service start and every hour, on the same Gateway. At 01:00–01:05 both processes' chunks were in flight together, and **both** timed out.

### Why the cache fixes it

| | Today | With the cache |
|---|---|---|
| Lookups per scan cycle | Every contract of every material symbol (thousands) | Only contracts never seen before today: new weekly expiries, strikes the band newly reaches as spot moves. Usually zero to a few dozen |
| Non-existent strikes | Re-asked every cycle | Remembered as "missing" for the rest of the ET day |
| After a restart | Everything re-looked-up | Nothing: the cache is on disk |
| Spreads GEX + wheel scan | Both send hundreds of lookups at once and time each other out | Both mostly hit the cache; residual misses take turns via the lock (Task 3) |

**Prices are never cached.** Bid/ask/greeks must stay fresh, and this plan doesn't touch the quote path. Only the contract *identity* (conId) is remembered, and identity can't go stale before expiry.

### Safety rules for remembering "missing"

A "missing" answer is only trusted when IBKR plainly said so:

1. **Timed-out chunks record nothing.** "No answer" isn't "doesn't exist".
2. **A missing strike is cached only when a sibling in the same (symbol, expiry, trading class) qualified** in this call or is already cached. If an *entire* expiry comes back missing, that's a transient failure (the expiry list came from IBKR itself), so nothing is cached.
3. **Missing entries expire at the next ET date.** IBKR lists new strikes overnight, so a strike missing today is asked again tomorrow.
4. **Positive entries expire after their expiry date** and are pruned.
5. **The cache can never break a scan.** Any cache error (locked DB, corrupt file, disk full) logs a warning and falls back to asking IBKR exactly as today.
6. **Corporate actions drop a symbol's entries.** After an uneven split, special dividend or merger, IBKR moves the existing contracts to an *adjusted* trading class (`2AMD`) under the same conIds and lists new standard contracts with new conIds. A cached entry would then point the scan at the adjusted contract. The signature of that event is a **new** trading class appearing in the symbol's `reqSecDefOptParams` list, which the scan already fetches every cycle (about 0.1 s). When one appears, every cached entry for that symbol is deleted and looked up fresh. Classes already present the first time the cache sees a symbol (AMD and GOOGL carry `2AMD`/`2GOOGL` today) don't trigger it. Orders were never at risk: the order path does its own fresh lookup and re-prices at send time.

**Cleanup.** Once per ET day, each process's first use of the cache deletes positive entries whose expiry has passed and "missing" entries from earlier days. Expired contracts are never *asked* for anyway: the scan only builds expiries inside its DTE window, all of which are today or later. Size stays bounded at roughly 34 symbols × a few hundred live contracts (≤ ~20K rows, a few MB).

### Does this change what the scan finds?

No, by design. The same contracts get the same conIds, and every price is fetched fresh exactly as today. The practical difference is that the output becomes **more complete**: today a timed-out lookup chunk silently drops up to 40 contracts (GOOGL ended with zero at 01:00), and those drops go away. Two narrow differences remain, both bounded:
- A strike IBKR lists *intraday* after it was cached as "missing" that morning is skipped until the next day.
- A corporate action is caught on the next cycle via rule 6, not instantly.

### "Upon every restart, the entire 34 symbols are scanned fully again — isn't this redundant?"

Mostly yes. Precisely: the first cycle after any process start **force-fetches the option chain of every actively-wheeled and held name** (20 of the 34). The 14 dip-watch names only get a cheap price check. Two kinds of work happen in that sweep:

- **Contract lookups:** fully redundant. The cache removes them.
- **Fresh quotes:** these must be fetched sometime; prices go stale in minutes. But a forced sweep is redundant too: `scan_state` (each symbol's last scanned spot and time) is **already persisted in the DB**, so the normal materiality gate works right after a restart. Its 120-minute staleness timer (`force_full_scan_minutes`) already guarantees nothing goes unrefreshed for long.

Task 4 changes the trigger from "first cycle since **process start**" to "first cycle of the **ET trading day**", stored in `system_settings`. The morning still gets one full picture; a mid-session restart resumes the normal gate. The one thing the forced sweep was quietly covering is the in-memory retry queue (`pending_retry_symbols`: symbols a previous cycle never reached). Task 4 persists that queue so a restart doesn't drop it.

### "Would it help to run the GEX map first, or the scan first?"

The **GEX map is the more urgent** of the two. It's built at 09:31 ET, spreads entries open at 09:35, and no entry can happen without it. The wheel scan has no minute-level urgency; CSPs and CCs don't care whether they're found at 09:30 or 09:45.

But a strict "GEX first, then scan" ordering would need the two processes to know about each other. The spreads isolation fence deliberately forbids that: the wheel learns about the spreads book only through `src/common/books.py`, and spreads imports no wheel layer. The plan gets the benefit without the coupling:

1. **The cache (Tasks 1–2)** removes nearly all the lookups both sides compete for.
2. **A shared one-at-a-time lookup lock (Task 3)**, at *chunk* granularity: whichever process is looking up contracts holds the lock for one chunk (≤40 contracts), then releases it, so the other side's chunks interleave instead of colliding. Each chunk's 20 s timeout starts **after** the lock is acquired, so neither side ever times out because of the other. The lock lives in `src/ibkr/` (which spreads already imports), so the fence is untouched.

If, after this ships, the 09:30 scan and the 09:31 map still visibly slow each other, the follow-up is a one-line config change: start the wheel's first RTH cycle at 09:45. That's **out of scope** here; decide from Task 5's measurements.

---

## Global Constraints

- Python ≥ 3.12; `ib_async` only (never `ib_insync`); consult `ib_async_documentation.md` before guessing an API.
- The Rules Engine stays the only path to an order. Nothing here touches `src/engine/`, sizing, or order sending. `executor.py`, `position_manager.py`, `roll_executor.py` and `profit_take.py` qualify their single order contract directly with `ib.qualifyContractsAsync`. **Leave them alone:** order paths keep a fresh lookup.
- `src/ibkr/contract_cache.py` may import only the stdlib, SQLAlchemy, `ib_async`, and `src.common.*`, so that both the wheel and the spreads process can load it (`tests/test_spreads_fence.py` must stay green).
- New config keys go in `src/common/config.py::MarketDataCfg`, `config/examples/settings.yaml`, **and** the operator's private `config/settings.yaml` (git-ignored, never `git add` it).
- Tests read the example configs (`IBKR_CONFIG_USE_EXAMPLES=1`). A test must never write to the real `data/contracts.db` or `data/income_system.db`.
- Quality gate before every commit: `python -m pytest -q`, `ruff check .`, `ruff format --check <changed files>`, `mypy src`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Work on a branch (`feat/contract-cache`), never directly on `main`.

## Review Focus

1. **A transient Gateway failure** (farm reconnect, restart mid-scan) returns `None` for a whole chunk or expiry → must **not** be remembered as "missing" for the day. Pinned by Task 2's `test_whole_expiry_missing_is_not_cached` and `test_timed_out_chunk_records_nothing`.
2. **Two processes writing the cache at once** (spreads GEX build + wheel scan) → may slow, never raise into a scan. Pinned by Task 2's `test_cache_failure_falls_back_to_ibkr` and Task 1's WAL/`busy_timeout` engine test.
3. **A contract built with an empty trading class** (portfolio greeks enrichment, the monitor) → IBKR fills in the real class (`AMD`) on qualification; the cache must key on what was *asked*, or those lookups never hit. Pinned by Task 1's `test_key_is_the_requested_trading_class`.
4. **Restart mid-session** → must not drop the retry queue of symbols a cut-short cycle never reached. Pinned by Task 4's `test_retry_queue_survives_a_restart`.
5. **A corporate action re-classes a symbol's contracts mid-life** → the cache must stop handing out the old conIds. Pinned by Task 1's `test_a_new_trading_class_drops_the_symbols_entries` and Task 2's `test_chain_fetch_reports_trading_classes_to_the_cache`. (An unwritable `data/contracts.db` is pinned by Task 1's `test_unusable_cache_path_disables_the_cache`.)

---

### Task 1: The cache store

**Files:**
- Create: `src/ibkr/contract_cache.py`
- Modify: `src/common/config.py` (`MarketDataCfg` + a `contract_cache_url_abs()` method on `Config`, beside `news_db_url_abs`)
- Modify: `config/examples/settings.yaml`, `config/settings.yaml` (private, `market_data:` block)
- Modify: `tests/conftest.py` (autouse fixture: no test touches the real cache)
- Create: `tests/test_contract_cache.py`
- Modify: `tests/test_spreads_fence.py` (no change expected; just run it)

**Interfaces:**
- Produces:
  - `Key = tuple[str, str, float, str, str, str]` — `(symbol, expiry YYYYMMDD, strike, right C/P, trading_class, exchange)`
  - `contract_key(c: Any) -> Key`
  - `@dataclass Lookup: hits: list[Any]; misses: list[Any]; known_missing: int`
  - `class ContractCache(url: str, *, today: Callable[[], date] = _et_today)` with `.lookup(contracts: Sequence[Any]) -> Lookup`, `.record(entries: Sequence[tuple[Key, Any | None]]) -> None`, `.prune() -> int`, `.lock_path: Path`
  - `confirmed_missing(missing: Sequence[Key], good: Sequence[Key]) -> list[Key]`
  - `ContractCache.note_trading_classes(symbol: str, classes: Iterable[str]) -> bool`: returns True when a new class appeared and the symbol's entries were dropped
  - `get_contract_cache() -> ContractCache | None` (process-wide; `None` when disabled or unusable)

- [x] **Step 1: Add config keys**

In `src/common/config.py`, inside `MarketDataCfg`, right after `qualify_timeout_seconds`:

```python
    # Contract lookup cache (2026-10-10, docs/superpowers/plans/2026-10-10-contract-cache.md).
    # Every IBKR process records each option contract's conId — or "IBKR has no such contract" —
    # in one shared SQLite file and asks IBKR only for contracts it hasn't seen today. Prices are
    # never cached; only identity, which can't change before expiry.
    contract_cache_enabled: bool = True
    contract_cache_db_url: str = "sqlite:///data/contracts.db"
```

On the `Config` class, beside `news_db_url_abs`:

```python
    def contract_cache_url_abs(self) -> str:
        """Resolve the relative contract-cache sqlite path against the project root."""
        url = self.market_data.contract_cache_db_url
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            return f"sqlite:///{(ROOT / rel).as_posix()}"
        return url
```

In both `config/examples/settings.yaml` and `config/settings.yaml`, under `market_data:` after `qualify_timeout_seconds:`:

```yaml
  # Contract lookup cache: each option contract is looked up at IBKR once a day (and survives
  # restarts) instead of every 15-min cycle. Only identity is cached, never prices.
  contract_cache_enabled: true
  contract_cache_db_url: "sqlite:///data/contracts.db"
```

- [x] **Step 2: Keep tests off the real cache**

Append to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _no_real_contract_cache(monkeypatch):
    """No test may read or write data/contracts.db: the process-wide cache starts "failed", so
    get_contract_cache() returns None. Tests that exercise the cache build a ContractCache on
    tmp_path and pass it explicitly (or reset these two attributes themselves)."""
    import src.ibkr.contract_cache as cc

    monkeypatch.setattr(cc, "_CACHE", None)
    monkeypatch.setattr(cc, "_CACHE_FAILED", True)
```

- [x] **Step 3: Write the failing tests**

Create `tests/test_contract_cache.py`:

```python
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
```

- [x] **Step 4: Run them to verify they fail**

Run: `python -m pytest tests/test_contract_cache.py -q`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'src.ibkr.contract_cache'`

- [x] **Step 5: Implement `src/ibkr/contract_cache.py`**

```python
"""Shared option-contract lookup cache (docs/superpowers/plans/2026-10-10-contract-cache.md).

Every IBKR process — scan, monitor, portfolio greeks, spreads — qualifies option contracts
through ``src.ibkr.contracts.qualify_options_async``, which consults this cache first. A
contract's conId can't change before expiry, so each one is looked up at IBKR once; a strike
IBKR says doesn't exist is remembered for the rest of the ET day. Prices are never cached.

Neutral reference data on purpose: this module imports only the stdlib, SQLAlchemy, ib_async
and src.common, so the wheel and the spreads process can both use it without crossing either
fence. It owns ``data/contracts.db``; nothing else writes it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, Float, Integer, String, UniqueConstraint, create_engine, delete, event, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from src.common.config import get_config
from src.common.logging import get_logger

log = get_logger(__name__)

ET = ZoneInfo("America/New_York")

# (symbol, expiry YYYYMMDD, strike, right C/P, trading_class, exchange) — as the caller ASKED.
Key = tuple[str, str, float, str, str, str]


def _et_today() -> date:
    return datetime.now(ET).date()


class ContractCacheBase(DeclarativeBase):
    pass


class ContractRow(ContractCacheBase):
    __tablename__ = "option_contracts"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "expiry", "strike", "right", "trading_class", "exchange",
            name="uq_option_contract",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16))
    expiry: Mapped[str] = mapped_column(String(8))
    strike: Mapped[float] = mapped_column(Float)
    right: Mapped[str] = mapped_column(String(1))
    trading_class: Mapped[str] = mapped_column(String(16), default="")
    exchange: Mapped[str] = mapped_column(String(16), default="SMART")
    # None = IBKR answered "no security definition" (a negative entry, valid for checked_on).
    con_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    multiplier: Mapped[str] = mapped_column(String(8), default="")
    currency: Mapped[str] = mapped_column(String(8), default="")
    local_symbol: Mapped[str] = mapped_column(String(32), default="")
    checked_on: Mapped[date] = mapped_column(Date)


class ChainClassRow(ContractCacheBase):
    """The trading classes IBKR listed for a symbol's option chain when last seen. A class
    newly appearing marks a corporate action (see ContractCache.note_trading_classes)."""

    __tablename__ = "chain_classes"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    classes: Mapped[str] = mapped_column(String(256))  # sorted, comma-joined


def contract_key(c: Any) -> Key:
    return (
        str(c.symbol).upper(),
        str(c.lastTradeDateOrContractMonth)[:8],
        round(float(c.strike), 4),
        str(c.right).upper()[:1],
        str(getattr(c, "tradingClass", "") or ""),
        str(getattr(c, "exchange", "") or "SMART"),
    )


def confirmed_missing(missing: Sequence[Key], good: Sequence[Key]) -> list[Key]:
    """The missing keys safe to remember: those whose (symbol, expiry, trading class) has at
    least one contract that DID qualify. A whole expiry coming back missing is a transient
    failure — the expiry list came from IBKR itself — so none of it is remembered."""
    groups = {(k[0], k[1], k[4]) for k in good}
    return [k for k in missing if (k[0], k[1], k[4]) in groups]


@dataclass
class Lookup:
    hits: list[Any] = field(default_factory=list)
    misses: list[Any] = field(default_factory=list)
    known_missing: int = 0


class ContractCache:
    def __init__(self, url: str, *, today: Callable[[], date] = _et_today) -> None:
        if url.startswith("sqlite:///"):
            Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(url, future=True)

        @event.listens_for(self._engine, "connect")
        def _pragmas(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        ContractCacheBase.metadata.create_all(self._engine)
        self._session = sessionmaker(bind=self._engine, future=True, expire_on_commit=False)
        self._today = today
        self.lock_path = Path(url[len("sqlite:///") :]).with_suffix(".lock")

    def lookup(self, contracts: Sequence[Any]) -> Lookup:
        today = self._today()
        keys = [contract_key(c) for c in contracts]
        symbols = {k[0] for k in keys}
        with self._session() as s:
            rows = s.scalars(select(ContractRow).where(ContractRow.symbol.in_(symbols))).all()
        index = {
            (r.symbol, r.expiry, round(r.strike, 4), r.right, r.trading_class, r.exchange): r
            for r in rows
        }
        out = Lookup()
        for c, k in zip(contracts, keys, strict=True):
            r = index.get(k)
            if r is not None and r.con_id is not None and r.expiry >= today.strftime("%Y%m%d"):
                c.conId, c.multiplier, c.currency = r.con_id, r.multiplier, r.currency
                c.localSymbol = r.local_symbol
                out.hits.append(c)
            elif r is not None and r.con_id is None and r.checked_on == today:
                out.known_missing += 1
            else:
                out.misses.append(c)
        return out

    def record(self, entries: Sequence[tuple[Key, Any | None]]) -> None:
        if not entries:
            return
        today = self._today()
        values = [
            {
                "symbol": k[0], "expiry": k[1], "strike": k[2], "right": k[3],
                "trading_class": k[4], "exchange": k[5],
                "con_id": int(q.conId) if q is not None else None,
                "multiplier": str(getattr(q, "multiplier", "") or "") if q is not None else "",
                "currency": str(getattr(q, "currency", "") or "") if q is not None else "",
                "local_symbol": str(getattr(q, "localSymbol", "") or "") if q is not None else "",
                "checked_on": today,
            }
            for k, q in entries
        ]
        stmt = insert(ContractRow).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "expiry", "strike", "right", "trading_class", "exchange"],
            set_={c: stmt.excluded[c] for c in ("con_id", "multiplier", "currency", "local_symbol", "checked_on")},
        )
        with self._session() as s, s.begin():
            s.execute(stmt)

    def note_trading_classes(self, symbol: str, classes: Iterable[str]) -> bool:
        """Record the chain's trading classes. A class not seen before for this symbol means a
        corporate action re-classed its contracts: drop every cached entry for the symbol and
        return True. First sight only sets the baseline; a class disappearing drops nothing."""
        sym = symbol.upper()
        now = sorted({c for c in classes if c})
        with self._session() as s, s.begin():
            row = s.get(ChainClassRow, sym)
            before = set(row.classes.split(",")) if row is not None and row.classes else None
            added = before is not None and bool(set(now) - before)
            if added:
                s.execute(delete(ContractRow).where(ContractRow.symbol == sym))
                log.warning(
                    "contract cache: new trading class for %s (%s) — dropped its cached contracts",
                    sym, sorted(set(now) - (before or set())),
                )
            if row is None:
                s.add(ChainClassRow(symbol=sym, classes=",".join(now)))
            else:
                row.classes = ",".join(now)
        return added

    def prune(self) -> int:
        today = self._today()
        with self._session() as s, s.begin():
            result = s.execute(
                delete(ContractRow).where(
                    or_(
                        ContractRow.expiry < today.strftime("%Y%m%d"),
                        (ContractRow.con_id.is_(None)) & (ContractRow.checked_on < today),
                    )
                )
            )
        return int(result.rowcount or 0)


_CACHE: ContractCache | None = None
_CACHE_FAILED = False
_PRUNED_ON: date | None = None


def get_contract_cache() -> ContractCache | None:
    """The process-wide cache, or None when disabled or unusable (logged once). Prunes at most
    once per ET day per process."""
    global _CACHE, _CACHE_FAILED, _PRUNED_ON
    cfg = get_config()
    if not cfg.market_data.contract_cache_enabled or _CACHE_FAILED:
        return None
    if _CACHE is None:
        try:
            _CACHE = ContractCache(cfg.contract_cache_url_abs())
        except Exception:
            log.warning("contract cache unavailable — qualifying every contract at IBKR", exc_info=True)
            _CACHE_FAILED = True
            return None
    today = _et_today()
    if _PRUNED_ON != today:
        _PRUNED_ON = today
        try:
            pruned = _CACHE.prune()
            if pruned:
                log.info("contract cache: pruned %d expired entr%s", pruned, "y" if pruned == 1 else "ies")
        except Exception:
            log.warning("contract cache prune failed", exc_info=True)
    return _CACHE
```

Note on `test_unusable_cache_path_disables_the_cache`: `mkdir(parents=True)` under a regular file raises `NotADirectoryError`, which the factory catches.

- [x] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_contract_cache.py tests/test_spreads_fence.py -q`
Expected: all PASS. `test_spreads_fence.py` proves the spreads process can load the new module (it imports only stdlib/SQLAlchemy/ib_async/`src.common`).

- [x] **Step 7: Format, lint, type-check, commit**

```bash
ruff format src/ibkr/contract_cache.py tests/test_contract_cache.py
ruff check . && mypy src
python -m pytest -q
git add src/ibkr/contract_cache.py src/common/config.py config/examples/settings.yaml tests/conftest.py tests/test_contract_cache.py
git commit -m "feat(ibkr): shared on-disk option-contract lookup cache

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Then update this plan's Progress log row 1 (status, commit, gate result, date, any rulings) and commit that with the task.

---

### Task 2: Consult the cache in `qualify_options_async`

**Files:**
- Modify: `src/ibkr/contracts.py` (`qualify_options_async`, lines 64-111)
- Modify: `src/ibkr/market_data.py` (`get_option_chain_quotes_async`, right after `reqSecDefOptParamsAsync` ~line 1084: report the chain's trading classes)
- Create: `tests/test_qualify_cache.py`
- Docs: `ARCHITECTURE.md` (src/ibkr/ folder guide: new `contract_cache.py` row, plus a sentence on the `contracts.py` row), `STATUS.md`

**Interfaces:**
- Consumes (Task 1): `ContractCache`, `Lookup`, `contract_key`, `confirmed_missing`, `get_contract_cache`
- Produces: `qualify_options_async(ib, contracts, *, chunk_size=40, throttle_seconds=0.25, chunk_timeout_seconds=20.0, cache: ContractCache | None | _UseDefault = USE_DEFAULT) -> list[Option]`. It still returns the qualified contracts **in input order**, still fills each input contract in place (`src/spreads/chain.py` and `src/ibkr/portfolio.py` rely on in-place filling), and still drops the unqualified.

- [x] **Step 1: Write the failing tests**

Create `tests/test_qualify_cache.py`:

```python
"""qualify_options_async consults the contract cache before asking IBKR."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from ib_async import Option

from src.ibkr.contract_cache import ContractCache
from src.ibkr.contracts import qualify_options_async


def _cache(tmp_path) -> ContractCache:
    return ContractCache(f"sqlite:///{tmp_path / 'c.db'}", today=lambda: date(2026, 10, 12))


def _opt(strike: float, expiry: str = "20261023") -> Option:
    return Option("AMD", expiry, strike, "P", "SMART", tradingClass="AMD")


def _ib(missing: set[float] = frozenset(), *, raise_timeout: bool = False) -> MagicMock:
    """Fake IBKR: qualifies every strike except *missing* (returns None in its slot, as
    ib_async does for an unknown contract). conId = strike * 10."""

    async def _qualify(*cs):
        if raise_timeout:
            raise TimeoutError
        out = []
        for c in cs:
            if c.strike in missing:
                out.append(None)
            else:
                c.conId = int(c.strike * 10)
                out.append(c)
        return out

    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(side_effect=_qualify)
    return ib


async def test_second_call_hits_the_cache_and_keeps_input_order(tmp_path) -> None:
    cache = _cache(tmp_path)
    await qualify_options_async(_ib(), [_opt(600.0), _opt(605.0)], cache=cache, throttle_seconds=0)

    ib = _ib()
    again = [_opt(605.0), _opt(600.0)]
    result = await qualify_options_async(ib, again, cache=cache, throttle_seconds=0)

    ib.qualifyContractsAsync.assert_not_called()
    assert result == again and [c.conId for c in again] == [6050, 6000]


async def test_known_missing_strike_is_not_asked_again_today(tmp_path) -> None:
    cache = _cache(tmp_path)
    await qualify_options_async(
        _ib(missing={602.5}), [_opt(600.0), _opt(602.5)], cache=cache, throttle_seconds=0
    )

    ib = _ib()
    result = await qualify_options_async(ib, [_opt(600.0), _opt(602.5)], cache=cache, throttle_seconds=0)

    ib.qualifyContractsAsync.assert_not_called()
    assert [c.strike for c in result] == [600.0]


async def test_whole_expiry_missing_is_not_cached(tmp_path) -> None:
    """Every contract of an expiry coming back None is a transient failure, not a fact."""
    cache = _cache(tmp_path)
    await qualify_options_async(
        _ib(missing={600.0, 605.0}), [_opt(600.0), _opt(605.0)], cache=cache, throttle_seconds=0
    )

    ib = _ib()
    await qualify_options_async(ib, [_opt(600.0), _opt(605.0)], cache=cache, throttle_seconds=0)
    assert ib.qualifyContractsAsync.await_count == 1  # asked again, not remembered as missing


async def test_timed_out_chunk_records_nothing(tmp_path) -> None:
    cache = _cache(tmp_path)
    await qualify_options_async(_ib(raise_timeout=True), [_opt(600.0)], cache=cache, throttle_seconds=0)

    ib = _ib()
    result = await qualify_options_async(ib, [_opt(600.0)], cache=cache, throttle_seconds=0)
    assert ib.qualifyContractsAsync.await_count == 1 and len(result) == 1


async def test_cache_failure_falls_back_to_ibkr(tmp_path) -> None:
    broken = MagicMock(spec=ContractCache)
    broken.lookup.side_effect = RuntimeError("database is locked")
    broken.record.side_effect = RuntimeError("database is locked")
    broken.lock_path = tmp_path / "c.lock"

    result = await qualify_options_async(_ib(), [_opt(600.0)], cache=broken, throttle_seconds=0)
    assert [c.conId for c in result] == [6000]


async def test_short_result_list_records_no_missing(tmp_path) -> None:
    """A result list that doesn't line up with the chunk (a mock or a future ib_async that
    returns only the qualified) must never mislabel a real contract as missing."""
    cache = _cache(tmp_path)

    async def _only_qualified(*cs):
        cs[0].conId = 6000
        return [cs[0]]

    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(side_effect=_only_qualified)
    await qualify_options_async(ib, [_opt(600.0), _opt(605.0)], cache=cache, throttle_seconds=0)

    assert cache.lookup([_opt(605.0)]).misses != []


async def test_chain_fetch_reports_trading_classes_to_the_cache(monkeypatch, tmp_path) -> None:
    """get_option_chain_quotes_async hands every trading class from reqSecDefOptParams to the
    cache, so a corporate action (a new class) drops the symbol's stale entries that cycle."""
    from types import SimpleNamespace

    import src.ibkr.contract_cache as cc
    import src.ibkr.market_data as md

    seen: list[tuple[str, list[str]]] = []
    fake = SimpleNamespace(note_trading_classes=lambda sym, classes: seen.append((sym, sorted(classes))) or False)
    monkeypatch.setattr(cc, "get_contract_cache", lambda: fake)

    stock = SimpleNamespace(symbol="AMD", secType="STK", conId=1)
    monkeypatch.setattr(md, "qualify_stock_async", AsyncMock(return_value=stock))
    monkeypatch.setattr(md, "_resolve_spot_async", AsyncMock(return_value=600.0))
    monkeypatch.setattr(md, "_select_chain", lambda chains, sym: None)  # stop right after
    ib = MagicMock()
    ib.reqSecDefOptParamsAsync = AsyncMock(
        return_value=[SimpleNamespace(tradingClass="AMD"), SimpleNamespace(tradingClass="2AMD")]
    )

    assert await md.get_option_chain_quotes_async(ib, "AMD") == []
    assert seen == [("AMD", ["2AMD", "AMD"])]


async def test_default_cache_comes_from_the_process_factory(monkeypatch, tmp_path) -> None:
    import src.ibkr.contract_cache as cc

    cache = _cache(tmp_path)
    monkeypatch.setattr(cc, "get_contract_cache", lambda: cache)
    await qualify_options_async(_ib(), [_opt(600.0)], throttle_seconds=0)

    assert cache.lookup([_opt(600.0)]).hits != []
```

- [x] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_qualify_cache.py -q`
Expected: FAIL — `TypeError: qualify_options_async() got an unexpected keyword argument 'cache'`

- [x] **Step 3: Implement**

In `src/ibkr/contracts.py`, add imports:

```python
from typing import Any, Final, cast

import src.ibkr.contract_cache as contract_cache
from src.ibkr.contract_cache import ContractCache, Key, confirmed_missing, contract_key
```

Replace `qualify_options_async` (keep its existing docstring, adding the cache paragraph):

```python
class _UseDefault:
    pass


USE_DEFAULT: Final = _UseDefault()


async def qualify_options_async(
    ib: IB,
    contracts: list[Option],
    *,
    chunk_size: int = 40,
    throttle_seconds: float = 0.25,
    chunk_timeout_seconds: float = 20.0,
    cache: ContractCache | None | _UseDefault = USE_DEFAULT,
) -> list[Option]:
    """...existing docstring...

    **Contract cache (2026-10-10).** Contracts already looked up (by any process, any time
    before expiry) are filled from ``data/contracts.db`` without asking IBKR; strikes IBKR
    said don't exist are skipped for the rest of the ET day. Only misses are sent, in the same
    chunked, paced, timeout-bounded way. Any cache error falls back to asking IBKR. Returns the
    qualified input contracts in input order, each filled in place.
    """
    if not contracts:
        return []
    if chunk_size <= 0:
        chunk_size = len(contracts)
    store = contract_cache.get_contract_cache() if isinstance(cache, _UseDefault) else cache

    to_ask: list[Option] = list(contracts)
    hits: list[Option] = []
    known_missing = 0
    if store is not None:
        try:
            found = store.lookup(contracts)
            hits, to_ask, known_missing = found.hits, found.misses, found.known_missing
        except Exception:
            log.warning("contract cache lookup failed — asking IBKR for all", exc_info=True)

    asked_keys: dict[int, Key] = {id(c): contract_key(c) for c in to_ask} if store is not None else {}
    fresh: list[Option] = []
    missing: list[Option] = []
    for i in range(0, len(to_ask), chunk_size):
        chunk = to_ask[i : i + chunk_size]
        try:
            result = await asyncio.wait_for(
                ib.qualifyContractsAsync(*chunk), timeout=chunk_timeout_seconds
            )
        except TimeoutError:
            log.warning(
                "qualify_options_async: chunk %d-%d timed out after %.0fs — skipping chunk",
                i, i + len(chunk), chunk_timeout_seconds,
            )
            continue
        items = result if isinstance(result, list) else [result]
        for item in items:
            if item is not None and getattr(item, "conId", None):
                fresh.append(cast(Option, item))
        if len(items) == len(chunk):  # aligned slots: a None slot is IBKR's "no such contract"
            missing.extend(c for c, item in zip(chunk, items, strict=True) if item is None)
        if throttle_seconds > 0 and i + chunk_size < len(to_ask):
            await asyncio.sleep(throttle_seconds)

    if store is not None and (fresh or missing):
        good = [contract_key(c) for c in hits] + [asked_keys[id(c)] for c in fresh if id(c) in asked_keys]
        keep = set(confirmed_missing([asked_keys[id(c)] for c in missing], good))
        entries: list[tuple[Key, Any | None]] = [
            (asked_keys[id(c)], c) for c in fresh if id(c) in asked_keys
        ] + [(k, None) for k in keep]
        try:
            store.record(entries)
        except Exception:
            log.warning("contract cache write failed — answers not remembered", exc_info=True)
    if store is not None:
        log.info(
            "qualify: %d cached, %d known-missing skipped, %d asked IBKR (%d qualified, %d missing)",
            len(hits), known_missing, len(to_ask), len(fresh), len(missing),
        )

    good_ids = {id(c) for c in hits} | {id(c) for c in fresh}
    return [c for c in contracts if id(c) in good_ids]
```

In `src/ibkr/market_data.py::get_option_chain_quotes_async`, directly after
`chains = await ib.reqSecDefOptParamsAsync(...)` and before `_select_chain`:

```python
    store = contract_cache.get_contract_cache()
    if store is not None:
        try:
            store.note_trading_classes(symbol, (getattr(c, "tradingClass", "") for c in chains))
        except Exception:
            log.warning("contract cache: trading-class check failed for %s", symbol, exc_info=True)
```

(add `import src.ibkr.contract_cache as contract_cache` to that module's imports). The spreads chain doesn't need this: its contracts are same-day or next-day expiries, so a cached entry can't outlive a corporate action by more than a day.

Why `id(c) in asked_keys` on `fresh`: ib_async fills and returns the *input* object, so `id()` matches. A mock returning different objects simply records nothing (safe).

- [x] **Step 4: Run the new and the existing qualification tests**

Run: `python -m pytest tests/test_qualify_cache.py tests/test_market_data.py tests/test_monitor.py tests/test_spreads_chain.py tests/test_ibkr_portfolio.py -q`
Expected: all PASS. The existing tests run with the default cache disabled (conftest), so their behaviour is unchanged.

- [x] **Step 5: Docs**

`ARCHITECTURE.md`, `src/ibkr/` folder guide: add a row

```markdown
| `contract_cache.py` | **Shared option-contract lookup cache** (2026-10-10). Owns `data/contracts.db` (its own `ContractCacheBase`; nothing else writes it). `qualify_options_async` fills contracts from it and asks IBKR only for misses: a conId is remembered until expiry, a strike IBKR says doesn't exist until the next ET date — only when a sibling in the same expiry qualified, never from a timed-out chunk. Prices are never cached. Neutral reference data: imports only stdlib/SQLAlchemy/ib_async/`src.common`, so the wheel and the spreads process both use it. Any cache error falls back to asking IBKR. Also provides the cross-process lookup lock (`contract_details_slot`, Task 3). |
```

…and on the `contracts.py` row append: "`qualify_options_async` consults `contract_cache.py` first (2026-10-10)." In `STATUS.md`, change the "Open: contract qualification is slow…" bullet's opening to "**Mitigated 2026-10-10 (contract cache, Tasks 1-2 of docs/superpowers/plans/2026-10-10-contract-cache.md)…**", leaving the measurements in place.

- [x] **Step 6: Gate and commit**

```bash
ruff format src/ibkr/contracts.py tests/test_qualify_cache.py && ruff check . && mypy src && python -m pytest -q
git add src/ibkr/contracts.py tests/test_qualify_cache.py ARCHITECTURE.md STATUS.md
git commit -m "feat(ibkr): qualify_options_async asks IBKR only for contracts it hasn't seen

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Update Progress log row 2, commit with the task.

---

### Task 3: Cross-process lookup lock

**Files:**
- Modify: `src/ibkr/contract_cache.py` (add `contract_details_slot`)
- Modify: `src/ibkr/contracts.py` (hold the slot per chunk; timeout starts after acquiring)
- Modify: `src/common/config.py`, `config/examples/settings.yaml`, `config/settings.yaml` (`qualify_lock_wait_seconds`)
- Create: `tests/test_contract_lock.py`
- Docs: `ARCHITECTURE.md` (the `contract_cache.py` row already names the lock; add its behaviour), `How the scan works.md` (one paragraph under the chain-fetch budget section)

**Interfaces:**
- Consumes: `ContractCache.lock_path` (Task 1), `qualify_options_async` (Task 2)
- Produces: `contract_details_slot(lock_path: Path | None, wait_seconds: float) -> AsyncContextManager[bool]`, which yields whether the lock was acquired (False = waited out, proceeding unlocked)

- [x] **Step 1: Config key**

`MarketDataCfg`, after `contract_cache_db_url`:

```python
    # Every process qualifies contracts one chunk at a time through one shared file lock, so the
    # spreads GEX build and the wheel scan interleave chunks instead of timing each other out.
    # A chunk's qualify_timeout_seconds starts AFTER the lock is acquired. Waiting longer than
    # this proceeds unlocked (logged) — the lock can slow a scan, never stop it.
    qualify_lock_wait_seconds: float = 30.0
```

Same key, with a one-line comment, in both settings YAMLs.

- [x] **Step 2: Write the failing tests**

Create `tests/test_contract_lock.py`:

```python
"""contract_details_slot — one process at a time talks to IBKR's contract-details service."""

from __future__ import annotations

import asyncio
import time
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from ib_async import Option

from src.ibkr.contract_cache import ContractCache, contract_details_slot
from src.ibkr.contracts import qualify_options_async


async def test_second_holder_waits_for_the_first(tmp_path) -> None:
    lock = tmp_path / "c.lock"
    order: list[str] = []

    async def first() -> None:
        async with contract_details_slot(lock, 5.0):
            order.append("first in")
            await asyncio.sleep(0.2)
            order.append("first out")

    async def second() -> None:
        await asyncio.sleep(0.05)
        async with contract_details_slot(lock, 5.0) as got:
            assert got is True
            order.append("second in")

    await asyncio.gather(first(), second())
    assert order == ["first in", "first out", "second in"]


async def test_waiting_too_long_proceeds_unlocked(tmp_path) -> None:
    lock = tmp_path / "c.lock"
    async with contract_details_slot(lock, 5.0):
        started = time.monotonic()
        async with contract_details_slot(lock, 0.2) as got:
            assert got is False
        assert time.monotonic() - started < 1.0


async def test_no_lock_path_means_no_lock() -> None:
    async with contract_details_slot(None, 0.0) as got:
        assert got is False


async def test_chunk_timeout_starts_after_the_lock_is_acquired(tmp_path) -> None:
    """Another process holding the lock for longer than chunk_timeout_seconds must not make
    this process's chunk time out — the wait isn't the chunk's fault."""
    cache = ContractCache(f"sqlite:///{tmp_path / 'c.db'}", today=lambda: date(2026, 10, 12))

    async def _qualify(*cs):
        for c in cs:
            c.conId = 1
        return list(cs)

    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(side_effect=_qualify)

    async def holder() -> None:
        async with contract_details_slot(cache.lock_path, 5.0):
            await asyncio.sleep(0.4)

    async def asker() -> list:
        await asyncio.sleep(0.05)
        return await qualify_options_async(
            ib,
            [Option("AMD", "20261023", 600.0, "P", "SMART", tradingClass="AMD")],
            cache=cache,
            throttle_seconds=0,
            chunk_timeout_seconds=0.2,
        )

    _, result = await asyncio.gather(holder(), asker())
    assert len(result) == 1
```

- [x] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_contract_lock.py -q`
Expected: FAIL — `ImportError: cannot import name 'contract_details_slot'`

- [x] **Step 4: Implement the slot** (append to `src/ibkr/contract_cache.py`; add `import asyncio, contextlib, fcntl` and `from collections.abc import AsyncIterator`)

```python
@contextlib.asynccontextmanager
async def contract_details_slot(lock_path: Path | None, wait_seconds: float) -> AsyncIterator[bool]:
    """Hold the cross-process contract-lookup lock for one chunk. Yields True when held, False
    when there is no lock (cache disabled) or the wait ran out — the caller proceeds either way.
    flock locks belong to the open file, so two opens in one process exclude each other too."""
    if lock_path is None:
        yield False
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+")  # noqa: SIM115 — closed in finally
    held = False
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except BlockingIOError:
                if loop.time() >= deadline:
                    log.warning(
                        "contract lookup lock busy for %.0fs — qualifying without it", wait_seconds
                    )
                    break
                await asyncio.sleep(0.05)
        yield held
    finally:
        if held:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
```

- [x] **Step 5: Hold it per chunk in `qualify_options_async`**

In the chunk loop of `src/ibkr/contracts.py`, wrap only the IBKR call:

```python
        lock_path = store.lock_path if store is not None else None
        wait = get_config().market_data.qualify_lock_wait_seconds
        try:
            async with contract_cache.contract_details_slot(lock_path, wait):
                result = await asyncio.wait_for(
                    ib.qualifyContractsAsync(*chunk), timeout=chunk_timeout_seconds
                )
        except TimeoutError:
            ...unchanged...
```

(add `from src.common.config import get_config` to the imports). The `wait_for` sits inside the `async with`, so the timeout clock starts after acquisition. The throttle sleep stays outside the lock, which lets the other process take a turn between chunks.

- [x] **Step 6: Run the lock tests and the full qualification suite**

Run: `python -m pytest tests/test_contract_lock.py tests/test_qualify_cache.py tests/test_market_data.py tests/test_spreads_chain.py -q`
Expected: all PASS.

- [x] **Step 7: Docs, gate, commit**

`How the scan works.md`, in the chain-fetch budget section, add:

```markdown
**Contract lookups are cached and take turns (2026-10-10).** Before quoting, each option must be
"qualified" (its IBKR conId looked up). That answer never changes before expiry, so it is
remembered in `data/contracts.db` and a cycle asks IBKR only for contracts it hasn't seen today.
The few remaining lookups go through a lock shared with the spreads service, one chunk at a time,
so the GEX map build and the scan interleave instead of timing each other out.
```

```bash
ruff format src/ibkr/contract_cache.py src/ibkr/contracts.py tests/test_contract_lock.py && ruff check . && mypy src && python -m pytest -q
git add src/ibkr/contract_cache.py src/ibkr/contracts.py src/common/config.py config/examples/settings.yaml tests/test_contract_lock.py ARCHITECTURE.md "How the scan works.md"
git commit -m "feat(ibkr): one process at a time qualifies contracts; chunk timeout starts after the lock

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Update Progress log row 3, commit with the task.

---

### Task 4: Full sweep once per ET trading day; persisted retry queue

**Files:**
- Modify: `src/notify/approval_service.py`: the intraday loop (~line 1535), the manual `/scan` handler (~line 524), `_run_intraday_scan` (~lines 1321 and 1338)
- Modify: `tests/test_notify.py`: rewrite `test_intraday_loop_forces_full_sweep_only_on_first_spawned_cycle` (~line 2282)
- Create: `tests/test_daily_full_sweep.py`
- Docs: `How the scan works.md` (the "Two overrides" list ~line 365, the scenario table ~line 566, the triggers table ~line 716), `STATUS.md`

**Interfaces:**
- Consumes: `src.storage.system_settings.get_setting` / `set_setting`
- Produces (module-level in `approval_service.py`): `_FULL_SWEEP_DATE_KEY = "intraday_full_sweep_et_date"`, `_RETRY_QUEUE_KEY = "intraday_pending_retry_symbols"`, `_et_today() -> date`, `_full_sweep_due() -> bool`, `_mark_full_sweep_done() -> None`, `_load_retry_queue(bot_data) -> set[str]`, `_save_retry_queue(bot_data, symbols) -> None`

- [x] **Step 1: Write the failing tests**

Create `tests/test_daily_full_sweep.py`:

```python
"""The forced full sweep runs once per ET trading day, not once per process start, and the
retry queue survives a restart (docs/superpowers/plans/2026-10-10-contract-cache.md, Task 4)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch


def test_full_sweep_due_once_per_et_day(db, monkeypatch) -> None:
    import src.notify.approval_service as svc

    monkeypatch.setattr(svc, "_et_today", lambda: date(2026, 10, 12))
    assert svc._full_sweep_due() is True
    svc._mark_full_sweep_done()
    assert svc._full_sweep_due() is False  # same day, even from a fresh process

    monkeypatch.setattr(svc, "_et_today", lambda: date(2026, 10, 13))
    assert svc._full_sweep_due() is True


async def test_retry_queue_survives_a_restart(db) -> None:
    from src.notify.approval_service import _run_intraday_scan
    from src.orchestrator.scan import ScanResult

    ib_scan = MagicMock()
    ib_scan.isConnected.return_value = True
    cut_short = ScanResult(aborted_unhealthy=True, unreached_symbols=["NVDA", "PLTR"])
    with (
        patch("src.orchestrator.scan.run_scan", AsyncMock(return_value=cut_short)),
        patch("src.notify.approval_service._update_pending_order_notifications", AsyncMock()),
        patch("src.notify.approval_service._notify_scan_blocked", AsyncMock()),
        patch("src.notify.approval_service._force_scan_reconnect", AsyncMock()),
    ):
        await _run_intraday_scan(ib_scan, AsyncMock(), "123", {})

    restarted_bot_data: dict = {}  # a new process: empty bot_data
    run_scan = AsyncMock(return_value=ScanResult())
    with (
        patch("src.orchestrator.scan.run_scan", run_scan),
        patch("src.notify.approval_service._update_pending_order_notifications", AsyncMock()),
    ):
        await _run_intraday_scan(ib_scan, AsyncMock(), "123", restarted_bot_data)

    assert run_scan.call_args.kwargs["must_include_symbols"] == {"NVDA", "PLTR"}
```

In `tests/test_notify.py`, rewrite `test_intraday_loop_forces_full_sweep_only_on_first_spawned_cycle` to take the `db` fixture and pin today's date, then assert across a simulated restart:

```python
async def test_intraday_loop_forces_full_sweep_once_per_et_day(db, monkeypatch):
    """2026-10-10: the full sweep is once per ET trading day (persisted), not once per process
    start — scan_state is persisted, so a mid-session restart resumes the normal gate."""
    # ...same setup as the old test, plus:
    monkeypatch.setattr(approval_service, "_et_today", lambda: date(2026, 10, 12))
    # run the loop for two cycles exactly as before, then:
    assert force_flags[:2] == [True, False]
    # a restart (fresh bot_data, same day) does not force it again:
    app2 = SimpleNamespace(bot=bot, bot_data={})
    # ...run app2's loop for one cycle with the same _capture_run_scan...
    assert force_flags[2] is False
```

Keep the old test's patch list and loop-driving code verbatim; only the fixture, the date pin, the assertions and the second app change. Delete the old `assert app.bot_data.get("startup_full_sweep_done") is True`.

- [x] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_daily_full_sweep.py "tests/test_notify.py::test_intraday_loop_forces_full_sweep_once_per_et_day" -q`
Expected: FAIL — `AttributeError: module 'src.notify.approval_service' has no attribute '_et_today'`

- [x] **Step 3: Implement**

Module level in `src/notify/approval_service.py`, beside `_BUY_LIST_SENT_DATE_KEY`:

```python
# The forced full sweep runs once per ET trading day (2026-10-10), not once per process start:
# scan_state is persisted, so after a mid-session restart the normal materiality gate (plus its
# force_full_scan_minutes staleness timer) is correct. The retry queue is persisted for the same
# reason — the forced sweep used to cover for losing it on restart.
_FULL_SWEEP_DATE_KEY = "intraday_full_sweep_et_date"
_RETRY_QUEUE_KEY = "intraday_pending_retry_symbols"


def _et_today() -> date:
    return datetime.now(_ET).date()


def _full_sweep_due() -> bool:
    return get_setting(_FULL_SWEEP_DATE_KEY) != _et_today().isoformat()


def _mark_full_sweep_done() -> None:
    set_setting(_FULL_SWEEP_DATE_KEY, _et_today().isoformat())


def _load_retry_queue(bot_data: dict) -> set[str]:
    if "pending_retry_symbols" not in bot_data:
        try:
            bot_data["pending_retry_symbols"] = set(json.loads(get_setting(_RETRY_QUEUE_KEY, "[]")))
        except (ValueError, TypeError):
            bot_data["pending_retry_symbols"] = set()
    return set(bot_data["pending_retry_symbols"])


def _save_retry_queue(bot_data: dict, symbols: set[str]) -> None:
    bot_data["pending_retry_symbols"] = set(symbols)
    set_setting(_RETRY_QUEUE_KEY, json.dumps(sorted(symbols)))
```

(Ensure `json`, `date`, `datetime`, `get_setting` and `set_setting` are imported; most already are. Check the top of the file.)

Then:
- Intraday loop (~1535): replace the two `startup_full_sweep_done` lines with `force_full_sweep = _full_sweep_due()` and `_mark_full_sweep_done()`. Rewrite the comment block above them to say "first cycle of the ET trading day (persisted)" and why (the 2026-10-10 rationale above).
- Manual `/scan` (~524): replace `context.bot_data["startup_full_sweep_done"] = True` with `_mark_full_sweep_done()`, and update its comment.
- `_run_intraday_scan`: `pending_retry = _load_retry_queue(bot_data)` (~1321), and `_save_retry_queue(bot_data, set(result.unreached_symbols))` (~1338).

- [x] **Step 4: Run them and the existing retry-queue tests**

Run: `python -m pytest tests/test_daily_full_sweep.py tests/test_notify.py -q`
Expected: all PASS. The four existing `pending_retry_symbols` tests (~lines 2065-2140) pre-seed `bot_data`, so `_load_retry_queue` uses that; their `set_setting` calls fail softly when no DB is configured (`set_setting` logs and returns). If any of them now writes the real `data/income_system.db`, add the `db` fixture to it. **Check:** run `ls -la data/income_system.db` before and after the test run; the mtime must not change.

- [x] **Step 5: Docs, gate, commit**

`How the scan works.md`:
- "Two overrides" list: replace the "First eligible cycle after the process starts (`startup_full_sweep_done`)" bullet with "**First eligible cycle of the ET trading day** (persisted in `system_settings` as `intraday_full_sweep_et_date`, 2026-10-10). A restart later the same day resumes the normal gate: `scan_state` is persisted and `force_full_scan_minutes` still re-fetches anything older than 120 min. A manual `/scan` also marks the day swept."
- The retry-queue paragraph: replace "A restart clears the queue in effect (…)" with "The queue is persisted in `system_settings` (`intraday_pending_retry_symbols`), so a restart doesn't drop it."
- Scenario table (~566) and triggers table (~716): "Daemon restart" → "The next cycle uses the normal gate; the forced full sweep is once per ET day."

`STATUS.md`: in the 2026-10-09 log-review section, add a bullet recording the change and the reason.

```bash
ruff format src/notify/approval_service.py tests/test_daily_full_sweep.py tests/test_notify.py && ruff check . && mypy src && python -m pytest -q
git add src/notify/approval_service.py tests/test_daily_full_sweep.py tests/test_notify.py "How the scan works.md" STATUS.md
git commit -m "feat(scan): full sweep once per ET trading day, not per restart; persist the retry queue

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Update Progress log row 4, commit with the task.

---

### Task 5: Live verification and close-out

No new code. This confirms the fix on the real Gateway and records the numbers that decide the optional 09:45 follow-up.

- [ ] **Step 1: Merge and restart outside RTH**

`git checkout main && git merge --no-ff feat/contract-cache`, then `./ibkr restart`. The first scans after the restart populate `data/contracts.db`.

- [ ] **Step 2: Measure two consecutive RTH cycles**

```bash
grep -E "qualify: [0-9]+ cached" logs/system.log | tail -40
grep -E "scan complete|chain-fetch budget|exceeded symbol_timeout|qualify_options_async: chunk .* timed out" logs/system.log | tail -20
sqlite3 -readonly data/contracts.db "select count(*), sum(con_id is null) from option_contracts"
```

Expected:
- First cycle: mostly "asked IBKR".
- Second cycle: mostly "cached", with "asked IBKR" in the low tens at most.
- No chunk timeouts in the second cycle.
- The second cycle reaches every material symbol inside the 350 s budget (no "chain-fetch budget exhausted").

- [ ] **Step 3: Restart test**

`./ibkr restart` mid-session. The next cycle's log must show:
- **no** "(forced full sweep — first cycle since process start)";
- `qualify:` lines that are almost all "cached".

- [ ] **Step 4: Spreads overlap**

At the next hourly GEX build (`grep "GEX map" logs/spreads.log | tail -3`), check that neither the spreads log nor `system.log` shows `qualify_options_async: chunk … timed out` during it. If timeouts remain **and** the 09:30 scan/09:31 map overlap is the cause, record that in `STATUS.md` as the trigger for the 09:45 first-cycle follow-up. Don't implement it here.

- [ ] **Step 5: Close out**

Fill in the Progress log row 5 with the measured numbers. In `STATUS.md`, change the "Open: contract qualification…" bullet to "Fixed" with the before/after numbers. Commit.

---

## Self-review (done while writing)

- **Coverage:** Cache with persistence across restarts (T1). Expiry cleanup (T1 `prune`). Corporate-action invalidation (T1 `note_trading_classes`, T2 call site). Lookups skipped for hits and known-missing (T2). Transient failures not cached (T2 tests). Spreads benefits automatically: `src/spreads/chain.py` already calls `qualify_options_async` (T2). GEX-vs-scan contention via the lock, chosen over an ordering that would break the spreads fence (T3). Restart redundancy (T4). Numbers checked live (T5).
- **Order paths untouched:** `executor.py`, `position_manager.py`, `roll_executor.py`, `profit_take.py` and `approval_service.py:1607` call `ib.qualifyContractsAsync` directly and are deliberately not routed through the cache.
- **Type consistency:** `Key`, `contract_key`, `confirmed_missing`, `Lookup`, `ContractCache.lookup/record/prune/lock_path`, `get_contract_cache`, `contract_details_slot` and `USE_DEFAULT` are used with the same names and signatures in every task.
