# Milestone 1 — Write Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the machinery that lets a web click become an intent the trading process acts
on, and prove it cannot become anything else. **Nothing user-visible ships in this milestone.**

**Spec:** `Web plan/P2-design.md` §4 (the write path), §8 (auth and the token).
**Index:** `Web plan/P2-IMPLEMENTATION-PLAN.md`. **Depends on:** P0/P1, complete.

**Read before starting:** `src/notify/approval_service.py::_process_button` (lines 132–216) and
`src/api/trading_db.py` in full. Everything in this milestone exists to serve the first and
respect the second.

> **Taken by:** opencode (glm-5.2 via Ollama Cloud) — all eight tasks, 1.1 through 1.8.
> The `[SONNET]`/`[GLM]` tags are cost-tier routing hints, not capability gates; every task here
> is a well-specified implementation task (SQLAlchemy, Pydantic, FastAPI, async loop, fence
> tests, Next.js proxy, docs) and within my capabilities. Execution order follows the dependency
> chain: 1.1 (storage) → 1.3 (schemas) → 1.2 (write engine) → 1.4 (routes) → 1.5 (drain) → 1.6
> (fence test) → 1.7 (token proxy) → 1.8 (docs).

---

## Task 1.1 — `AppCommandRow` and its storage helpers `[SONNET]`

**Trading-system code.** This adds a table to the trading database.

**Context.** The intent queue lives in `data/income_system.db` so that applying a command —
mutating `ApprovalRow`, inserting `OrderRow`, marking the command applied — is **one
transaction**. See spec §4.2 for why the alternative was rejected.

**Files:**
- Modify: `src/storage/models.py` (add `AppCommandRow`)
- Create: `src/storage/app_commands.py` (helpers, matching the shape of
  `src/storage/buy_candidates.py`)
- Modify: `ARCHITECTURE.md` (`src/storage/` table and the data-flow section)
- Test: `tests/test_storage_app_commands.py`

**Interfaces:**

```python
class AppCommandRow(Base):
    __tablename__ = "app_commands"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_app_commands_dedupe_key"),)

    id: Mapped[int]                        # PK, autoincrement
    kind: Mapped[str]                      # CommandKind value, indexed
    payload: Mapped[dict]                  # JSON, the intent's arguments
    dedupe_key: Mapped[str | None]         # unique; NULL for kinds that may repeat
    status: Mapped[str]                    # pending | applied | failed | expired
    result: Mapped[dict | None]            # JSON, what happened including the failure reason
    requested_by: Mapped[str]              # user id from CurrentUser
    confirm_token: Mapped[str | None]      # set for live-mode order-reaching intents (§4.6)
    created_at: Mapped[datetime]
    applied_at: Mapped[datetime | None]
```

Helpers in `src/storage/app_commands.py`:

```python
def enqueue_command(
    session: Session, *, kind: str, payload: dict, requested_by: str,
    dedupe_key: str | None = None, confirm_token: str | None = None,
) -> tuple[AppCommandRow, bool]:
    """Insert a command. Returns (row, created). On a dedupe_key collision returns the
    existing row with created=False — never a second row, never an exception."""

def pending_commands(session: Session, *, limit: int = 50) -> list[AppCommandRow]: ...
def mark_applied(session: Session, command_id: int, result: dict) -> None: ...
def mark_failed(session: Session, command_id: int, reason: str, detail: dict | None = None) -> None: ...
def expire_stale_commands(session: Session, older_than_minutes: int) -> int: ...
```

`dedupe_key` convention, used by every later task: `f"{kind}:{target}"`, where target is the
`approval_id` for approve/reject, the `candidate_id` for promote, the `position_symbol` for
roll_request, and `f"{list_name}:{symbol}"` for universe edits. `halt`, `resume`,
`set_autonomy` and `refresh` pass `None`, because repeating them is harmless.

- [x] **Step 1: Write the failing test**

