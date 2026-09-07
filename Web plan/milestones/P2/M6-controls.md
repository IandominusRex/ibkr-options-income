# Milestone 6 — Controls

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Halt, resume and the autonomy rung reachable from the browser.

**Spec:** `Web plan/P2-design.md` §6.4, §9.3. **Index:** `Web plan/P2-IMPLEMENTATION-PLAN.md`.
**Depends on:** Milestone 5.

> **Taken by:** opencode (glm-5.3 via Ollama Cloud) — **all four tasks, 6.1 through 6.4, now
> complete** (see the completion record at the bottom of this file for per-task notes and the
> outcomes of the four design decisions flagged below). The `[SONNET]`/`[GLM]` tags are
> cost-tier routing hints, not capability gates — same
> convention M1–M5 used, where opencode took every task regardless of tag. All four are
> honestly within reach here:
>
> - **6.1** is trading-system code, but of the lightest kind: `system_settings` already owns
>   every helper (`set_halted`, `get_halt_reason`, `set_autonomy_level` — verified in the tree),
>   the Telegram `handle_halt_command` / `handle_resume_command` / `handle_autonomy_command`
>   (`approval_service.py`) are the reference behaviour, and the drain's `register` /
>   `drain_once` / `CommandFailed` machinery plus the `drain_env` fixture pattern exist from
>   M3–M5 (`tests/test_drain_approve_reject.py` etc.). The handlers are thin resolvers over
>   existing helpers, same shape as `_reject`, with no order path anywhere near them.
> - **6.2** is pure Pydantic-schema hardening on models that already exist from M1, with the
>   required behaviours given verbatim; the `needs_confirmation` asymmetry pins what
>   `_LIVE_CONFIRM_KINDS` already does (halt/resume/set_autonomy are simply not in the set).
> - **6.3** is judgment-weight work, but the weight table above is the specification and
>   `ConfirmAction`'s typed-word gate (`requireTypedWord`, "stays disabled until the word
>   matches exactly") already exists from M3, as do `CommandReceipt`, `submitCommand`,
>   `useCommandStatus` and the live-mode second-confirmation wiring in `DecideControls`. The
>   asymmetry (halt one click, resume typed) deliberately refines design §9.3's first draft
>   ("halt takes a typed word") — this milestone's table is the later, considered word.
> - **6.4** is pure test authoring against machinery 6.1 builds; the three test bodies are
>   concrete, and the token-grep pattern is already proven in M5's
>   `test_the_roll_handler_adds_no_economic_bounds_of_its_own` (same file).
>
> **Four design decisions worth flagging up front** (each resolved below, recorded here so the
> resolution is visible before the diff):
>
> 1. **"No new setting keys" vs. the banner's "time it was halted".** Task 6.1 says "write no
>    new setting keys"; Task 6.3's banner requires "the time it was halted". No halt timestamp
>    exists anywhere today. Resolution: the resume-side and display-side data is already
>    sufficient without a new key — the **command row** carries `created_at`/`applied_at`, so
>    `GET /options/controls` gains `halted_at` derived from the **most recent applied `halt`
>    command** (a join the read path already knows how to do), and `set_halted` is called
>    unchanged. A halt tripped by a circuit breaker (no command row) renders the banner without
>    a time rather than fabricating one — an honest "unknown" beats a wrong timestamp.
> 2. **`promotion_blockers` on the web rung change.** Telegram's `/autonomy` refuses a
>    promotion with unmet evidence criteria. The web `set_autonomy` must enforce the same
>    policy — otherwise the browser becomes the rung ladder's back door — but the milestone
>    text is silent on it. Resolution: the handler calls `promotion_blockers(target)` exactly
>    as Telegram does, and unmet criteria fail the command with reason `promotion_refused`
>    carrying the blocker list, so the receipt can render them. Demotion is always applied.
> 3. **"Never fails for lack of one" vs. `promotion_blockers`' DB read.** The halt handler
>    must work with the broker down (design point 1); `promotion_blockers` reads the trading
>    DB, which is local SQLite and does not need the broker — but it can raise, and its own
>    fallback returns `["could not read fill history"]`. The handlers keep 6.1's rule absolute:
>    `halt` and `resume` touch nothing but `system_settings` and never fail for lack of a
>    broker; only `set_autonomy` reads history, exactly like Telegram does today.
> 4. **`ConfirmAction`'s docstring says the typed word is "used by `halt` in M6".** The
>    milestone moved the typed word to `resume`. The component is untouched functionally; its
>    docstring is corrected to say `resume`, so a later reader does not re-attach it to halt.

