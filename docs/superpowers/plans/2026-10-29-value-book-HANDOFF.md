# Value book — handoff for the next session (updated 2026-10-30)

This file was written so a fresh session (Sonnet is fine as the orchestrator) can carry on without
the conversation that produced the spec and plans. Read it top to bottom before doing anything.

## 1. Where things stand

| Part | Plan file | State |
|---|---|---|
| Spec | `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` | Merged with Part 1. Revisions 1–3; §19/§20 record every operator answer; §14 has no open decisions |
| 1 — Scorecard + calibration dry run | `docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md` | **Merged and pushed** (main `23b1ef3`). `value_rules: v1` frozen at `e1a1b3b096b1`. Progress log fully filled |
| 2 — Value process + shadow record | `docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md` | **Merged and pushed** (main `7d37f95`, 16 commits; `main` is now `1dad9dc` with an unrelated web fix on top). pytest 5,239 passed / 1 skipped, ruff and mypy clean. `value_rules: v2` frozen at `d07717fe5348` (ruling 1 accepted). Opus review: 0 Critical, 5 Important, all fixed. Progress log fully filled |
| 3 — Re-evaluation (§7.1) + Stage 1b backtest | `docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md` | **Merged and pushed** (main `da5d3c3`, 18 commits). pytest 5,305 passed / 1 skipped; ruff and mypy (325 files) clean. `value_rules: v3` = v2 + `rules.reevaluation`, frozen at `ad8841127029`. Opus review: 1 Critical, 2 Important, all fixed. The two rulings were taken at the plan defaults (dividend rebase on, strict going-concern). Progress log fully filled |
| 4 — Claude as the analyst (`src/value_ai/`) | `docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md` | **Written 2026-10-30, NOT committed, NOT executed.** 7,789 lines, 13 tasks in sections A–D (all sonnet/high). `value_rules: v4` adds `rules.claude`, hash `be30d1eaa915`. Record-only; Claude reads are off until `value.claude.enabled`. Prototype: 5,382 passed / 1 skipped, mypy 338 files |
| 5 — Money, paper (gate, `orderRef` attribution, clientId 31, capital release) | `docs/superpowers/plans/2026-10-29-value-book-5-money-paper.md` | **Written 2026-10-30, NOT committed, NOT executed.** 6,989 lines, 15 tasks in sections A–E (B and D opus/high, rest sonnet/high). Written against Part 4's PLAN: entry check A1 reconciles it with Part 4's Progress log before Section A. Prototype on top of Part 4: 5,459 passed / 1 skipped, mypy 348 files. Five operator questions below |
| 6 — Web + Telegram | not written | After Part 5; Part 2's roadmap says it could move ahead of Part 4 |

Part 2's own Roadmap section is the current, authoritative scope for Parts 3–6. It moved items
between parts: shock stops, corporate-action rebase and going-concern to Part 3; the Claude track
to Part 4; `last_viewed_at`, digests/review cards and a watchdog to Part 6.

**Housekeeping (2026-10-30):** all git worktrees (including `value-book-3` after Part 3 merged) were removed (every one was clean and fully merged
into main). The branches still exist (`feat/value-book-1`, `feat/value-book-2`, and the older
feature branches); delete them with `git branch -d` when you like. Disk had 35 GiB free.

