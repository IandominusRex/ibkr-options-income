# Web Platform P2 — Options Console — Implementation Plan (Index)

> **Complete.** All seven milestones shipped (M7 closed 2026-09-07). Milestone files live in
> `milestones/P2/`. See "Implementation log — M7 (universe editing)" below for M7's own
> account; M1-M6's completion records live in their own milestone files
> (`milestones/P2/M1-write-foundation.md` through `M6-controls.md`). This is the last phase this
> plan covers — see § "Verification before live" below for what live-cutover verification still
> needs to happen before `LIVE_TRADING=true`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the web console the ability to act on what the trading system proposed — approve,
reject, promote a gate-passed contract, roll a short, halt the system, and edit the universe —
without any of it becoming a second path to an order.

**Architecture:** No new processes. The existing FastAPI process (`src/api/`) gains a **second,
write-scoped SQLAlchemy engine** it may use for exactly one table, `app_commands`. Its read path
keeps the `mode=ro` engine untouched. `approval_service` gains a **command drain loop** beside
its existing order poll loop; every command kind terminates in a code path that already exists
and already gates. The Next.js client gains a **server-side proxy route** so the bearer token
leaves the browser bundle.

**Tech Stack:** unchanged from P0/P1. Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic 2 ·
Next.js App Router, TypeScript, Tailwind, TanStack Query · pytest, ruff, mypy, Vitest, Playwright.

**Spec:** `Web plan/P2-design.md` (read it first, in full). Context: `Web plan/OVERVIEW.md`.
Foundation this builds on: `Web plan/P0-P1-design.md`, shipped, milestone logs in
`Web plan/milestones/P0-P1/`.

---

## Global Constraints

Every task's requirements implicitly include this section.

**Repo-wide (from `CLAUDE.md`)**
- Python ≥ 3.12. Type-hint everything. Ruff line length 100.
- Quality gate before any task is complete: `python -m pytest -q` · `ruff check .` · `mypy src`
  and, for any task touching `web/`, `npx vitest run` · `npm run lint` · `npm run build`.
- Config in `config/*.yaml`; secrets only in `.env`, never logged or committed.
- Modules communicate only through Pydantic schemas. No raw `ib_async` objects across a boundary.
- Money is explicit; option premiums are per share.

**Inherited from P0/P1, still in force**
- Neither `src/api/` nor `src/research/` constructs an `ib_async` connection or holds a clientId.
- `data/research.db` keeps its own `Base`. It must not import `src/storage/models.py`'s `Base`.
- **One-way import fence:** `src/engine/`, `src/execution/` and `src/strategies/` may never
  import `src.api` or `src.research`. `src/research/checks/` may never import
  `src.research.summary`.
- Provenance envelope on every headline number; every response carries a top-level `as_of`.

**New invariants this plan introduces**
- **The API writes exactly one table.** The read path uses the `mode=ro` engine
  (`get_trading_engine`). The only read-write handle is `get_command_engine`, it lives in
  `src/api/commands.py`, and no other module may import it. Enforced by
  `tests/test_web_fence.py`, not by convention. **If that test is ever deleted, the guarantee is
  gone** — treat it as load-bearing.
- **`_process_button` is called, never reimplemented.** The web approve performs exactly the
  `ApprovalRow` mutation Telegram performs today, in the same function. A test asserts the drain
  invokes it, so a refactor cannot quietly fork the mutation.
- **Promote never bypasses the gate.** `RISK_GATE` and `GENERATOR` stages are refused at the API
  boundary with `409`, and the UI renders no promote affordance for them.
- **Universe overrides accept `would_own` and `watchlist` only.** Any other `list_name` is `422`
  before a command row exists, so `sectors` (and therefore `risk_engine.py`) is unreachable from
  the web.
- **`pending` never renders as `applied`.** The most dangerous failure mode in this phase. Has
  its own component, its own frontend test, and its own acceptance criterion in every write task.
- **No new process, no new clientId.**

**Live-mode rule**
- In live mode, any intent that can reach an order (`approve`, `promote`, `roll_request`) is
  created with a `confirm_token` and is skipped by the drain until confirmed. The existing
  execution-time `[CONFIRM LIVE]` path is untouched and still fires.

**Frontend rules (unchanged from P0/P1 spec §8)**
- Dark only. Every colour consumed through a semantic token (`bg-background`, `bg-surface`,
  `bg-elevated`, `text-content`, `text-muted`, `border-border`). **No raw `bg-white`,
  `bg-gray-*`, or hex literals in components.**
