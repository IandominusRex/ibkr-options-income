# Milestone 3 — Approve and Reject

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The first web action that can cause an order to exist. After this milestone the console
does the Telegram Approve/Reject buttons' job, through the same code path, with a receipt that
never overstates what happened.

**Spec:** `Web plan/P2-design.md` §4.5 (idempotency), §4.6 (live confirmation), §6.1, §9.2 (the
command receipt), §9.3 (confirmation). **Index:** `Web plan/P2-IMPLEMENTATION-PLAN.md`.
**Depends on:** Milestone 2.

**This is the milestone with teeth.** Read `_process_button` (`approval_service.py:132–216`) in
full before starting, and do not reimplement one line of it.

---

## Task 3.1 — The `approve` and `reject` drain handlers `[SONNET]`

**Trading-system code, and the core safety property of the entire phase.**

**Context.** `_process_button(approval_id, action)` already does everything: the idempotency
guard on non-`PENDING` status, the `has_active_order` check, the `N2a` snapshot copy onto the
`OrderRow`, the `record_outcome(USER_REJECTED)` call, and the `IntegrityError` catch for a
concurrent duplicate. It returns `(found, decision_text, candidate_short)`.

**The handler calls it. The handler does not reimplement it.** If a future refactor makes the web
path diverge from the Telegram path, every safety property tested against Telegram silently stops
covering the web.

**Files:** Modify `src/notify/command_drain.py`. Test `tests/test_drain_approve_reject.py`.

**Interfaces:**

```python
@register("approve")
def _approve(*, command: AppCommandRow, ib: IB | None, **_) -> dict:
    """Apply an approve intent by calling _process_button unchanged.

    Returns the result dict stored on the command. Raises to fail the command.
    """
    payload = ApprovePayload(**command.payload)
    found, decision_text, _ = _process_button(payload.approval_id, "approve")
    if not found:
        raise CommandFailed("approval_not_found")
    return {"decision": decision_text, "approval_id": payload.approval_id}


@register("reject")
def _reject(...) -> dict:   # identical shape, action="reject"
```

**Design points that are not negotiable:**

1. `_process_button` is imported and called. No copied logic, no parallel implementation.
2. **An already-decided approval is not a failure.** `_process_button` returns
   `"Already approved"` and mutates nothing. The command is marked **`applied`** with that text
   in `result`, because the intent's goal — this approval is decided — is satisfied. Marking it
   `failed` would make a normal race look like a malfunction.
3. **Neither handler needs `ib`.** A reject with TWS down must still apply. So must an approve:
   it creates a `QUEUED` `OrderRow`, and `process_queued_orders` picks it up when the exec
   connection returns, which is existing behaviour.
4. The handler sends no Telegram message. Notification stays with the existing order poll loop,
   which already reports fills. Two notification paths for one order is how duplicates start.

- [ ] **Step 1: Write the failing test**