**The asymmetry that shapes this milestone:** halting when you did not mean to costs you some
missed premium. Failing to halt when you meant to can cost a great deal more. So the halt path is
built to be fast and hard to miss, and the resume path is built to be deliberate. They are not
mirror images and should not be implemented as one toggle.

---

## Task 6.1 — The `halt`, `resume` and `set_autonomy` handlers `[SONNET]`

> **Taken by:** opencode (glm-5.3). Trading-system code, but the lightest kind: the
> `system_settings` helpers and the drain machinery are verified in the tree, the Telegram
> reference behaviour is read, and no order path is reachable from any of the three handlers.

**Trading-system code, and one of them is the kill switch.**

**Context.** `src/storage/system_settings.py` already owns all three:
`get_autonomy_level` / `set_autonomy_level`, and the halt keys `HALT_KEY` / `HALT_REASON_KEY`.
The Telegram commands `handle_halt_command`, `handle_resume_command` and
`handle_autonomy_command` (`approval_service.py:869–941`) are the reference behaviour.

**Files:** Modify `src/notify/command_drain.py`, `docs/web/commands.md`. Test
`tests/test_drain_controls.py`.

**Interfaces:**

```python
@register("halt")
def _halt(*, command, **_) -> dict:
    """Set the kill switch. Never needs the broker, never fails for lack of one."""

@register("resume")
def _resume(*, command, **_) -> dict: ...

@register("set_autonomy")
def _set_autonomy(*, command, **_) -> dict: ...
```

**Design points that are not negotiable:**

1. **All three apply with `ib is None`.** Halting is most valuable exactly when something is
   wrong, and "TWS is unreachable" is a common shape of wrong. A halt that fails because the
   broker is down is a halt that fails when you need it.
2. **Halt is idempotent and always succeeds.** Halting an already-halted system is `applied`,
   not `failed`. The operator's intent is satisfied.
3. **The reason is recorded.** `halt` stores `payload.reason` in `HALT_REASON_KEY`, and an empty
   reason becomes `"halted from the web console"` rather than an empty string, so
   `/status` and the console both say something useful.
4. **`resume` records who released it** in the command's `result`, using `requested_by`.
5. `set_autonomy` accepts only the four `AutonomyLevel` rungs. 1.3's schema already enforces this
   at parse time; the handler does not need to re-check, and must not silently coerce an unknown
   value.
6. Each handler sends a Telegram notification, because a halt raised from the browser must be
   visible to the operator wherever they are. This is the one place a handler notifies, and the
   reason is that these are control-plane changes with no order-poll loop to report them later.

- [x] **Step 1: Write the failing test** (13 tests in `tests/test_drain_controls.py` —
  the six specified plus resume-when-not-halted, missing-reason-key, promotion-refused,
  demotion-always-applies, both-other-kinds-notify, and the parametrised
  all-three-with-no-broker)

```python
"""The kill switch works when everything else does not."""

from __future__ import annotations

import pytest

from src.common.schemas import AutonomyLevel
from src.storage.system_settings import get_autonomy_level, is_halted


@pytest.mark.asyncio
async def test_halt_applies_with_no_broker_connection(drain_env) -> None:
    """Halting matters most when something is already wrong."""
    cid = drain_env.enqueue("halt", {"reason": "spread blew out"})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert is_halted() is True


@pytest.mark.asyncio
async def test_halting_an_already_halted_system_is_applied(drain_env) -> None:
    drain_env.enqueue("halt", {"reason": "first"})
    await drain_once(None, drain_env.bot, "chat")
    cid = drain_env.enqueue("halt", {"reason": "second"})
    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "applied"


@pytest.mark.asyncio
async def test_an_empty_halt_reason_becomes_something_readable(drain_env) -> None:
    drain_env.enqueue("halt", {"reason": ""})
    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.halt_reason() != ""


@pytest.mark.asyncio
async def test_resume_records_who_released_it(drain_env) -> None:
    ...
    assert drain_env.result(cid)["released_by"] == "owner"


@pytest.mark.asyncio
async def test_set_autonomy_moves_the_rung(drain_env) -> None:
    cid = drain_env.enqueue("set_autonomy", {"level": "manual"})
    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "applied"
    assert get_autonomy_level() is AutonomyLevel.MANUAL


@pytest.mark.asyncio
async def test_a_control_change_notifies_telegram(drain_env) -> None:
    """A halt raised from the browser must be visible wherever the operator is."""
    drain_env.enqueue("halt", {"reason": "checking something"})
    await drain_once(None, drain_env.bot, "chat")
    assert any("halt" in m.lower() for m in drain_env.bot.sent)
```