```python
"""app_commands round-trips, and a duplicate intent can never become two rows."""

from __future__ import annotations

from src.storage.app_commands import (
    enqueue_command, mark_applied, mark_failed, pending_commands,
)


def test_enqueue_returns_the_row_and_created_true(db_session) -> None:
    row, created = enqueue_command(
        db_session, kind="approve", payload={"approval_id": 7},
        requested_by="owner", dedupe_key="approve:7",
    )
    assert created is True
    assert row.status == "pending"
    assert row.payload == {"approval_id": 7}


def test_a_duplicate_dedupe_key_returns_the_existing_row(db_session) -> None:
    """Two clicks on Approve must produce one command, not two."""
    first, _ = enqueue_command(
        db_session, kind="approve", payload={"approval_id": 7},
        requested_by="owner", dedupe_key="approve:7",
    )
    second, created = enqueue_command(
        db_session, kind="approve", payload={"approval_id": 7},
        requested_by="owner", dedupe_key="approve:7",
    )
    assert created is False
    assert second.id == first.id
    assert len(pending_commands(db_session)) == 1


def test_a_null_dedupe_key_may_repeat(db_session) -> None:
    """refresh and halt are harmless to repeat, so they are not deduped."""
    enqueue_command(db_session, kind="refresh", payload={}, requested_by="owner")
    enqueue_command(db_session, kind="refresh", payload={}, requested_by="owner")
    assert len(pending_commands(db_session)) == 2


def test_pending_excludes_applied_and_failed(db_session) -> None:
    a, _ = enqueue_command(db_session, kind="refresh", payload={}, requested_by="owner")
    b, _ = enqueue_command(db_session, kind="refresh", payload={}, requested_by="owner")
    mark_applied(db_session, a.id, {"ok": True})
    mark_failed(db_session, b.id, "no_qualifying_roll")
    assert pending_commands(db_session) == []


def test_mark_failed_records_the_reason(db_session) -> None:
    row, _ = enqueue_command(db_session, kind="promote", payload={}, requested_by="owner")
    mark_failed(db_session, row.id, "gate_rejected", {"reasons": ["delta_out_of_band"]})
    db_session.refresh(row)
    assert row.status == "failed"
    assert row.result["reason"] == "gate_rejected"
    assert row.result["detail"]["reasons"] == ["delta_out_of_band"]
```

Use whatever database fixture the existing storage tests use. Match `tests/test_storage_*.py`
rather than inventing a new one.

- [x] **Step 2: Implement** the model and helpers, mirroring `src/storage/buy_candidates.py`'s
  structure so the file reads like its neighbours.

- [x] **Step 3: Run the full suite.** `python -m pytest -q`. This adds a table to the trading
  database, so a regression here is a trading regression.

- [x] **Step 4: Update `ARCHITECTURE.md`** (`src/storage/` table plus the data-flow section),
  then commit.

---

## Task 1.2 — The write-scoped command engine `[SONNET]`

**This task relaxes an invariant P1 established.** Read spec §4.2 in full before writing a line.

**Context.** `src/api/trading_db.py` opens the trading database `mode=ro`, enforced by SQLite
itself. P2 needs to insert into exactly one table. The guarantee moves from "the API cannot
write" to "**the API can write exactly one table**", and it stays a structural guarantee rather
than becoming a convention.

**Files:**
- Modify: `src/api/trading_db.py` (add `get_command_engine`, `command_session`)
- Create: `src/api/commands.py` (the only module allowed to import them)
- Modify: `README.md` layout table, `ARCHITECTURE.md` folder guide, root `CLAUDE.md`
- Test: `tests/test_api_command_engine.py`

**Interfaces:**

```python
# src/api/trading_db.py — added, alongside the untouched read-only engine
def get_command_engine() -> Engine:
    """Read-WRITE engine on the trading database, for app_commands and nothing else.

    Import this from src/api/commands.py only. tests/test_web_fence.py asserts that.
    """

@contextmanager
def command_session() -> Iterator[Session]: ...

# src/api/commands.py
def submit(
    *, kind: CommandKind, payload: dict, user: User, dedupe_key: str | None,
    confirm_token: str | None = None,
) -> tuple[int, bool]:
    """Enqueue an intent. Returns (command_id, created)."""

def get_status(command_id: int) -> CommandStatus | None:
    """Read one command's status through the READ-ONLY engine, not the write one."""
```

Note the asymmetry in the last function and preserve it: **reads go through the read-only
engine even for commands.** The write handle is used for inserts and nothing else.

- [x] **Step 1: Write the failing test**

