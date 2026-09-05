# Milestone 2 — Read Surfaces

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The options console exists and is worth opening, while still being completely unable to
do anything. Every read surface P2 needs, and the page that renders them.

**Spec:** `Web plan/P2-design.md` §5 (read surfaces), §9.1 (routes and shell).
**Index:** `Web plan/P2-IMPLEMENTATION-PLAN.md`. **Depends on:** Milestone 1.

**The discipline of this milestone:** no writes, no action buttons, no affordance that implies a
capability that does not exist yet. Client rule 3 from `P0-P1-design.md` §4.5 applies literally:
never claim more than the backend did. An Approve button that does nothing is worse than no
button.

---

## Task 2.1 — `GET /options/approvals` and the detail route `[SONNET]`

**First options router. It sets the join pattern the rest of the milestone copies.**

**Context.** An approval is only legible when joined to four other tables. `ApprovalRow` carries
the frozen `snapshot`; `CandidateRow` carries the full payload; `RiskVerdictRow` carries the
gate's reasons and the ideal zone; `ClaudeReviewRow` carries the five review fields Telegram
renders as one prose blob. All four read through the `mode=ro` engine.

**Files:** Create `src/api/routers/options.py`, `src/api/models/options.py`. Modify
`src/api/main.py`, `docs/web/api.md`. Test `tests/test_api_approvals.py`.

**Interfaces:**

```
GET /options/approvals?status=pending&limit=50
  → {as_of, approvals: [ApprovalSummary]}

GET /options/approvals/{id}
  → ApprovalDetail   404 if unknown
```

```python
class ApprovalSummary(Envelope):
    id: int
    candidate_id: str
    status: Literal["pending", "approved", "rejected", "expired"]
    underlying: str
    strategy: str
    right: str
    strike: float
    expiry: date | None
    contracts: int
    premium: float                    # per share, always
    blended_score: float | None
    expires_at: datetime | None
    decided_at: datetime | None
    order_state: str | None           # joined from OrderRow when one exists
    source: Literal["scan", "roll"]   # derived from the candidate's run_id prefix


class ApprovalDetail(ApprovalSummary):
    snapshot: dict                    # the frozen payload the human was shown
    ideal: IdealZonePayload | None    # lo, hi, min_credit, from RiskVerdictRow
    gate_reasons: list[str]           # humanised, via the same mapper the formatters use
    review: ClaudeReviewPayload | None    # the five fields, separately, never one blob
    alternatives: list[AlternativeStrike]  # other contracts assessed on this underlying
```

Required behaviours, each with a test:
- **Owner only.** A non-owner role gets `403` on both routes.
- `status=pending` is the default. `status=all` returns decided approvals too, newest first.
- An approval whose `CandidateRow` has been pruned still renders from `snapshot` alone, with
  `ideal` and `review` `null`. **The snapshot is the source of truth for what was shown**; the
  joined rows are enrichment and their absence must never 500.
- `premium` is per share. A test asserts the value equals the stored per-share number and is not
  multiplied by 100 anywhere in the route.
- `order_state` is `null` when no order exists, never `"none"` and never `""`.
- `review` renders `why_attractive`, `risks`, `tradeoffs`, `assignment_considerations` and
  `rolling_considerations` as **five separate fields**. A test asserts they are not concatenated.
- Empty table returns `200` with an empty list, not `404`.

- [ ] Write the tests, implement, regenerate `docs/web/openapi.json`, update `docs/web/api.md`,
  run the gate, commit.

---

## Task 2.2 — `GET /options/assessed` `[SONNET]`

**The stage semantics are the whole task. Getting them wrong makes the console misleading.**

**Context.** `risk_verdicts` already stores every contract the scan priced, with its
`AssessmentStage`, reason codes, score, premium and denormalised ideal zone. Spec §5.2 defines
exactly which stages are promotable and why.

**Files:** Modify `src/api/routers/options.py`, `src/api/models/options.py`, `docs/web/api.md`.
Test `tests/test_api_assessed.py`.

**Interfaces:**

```
GET /options/assessed?run=latest&symbol=&stage=&limit=200
  → {as_of, run_id, computed_at, groups: [AssessedGroup]}
```