- Elevation by lightness, never shadow. Never stack a border and a shadow on one surface.
- IBM Plex Sans for UI, IBM Plex Mono for tickers, prices, financial cells. Tabular figures.
- Semantic colour only. **State is never encoded by colour alone** — fill and texture carry it
  too. This applies to receipt states exactly as it applied to check states.
- Every interactive element has hover, focus-visible, disabled, loading and empty states.
- `prefers-reduced-motion` disables all motion.
- **Zero em dashes in shipped UI copy.** Restructure the sentence instead.
- No fabricated precision, no decorative status dots, no section-number eyebrows, no fake
  version chrome, no icon-in-a-rounded-square above a heading.
- Banned words in UI copy: "seamless", "robust", "unlock", "elevate".

---

## Model routing

Tasks are tagged **`[GLM]`** or **`[SONNET]`**. Same split as P0/P1, by task property.

### Route to GLM 5.2 when *all* of these hold

1. The interface is fully specified in the task's `Interfaces` block.
2. Success is verifiable by test code the task already contains.
3. It touches at most three files and **no trading-system code**.
4. No `CLAUDE.md` invariant and no invariant from the section above is in scope.
5. External data shapes are known and fixed.

### Route to Sonnet when *any* of these hold

1. **It touches trading-system code** — `src/engine/`, `src/execution/`, `src/strategies/`,
   `src/orchestrator/`, `src/storage/models.py`, `src/notify/approval_service.py`, `src/claude/`.
2. **It enforces or tests an invariant** — the write fence, the import fence, `owner_only`,
   promote-stage refusal, the override surface, `pending` vs `applied`.
3. **It can cause an order to exist**, however indirectly.
4. **It requires a judgment call about degradation** — what the console shows when the drain is
   down, when a gate changes its mind, when Telegram decided first.
5. **It sets a pattern later tasks copy** — the first write route, the first drain handler, the
   receipt component.
6. **GLM has failed the task twice.** Escalate rather than iterating a third time.

### Escalation protocol

If a `[GLM]` task's tests still fail after two honest attempts, stop and re-run it on Sonnet. Do
not weaken the test to make it pass; the test is the specification. Record the escalation in the
task checkbox line.

---

## Routing summary

