# Milestone 1 — Portfolio spine

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [x]`) syntax.

**Goal:** The account's positions and values are recorded more than once a day, by processes that
already hold an IB connection, into a table the API can read — and when nothing has been recorded,
every reader can tell.

**Spec:** `Web plan/P3-P4-design.md` §4 in full. **Index:** `Web plan/P3-P4-IMPLEMENTATION-PLAN.md`.
**Depends on:** P2, shipped, and **Milestone 0** — in particular Task 0.2, which made the EOD run
idempotent. This milestone's `eod` fallback rung reads `position_snapshots` and
`journal.payload`, and before 0.2 a repeated EOD run left both unwritten.

> **CLAIMED — all six tasks (1.1–1.6), by opencode (glm-5.3), 2026-09-09.** The `[SONNET]` /
> `[GLM]` tags were treated as capacity hints, not gates; the claim is grounded instead in a
> dependency audit run against the tree before taking anything. Confirmed to exist, exactly as
> each task describes them: `AccountSnapshot`/`PositionSnapshot` (`src/common/schemas.py:89,105`)
> and no `PortfolioSnapshot` symbol anywhere yet; `PositionSnapshotRow` (`src/storage/models.py:244`)
> and `_utcnow` (`:27`); `save_position_snapshot`'s swallow-and-log discipline to mirror
> (`src/storage/positions.py:22`); config models `MarketDataCfg`/`StorageCfg`
> (`src/common/config.py:99,362` — the sketch below names them `MarketData`/`Storage`; the real
> names win, per the task's own "match their field style" instruction); the existing EOD prune
> site to sit beside (`src/orchestrator/eod_report.py:425`, `purge_old_risk_verdicts()`);
> `_refresh_subscriptions` with its single `get_positions` call (`src/monitor/intraday.py:313,317`);
> `register`/`CommandFailed` (`src/notify/command_drain.py:79,54`); `RefreshPayload` and the
> no-dedupe listing (`src/api/models/commands.py:90,134`); `as_utc_opt`
> (`src/api/models/common.py:36`); `is_rth` (`src/common/market_hours.py:192`);
> `get_positions`/`get_account_snapshot_async` (`src/ibkr/portfolio.py:91,150`); the journal's
> `eod_summary` payload the fallback rung reads (`eod_report.py:276`); and fixture precedent for
> `db`/`session` (`tests/test_eod_idempotency.py:56,75`), `drain_env` (`test_drain_promote.py:189`,
> `test_drain_universe.py:250`), and monitor wrapping (`test_monitor.py:855–958`). Step checkboxes
> below remain unchecked — they close as each task is actually executed and its gate run green.
>
> **EXECUTED — all six tasks completed 2026-09-09, same session, six commits** (`82ac98f` storage,
> `c499059` config, `0d3e702` monitor, `8091cbb` drain, `b645e49` fallback chain, `ca1615e` docs
> sweep). Every task followed its step order: failing test confirmed failing for the right reason
> (`ModuleNotFoundError` / missing attribute, never an assertion), then implementation, then the
> FULL suite, then docs, then commit. Final gate, run at HEAD: `python -m pytest -q`
> (**1996 passed**, up from 1974 pre-milestone — 22 new tests across five new test files),
> `ruff check .` clean, `mypy src` clean (156 files). Deviations from the sketches, all
> within each task's own instructions: config keys landed on the real `MarketDataCfg`/
> `StorageCfg` names; the EOD prune test drives the real `eod_report.run()` through the
> `test_eod_idempotency.py::eod_env` pattern rather than a step-8 stub; `PortfolioSnapshot.account`
> is optional (`AccountSnapshot | None`) because the task's own required behaviour makes the
> account optional on the `eod` rung — writers always supply it. Acceptance boxes ticked only
> after verification: `position_snapshots` confirmed byte-untouched by `git diff 6f15e36..HEAD --
> src/storage/models.py` (zero touching lines); the escaping-write test makes
> `save_portfolio_snapshot` raise through the real `_refresh_subscriptions`; `commands.md`'s
> `refresh` section rewritten to the handler that now exists and greps clean for the old
> "Triggers a full scan" text.

**Nothing in this milestone is user-visible.** No route, no component, no nav change. It exists so
that M2 and M3 render real numbers on their first day.

**The shape of this milestone in one sentence:** the API cannot ask IBKR anything, so somebody
else has to write down what IBKR said — and the two processes that can already do that must not be
made any less reliable at their real jobs by being asked to.

---

## Task 1.1 — `PortfolioSnapshotRow` and its storage helpers `[SONNET]`

**Trading-system storage code.** A new table in the trading database.

**Context.** `src/storage/positions.py` already persists a daily position snapshot into
`position_snapshots`, and `src/claude/eval/assignment.py::detect_assignments` diffs the most recent
*prior-day* row from that table to distinguish an assignment from an expiry. Spec §4.4 explains why
this milestone must not reuse it. **Do not add columns to `PositionSnapshotRow`, do not relax its
`UniqueConstraint("snapshot_date")`, and do not write to it from anywhere new.**

**Files:** Modify `src/storage/models.py`, `ARCHITECTURE.md`, `README.md`. Create
`src/storage/portfolio_snapshots.py`. Test `tests/test_portfolio_snapshots.py`.

**Interfaces:**

```python
# src/storage/models.py
class PortfolioSnapshotRow(Base):
    """A point-in-time capture of positions and account values, for the web portfolio.

    Deliberately separate from PositionSnapshotRow: that table is one row per ET trading day
    and assignment auto-detection depends on that contract (see src/claude/eval/assignment.py).
    This one is append-only and captured on an intraday cadence. Pruned by retention, not by
    a unique constraint.
    """

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True, default=_utcnow)
    source: Mapped[str] = mapped_column(String(8))  # "monitor" | "refresh" | "eod"
    account: Mapped[dict] = mapped_column(JSON)      # AccountSnapshot.model_dump(mode="json")
    positions: Mapped[list] = mapped_column(JSON)    # list[PositionSnapshot.model_dump(...)]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# src/storage/portfolio_snapshots.py
