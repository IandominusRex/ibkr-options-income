# Web Platform P2 — Options Console — Implementation Plan (Index)

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