```python
class AssessedContract(Envelope):
    candidate_id: str
    symbol: str
    strategy: str
    strike: float | None
    expiry: date | None
    stage: Literal["generator", "risk_gate", "score_floor", "dedupe", "top_n", "passed"]
    reasons: list[str]              # raw codes
    reasons_text: list[str]         # humanised, same mapper the Telegram formatters use
    blended_score: float | None
    premium: float | None
    ideal: IdealZonePayload | None
    promotable: bool
    promote_note: str | None        # why not, when promotable is false


class AssessedGroup(Envelope):
    symbol: str
    contracts: list[AssessedContract]
    counts: dict[str, int]          # per stage
```

**The promotable table, from spec §5.2. Implement it exactly:**

| Stage | `promotable` | `promote_note` |
|---|---|---|
| `generator` | `false` | "Failed a strategy filter, so the system never priced it as a candidate." |
| `risk_gate` | `false` | "The Rules Engine rejected this contract." |
| `score_floor` | `true` | "Scores below your configured minimum of {min}." |
| `dedupe` | `true` | `null` |
| `top_n` | `true` | `null` |
| `passed` | `false` | "Already surfaced for approval." |

Required behaviours, each with a test:
- **`risk_gate` and `generator` are never promotable**, one explicit test per stage. This is the
  invariant; treat these two tests as load-bearing.
- `score_floor` is promotable and its note carries the **actual** configured
  `min_candidate_score`, read from config, not hardcoded.
- `run=latest` resolves to the newest non-`scan-`-prefixed `run_id`, matching how
  `latest_buy_candidates` filters single-ticker runs. A `/scan NVDA` must not become "the latest
  run" for the assessed browser either.
- Groups are ordered by best contract first, using the same ranking idea as
  `scan.py::_rank_assessed`: promotable before non-promotable, then score descending.
- `reasons_text` never returns a raw code. If a code has no humanisation, it falls back to the
  code with underscores replaced, never an empty string.

- [ ] Write the tests, implement, update the docs, run the gate, commit.

---

## Task 2.3 — `GET /options/orders` and `GET /options/fills` `[GLM]`

**Files:** Modify `src/api/routers/options.py`, `src/api/models/options.py`, `docs/web/api.md`.
Test `tests/test_api_orders.py`.

**Interfaces:**

```
GET /options/orders?state=working&limit=50
  → {as_of, orders: [OrderSummary]}
GET /options/fills?days=7&limit=100
  → {as_of, fills: [FillSummary]}
```

```python
class OrderSummary(Envelope):
    id: int
    candidate_id: str
    approval_id: int | None
    underlying: str
    strategy: str
    strike: float
    expiry: date | None
    state: Literal["queued", "submitted", "filled", "partial", "cancelled", "rejected"]
    limit_price: float | None
    filled_qty: float
    avg_fill_price: float | None
    is_live: bool
    detail: str | None
    created_at: datetime
    updated_at: datetime
```

Required behaviours, each with a test:
- Owner only.
- `state=working` means `queued`, `submitted` or `partial`. `state=all` means everything.
- `underlying`/`strategy`/`strike` come from the order's `snapshot`, falling back to the joined
  `CandidateRow`, so a pruned candidate does not blank the row.
- `avg_fill_price` is `null` for an unfilled order, never `0.0`. A test locks this: a fabricated
  zero fill price is the kind of thing an operator reads as real.
- Empty result is `200` with an empty list.

- [ ] Write the tests, implement, update the docs, run the gate, commit.

---

## Task 2.4 — `GET /options/shorts` `[GLM]`

**Files:** Modify `src/api/routers/options.py`, `src/api/models/options.py`, `docs/web/api.md`.
Test `tests/test_api_shorts.py`.

**Interfaces:**

```
GET /options/shorts  → {as_of, shorts: [ShortPosition]}
```

```python
class ShortPosition(Envelope):
    position_symbol: str            # the OCC option symbol
    underlying: str
    right: Literal["C", "P"]
    strike: float
    expiry: date
    dte: int
    contracts: int
    avg_cost: float | None
    mark: float | None
    unrealized_pnl: float | None
    pnl_pct: float | None
    delta: Sourced[float] | None    # provenance matters: BS-derived is not IBKR-derived
    assignment_risk: bool
    alerts: list[RollAlertSummary]  # RollAlertRow rows fired against this position
```