def save_portfolio_snapshot(
    *,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    source: str,
    captured_at: datetime | None = None,
) -> int | None:
    """Append one snapshot. Returns the new row id, or None on any failure.

    NEVER RAISES. Callers include a live event loop whose real job is firing roll alerts;
    a failed snapshot write must not interrupt it. Mirrors save_position_snapshot's
    swallow-and-log discipline.
    """


def load_latest_portfolio_snapshot() -> PortfolioSnapshot | None:
    """The newest snapshot, or None when the table is empty. Never raises."""


def latest_capture_time() -> datetime | None:
    """captured_at of the newest row without deserialising its payload. Never raises."""


def prune_portfolio_snapshots(days: int) -> int:
    """Delete rows older than `days`. Returns how many were deleted. Never raises."""
```

```python
# src/common/schemas.py — the read-side type, so nothing passes raw ORM rows across a boundary
class PortfolioSnapshot(BaseModel):
    captured_at: datetime
    source: Literal["monitor", "refresh", "eod"]
    account: AccountSnapshot
    positions: list[PositionSnapshot]
```

Required behaviours, each with a test:
- A saved snapshot round-trips: same account values, same position count, same `source`.
- `captured_at` defaults to now when not supplied, and is stored as given when it is.
- **Two snapshots may share a timestamp.** There is no unique constraint; the newest `id` wins a
  tie. Its own test, because a future "helpful" unique index would break the refresh button.
- `load_latest_portfolio_snapshot()` returns `None` on an empty table, not an exception and not an
  empty snapshot.
- **A save that raises inside the session returns `None` and logs.** Asserted by patching
  `session_scope` to raise.
- `prune_portfolio_snapshots(30)` deletes a 31-day-old row and keeps a 29-day-old one.
- **`position_snapshots` is untouched by every one of the above.** Asserted by counting rows in
  that table before and after.

- [x] **Step 1: Write the failing test**

```python
"""The portfolio spine's storage. Separate table, append-only, never raises."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.common.schemas import AccountSnapshot, PositionSnapshot
from src.storage.models import PositionSnapshotRow
from src.storage.portfolio_snapshots import (
    latest_capture_time,
    load_latest_portfolio_snapshot,
    prune_portfolio_snapshots,
    save_portfolio_snapshot,
)


def _account(net_liq: float = 100_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123", net_liquidation=net_liq, total_cash=50_000.0,
        buying_power=200_000.0, maintenance_margin=10_000.0, excess_liquidity=90_000.0,
    )


def _positions() -> list[PositionSnapshot]:
    return [PositionSnapshot(symbol="NVDA", sec_type="STK", position=100.0, avg_cost=170.0)]


def test_a_snapshot_round_trips(db) -> None:
    save_portfolio_snapshot(account=_account(), positions=_positions(), source="monitor")
    snap = load_latest_portfolio_snapshot()
    assert snap is not None
    assert snap.source == "monitor"
    assert snap.account.net_liquidation == 100_000.0
    assert len(snap.positions) == 1
    assert snap.positions[0].symbol == "NVDA"


def test_two_snapshots_may_share_a_timestamp(db) -> None:
    """No unique constraint. A refresh moments after a monitor write must not fail."""
    when = datetime.now(UTC)
    first = save_portfolio_snapshot(
        account=_account(1.0), positions=[], source="monitor", captured_at=when
    )
    second = save_portfolio_snapshot(
        account=_account(2.0), positions=[], source="refresh", captured_at=when
    )
    assert first is not None and second is not None
    snap = load_latest_portfolio_snapshot()
    assert snap is not None and snap.account.net_liquidation == 2.0


def test_an_empty_table_returns_none_not_an_empty_snapshot(db) -> None:
    assert load_latest_portfolio_snapshot() is None
    assert latest_capture_time() is None


def test_a_failing_save_returns_none_and_does_not_raise(db, monkeypatch) -> None:
    """A live event loop calls this. It may never propagate."""
    def boom(*_a, **_k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("src.storage.portfolio_snapshots.session_scope", boom)
    assert save_portfolio_snapshot(
        account=_account(), positions=_positions(), source="monitor"
    ) is None


def test_prune_deletes_only_rows_past_retention(db) -> None:
    now = datetime.now(UTC)
    save_portfolio_snapshot(
        account=_account(), positions=[], source="monitor",
        captured_at=now - timedelta(days=31),
    )
    save_portfolio_snapshot(
        account=_account(), positions=[], source="monitor",
        captured_at=now - timedelta(days=29),
    )
    assert prune_portfolio_snapshots(30) == 1
    assert latest_capture_time() is not None


def test_position_snapshots_is_never_touched(db, session) -> None:
    """Assignment auto-detection depends on that table. This milestone does not write it."""
    before = session.query(PositionSnapshotRow).count()
    save_portfolio_snapshot(account=_account(), positions=_positions(), source="monitor")
    assert session.query(PositionSnapshotRow).count() == before
```

- [x] **Step 2: Run the tests and confirm they fail** with `ImportError` / `ModuleNotFoundError`,
  not with an assertion error. A test that fails for the wrong reason proves nothing.

  Run: `python -m pytest tests/test_portfolio_snapshots.py -v`

- [x] **Step 3: Implement** `PortfolioSnapshot` in `src/common/schemas.py`,
  `PortfolioSnapshotRow` in `src/storage/models.py`, and `src/storage/portfolio_snapshots.py`.
  Every public function wraps its body in `try/except Exception` with `log.exception` and a safe
  return, mirroring `src/storage/positions.py`.

- [x] **Step 4: Run the full suite.** This adds a model to the trading database's `Base`; every
  pre-existing storage and orchestrator test must still pass.

  Run: `python -m pytest -q` · `ruff check .` · `mypy src`

- [x] **Step 5: Docs.** `ARCHITECTURE.md` `src/storage/` section and data-flow schemas gain
  `PortfolioSnapshotRow` and `src/storage/portfolio_snapshots.py`; `README.md`'s layout table gains
  the module. State in both that it is deliberately separate from `position_snapshots` and why.

- [x] **Step 6: Commit.**

```bash
git add src/storage/models.py src/storage/portfolio_snapshots.py src/common/schemas.py \
        tests/test_portfolio_snapshots.py ARCHITECTURE.md README.md
git commit -m "feat(storage): add portfolio_snapshots, the intraday portfolio capture table"
```

---

## Task 1.2 — Config keys and retention pruning `[GLM]`

**Files:** Modify `config/settings.yaml`, `src/common/config.py`,
`src/orchestrator/eod_report.py`, `ARCHITECTURE.md`, `SETUP.md`. Test
`tests/test_portfolio_snapshot_config.py`.

**Interfaces:**

```yaml
# config/settings.yaml
market_data:
  # Minimum minutes between automatic portfolio snapshots written by the intraday monitor.
  # A `refresh` command ignores this — an operator asking for a fetch gets one.
  portfolio_snapshot_interval_minutes: 15

storage:
  # Days of intraday portfolio history kept. Pruned by the EOD run. See P3-P4-design.md §4.2:
  # a year of intraday history needs a rollup, not a longer retention here.
  portfolio_snapshot_retention_days: 30
```

```python
# src/common/config.py — added to the existing MarketData and Storage config models
class MarketData(BaseModel):
    ...
    portfolio_snapshot_interval_minutes: int = 15


class Storage(BaseModel):
    ...
    portfolio_snapshot_retention_days: int = 30
```

Read the existing `MarketData` and `Storage` model definitions in `src/common/config.py` before
editing and match their field style exactly. If `Storage` does not exist as a config section, add
the key to whichever section already owns retention-shaped settings rather than inventing a new
top-level section for one key.

The prune call goes into the EOD run beside whatever pruning already happens there. Find the
existing prune site by grepping for `days=` in `src/storage/risk_verdicts.py` and following its
caller; put the new call next to it, not in a new function.

Required behaviours, each with a test:
- Both keys load with their documented defaults when absent from the YAML.
- Both keys are honoured when present.
- The EOD run calls `prune_portfolio_snapshots` with the configured value.

- [x] **Step 1: Write the failing test**

```python
"""Two config keys, both defaulted, both honoured, and the EOD run prunes."""

from __future__ import annotations

from unittest.mock import patch

from src.common.config import get_config


def test_defaults_when_absent(config_without_keys) -> None:
    cfg = get_config()
    assert cfg.market_data.portfolio_snapshot_interval_minutes == 15
    assert cfg.storage.portfolio_snapshot_retention_days == 30


def test_values_are_honoured(config_with={"portfolio_snapshot_interval_minutes": 5}) -> None:
    assert get_config().market_data.portfolio_snapshot_interval_minutes == 5


def test_the_eod_run_prunes_portfolio_snapshots() -> None:
    with patch("src.orchestrator.eod_report.prune_portfolio_snapshots") as prune:
        run_the_eod_prune_step()          # call whatever function owns the existing prune
    prune.assert_called_once()
    assert prune.call_args.args[0] == 30  # or kwargs["days"], matching the signature you wrote
```

Build `config_without_keys` and the config override the way `tests/` already overrides config —
grep the existing tests for `get_config.cache_clear` and copy that fixture pattern rather than
inventing a second one.

- [x] **Step 2: Run the tests and confirm they fail.**

- [x] **Step 3: Implement.** Add the keys, wire the prune call.

- [x] **Step 4: Run the gate.** `python -m pytest -q` · `ruff check .` · `mypy src`

- [x] **Step 5: Docs.** `ARCHITECTURE.md`'s config section gains both keys with their meaning;
  `SETUP.md` gains them wherever `market_data` and retention settings are already documented.

- [x] **Step 6: Commit.**

---

## Task 1.3 — The monitor snapshot writer `[SONNET]`

**Trading-system code, inside a live event loop.** This is the task where a mistake stops roll
alerts from firing.

**Context.** `src/monitor/intraday.py`'s `_refresh_loop` (around line 429) runs every
`scheduler.intraday_poll_seconds` and calls `_refresh_subscriptions()`, which already calls
`get_positions(self._ib)` to maintain tick subscriptions. The monitor's real job is
`_on_pending_tickers` → `check_all` → roll and assignment alerts. Writing a row for a web page is
strictly secondary to that and the code must say so.

**Files:** Modify `src/monitor/intraday.py`, `ARCHITECTURE.md`. Test
`tests/test_monitor_snapshot.py`.

**Interfaces:**

```python
# src/monitor/intraday.py — a method on the existing monitor class
async def _maybe_write_snapshot(self, positions: list[PositionSnapshot]) -> None:
    """Write a portfolio snapshot if the interval has elapsed and the market is open.

    Called from _refresh_subscriptions with the positions it already fetched, so this
    adds an account fetch and a DB write, never a second get_positions call.

    NEVER RAISES. Every failure path logs and returns.
    """
```

Consumes: `save_portfolio_snapshot` (Task 1.1), `latest_capture_time` (Task 1.1),
`cfg.market_data.portfolio_snapshot_interval_minutes` (Task 1.2),
`src.common.market_hours.is_rth`, `src.ibkr.portfolio.get_account_snapshot_async`.

**Design points that are not negotiable:**

1. **It reuses the positions `_refresh_subscriptions` already fetched.** A second
   `get_positions` call doubles the IB round-trips on every poll for no benefit.
2. **It never raises.** Wrap the whole body. A `RuntimeError` escaping into `_refresh_loop` kills
   the refresh task, and a dead refresh task means the monitor stops subscribing to new positions —
   which means roll alerts silently stop firing for anything opened after that moment. This is the
   single most dangerous failure in the milestone and it has its own test.
3. **The interval gate reads `latest_capture_time()` from the database**, not an in-memory
   timestamp. A monitor restart must not produce a burst of snapshots, and an in-memory clock
   resets on restart while the table does not.
4. **`is_rth()` gates it.** A monitor left running overnight writes nothing.
5. **A `refresh` command's row counts toward the interval.** Because the gate reads the table, this
   falls out for free — do not add a `source` filter to the gate.
6. **The account fetch is awaited with the same timeout discipline the surrounding code uses.** A
   hung `get_account_snapshot_async` must not stall the refresh loop.

Required behaviours, each with a test:
- A snapshot is written when the interval has elapsed and the market is open.
- **No snapshot is written when `is_rth()` is false.** Its own test.
- No snapshot is written when the last capture is inside the interval.
- **A raising `save_portfolio_snapshot` does not propagate**, and `_refresh_subscriptions`
  completes normally afterwards. Its own test, and the most important one here.
- **A raising account fetch does not propagate** and writes nothing.
- `get_positions` is called exactly once per refresh pass, not twice.

- [x] **Step 1: Write the failing test**

```python
"""The monitor may write snapshots. It may never let that interrupt its real job."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_a_snapshot_is_written_during_rth_after_the_interval(monitor_env) -> None:
    with patch("src.monitor.intraday.is_rth", return_value=True), \
         patch("src.monitor.intraday.latest_capture_time",
               return_value=datetime.now(UTC) - timedelta(minutes=20)), \
         patch("src.monitor.intraday.save_portfolio_snapshot") as save:
        await monitor_env.monitor._refresh_subscriptions()
    save.assert_called_once()


