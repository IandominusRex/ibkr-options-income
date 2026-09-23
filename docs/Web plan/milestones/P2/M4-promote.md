# Milestone 4 — Promote

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The operator can act on a contract the Rules Engine passed but the ranking dropped, and
cannot act on one the Rules Engine refused.

**Spec:** `Web plan/P2-design.md` §5.2 (the promotable table), §6.2 (the re-derive mechanism).
**Index:** `Web plan/P2-IMPLEMENTATION-PLAN.md`. **Depends on:** Milestone 3.

**The shape of this milestone in one sentence:** a promote is not "approve this stored contract",
it is "**price this contract again, gate it again, and raise an approval only if it still
passes**". If you find yourself copying a payload out of `risk_verdicts`, you have taken the
wrong approach; re-read spec §6.2.

---

## Task 4.1 — The promotable-stage guard `[SONNET]`

**Enforces an invariant. The refusal must be total, at the API boundary, before a command row
exists.**

**Context.** `AssessmentStage` (`src/common/schemas.py:428`) has six values. Spec §5.2 defines
exactly three as promotable. `RISK_GATE` means the deterministic Rules Engine said no, and
`GENERATOR` means the strategy filters said no. Neither is a ranking decision, and neither is
the operator's to override from a browser.

**Files:** Modify `src/api/routers/commands.py`, `src/api/models/commands.py`,
`docs/web/commands.md`. Test `tests/test_promote_guard.py`.

**Interfaces:**

```python
PROMOTABLE_STAGES: frozenset[str] = frozenset({"score_floor", "dedupe", "top_n"})

def assert_promotable(session: Session, candidate_id: str) -> RiskVerdictRow:
    """Look up the assessed row and refuse a non-promotable stage with 409.

    Raises HTTPException(409, {"reason": "stage_not_promotable", "stage": ...})
    Raises HTTPException(404) when no assessed row exists for this candidate_id.
    """
```

The guard runs in `POST /commands` **before** `enqueue_command`. A refused promote leaves no row
behind, so the assessed browser cannot accumulate failed intents against contracts that were
never eligible.

Required behaviours, each with a test:
- **`risk_gate` is refused with `409`.** Its own test.
- **`generator` is refused with `409`.** Its own test.
- **`passed` is refused with `409`**, because it already has an approval.
- `score_floor`, `dedupe` and `top_n` pass the guard.
- An unknown `candidate_id` is `404`, not `409`.
- **A refused promote creates no `app_commands` row.** Asserted by counting rows before and
  after.
- The guard reads through the **read-only** engine.

- [ ] **Step 1: Write the failing test**

```python
"""The gate saying no is the point of the gate. No web path may override it."""

from __future__ import annotations

import pytest

REFUSED = ("risk_gate", "generator", "passed")
ALLOWED = ("score_floor", "dedupe", "top_n")


@pytest.mark.parametrize("stage", REFUSED)
def test_a_non_promotable_stage_is_refused(client, seed_assessed, stage) -> None:
    seed_assessed(candidate_id="c1", stage=stage)
    r = client.post("/commands", json={
        "kind": "promote",
        "payload": {"candidate_id": "c1", "symbol": "NVDA",
                    "strategy": "covered_call", "strike": 180.0, "expiry": "2026-10-17"},
    }, headers=AUTH)
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "stage_not_promotable"
    assert r.json()["detail"]["stage"] == stage


@pytest.mark.parametrize("stage", ALLOWED)
def test_a_promotable_stage_is_accepted(client, seed_assessed, stage) -> None:
    seed_assessed(candidate_id="c1", stage=stage)
    r = client.post("/commands", json={"kind": "promote", "payload": {...}}, headers=AUTH)
    assert r.status_code == 201


@pytest.mark.parametrize("stage", REFUSED)
def test_a_refused_promote_leaves_no_command_row(client, seed_assessed, count_commands, stage):
    seed_assessed(candidate_id="c1", stage=stage)
    before = count_commands()
    client.post("/commands", json={"kind": "promote", "payload": {...}}, headers=AUTH)
    assert count_commands() == before


def test_an_unknown_candidate_is_404_not_409(client) -> None:
    r = client.post("/commands", json={
        "kind": "promote", "payload": {"candidate_id": "nope", ...},
    }, headers=AUTH)
    assert r.status_code == 404
```

- [ ] **Step 2:** Implement, run the gate, update `docs/web/commands.md`'s `promote` section with
  the refusal table verbatim from spec §5.2. Commit.

---

## Task 4.2 — The `promote` drain handler `[SONNET]`

**Trading-system code, and the hardest task in the plan.** It re-runs a scan path and gates its
output.

**Context.** `src/orchestrator/scan.py::run_ticker_scan` (line 1695) already does the
single-symbol work: it fetches the chain, runs the generators, scores, gates through
`validate_candidates`, and records assessments. It does **not** raise approvals; the Telegram
`/scan TICKER` path renders a card instead.