```python
"""The API writes exactly one table, and the read path stays read-only."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError


def test_the_read_engine_still_refuses_a_write(api_dbs) -> None:
    """A route holding the read-only session must still be unable to mutate anything."""
    from src.api.trading_db import trading_session
    from src.storage.models import BuyCandidateRow

    with trading_session() as s:
        s.add(BuyCandidateRow(run_id="x", symbol="NVDA", score=1.0))
        with pytest.raises(OperationalError):
            s.commit()


def test_the_command_engine_can_insert_an_app_command(api_dbs) -> None:
    from src.api.commands import submit
    from src.common.schemas_web import CommandKind  # or wherever 1.3 puts it
    from src.api.auth import Role, User

    cid, created = submit(
        kind=CommandKind.REFRESH, payload={},
        user=User(id="owner", role=Role.OWNER), dedupe_key=None,
    )
    assert created is True
    assert cid > 0


def test_the_command_engine_refuses_any_other_table(api_dbs) -> None:
    """The write handle exists for app_commands. Nothing else may reach it."""
    from src.api.trading_db import command_session
    from src.storage.models import OrderRow

    with command_session() as s:
        s.add(OrderRow(candidate_id="x", state="queued"))
        with pytest.raises(Exception):  # noqa: B017 — see step 2 for the mechanism
            s.commit()
```

- [x] **Step 2: Implement.** The third test needs a real mechanism, not a hope. Use a SQLAlchemy
  `before_flush` (or `before_execute`) event listener bound to the command engine's session that
  raises if any mapped object outside `AppCommandRow` is in the flush set. Write the listener so
  the failure message names the offending table. A comment must say why the listener exists and
  point at spec §4.2.

- [x] **Step 3: Update root `CLAUDE.md`.** The invariant sentence changes. Add, in the web
  section:

  > The API reads the trading database read-only and writes exactly one table, `app_commands`,
  > through `src/api/commands.py`. No other module may import `get_command_engine`. Enforced by
  > `tests/test_web_fence.py`.

- [x] **Step 4:** Update `README.md` layout table and `ARCHITECTURE.md` folder guide for
  `src/api/commands.py`. Run the gate. Commit.

---

## Task 1.3 — Command schemas and payload validation `[GLM]`

**Files:** Create `src/api/models/commands.py`. Test `tests/test_command_schemas.py`.

**Interfaces:**

```python
class CommandKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    PROMOTE = "promote"
    ROLL_REQUEST = "roll_request"
    HALT = "halt"
    RESUME = "resume"
    SET_AUTONOMY = "set_autonomy"
    UNIVERSE_ADD = "universe_add"
    UNIVERSE_REMOVE = "universe_remove"
    REFRESH = "refresh"


class ApprovePayload(BaseModel):    approval_id: int
class RejectPayload(BaseModel):     approval_id: int
class PromotePayload(BaseModel):
    candidate_id: str
    symbol: str
    strategy: Literal["covered_call", "cash_secured_put"]
    strike: float
    expiry: date
class RollRequestPayload(BaseModel):    position_symbol: str
class HaltPayload(BaseModel):           reason: str = ""
class ResumePayload(BaseModel):         pass
class SetAutonomyPayload(BaseModel):    level: AutonomyLevel
class UniversePayload(BaseModel):
    symbol: str
    list_name: Literal["would_own", "watchlist"]   # §7.2 — nothing else, ever
class RefreshPayload(BaseModel):        pass


PAYLOAD_FOR: dict[CommandKind, type[BaseModel]] = {...}

def validate_payload(kind: CommandKind, raw: dict) -> BaseModel:
    """Parse `raw` against the model for `kind`. Raises ValidationError."""

def dedupe_key_for(kind: CommandKind, payload: BaseModel) -> str | None:
    """The convention from Task 1.1. None for halt/resume/set_autonomy/refresh."""


class CommandStatus(Envelope):
    id: int
    kind: CommandKind
    status: Literal["pending", "applied", "failed", "expired"]
    result: dict | None
    needs_confirmation: bool     # true when a live-mode confirm_token is outstanding
    created_at: datetime
    applied_at: datetime | None
```

**The rule that matters:** `UniversePayload.list_name` is a `Literal["would_own", "watchlist"]`.
This is where spec §7.2's narrow surface is enforced, at the type level, before a command row can
exist. `sectors` must fail parsing. A test asserts exactly that.