@pytest.mark.asyncio
async def test_nothing_is_written_outside_rth(monitor_env) -> None:
    with patch("src.monitor.intraday.is_rth", return_value=False), \
         patch("src.monitor.intraday.save_portfolio_snapshot") as save:
        await monitor_env.monitor._refresh_subscriptions()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_nothing_is_written_inside_the_interval(monitor_env) -> None:
    with patch("src.monitor.intraday.is_rth", return_value=True), \
         patch("src.monitor.intraday.latest_capture_time",
               return_value=datetime.now(UTC) - timedelta(minutes=2)), \
         patch("src.monitor.intraday.save_portfolio_snapshot") as save:
        await monitor_env.monitor._refresh_subscriptions()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_a_failing_snapshot_write_never_reaches_the_refresh_loop(monitor_env) -> None:
    """If this escapes, the refresh task dies and roll alerts stop for new positions."""
    with patch("src.monitor.intraday.is_rth", return_value=True), \
         patch("src.monitor.intraday.latest_capture_time", return_value=None), \
         patch("src.monitor.intraday.save_portfolio_snapshot",
               side_effect=RuntimeError("database is locked")):
        await monitor_env.monitor._refresh_subscriptions()   # must not raise

    assert monitor_env.monitor._subscriptions_were_refreshed()   # the real work still happened


