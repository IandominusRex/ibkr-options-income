# Design — P2 Options Console

**Date:** 2026-09-06
**Status:** design, approved in outline, pending written review
**Context:** `OVERVIEW.md` holds the end-state vision and the P0–P5 decomposition.
`P0-P1-design.md` designs the foundation and the research tier, both shipped.
**Prior art re-used, not redesigned:** `docs/superpowers/specs/2026-08-10-remediation-and-ios-app-design.md`
§9.3 (the intent queue), §9.4 (`universe_overrides`), §10.2 (the three client rules).

---

## 1. Scope

**P2 — Options console.** The section OVERVIEW §1 describes as "the system's option
recommendations, with approve / reject / manual execute / manual roll". It is the phase with
teeth: the first web surface that can cause an order to exist.

It ships six things:

1. **The approvals queue** — pending approvals with the full candidate card, approve and reject.
2. **The assessed browser** — every contract the scan priced and why it was not surfaced, with
   the ability to promote a contract the gate passed but the ranking dropped.
3. **Manual roll** — an on-demand roll for any open short option.
4. **Orders and fills** — an approval watched through to a fill without opening Telegram.
5. **Controls** — halt, resume, and the autonomy rung.
6. **Universe editing** — the write path P1 deliberately deferred here.

**Out of scope, by phase:** portfolio screens (P3), the profitability tracker (P4), mobile (P5).
Their rail entries keep rendering their placeholder.

**Out of scope, by decision:** building a contract the system never priced. There is no order
ticket and no symbol-plus-strategy proposal form in P2. See §4.3.

---

## 2. Decisions this design implements

Each was taken explicitly during the P2 brainstorm on 2026-09-06.

| Decision | Value |
|---|---|
| Manual execute | **Act on what the system proposed.** Approve, reject, and promote a gate-passed assessed contract. No contract construction in the web layer. |
| Manual roll | **On demand for any open short**, via an intent that reuses `queue_roll_for_approval` unchanged. |
| Also in P2 | Universe editing · halt/resume/autonomy · the assessed browser · the orders and fills monitor. |
| Access posture | **Loopback only, writes hardened.** `api.host` stays `127.0.0.1`. The bearer token moves out of the client bundle. Tailscale and any hosting are a separate later change. |
| Intent queue home | **The trading database, through a write-scoped engine** the API may use for `app_commands` and nothing else. |
| Promote mechanism | **Re-derive and re-gate.** No stored payload, no stale premium. |
| Override surface | **`would_own` and `watchlist` only.** `sectors`, `leveraged_etfs` and `strike_bands` stay file-only. |

---

## 3. Inherited invariants

From `CLAUDE.md` and `P0-P1-design.md` §3. Non-negotiable, and P2 is the phase where they are
actually load-bearing rather than theoretical.

1. **The Rules Engine is the only path to order execution**, and it is deterministic Python with
   no LLM involvement. P2 adds no second path. Every intent terminates in a code path that
   already exists and already gates.
2. **The fence.** Nothing in `src/claude/eval/` or the research layer reaches the engine, the
   scoring weights, the risk limits, or sizing. P2 adds a write path for `universe_overrides`,
   which is human-authored config, not a learned signal. §7.4 explains why that distinction
   holds and what enforces it.
3. **Analytics tiers.** The enrichment tier still may not be imported by `engine/`,
   `execution/`, or `strategies/`.
4. **Pydantic at every boundary.** No raw `ib_async` object crosses a module line. The API is
   still no exception, and still holds no `ib_async` connection.
5. **One clientId per process.** P2 adds **no new process**, so it adds no clientId.

---

## 4. The write path

### 4.1 Shape

```
console ──POST /commands──▶ API ──write-scoped engine──▶ app_commands (status=pending)
                             │
                             └────mode=ro engine───────▶ approvals · orders · fills
                                                         risk_verdicts · position_snapshots
                                                         system_settings · universe_overrides

approval_service._command_drain_loop        (every `execution.poll_interval_seconds`)
   approve / reject      → _process_button(approval_id, action)        [existing, unchanged]
   promote               → re-run single-ticker → gate → raise approval
   roll_request          → chain → generate_roll_candidates → queue_roll_for_approval [existing]
   halt / resume         → set_halted(True/False, reason)                [existing]
   set_autonomy          → set_autonomy_level                          [existing]
   universe_add / remove → universe_overrides
   refresh               → position + quote refresh
        ↓
   app_commands.status = applied | failed, result_json = what happened
```

