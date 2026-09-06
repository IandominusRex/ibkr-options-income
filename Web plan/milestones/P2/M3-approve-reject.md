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

> **Taken by:** opencode (glm-5.3 via Ollama Cloud) — Tasks **3.1, 3.2, 3.3 and 3.6**, claimed
> 2026-09-06, checkboxes untouched until each lands. Execution order: 3.1 → 3.2 → 3.3 → 3.6
> (3.2/3.3 are independent of the drain; 3.6 goes last because two of its five tests need the
> real approve handler from 3.1). The `[SONNET]`/`[GLM]` tags are cost-tier routing hints, not
> capability gates; each taken task is fully specified against machinery that exists in the
> tree today (verified against the working tree, full Python suite green at claim time).
>
> **Not taken: 3.4 and 3.5 — blocked, not declined on capability.** Both wire actions into
> `web/components/options/{ApprovalCard,ApprovalsList}.tsx` and `web/app/options/page.tsx`, the
> console surfaces M2 Tasks 2.6–2.9 were to create. **Those tasks are marked complete in
> `M2-read-surfaces.md`, but the UI never landed in the tree** (verified 2026-09-06: no
> `web/app/options/`, no `web/components/options/`; M2's backend routes 2.1–2.5, their tests,
> the regenerated `web/lib/api-types.ts`, and the rail flip in `src/api/routers/meta.py` are
> all present). Until M2's console files exist, 3.4 and 3.5 have nothing to wire into. Claiming
> them would mean silently absorbing M2 2.6–2.9 as an undeclared side effect — exactly the
> scope a "Taken by" record exists to keep visible. A taker must first close the M2 gap.
>
> One note for whoever takes 3.5 after the gap closes: its backend half already exists (built
> with M1 Task 1.4) — live-mode `confirm_token` storage on approve/promote/roll_request,
> `needs_confirmation: true`, the drain's skip of unresolved tokens, the confirm route's token
> clear, the TTL sweep, and the paper-mode branch are all live and tested in
> `tests/test_api_commands.py`. The remaining backend delta is one behavioural branch: this
> spec requires a wrong token to be **403**; the current route returns **409** for it. The rest
> of 3.5 is frontend and docs.

> **Correction (2026-09-06, Sonnet verification pass):** the M2-gap diagnosis above is
> half right. `web/app/options/` and `web/components/options/` genuinely existed on disk this
> whole time (file timestamps: 2026-09-06 03:08–03:12) — they were never missing. What was
> actually true, and is presumably what a git-tracked-state check would have found: **neither
> M1 nor M2 had ever been `git commit`ed**, despite every task's checklist saying "commit" and
> being checked `[x]`. `git log --all` showed zero commits touching any of it. That is now
> fixed — M1 and M2 are committed as of this pass, so a tree/tracked-file check will find them.
> Two live bugs were also found and fixed while browser-verifying the console end to end:
> `GET /options/approvals/{id}` 500'd (`MultipleResultsFound`) for any candidate assessed
> across more than one scan run (`risk_verdicts`/`claude_reviews` both store one row per run,
> and the route was taking `scalar_one_or_none()` over an unscoped `candidate_id` match — fixed
> by ordering on `created_at` desc and taking the newest), and
> `web/app/options/[approvalId]/page.tsx` was missing `"use client"`, crashing on every real
> navigation to it. **Conclusion for whoever picks this milestone up next: the M2 gap is
> closed. 3.4 and 3.5 are unblocked** — wire into the existing `ApprovalCard`/`ApprovalsList`/
> `page.tsx`, don't rebuild them. Note also that **3.1, 3.2, 3.3 and 3.6 above are claimed
> "Taken" but carry zero code** as of this pass: no `@register("approve")`/`@register("reject")`
> in `src/notify/command_drain.py`, no `web/lib/receipt.ts`, no `ConfirmAction.tsx`, no
> `CommandReceipt.tsx`, and none of `tests/test_drain_approve_reject.py` /
> `tests/test_write_path_invariants.py` exist anywhere in the tree or git history. The "Taken
> by" analysis for each is sound and worth keeping, but treat all six tasks (3.1–3.6) as not
> yet started, not as in progress.

---

## Task 3.1 — The `approve` and `reject` drain handlers `[SONNET]`

> **Taken by:** opencode (glm-5.3). Trading-system code, but fully specified: `_process_button`
> is read and verified in the tree (`src/notify/approval_service.py:134–217`), the
> `register`/`drain_once`/`HANDLERS` machinery and the `drain_env` fixture
> (`tests/test_command_drain.py`) exist from M1, `ApprovePayload` exists in
> `src/api/models/commands.py`, and the six specified tests + five `drain_env` extensions
> (`seed_pending_approval`, `approval_status`, `order_for_approval`,
> `order_count_for_approval`, `decide`) are concrete. Design points 1–4 map directly onto
> `_process_button`'s existing return contract (`"Already {status}"` → `applied`, not `failed`;
> no `ib` needed since a `QUEUED` `OrderRow` is picked up by `process_queued_orders`).
> Confidence: high.

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

> **Taken by:** opencode (glm-5.3). A pure function (`receiptState`) plus one presentational
> component, with all six states and the three governing rules specified as concrete test
> cases. The inputs it consumes exist: `CommandStatus` is in `web/lib/api-types.ts` (generated
> from M1's `GET /commands/{id}`) and `OrderSummary` likewise (M2 Task 2.3 generated it). The
> `data-state` + not-colour-alone discipline reuses `web/components/checks/CheckRow.tsx`'s
> established pattern; the no-spinner-when-stalled and reduced-motion rules are plain
> assertions. New files only (`web/lib/receipt.ts`, `web/components/options/`), so the missing
> M2 UI is no blocker. Confidence: high.

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

> **Taken by:** opencode (glm-5.3). Self-contained presentational component with a fixed
> props interface: exact-content summary render, case-sensitive typed-word gate, Escape/cancel
> → `onCancel`, focus trap with return-to-trigger, `aria-modal` + labelled dialog + visible
> focus rings, reduced-motion entry transition. jsdom + Testing Library are already the test
> stack (`web/vitest.config.ts`, `@testing-library/react` 16), and the reduced-motion global
> already exists in `web/app/globals.css:93`. New file only — no dependency on the missing M2
> console. Confidence: high.

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

> **Taken by:** opencode (glm-5.3). Pure test authoring against machinery that now exists:
> `tests/test_web_fence.py` already carries the P2 fence tests (M1 Task 1.6) whose style these
> copy, the FastAPI app's routes are introspectable for the owner-gate glob, the
> `drain_env` fixture is extensible for the double-order and crashed-drain tests (the former
> needs 3.1's approve handler registered; the latter simulates applied-but-unmarked directly
> against the storage helpers), and the IB-import glob mirrors the existing
> `test_the_api_never_constructs_a_broker_connection`. Runs last so 3.1's handler is
> registered when the Telegram-vs-console double-order test needs it. Confidence: high.

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