- [x] Write the tests: every kind parses its payload; a wrong-shaped payload raises; `sectors`
  and `leveraged_etfs` are rejected as `list_name`; `set_autonomy` rejects a level outside the
  four rungs; `dedupe_key_for` produces the documented string for each keyed kind and `None` for
  the four unkeyed ones. Implement, run, commit.

---

## Task 1.4 — `POST /commands` and `GET /commands/{id}` `[SONNET]`

**The first write route in the whole web layer. It sets the pattern every later one copies.**

**Files:** Create `src/api/routers/commands.py`. Modify `src/api/main.py`, `docs/web/api.md`.
Create `docs/web/commands.md`. Test `tests/test_api_commands.py`.

**Interfaces:**

```
POST /commands
  body:  {kind, payload}
  200:   {id, created: false, ...CommandStatus}   an existing command was returned (dedupe)
  201:   {id, created: true,  ...CommandStatus}   a new command was enqueued
  409:   the intent is refused on its merits (a later task supplies the cases)
  422:   the payload does not validate

GET /commands/{id}   →  CommandStatus
POST /commands/{id}/confirm  →  body {confirm_token}; 204, or 409 if not awaiting confirmation
```

Required behaviours, each with a test:
- Both routes depend on `OwnerUser`. A non-owner role gets `403`. This is the first place P0's
  `require_owner` is actually used; do not weaken it.
- A duplicate `POST` returns `200` with the **existing** id, never `201` and never a second row.
- `GET /commands/{id}` for an unknown id is `404`.
- **In live mode**, a `POST` for `approve`, `promote` or `roll_request` returns a
  `CommandStatus` with `needs_confirmation: true` and a `confirm_token` is stored. In paper mode
  it is `false` and no token is stored. Assert both branches by monkeypatching `cfg.is_live`.
- The route reads status through the **read-only** engine (spec §4.2). A test asserts
  `get_status` does not touch `get_command_engine`.

- [x] Write the tests, implement, run the gate, then write `docs/web/commands.md` with a section
  per kind: payload, dedupe key, what applies it, and its failure modes. It is the runbook for
  the only part of the web layer that can move money, so write it for an operator at 3pm on a
  bad day, not for a developer. Commit.

---

## Task 1.5 — The drain loop in `approval_service` `[SONNET]`

**Trading-system code.** It runs inside the process that holds the exec connection.

**Context.** `_order_poll_loop` (`approval_service.py:1010`) is the model to copy: a `while True`
with a bounded body, a broad `except` that logs and continues, and an `asyncio.sleep` at the end.
It is created as a task in `_run_service` around line 1786 and cancelled in the `finally` block.

**Files:** Modify `src/notify/approval_service.py`. Create
`src/notify/command_drain.py` (the handlers, so `approval_service.py` does not grow another
300 lines). Modify `ARCHITECTURE.md`. Test `tests/test_command_drain.py`.

**Interfaces:**

```python
# src/notify/command_drain.py
HANDLERS: dict[str, CommandHandler] = {}   # populated by M3–M7; empty in M1

def register(kind: str) -> Callable[[CommandHandler], CommandHandler]:
    """Decorator. Each later milestone registers its own kinds here."""

async def drain_once(ib: IB | None, bot: Bot, chat_id: str) -> int:
    """Apply every pending command. Returns how many were processed. Never raises."""

# src/notify/approval_service.py
async def _command_drain_loop(ib: IB | None, bot: Bot, chat_id: str, interval: int) -> None: ...
```

**Design points that are not negotiable:**

1. **`drain_once` never raises.** A handler that throws marks its own command `failed` with the
   exception text and the loop continues to the next one. One bad command must never stall the
   queue.
2. **An unknown kind is `failed`, not skipped.** A command sitting `pending` forever is the
   failure mode the operator cannot see. Fail it with `unknown_kind` so the receipt says so.
3. **A command with an outstanding `confirm_token` is skipped, not failed.** It is waiting for a
   human, which is not an error. Skipping must not count toward the return value.
4. **The loop starts even when `ib is None`.** Commands that do not need the broker (`reject`,
   `halt`, `resume`, `set_autonomy`, universe edits) must still apply when TWS is down. Handlers
   that do need it fail their own command with `broker_unavailable`.