The API creates intent. It cannot create an order. That is a property of the process, not a
convention: `src/api/` still constructs no `IB` object, and the only trading-database table it
may write is `app_commands`.

### 4.2 Why the queue lives in the trading database

`P0-P1-design.md` §4.3 opened the trading database `mode=ro` and stated the API writes to it
never. P2 relaxes that to **read-only except `app_commands`**, and it is worth being explicit
about why, because the alternative preserved the older sentence at a real cost.

The rationale for `mode=ro` was never a blanket prohibition. It was ingest volume: SQLite permits
one writer per database, and a nightly multi-thousand-row research ingest writing into the
trading database would serialise against `approval_service`'s writes, delaying a trade approval.
A command insert is one small row at human click rate, a few per day. It does not have that
failure mode.

Putting the queue in `research.db` would preserve the old sentence verbatim, but it would make
`approval_service` — a trading process — depend on the web layer's database, and it would split
every command application across two databases with no shared transaction. Applying a command
means mutating `ApprovalRow`, inserting `OrderRow`, and marking the command applied. In one
database that is **one transaction with no partially-applied state to reason about**. Across two
it is three steps with a window in the middle.

So the queue lives in the trading database, and the guarantee is moved from "the API cannot
write" to "**the API can write exactly one table**", enforced structurally:

- `src/api/trading_db.py` keeps `get_trading_engine()` on the `mode=ro` URI, unchanged.
- A second `get_command_engine()` opens the same file read-write, used only by
  `src/api/commands.py`.
- `tests/test_web_fence.py` gains an assertion that no module outside `src/api/commands.py`
  imports `get_command_engine`, and that the command writer's SQL touches no table but
  `app_commands`.

An accidental `INSERT` into `orders` from a route still raises `OperationalError`, because
routes hold the read-only session.

### 4.3 What the console cannot do

There is no order ticket. The operator cannot type a strike and an expiry and send it, and
cannot ask the system to price a symbol on demand from the web.

This is a scope decision, not an oversight. Everything P2 can act on is a contract **the system
itself priced and recorded**, which means every action inherits the generator's filters, the
Rules Engine's verdict, and the score floor. Authoring a contract by hand would introduce a
class of input the deterministic layer has never seen, and the honest place to add it is a later
phase with its own safety review.

The nearest available thing is the assessed browser (§5.2): if the system priced a contract this
scan, the operator can act on it. If it did not, the answer is to run a scan.

### 4.4 The `app_commands` table

```
app_commands(
  id            PK
  kind          approve | reject | promote | roll_request | halt | resume
                | set_autonomy | universe_add | universe_remove | refresh
  payload_json  the intent's arguments
  dedupe_key    unique, derived from (kind, target); NULL for kinds that may repeat
  status        pending | applied | failed | expired
  result_json   what happened, including the failure reason
  requested_by  user id from CurrentUser
  confirm_token set for live-mode intents that need a second confirmation (§4.6)
  created_at
  applied_at
)
```

`dedupe_key` carries a unique constraint. Two clicks on Approve for the same approval produce one
row, and the second `POST /commands` returns the existing command's id with `200`, not a second
`201`. This is the first of four idempotency layers.

### 4.5 Idempotency, in four layers

A drain that crashes after applying a command but before marking it `applied` will retry it. Every
retry is absorbed:

1. **Command level.** `dedupe_key` prevents a duplicate intent from being created at all.
2. **`_process_button`'s status guard.** An approval that is no longer `PENDING` returns
   "Already `<status>`" and mutates nothing.
3. **`has_active_order`.** An approve whose candidate already has a working or filled order marks
   the approval approved and creates no second `OrderRow`.
4. **`OrderRow.approval_id`'s unique constraint.** A concurrent writer that got past layer 3
   raises `IntegrityError`, which `_process_button` already catches and logs.

Layers 2 through 4 exist today and are already tested. P2 adds only layer 1 and must not weaken
the others.

### 4.6 Live mode needs a second confirmation