```python
"""The web approve is the Telegram approve. Same function, same guarantees."""

from __future__ import annotations

import pytest

from src.common.schemas import ApprovalStatus, OrderState


@pytest.mark.asyncio
async def test_approve_creates_a_queued_order_from_the_frozen_snapshot(drain_env) -> None:
    approval_id = drain_env.seed_pending_approval("NVDA", snapshot={"contracts": 2})
    cid = drain_env.enqueue("approve", {"approval_id": approval_id})

    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert drain_env.approval_status(approval_id) == ApprovalStatus.APPROVED
    order = drain_env.order_for_approval(approval_id)
    assert order.state == OrderState.QUEUED
    assert order.snapshot == {"contracts": 2}   # N2a: the payload the human was shown


@pytest.mark.asyncio
async def test_the_handler_calls_process_button_rather_than_reimplementing_it(
    drain_env, monkeypatch
) -> None:
    """A refactor must not be able to fork the mutation without this test failing."""
    calls = []
    import src.notify.command_drain as drain

    real = drain._process_button
    monkeypatch.setattr(
        drain, "_process_button",
        lambda aid, action: (calls.append((aid, action)), real(aid, action))[1],
    )
    approval_id = drain_env.seed_pending_approval("NVDA")
    drain_env.enqueue("approve", {"approval_id": approval_id})
    await drain_once(None, drain_env.bot, "chat")

    assert calls == [(approval_id, "approve")]


@pytest.mark.asyncio
async def test_an_already_decided_approval_applies_neutrally(drain_env) -> None:
    """Telegram got there first. That is a normal race, not a malfunction."""
    approval_id = drain_env.seed_pending_approval("NVDA")
    drain_env.decide(approval_id, ApprovalStatus.APPROVED)
    cid = drain_env.enqueue("approve", {"approval_id": approval_id})

    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert "Already" in drain_env.result(cid)["decision"]


@pytest.mark.asyncio
async def test_a_replayed_drain_creates_no_second_order(drain_env) -> None:
    approval_id = drain_env.seed_pending_approval("NVDA")
    drain_env.enqueue("approve", {"approval_id": approval_id})
    await drain_once(None, drain_env.bot, "chat")
    drain_env.reset_to_pending_without_touching_the_approval()
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.order_count_for_approval(approval_id) == 1


@pytest.mark.asyncio
async def test_approve_applies_with_no_exec_connection(drain_env) -> None:
    """TWS down queues the order. It does not lose the decision."""
    approval_id = drain_env.seed_pending_approval("NVDA")
    cid = drain_env.enqueue("approve", {"approval_id": approval_id})
    await drain_once(None, drain_env.bot, "chat")   # ib is None
    assert drain_env.status(cid) == "applied"
    assert drain_env.order_for_approval(approval_id).state == OrderState.QUEUED


@pytest.mark.asyncio
async def test_reject_records_the_outcome(drain_env) -> None:
    approval_id = drain_env.seed_pending_approval("NVDA")
    cid = drain_env.enqueue("reject", {"approval_id": approval_id})
    await drain_once(None, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    assert drain_env.approval_status(approval_id) == ApprovalStatus.REJECTED
    assert drain_env.order_for_approval(approval_id) is None


@pytest.mark.asyncio
async def test_an_unknown_approval_id_fails_the_command(drain_env) -> None:
    cid = drain_env.enqueue("approve", {"approval_id": 999999})
    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "approval_not_found"
```

Extend M1's `drain_env` fixture with `seed_pending_approval`, `approval_status`,
`order_for_approval`, `order_count_for_approval` and `decide`.

- [ ] **Step 2: Implement** both handlers.

- [ ] **Step 3: Run the full suite.** This modifies the process that places orders. Every
  pre-existing `approval_service`, `execution` and `sender` test must still pass.

- [ ] **Step 4:** Update `docs/web/commands.md`'s `approve` and `reject` sections with the
  already-decided behaviour and the TWS-down behaviour. Commit.

---

## Task 3.2 — The command receipt component `[SONNET]`

**The signature component of P2**, and the one that enforces the phase's most important UI rule.

**Spec §9.2.** Read it before writing the component.

**Files:** Create `web/components/options/{CommandReceipt,ReceiptState}.tsx`,
`web/lib/receipt.ts`. Test `web/components/options/CommandReceipt.test.tsx`,
`web/lib/receipt.test.ts`.

**Interfaces:**

```ts
export type ReceiptState =
  | "queued"      // command pending, drain has not applied it
  | "applied"     // the approval was mutated
  | "submitted"   // an order is working at the broker
  | "filled"      // a fill exists
  | "failed"      // the command failed, with a reason
  | "stalled";    // pending, and the drain is not healthy

export function receiptState(
  command: CommandStatus,
  order: OrderSummary | null,
  drainHealthy: boolean,
): ReceiptState;
```

**The three rules, each with its own test:**