Required behaviours, each with a test:
- Owner only.
- Reads the **most recent** `position_snapshots` rows, and the response's `as_of` is the
  snapshot's capture time, **not** request time. This is the exact bug M4 of P0/P1 had to fix for
  quotes; do not reintroduce it here.
- Only short option positions are returned. Long options and stock are excluded.
- `delta` carries its source through `Sourced`, so a Black-Scholes delta never looks identical to
  an IBKR one.
- A position with no snapshot data returns `null` for `mark` and `unrealized_pnl`, never `0.0`.
- `alerts` is empty, not `null`, when nothing has fired.

- [ ] Write the tests, implement, update the docs, run the gate, commit.

---

## Task 2.5 — `GET /options/controls` `[GLM]`

**Files:** Modify `src/api/routers/options.py`, `src/api/models/options.py`, `docs/web/api.md`.
Test `tests/test_api_controls.py`.

**Interfaces:**

```
GET /options/controls → {
    as_of,
    autonomy: {level, rungs: [...]},
    halted: bool,
    halt_reason: str | null,
    mode: "paper" | "live",
    drain_healthy: bool,
    drain_last_seen: datetime | null,
    pending_commands: int,
}
```

Required behaviours, each with a test:
- Owner only.
- `autonomy.level` reads through `get_autonomy_level()`, and `rungs` lists all four in ladder
  order so the UI does not hardcode them.
- `mode` derives from `cfg.is_live`. A test asserts both branches.
- **`drain_healthy` is honest, and reads the right key.** It compares
  `system_settings["command_drain_heartbeat"]` (written by the drain in Task 1.5) against twice
  `execution.poll_interval_seconds`. **Do not reuse `/health`'s `worker_heartbeat`** — that one
  reports the *research* worker and would show green while the command drain is dead, which is
  precisely the failure this field exists to catch. A drain that has never run is `false` with
  `drain_last_seen: null`. It must never default to `true`.
- `pending_commands` counts `status="pending"` rows.

- [ ] Write the tests, implement, update the docs, run the gate, commit.

---

## Task 2.6 — Console shell and the approvals list `[SONNET]`

**Sets every frontend convention for the section.** Later tasks copy it, so getting it wrong
multiplies.

**Files:** Create `web/app/options/page.tsx`,
`web/components/options/{ApprovalsList,ApprovalCard,StageBadge,EmptyState}.tsx`. Modify
`src/api/routers/meta.py`, `web/CLAUDE.md`. Test
`web/components/options/ApprovalsList.test.tsx`.

**Interfaces:** consumes `GET /options/approvals` (2.1) and `GET /options/controls` (2.5).

- [ ] **Step 1: Flip the rail.** In `src/api/routers/meta.py`, change the `options` section to
  `("options", "Options", True, None)`. Update `tests/test_api_meta.py` (or wherever the nav
  assertions live) so the change is asserted, not incidental.

- [ ] **Step 2: Build the page.** Layout, top to bottom:
  1. A controls strip: mode (paper/live), autonomy rung, halt state, drain health. Read-only in
     M2. If `drain_healthy` is false, this strip says so in words.
  2. Pending approvals as cards.
  3. Tabs or segments for Assessed, Orders, Shorts. They render in 2.7 through 2.9; in this task
     they may render an empty shell, but **not** a "coming soon" placeholder — this section is
     shipping now.

- [ ] **Step 3: The card.** Contract label, contracts, premium per share and total, score, ideal
  zone, expiry countdown, and the five review fields when present. All P1 §8 rules apply:
  semantic tokens only, IBM Plex Mono for every number, tabular figures, no em dashes, no
  decorative status dots.

  **No action buttons in this milestone.** Not disabled ones either. An operator must not see an
  Approve control that cannot approve.

- [ ] **Step 4: States.** Loading, empty, and error each designed. Empty is one line of text plus
  nothing else, per §8.1's table: no icon circle above a heading.