@pytest.mark.asyncio
async def test_a_failing_account_fetch_writes_nothing_and_does_not_raise(monitor_env) -> None:
    with patch("src.monitor.intraday.is_rth", return_value=True), \
         patch("src.monitor.intraday.latest_capture_time", return_value=None), \
         patch("src.monitor.intraday.get_account_snapshot_async",
               new=AsyncMock(side_effect=TimeoutError())), \
         patch("src.monitor.intraday.save_portfolio_snapshot") as save:
        await monitor_env.monitor._refresh_subscriptions()
    save.assert_not_called()


@pytest.mark.asyncio
async def test_positions_are_fetched_once_per_pass(monitor_env) -> None:
    with patch("src.monitor.intraday.is_rth", return_value=True), \
         patch("src.monitor.intraday.latest_capture_time", return_value=None), \
         patch("src.monitor.intraday.get_positions", return_value=[]) as get_pos, \
         patch("src.monitor.intraday.save_portfolio_snapshot"):
        await monitor_env.monitor._refresh_subscriptions()
    assert get_pos.call_count == 1
```

Build `monitor_env` as a fixture wrapping the existing monitor class with a fake `IB`. Follow
whatever the existing `tests/` already do for the monitor — grep for `intraday` in `tests/` and
extend that fixture rather than building a second one. `_subscriptions_were_refreshed()` stands in
for whatever observable the existing tests already use to prove the subscription pass completed;
use that observable, do not add a method to production code for the test's benefit.

- [x] **Step 2: Run the tests and confirm they fail.**

- [x] **Step 3: Implement** `_maybe_write_snapshot` and call it from `_refresh_subscriptions` after
  the subscription work, not before. Ordering matters: if the write is somehow slow, the
  subscriptions are already correct.

- [x] **Step 4: Run the FULL suite.** This modifies a trading process.

  Run: `python -m pytest -q` · `ruff check .` · `mypy src`

- [x] **Step 5: Docs.** `ARCHITECTURE.md`'s `src/monitor/` section gains a paragraph: the monitor
  now writes portfolio snapshots on its refresh cadence, rate-limited, RTH-only, and never at the
  expense of alerting.

- [x] **Step 6: Commit.**

---

## Task 1.4 — The `refresh` drain handler `[SONNET]`

**Trading-system code, and the only write this phase adds.**

**Context.** `refresh` is already a full `CommandKind` — `src/api/models/commands.py` defines
`CommandKind.REFRESH`, a `RefreshPayload`, and lists it among the kinds that carry no
`dedupe_key`. What it has never had is a registered handler, so a `refresh` command sits pending
forever. `STATUS.md`'s P2 row flags this, and **M0 Task 0.6** corrected
`docs/web/commands.md` to say so — that section currently reads "has no registered handler", which
this task replaces with the real behaviour.

**Files:** Modify `src/notify/command_drain.py`, `docs/web/commands.md`, `ARCHITECTURE.md`,
`STATUS.md`. Test `tests/test_drain_refresh.py`.

**Interfaces:**

```python
# src/notify/command_drain.py
@register("refresh")
async def _refresh(*, command: Any, ib: IB | None, **_: Any) -> dict:
    """Capture positions and account values now and write one portfolio snapshot.

    Ignores the monitor's interval gate: an operator asking for a fetch gets one.
    Raises CommandFailed("broker_unavailable") when ib is None.

    Returns {"captured_at": "<iso>", "positions": <int>, "snapshot_id": <int>}.
    """