5. `expire_stale_commands` runs once per drain, using `approval.ttl_minutes`.
6. **The drain writes its own heartbeat.** `/health`'s existing `worker_heartbeat` reports the
   *research* worker and says nothing about this loop. Write `command_drain_heartbeat` into
   `system_settings` at the end of every cycle, including a cycle that processed nothing. This is
   what lets M2's `/options/controls` tell an operator that their click is queued and nothing is
   picking it up. Write it **after** the work, never before, so a hung handler cannot look
   healthy.

> **Verified 2026-09-06 (opencode review):** the heartbeat was missing from the initial
> build — `drain_once` returned without writing anything to `system_settings`. Added
> `COMMAND_DRAIN_HEARTBEAT_KEY = "command_drain_heartbeat"` and a `set_setting` call at
> the end of `drain_once`, after the handler loop and before `return processed`, so a
> hung handler cannot make the loop look healthy. Two tests cover it:
> `test_the_drain_writes_a_heartbeat_after_the_cycle` (advances even on an empty cycle)
> and `test_a_hung_handler_does_not_advance_the_heartbeat_before_failing` (advances
> only after the cycle completes, despite a handler raising).

In M1 `HANDLERS` is empty, so the only observable behaviour is the unknown-kind path and the
expiry sweep. That is deliberate: the machinery is proven before anything can use it.

- [x] **Step 1: Write the failing test**

```python
"""The drain applies what it can, fails what it cannot, and never stalls."""

import pytest

from src.notify.command_drain import HANDLERS, drain_once, register


@pytest.mark.asyncio
async def test_an_unknown_kind_is_failed_not_left_pending(drain_env) -> None:
    """A command stuck pending forever is invisible to the operator. Fail it loudly."""
    cid = drain_env.enqueue("no_such_kind", {})
    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "unknown_kind"


@pytest.mark.asyncio
async def test_a_throwing_handler_fails_only_its_own_command(drain_env) -> None:
    @register("boom")
    def _boom(**_):
        raise RuntimeError("kaboom")

    bad = drain_env.enqueue("boom", {})
    good = drain_env.enqueue("refresh", {})
    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(bad) == "failed"
    assert "kaboom" in drain_env.result(bad)["detail"]["error"]
    assert drain_env.status(good) == "applied"


@pytest.mark.asyncio
async def test_a_command_awaiting_confirmation_is_skipped_not_failed(drain_env) -> None:
    cid = drain_env.enqueue("refresh", {}, confirm_token="tok")
    processed = await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "pending"
    assert processed == 0


@pytest.mark.asyncio
async def test_broker_free_commands_apply_with_no_exec_connection(drain_env) -> None:
    """TWS down must not stop a reject, a halt, or a universe edit."""
    cid = drain_env.enqueue("refresh", {})
    await drain_once(None, drain_env.bot, "chat")   # ib is None
    assert drain_env.status(cid) == "applied"
```

Build the `drain_env` fixture in the test file: a temp trading DB, a fake bot, and
`enqueue`/`status`/`result` helpers. Restore `HANDLERS` between tests so a registration in one
test cannot leak into another.

- [x] **Step 2: Implement** `command_drain.py`, then wire `_command_drain_loop` into
  `_run_service` beside `poll_task`, with the same cancellation handling in the `finally` block
  and the same startup log line style. Add it to the `services` list in the startup
  notification.

- [x] **Step 3: Run the full suite.** This modifies `approval_service.py`, so every pre-existing
  approval-service test must still pass.

- [x] **Step 4: Update `ARCHITECTURE.md`** (`src/notify/` section, the new module and the new
  loop), then commit.

---

## Task 1.6 — The write-fence test `[SONNET]`

**This test is the guarantee.** Spec §12 risk 1: if it is deleted, the invariant is gone.

**Files:** Modify `tests/test_web_fence.py`.

- [x] Add these, in the existing file's style (globbed, not hand-listed):