`LIVE_TRADING=true` already forces a second confirmation before an order transmits, via
`register_live_confirm` / `resolve_live_confirm` and the `[CONFIRM LIVE]` Telegram button. The web
must not become a way around it.

In live mode, any intent that can reach an order — `approve`, `promote`, `roll_request` — is
created with a `confirm_token` and `status=pending`, and the drain **skips it** until a second
`POST /commands/{id}/confirm` supplies that token. The token expires with the approval's TTL.
In paper mode no token is issued and the drain proceeds normally.

The existing execution-time confirmation is untouched and still fires. A live web approve
therefore requires two web confirmations and the existing Telegram confirm, which is deliberate.

---

## 5. Read surfaces

All read routes serve from SQLite through the `mode=ro` engine, carry a top-level `as_of`, and
inherit P1's provenance envelope. None of them reach IBKR, so every number is as fresh as the
last write by a trading process and says so.

### 5.1 Approvals

`GET /options/approvals` returns pending and recently decided approvals. Each carries the frozen
`snapshot` — the exact payload the human was shown — plus the joined `CandidateRow` payload, the
`RiskVerdictRow` for that candidate, and the `ClaudeReviewRow` if one exists.

That last point matters: the Telegram card renders Claude's review as prose in a chat bubble.
The console can render `why_attractive`, `risks`, `tradeoffs`, `assignment_considerations` and
`rolling_considerations` as five labelled fields beside the numbers they refer to. Same data,
a shape a chat window cannot produce.

`GET /options/approvals/{id}` returns one approval in full, including the ideal zone, the
alternative strikes the scan considered, and the greeks with their source.

### 5.2 The assessed browser

`GET /options/assessed` reads `risk_verdicts`, which already stores every contract the scan
priced with its stage, reasons, score, premium and denormalised ideal zone. The iOS spec called
this "the most useful output the system produces and the one Telegram renders worst", and it is
correct: a chat message can list three near-misses, not two hundred assessed contracts grouped
by symbol and filterable by reason.

`AssessmentStage` supplies the vocabulary, and P2 uses it to decide what is promotable:

| Stage | Meaning | Promotable |
|---|---|---|
| `GENERATOR` | failed a strategy filter (delta band, DTE, liquidity, ROC) | **no** |
| `RISK_GATE` | failed the deterministic Rules Engine | **no** |
| `SCORE_FLOOR` | cleared the gate, scored below `min_candidate_score` | **yes, flagged** |
| `DEDUPE` | a better strike for the same underlying and strategy won | **yes** |
| `TOP_N` | good enough, but `max_new_positions_per_run` was already full | **yes** |
| `PASSED` | surfaced for approval | already an approval |

`DEDUPE` and `TOP_N` mean the Rules Engine said yes and the score floor said yes; only the
ranking dropped the contract. Promoting one is the operator disagreeing with a ranking, which is
a judgment call the operator is entitled to make.

`SCORE_FLOOR` is promotable but rendered distinctly, because the contract fell below a bar the
operator themselves configured. The UI states the score and the threshold rather than hiding the
distinction.

`RISK_GATE` and `GENERATOR` are never promotable. The gate saying no is the whole point of the
gate, and no web affordance may suggest otherwise. The API refuses a promote for those stages
with `409` and the stage name, and the UI renders no promote action for them at all.

### 5.3 Orders and fills

`GET /options/orders` returns working orders with their state, limit price, filled quantity and
average fill, joined to the approval and candidate that produced them. `GET /options/fills`
returns recent fills. Together they let an approval be watched from click to fill without
opening Telegram.

### 5.4 Open shorts

`GET /options/shorts` returns open short option positions from `position_snapshots` with DTE,
delta, P&L and the assignment-risk flag, plus any `RollAlertRow` fired against them. This is the
list the roll action hangs off. It is deliberately narrower than P3's full portfolio view: only
the positions a roll can apply to.

### 5.5 Controls

`GET /options/controls` returns the autonomy rung, the halt state and its reason, the live/paper
mode, and whether `approval_service` is draining.