```

Consumes: `save_portfolio_snapshot` (Task 1.1), `src.ibkr.portfolio.get_positions` and
`get_account_snapshot_async`, the existing `CommandFailed` and `register` from the same module.

**Design points that are not negotiable:**

1. **`ib is None` fails with `broker_unavailable`.** It must not write a row containing whatever
   the last known state was. A refresh that silently writes stale data is worse than a refresh
   that says it could not run.
2. **It ignores the interval gate.** The gate is the monitor's cadence control, not a rate limit on
   the operator.
3. **It creates no candidate, no approval, and no order**, so it needs no live-mode
   `confirm_token`. Do not add one. A test asserts no approval and no order row is created.
4. **A failed IB fetch fails the command with a reason**, not with `handler_error`. Use
   `CommandFailed("broker_unavailable")` for a connection problem and
   `CommandFailed("snapshot_failed", {...})` when the write itself returns `None`.
5. **`result_json` carries `captured_at`**, so the receipt can say what it actually got rather than
   just "applied".
6. It sends no Telegram notification. A refresh is not a safety-critical control; this matches how
   `universe_add`/`universe_remove` deliberately stay silent while halt/resume do not.

Required behaviours, each with a test:
- A refresh with a connected broker writes exactly one snapshot and marks the command `applied`.
- `result` contains `captured_at` and the position count.
- **`ib is None` fails with `broker_unavailable` and writes no row.** Its own test.
- **A refresh creates no `ApprovalRow` and no `OrderRow`.** Its own test — this is the phase's
  no-new-order-path assertion and it belongs here.
- A failing `save_portfolio_snapshot` fails the command with `snapshot_failed`, not
  `handler_error`.
- Two refreshes in a row both apply. There is no dedupe key and repeating is harmless.

- [x] **Step 1: Write the failing test**

```python
"""refresh is the phase's only write, and it is the least dangerous command in the system."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.notify.command_drain import drain_once


@pytest.mark.asyncio
async def test_a_refresh_writes_one_snapshot_and_applies(drain_env) -> None:
    cid = drain_env.enqueue("refresh", {})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    result = drain_env.result(cid)
    assert "captured_at" in result
    assert result["positions"] >= 0
    assert drain_env.snapshot_count() == 1


@pytest.mark.asyncio
async def test_a_refresh_with_no_broker_fails_honestly(drain_env) -> None:
    """Writing the last known state and calling it fresh is worse than saying no."""
    cid = drain_env.enqueue("refresh", {})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "broker_unavailable"
    assert drain_env.snapshot_count() == 0


@pytest.mark.asyncio
async def test_a_refresh_creates_no_approval_and_no_order(drain_env) -> None:
    """P3 and P4 add no path to an order. This is where that is asserted."""
    approvals_before = drain_env.approval_count()
    orders_before = drain_env.order_count()

    drain_env.enqueue("refresh", {})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.approval_count() == approvals_before
    assert drain_env.order_count() == orders_before


@pytest.mark.asyncio
async def test_a_failed_write_fails_with_its_own_reason(drain_env) -> None:
    cid = drain_env.enqueue("refresh", {})
    with patch("src.notify.command_drain.save_portfolio_snapshot", return_value=None):
        await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "snapshot_failed"


@pytest.mark.asyncio
async def test_two_refreshes_both_apply(drain_env) -> None:
    first = drain_env.enqueue("refresh", {})
    second = drain_env.enqueue("refresh", {})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(first) == "applied"
    assert drain_env.status(second) == "applied"
    assert drain_env.snapshot_count() == 2
```

`drain_env` already exists from P2's drain tests. Extend it with `snapshot_count()`,
`approval_count()` and `order_count()` rather than building a second fixture — grep
`tests/test_drain_*.py` for the existing definition.

- [x] **Step 2: Run the tests and confirm they fail.**

- [x] **Step 3: Implement** the handler.

- [x] **Step 4: Run the FULL suite.** This modifies `command_drain.py`, which every P2 command kind
  runs through.

- [x] **Step 5: Docs.** Replace `docs/web/commands.md`'s `refresh` section — M0 Task 0.6 left it
  describing an unregistered kind, and this task registers it. It gets: the empty payload, no
  dedupe key, the two failure reasons (`broker_unavailable`, `snapshot_failed`), what `result`
  contains, and the explicit statement that it creates no approval and no order.
  `ARCHITECTURE.md`'s `command_drain.py` entry gains the `refresh` paragraph the other kinds
  already have. `STATUS.md`'s P2 row: strike the "`refresh`'s handler remains unregistered" note,
  and say where it landed.

- [x] **Step 6: Commit.**

---

## Task 1.5 — The snapshot read helper and the fallback chain `[SONNET]`

**Requires a judgment call about degradation, and it sets the pattern every M2 route copies.**

**Context.** Spec §4.5. Three rungs: the newest `portfolio_snapshots` row; failing that, the
newest `position_snapshots` row plus the account block out of the newest
`journal.payload.eod_summary.account`; failing that, an explicit empty state. The third rung is the
point of the task. **A portfolio page rendering zeros because nothing has been captured is
indistinguishable from an account that is genuinely empty, and the difference is the whole
account.**

**Files:** Create `src/api/portfolio_source.py`. Modify `README.md`, `ARCHITECTURE.md`. Test
`tests/test_portfolio_source.py`.

**Interfaces:**

```python
# src/api/portfolio_source.py
@dataclass(frozen=True)
class PortfolioReading:
    """What the API managed to find, and how good it is."""

    snapshot: PortfolioSnapshot | None   # None only when every rung failed
    source: Literal["monitor", "refresh", "eod", "none"]
    as_of: datetime | None               # the capture time, NOT request time
    degraded: bool                       # True on the eod rung and the empty rung


def read_portfolio(db: Session) -> PortfolioReading:
    """Resolve the freshest portfolio state available, through the fallback chain.

    Reads through the caller's read-only session. Never raises: a failure on any rung
    falls through to the next, and the final rung is the empty reading.
    """
```

**Design points that are not negotiable:**

1. **`as_of` is the capture time, never `datetime.now()`.** P2's `/options/shorts` already
   establishes this discipline ("`as_of` is the snapshot's capture time, not request time") and its
   docstring says so. Copy it.
2. **Coerce it through `as_utc_opt` from `src/api/models/common.py`** (M0 Task 0.9). SQLite returns
   naive datetimes, and a naive datetime serialised without an offset is read by the browser as
   *local* time — silently shifting every displayed age by the viewer's UTC offset. **Do not write a
   local `_as_utc` here**; consolidating the two that existed is what M0 Task 0.9 was for.
3. **The empty rung is distinguishable from an empty account.** `source="none"` and
   `snapshot=None`, never a `PortfolioSnapshot` with empty lists and zeroed account values.
4. **An exception on a rung falls through, it does not fail the request.** A corrupt JSON payload
   in the newest row must not take the portfolio down when yesterday's row is fine.
5. **The account on the `eod` rung comes from `journal.payload["eod_summary"]["account"]`** and is
   validated through `AccountSnapshot.model_validate` rather than read field by field, so a schema
   drift surfaces as a fall-through rather than a `KeyError` at render time.

Required behaviours, each with a test:
- With a `portfolio_snapshots` row present, that row is returned with `degraded=False` and
  `as_of == captured_at`.
- With no `portfolio_snapshots` row but a `position_snapshots` row and a `journal` row, the `eod`
  rung is returned with `degraded=True` and the account values from the journal payload.
- **With nothing at all, `source="none"` and `snapshot is None`.** Its own test.
- With a `position_snapshots` row but no `journal` row, the reading still returns positions with a
  `None` account rather than falling all the way through. (State this in the dataclass: the account
  is optional on the `eod` rung.)
- A corrupt newest `portfolio_snapshots` payload falls through to the `eod` rung.
- `as_of` is never within a second of `datetime.now()` when a stored snapshot is old.

- [x] **Step 1: Write the failing test**

```python
"""Three rungs, and the bottom one must not look like an empty account."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.api.portfolio_source import read_portfolio