1. **`pending` never renders as `applied`.** `receiptState` returns `"queued"` for a pending
   command regardless of anything else, and `"stalled"` when the command is pending and
   `drainHealthy` is false. The rendered text differs, the `data-state` attribute differs, and
   the states are not distinguished by colour alone.
2. **Never claim a trade happened until `OrderRow` says so.** `"submitted"` requires an order in
   a working state. `"filled"` requires `filled_qty > 0`. `receiptState` must not infer either
   from the command alone. A test passes an `applied` command with `order: null` and asserts the
   result is `"applied"`, not `"submitted"`.
3. **A stalled drain is stated in words.** The `"stalled"` state renders "the trading service is
   not draining commands", not a spinner. A test asserts the string is present and that no
   element with `role="progressbar"` is rendered in that state.

Also required:
- Every receipt shows its intent id, so an operator can ask about a specific command.
- `"failed"` renders the reason from `result.reason`, humanised, plus any `result.detail`
  reason codes.
- Reduced motion disables the state transition animation.

- [ ] **Step 1:** Write `web/lib/receipt.test.ts` as a table covering all six states plus the
  three rules above. This is a pure function, so test it exhaustively before the component.

- [ ] **Step 2:** Implement `receiptState`, then the component.

- [ ] **Step 3:** Write the component test, including the no-spinner-when-stalled assertion.

- [ ] **Step 4:** Run all six gate commands. Commit.

---

## Task 3.3 — The confirmation dialog `[GLM]`

**Files:** Create `web/components/options/ConfirmAction.tsx`. Test
`web/components/options/ConfirmAction.test.tsx`.

**Interfaces:**

```ts
type ConfirmActionProps = {
  title: string;
  summary: React.ReactNode;      // the exact contract and contract count
  confirmLabel: string;
  requireTypedWord?: string;     // when set, the confirm stays disabled until typed exactly
  onConfirm: () => void;
  onCancel: () => void;
};
```

Required behaviours, each with a test:
- The dialog shows the exact contract and contract count. A test asserts the summary content is
  rendered, not summarised away.
- With `requireTypedWord`, the confirm control is disabled until the word matches **exactly**,
  case-sensitive. Used by `halt` in M6.
- Escape and the cancel control both call `onCancel`. Focus is trapped while open and returns to
  the trigger on close.
- `aria-modal`, a labelled dialog, and a visible focus ring on every control.
- Reduced motion disables the entry transition.

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Task 3.4 — Wire approve and reject into the console `[GLM]`

**Files:** Modify `web/components/options/{ApprovalCard,ApprovalsList}.tsx`,
`web/app/options/page.tsx`, `web/app/options/[approvalId]/page.tsx`. Create
`web/lib/commands.ts`. Test `web/components/options/ApprovalCard.test.tsx`.

**Interfaces:**

```ts
// web/lib/commands.ts
export async function submitCommand(kind: string, payload: unknown): Promise<CommandStatus>;
export function useCommandStatus(id: number | null): UseQueryResult<CommandStatus>;
```

Required behaviours, each with a test:
- Approve and Reject open `ConfirmAction` (3.3) before any request is made.
- On confirm, `POST /commands` is called once, and the returned id drives a `CommandReceipt`
  (3.2) rendered on the card.
- `useCommandStatus` polls `GET /commands/{id}` **every 2 seconds while pending**, and stops
  polling once the command reaches a terminal state. A test asserts polling stops.
- The card's action controls are disabled while a command for that approval is in flight, so a
  second click cannot fire. The dedupe key covers it server-side, but the UI should not rely on
  the server to prevent an obvious double-submit.
- An approval that is no longer pending renders its decision, not action controls.
- A `403` renders a permission message, not a generic failure.

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Task 3.5 — Live-mode second confirmation `[SONNET]`

**A safety gate. It must fail closed.** Spec §4.6.

**Context.** `LIVE_TRADING=true` already forces a second confirmation before an order transmits,
via `register_live_confirm` / `resolve_live_confirm` and the `[CONFIRM LIVE]` Telegram button.
That path is untouched by this task and still fires. This task adds a **separate, earlier**
confirmation so the web cannot queue a live order in one click.

