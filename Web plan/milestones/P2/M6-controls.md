# Milestone 6 — Controls

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Halt, resume and the autonomy rung reachable from the browser.

**Spec:** `Web plan/P2-design.md` §6.4, §9.3. **Index:** `Web plan/P2-IMPLEMENTATION-PLAN.md`.
**Depends on:** Milestone 5.

**The asymmetry that shapes this milestone:** halting when you did not mean to costs you some
missed premium. Failing to halt when you meant to can cost a great deal more. So the halt path is
built to be fast and hard to miss, and the resume path is built to be deliberate. They are not
mirror images and should not be implemented as one toggle.

---

## Task 6.1 — The `halt`, `resume` and `set_autonomy` handlers `[SONNET]`

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

- [ ] **Step 1: Write the failing test**

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

- [ ] **Step 2:** Implement. Reuse the existing `system_settings` helpers; write no new setting
  keys.

- [ ] **Step 3:** Run the full suite, including every pre-existing autonomy and halt test.

- [ ] **Step 4:** Update `docs/web/commands.md`. Commit.

---

## Task 6.2 — Control-kind payload validation `[GLM]`

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

- [ ] Write the tests, implement, run the gate, commit.

---

## Task 6.3 — The controls panel `[SONNET]`

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

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Task 6.4 — Controls tests `[GLM]`

**Files:** Modify `tests/test_write_path_invariants.py`.

- [ ] Add:

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

- [ ] Run the full suite. Commit.

---

## Milestone 6 acceptance

- [ ] Halt, resume and autonomy all apply with no exec connection.
- [ ] Halting an already-halted system is `applied`, not `failed`.
- [ ] Halt is one click; resume requires a typed word. The asymmetry is deliberate and
  documented in the tests.
- [ ] A halted system shows an unmissable banner with the reason and the time, using fill and
  text rather than colour alone.
- [ ] A control change notifies Telegram, so a halt raised from the browser is visible anywhere.
- [ ] Control kinds never require live confirmation, and a test asserts it.
- [ ] There is exactly one halt flag, read through `system_settings.HALT_KEY`.
- [ ] Full gate green, all six commands, with the full Python suite run because this milestone
  modifies trading code.