def test_the_newest_snapshot_wins(db, seed_portfolio_snapshot) -> None:
    when = datetime.now(UTC) - timedelta(minutes=7)
    seed_portfolio_snapshot(captured_at=when, source="monitor", net_liq=123.0)

    reading = read_portfolio(db)
    assert reading.source == "monitor"
    assert reading.degraded is False
    assert reading.as_of == when
    assert reading.snapshot is not None
    assert reading.snapshot.account.net_liquidation == 123.0


def test_the_eod_rung_is_used_when_no_snapshot_exists(db, seed_position_snapshot, seed_journal):
    seed_position_snapshot(symbols=["NVDA"])
    seed_journal(net_liq=456.0)

    reading = read_portfolio(db)
    assert reading.source == "eod"
    assert reading.degraded is True
    assert reading.snapshot is not None
    assert reading.snapshot.account.net_liquidation == 456.0


def test_nothing_at_all_is_reported_as_nothing_not_as_an_empty_account(db) -> None:
    """Zeros here would be a claim about the account. This is the point of the task."""
    reading = read_portfolio(db)
    assert reading.source == "none"
    assert reading.snapshot is None
    assert reading.as_of is None
    assert reading.degraded is True


def test_a_corrupt_newest_row_falls_through(db, seed_portfolio_snapshot,
                                            seed_position_snapshot, seed_journal) -> None:
    seed_portfolio_snapshot(corrupt=True)
    seed_position_snapshot(symbols=["NVDA"])
    seed_journal(net_liq=456.0)

    reading = read_portfolio(db)
    assert reading.source == "eod"


