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
| `POST` | `/commands` | owner | Enqueue an intent. `201` if new, `200` if dedupe returned the existing row (kinds with no dedupe key — halt/resume/set_autonomy/refresh/universe_add/universe_remove — always get `201`). For `kind: "universe_add"`/`"universe_remove"` specifically, an unknown `symbol` (not in the research symbol directory) is `404` here too, before a command row can exist — the same check `POST`/`DELETE /universe/{list_name}/{symbol}` already do, closing a path that would otherwise let this generic route bypass those thin wrappers' validation. |
| `GET` | `/commands/{id}` | owner | Read one command's status (through the read-only engine). `404` if unknown. |
| `POST` | `/commands/{id}/confirm` | owner | Supply the `confirm_token` for a live-mode order-reaching intent. `204` on success. `403` on a wrong or missing token (the token is NOT cleared). `409` when the command is not awaiting confirmation. |
| `POST` | `/universe/{list_name}/{symbol}` | owner | Thin wrapper: creates a `universe_add` intent. `422` if `list_name` is not `would_own`/`watchlist`. `404` if `symbol` is not a known SEC filer. Response is the same `CommandStatus` shape as `POST /commands`. See `docs/web/api.md` and the `universe_add` section below. |
| `DELETE` | `/universe/{list_name}/{symbol}` | owner | Thin wrapper: creates a `universe_remove` intent. Same `422`/`404` as above, plus `409` when removing an `actively_wheeling` symbol from `would_own`. See the `universe_remove` section below. |

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
- **Dedupe key:** `promote:{candidate_id}`, scoped to `status == "pending"` rows only (fixed
  2026-09-11 — see STATUS.md's former "Remaining known issues" entry). `candidate_id` is stable
  across rescans, so a global dedupe key used to permanently block a fresh promote of the same
  contract once the first request had already been applied — days or months later, re-promoting
  after the original approval expired silently no-op'd with the OLD command's stale `applied`
  receipt instead of actually re-pricing and re-gating. `enqueue_command` now only matches an
  existing row for this key while it is still `pending` — two clicks while one is in flight still
  collapse to one command, but once that command is applied/failed/expired the key is live again.
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
- **Dedupe key:** `roll_request:{position_symbol}`, scoped to `status == "pending"` rows only
  (fixed 2026-09-11, same defect and fix as `promote` above) — a bare symbol is a permanent key,
  so before this fix a second `roll_request` for a symbol months later, on an entirely different
  position, deduped to the first, already-`applied` command and silently no-op'd instead of
  proposing a fresh roll.
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

- **Payload:** `{ reason: str = "" }` — capped at 200 characters (`422` past that:
  the reason is rendered by `/status` and the console's halt banner, and an
  unbounded string in a settings value is a rendering bug waiting to happen).
  Unknown keys are `422`. An empty reason is stored as
  `"halted from the web console"` so `/status` and the console always say something.
- **Dedupe key:** `None` (may repeat — halting an already-halted system is `applied`,
  not `failed`; the operator's intent is satisfied either way).
- **Applied by:** M6 Task 6.1. Sets the same `execution_halted` kill switch
  Telegram's `/halt` sets (`system_settings.set_halted`) — one halt flag, read
  through `HALT_KEY` by every consumer. Auto-close still runs (closing risk should
  never wait for a human tap). Applies with TWS down: halting matters most
  exactly when something is wrong, and "TWS is unreachable" is a common shape of
  wrong.
- **Live mode:** No confirmation needed, by design — a halt must never be slowed by
  a second step (the live token is for intents that can reach an order; a halt is
  not one). Pinned by `tests/test_write_path_invariants.py::
  test_control_kinds_never_require_live_confirmation`.
- **Notification:** the handler sends a Telegram message, so a halt raised from the
  browser is visible to the operator wherever they are.
- **Failure modes:** none (beyond a dead drain, which the receipt states in words).
- **Milestone:** M6, built.

### `resume` — resume the system after a halt

- **Payload:** `{}` (empty; unknown keys are `422`, so a client typo is caught
  rather than ignored).
- **Dedupe key:** `None` (may repeat). Resuming an un-halted system is `applied`,
  not `failed` — the same idempotency shape as halt.
- **Applied by:** M6 Task 6.1. Clears the kill switch via `set_halted(False)` and
  records who released it in the command's `result` (`released_by`), because
  releasing the kill switch re-arms execution. Applies with TWS down.
- **Live mode:** No confirmation needed (same asymmetry as halt). The console side
  is deliberately heavier: resume requires the typed word RESUME while halt is one
  click — failing to halt when you meant to costs far more than halting when you
  did not.
- **Notification:** the handler sends a Telegram message.
- **Failure modes:** none (beyond a dead drain).
- **Milestone:** M6, built.

### `set_autonomy` — change the autonomy level

- **Payload:** `{ level: "observe" | "manual" | "whitelist" | "full" }` — anything
  outside the four rungs is `422` at parse time, before a command row exists, and
  is never coerced. Unknown keys are `422`.
- **Dedupe key:** `None` (may repeat — setting the same level twice is harmless).
- **Applied by:** M6 Task 6.1. Persists the new level through
  `system_settings.set_autonomy_level`, the same key Telegram's `/autonomy` writes.
  Promotion is refused the same way Telegram refuses it — `promotion_blockers` must
  be empty — so the web is not the rung ladder's back door. Demotion (including a
  same-rung no-op) always applies.
- **Live mode:** No confirmation needed (control kind).
- **Notification:** the handler sends a Telegram message.
- **Failure modes:** `promotion_refused` (`result.detail.blockers` carries the
  unmet criteria, rendered by the receipt). Reads the trading DB (local SQLite),
  never the broker.
- **Milestone:** M6, built.

### `universe_add` — add a symbol to a universe list

- **Payload:** `{ symbol: str, list_name: "would_own" | "watchlist" }`
- **Dedupe key:** `None` (may repeat — an add/remove is an idempotent upsert, same shape
  as halt/resume/set_autonomy; repeating one just re-applies). Fixed in the M7 final-review
  round: a stable `universe_add:{list_name}:{symbol}` key let a later, semantically different
  request against the same symbol dedupe to an already-`applied` row from an earlier request
  (e.g. remove -> add -> remove would silently no-op on the second remove).
- **Reachable from the console since Task 7.4:** `POST /universe/{list_name}/{symbol}` is a
  thin wrapper that validates and enqueues this exact intent, returning the same
  `CommandStatus` shape `POST /commands` returns — see the route in the table above.
- **Applied by:** M7 Task 7.4. The drain handler (`src/notify/command_drain.py`'s
  `_universe_add`) upserts a `UniverseOverrideRow` with `action="add"` via
  `src.storage.universe_overrides.set_override`, then calls
  `invalidate_universe_cache()` so the edit is live in this process at once, not up to 60s
  later. Idempotent: repeating it re-applies the same upsert, same idempotency shape as
  halt/resume/set_autonomy. Sends no Telegram notification — a universe edit is reversible,
  non-urgent config, not a safety-critical control. Applies with `ib is None`.
- **Live mode:** No confirmation needed.
- **Failure modes:** none — all real validation happens **before** a command row can exist,
  at the API boundary: `list_name` outside `{would_own, watchlist}` is `422` (enforced by
  `Literal` typing on both the `POST /universe/{list_name}/{symbol}` path parameter and
  `UniversePayload.list_name`, so `sectors`/`leveraged_etfs`/`strike_bands`/
  `actively_wheeling` can never become a command), and an unknown `symbol` (not in the
  research symbol directory) is `404` — checked both by `POST /universe/{list_name}/{symbol}`
  and, since the M7 final-review round, by the generic `POST /commands` route too
  (`src/api/deps.py::assert_known_symbol`, shared by both), so the generic route can no
  longer be used to bypass the thin wrapper's symbol check. A command that reaches the drain
  is therefore always valid and always applies.
- **Milestone:** M7, built (Task 7.4; boundary check closed at the generic route in the
  final-review round).

### `universe_remove` — remove a symbol from a universe list

- **Payload:** `{ symbol: str, list_name: "would_own" | "watchlist" }`
- **Dedupe key:** `None` (may repeat — an add/remove is an idempotent upsert, same shape
  as halt/resume/set_autonomy; repeating one just re-applies).
- **Reachable from the console since Task 7.4:** `DELETE /universe/{list_name}/{symbol}` is
  a thin wrapper that validates and enqueues this exact intent.
- **Applied by:** M7 Task 7.4. The drain handler (`_universe_remove`) upserts a
  `UniverseOverrideRow` with `action="remove"` — **never `clear_override`**: a remove always
  means "record an override that suppresses this symbol," whether it started in the YAML
  base or was itself an override-add; deleting the row would silently do nothing for a
  YAML-base symbol. Also calls `invalidate_universe_cache()`. Sends no Telegram
  notification. Applies with `ib is None`.
- **Live mode:** No confirmation needed.
- **Failure modes:** none — same boundary-first validation as `universe_add` (including the
  generic `POST /commands` route's `404` check since the final-review round), plus one more
  check specific to removal: removing a symbol that is in `actively_wheeling` **from
  `would_own`** is `409` with `{"reason": "actively_wheeling", "symbol": ...}` — you cannot
  stop being willing to own something you are actively wheeling. This guard is
  `would_own`-only, mirroring the composer's own remove-guard (`src/common/universe.py`):
  removing the same symbol from `watchlist` is harmless and is not blocked. It is enforced
  only by the thin `DELETE /universe/{list_name}/{symbol}` wrapper, not by the generic
  `POST /commands` route — the composer's own remove-guard in `effective_universe()` makes
  that asymmetry safe regardless of which route an override row came in through, so only the
  symbol-existence check needed closing at the generic route. As with `universe_add`, a
  command that reaches the drain is always valid and always applies.
- **Milestone:** M7, built (Task 7.4; boundary check closed at the generic route in the
  final-review round).

### `refresh` — capture the portfolio now

- **Payload:** `{}` (empty)
- **Dedupe key:** `None` (may repeat — two refreshes in a row both apply; there is nothing
  to dedupe because each writes its own snapshot row)
- **Applied by:** the `_refresh` handler in `src/notify/command_drain.py` (registered
  2026-09-09, P3/P4 M1 Task 1.4). It fetches current positions and account values through
  the drain's live IB connection and appends **one** `portfolio_snapshots` row with
  `source="refresh"`. It ignores the monitor's interval gate — that gate is the monitor's
  cadence control, not a rate limit on the operator — but the row it writes still counts
  toward the gate, because the gate reads the table's newest `captured_at`.
- **Live mode:** No confirmation needed. A refresh creates no candidate, no approval, and no
  order — it is a data capture, not a trade intent, and it reaches no order path at any
  point (asserted by `tests/test_drain_refresh.py`).
- **Failure modes:** `broker_unavailable` (no IB connection at drain time — the handler
  refuses to write a row of whatever the last known state was; also raised when the
  positions/account fetch itself fails), and `snapshot_failed` (the write returned `None` —
  a storage failure, reported as its own reason rather than `handler_error`).
- **Result:** `{"captured_at": "<iso UTC>", "positions": <int>, "snapshot_id": <int>}` — the
  receipt says what was actually captured, not just "applied".
- **Notifications:** none. A refresh is reversible, non-urgent, and not a safety-critical
  control (the same reasoning that keeps `universe_add`/`universe_remove` silent while
  halt/resume notify).
- **Milestone:** M1 of P3/P4 (built, Task 1.4).

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