That last field needs its own signal. `/health`'s existing `worker_heartbeat` reports the
**research** worker (`src/research/ingest/jobs.py::read_heartbeat`) and says nothing about the
command drain. So the drain writes its own heartbeat into `system_settings` on every cycle, under
a `command_drain_heartbeat` key, and `drain_healthy` is that timestamp compared against twice the
poll interval. A drain that has never run reports `false` with a null timestamp. It must never
default to `true`, because the entire purpose of the field is to let the console say "your click
is queued and nothing is picking it up".

---

## 6. Command kinds in detail

### 6.1 `approve` and `reject`

Payload: `{approval_id}`. The drain calls `_process_button(approval_id, action)` and stores its
returned decision text in `result_json`.

**Nothing is reimplemented.** This is the load-bearing property of the whole design: the web
approve performs exactly the `ApprovalRow` mutation Telegram performs today, in the same
function, with the same `N2a` snapshot freeze and the same execution-time re-gate. Every safety
property already tested holds unchanged and the console inherits them rather than reproducing
them.

Telegram and the console can both act on the same approval. The second one to arrive sees a
non-`PENDING` status and reports "already decided", which the console renders as a neutral
outcome rather than an error.

### 6.2 `promote`

Payload: `{candidate_id, symbol, strategy, strike, expiry}`.

The drain re-runs the single-ticker scan path for that symbol, which fetches a fresh chain,
regenerates candidates, and re-gates them. If a candidate matching `(strategy, strike, expiry)`
comes back gate-passed, a `PENDING` approval is raised for it exactly as `send_candidates`
would, with a freshly frozen snapshot. If nothing matches, the command is marked `failed` with
the reason, which is one of: the contract no longer prices, the gate now rejects it, or the
chain fetch failed.

**The re-derivation is the safety property, not a cost.** A stored payload would let the operator
approve a premium the market has moved away from, and `risk_verdicts` rows live for fourteen
days. Re-deriving means a promote is always priced now and gated now, which is the same
discipline the executor already applies with `validate_live_quote`. A promote that gets refused
because the gate changed its mind is the system working.

### 6.3 `roll_request`

Payload: `{position_symbol}`.

The drain fetches the chain for the underlying and calls `queue_roll_for_approval`, which already
does everything else: it runs `generate_roll_candidates` with `defensive=True`, takes the best by
ROC, checks `has_active_order`, upserts the `CandidateRow`, and raises a `PENDING` `ApprovalRow`
with the frozen snapshot. The resulting roll appears in the approvals queue and is approved
through §6.1 like anything else.

Two steps, not one. The console never rolls a position directly; it asks the system to propose a
roll, and the operator then approves that proposal. `rolling.py`'s own `max_debit` and
`min_delta_reduction` bounds remain the roll's economic control, exactly as `CLAUDE.md`
describes.

If `generate_roll_candidates` returns nothing, the command is `failed` with "no qualifying roll",
which is a real answer and is rendered as one.

### 6.4 `halt`, `resume`, `set_autonomy`

Payloads: `{reason}`, `{}`, `{level}`. Each calls the existing `system_settings` helper. `halt`
is the kill switch and is the one control that must never be slow, so the console renders it
distinctly and confirms it with a typed word rather than a click, matching how consequential it
is.

`set_autonomy` accepts only the four defined rungs and refuses anything else at the API boundary,
before a command row is created.

### 6.5 `universe_add` and `universe_remove`

Payload: `{symbol, list_name}`. See §7.

### 6.6 `refresh`

Payload: `{}`. Asks the trading process to refresh positions and quotes on its next cycle, so the
console's `as_of` advances without waiting fifteen minutes. Carries no `dedupe_key`, because
repeating it is harmless.

---

## 7. Universe editing

### 7.1 Why it is not a simple CRUD screen

`config/universe.yaml → would_own` is read directly by `src/strategies/cash_secured_put.py:93`
to decide whether a symbol is CSP-eligible. Adding a symbol to `would_own` from a browser
changes what the system may be assigned shares of. That is the most consequential config edit in
the system and it deserves to be designed rather than shipped as a form.

`config/universe.yaml → sectors` is read by `src/engine/risk_engine.py:41` for concentration
limits. A browser click must not be able to move a risk limit.

### 7.2 The override surface is deliberately narrow

`list_name` accepts **`would_own` or `watchlist`, and nothing else**. The API rejects any other
list name with `422` before a command row exists.