| Milestone | Task | Model | Why |
|---|---|---|---|
| M1 | 1.1 `AppCommandRow` + storage helpers | SONNET | Trading-system storage code |
| M1 | 1.2 Write-scoped command engine | SONNET | Relaxes the read-only invariant |
| M1 | 1.3 Command schemas + payload validation | GLM | Fixed shapes, given verbatim |
| M1 | 1.4 `POST /commands` · `GET /commands/{id}` | SONNET | First write route; sets the pattern |
| M1 | 1.5 Drain loop in `approval_service` | SONNET | Trading-system code; process model |
| M1 | 1.6 Write-fence test | SONNET | Enforces the new invariant |
| M1 | 1.7 Token out of the client bundle | SONNET | Security boundary; fails closed |
| M1 | 1.8 Docs: `commands.md`, `CLAUDE.md`, `STATUS.md` | GLM | Mechanical |
| M2 | 2.1 `/options/approvals` + detail | SONNET | First options router; four-table join |
| M2 | 2.2 `/options/assessed` + promotable flags | SONNET | Stage semantics; wrong = misleading |
| M2 | 2.3 `/options/orders` + `/options/fills` | GLM | Read-only query, pattern set by 2.1 |
| M2 | 2.4 `/options/shorts` | GLM | Read-only query |
| M2 | 2.5 `/options/controls` | GLM | Read-only query |
| M2 | 2.6 Console shell + approvals list | SONNET | Sets every frontend convention for the section |
| M2 | 2.7 Approval detail page | GLM | Pattern fixed by 2.6 |
| M2 | 2.8 Assessed browser UI | GLM | Pattern fixed by 2.6 |
| M2 | 2.9 Orders, fills and shorts panels | GLM | Pattern fixed by 2.6 |
| M3 | 3.1 `approve` / `reject` drain handlers | SONNET | **Trading code.** The core safety property |
| M3 | 3.2 Command receipt component | SONNET | Signature component; `pending` vs `applied` |
| M3 | 3.3 Confirmation dialog | GLM | Self-contained |
| M3 | 3.4 Wire approve / reject into the UI | GLM | Pattern fixed by 3.2 and 3.3 |
| M3 | 3.5 Live-mode second confirmation | SONNET | Safety gate; must fail closed |
| M3 | 3.6 Write-path test suite | SONNET | Enforces invariants |
| M4 | 4.1 Promotable-stage guard | SONNET | Enforces an invariant; refusal must be total |
| M4 | 4.2 `promote` drain handler | SONNET | **Trading code.** Hardest task in the plan |
| M4 | 4.3 Promote action + receipt | GLM | Pattern fixed by M3 |
| M4 | 4.4 Promote refusal tests | SONNET | Highest-value tests in P2 |
| M5 | 5.1 `roll_request` drain handler | SONNET | **Trading code.** Reuses the roll pipeline |
| M5 | 5.2 Roll action on the shorts list | GLM | Pattern fixed by M3 |
| M5 | 5.3 Roll alerts on the shorts list | GLM | Read-only rendering |
| M5 | 5.4 Roll degradation tests | SONNET | Degradation judgment |
| M6 | 6.1 `halt` / `resume` / `set_autonomy` handlers | SONNET | The kill switch |
| M6 | 6.2 Control-kind payload validation | GLM | Fixed enum, fully specified |
| M6 | 6.3 Controls panel + typed halt confirm | SONNET | Confirmation-weight judgment |
| M6 | 6.4 Controls tests | GLM | Pattern fixed by 3.6 |
| M7 | 7.1 `UniverseOverrideRow` + storage helpers | GLM | Fixed schema, given verbatim |
| M7 | 7.2 `effective_universe()` | SONNET | TTL cache; fallback semantics |
| M7 | 7.3 Migrate universe consumers | SONNET | **Trading code**, including a strategy |
| M7 | 7.4 `universe_add` / `universe_remove` | SONNET | Enforces the narrow override surface |
| M7 | 7.5 Universe edit UI | GLM | Standard CRUD over a settled API |
| M7 | 7.6 Fence test extension | SONNET | Enforces an invariant |
| M7 | 7.7 Close out P2 | GLM | Mechanical |

**Totals: 42 tasks, 18 GLM and 24 Sonnet.**

Sonnet concentrates in M1 (the invariant relaxation) and M3–M4 (the first write paths), which is
where a silent mistake is most expensive and least visible.

**Nine tasks modify trading-system code:** 1.1, 1.5, 3.1, 3.5, 4.2, 5.1, 7.1, 7.3, 7.4. P0/P1 had
one. That difference is the phase. Every one of them runs the **full** suite before completion,
because a regression there is a trading regression, not a web regression.

---

## Milestone files

| File | Ends with |
|---|---|
| `milestones/P2/M1-write-foundation.md` | Intent queue, write-scoped engine, drain loop, `/commands`, token out of the bundle. Nothing user-visible. |
| `milestones/P2/M2-read-surfaces.md` | The console page. Approvals, assessed, orders, shorts, controls. All read-only. |
| `milestones/P2/M3-approve-reject.md` | Approve and reject with receipts and confirmations. The first teeth. |
| `milestones/P2/M4-promote.md` | Promote a gate-passed contract, re-derived and re-gated. |
| `milestones/P2/M5-roll.md` | On-demand roll for any open short. |
| `milestones/P2/M6-controls.md` | Halt, resume and autonomy from the browser. |
| `milestones/P2/M7-universe-editing.md` | Universe overrides, consumer migration, close-out. |

Milestones are strictly sequential. Each ends green on the full quality gate and is shippable on
its own.

**Writes reach a user's hands only in M3**, after both the receipt component and the token move
have landed. M1 and M2 are deliberately inert: M1 builds the machinery with no UI, M2 builds the
UI with no writes.

---

## Verification before live

P2 ships against paper. Before any of it runs with `LIVE_TRADING=true`:

1. Every command kind exercised end-to-end against paper, with the receipt observed advancing to
   `filled` at least once.
2. The live second-confirmation path (§4.6) exercised in paper by temporarily forcing the live
   branch, so the drain's skip behaviour is observed rather than assumed.
3. A deliberate drain outage: stop `approval_service`, queue a command, confirm the console says
   the service is not draining and claims nothing, then restart and confirm the command applies
   exactly once.
4. A deliberate double-decision: decide the same approval in Telegram and the console, and
   confirm the losing surface reports it neutrally and no second order is created.