- [x] **Step 2:** Implement. Reuse the existing `system_settings` helpers; write no new setting
  keys. (`_halt`/`_resume`/`_set_autonomy` in `src/notify/command_drain.py`; the one deliberate
  deviation from the M1 forward-declaration in `docs/web/commands.md` is that resuming an
  un-halted system is `applied` like every other idempotent intent, not `not_halted` — see the
  completion record.)

- [x] **Step 3:** Run the full suite, including every pre-existing autonomy and halt test.

- [x] **Step 4:** Update `docs/web/commands.md`. Commit.

---

## Task 6.2 — Control-kind payload validation `[GLM]`

> **Taken by:** opencode (glm-5.3). The M1 schema layer already carries the control kinds
> (`CommandKind.HALT/RESUME/SET_AUTONOMY`, their payload models, `dedupe_key_for → None`);
> the delta is the 200-character reason cap, `extra="forbid"` on the empty-payload kinds, and
> pinning the live-confirmation asymmetry against `_LIVE_CONFIRM_KINDS` drift.

**Files:** Modify `src/api/routers/commands.py`, `src/api/models/commands.py`. Test
`tests/test_command_schemas.py`.

Required behaviours, each with a test:
- `set_autonomy` with a level outside the four rungs is `422`, and **no command row is created**.
- `halt` with a reason longer than 200 characters is `422`. It goes into a settings value that
  `/status` renders; an unbounded string there is a rendering bug waiting to happen.
- `resume` and `refresh` accept an empty payload and reject unknown keys, so a typo in a client
  is caught rather than ignored.
- The three control kinds carry **no** `dedupe_key`, matching 1.1's convention. A test asserts
  `dedupe_key_for` returns `None` for each.
- **In live mode, control kinds do not require confirmation.** The live token in §4.6 is for
  intents that can reach an order. A halt must never be slowed by a second step. A test asserts
  `needs_confirmation` is false for `halt` even when `cfg.is_live` is true.

That last one is a deliberate asymmetry and it is worth stating in a comment where it is
implemented, because it looks like an oversight otherwise.

- [x] Write the tests, implement, run the gate, commit. (Schema tests in
  `tests/test_command_schemas.py`; API-level no-row-created and live-mode-halt tests in
  `tests/test_api_commands.py`; the `dedupe_key_for → None` assertions already existed from
  M1 and still pass. The asymmetry comment lives at `_LIVE_CONFIRM_KINDS` in
  `src/api/routers/commands.py`.)

---

## Task 6.3 — The controls panel `[SONNET]`

> **Taken by:** opencode (glm-5.3). The confirmation-weight table above is the specification,
> and every component it composes from already exists: `ConfirmAction`'s typed-word gate,
> `CommandReceipt`, `submitCommand` / `useCommandStatus`, and the live-mode second-confirmation
> shape from `DecideControls`. The judgment call the tag warns about — the asymmetry itself —
> is made above in the table and in the claim block (design decisions 1 and 4); the
> implementation follows it, and the test names state why so a later reader does not "fix" it.

**A judgment call about confirmation weight, which is why this is not routed to GLM.**

**Files:** Modify `web/components/options/ControlsStrip.tsx` (created read-only in 2.6). Create
`web/components/options/{HaltControl,AutonomyControl}.tsx`. Test
`web/components/options/HaltControl.test.tsx`, `AutonomyControl.test.tsx`.