That single restriction means `risk_engine.py` is never reachable from the web, because
`sectors` is not overridable. `leveraged_etfs` and `strike_bands` are likewise file-only. The
YAML remains the documented, comment-rich base for everything that is genuinely risk-shaping.

Two further guards:

- **Removing a symbol that sits in `actively_wheeling` is refused.** You cannot stop being
  willing to own something you are actively wheeling; the honest action is to stop wheeling it
  first, which is not a P2 capability.
- **Every override is reversible and audited.** `universe_overrides` stores deltas, never a
  rewritten file, so the base configuration is always recoverable and every change has an author
  and a timestamp.

### 7.3 How an override reaches a running process

```
universe_overrides(id, symbol, list_name, action, created_at, created_by)
        │
        ▼
src/common/universe.py :: effective_universe()      60-second TTL cache
        │
        ├──▶ src/strategies/cash_secured_put.py     would_own eligibility
        ├──▶ src/orchestrator/scan.py               symbol selection
        ├──▶ src/orchestrator/eod_report.py         watchlist reporting
        └──▶ src/api/routers/universe.py            the console's own view
```

`get_config()` is `@functools.lru_cache(maxsize=1)`, so anything composed at config load would be
invisible to running processes until every one of them restarts. Composing inside `get_config()`
would also make `src/common/config.py` import a storage module, and `get_config()` is called from
the risk engine, so a locked database at import time would become a trading failure.

A separate accessor with its own short TTL avoids both. An edit takes effect within a minute,
`config.py` keeps no database dependency, and the failure mode of an unreadable
`universe_overrides` table is "the YAML base is used", which is the safe direction.

### 7.4 Why this does not breach the fence

The fence forbids the enrichment learning loop from reaching the engine, the weights, the risk
limits, or sizing. `CLAUDE.md` is explicit that those "remain **human-edited config**".

An override is human-edited config. The human is editing it through a form instead of a text
editor, and the edit is stored as an auditable, reversible delta rather than a file rewrite.
Nothing in `src/claude/eval/`, `src/research/`, or any model output can create one: the only
writer is a `POST` carrying an authenticated owner's identity, recorded in `created_by`.

The fence test is extended to assert exactly that — that `universe_overrides` has no writer
reachable from `src.claude.eval`, `src.research`, or any summary backend.

### 7.5 The console surface

`GET /universe` flips from `editable: false` to `editable: true`, and each list reports whether
it accepts overrides. `would_own` and `watchlist` render add and remove actions; the other lists
render read-only with a note saying they are file-managed, which is more honest than hiding them.

An overridden entry renders distinctly from a YAML entry, with its author and timestamp, and
carries a revert action. The base file is always visible underneath.

---

## 8. Auth and the token

### 8.1 The problem P2 creates

`web/lib/api.ts` reads `NEXT_PUBLIC_API_TOKEN`, which Next.js inlines into the client bundle at
build time. Anything that can load `localhost:3000` — another local process, a browser extension
— can read that token out of the served JavaScript.

Today that leaks research reads. After P2 it leaks the ability to queue trades. Loopback binding
does not help here, because the attacker is already local by construction.

### 8.2 The fix

A Next.js route handler at `web/app/api/[...path]/route.ts` proxies to the API and injects the
token server-side from `API_TOKEN`, an environment variable with no `NEXT_PUBLIC_` prefix. The
client calls same-origin `/api/...` and never holds a credential.

- `web/lib/api.ts`'s `BASE` becomes `/api`, and its `Authorization` header is removed.
- `NEXT_PUBLIC_API_TOKEN` is deleted from `.env.example` and `SETUP.md`.
- `CurrentUser` and `src/api/auth.py` are untouched. The seam that a future real session system
  swaps into stays exactly where P0 put it.
- The proxy forwards `GET`, `POST` and `DELETE`, and refuses everything else.

This works unchanged under `next start` behind Tailscale later. **It does not survive a
Vercel-hosted frontend**, because a route handler running in Vercel's cloud cannot reach a
private API. That is a real limitation and §12 records it rather than papering over it.

### 8.3 Owner gating