Record the results in `STATUS.md`, the way M4's live browser verification was recorded.

---

## Documentation obligations

Per `CLAUDE.md`'s mandatory doc-update rule, these are **not optional** and each is folded into
the task whose deliverable creates the obligation:

| Trigger in this plan | Task | Files |
|---|---|---|
| New storage models `AppCommandRow`, `UniverseOverrideRow` | 1.1, 7.1 | `ARCHITECTURE.md` `src/storage/` + data-flow sections |
| New modules `src/api/commands.py`, `src/common/universe.py` | 1.2, 7.2 | `README.md` layout table, `ARCHITECTURE.md` folder guide |
| New API endpoints | each router task | `docs/web/api.md`, regenerate `docs/web/openapi.json` |
| New command kind | 1.4, 3.1, 4.2, 5.1, 6.1, 7.4 | `docs/web/commands.md` |
| The relaxed read-only invariant | 1.2, 1.6 | root `CLAUDE.md`, `STATUS.md`, `docs/web/architecture.md` |
| Token handling change | 1.7 | `SETUP.md`, `.env.example`, `web/CLAUDE.md` |
| New config key | as they arise | `ARCHITECTURE.md` config section, `SETUP.md` |
| P2 built, P3–P5 still deferred | 1.8, 7.7 | `STATUS.md` web platform table |

`docs/web/commands.md` is new and is the runbook for the one part of the web layer that can move
money. Every command kind gets its payload, its idempotency key, its failure modes, and what an
operator should do when it fails.

---

## Implementation log — M7 (universe editing, 2026-09-07)

M7 makes `would_own` and `watchlist` editable from the browser as reversible, audited deltas over
`config/universe.yaml`, which stays the documented base — and closes out the whole P2 phase.
Tasks 7.1-7.6 landed as GLM/Sonnet work per the routing table above (`c31f808` through `6d74e4c`);
this entry (Task 7.7) is the close-out pass: docs, the schema/type regen, and this log.

### What each task shipped

**Task 7.1 — the override store.** `UniverseOverrideRow` (`src/storage/models.py`), unique on
`(symbol, list_name)`, holding one row per operator add/remove: upper-cased `symbol`,
`action: "add"|"remove"`, `created_by`/`created_at`. `src/storage/universe_overrides.py`'s
`set_override`/`clear_override`/`all_overrides` each take an explicit `session`, mirroring
`app_commands.py`'s shape. `set_override` is a **total-replace upsert** — a later call for the
same `(symbol, list_name)` overwrites `action`, `created_by`, and `created_at` in place, so an
add followed by a remove is one row, never two to reconcile at read time.

**Task 7.2 — the composer.** `src/common/universe.py::effective_universe()` composes
`universe_overrides` onto `get_config().universe`. `OVERRIDABLE_LISTS =
frozenset({"would_own", "watchlist"})` — every other key (`sectors`, `strike_bands`, `indexes`,
`actively_wheeling`, `leveraged_etfs`) passes through byte-identical, proven even against a
stray override row inserted directly under `list_name="sectors"` (defence in depth: the API and
schema already refuse it before a row can exist; the composer refuses it again). A `remove`
override on a symbol currently in `actively_wheeling` is ignored when composing `would_own`
specifically. A 60-second TTL cache (`(dict, time.monotonic())`, module-level) avoids a DB
round-trip on every read; `invalidate_universe_cache()` is the drain's escape hatch. An
unreadable overrides table (locked SQLite, missing table, anything) is caught broadly, logs a
warning, and returns the YAML base untouched — never raises, never empties the universe.
Composed-list ordering is deterministic: YAML file order minus removed symbols, then added
symbols appended in `created_at` order.

**Task 7.3 — six consumers migrated** from `get_config().universe` to `effective_universe()`:
`src/strategies/cash_secured_put.py` (the CSP eligibility check — the single most consequential
edit in the milestone, proven end-to-end by a test that adds an override and confirms
`generate_csp_candidates` actually changes its output), `src/orchestrator/scan.py` (symbol
selection), `src/orchestrator/eod_report.py` (two sites: the daily IV-history refresh set and
the EOD watchlist report), `src/api/routers/universe.py`, and `src/api/routers/research.py`
(two sites). `src/engine/risk_engine.py`, `src/ibkr/market_data.py`'s `strike_bands`, and every
`actively_wheeling`/`sectors` read elsewhere are deliberately untouched — not overridable. An
autouse `tests/conftest.py` fixture resets the TTL cache around every test, once `scan.py`
started reading through the cache (mirrors the pre-existing `_clear_daily_caches` pattern).