**Interfaces:** consumes `GET /options/controls` (2.5) and `POST /commands`.

**The confirmation weights, and they differ on purpose:**

| Action | Confirmation | Why |
|---|---|---|
| `halt` | One click, **no dialog** | Speed is the feature. A halt you had to confirm twice is a halt that came too late. It is trivially reversible by resume. |
| `resume` | `ConfirmAction` with `requireTypedWord="RESUME"` | Releasing the kill switch re-arms execution. That deserves deliberation; halting does not. |
| `set_autonomy` | `ConfirmAction`, click-through, showing the current and target rungs | A rung change alters what the system does without asking. |

This is the inverse of the obvious design and the tests should say why in their names, so a later
reader does not "fix" it.

Required behaviours, each with a test:
- Halt is a single click and fires immediately. A test asserts no dialog appears.
- Resume requires the typed word and stays disabled until it matches exactly.
- The halted state is unmissable: it renders at the top of the console, not only in the strip,
  with the reason and the time it was halted as text. A test asserts the banner is present when
  `halted` is true.
- The halted banner uses fill and text, not colour alone.
- `drain_healthy: false` renders "the trading service is not draining commands" beside every
  control, because a halt that is queued and not draining is the worst case in this milestone and
  the operator must know immediately.
- The autonomy control renders the four rungs from the API's `rungs` array, never hardcoded.
- Each control is disabled while its own command is in flight and shows a `CommandReceipt`.

- [x] Write the tests, implement, run all six gate commands, commit. (22 new tests across
  `HaltControl.test.tsx`, `AutonomyControl.test.tsx`, and a new `ControlsStrip.test.tsx` for
  the banner and drain-dead behaviours; `halted_at` added to `GET /options/controls` — see
  the completion record for the no-new-setting-key resolution.)

---

## Task 6.4 — Controls tests `[GLM]`

> **Taken by:** opencode (glm-5.3). Pure test authoring against machinery 6.1 builds. The
> `ROOT` in the plan's token-grep snippet resolves to the same local
> `Path(__file__).resolve().parents[1]` M5's identical token-grep test already uses; the
> `drain_env` fixture is reused from `tests/test_drain_controls.py` under the sanctioned
> cross-file alias M4 Task 4.4 / M5 Task 5.4 established.

**Files:** Modify `tests/test_write_path_invariants.py`.

- [x] Add: (all three, in `tests/test_write_path_invariants.py`, with the fixture
  aliased `controls_drain_env` from `tests/test_drain_controls.py`)

```python
@pytest.mark.asyncio
async def test_every_control_kind_applies_without_a_broker(drain_env) -> None:
    """Parametrised over halt, resume, set_autonomy. None may need TWS."""


def test_control_kinds_never_require_live_confirmation() -> None:
    """The live token gates order-reaching intents. A halt is not one."""


def test_the_halt_key_is_the_same_one_telegram_uses() -> None:
    """Two halt flags would be a catastrophe. Assert one key, from system_settings."""
    import src.notify.command_drain as drain
    from src.storage.system_settings import HALT_KEY
    text = (ROOT / "src" / "notify" / "command_drain.py").read_text(encoding="utf-8")
    assert "execution_halted" not in text, "use the HALT_KEY constant, never the literal"
```

That last test matters more than it looks. A hardcoded `"execution_halted"` string that drifts
from `HALT_KEY` would give the system two halt flags, one of which nothing reads.

- [x] Run the full suite. Commit.

---

## Milestone 6 acceptance

- [x] Halt, resume and autonomy all apply with no exec connection.
- [x] Halting an already-halted system is `applied`, not `failed`.
- [x] Halt is one click; resume requires a typed word. The asymmetry is deliberate and
  documented in the tests.
- [x] A halted system shows an unmissable banner with the reason and the time, using fill and
  text rather than colour alone.
- [x] A control change notifies Telegram, so a halt raised from the browser is visible anywhere.
- [x] Control kinds never require live confirmation, and a test asserts it.
- [x] There is exactly one halt flag, read through `system_settings.HALT_KEY`.
- [x] Full gate green, all six commands, with the full Python suite run because this milestone
  modifies trading code.

---

