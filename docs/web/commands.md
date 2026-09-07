# Commands — the intent queue runbook

> **For the operator at 3pm on a bad day.** This is the only part of the web layer that
> can move money. Every kind is documented here: what it does, what its payload looks
> like, what applies it, and how it fails.

## The model

A web click does not mutate the trading system directly. It enqueues a **command** —
a row in `app_commands` — and the trading process's **drain loop** applies it. This
means:

- A click that arrives while TWS is down still enqueues; the drain applies it when TWS
  comes back (or immediately, for commands that don't need the broker).
- A duplicate click (two taps on Approve) produces **one** command, not two — the
  second `POST` returns the first command's id with `200`, not a second `201`.
- In **live mode**, order-reaching intents get a `confirm_token` and sit `pending`
  until a second `POST /commands/{id}/confirm` supplies it. Paper mode skips this.

## Routes

| Method | Path | Auth | Notes |
|---|---|---|---|
| `POST` | `/commands` | owner | Enqueue an intent. `201` if new, `200` if dedupe returned the existing row. |
| `GET` | `/commands/{id}` | owner | Read one command's status (through the read-only engine). `404` if unknown. |
| `POST` | `/commands/{id}/confirm` | owner | Supply the `confirm_token` for a live-mode order-reaching intent. `204` on success. `403` on a wrong or missing token (the token is NOT cleared). `409` when the command is not awaiting confirmation. |

Every route requires the `owner` role. A viewer token gets `403`.

## Request body

```json
{ "kind": "approve", "payload": { "approval_id": 42 } }
```

A wrong-shaped `payload` returns `422` with the validation errors.

## Response — `CommandStatus`

| Field | Type | Notes |
|---|---|---|
| `id` | int | The command id |
| `kind` | string | The `CommandKind` |
| `status` | `"pending"` \| `"applied"` \| `"failed"` \| `"expired"` | |
| `result` | object \| null | What happened — on failure, `{reason, detail}` |
| `needs_confirmation` | bool | `true` when a live-mode `confirm_token` is outstanding |
| `confirm_token` | string \| null | Present only while a live-mode token is outstanding — the owner supplies it back via the confirm route; cleared on confirm, absent in paper mode |
| `created` | bool | (POST only) `true` if a new row was inserted, `false` if a dedupe returned the existing one |
| `created_at` | datetime | |
| `applied_at` | datetime \| null | |
| `as_of` | datetime | Response envelope stamp |

### The live-mode flow, as an ordered list

When `LIVE_TRADING=true` and the kind can reach an order (`approve`, `promote`,
`roll_request`), one click is not enough. Follow these steps:

1. Click **Approve** (or the equivalent action) in the console. A first
   confirmation dialog opens showing the exact contract and contract count.
2. Confirm the first dialog. The API stores the intent with a `confirm_token`
   and returns `needs_confirmation: true`. **Nothing has been applied yet** —
   the drain skips this command until the token is released.
3. A **second, clearly labelled LIVE confirmation** opens in the console. This
   is not a repeat of the first dialog: it names the kind, says this is the
   mandatory live-trading release, and reminds you the execution-time
   `[CONFIRM LIVE]` Telegram step still fires afterwards.
4. Release it. The console `POST /commands/{id}/confirm` with the token; on
   `204` the token is cleared and the **next drain cycle** applies the intent.
5. If you cancel the second dialog instead, the intent stays queued awaiting
   confirmation. It does not apply; it expires with the approval TTL.

A wrong token never clears the field — the command stays pending, fail closed.
The token expires with `approval.ttl_minutes`; the drain's expiry sweep moves
an unconfirmed command to `expired`, never applies it. In paper mode no token
is issued, steps 2-4 do not happen, and the drain applies normally.

---

## Every kind

### `approve` — approve a pending approval

- **Payload:** `{ approval_id: int }`
- **Dedupe key:** `approve:{approval_id}`
- **Applied by:** M3. The drain's handler calls `_process_button(approval_id,
  "approve")` — the exact function the Telegram Approve button runs, unchanged.
  Sets `ApprovalRow.status = approved`, copies the frozen N2a snapshot onto a
  `QUEUED` `OrderRow`, and the executor picks it up when the exec connection is
  available.
- **Already decided is not a failure.** If Telegram got there first,
  `_process_button` returns "Already {status}" and mutates nothing; the command
  is still marked `applied` with that text in `result.decision`. The four
  idempotency layers (spec §4.5) mean a replayed or racing approve can never
  create a second order.
- **TWS down does not lose the decision.** The approve needs no broker
  connection: it creates a `QUEUED` order, and `process_queued_orders` submits
  it when the exec connection returns.
- **Live mode:** `needs_confirmation = true` — requires a `POST /commands/{id}/confirm`
  before the drain will process it.
- **Failure modes:** `approval_not_found` (no such `approval_id`).
- **Milestone:** M3.

### `reject` — reject a pending approval

- **Payload:** `{ approval_id: int }`
- **Dedupe key:** `reject:{approval_id}`
- **Applied by:** M3. The drain's handler calls `_process_button(approval_id,
  "reject")` unchanged: sets `ApprovalRow.status = rejected` and records the
  `USER_REJECTED` outcome. No order is created. An already-decided approval
  applies neutrally, same as approve.
- **Live mode:** No confirmation needed — rejecting cannot reach an order.
- **Failure modes:** `approval_not_found`.
- **Milestone:** M3.

### `promote` — promote an assessed contract to the approval queue

- **Payload:** `{ candidate_id: str, symbol: str, strategy: str, strike: float, expiry: date }`
- **Dedupe key:** `promote:{candidate_id}`
- **Applied by:** M4 Task 4.2. The drain handler (`src/notify/command_drain.py`'s `_promote`)
  re-prices and re-gates the requested contract **right now** — it re-runs the single-ticker
  pricing path (`src.orchestrator.scan._price_and_gate_ticker`: fresh chain, fresh analytics,
  the real CC/CSP screens, the real score, the real Rules Engine) for `payload.symbol`, then
  searches the gate-passed output for the exact `(strategy, strike, expiry)` requested. Only on
  a match that still clears the gate does it call
  `src.execution.promote_pipeline.queue_promoted_for_approval`, which persists the fresh
  `TradeCandidate` as a `CandidateRow` and raises a **PENDING** `ApprovalRow` (frozen snapshot,
  N2a) — mirroring `roll_pipeline.queue_roll_for_approval`'s `has_active_order` guard, so a
  replayed drain against a candidate that already has an active order is `applied` (not
  failed) with `result = {"approval_id": null, "note": "order_already_active"}` rather than a
  second order. `has_active_order` checks for an `OrderRow`, not an `ApprovalRow`, so this
  guards against a second *order*, not against every replay timing: a replay landing in the
  narrow window after the first approval is raised but before its command is marked `applied`
  (no `OrderRow` exists yet) can still raise a second PENDING approval for the same candidate.
  Pre-existing in the `roll_pipeline` pattern this mirrors, not introduced by this milestone.
  Nothing from the stored `RiskVerdictRow` reaches the approval except the
  `(candidate_id, symbol, strategy, strike, expiry)` used to select which contract to look for
  — every number on the resulting approval comes from this fresh run.
- **Live mode:** `needs_confirmation = true`.
- **Failure modes:** `broker_unavailable` (no `ib` — see below), plus the table below.
- **Reachable from the console since Task 4.3:** the Assessed tab's `<AssessedRow/>`
  renders a Promote button on any row where `promotable` is true, opens the same
  `ConfirmAction` → `submitCommand` → `CommandReceipt` shape `<DecideControls/>` uses for
  approve/reject (including the live-mode second confirmation), and on `applied` links to
  the new approval via `result.approval_id`. A `score_floor` row's confirmation additionally
  shows the score and this table's configured-minimum note, so promoting below a
  self-configured bar is not a surprise.
- **Milestone:** M4 (Task 4.2 backend, Task 4.3 frontend).

**The promote failure-reason table (Task 4.2).** If `ib is None` the command fails immediately
with `broker_unavailable` — a promote needs a fresh chain and cannot be honestly served without
one. Otherwise, when the fresh run does not end in a new PENDING approval, the command fails
with the most specific reason available:

| Situation | `reason` | `detail` |
|---|---|---|
| The chain fetch failed **or** the fresh analytics/account fetch failed outright | `chain_unavailable` | the provider's message (chain fetch), or `{"stage": "analytics" \| "account", "detail": <human text>}` (analytics/account fetch — `_price_and_gate_ticker` raised `TickerPricingAborted` before a chain was even screened) |
| The contract no longer prices | `contract_not_priced` | how many contracts were priced |
| The Rules Engine now rejects it | `gate_rejected` | the verdict's `reasons` list, verbatim |
| It priced but scored below the floor | `score_below_minimum` | the score and the threshold |

`chain_unavailable` is deliberately one reason covering two internal causes: a chain-fetch
failure and an analytics/account-fetch failure both mean the same thing to the operator — there
is no fresh, honest price for this ticker right now — so an analytics/account-fetch failure is
not given its own fifth reason code; it folds into `chain_unavailable`, with the failed stage
named in `detail` instead.

A `gate_rejected` outcome is a success of the design, not a bug — the gate changing its mind
between the original scan and the promote is exactly the mechanism working, so its reasons are
surfaced verbatim, never softened or summarized.

**The promotable-stage guard (Task 4.1).** `POST /commands` refuses a `promote` before any
`app_commands` row is created, unless the candidate's most recently assessed `risk_verdicts` row
(`candidate_id` is not unique — the same candidate can be assessed differently across scan runs,
so this means the newest by `created_at`) is at one of exactly three stages. This is spec §5.2's
promotable table, verbatim:

| Stage | Meaning | Promotable |
|---|---|---|
| `GENERATOR` | failed a strategy filter (delta band, DTE, liquidity, ROC) | **no** |
| `RISK_GATE` | failed the deterministic Rules Engine | **no** |
| `SCORE_FLOOR` | cleared the gate, scored below `min_candidate_score` | **yes, flagged** |
| `DEDUPE` | a better strike for the same underlying and strategy won | **yes** |
| `TOP_N` | good enough, but `max_new_positions_per_run` was already full | **yes** |
| `PASSED` | surfaced for approval | already an approval |

`DEDUPE` and `TOP_N` mean the Rules Engine said yes and the score floor said yes; only the
ranking dropped the contract — promoting one is the operator disagreeing with a ranking, which
is a judgment call the operator is entitled to make. `SCORE_FLOOR` is promotable but flagged,
because the contract fell below a bar the operator themselves configured.

`RISK_GATE` and `GENERATOR` are never promotable — the gate saying no is the whole point of the
gate — and `PASSED` is refused because it already has an approval. A refusal is `409` with
`{"reason": "stage_not_promotable", "stage": <the stage>}` and **leaves no command row behind**,
so the assessed browser cannot accumulate failed intents against contracts that were never
eligible. An unknown `candidate_id` (no assessed row at all) is `404`, not `409`. The guard reads
through the read-only trading-database engine, never the write-scoped command engine.

### `roll_request` — ask the system to propose a roll for an open short

- **Payload:** `{ position_symbol: str }` — the OCC symbol of the open short, exactly as
  `GET /options/shorts` returns it.
- **Dedupe key:** `roll_request:{position_symbol}`
- **Applied by:** M5 Task 5.1. The drain handler (`src/notify/command_drain.py`'s `_roll_request`)
  resolves the position from a live portfolio read, fetches a fresh chain + IV/technical stats
  through the same shared helper the intraday monitor uses
  (`src.execution.roll_pipeline.fetch_roll_inputs` — the one chain-fetch path for rolls, so the
  web console and the monitor cannot drift apart on how a roll is priced), and calls
  `queue_roll_for_approval` **unchanged**. The pipeline already runs
  `generate_roll_candidates(..., defensive=True)`, picks the best by ROC, and raises a **PENDING**
  `ApprovalRow` with the frozen snapshot. Two steps, never one: this proposes; the operator
  approves the proposal through the same path as every other approval (§6.1). No order is placed
  by a roll request. **Under `defensive=True` every candidate's `roc_pct` is 0** (D4: a defensive
  roll is judged on risk reduction, not yield) — `generate_roll_candidates`'s ROC-desc sort is
  therefore a no-op tie, and "picks the best" really means "picks whichever qualifying quote the
  chain listed first." Two fetches taken minutes apart can list qualifying strikes in a different
  order even when neither stops qualifying — see the in-flight check below, which accounts for
  this rather than assuming a stable "best."
- **Result on success:** `{"approval_id": int, "candidate_id": str}` — link the receipt to
  `/options/{approval_id}`.
- **The web roll is the monitor's roll.** `defensive=True` in both paths; the roll's own net-debit
  cap and delta-reduction floor (in `rolling.py`) are the roll's economic control, and the handler
  adds no bounds of its own and relaxes none. `tests/test_write_path_invariants.py` pins that no
  economic token leaks into the drain and that the defensive policy is shared.
- **Live mode:** `needs_confirmation = true`.
- **Failure modes:** the table below — five distinguishable outcomes, each rendered honestly.
  `position_not_found` (the OCC symbol is not in the live portfolio) is a sixth, listed in the
  table's note.
- **Milestone:** M5 (Task 5.1 backend, Task 5.2 frontend).

**The roll_request reason table (Task 5.1).** If `ib is None` the command fails immediately with
`broker_unavailable` — a roll needs a fresh chain and cannot be honestly served without one.
Otherwise, when the handler cannot end in a new PENDING approval, the command fails with the most
specific reason available:

| Situation | `reason` | `detail` |
|---|---|---|
| `ib is None` | `broker_unavailable` | none |
| The position is not an open short option (a long, or a stock) | `not_an_open_short` | none |
| The chain fetch failed | `chain_unavailable` | the provider's message |
| `generate_roll_candidates` returned nothing | `no_qualifying_roll` | none |
| An order is already active **or** a PENDING approval already exists for the same roll candidate | `roll_already_working` | `{"approval_id": int \| null}` — link the receipt to the in-flight proposal |

`roll_already_working` covers both an active order (the monitor's proposal was approved and is
working) and an existing PENDING approval (the monitor's proposal is awaiting the operator's
decision). The latter is the case `has_active_order` alone would miss — it only sees `OrderRow`s —
so the handler also checks for a PENDING approval on the same deterministic candidate id. This
check runs against **every candidate `generate_roll_candidates` returns for this position, not
just the top-ranked one** — since ranking is a no-op tie under `defensive=True` (see above), the
monitor's earlier proposal can still be sitting in this fetch's candidate list without being
first. Checking only the top-ranked candidate would let a web request race the monitor into a
second approval whenever the chain lists strikes in a different order between the two fetches
(`tests/test_drain_roll.py::test_an_in_flight_roll_is_caught_even_when_no_longer_top_ranked`
pins this). A sixth reason, `position_not_found`, fires when the OCC symbol is not in the live
portfolio at all.

A `no_qualifying_roll` outcome is a correct answer rendered as one, not an error: no roll on the
current chain clears the roll's own bounds. The frontend renders it as a plain sentence, not red
failed chrome. `roll_already_working` links to the existing approval. On success the receipt links
to the new approval.

### `halt` — halt the system

- **Payload:** `{ reason: str = "" }`
- **Dedupe key:** `None` (may repeat — halting an already-halted system is harmless)
- **Applied by:** M6. Sets the `execution_halted` kill switch in `system_settings`.
  Auto-close still runs (closing risk should never wait for a human tap).
- **Live mode:** No confirmation needed.
- **Failure modes:** none.
- **Milestone:** M6.

### `resume` — resume the system after a halt

- **Payload:** `{}` (empty)
- **Dedupe key:** `None` (may repeat)
- **Applied by:** M6. Clears the `execution_halted` kill switch.
- **Live mode:** No confirmation needed.
- **Failure modes:** `not_halted`.
- **Milestone:** M6.

### `set_autonomy` — change the autonomy level

- **Payload:** `{ level: "observe" | "manual" | "whitelist" | "full" }`
- **Dedupe key:** `None` (may repeat — setting the same level twice is harmless)
- **Applied by:** M6. Persists the new level to `system_settings`. Promotion to
  `whitelist`/`full` is blocked until the account shows ≥20 fills, ≥60% fill rate,
  and ≥1 buy-to-close — the same evidence `promotion_blockers` checks.
- **Live mode:** No confirmation needed.
- **Failure modes:** `promotion_blocked` (the blockers aren't met).
- **Milestone:** M6.

### `universe_add` — add a symbol to a universe list

- **Payload:** `{ symbol: str, list_name: "would_own" | "watchlist" }`
- **Dedupe key:** `universe_add:{list_name}:{symbol}`
- **Applied by:** M7. Creates a `UniverseOverrideRow`. **`sectors` and
  `leveraged_etfs` are rejected at the type level** — only `would_own` and
  `watchlist` may be edited from the web (spec §7.2).
- **Live mode:** No confirmation needed.
- **Failure modes:** `unknown_symbol`, `already_in_list`.
- **Milestone:** M7.

### `universe_remove` — remove a symbol from a universe list

- **Payload:** `{ symbol: str, list_name: "would_own" | "watchlist" }`
- **Dedupe key:** `universe_remove:{list_name}:{symbol}`
- **Applied by:** M7. Removes the `UniverseOverrideRow` (or the base entry, if the
  symbol is in `universe.yaml`).
- **Live mode:** No confirmation needed.
- **Failure modes:** `not_in_list`.
- **Milestone:** M7.

### `refresh` — request a scan refresh

- **Payload:** `{}` (empty)
- **Dedupe key:** `None` (may repeat — multiple refresh requests are harmless, only
  one scan runs at a time thanks to the scan lease)
- **Applied by:** M6. Triggers a full scan on the next cycle.
- **Live mode:** No confirmation needed.
- **Failure modes:** `scan_already_running`.
- **Milestone:** M6.

---

## The drain loop

The drain runs inside `approval_service` (the process that holds the exec connection).
Every `interval` seconds it:

1. Expires stale commands past their TTL (`approval.ttl_minutes`).
2. Reads all `pending` commands.
3. For each: if a `confirm_token` is outstanding, **skips** it (not an error — it's
   waiting for a human). Otherwise calls the registered handler.
4. A handler that throws marks **its own** command `failed` and the loop continues —
   one bad command never stalls the queue.
5. An unknown kind is **failed** with `unknown_kind`, not left pending.
6. Commands that don't need the broker (`reject`, `halt`, `resume`, `set_autonomy`,
   universe edits) apply even when `ib is None` (TWS down).
7. Writes `command_drain_heartbeat` to `system_settings` **after** the cycle completes
   (never before), so a hung handler cannot make the loop look healthy. M2's
   `/options/controls` reads this to tell an operator their click is queued and
   nothing is picking it up.

In M1, `HANDLERS` was empty — the only observable behaviour was the unknown-kind
path, the expiry sweep, and the heartbeat. This was deliberate: the machinery was
proven before anything could use it. **Since M3**, `approve` and `reject` are
registered. A handler raising `CommandFailed` fails its own command with that
machine-readable reason (rendered humanised on the receipt); any other exception
is recorded as `handler_error` with the exception text.