**Task 7.4 — the write path.** `GET /universe` reshaped: `lists: [{name, overridable, entries:
[{symbol, overridden, removed, created_by, created_at}]}]` — four lists (`indexes`, `watchlist`,
`would_own`, `actively_wheeling`, in that order), only the latter two `overridable`; `editable`
flips to `true`. `would_own`/`watchlist` entries are the **union** of the YAML base and every
override row for that list, not just the filtered effective list, so a removed YAML-base symbol
stays visible (greyed out) with a revert path. New routes `POST`/`DELETE
/universe/{list_name}/{symbol}` (owner-only, thin wrappers over the same command-queue path
`POST /commands` uses): `list_name` is a `Literal["would_own", "watchlist"]` path parameter so
any other value is `422` before any command row can exist (proven for
`sectors`/`leveraged_etfs`/`strike_bands`/`actively_wheeling`); an unknown symbol (checked
against the research symbol directory) is `404`; removing an `actively_wheeling` symbol
specifically from `would_own` (not `watchlist` — that guard is `would_own`-only, mirroring the
composer's own scoping) is `409`. Drain handlers `_universe_add`/`_universe_remove`
(`src/notify/command_drain.py`) call `set_override` (never `clear_override` — a remove is always
recorded as an explicit override row, even for a YAML-base symbol, because deleting the row
would silently do nothing for one) and `invalidate_universe_cache()` immediately after, so an
edit is live in the process that applied it within the same drain cycle rather than up to 60
seconds later. Neither handler ever fails (every validation already happened at the API
boundary) or sends a Telegram notification (deliberately, unlike halt/resume/set_autonomy — a
universe edit is reversible non-urgent config, not a safety-critical control).

**Task 7.5 — the frontend.** `web/components/universe/{UniverseList,OverrideBadge,AddSymbol}.tsx`,
a rewritten `web/app/universe/page.tsx` consuming the new `lists[]` shape, `web/lib/commands.ts`
gains `submitUniverseCommand`. Add/remove controls render only on `would_own`/`watchlist`;
`indexes`/`actively_wheeling` render read-only with a note that they're managed in
`config/universe.yaml`. Adding to `would_own` opens a confirmation naming the actual consequence
(the system may sell cash-secured puts on the symbol and the operator may be assigned its
shares); adding to `watchlist` fires immediately, no dialog (a reporting list, never reaches an
order). An overridden entry renders `OverrideBadge` (author, timestamp, a revert control that
fires the opposite action of the entry's current state). The symbol picker is a typeahead over
`GET /research/search` — a typo cannot become a `404`. Every mutation renders `CommandReceipt`
and stops polling at a terminal command status. The wheeling-vs-dip-watch tag the pre-M7 page
showed within `would_own` was preserved.

**Task 7.6 — the fence.** `tests/test_web_fence.py` gains three tests: no module under
`src/claude/eval/` or `src/research/` can write a universe override (`universe_overrides`/
`set_override` string-absent check); `src/engine/risk_engine.py` never mentions
`effective_universe`/`universe_overrides` anywhere in its text; `OVERRIDABLE_LISTS ==
frozenset({"would_own", "watchlist"})` exactly, pinned so a future widening fails here first.

**Task 7.7 — close out P2 (this entry).** `STATUS.md`'s P2 row gains the M7 paragraph in the
same dense style as M5/M6, and the "Not built" sentence is replaced with the explicit
no-order-ticket/no-Tailscale/no-`sectors`-override/P3-P5-deferred statement. Root `CLAUDE.md`'s
"The web layer and the trading database" section gains the two remaining P2 facts (the drain/
`_process_button` invariant, the `would_own`/`watchlist`-only override surface) beside the
`app_commands` fact an earlier P2 milestone already put there, plus a doc-update trigger row for
new command kinds. `README.md`'s layout table gains rows/extensions for `src/api/commands.py`,
`src/storage/universe_overrides.py`, `src/execution/{promote_pipeline,roll_pipeline}.py`,
`src/notify/command_drain.py`, and `web/app/options/` — `src/common/universe.py` already had a
row from Task 7.2, confirmed rather than duplicated. `SETUP.md` gains a "Using the options
console" section mirroring "Using the Telegram bot"'s shape (intro paragraph + table), covering
approvals, promote, roll requests, halt/resume/autonomy, and universe editing with the
`would_own` consequence spelled out; the `API_TOKEN`/`WEB_API_TOKEN` distinction from Task 1.7
was already documented (§6a and the troubleshooting table) and was left untouched.
`ARCHITECTURE.md`'s folder guide had three stale entries from when this milestone was mid-flight
— the `models.py`/`universe_overrides.py` entries still said "nothing reads this table yet" and
`routers/universe.py`'s entry still described the read-only P1 shape with `editable: false` —
corrected to the shipped state, and `command_drain.py`'s entry gained the `universe_add`/
`universe_remove` paragraph the other five handler kinds already had. `docs/web/openapi.json`
and `web/lib/api-types.ts` regenerated from `create_app().openapi()`; the new `/universe/
{list_name}/{symbol}` routes and the reshaped `UniverseResponse` are present in both.

### What was escalated

One fix-loop round across the whole milestone, in Task 7.4: the initial cut of `GET /universe`'s
entries-union silently dropped a genuinely reachable state — a symbol added via override and
then removed again, leaving a single non-base row with `action="remove"` and no corresponding
base-list entry to attach it to. The union logic as first written only ever walked the YAML
`base` list and separately appended override rows whose `action == "add"`, so a non-base
`remove` row (which represents real provenance — an operator who added a symbol and then
un-added it — and a state the UI should still be able to show/revert) fell through both loops
and never appeared in `entries` at all. Fixed so every override row for a non-base symbol
appears in `entries`, tagged `removed = (action == "remove")`, sorted by `created_at` alongside
the `add` rows in the same append order `_compose_list` uses. Every other task's review was
clean or Minor-only on the first pass.

### Every ruling made along the way

1. `effective_universe()` reads overrides via `src.storage.db.session_scope()`, not
   `src.api.trading_db.trading_session()` — keeps `src/common/config.py` free of any storage
   import while still working from both the exec process and the API process.
2. `GET /universe`'s reshaped response (`lists[]`/`entries` with `overridden`/`removed`/
   `created_by`/`created_at`) was fully specified before the write-path task started, including
   the union-not-filtered-list design that keeps removed YAML-base symbols visible for a revert.
3. Task 7.4's scope was extended to include rewriting `tests/test_api_universe.py` (the milestone
   file's own task list omitted it, but the new response shape made the old flat-shape tests
   break necessarily) and `docs/web/api.md`.