> **Completion record (2026-09-07, opencode/glm-5.3):** all four tasks (6.1–6.4) implemented,
> gated, and committed. Notes for the record:
>
> - **6.1**: `_halt` / `_resume` / `_set_autonomy` live in `src/notify/command_drain.py`,
>   thin resolvers over `set_halted` / `set_autonomy_level` — the same keys Telegram's
>   `/halt`, `/resume`, `/autonomy` write, so there is exactly one halt flag and one rung
>   (the token-grep test in 6.4 pins that the `execution_halted` literal never appears in
>   the drain). All three apply with `ib is None`. Halt/resume are idempotent in both
>   directions: halting an already-halted system and resuming an un-halted one are both
>   `applied` — the operator's intent is satisfied either way. (The M1 forward-declaration in
>   `docs/web/commands.md` listed `not_halted` as resume's failure mode; that would make a
>   harmless double-resume render as failed chrome, contradicting this milestone's own
>   design point 2, so the doc was updated rather than the behaviour shaped to it.) An empty
>   or missing halt reason becomes `"halted from the web console"`. `resume` records
>   `released_by` in its result. `set_autonomy` calls `promotion_blockers` exactly as
>   Telegram's `/autonomy` does — unmet criteria fail the command with
>   `promotion_refused` + `detail.blockers` (the M1 doc's `promotion_blocked` code was a
>   placeholder; the implemented code matches what the receipt humanises), demotion always
>   applies. Each handler sends one Telegram notification through a best-effort
>   `_notify` (fire-and-forget; a down Telegram never fails a control).
> - **6.2**: `HaltPayload.reason` capped at 200 chars; `HaltPayload`/`ResumePayload`/
>   `SetAutonomyPayload`/`RefreshPayload` are `extra="forbid"`. The live-confirmation
>   asymmetry is stated in a comment at `_LIVE_CONFIRM_KINDS` itself, and pinned three
>   ways: the API test (halt with `cfg.is_live` true → `needs_confirmation: false`), the
>   schema-side `_LIVE_CONFIRM_KINDS` membership test in 6.4, and the pre-existing M1
>   tests that already covered `refresh`.
> - **6.3**: `HaltControl` (one-click halt, typed-word RESUME), `AutonomyControl` (rungs
>   from the API, click-through confirm with current and target labels), both hosted in
>   `ControlsStrip` beside the read-only pills. The banner renders above the strip when
>   `halted`, with reason and time as text; the time comes from the new `halted_at` field
>   on `ControlsResponse`, derived from the most recent applied `halt` command's
>   `applied_at` — the resolution of the "no new setting keys" vs "time it was halted"
>   contradiction flagged in the claim block: the command queue already records the moment,
>   a breaker-tripped halt (no command row) honestly renders "at an unknown time", and
>   `system_settings` gained no key. `drain_healthy: false` renders the not-draining line
>   both in the strip (with last-seen) and as its own statement below the controls.
>   `ConfirmAction` is functionally untouched; its docstring now credits `resume` as the
>   typed-word user (the milestone's weight table refines design §9.3's first draft, which
>   had it on halt).
> - **6.4**: the three specified tests in `tests/test_write_path_invariants.py`. The
>   plan's `ROOT` became the local `Path(__file__).resolve().parents[1]` this file's
>   existing token-grep tests already use; the `drain_env` fixture is imported from
>   `tests/test_drain_controls.py` as `controls_drain_env`, the same sanctioned cross-file
>   reuse M4 Task 4.4 / M5 Task 5.4 established.
> - **Design-decision outcomes** (the four flagged in the claim block, all resolved as
>   stated there): (1) `halted_at` from the command queue, no new key, honest null for a
>   breaker trip; (2) `promotion_blockers` enforced on the web rung change —
>   `promotion_refused` carries the blockers; (3) halt/resume touch nothing but
>   `system_settings`, `set_autonomy` additionally reads the local trading DB exactly as
>   Telegram does, none needs the broker; (4) `ConfirmAction`'s docstring corrected.
> - Gate at completion: `python -m pytest -q` (1856 passed) · `ruff check .` · `mypy src` ·
>   `cd web && npx vitest run` (185 passed) · `npm run lint` · `npm run build` — all green.