- [ ] **Step 5: Tests.** Renders a list; renders the empty state; renders review fields
  separately; **asserts no button with an accessible name matching /approve|reject/i exists**.
  That last one is what stops a later task quietly shipping a dead control.

- [ ] **Step 6:** Record the new component directory in `web/CLAUDE.md`. Run all six gate
  commands. Commit.

---

## Task 2.7 — Approval detail page `[GLM]`

**Files:** Create `web/app/options/[approvalId]/page.tsx`,
`web/components/options/{ApprovalDetail,IdealZoneBar,ReviewPanel,AlternativesTable}.tsx`. Test
`web/components/options/ApprovalDetail.test.tsx`.

**Interfaces:** consumes `GET /options/approvals/{id}` (2.1).

Required behaviours, each with a test:
- The five review fields render as five labelled sections, never one paragraph.
- `gate_reasons` render as humanised text, not raw codes.
- The ideal zone renders as a bar with the actual premium marked against `lo`, `hi` and
  `min_credit`, with numbers visible. No fabricated precision: render at the precision the source
  provides.
- A `null` `review` renders nothing at all, not "No review available" in a bordered box.
- `404` renders a real not-found state with a link back to the list.
- No action buttons. Same rule as 2.6.

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Task 2.8 — Assessed browser UI `[GLM]`

**Files:** Create `web/components/options/{AssessedBrowser,AssessedRow,StageFilter}.tsx`. Modify
`web/app/options/page.tsx`. Test `web/components/options/AssessedBrowser.test.tsx`.

**Interfaces:** consumes `GET /options/assessed` (2.2).

This is the surface the iOS spec called the most useful output the system produces and the one
Telegram renders worst. Treat it as a real feature, not a debug dump.

Required behaviours, each with a test:
- Grouped by symbol, collapsible, with per-stage counts in the group header.
- Filterable by stage and by symbol.
- **Stage is never communicated by colour alone.** Each stage gets a text label plus a distinct
  fill or texture, exactly as the P1 check ribbon handles state. Reuse that visual language;
  do not invent a second one.
- A non-promotable row renders its `promote_note` as plain text. **It renders no promote control
  and no disabled promote control.** The action arrives in M4 and only for promotable rows.
- Empty run renders one line of text.

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Task 2.9 — Orders, fills and shorts panels `[GLM]`

**Files:** Create `web/components/options/{OrdersTable,FillsTable,ShortsTable}.tsx`. Modify
`web/app/options/page.tsx`. Test `web/components/options/OrdersTable.test.tsx`,
`ShortsTable.test.tsx`.

**Interfaces:** consumes `GET /options/orders`, `GET /options/fills` (2.3), `GET /options/shorts`
(2.4).

Required behaviours, each with a test:
- Order state renders with a label and a distinct fill, never colour alone.
- A `null` `avg_fill_price` renders `n/a`, never `0.00`. A `null` `mark` likewise. This is the
  same rule P1's `TechnicalsPanel` follows and the tests should mirror its assertions.
- `delta` renders its source, so an operator can see a Black-Scholes delta is not an IBKR one.
- The shorts table shows the snapshot's real age as text, not a dot, per §8.7.
- A fired roll alert renders on its position's row as text.
- **No roll button.** It arrives in M5.

- [ ] Write the tests, implement, run all six gate commands, commit.

---

## Milestone 2 acceptance

- [ ] `/options` is in the rail as available, and the page renders approvals, assessed contracts,
  orders, fills, shorts and the controls strip against real data.
- [ ] `risk_gate` and `generator` contracts report `promotable: false` and render no promote
  control, disabled or otherwise.
- [ ] Every route is `owner_only` and a non-owner gets `403`.
- [ ] No `null` numeric renders as `0`. Asserted for `avg_fill_price`, `mark`,
  `unrealized_pnl` and `blended_score`.
- [ ] `as_of` on the shorts route is the snapshot's capture time, not request time.
- [ ] `drain_healthy` is `false` when the drain has never run.
- [ ] **No control anywhere in the section can cause a write.** A frontend test asserts no
  approve, reject, promote or roll button exists.
- [ ] `docs/web/api.md` and `docs/web/openapi.json` cover every new route, and
  `web/lib/api-types.ts` is regenerated.
- [ ] Full gate green, all six commands.