def test_as_of_is_the_capture_time_not_request_time(db, seed_portfolio_snapshot) -> None:
    old = datetime.now(UTC) - timedelta(hours=6)
    seed_portfolio_snapshot(captured_at=old)
    assert read_portfolio(db).as_of == old
```

- [x] **Step 2: Run the tests and confirm they fail.**

- [x] **Step 3: Implement.**

- [x] **Step 4: Run the gate.** `python -m pytest -q` · `ruff check .` · `mypy src`

- [x] **Step 5: Docs.** `README.md` layout table and `ARCHITECTURE.md` folder guide gain
  `src/api/portfolio_source.py`, described as the fallback chain rather than as "a helper".

- [x] **Step 6: Commit.**

---

## Task 1.6 — Milestone documentation `[GLM]`

**Files:** Modify `STATUS.md`, `ARCHITECTURE.md`, `README.md`. No tests, no code.

- [x] **Step 1:** `STATUS.md`'s web platform table gains a P3 row in the same dense style P2's
  rows use, covering M1 only: the new table, the two writers, the config keys, the fallback chain,
  and the explicit statement that nothing is user-visible yet. Do not mark P3 built.

- [x] **Step 2:** Verify — do not assume — that Tasks 1.1 through 1.5 each landed their own doc
  obligations. For each of `PortfolioSnapshotRow`, `src/storage/portfolio_snapshots.py`,
  `src/api/portfolio_source.py`, the two config keys, and the `refresh` command kind, grep the
  target doc for the entry and add whatever is missing. Task-level doc steps get skipped; this
  step exists to catch that.

- [x] **Step 3:** Confirm `docs/web/commands.md`'s `refresh` section no longer says "Triggers a
  full scan on the next cycle". If it does, Task 1.4's Step 5 was not done.

- [x] **Step 4:** Run the full gate and commit.

---

## Milestone 1 acceptance

- [x] `portfolio_snapshots` exists, is append-only, has no unique constraint, and is pruned to the
  configured retention by the EOD run.
- [x] `position_snapshots` is byte-for-byte unchanged in schema and has no new writer. Assignment
  auto-detection's tests are green.
- [x] The monitor writes a snapshot at most once per configured interval, only during RTH, reusing
  the positions it already fetched.
- [x] **A snapshot write that raises cannot escape into the monitor's refresh loop**, proven by a
  test that makes it raise.
- [x] `refresh` is a registered command kind. It writes a snapshot, fails `broker_unavailable`
  without a broker, and creates no approval and no order.
- [x] `read_portfolio` resolves all three rungs, and the empty rung is distinguishable from an
  empty account.
- [x] `as_of` is a capture time everywhere, never a request time.
- [x] `docs/web/commands.md`'s `refresh` section describes the handler that now exists.
- [x] Full gate green — `python -m pytest -q`, `ruff check .`, `mypy src` — with the full Python
  suite run, because this milestone modifies the monitor and the drain.