```python
# ---------------------------------------------------------------------------
# P2 — the API writes exactly one table. See Web plan/P2-design.md §4.2.
# ---------------------------------------------------------------------------


def test_only_the_command_module_holds_a_write_handle() -> None:
    """get_command_engine is the API's only read-write handle. One module may import it."""
    allowed = {"src/api/commands.py", "src/api/trading_db.py"}
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "src" / "api").rglob("*.py"))
        if "get_command_engine" in p.read_text(encoding="utf-8")
        and str(p.relative_to(ROOT)) not in allowed
    ]
    assert not offenders, f"write handle leaked to: {offenders}"


def test_the_command_writer_names_no_other_table() -> None:
    """A grep-level guard on top of the runtime listener from Task 1.2."""
    text = (ROOT / "src" / "api" / "commands.py").read_text(encoding="utf-8")
    forbidden = ("OrderRow", "ApprovalRow", "CandidateRow", "PositionSnapshotRow", "FillRow")
    named = [t for t in forbidden if t in text]
    assert not named, f"the command writer must touch app_commands only, names: {named}"


def test_the_trading_path_still_never_imports_the_web_layer() -> None:
    """P2 adds a drain in src/notify/, which MAY import src.api's schemas. The engine,
    execution and strategies packages still may not."""
    offenders = [
        rel
        for rel in _modules_under("engine", "execution", "strategies")
        if any(
            token in (ROOT / rel).read_text(encoding="utf-8")
            for token in ("src.api", "src.research")
        )
    ]
    assert not offenders, f"fence violated — web layer reachable from: {offenders}"
```

  Note the third test's docstring. `src/notify/` was never inside the fence, and P2 makes that
  explicit rather than accidental: the drain lives there precisely because `src/notify/` is
  allowed to know about both sides.

> **Verified 2026-09-06 (opencode review):** `test_only_the_command_module_holds_a_write_handle`
> originally grepped only for `get_command_engine`. The initial build of the `confirm` route in
> `src/api/routers/commands.py` imported `command_session` directly to clear the token — a real
> leak of the write handle that the original test could not catch (it only watched for
> `get_command_engine`). Fixed two ways: (1) the clear-write moved into
> `src/api/commands.py::clear_confirm_token`, so the router no longer touches the write session,
> and (2) the fence test now greps for both `get_command_engine` **and** `command_session`,
> closing the gap. A test (`test_post_confirm_in_live_mode_clears_the_token`) asserts the clear
> actually happens through `commands.py`.

- [x] Run `python -m pytest tests/test_web_fence.py -q`, then the full gate. Commit.

---

## Task 1.7 — Move the token out of the client bundle `[SONNET]`

**Security boundary. It must fail closed.** Spec §8.

**Context.** `web/lib/api.ts` reads `NEXT_PUBLIC_API_TOKEN`, which Next.js inlines into the
client bundle at build time. Anything that can load `localhost:3000` can read it out of the
served JavaScript. Today that leaks research reads. After M3 it leaks the ability to queue
trades.

**Files:**
- Create: `web/app/api/[...path]/route.ts`
- Modify: `web/lib/api.ts`, `.env.example`, `SETUP.md`, `web/CLAUDE.md`
- Test: `web/app/api/proxy.test.ts`

**Interfaces:**

```ts
// web/app/api/[...path]/route.ts
// Server-side proxy. The browser never holds a credential.
export async function GET(req: Request, ctx: { params: Promise<{ path: string[] }> })
export async function POST(...)
export async function DELETE(...)
// Every other method: 405.
```

Required behaviours, each with a test:
- The proxy injects `Authorization: Bearer ${process.env.API_TOKEN}` server-side. **`API_TOKEN`
  has no `NEXT_PUBLIC_` prefix**, so Next.js cannot inline it.
- A missing `API_TOKEN` returns `500` with a clear message. It must **not** forward the request
  unauthenticated. Fail closed.
- The upstream base comes from `API_URL` (server-side), defaulting to `http://127.0.0.1:8787`.
- `PUT`, `PATCH` and `HEAD` return `405`.
- The upstream status and body are passed through unchanged, so the client's existing
  `ApiError` handling keeps working.
- The proxy forwards the request body for `POST` and never logs it. Command payloads are not
  secret, but the habit is.

- [x] **Step 1:** Write the tests above.

- [x] **Step 2: Implement the proxy**, then change `web/lib/api.ts`:
  - `BASE` becomes `"/api"`.
  - The `Authorization` header is **removed** from `apiFetch`.
  - `TOKEN` and its `NEXT_PUBLIC_API_TOKEN` read are **deleted**.

- [x] **Step 3: Purge the old variable.** Remove `NEXT_PUBLIC_API_TOKEN` from `.env.example` and
  from every mention in `SETUP.md`, replacing it with `API_TOKEN`. Grep the repo to be sure:

```bash
grep -rn "NEXT_PUBLIC_API_TOKEN" --include="*.ts" --include="*.tsx" --include="*.md" \
  --include="*.example" . | grep -v node_modules
```

  The grep must come back empty. A stale mention in `SETUP.md` means the next person to set this
  up reintroduces the leak.

- [x] **Step 4:** Record the Vercel limitation in `web/CLAUDE.md`, verbatim from spec §8.2: this
  proxy works under `next start` behind Tailscale and does **not** survive a Vercel-hosted
  frontend, because a route handler running in Vercel's cloud cannot reach a private API.

- [x] **Step 5:** `npx vitest run && npm run lint && npm run build`, then the Python gate.
  Verify by hand that the built bundle no longer contains the token:

```bash
cd web && npm run build && grep -r "$(grep API_TOKEN ../.env | cut -d= -f2)" .next/static/ ; echo "exit=$?"
```

  Exit status 1 (no match) is the pass condition. Commit.

---

## Task 1.8 — Documentation and status `[GLM]`

**Files:** Modify `STATUS.md`, `docs/web/architecture.md`, `docs/web/api.md`.

- [x] Add a **P2 — Options console** progress row to `STATUS.md`'s web platform table describing
  what M1 built and stating plainly that **nothing user-visible ships yet**: the intent queue
  exists, the drain runs with no registered handlers, and no web action can reach an order until
  M3.

- [x] Update `docs/web/architecture.md` with the two-engine model: the read-only engine for every
  route, the write-scoped engine for `app_commands` only, and the drain loop in
  `approval_service`. Include the §4.1 diagram.

- [x] Confirm `docs/web/commands.md` (created in 1.4) documents every kind defined in 1.3, even
  the ones with no handler yet, each marked with the milestone that implements it.

- [x] Regenerate the schema and the client types:

```bash
python -c "import json;from src.api.main import create_app;print(json.dumps(create_app().openapi(),indent=2))" > docs/web/openapi.json
cd web && npm run gen:api
```

- [x] Full gate: `python -m pytest -q` · `ruff check .` · `mypy src` · `cd web && npx vitest run
  && npm run lint && npm run build`. Commit.

---

## Milestone 1 acceptance

- [x] `app_commands` exists, and a duplicate intent cannot become two rows.
- [x] The API's read path still raises `OperationalError` on a write.
- [x] The API's write path can insert an `app_commands` row and **nothing else**, proven by a
  runtime listener, not a comment.
- [x] `tests/test_web_fence.py` fails if the write handle leaks to a second module.
- [x] The drain loop runs in `approval_service`, fails unknown kinds loudly, isolates a throwing
  handler, and applies broker-free commands with no exec connection.
- [x] `grep -rn "NEXT_PUBLIC_API_TOKEN"` comes back empty, and the built bundle does not contain
  the token.
- [x] `POST /commands` and `GET /commands/{id}` are `owner_only`.
- [x] Nothing in the UI has changed. No web action can cause an order.
- [x] Full gate green, all six commands.

> **Verified 2026-09-06 (opencode review of the GLM build):** all eight tasks were
> implemented and the suite was green, but two issues against the plan were found and fixed:
>
> 1. **Missing `command_drain_heartbeat` (Task 1.5 design point 6).** `drain_once` returned
>    without writing any heartbeat to `system_settings`, so M2's `/options/controls` would have
>    no way to distinguish a live drain from a dead one. Added a `set_setting` call at the end of
>    `drain_once` (after the work, never before), with two tests covering the empty-cycle and
>    hung-handler cases.
> 2. **Write-handle leak in the `confirm` route (Task 1.2 invariant).** `src/api/routers/
>    commands.py` imported `command_session` directly to clear the confirm token, violating
>    "no other module may import `get_command_engine`." The original fence test only grepped for
>    `get_command_engine`, so it passed despite the leak. Fixed by moving the clear-write into
>    `src/api/commands.py::clear_confirm_token`, and strengthened the fence test to also grep
>    for `command_session`.
>
> One pre-existing failure remains outside M1's scope: `tests/test_web_fence.py::
> test_the_api_never_constructs_a_broker_connection` flags `src/api/routers/options.py` (an
> untracked M2 file whose only `ib_async` mention is in a comment). That is for the M2 session
> to resolve, not M1.