The handler's job is to run that path, find the matching contract in its **gate-passed** output,
and raise a `PENDING` `ApprovalRow` for it exactly as `sender.py::_send_with_session` does.

**Files:** Modify `src/notify/command_drain.py`. Create
`src/execution/promote_pipeline.py` (mirroring `src/execution/roll_pipeline.py`'s shape and
docstring style). Modify `ARCHITECTURE.md`. Test `tests/test_promote_pipeline.py`,
`tests/test_drain_promote.py`.

**Interfaces:**

```python
# src/execution/promote_pipeline.py
def queue_promoted_for_approval(
    candidate: TradeCandidate, *, chat_id: str, ttl_minutes: int,
) -> int | None:
    """Persist `candidate` and raise a PENDING approval for it.

    Returns the approval id, or None when an order is already active for this candidate
    (idempotent against a replayed drain). Never raises.

    Deliberately mirrors roll_pipeline.queue_roll_for_approval: same has_active_order guard,
    same CandidateRow upsert, same N2a snapshot freeze onto the ApprovalRow.
    """

# src/notify/command_drain.py
@register("promote")
async def _promote(*, command, ib, bot, chat_id, **_) -> dict: ...
```

**The handler's algorithm, in order:**

1. If `ib is None`, fail with `broker_unavailable`. A promote needs a fresh chain and cannot be
   honestly served without one.
2. Re-run the single-ticker path for `payload.symbol`.
3. Search its **gate-passed** output for a candidate matching `(strategy, strike, expiry)`.
4. If found, call `queue_promoted_for_approval` and mark the command `applied` with the new
   `approval_id` in `result`.
5. If not found, mark the command `failed` with the most specific reason available:

| Situation | `reason` | `detail` |
|---|---|---|
| The chain fetch failed | `chain_unavailable` | the provider's message |
| The contract no longer prices | `contract_not_priced` | how many contracts were priced |
| The Rules Engine now rejects it | `gate_rejected` | the verdict's `reasons` list, verbatim |
| It priced but scored below the floor | `score_below_minimum` | the score and the threshold |

**Design points that are not negotiable:**

1. **Nothing is copied out of `risk_verdicts`.** The stored row selects *which* contract to look
   for. Every number that reaches the approval comes from the fresh run.
2. **A `gate_rejected` outcome is a success of the design, not a bug.** The reason codes are
   surfaced verbatim so the operator sees exactly what the gate saw. Do not soften the message.
3. **The approval is `PENDING`, never `APPROVED`.** A promote raises a proposal. Approving it is
   a separate act through M3's path. Two steps, always.
4. `has_active_order` is checked, so a replayed drain cannot raise a second approval.
5. The handler is bounded. A chain fetch that hangs must not stall the drain; wrap it with the
   same timeout discipline the scan path already uses.

- [ ] **Step 1: Write the failing test**

```python
"""A promote is priced now and gated now, or it does not happen."""

from __future__ import annotations

import pytest

from src.common.schemas import ApprovalStatus


@pytest.mark.asyncio
async def test_a_still_passing_contract_becomes_a_pending_approval(drain_env, fake_chain) -> None:
    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="pass")
    cid = drain_env.enqueue("promote", {"candidate_id": "c1", "symbol": "NVDA",
                                        "strategy": "covered_call", "strike": 180.0,
                                        "expiry": "2026-10-17"})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "applied"
    approval_id = drain_env.result(cid)["approval_id"]
    assert drain_env.approval_status(approval_id) == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_a_promote_never_creates_an_approved_approval(drain_env, fake_chain) -> None:
    """A promote raises a proposal. Approving it is a separate human act."""
    ...
    assert drain_env.approval_status(approval_id) != ApprovalStatus.APPROVED
    assert drain_env.order_for_approval(approval_id) is None


@pytest.mark.asyncio
async def test_a_now_rejected_contract_fails_with_the_gates_reasons(drain_env, fake_chain):
    """The gate changing its mind is the mechanism working."""
    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
    fake_chain.will_price("NVDA", strike=180.0, gate="reject",
                          reasons=["delta_out_of_band", "premium_below_fair_value"])
    cid = drain_env.enqueue("promote", {...})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "gate_rejected"
    assert drain_env.result(cid)["detail"]["reasons"] == [
        "delta_out_of_band", "premium_below_fair_value",
    ]


@pytest.mark.asyncio
async def test_the_promoted_numbers_come_from_the_fresh_run(drain_env, fake_chain) -> None:
    """The stored row picks the contract. It supplies none of the numbers."""
    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0, premium=1.00)
    fake_chain.will_price("NVDA", strike=180.0, gate="pass", premium=2.50)
    cid = drain_env.enqueue("promote", {...})
    await drain_once(drain_env.ib, drain_env.bot, "chat")

    approval = drain_env.approval(drain_env.result(cid)["approval_id"])
    assert approval.snapshot["premium"] == 2.50    # not 1.00


@pytest.mark.asyncio
async def test_a_vanished_contract_fails_with_contract_not_priced(drain_env, fake_chain):
    ...


@pytest.mark.asyncio
async def test_a_promote_with_no_broker_fails_honestly(drain_env) -> None:
    cid = drain_env.enqueue("promote", {...})
    await drain_once(None, drain_env.bot, "chat")
    assert drain_env.status(cid) == "failed"
    assert drain_env.result(cid)["reason"] == "broker_unavailable"


@pytest.mark.asyncio
async def test_a_replayed_promote_raises_no_second_approval(drain_env, fake_chain) -> None:
    ...
```

