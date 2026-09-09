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