Every `/options/*` route and every write is tagged `owner_only` and depends on `OwnerUser`, the
dependency P0 built and P1 never needed. P2 is where it earns its place.

---

## 9. Frontend

### 9.1 Routes and shell

`/options` and `/options/[approvalId]` are new. `/universe` gains its edit affordances.
`src/api/routers/meta.py` flips the `options` section to `available: true` and drops its
"Arrives in P2" note.

Every P1 convention in `P0-P1-design.md` §8 is inherited verbatim: the dark tokens, IBM Plex Sans
and Mono, tabular figures, elevation by lightness only, semantic colour only, state never encoded
by colour alone, `prefers-reduced-motion`, and the banned-copy list including zero em dashes.

### 9.2 The signature component: the command receipt

P1's differentiator was the check ribbon. P2's is the **command receipt**, and it exists to
answer one question the design considers the most dangerous in the whole phase: *did this
actually happen?*

Every write renders a receipt row that advances through real backend state:

```
queued      ▸ intent 41 accepted, waiting for the trading service
applied     ▸ approved, order queued for execution
submitted   ▸ working at IBKR, limit 2.45
filled      ▸ 2 contracts at 2.47
```

and, when it goes wrong:

```
failed      ▸ gate now rejects this contract: delta_out_of_band
```

Three rules govern it:

1. **`pending` never renders as `applied`.** A queued approval that reads as an executed one is
   the single most dangerous failure mode in this design, and `GET /commands/{id}` exists for
   exactly this. The states are visually and textually distinct, never distinguished by colour
   alone, and the receipt shows the intent id so an operator can always ask about a specific
   command.
2. **The UI never claims a trade happened until `OrderRow` says so.** `applied` means the
   approval was mutated. `filled` means a fill exists. Nothing interpolates between them.
3. **A stalled drain is stated, not hidden.** If the worker heartbeat is stale, a queued receipt
   says "the trading service is not draining commands" instead of spinning.

### 9.3 Confirmation

Anything that can reach an order confirms before the intent is created. Approve and promote take
a click-through confirm showing the exact contract and contract count. `halt` takes a typed
word, because a mis-click on the kill switch and a mis-click on Approve are not the same
mistake. In live mode the second confirmation of §4.6 is a distinct, clearly-labelled step, not
a repeat of the first.

### 9.4 Polling

TanStack Query, as P1. Commands with a `pending` status poll `GET /commands/{id}` every two
seconds until they resolve; everything else refreshes on the fifteen-minute cadence the data
actually has. No websockets and no SSE: the underlying data changes on a fifteen-minute clock
and a poll is honest about that.

---

## 10. Error handling and degradation

| Failure | Behaviour |
|---|---|
| `approval_service` down | Commands stay `pending`. `/health`'s worker heartbeat is stale, and every queued receipt says the service is not draining. Nothing is lost and nothing is claimed. |
| Drain crashes mid-apply | The command is retried on the next cycle and absorbed by the four idempotency layers of §4.5. |
| Chain fetch fails on promote or roll | The command is marked `failed` with the provider's reason, surfaced verbatim in the receipt. |
| Gate now rejects a promoted contract | `failed`, with the reason codes rendered through the same humaniser Telegram uses. This is a correct outcome, not an error state. |
| SQLite lock contention | Bounded backoff, then `503` carrying the last known `as_of`. The client falls back to its cache, per client rule 1. |
| Telegram decided first | The command applies, `_process_button` reports "already `<status>`", and the receipt renders it as a neutral outcome. |
| IBKR disconnected | Approvals still queue. `OrderRow`s stay `QUEUED` until the exec connection returns, which is existing behaviour. The console reports the connection state rather than implying the order is working. |

---

## 11. Testing

**Python.**

- **The write fence.** `tests/test_web_fence.py` gains: no module outside `src/api/commands.py`
  imports `get_command_engine`; the command writer touches no table but `app_commands`; a route
  holding the read-only session still raises `OperationalError` on an `INSERT`.
- **Every command kind**, table-driven, with three cases each: the applied path, an idempotent
  replay, and the failure path with its reason recorded in `result_json`.
- **Promote refuses `RISK_GATE` and `GENERATOR`**, with an explicit test per stage. This is the
  highest-value single test in P2.