**Files:** Modify `src/api/routers/commands.py`, `src/api/commands.py`,
`src/notify/command_drain.py`, `web/components/options/ApprovalCard.tsx`,
`docs/web/commands.md`. Test `tests/test_live_confirmation.py`.

**Interfaces:** `POST /commands/{id}/confirm` with `{confirm_token}`, defined in Task 1.4.

Required behaviours, each with a test:
- **In live mode**, a `POST /commands` for `approve`, `promote` or `roll_request` stores a
  `confirm_token` and returns `needs_confirmation: true`.
- **The drain skips a command with an unresolved `confirm_token`**, leaving it `pending` and not
  counting it as processed. Asserted directly against the drain, not through the UI. This is the
  fail-closed property: if the confirm route were broken, nothing executes.
- `POST /commands/{id}/confirm` with the right token clears it; the next drain applies the
  command.
- A wrong token is `403` and does **not** clear the field. A test asserts the command is still
  pending afterwards.
- Confirming a command that is not awaiting confirmation is `409`.
- The token expires with `approval.ttl_minutes`; an expired command is swept to `expired`, never
  applied. A test moves the clock forward and asserts it.
- **In paper mode** no token is stored and the drain applies normally. Assert both branches by
  monkeypatching `cfg.is_live`.
- The frontend renders the live confirmation as a **distinct, clearly labelled second step**, not
  a repeat of the first dialog. A test asserts the live copy differs from the paper copy.

- [ ] Write the tests, implement, run the full suite, update `docs/web/commands.md` with the
  live-mode flow as an ordered list an operator can follow, commit.

---

## Task 3.6 — The write-path test suite `[SONNET]`

**Files:** Create `tests/test_write_path_invariants.py`. Modify `tests/test_web_fence.py`.

This task exists so the invariants are asserted in one findable place rather than scattered.
Several assertions overlap earlier tasks deliberately: an invariant with one test has one point
of failure.

- [ ] Write these:

```python
def test_every_options_route_requires_owner() -> None:
    """Globbed, not listed: a new route must not be able to ship ungated."""
    # Introspect the FastAPI app's routes under /options and /commands, and assert every
    # one has require_owner in its dependency chain.


def test_no_route_module_imports_the_command_engine() -> None:
    """Routes hold the read-only session. Only src/api/commands.py may write."""


@pytest.mark.asyncio
async def test_telegram_and_the_console_cannot_double_order(drain_env) -> None:
    """Both surfaces decide the same approval. Exactly one order exists."""


@pytest.mark.asyncio
async def test_a_crashed_drain_reapplies_exactly_once(drain_env) -> None:
    """Simulate: handler applied, process died before mark_applied. Retry is absorbed."""


def test_the_api_still_holds_no_broker_connection() -> None:
    """P2 adds a write path. It must not have added an IB import along the way."""
```

- [ ] Run the full suite. Every one of these must pass without weakening an earlier test.
  Commit.

---

## Milestone 3 acceptance

- [ ] Approving from the console creates a `QUEUED` `OrderRow` carrying the frozen snapshot, via
  `_process_button` and no other code.
- [ ] A test fails if a future refactor stops calling `_process_button`.
- [ ] Deciding the same approval in Telegram and the console produces exactly one order, and the
  losing surface reports it neutrally.
- [ ] A replayed drain creates no second order.
- [ ] In live mode, an unconfirmed order-reaching command is **skipped**, and the existing
  execution-time `[CONFIRM LIVE]` path still fires afterwards.
- [ ] A pending command never renders as applied, and a stalled drain is stated in words with no
  spinner.
- [ ] The UI claims `submitted` only when an order is working, and `filled` only when a fill
  exists.
- [ ] Every `/options/*` and `/commands` route is owner-gated, asserted by a globbed test.
- [ ] Full gate green, all six commands, with the full Python suite run because this milestone
  modifies trading code.
