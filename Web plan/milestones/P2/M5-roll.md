# Milestone 5 — Roll On Demand

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The operator can ask the system to propose a roll for any open short, without waiting
for the intraday monitor to fire an alert.

**Spec:** `Web plan/P2-design.md` §6.3. **Index:** `Web plan/P2-IMPLEMENTATION-PLAN.md`.
**Depends on:** Milestone 4.

**This is the smallest write milestone**, because `queue_roll_for_approval`
(`src/execution/roll_pipeline.py:37`) already does the entire job. Read that file first. The
handler fetches a chain and calls it. If you are writing roll logic, you have taken the wrong
approach.

**Two steps, never one.** The console asks the system to propose a roll; the operator then
approves that proposal through M3's path. There is no button that rolls a position.

> **Taken by:** opencode (glm-5.2 via Ollama Cloud) — **all four tasks, 5.1 through 5.4**, now
> complete (see the completion record at the bottom of this file for per-task notes, the two
> design decisions worth flagging, and the gate counts). The `[SONNET]`/`[GLM]` tags are
> cost-tier routing hints, not capability gates — same convention M1/M2/M3 used, where opencode
> took every task regardless of tag. All four tasks are honestly within reach here:
>
> - **5.1** is trading-system code, but `queue_roll_for_approval` already does the entire job and
>   the monitor's `_try_queue_roll` already composes the fetch — the handler is a thin resolver
>   that delegates to both, plus a `has_active_order` pre-check the milestone itself specifies.
>   Same shape as the promote handler already in `command_drain.py`.
> - **5.2** mirrors `AssessedRow`'s promote control exactly (`ConfirmAction` → `submitCommand`
>   → `CommandReceipt` → link); the receipt components and decide-flow already exist from M3/M4.
> - **5.3** adds two fields to `RollAlertSummary` and moves the trigger humaniser to a shared
>   home (the one mapping, no second copy); the alert rows already come back on `GET /options/shorts`.
> - **5.4** is pure test authoring against machinery 5.1 builds; the three test bodies are
>   concrete and the invariant they pin is the milestone's own design point.
>
> **One design decision worth flagging up front (see the completion record for the rest).** The
> milestone's headline test — "a monitor alert and a web request produce exactly one approval" —
> cannot be satisfied by `has_active_order` alone, because `has_active_order` only sees `OrderRow`s
> and the monitor's roll raises a **PENDING** `ApprovalRow` (no order until the operator approves
> it). The handler therefore disambiguates the pipeline's `None` against *both* an active order and
> an existing PENDING approval for the same deterministic candidate id, mapping either to
> `roll_already_working` with `detail.approval_id` so the receipt can link to the in-flight
> proposal. This stays inside the five reasons in the table below (a PENDING proposal is "a roll
> already in flight for this position"), adds no economic bound, and is the only reading under
> which the milestone's own acceptance criterion holds. Documented in `docs/web/commands.md`.

---

## Task 5.1 — The `roll_request` drain handler `[SONNET]`

> **Taken by:** opencode (glm-5.2). Trading-system code, but `queue_roll_for_approval`
> (`src/execution/roll_pipeline.py:37`) is read and verified in the tree, the drain's
> `register`/`drain_once`/`HANDLERS` machinery and the `drain_env`/`fake_chain` fixture pattern
> exist from M3/M4 (`tests/test_drain_approve_reject.py`, `tests/test_drain_promote.py`), the
> monitor's `_try_queue_roll` (`src/monitor/intraday.py:150`) is the existing chain-fetch
> composition the handler must reuse, and `RollRequestPayload` + its dedupe key + its live-mode
> confirm-token membership (`_LIVE_CONFIRM_KINDS`) already exist from M1. The five reasons in the
> table below are concrete and the seven specified tests + the two extra distinguishable-outcome
> tests (chain fetch failure, position not found) write directly against that fixture pattern.

**Trading-system code.** It reaches the broker and raises an approval.

**Context.** `queue_roll_for_approval(position, quotes, iv_stats, tech_stats, *, chat_id,
ttl_minutes)` already runs `generate_roll_candidates(..., defensive=True)`, takes the best by
ROC, checks `has_active_order`, upserts the `CandidateRow`, and raises a `PENDING` `ApprovalRow`
with the frozen snapshot. It returns `(approval_id, candidate)` or `None`, and never raises.

The monitor calls it today after its own chain fetch. The handler does the same fetch and the
same call.

**Files:** Modify `src/notify/command_drain.py`. Modify `docs/web/commands.md`. Test
`tests/test_drain_roll.py`.

**Interfaces:**

```python
@register("roll_request")
async def _roll_request(*, command, ib, bot, chat_id, **_) -> dict:
    """Ask the system to propose a roll for one open short.

    Fetches the chain for the underlying, then calls queue_roll_for_approval unchanged.
    Returns {"approval_id": int, "candidate_id": str} on success.
    """
```

**The handler's algorithm, in order:**

1. If `ib is None`, fail with `broker_unavailable`.
2. Resolve `payload.position_symbol` to a live `PositionSnapshot`. If it is not an open short,
   fail with `not_an_open_short`. If it is not held at all, fail with `position_not_found`.
3. Fetch the chain for the underlying, plus `IVStats` and `TechnicalStats`, using the same
   helpers the intraday monitor uses. Do not build a second chain-fetch path.
4. Call `queue_roll_for_approval`.
5. `None` back means either no qualifying roll or an already-active order. **Distinguish them**,
   because they mean very different things to an operator:

| Situation | `reason` | What the operator should read |
|---|---|---|
| `ib is None` | `broker_unavailable` | The system cannot price a roll right now. |
| Not an open short | `not_an_open_short` | Rolls apply to short options only. |
| Chain fetch failed | `chain_unavailable` | Try again; the provider's message is attached. |
| `generate_roll_candidates` returned nothing | `no_qualifying_roll` | No roll clears `max_debit` / `min_delta_reduction`. This is a real answer. |
| An order is already active | `roll_already_working` | A roll is already in flight for this position. |

  `queue_roll_for_approval` currently returns `None` for both of the last two. Check
  `has_active_order` in the handler **before** calling it so the two cases are separable, rather
  than changing the pipeline's return type.

**Design points that are not negotiable:**

1. **`rolling.py`'s `max_debit` and `min_delta_reduction` remain the roll's economic control.**
   `CLAUDE.md` is explicit that rolls are scoped out of the ROC, annualized-yield and
   `min_credit` gates precisely because a defensive roll deliberately pays under fair value. The
   handler adds no bounds of its own and relaxes none.
2. **The approval is `PENDING`.** The console proposes; the operator approves.
3. `defensive=True`, matching the monitor. The web does not get a different roll policy from the
   alert path.
4. A `no_qualifying_roll` outcome is a correct answer rendered as one, not an error.

- [ ] **Step 1: Write the failing test**

```python
"""A roll request proposes. It never rolls."""

from __future__ import annotations

import pytest

from src.common.schemas import ApprovalStatus


@pytest.mark.asyncio
async def test_a_roll_request_raises_a_pending_approval(drain_env, fake_chain) -> None:
    drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA", delta=-0.45, dte=9)
    fake_chain.will_offer_roll("NVDA", strike=175.0, dte=44, credit=0.35)
    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})

    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    approval_id = drain_env.result(cid)["approval_id"]
    assert drain_env.approval_status(approval_id) == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_a_roll_request_never_places_an_order(drain_env, fake_chain) -> None:
    """Two steps, always. The console proposes; the operator approves."""
    ...
    assert drain_env.order_for_approval(approval_id) is None


@pytest.mark.asyncio
async def test_no_qualifying_roll_is_a_real_answer(drain_env, fake_chain) -> None:
    drain_env.seed_short("NVDA  261017C00180000", underlying="NVDA")
    fake_chain.will_offer_no_roll("NVDA")
    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "no_qualifying_roll"


@pytest.mark.asyncio
async def test_an_already_working_roll_is_distinguished(drain_env, fake_chain) -> None:
    """'A roll is already in flight' and 'no roll qualifies' are different answers."""
    ...
    assert drain_env.result(cid)["reason"] == "roll_already_working"


@pytest.mark.asyncio
async def test_a_long_position_is_refused(drain_env) -> None:
    drain_env.seed_long("NVDA  261017C00180000")
    cid = drain_env.enqueue("roll_request", {"position_symbol": "NVDA  261017C00180000"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")
    assert drain_env.result(cid)["reason"] == "not_an_open_short"


@pytest.mark.asyncio
async def test_a_roll_request_with_no_broker_fails_honestly(drain_env) -> None:
    ...
    assert drain_env.result(cid)["reason"] == "broker_unavailable"


@pytest.mark.asyncio
async def test_a_monitor_alert_and_a_web_request_produce_one_approval(drain_env, fake_chain):
    """The monitor fires for the same position while a request is queued. One approval."""
    ...
    assert drain_env.pending_approval_count(underlying="NVDA") == 1
```

That last test is the one that matters most. The intraday monitor already calls
`queue_roll_for_approval` on its own schedule; a web request must not be able to race it into two
approvals for the same position. `has_active_order` plus the deterministic `candidate_id` is what
prevents it, and this test is what proves it.

- [ ] **Step 2: Implement.** Reuse the monitor's chain-fetch helper; do not write a second one.

- [ ] **Step 3: Run the full suite**, including every pre-existing monitor, roll-pipeline and
  roll-executor test.

- [ ] **Step 4:** Update `docs/web/commands.md` with the reason table verbatim. Commit.

---

## Task 5.2 — The roll action on the shorts list `[GLM]`

> **Taken by:** opencode (glm-5.2). The decide-flow primitives all exist from M3/M4:
> `ConfirmAction`, `CommandReceipt`, `submitCommand`/`useCommandStatus`, and the live-mode second
> confirmation. The shape to mirror is `web/components/options/AssessedRow.tsx` (M4 Task 4.3's
> promote control) — extract a `ShortsRow` that renders the table row plus the
> confirm-then-submit-then-receipt flow, the same way `AssessedRow` was extracted from
> `AssessedBrowser`. `CommandReceipt` gains one optional prop (`plainReasons`) so `no_qualifying_roll`
> renders as a plain sentence instead of red failed chrome — default absent, so every existing
> receipt test stays green. The M2-era "asserts no roll button exists" guard in
> `ShortsTable.test.tsx` evolves the same way M3's no-approve-button guard did: into "the roll
> control exists and is wired through the confirm gate".

**Files:** Modify `web/components/options/ShortsTable.tsx`. Test
`web/components/options/ShortsTable.test.tsx`.

**Interfaces:** consumes `POST /commands` with `kind: "roll_request"`, plus M3's
`CommandReceipt` and `ConfirmAction`.

Required behaviours, each with a test:
- A Roll control renders on every open short row.
- **Its label says what it does.** "Propose a roll", not "Roll". The button does not roll the
  position, and the copy must not imply it does. This is client rule 3 applied to a verb.
- The confirmation dialog states plainly that the system will price a roll and raise it for
  approval, and that nothing executes until that approval is approved.
- The receipt renders `no_qualifying_roll` as a plain sentence, not an error state with red
  chrome. It is a legitimate answer.
- `roll_already_working` links to the existing approval.
- On success the receipt links to the new approval.
- The control is disabled while a roll command for that position is in flight.

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Task 5.3 — Roll alerts on the shorts list `[GLM]`

> **Taken by:** opencode (glm-5.2). `RollAlertRow` already carries `claude_recommendation`
> (`src/storage/models.py:292`) and `GET /options/shorts` already returns alerts (M2 Task 2.4);
> the delta is two new fields on `RollAlertSummary` (`trigger_label`, `claude_recommendation`) and
> moving `_TRIGGER_LABELS`/`_humanize_trigger` out of `src/notify/formatters.py` into
> `src/monitor/triggers.py` (where the trigger codes are defined) so the API router and the
> Telegram formatter import the one mapping — no second copy, no notify-layer import from the API
> (the heartbeat-key precedent in `src/api/routers/options.py` already established that the API
> must not pull in the notify layer). The web renders `trigger_label` verbatim; the humaniser
> correctness is a Python-side test. `relativeAge` already exists in `web/lib/format.ts` for the
> alert age.

**Files:** Modify `web/components/options/ShortsTable.tsx`, and
`src/api/routers/options.py` if `alerts` needs more fields than 2.4 shipped. Test
`web/components/options/ShortsTable.test.tsx`.

**Context.** `RollAlertRow` carries `trigger`, `detail`, `claude_recommendation` and a `payload`.
The monitor writes one per fired trigger. 2.4 already returns them on the shorts route.

Required behaviours, each with a test:
- A fired alert renders on its position's row with the humanised trigger, using the same
  humaniser `formatters.py::_humanize_trigger` uses. Do not write a second mapping; if it needs
  to be shared, move it somewhere both can import rather than copying it.
- `claude_recommendation` renders labelled as a model opinion, distinct from any deterministic
  number on the row. Enrichment must look like enrichment.
- A position with no alerts renders nothing extra, not "No alerts".
- The alert's age renders as text, not a dot.

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Task 5.4 — Roll degradation tests `[SONNET]`

> **Taken by:** opencode (glm-5.2). Pure test authoring against machinery 5.1 builds. The three
> test bodies are concrete: a source-scan + behavioral tripwire proving the handler never reaches
> `execute_roll` directly; the verbatim token grep proving no roll economics leaked into
> `command_drain.py`; and a `wraps`-spy on `generate_roll_candidates` proving `defensive=True`
> flows through both the handler's own pre-check call and the pipeline's internal call (the web
> roll is the monitor's roll). Reuses the `drain_env`/`fake_chain` fixtures from
> `tests/test_drain_roll.py` the same sanctioned way `tests/test_write_path_invariants.py` already
> imports the promote fixtures from `tests/test_drain_promote.py` (documented exception to the
> no-shared-fixtures convention, M4 Task 4.4).

**Files:** Modify `tests/test_write_path_invariants.py`.

- [ ] Add:

```python
@pytest.mark.asyncio
async def test_a_roll_request_never_reaches_execute_roll_directly() -> None:
    """The console proposes. Only an approved OrderRow reaches execute_roll."""


def test_the_roll_handler_adds_no_economic_bounds_of_its_own() -> None:
    """max_debit and min_delta_reduction live in rolling.py. The handler must not
    reimplement, tighten, or relax them."""
    text = (ROOT / "src" / "notify" / "command_drain.py").read_text(encoding="utf-8")
    for token in ("max_debit", "min_delta_reduction", "roc_pct"):
        assert token not in text, f"roll economics leaked into the drain: {token}"


@pytest.mark.asyncio
async def test_the_web_and_the_monitor_share_one_roll_policy() -> None:
    """defensive=True in both paths. A web roll is not a different roll."""
```

- [ ] Run the full suite. Commit.

---

## Milestone 5 acceptance

- [ ] A Roll control on any open short raises a `PENDING` roll approval, and places no order.
- [ ] The control is labelled "Propose a roll" and its confirmation says what actually happens.
- [ ] `no_qualifying_roll`, `roll_already_working`, `not_an_open_short`, `chain_unavailable` and
  `broker_unavailable` are five distinguishable outcomes, each rendered honestly.
- [ ] A monitor alert and a web request for the same position produce exactly one approval.
- [ ] `command_drain.py` contains no roll economics; `rolling.py` remains the only place they
  live.
- [ ] The web roll uses `defensive=True`, the same policy as the monitor.
- [ ] Full gate green, all six commands, with the full Python suite run because this milestone
  modifies trading code.
