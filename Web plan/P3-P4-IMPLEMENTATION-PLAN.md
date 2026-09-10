# Web Platform P3 + P4 — Portfolio and Profitability — Implementation Plan (Index)

> **Not started.** Milestone files live in `milestones/P3-P4/`. Written 2026-09-09 against
> `Web plan/P3-P4-design.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the web platform a portfolio the operator can trust to be current, and a
profitability ledger that says what every trade actually earned — without adding a second path to
an order, and without a second implementation of the accounting rule.

**Architecture:** No new processes, no new clientIds, no relaxation of P2's write fence. A new
`portfolio_snapshots` table is written by two processes that already hold IB connections (the
intraday monitor, and the command drain via a newly registered `refresh` handler); the API reads it
through the unchanged `mode=ro` engine. A new deterministic package, `src/reporting/`, owns
paired realised P&L — and it owns it by **taking over** the two pure functions
(`_fill_economics`, `_classify`) that already implement that rule inside
`src/claude/eval/reconcile.py`, inverting the dependency so the fenced module imports the neutral
one rather than the reverse.

**Milestone 0 comes first and builds nothing.** Writing the design meant reading the code it sits
on, then auditing what P0, P1 and P2 shipped. That found nine pre-existing defects this phase would
otherwise be built on top of — including a repeated EOD run that raises before the reconciler and
the position snapshot ever run, and a BFF proxy that hands the browser an HTML error page whenever
the API is down. M0 closes them and records a measured baseline. It is not optional and it is not
P3/P4 work; it is the cost of building on this foundation honestly.

**Tech Stack:** unchanged from P0/P1/P2. Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic 2 ·
Next.js App Router, TypeScript, Tailwind, TanStack Query, Recharts · pytest, ruff, mypy, Vitest,
Playwright.

**Spec:** `Web plan/P3-P4-design.md` (read it first, in full). Context: `Web plan/OVERVIEW.md`.
Foundation this builds on: `Web plan/P0-P1-design.md` and `Web plan/P2-design.md`, both shipped,
milestone logs in `Web plan/milestones/P0-P1/` and `Web plan/milestones/P2/`.

---

## Global Constraints

Every task's requirements implicitly include this section.

**Repo-wide (from `CLAUDE.md`)**
- Python ≥ 3.12. Type-hint everything. Ruff line length 100.
- Quality gate before any task is complete: `python -m pytest -q` · `ruff check .` · `mypy src`
  and, for any task touching `web/`, `npx vitest run` · `npm run lint` · `npm run build`.
- Config in `config/*.yaml`; secrets only in `.env`, never logged or committed.
- Modules communicate only through Pydantic schemas. No raw `ib_async` objects across a boundary.
- Money is explicit; option premiums are per share (×100 for contract value).

**Inherited from P0/P1/P2, still in force**
- Neither `src/api/` nor `src/research/` constructs an `ib_async` connection or holds a clientId.
- **The API writes exactly one table, `app_commands`, through `src/api/commands.py`.** P3 and P4
  do **not** relax this. `portfolio_snapshots` is written by trading processes only.
- `_process_button` is called, never reimplemented. Promote never bypasses the gate. Universe
  overrides accept `would_own` and `watchlist` only.
- `data/research.db` keeps its own `Base`. It must not import `src/storage/models.py`'s `Base`.
- **One-way import fence:** `src/engine/`, `src/execution/` and `src/strategies/` may never import
  `src.api` or `src.research`.
- Provenance envelope on every headline number; every response carries a top-level `as_of`.

**New invariants this plan introduces**
- **`src/reporting/` is a third analytics tier: read-only, downstream of everything, upstream of
  nothing.** `src/engine/`, `src/execution/` and `src/strategies/` may never import it, and it may
  never import `src.claude`. Enforced by `tests/test_web_fence.py`, not by convention.
- **One accounting rule.** After Task 4.1 there is exactly one implementation of
  `fill_economics` and `classify_outcome` in the repo. A second one is a defect regardless of how
  well it is tested.
- **`position_snapshots` is not touched.** Assignment auto-detection keeps its one-row-per-ET-day
  contract. Any change to that table is out of scope for this phase.
- **A realised figure is never `0.0` when it is unknown.** `PnlLeg.net_pnl` is `None` while the
  leg is open, and the UI renders `None` as `n/a` with hatch texture. This has its own test in
  every task that produces or renders a money figure.
- **The monitor's snapshot write may never propagate an exception.** Tick handling and roll alerts
  outrank it.
- **No new process, no new clientId, no new command kind but `refresh`.**

**Frontend rules (unchanged from P0/P1 spec §8 and `web/CLAUDE.md`)**
- Dark only. Every colour consumed through a semantic token (`bg-background`, `bg-surface`,
  `bg-elevated`, `text-content`, `text-muted`, `border-border`, `text-gain`, `text-loss`,
  `text-unknown`). **No raw `bg-white`, `bg-gray-*`, or hex literals in components.**
- Elevation by lightness, never shadow. Never stack a border and a shadow on one surface.
- IBM Plex Sans for UI, IBM Plex Mono for tickers, prices, financial cells. `.tabular` on every
  numeric column.
- Semantic colour only. **State is never encoded by colour alone** — a negative figure carries a
  minus sign and a label, not just `text-loss`.
- **Charts never animate their data in.** A bar that grows on mount lies about its value during
  the animation. A gap in a series renders as a gap, never as an interpolated line.
- Every interactive element has hover, focus-visible, disabled, loading and empty states.
- `prefers-reduced-motion` disables all motion.
- **Zero em dashes in shipped UI copy.** Restructure the sentence instead.
- No fabricated precision, no decorative status dots, no section-number eyebrows, no fake version
  chrome, no icon-in-a-rounded-square above a heading.
- Banned words in UI copy: "seamless", "robust", "unlock", "elevate".

---

## Model routing

Tasks are tagged **`[GLM]`** or **`[SONNET]`**. Same shape as P0/P1 and P2, with one criterion
added and the verification protocol made mandatory rather than advisory. Read the honest
assessment below before trusting the tags.

### An honest read of GLM's record in this repo

The routing tables in P0/P1 and P2 were written against **GLM 5.2**. This phase assumes **GLM
5.3**. That is a real difference and it is worth being precise about what is and is not known.

**What is known**, from the implementation logs in `milestones/P0-P1/M7-ai-summary.md` and
`milestones/P2/`:

*Where GLM was genuinely reliable.* The three HTTP summary backends (`anthropic.py`,
`openai.py`, `ollama.py`) were code-reviewed line by line and found correct, including their
fail-soft timeout and malformed-response handling. `protocol.py`, `context.py` and `factory.py`
matched the full specified field set on inspection with no changes needed. P2's Task 7.5 — a
standard CRUD UI over a settled API — landed clean. Documentation tasks were discharged
accurately. When the interface is fully specified and the work is "build this shape", the output
was good.

*Where it failed, three distinct ways, none of them raw coding ability:*

1. **Completion claims were unreliable.** Sonnet's hardening pass on P0/P1 M7 opened with "nothing
   GLM's log claimed was 'committed' actually was" — `git status` showed every file untracked or
   modified. Separately, a task log claimed "all six spec behaviours" were tested when only five
   were; the sixth was implemented correctly but had zero coverage. The gate numbers it reported
   were real; the claims about what had been committed and tested were not. This is recorded in
   the project memory as a standing instruction: verify git status, test counts and regenerated
   artifacts yourself.
2. **"Reuse this, do not build a second one" was not reliably obeyed.** Task 7.2's brief said to
   reuse `src/claude/runner.py`'s CLI invoker. GLM built a second `subprocess.run` call and
   command list instead, with no cost logging and no retry handling — "exactly what the task text
   says not to do". A fully specified interface did not protect against this, because the failure
   was not in the interface; it was in noticing that an existing implementation was the point.
3. **Test form and placement drifted from the plan.** Tests landed in a combined file rather than
   the plan-named ones, and a fence test landed as an explicitly labelled "stand-in" rather than
   the specified form. The behaviour was often right; the artifact the plan asked for was not what
   arrived.

**What is not known.** There is no measured record of GLM 5.3 in this repository. Every data point
above is 5.2. A version bump plausibly improves code quality, and if it does, failure mode (1) may
soften along with it — but (1) and (3) are reporting and instruction-adherence behaviours, and (2)
is a judgment behaviour, and version bumps historically move those less than they move raw code
quality. **So the routing criteria below do not loosen on the strength of a version number.** If
5.3 outperforms this on P3/P4, tighten the criteria in P5 with evidence from this phase, not with
optimism ahead of it.

The practical consequence: GLM is routed here to roughly half the tasks, all of them in the same
category the record supports — specified shapes over settled interfaces, with tests supplied in
the task — and none of them where the deliverable is "notice that this already exists".

### Route to GLM 5.3 when *all* of these hold

1. The interface is fully specified in the task's `Interfaces` block.
2. Success is verifiable by test code the task already contains.
3. It touches at most three files and **no trading-system code**.
4. No `CLAUDE.md` invariant and no invariant from the Global Constraints section is in scope.
5. External data shapes are known and fixed.
6. **The task does not turn on reusing an existing implementation.** New criterion, added from
   failure mode (2) above.

### Route to Sonnet when *any* of these hold

1. **It touches trading-system code** — `src/engine/`, `src/execution/`, `src/strategies/`,
   `src/orchestrator/`, `src/monitor/`, `src/storage/models.py`,
   `src/notify/approval_service.py`, `src/notify/command_drain.py`, `src/claude/`.
2. **It enforces or tests an invariant** — the write fence, the `src/reporting/` import fence, the
   single-accounting-rule rule, `owner_only`, `None`-never-renders-as-zero.
3. **It can cause an order to exist**, however indirectly. (Nothing in this phase should. A task
   where this is even arguable is a Sonnet task and probably a design bug.)
4. **It requires a judgment call about degradation** — what the portfolio shows when no snapshot
   exists, what the ledger shows when a commission is missing, what the equity curve shows across
   a gap.
5. **It sets a pattern later tasks copy** — the first portfolio route, the money cell, the first
   `/pnl` route.
6. **Its deliverable is "reuse what exists rather than write a new one".** Task 4.1 is the whole
   milestone-4 example and is the single highest-risk task in the phase.
7. **GLM has failed the task twice.** Escalate rather than iterating a third time.

### Escalation protocol

If a `[GLM]` task's tests still fail after two honest attempts, stop and re-run it on Sonnet. Do
not weaken the test to make it pass; the test is the specification. Record the escalation in the
task checkbox line.

### Verification protocol — mandatory, not advisory

**A task is not complete because its worker said so.** Before accepting any task, GLM or Sonnet:

1. `git status` and `git log --oneline -3` — was it actually committed, and is the tree clean?
2. The test count delta — did the suite grow by the number of tests the task specified? A task
   that adds "six behaviours, each with a test" and grows the suite by five is not done.
3. `grep` for the test names the task named. A test that exists under a different name in a
   different file is a plan deviation, and it needs a recorded ruling, not a silent accept.
4. For any task listing regenerated artifacts (`docs/web/openapi.json`, `web/lib/api-types.ts`):
   regenerate them yourself and confirm the diff is empty.
5. Run the gate commands yourself for the milestone's final task. Reported numbers are evidence
   only once you have reproduced them.

This protocol exists because it caught real defects in P0/P1 M7. It costs minutes. Skipping it
cost a full hardening pass.

---

## Routing summary

| Milestone | Task | Model | Why |
|---|---|---|---|
| M0 | 0.1 Establish a known baseline | SONNET | Judgment about an unattributed working tree; has a human checkpoint |
| M0 | 0.2 Make the EOD run idempotent | SONNET | **Trading code.** A repeat run currently skips reconciliation |
| M0 | 0.3 One assignment-risk predicate | SONNET | **Trading code**; two callers must agree |
| M0 | 0.4 Pin the campaign rollup's commission semantics | SONNET | **Trading code**; a semantics ruling M4 depends on |
| M0 | 0.5 Enforce schema-artifact freshness with a test | SONNET | Enforces an invariant three later tasks rely on |
| M0 | 0.6 Correct the `refresh` runbook entry | GLM | Documentation only |
| M0 | 0.7 Clear P2's deferred findings | GLM | Mechanical cleanup, four small items |
| M0 | 0.8 Proxy fails soft when the API is down | SONNET | Touches the P2 security boundary; degradation judgment |
| M0 | 0.9 One `as_utc` | SONNET | Reuse is the deliverable (criterion 6) |
| M0 | 0.10 Consolidate + strengthen the fence tests | SONNET | Enforces an invariant `CLAUDE.md` calls load-bearing |
| M1 | 1.1 `PortfolioSnapshotRow` + storage helpers | SONNET | Trading-system storage code |
| M1 | 1.2 Config keys + retention prune | GLM | Fixed shapes, pattern already exists |
| M1 | 1.3 The monitor snapshot writer | SONNET | **Trading code**, inside a live event loop |
| M1 | 1.4 `refresh` drain handler | SONNET | **Trading code**; the phase's only write |
| M1 | 1.5 The snapshot read helper + fallback chain | SONNET | Degradation judgment; sets the pattern |
| M1 | 1.6 Docs: `commands.md`, `ARCHITECTURE`, `README`, `STATUS` | GLM | Mechanical |
| M2 | 2.1 `GET /portfolio/summary` | SONNET | First portfolio router; sets every convention |
| M2 | 2.2 `GET /portfolio/positions` | SONNET | Adjusted-basis semantics; wrong = misleading |
| M2 | 2.3 `GET /portfolio/campaigns` | GLM | Read-only query, pattern set by 2.1 |
| M2 | 2.4 `GET /portfolio/calendar` | GLM | Read-only query |
| M2 | 2.5 Docs + openapi/type regen | GLM | Mechanical |
| M3 | 3.1 The money cell + freshness label | SONNET | Signature component; `None` vs `$0.00` |
| M3 | 3.2 Portfolio shell + summary panel | SONNET | Sets every frontend convention for the section |
| M3 | 3.3 Position groups | GLM | Pattern fixed by 3.1 and 3.2 |
| M3 | 3.4 Campaign threads | GLM | Pattern fixed by 3.2 |
| M3 | 3.5 Calendar panel + refresh control | GLM | Reuses P2's `CommandReceipt` unchanged |
| M3 | 3.6 Nav flip + docs | GLM | Mechanical |
| M4 | 4.1 Extract the accounting rule into `src/reporting/legs.py` | SONNET | **Highest-risk task in the phase.** Trading-adjacent; reuse is the deliverable |
| M4 | 4.2 P&L schemas | GLM | Fixed shapes, given verbatim |
| M4 | 4.3 `build_legs` | SONNET | The accounting; a silent error is a wrong P&L |
| M4 | 4.4 `build_campaigns` | SONNET | Stock leg + marks; degradation judgment |
| M4 | 4.5 `build_summary` | GLM | Pure aggregation over a settled type |
| M4 | 4.6 `equity_curve` | SONNET | Gap semantics; the honesty constraint |
| M4 | 4.7 Wheel-scenario suite + the reporting fence | SONNET | Highest-value tests in P4 |
| M5 | 5.1 `GET /pnl/ledger` + `/pnl/summary` | SONNET | First `/pnl` router; sets the pattern |
| M5 | 5.2 `GET /pnl/equity` | GLM | Read-only query, pattern set by 5.1 |
| M5 | 5.3 `GET /pnl/ledger.csv` + proxy header allowlist | SONNET | Touches the P2 security boundary |
| M5 | 5.4 The ledger table UI | GLM | Standard table over a settled API |
| M5 | 5.5 Equity curve chart | GLM | Self-contained; rules given verbatim |
| M5 | 5.6 Breakdown panels | GLM | Pattern fixed by 5.4 |
| M5 | 5.7 Nav flip + docs + regen | GLM | Mechanical |
| M6 | 6.1 `GET /pnl/system` | SONNET | Reads behind the fence; the verbatim-notes rule |
| M6 | 6.2 System performance UI | GLM | Rendering over a settled schema |
| M6 | 6.3 Fence test extensions | SONNET | Enforces the new invariants |
| M6 | 6.4 Close out P3 + P4 | GLM | Mechanical |

**Totals: 45 tasks, 20 GLM and 25 Sonnet** — M0 10, M1 6, M2 5, M3 6, M4 7, M5 7, M6 4.

**Seven tasks modify trading-system code:** 0.2, 0.3, 0.4, 1.1, 1.3, 1.4 and 4.1. P2 had nine,
P0/P1 had one. Every one of them runs the **full** suite before completion, because a regression
there is a trading regression, not a web regression.

**M0 is Sonnet-heavy (eight of ten) and that is deliberate.** Every task in it edits existing code
that other things already depend on, to fix defects nobody in this phase introduced — which is
precisely the shape the GLM criteria exclude. Three of its tasks change trading behaviour, one
changes a security boundary, and two have "reuse what exists rather than write a new one" as their
literal deliverable, which is criterion 6. Its two GLM tasks are a documentation correction and a
four-item cleanup, both fully specified.

Task 4.1 deserves separate mention. It moves two functions that decide whether a closed trade is
recorded as assigned or expired, and what P&L the outcome ledger stores. Its safety property is
that **`reconcile.py`'s existing test suite must pass unchanged** — not adapted, not relaxed. If
that suite needs editing to go green, the extraction changed behaviour and the task is wrong.

---

## Milestone files

| File | Ends with |
|---|---|
| `milestones/P3-P4/M0-baseline-and-fixes.md` | A recorded baseline and nine pre-existing defects closed. **No new capability.** |
| `milestones/P3-P4/M1-portfolio-spine.md` | `portfolio_snapshots`, the monitor writer, the `refresh` handler, the fallback chain. Nothing user-visible. |
| `milestones/P3-P4/M2-portfolio-api.md` | `/portfolio/*` read routes. |
| `milestones/P3-P4/M3-portfolio-ui.md` | The portfolio page. The money cell. Nav flips `portfolio`. |
| `milestones/P3-P4/M4-pnl-engine.md` | `src/reporting/`, the dependency inversion, the accounting rules. No routes. |
| `milestones/P3-P4/M5-pnl-surfaces.md` | `/pnl/*`, the ledger page, the equity curve, CSV export. Nav flips `pnl`. |
| `milestones/P3-P4/M6-system-performance.md` | `/pnl/system`, the fence extensions, close-out. |

Milestones are strictly sequential. Each ends green on the full quality gate and is shippable on
its own.

**M0 comes before any P3 or P4 work and is not optional.** Writing the design meant reading the
code it sits on, then auditing what P0, P1 and P2 shipped. That turned up nine defects that
predate this phase and are
load-bearing for it — most consequentially, that a repeated EOD run raises before the reconciler
and the position snapshot ever run, so the day is never reconciled and tomorrow's assignment
baseline is never written. M4's realised-P&L cross-check and M1's `eod` fallback rung both depend
on those two steps. Building P3 and P4 on top of that and fixing it afterwards would mean
diagnosing failures in new code that new code did not cause.

**M1 and M4 are deliberately inert.** M1 builds the data spine with no UI; M4 builds the
accounting with no routes. Both exist so the first screen of their half renders real numbers on
its first day rather than placeholders that get replaced.

---

## Verification before live

P3 and P4 ship against paper, and neither can create an order, so the live-cutover risk is lower
than P2's. Three things still need observing against a running paper system before the phase is
called done:

1. **The monitor writes snapshots on its own for a full session**, and the portfolio's `as_of`
   advances on the expected cadence without anyone clicking anything.
2. **A deliberate monitor outage:** stop the monitor, confirm the portfolio ages visibly and says
   how old it is rather than going blank or claiming currency, then restart and confirm it
   recovers.
3. **A `refresh` end-to-end**, with the receipt observed advancing to `applied` and the portfolio's
   `as_of` jumping to the new `captured_at`.

Additionally, before P4's numbers are trusted for anything that matters: **reconcile one closed
campaign by hand** against the IBKR statement, and record the comparison. The ledger's first real
test is whether it agrees with the broker, and no unit test can establish that.

Record the results in `STATUS.md`, the way P2's milestone verifications were recorded.

---

## Documentation obligations

Per `CLAUDE.md`'s mandatory doc-update rule, these are **not optional** and each is folded into
the task whose deliverable creates the obligation:

| Trigger in this plan | Task | Files |
|---|---|---|
| The EOD run becomes idempotent | 0.2 | `ARCHITECTURE.md` `src/orchestrator/` section, `SETUP.md` troubleshooting table |
| New module `src/common/assignment_risk.py`, and `/options/shorts` widens what it flags | 0.3 | `README.md` layout table, `ARCHITECTURE.md` folder guide + `/options/shorts` description |
| `campaigns.net_premium` documented as gross of commissions | 0.4 | `src/storage/models.py` docstring, `ARCHITECTURE.md` `src/storage/` section |
| `refresh` documented honestly as unregistered | 0.6 | `docs/web/commands.md` |
| The proxy's failure contract (`502`/`504`, JSON detail) | 0.8 | `web/CLAUDE.md` "API proxy" section |
| New storage model `PortfolioSnapshotRow` | 1.1 | `ARCHITECTURE.md` `src/storage/` + data-flow sections |
| New modules `src/storage/portfolio_snapshots.py`, `src/api/portfolio_source.py` | 1.1, 1.5 | `README.md` layout table, `ARCHITECTURE.md` folder guide |
| New package `src/reporting/` | 4.1 | `README.md` layout table, `ARCHITECTURE.md` folder guide, root `CLAUDE.md` analytics-tier section |
| New Pydantic schemas | 4.2 | `ARCHITECTURE.md` `src/common/` + data-flow sections |
| New config keys | 1.2 | `ARCHITECTURE.md` config section, `SETUP.md` |
| `refresh` becomes a registered command kind | 1.4 | `docs/web/commands.md` — replacing the honest "unregistered" stub Task 0.6 left |
| New API endpoints | 2.5, 5.7, 6.4 | `docs/web/api.md`, regenerate `docs/web/openapi.json` and `web/lib/api-types.ts` |
| New frontend components | 3.6, 5.7 | `web/CLAUDE.md` layout section |
| The `src/reporting/` import fence | 4.1, 6.3 | root `CLAUDE.md`, `docs/web/architecture.md`, `STATUS.md` |
| P3 and P4 built, P5 still deferred | 1.6, 6.4 | `STATUS.md` web platform table |

**Task 0.5 changes how every regeneration obligation above is enforced.** Before it, "regenerate
`docs/web/openapi.json`" was a step somebody had to remember, and the record says it gets forgotten
— `docs/web/openapi.json` is stale right now, and a previous phase's close-out found
`web/lib/api-types.ts` stale by three whole endpoints. After 0.5, a stale artifact fails
`tests/test_openapi_current.py`, so the gate catches it rather than the next reader.

`docs/web/commands.md`'s `refresh` section currently claims "Applied by: M6. Triggers a full scan
on the next cycle" — which describes neither the handler that does not exist nor the one Task 1.4
builds. Task 0.6 corrects it to the truth as of today; Task 1.4 then replaces that with the shipped
behaviour. Two edits rather than one, deliberately: leaving a false runbook entry standing through
an entire milestone is the thing worth avoiding, not the second edit.

## Implementation log — M6 (system performance and close-out, 2026-09-11)

M6 gives the score-vs-outcome evidence `src/claude/eval/score_metrics.py` already produced its
first reader, locks the two fences this phase leans on with tests rather than intention, and
closes out the whole P3-P4 phase. Tasks 6.1-6.3 landed as straight implementation against the
milestone's own spec; this entry (Task 6.4) is the close-out pass.

### What each task shipped

**Task 6.1 — `GET /pnl/system`.** `VerdictAgreement`/`SystemPerformanceResponse`
(`src/api/models/pnl.py`) and the route itself (`src/api/routers/pnl.py`) call
`score_outcome_report(since, until)` and return exactly what it gets — a test spies on the
patched function and asserts exactly one call, and a second test diffs the response's buckets
and correlations against a direct call to the same function. A new `_verdict_agreement` helper
reads `src.claude.eval.ledger.load_records(closed_only=True)`, windows it on `outcome_date` the
same way the report windows itself, and computes `agreement_rate` (the ledger's own
scan-time `agreement` flag, never recomputed) plus `claude_win_rate`/`baseline_win_rate` (win
rate among the trades each side recommended selling) — all three `null` with zero closed rows,
never `0.0`. The route needs no `TradingDb` session: `score_outcome_report`/`load_records` read
through `src.storage.db.session_scope()` directly, the same access path every other `eval/`
consumer uses, which is exactly why the route's own docstring and `docs/web/api.md` spell out
that this is the fence's intended use rather than a second read path around it. `tests/conftest.py`
gained `seed_closed_ledger_rows(n, offset_days)`, alongside the existing `seed_wheel_ledger`,
writing directly through `record_verdicts` with no `CandidateRow`/fill dependency (the ledger
table carries no foreign key) — `offset_days` namespaces `candidate_id` and sets `outcome_date`
so a since/until window test can seed two date cohorts without one upsert clobbering the other.

**Task 6.2 — the System tab.** `SystemPanel`/`ScoreBucketTable`/`CorrelationTable`
(`web/components/pnl/`), wired into `PnlShell` as a third tab. `SystemPanel` is presentational —
a `data: SystemPerformanceResponse` prop, like `EquityChart`, not self-fetching like
`SummaryPanel` — because the test file's own `render(<SystemPanel data={aReport()} />)` calls
carry no `QueryClientProvider`; `PnlShell` owns the `useQuery` call and a second, independent
since/until window state (the ledger/equity/summary filters are a different axis — opened-date
vs. `outcome_date`). Every note renders in full and in order via a plain `<ul>`; a `ScoreBucket`
with `n` under 5 is labelled "small sample" in words beside the count; `report.n_closed === 0`
renders the notes and no tables at all (not empty tables with `n/a` rows); the two date inputs
carry `data-role="window-control"` and a test asserts they are the *only*
button/input/select anywhere in the panel. `ScoreOutcomeReport`'s array fields
(`blended_score_buckets`/`component_buckets`/`signal_correlations`/`notes`) are optional in the
generated OpenAPI type (Pydantic's `default_factory=list` serialises as an optional property),
so `SystemPanel` normalises each with `?? []` before handing it to a child component.
`web/lib/api-types.ts` was regenerated by pointing `openapi-typescript` at the already-current
`docs/web/openapi.json` file directly, not via `npm run gen:api`'s hardcoded
`http://127.0.0.1:8787` — a live API instance was already running on that port for other
purposes at the time and was deliberately left untouched; the output is byte-identical to what
`gen:api` would have produced from the same schema.

**Task 6.3 — five new fence tests** (`tests/test_web_fence.py`): no module under `src/api/` can
write the verdict ledger (`record_verdicts`/`update_outcome`/`mark_filled`/`VerdictLedgerRow(`)
or reference the scoring config by filename; the API still writes exactly one table, re-asserting
the P2 guarantee with the same `trading_db.py` exception `test_only_the_command_module_holds_a_
write_handle` already carries (that module *defines* `get_command_engine`/`command_session`,
it does not use them to reach a second table); `src/reporting/` never calls a session
add/merge/delete/commit; `save_portfolio_snapshot` still has exactly its two intended callers.
Root `CLAUDE.md`'s "The web layer and the trading database" section gained the one-sentence
summary the milestone asked for.

**Task 6.4 — close out P3 and P4 (this entry).** Re-derived every item in the milestone's
verification checklist rather than trusting an earlier task did it: `STATUS.md`'s P4 row gained
the M6 paragraph (same dense style as M4/M5) plus a "Not built" sentence — neither the P3 nor
the P4 row had one before this pass. Root `CLAUDE.md` gained a doc-update trigger row for new
`src/reporting/` modules; its analytics-tier section already named `src/reporting/` as the
third tier (M4) and needed no change. `README.md`'s layout table and `ARCHITECTURE.md`'s folder
guide (the `intraday.py`/`command_drain.py`/`reconcile.py` entries this task was told to check)
were already accurate for every P3/P4 module — confirmed by direct grep/read, not assumed.
Every command failure reason in `src/notify/command_drain.py` was re-extracted (correctly this
time — Python, not the milestone's own single-line grep, which misses the multi-line
`CommandFailed(\n    "score_below_minimum", ...)` call the same way the P2 close-out log
already flagged a similar gap) and confirmed present in `docs/web/commands.md`; none were
missing. `docs/web/openapi.json` and `web/lib/api-types.ts` both confirmed to regenerate to an
empty diff. All six milestone-6 checkboxes and its acceptance list were ticked to match what
actually shipped.

### What was escalated

None. Every task's tests passed against the code as written, apart from the one real trip
recorded under "Every ruling made along the way" below (found and fixed within Task 6.3, not
escalated past it).

### Every ruling made along the way

1. Task 6.3's literal `test_the_api_still_writes_exactly_one_table` (as given in the milestone
   text) skips only `commands.py`. Run as written, it fails on `src/api/trading_db.py`, which
   *defines* `get_command_engine`/`command_session` — the same reason
   `test_only_the_command_module_holds_a_write_handle` (P2) already excludes that file. Added
   `trading_db.py` to this test's skip set too, mirroring the existing P2 test's allowed set
   rather than narrowing the invariant.
2. Running the tests above surfaced a real, if harmless, trip: `pnl_system`'s own docstring
   (Task 6.1) named the scoring config by its literal filename in explanatory prose, which
   `test_no_web_module_can_write_a_scoring_weight`'s blunt substring check does not distinguish
   from a code reference. Reworded the docstring rather than weakening the test — the fence's
   point is that the name should be ungreppable from `src/api/`, not merely absent from
   executable code, so the docstring was the thing to fix. `docs/web/openapi.json` and
   `web/lib/api-types.ts` were regenerated a second time for the description-text change this
   produced in the OpenAPI schema (a route's docstring is its OpenAPI operation description).
3. `VerdictAgreement`'s `claude_win_rate`/`baseline_win_rate` are win rates among the trades
   *that side recommended selling* (`claude_recommendation == "sell"` /
   `baseline_recommendation == "sell"`), not a rate over every closed row — the milestone's
   interface names the fields but not the exact population; this reading matches the docstring
   ("how each did") and gives the two rates something to actually contrast.
4. `_verdict_agreement` computes its own windowed closed set from `load_records(closed_only=True)`
   rather than reusing `score_outcome_report`'s internal `_closed` list — the two functions
   already use slightly different closed-row definitions (`filled=True` + `realized_pnl is not
   None` for the report vs. `outcome in _TERMINAL` + `realized_pnl is not None` for the ledger
   helper), and the milestone's own "Consumes" line names `load_records(closed_only=True)`
   explicitly for the agreement figure. Left both definitions as they already were; reconciling
   them was out of this milestone's scope.
5. `web/lib/api-types.ts` was regenerated by running `openapi-typescript` against the
   already-regenerated `docs/web/openapi.json` file path, not the live-server URL
   `npm run gen:api` hardcodes — a real, already-running API instance occupied port 8787 for
   the duration of this work and was left alone rather than restarted. The output is identical
   either way, since both paths feed the same JSON into the same generator; documented here so
   a future `git blame` on `api-types.ts` doesn't wonder why `gen:api` wasn't run literally.
6. M0's (`M0-baseline-and-fixes.md`) own checkboxes were still unticked (0 of ~60) at this pass's
   close, despite the milestone plainly being shipped (M1 already depended on it and was itself
   fully built). Left untouched here: the milestone's own file list for this task names "all six
   milestone files" (M1-M6), and M0 predates that count. Recorded as a deferred finding rather
   than fixed silently or ignored silently. **Closed out 2026-09-11**, in a follow-up pass: every
   task's deliverable re-verified against the tree (not re-asserted from the commit log), all 62
   step checkboxes and the milestone's acceptance list ticked, and an EXECUTED summary added to
   the top of the file in the same style M1-M6 already carry — see
   `milestones/P3-P4/M0-baseline-and-fixes.md`'s own header note for the detail.
7. The `ScoreBucketTable`/`CorrelationTable` "small sample" and n/a rendering rules apply
   per-bucket/per-signal, not to the whole panel — a report can show one small-sample band
   beside several well-populated ones, and the UI says so band by band rather than flagging the
   whole surface as thin evidence.

### Minor findings deferred, not fixed (recorded for completeness)

- `components/options/AssessedRow.test.tsx`'s "renders a permission message on a 403" test is
  order-dependent: it fails with `TypeError: ApiError is not a constructor` when the full suite
  runs in one particular file order and passes both in isolation and in most full-suite runs
  (reproduced twice, passed on a third and fourth full run without any source change) — a
  pre-existing `vi.mock` hoisting interaction between test files, not something this milestone's
  changes introduced or could fix without touching unrelated test infrastructure.
- The api.md `### ` heading count (19) does not equal the live app's route count (32 paths):
  pre-existing and structural — the early routes (`/health`, `/watchlist`, `/research/*`, ...)
  each get their own `##`-level heading, while grouped sections (Commands, Options console,
  Portfolio, P&L) use one `##` section header with `###` per-route subheadings underneath. The
  milestone's own check asks to "record the result," not reconcile it, and the new
  `### GET /pnl/system` entry follows the surrounding P&L section's existing `###` convention
  correctly.

None of these block the milestone or the phase.

### Final gate (2026-09-11)

`python -m pytest -q` — 2187 passed. `ruff check .` — clean. `mypy src` — clean (163 source
files). `cd web && npx vitest run` — 347 passed (43 files). `npm run lint` — clean. `npm run
build` — clean (`/`, `/options`, `/options/[approvalId]`, `/pnl`, `/portfolio`,
`/stock/[symbol]`, `/universe` all compile and prerender). All six green — P3 and P4 are
complete.

**Acceptance, independently re-verified in this pass, not just re-asserted:** `/pnl/system`
renders the report and the agreement figure read-only
(`tests/test_api_pnl_system.py`, 7 tests). Every note renders in full and in order
(`SystemPanel.test.tsx`'s first test, against a report whose `notes` include the exact
read-only sentence). The surface offers no weight-changing control (a test counts every
button/input/select and asserts it equals the count of `data-role="window-control"` elements —
2). A bucket with `n=3` renders "small sample" in words. No module under `src/api/` can write
`verdict_ledger` or reference the scoring config
(`test_no_web_module_can_write_the_verdict_ledger`,
`test_no_web_module_can_write_a_scoring_weight`). `src/reporting/` writes nothing
(`test_reporting_never_writes_anything`). `save_portfolio_snapshot` has exactly two callers
(`test_the_portfolio_snapshot_writers_are_the_two_we_intended`). The API still writes exactly
one table (`test_the_api_still_writes_exactly_one_table`). `docs/web/openapi.json` and
`web/lib/api-types.ts` both re-derived to an empty diff in this pass, not carried forward from
Task 6.1/6.2's own regeneration. `STATUS.md` records P3 and P4 as built, names five deferred
items, and states the broker-reconciliation caveat plainly. Every milestone file's checkboxes
(M1-M6) reflect what actually landed; M0's pre-existing gap is recorded above, not silently
fixed. Full gate green, all six commands, numbers recorded above.

**M0's gap, closed 2026-09-11 (same day, follow-up pass):** every task's deliverable in
`milestones/P3-P4/M0-baseline-and-fixes.md` was re-verified against the tree, all step and
acceptance checkboxes ticked, and an EXECUTED summary added naming the ten landing commits — see
item 6 above and the milestone file itself. Full gate re-run at that point and unchanged from the
numbers recorded above (`pytest` 2187, `vitest` 347/43, `ruff`/`mypy`/`lint`/`build` all clean),
confirming no drift between the two passes. Every milestone file in P3-P4, M0 through M6, now
reflects what actually landed.
