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
- **Applied by:** M4. Creates an `ApprovalRow` from the `CandidateRow`'s frozen snapshot.
- **Live mode:** `needs_confirmation = true`.
- **Failure modes:** `candidate_not_found`, `already_has_approval`, `gate_rejected`.
- **Milestone:** M4.

### `roll_request` — request a roll for a position

- **Payload:** `{ position_symbol: str }`
- **Dedupe key:** `roll_request:{position_symbol}`
- **Applied by:** M5. Triggers the roll evaluation; a `RollAlertRow` is created and
  Claude reviews it.
- **Live mode:** `needs_confirmation = true`.
- **Failure modes:** `position_not_found`, `no_qualifying_roll`, `broker_unavailable`.
- **Milestone:** M5.

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