4. A pre-existing doc stub in `docs/web/commands.md` (written speculatively before this milestone
   ran) claimed `universe_add`/`universe_remove` could fail with `unknown_symbol`/
   `already_in_list`/`not_in_list` as **drain** failure reasons. Corrected: all validation
   happens at the API boundary (`422`/`404`/`409`) before a command row can exist, so a command
   that reaches the drain always applies — the drain handlers have no failure reasons of their
   own.
5. The `actively_wheeling`-removal `409` guard is scoped to `would_own` only, not `watchlist`
   (mirrors the composer's own guard scoping — watchlist membership doesn't gate CSP
   eligibility).
6. `POST`/`DELETE /universe/{list_name}/{symbol}` require the owner role, deliberately diverging
   from the P1 `watchlist.py` precedent's any-authenticated-role gate on its analogous
   single-symbol routes — these change CSP eligibility, watchlist membership does not.
7. Task 7.5's UI satisfies "no control exists on the sectors list" (the milestone text's literal
   wording) via the two real non-overridable sections (`indexes`/`actively_wheeling`) rather than
   inventing a `sectors` list-section the shipped backend never has — `sectors` stayed a flat
   per-symbol annotation map, unchanged from before this milestone.
8. Task 7.4's fix-loop round (see "What was escalated" above) was the only one needed across the
   whole milestone; every other task's review was clean or Minor-only on the first pass.