Build `fake_chain` as a fixture that lets a test declare, per symbol and strike, whether the
contract prices, what premium it prices at, and whether the gate passes it. Mock at the chain
boundary, not at `validate_candidates`: **the real Rules Engine must run in these tests**, or
they prove nothing about gating.

- [ ] **Step 2: Implement** `promote_pipeline.py` first, tested on its own, then the handler.

- [ ] **Step 3: Run the full suite.** This adds a module under `src/execution/` and calls the
  orchestrator. Every pre-existing execution and orchestrator test must still pass, and
  `tests/test_web_fence.py` must still be green: `src/execution/promote_pipeline.py` may **not**
  import `src.api` or `src.research`.

- [ ] **Step 4:** Update `ARCHITECTURE.md` (`src/execution/` table) and `docs/web/commands.md`
  (the failure-reason table verbatim). Commit.

---

## Task 4.3 — The promote action and its receipt `[GLM]`

**Files:** Modify `web/components/options/{AssessedRow,AssessedBrowser}.tsx`. Test
`web/components/options/AssessedRow.test.tsx`.

**Interfaces:** consumes `POST /commands` with `kind: "promote"`, and M3's `CommandReceipt` and
`ConfirmAction`.

Required behaviours, each with a test:
- A promote control renders **only** when `promotable` is true. For a non-promotable row it
  renders the `promote_note` as text and **no control, disabled or otherwise**. A test asserts
  no button exists on a `risk_gate` row.
- The confirmation dialog explains what a promote does in one sentence: the contract will be
  priced again and gated again, and an approval appears only if it still passes. The operator
  should not be surprised by a `gate_rejected` outcome.
- A `score_floor` row's confirmation additionally shows the score and the configured minimum, so
  the operator knows they are going below a bar they set.
- The receipt renders `failed` with the humanised reason. `gate_rejected` lists the reason codes
  through the same humaniser the assessed browser uses.
- On success the receipt links to the new approval.
- Polling stops at a terminal state.

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Task 4.4 — Promote refusal tests `[SONNET]`

**The highest-value tests in P2.** They are the assertion that a browser cannot overrule the
Rules Engine.

**Files:** Modify `tests/test_write_path_invariants.py`.

- [ ] Add:

```python
def test_no_promote_path_exists_for_a_gate_rejected_contract() -> None:
    """Belt and braces: the API refuses it, and the drain would too.

    Bypass the API guard entirely, insert a promote command for a risk_gate contract
    directly, and assert the drain still refuses rather than raising an approval.
    """


def test_the_promote_handler_runs_the_real_rules_engine() -> None:
    """A test that mocks validate_candidates proves nothing. Assert the real one is called."""


def test_promotable_stages_match_the_spec_exactly() -> None:
    """A future edit that widens PROMOTABLE_STAGES must fail here first."""
    from src.api.routers.commands import PROMOTABLE_STAGES
    assert PROMOTABLE_STAGES == frozenset({"score_floor", "dedupe", "top_n"})
```

The first of those is the important one. The API guard is the primary defence, but a defence
with one layer is a defence with one bug between it and an unguarded order.

- [ ] Run the full suite. Commit.

---

## Milestone 4 acceptance

- [ ] A `dedupe` or `top_n` contract can be promoted, and the resulting approval is `PENDING`
  with numbers from a fresh run, never from the stored assessed row.
- [ ] A `risk_gate` contract is refused at the API with `409`, leaves no command row, renders no
  control, and is **also** refused by the drain if a command is inserted directly.
- [ ] A `generator` contract is refused the same way.
- [ ] A contract the gate now rejects fails with `gate_rejected` and the verdict's reason codes
  verbatim.
- [ ] A promote with no broker connection fails with `broker_unavailable` rather than guessing.
- [ ] A replayed promote raises no second approval.
- [ ] The promote tests exercise the **real** `validate_candidates`, not a mock of it.
- [ ] `src/execution/promote_pipeline.py` imports neither `src.api` nor `src.research`; the fence
  test is green.
- [ ] Full gate green, all six commands, with the full Python suite run because this milestone
  modifies trading code.