**The main checkout is on `main`** (switched back 2026-10-30; the `fix/refresh-invalidation-loop` branch was redundant with main's `1dad9dc`). The daemons run from it, so a branch switch changes what the next `./ibkr restart` loads.

## 2. Operator to-dos still owed

- `config/value.yaml` was refreshed to the v3 example on 2026-10-30 and loads as `v3 ad8841127029`.
  Any future example change (Parts 4–5 add keys) needs a re-copy; a stale private file idles the process.
- **`./ibkr restart` is owed:** the daemons started at 16:36 on 2026-10-30, before Part 3 merged.
- After the restart watch `df -h .` (Part 3 adds about 520 submissions reads and the sector ETFs' bars),
  then read `python -m scripts.value_report`.
- Run `python -m scripts.value_backtest` (Stage 1b). The spec makes it mandatory before any money.
- Parts 4–5 execution wants a few real nights of the shadow record first.

**Part 5 questions for the operator** (default in brackets; cheap to change before execution):
1. Does a capital release inherit its buy's approval, or always wait for its own tap? [inherits: auto when the autonomy ladder allows the buy]
2. Approve Rules-Engine edits E1–E8 (listed in Part 5's Rulings; all inert while `value.book.enabled` is false)?
3. Combined name cap of 15% of net liq? [15%]
4. Release thresholds? [breakeven floor 0%, prefer 25% of max profit, 3 closes per request, 4 a day, 10% of net liq a day]
5. Should "trim to half" at a 25% book drawdown be an automatic proposal, or only a card? [card; Part 6]

## 3. Operator decisions that bind every part (do not re-ask)

- **Two lists**, deep value and quality growth.
- **Health and earnings-quality gates are hard.** Claude cannot lift a name over them.
- **Claude decides the verdict on healthy names.** It chooses bounded valuation drivers, Python
  computes the value, and the result is clamped at **1.5× Python's fair value**.
- **Size follows Claude's margin of safety,** with a breaker. Claude's fair value also reaches the
  wheel's value-suggested put ceiling. A Python-only baseline track is recorded beside it. Claude is
  **record-only in live** (`value.claude.apply_live: false`) until the go-live review.
- **The wheel and the value book may share a ticker** from the first share purchase. Shares are
  tracked by `orderRef`, with independent wheel and value counts, fail-closed reads, and fault
  drills before the first buy. An assigned value-suggested put is wheel stock.
- **The live exit policy is `value`, pre-registered.** `full` and `hold12` are diagnostics only.
  Automatic exits read Python's fair value; anything only Claude's value would trigger is a
  tap-only proposal.
- **Auto mode:** stops and thesis exits send without a tap, and buys follow the autonomy ladder.
  Claude-caused sells always need a tap.
- **No reserved pot (operator, 2026-10-30; supersedes the 70/30 split and spec §9.3's ready buffer).**
  The wheel keeps selling CSPs against **100%** of the account. The value book holds no cash back.
  When a value buy is valid (READY, every value gate passes, a tranche due) and the cash is not
  there, the system **closes selected wheel positions to release capital**: CSPs at **breakeven or
  better, or 25% in profit**, never at a loss. Deterministic Python only (no LLM); it must go through
  the Rules Engine's close path and re-gate. Details (exact eligibility, ordering, tap vs auto,
  caps, close-then-buy sequencing) are Part 5's rulings. Both lists share the value book's caps
  (8% per name, at most 20 positions, per-list share cap) as ceilings, not reservations.
- **The operator is not a US taxpayer,** so no wash-sale rule is built.
- **Frozen v1 calibration** (Part 1, Tasks 15–16): growth valuation kept (r 8%, half of SBC, growth
  capped at 20%); `banks.require_cet1: false`; Consumer Finance and Investment Banking & Brokerage
  added to `bank_industries`; margin-of-safety bars and the 60% review line kept.

## 4. How a plan is executed (operator-mandated, token-light)

- **Work in a git worktree**, `.claude/worktrees/value-book-N` on branch `feat/value-book-N`, never
  the main checkout (live daemons and `next dev` run there). Setup:
  - `ln -s "/Users/ianlim/Desktop/IBKR Investments/.venv" .venv`
  - `IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"`
  - only if the part touches `web/`: `ln -s "/Users/ianlim/Desktop/IBKR Investments/web/node_modules" web/node_modules`
- **The main session is the Sonnet orchestrator, at high effort.** The operator sets that effort,
  because a session can't set its own.
  - It runs each section's entry checks itself.
  - It spawns **one subagent per section** with the model and **effort** the plan's Execution
    model table gives.
  - It verifies the report itself: `git log main..HEAD`, `git status`, gate counts, protected-file
    diff.
  - It **stops and asks the operator before the next section**.
- **After the last code section:** one **Opus whole-branch review** (high), then one **Sonnet fix
  pass** (high). Ask before merging or pushing.
- **Effort guide:**

  | Work | Effort |
  |---|---|
  | Wiring into existing modules, and risky logic (exit engine, gates, share attribution) | high |
  | Pure pinned formulas, pattern-following storage, scripts and docs | medium |
  | A section rerun after it stopped on a false plan fact | xhigh |

- **Gotchas found during Part 1:**
  - Commit and test-count targets go stale (each section adds a `docs(plan)` commit). Recompute
    from `git log` and the baseline.
  - Run pytest from the worktree root, or 4 ledger/openapi/web-fence tests fail spuriously.
  - Worktree sessions refuse compound Bash commands that mention git paths, so use plain single
    commands.
  - Worktree sessions can't edit private `config/*.yaml`. New keys go into
    `config/examples/value.yaml`, and the private copy becomes an operator to-do.
  - **Never import `scripts.run_*`.** With no `__main__` guard, importing starts a live service that
    fights the daemons. Use `python -m py_compile`.
  - Never copy `research.db` (~2 GB) into a worktree. Use fixtures, or open it read-only.
  - Daemons don't hot-reload: after a merge, `./ibkr restart`.
- **Progress log:** after every task, tick its boxes and fill its row (status, commit, gates,
  date, every ruling with its cost-if-wrong), and commit it with the task.

**To run Part N**, start a session on Sonnet at high effort and say:

> Execute docs/superpowers/plans/<the Part N plan file> per its Execution model, passing each
> section's effort when spawning. First read docs/superpowers/plans/2026-10-29-value-book-HANDOFF.md.

Each plan lists its own operator to-dos (before and after the merge). Part 2's are in section 2 above.

## 5. How to commission the next plan (Part N) from an Opus subagent

Do this only **after Part N−1 is merged**. Spawn one `general-purpose` agent with `model: opus`,
`run_in_background: true`, using this brief with the `<…>` filled in:

```
You are the plan writer for **Part <N> of 6 of the Value book** in a live trading repo. Write one
implementation plan file. Do NOT commit, do NOT spawn subagents, do NOT touch running services or
the main checkout's data/*.db.

The main checkout may NOT be on `main` (see HANDOFF section 1): read merged code with `git show main:<path>` and build the scratch copy with `git archive main`, never from the working tree.

Read first: CLAUDE.md (core invariant, tier fences, doc-update table, change workflow); the
previous part's plan IN FULL — its format is the one to reproduce exactly, and its Progress log
and rulings are the ground truth for what was built (it may differ from the spec):
<path of Part N−1 plan>; the Roadmap section of that plan (the authoritative scope for Part <N>);
docs/superpowers/plans/2026-10-29-value-book-HANDOFF.md; the spec
docs/superpowers/specs/2026-10-28-value-swing-book-design.md sections Part <N> covers; and the
merged code under src/value/ (and anything else Part <N> edits).

Scope: Part <N> as the previous plan's Roadmap defines it. Re-check the boundary against reality;
rule on any move with a reason. Fold in any deferred review minors from earlier Progress logs that
Part <N>'s code touches; record each as fixed or deferred.

Format: reproduce the previous plan's structure exactly (header; Execution model table WITH Model
and Effort columns, and the orchestrator procedure that passes effort on every spawn; empty
Progress log; updated Roadmap; Rulings made up front; Global Constraints; Review Focus; File
structure; sections with entry checks — exact commands and expected output, greps proving every
edited line is where the plan says; tasks with TDD checkbox steps; section exits; whole-branch
review; operator to-dos; self-review). Same execution model and effort guide as the HANDOFF file.

Specificity: complete code for every module, table, config key, transition and test; exact paths
and commands; every edited existing line verified by grep in the CURRENT tree and quoted with line
numbers; numeric fixtures you computed yourself. Prototype the whole part first in a CODE-ONLY
scratch copy of main (exclude data/, .claude/worktrees/, web/node_modules, .venv — symlink the
venv) so every code block is code that passed pytest, ruff and mypy src; delete the copy after.
Token economy: cite spec §§ rather than restating; each section lists exactly the files and §§ its
subagent reads; point to pattern files; targeted gates per task, the full gate at section exits;
3–6 tasks per section. Encode the HANDOFF gotchas (stale counts, pytest from worktree root, no
compound git-path Bash in worktrees, no private config edits, never import scripts.run_*, never
copy research.db, df -h entry check). <Part-specific notes: e.g. Part 4 — headless Claude goes
through src.claude.cli.build_cmd with the workdir outside the repo; Ollama output never becomes
the effective verdict; Part 5 — opus model for the Rules-Engine and attribution sections; Part 6 —
every UI task invokes the da-vinci skill, never run next build inside web/.>

Output: write the plan to docs/superpowers/plans/2026-10-29-value-book-<N>-<slug>.md (do not
commit). Invoke superpowers:writing-plans first. Final message ≤ 400 words: path and line count;
sections with task counts, model and effort; main rulings; minors fixed/deferred; spec/Roadmap
items moved; prototype results; operator to-dos; any question only the operator can answer.
```

Then verify the file exists and its line count, read its Roadmap and Execution model, and relay
the summary to the operator. Don't commit the plan; the plan's first task does that.

## 6. Open items carried forward (details in the plans' Progress logs)

- **Part 2 deferred minors (M1, M2, M5–M15; full text in its Progress log, last row):**
  - M1: catch-up nights apply tonight's facts to the first session they step over.
  - M2: a forming bar can survive as a settled one (`last < due`; use `<=`).
  - M5/M6: an unknown F-score component counts as zero in an exit, and the Altman Z thesis exit
    moves with the price. Part 3's going-concern and thesis-exit work touches both.
  - M7: controls are frozen as `rebase_needed` on a split though their returns are split-safe.
    Part 3's rebase work touches this.
  - M8–M12, M14, M15: benchmark basis mix, no bar-freshness gate, `rs_cutoff` population, the
    `sys.modules` probe, `value_report` labelling, repeated proposal events, a missing SPY bar.
  - M13: steady-state SEC load is about 1 GB a night, not "first sweep only".
  - **Exit-logic changes after the first live row need a `value_rules` bump** (the hash covers only
    `rules:`). Part 3 freezes `v3` for its `reevaluation:` thresholds.
- **Part 3 deferred minors:** listed in its Progress log (Part 2 P2-M9, M10, M12, M15 deferred again where untouched; Part 1 M1 to Part 6's `is_fresh`; trigger 4 robustness, a halted name never receiving tonight's facts, the report comparing only closed pairs).
- **Part 1 deferred minors:**
  - M1: two "latest accession" fingerprints disagree. This matters for Part 6's `is_fresh`.
  - M6: fractions-in-config units. Deferred again by Part 2 (renaming the keys would stop processes
    running on a stale `value.yaml`).
  - M2–M4, M7, M8: deferred with reasons. M5 is fixed in the Part 2 plan.
- **Data gaps found in the dry run:**
  - Dual-class filers (V, MA, CMCSA, BRK-B, NKE, UPS…) are held UNKNOWN by the EDGAR-vs-yfinance
    market-cap check.
  - Beneish is UNKNOWN for 158 of 519 names (missing gross-margin inputs).
  - With CET1 off, a tagged CET1 (HBAN) also goes unchecked, and RF reads READY on P/TBV alone.
- **Prototype numbers:** GOOGL's growth value is about $94 on real data, because capex depresses
  FCF. NVDA and MU fail Beneish; TRV fails ROTE stability.

## Flow after Part 5 (operator, 2026-11-04)

Parts 1-5 are merged. Part 6 touches the web design, which the web overhaul (Parts 1-3 done) also owns. Order:

1. **Opus** writes the Part 6 plan (`2026-10-29-value-book-6-web-telegram.md`): backend/Telegram sections first, web UI sections last and marked "web-overhaul-sensitive". May hand back questions.
2. **Part 6 is built** (Sonnet orchestrator, one subagent per section).
3. **Sonnet (xhigh)** is spawned only after Part 6 is built: reads the current web design and builds a ledger for the remaining web overhaul (like this HANDOFF: done / not done), adds parts after Part 3, and decides what to build on top of what exists or cut (including any Part 6 web pieces, given value-book and other changes). May ask the operator questions.
4. **Opus** writes the plan for the next web overhaul part.

Status: step 1 done 2026-11-04 (plan written, 1,793 lines, uncommitted; operator rulings: value process drains value_approve/reject, trim = one button, VALUE NOTE wired in). Next: execute Part 6.