9. (Task 7.7) The brief's literal cross-check command,
   `grep -o 'reason="[a-z_]*"' src/notify/command_drain.py`, matches nothing against the shipped
   code — every failure reason is raised as `CommandFailed("reason_string", ...)` (a positional
   argument) or `_fail(cmd.id, "reason_string")`, never as a `reason="..."` keyword literal. Ran
   the semantically equivalent check instead: extracted every string literal passed to
   `CommandFailed`/`_fail` (`approval_not_found`, `broker_unavailable`, `chain_unavailable`,
   `contract_not_priced`, `gate_rejected`, `score_below_minimum`, `position_not_found`,
   `not_an_open_short`, `no_qualifying_roll`, `roll_already_working`, `promotion_refused`,
   `unknown_kind`, `handler_error`) and confirmed each appears in `docs/web/commands.md`. All
   present; no changes needed there. Separately noticed (not fixed, out of this task's scope):
   `docs/web/commands.md`'s `refresh` section still says "Applied by: M6. Triggers a full scan on
   the next cycle," but `refresh` has no registered handler in `command_drain.py` — a pre-existing
   inaccuracy `STATUS.md`'s own P2 row already flagged before this pass ("`refresh`'s handler
   ... remains unregistered") and unrelated to universe editing.
10. (Task 7.7) `Web plan/milestones/P2/M7-universe-editing.md`'s own checkboxes (31 across all
    seven tasks plus the acceptance list) were still unchecked despite every task being shipped
    and committed — the file was never updated to reflect completion the way `M6-controls.md`
    was by its own close-out commit. Checked off as part of this close-out pass, with a short
    completion banner added after the acceptance list pointing back to this log for the full
    account, since the M7-file's own file list in Task 7.7's brief didn't call it out explicitly
    but leaving a "closed-out" milestone's own tracking file showing zero completed tasks would
    misrepresent the phase's status to the next reader.

### Minor findings deferred, not fixed (recorded for completeness, per the brief's template)

- `src/storage/universe_overrides.py`: an unused `logging` import (dead code) — left in place;
  Task 7.7 is documentation-only and the brief's own commit instructions scope generated/derived
  changes to the openapi/api-types regeneration alone.
- `README.md`'s layout table did not have a row for `src/storage/universe_overrides.py`
  specifically (Task 7.1's own file list didn't ask for it) — added in this pass.
- `tests/test_universe_consumers.py` has a local autouse cache-reset fixture now redundant with
  the global one Task 7.3 added to `tests/conftest.py`.
- `src/common/universe.py`'s two `remove_guard`-named variables at different scopes (naming
  clarity nit, not a bug).
- `eod_report.py`'s `_universe_symbols(cfg)` retains a now-unused `cfg` parameter.
- `web/CLAUDE.md`'s `components/universe/` bullet slightly over-attributes
  `submitUniverseCommand`/`CommandReceipt` behaviour to `OverrideBadge` (purely presentational).
- `AddSymbol.tsx`/`UniverseList.tsx` each have their own small `describeError` function with
  slightly different case coverage (403/404 vs 403/404/409) — a reasonable divergence, not true
  duplication.

None of these block the milestone or the phase.

### Final gate (2026-09-07)

`python -m pytest -q` — 1920 passed. `ruff check .` — clean. `mypy src` — clean.
`cd web && npx vitest run` — 203 passed (28 files). `npm run lint` — clean. `npm run build` —
clean (`/options`, `/options/[approvalId]`, `/universe`, `/`, `/stock/[symbol]` all compile and
prerender). All six green — P2 is complete.

**Acceptance, independently re-verified in this pass, not just re-asserted:**
`would_own`/`watchlist` are editable from the browser and the edit changes CSP eligibility
(`tests/test_universe_consumers.py`'s end-to-end `generate_csp_candidates` test, Task 7.3).
`sectors` cannot be overridden through the API, the schema, or the composer, even via a row
inserted directly into the table (`tests/test_effective_universe.py`,
`tests/test_api_universe.py`, Task 7.6's `test_the_overridable_set_matches_the_spec_exactly`).
`risk_engine.py` still reads `get_config()` and imports nothing from the override path
(`tests/test_web_fence.py::test_the_risk_engine_never_reads_an_override`, verified by direct
`grep` against the file's own text during this pass, not just by re-running the test). Removing
an `actively_wheeling` symbol from `would_own` is refused at the API (`409`) and ignored by the
composer. An unreadable overrides table falls back to the YAML base. Adding to `would_own`
carries a confirmation naming the assignment consequence. No enrichment layer can write an
override (`tests/test_web_fence.py::test_no_enrichment_layer_can_write_a_universe_override`).
Every command reason in the code appears in `docs/web/commands.md` (re-derived fresh in this
pass — see ruling 9 above). `STATUS.md` records P2 as built and P3-P5 as still deferred.