- **Live mode blocks an unconfirmed order-reaching intent.** The drain must skip a command whose
  `confirm_token` is unresolved, asserted directly rather than through the UI.
- **`_process_button` is called, not reimplemented.** A test asserts the drain's approve path
  invokes it, so a future refactor cannot quietly fork the mutation.
- **Universe overrides**: a non-overridable `list_name` is refused; removing an
  `actively_wheeling` symbol is refused; `effective_universe()` composes and reverts correctly;
  an unreadable overrides table falls back to the YAML base.
- **`owner_only`** on every `/options/*` route and every write, asserted with a non-owner role.
- **Regression.** M3, M4, M5 and M7 touch trading code. Each runs the full suite, because a
  regression there is a trading regression.

**Frontend.** Vitest for the receipt state machine, including the assertion that `pending` never
renders as `applied`. React Testing Library for the confirmation flows. Playwright for the two
flows where a mistake is expensive: approving from the console, and editing the universe.

---

## 12. Risks and limitations

1. **The read-only invariant is genuinely relaxed.** "The API never writes to the trading
   database" becomes "the API writes exactly one table". §4.2 argues the trade is right, but it
   is a real weakening and the structural test in §11 is what keeps it honest. If that test is
   ever deleted, the guarantee is gone.
2. **Two surfaces can now act on one approval.** Telegram and the console. The idempotency layers
   cover it and the losing surface reports it neutrally, but an operator watching both will
   occasionally see a decision they did not make on the screen they are looking at.
3. **Promote costs a chain fetch.** Seconds, and it can fail. That is the price of never
   approving a stale premium, and the receipt makes the wait visible rather than hiding it.
4. **The BFF proxy does not survive a Vercel-hosted frontend.** §8.2. Remote hosting needs
   Tailscale first, and a public frontend would need real sessions rather than a shared token.
   Both are deliberately out of P2.
5. **Universe overrides change trading behaviour within a minute.** That is the point, and it is
   also the risk. The narrow surface of §7.2 is the mitigation: the widest thing an override can
   do is make a symbol CSP-eligible, and it cannot touch a concentration limit.
6. **No order ticket.** Some operators will want one. §4.3 explains why it is not here, and the
   assessed browser covers most of the real need.

---

## 13. Sequencing

| # | Milestone | Ends with |
|---|---|---|
| 1 | Write foundation | `app_commands`, the write-scoped engine, the drain loop, `POST /commands`, `GET /commands/{id}`, and the token out of the client bundle. Nothing user-visible. |
| 2 | Read surfaces | `/options/*` routes and the console page. Approvals, assessed, orders, shorts, controls. All read-only. |
| 3 | Approve and reject | The command receipt, the confirmation flow, the live second-confirm. The first teeth. |
| 4 | Promote | Re-derive and re-gate a `DEDUPE`, `TOP_N` or `SCORE_FLOOR` contract. |
| 5 | Roll on demand | `roll_request` reusing `queue_roll_for_approval`, hung off the open-shorts list. |
| 6 | Controls | Halt, resume, autonomy from the browser. |
| 7 | Universe editing | `universe_overrides`, `effective_universe()`, consumer migration, close-out and docs. |

Writes reach a user's hands only in milestone 3, after both the receipt UI and the token move
have landed. Milestones are strictly sequential and each ends green on the full quality gate.

---

## 14. Documentation obligations

Per `CLAUDE.md`'s mandatory doc-update rule:

| Trigger | Files |
|---|---|
| New storage models `AppCommandRow`, `UniverseOverrideRow` | `ARCHITECTURE.md` `src/storage/` + data-flow sections |
| New module `src/api/commands.py`, `src/common/universe.py` | `README.md` layout table, `ARCHITECTURE.md` folder guide |
| New API endpoints | `docs/web/api.md`, regenerate `docs/web/openapi.json` |
| The relaxed read-only invariant | root `CLAUDE.md`, `STATUS.md`, `docs/web/architecture.md` |
| Token handling change | `SETUP.md`, `.env.example` |
| P2 built, P3–P5 still deferred | `STATUS.md` web platform table |

A new `docs/web/commands.md` documents every command kind, its payload, its idempotency key, and
its failure modes. It is the runbook for the one part of the web layer that can move money.
