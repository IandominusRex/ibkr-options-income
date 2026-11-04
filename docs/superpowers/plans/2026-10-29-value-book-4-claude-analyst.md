# Value Book, Part 4: Claude as the Analyst — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan **section by section** (one subagent per section, never per task — see "Execution model"). Every section opens with **entry checks** the orchestrator runs itself before it spawns the section's subagent. Each section carries a **model** and an **effort** label; the orchestrator passes both when it spawns. No section of Part 4 touches `web/`; if one ever does, its subagent invokes the `da-vinci` skill first and its prompt says so, and nobody runs `next build` inside `web/`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 2 of the value book (spec §8): Claude reads the healthy names Python ranks highest,
writes a verdict and **valuation drivers** per list (never a number to trade on), a profile, a
thesis, a bear case and kill triggers from a menu; Python bounds every driver by the company's own
history, computes Claude's fair value, caps it at 1.5x its own and decides the **effective
verdict** (Claude decides the state on healthy names, Python's gates bound it). A `claude` track
runs in the shadow record beside the baseline, a breaker stops Claude's verdict applying when it
runs away, trigger 6 (a kill trigger near firing) joins §7.1's re-evaluations, filing reads propose
**grounded facts** checked verbatim against the filing, and an interactive `/value` skill reads the
same ticker file. Record-only: nothing in Part 4 places, sizes or gates an order.

**Architecture:** `src/value_ai/` (new, enrichment) is the analyst: news context from `news.db`
(read-only), versioned prompts with one output schema, strict parsing, one slim `claude -p` call per
read through `src.claude.cli` from `value.claude.workdir` (outside the repo), an Ollama fallback that
is labelled and never decides. It exchanges only the plain shapes of `src/common/value_ai_types.py`
with `src/value/`, which stays the only writer of `value.db`: `claude_valuation.py` (pure) bounds,
computes and clamps; `effective.py` (pure) combines; `claude_verdicts.py` accepts a read, recomputes
opinions nightly, writes `value_effective` and runs the breaker; `claude_reads.py` keeps the queue,
the priorities and the daily caps and runs reads through a reader the entrypoint passes in;
`kill_triggers.py` and `grounding.py` (pure) evaluate and verify. The research worker gains a
`filing_sections` job (a filing sliced to Items 1, 1A, 7 / Item 2) fed by a plain file. The ruleset
becomes `value_rules: v4` = v3 + `rules.claude`. Root `CLAUDE.md` gains the second written exception
under the core invariant (spec §18).

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 (SQLite, WAL; `mode=ro` URIs), asyncio, the
Claude Code CLI (`claude -p`, slim), httpx (Ollama, through `src.claude.cli` only), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` (revisions 1–3; §19/§20 hold
the operator's answers). Part 4 implements §8 (§8.1–§8.6), §6.7's effective verdict, §7.1 trigger 6
and step 3 (Claude's review: built, idle until Part 5 holds a name), the Claude track of §6.8/§12,
§13 failure mode 5, and §16/§18 for what Part 4 builds. **Part 3's plan**
(`docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md`, on `main`) and its Progress log
are the ground truth for the code Part 4 builds on; its Roadmap is Part 4's scope. Executors read
the spec sections each section cites, not the whole spec.

## Execution model

| Section | Tasks | Model | Effort | Why this model | Why this effort |
|---|---|---|---|---|---|
| **Orchestrator** (the main session) | — | **sonnet** | **high** | Runs entry checks, spawns, verifies, asks the operator; writes no product code. | It is the one reader of every subagent's report and the protected-file diff; a missed red gate ships. |
| **A — Ruleset v4, the shapes, Claude's valuation, the effective verdict** | 1–3 | **sonnet** | **high** | Every line of code and every test is given; the risk is wiring. | Wires into `config.py`, the frozen ruleset and the scorecard; a slip moves the frozen hash or a verdict. |
| **B — The analyst, acceptance, the read queue** | 4–6 | **sonnet** | **high** | A new package, a new acceptance module and the process wiring, all given whole. | Wires headless Claude into the value process and writes Claude's tables in a live `value.db`; the fences must stay green. |
| **C — Kill triggers, the Claude track, the report** | 7–9 | **sonnet** | **high** | Pure evaluation plus edits to the shadow record and the report, given as exact diffs. | `shadow.py`'s per-session loop and the nightly transaction are the riskiest code the book has before money. |
| **D — Filing reads, grounding, the skill, the docs** | 10–13 | **sonnet** | **high** | A research-worker job, a pure checker, a skill and a doc sweep given as text. | The job runs in the live research worker; a wrong slice or a test that writes `data/` touches the operator's files. |
| **Whole-branch review** | after D | **opus** | **high** | One review of the whole branch; no per-task reviews. | Reads the bounds, the clamp, the effective verdict, the breaker and the fences against the spec end to end. |
| **Review fix pass** | after the review | **sonnet** | **high** | Critical/Important findings fixed in one commit. | Fixes land in the acceptance path with the full gate as the only check. |
| **A section's rerun** (only when its subagent stopped because a plan fact was false) | that section | **sonnet** | **xhigh** | The same section prompt plus the orchestrator's corrected fact. | The plan was wrong once there; the rerun has to reason past it. |

**How the orchestrator runs a section** (the main session: the operator starts it on Sonnet at
effort high, since a session cannot set its own effort):

1. Run the section's **entry checks** itself, in order, from the worktree root. Any check fails →
   stop, report the failing command and its output, and do not spawn. A failure that belongs to the
   previous section is fixed there first (reopen its last task, record the ruling).
2. All pass → add a "Section X entry" row to the Progress log (gate result, date, and the
   recomputed commit count and test target — see "Counts" below).
3. Spawn **one subagent for the whole section** with the Agent tool, `model` set to the section's
   **Model** and `effort` set to the section's **Effort** from the table above (the operator asked
   for effort to be set from this plan), with this prompt (fill the brackets):

   > You are executing Section [X] of `docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md`
   > in the git worktree `.claude/worktrees/value-book-4` (branch `feat/value-book-4`). Read, in this
   > order: the plan's "Rulings made up front", "Global Constraints" and Section [X] in full; the spec
   > sections Section [X] cites; and only the files its tasks list. Do the tasks in order, TDD as
   > written: each failing test first, then the code, then the gates the task names. Apply each diff
   > with the Edit tool, or save it with the Write tool to a file in your scratchpad (outside the
   > worktree) and run `git apply <that file>` from the worktree root; a new file is written whole
   > with the Write tool. Run pytest from the worktree root. One commit per task, message ending
   > `Co-Authored-By: <your model name> <noreply@anthropic.com>`. After each task tick its checkboxes
   > and fill its Progress-log row (status, commit, gate counts, date, every ruling with its
   > cost-if-wrong) and commit that with the next task (the last task's row goes in a final
   > `docs(plan)` commit). Never import a `scripts.run_*` module; never run a real `claude -p` (every
   > test fakes the runner); never touch `data/*.db` of the main checkout; never edit a private
   > `config/*.yaml`; never copy `research.db`. If an entry-check fact turns out false mid-task, stop
   > and report instead of improvising. Report: commits, gate counts, rulings, anything left undone.

4. When the subagent reports, **verify it yourself** before anything else: `git log --oneline
   main..HEAD`, `git status --short` (clean), the section exit's gate command and its counts, and the
   protected-file diff (Global Constraints).
5. **Stop and ask the operator** whether to continue to the next section or stop here. Never start
   the next section without that answer.
6. If a subagent stopped because a plan fact was false: record the false fact and the corrected one
   in the Progress log as a ruling, then rerun that section once with `effort: "xhigh"` and the
   corrected fact prepended to the prompt. A second stop goes to the operator.

After Section D: spawn **one opus subagent** (`effort: "high"`) for a whole-branch review
(superpowers:requesting-code-review; the prompt is under "Whole-branch review"), then **one sonnet
subagent** (`effort: "high"`) that fixes every Critical and Important finding in one commit, then
verify it and **ask the operator before merging or pushing**. Part 4 has no calibration section and
makes no real Claude call before the merge: reads are off until the operator turns
`value.claude.enabled` on (ruling 3, operator to-dos).

**Counts go stale, so recompute them.** Each section adds one final `docs(plan)` commit and a
Progress-log row beyond its task commits, and the review fix pass adds its own. Never trust a fixed
total in this plan: at every entry check and exit, take the commit count from
`git log --oneline main..HEAD | wc -l` and record it, and state pytest targets as **baseline + N**,
where the baseline is the count recorded at A2 and N is the sum of the "new tests" of the tasks
done so far (File structure lists N per task; 77 in all).

**Commits.** Each task is one commit; Task 1's commit also adds this plan file. Every commit
message ends with the trailer `Co-Authored-By: <model> <noreply@anthropic.com>`, where `<model>`
is the executing agent's own model name.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| Section A entry | checks A0–A4 passed | 0 (branch `feat/value-book-4` at `da5d3c3`) | **baseline: pytest 5305 passed, 1 skipped**; ruff clean; mypy 325 source files; df 30 GiB free | 2026-11-04 | A3 line numbers matched exactly; v3 hash `ad8841127029` confirmed; no Part 4 code present. Section A exit target: baseline + 23 = 5328 passed, 1 skipped |
| A1 (Task 1) ruleset v4 | done | `4757ffd` | task gate: 72 passed (config, dry-run, service, scorecard, private-config, config-keys); ruff check + format clean; mypy clean on `config.py`, `ruleset.py`; v4 hash printed `be30d1eaa915` | 2026-11-04 | No deviation from the task text; the diffs were applied with Edit (same content). `claude` workdir default `~/.cache/ibkr-value-ai` passes the outside-repo validator. Cost-if-wrong: none beyond ruling 1 (before the first v4 night, re-pin; after it, a v5). |
| A2 (Task 2) shapes, scorecard inputs, Claude's fair value | done | `dc19945` | task gate: 65 passed (valuation, scorecard, shadow, service); ruff check + format clean on the 5 touched files; mypy clean on the 3 src files; the 8 + 1 new tests all pinned numbers matched first time | 2026-11-04 | No deviation. The scorecard's new `metrics` keys moved no verdict (shadow and service tests green). Cost-if-wrong: none. |
| A3 (Task 3) effective verdict, Claude's tables | done | `39387a0` | task gate: 35 passed (effective, store, fence); ruff check + format clean; mypy clean on `effective.py`, `store.py` | 2026-11-04 | No deviation. `Effective`/`ClaudeOpinion` and the seven `value_claude_*`/`value_effective` tables as written; the new tables are created by the existing `create_all` in `init_value_db` (no migration needed, all new). Cost-if-wrong: one function (`effective.py`) per ruling 4. |
| Section B entry | checks B1–B4 passed | 4 commits on branch | pytest 5328 passed, 1 skipped (re-verified by orchestrator); ruff clean; mypy 328 files | 2026-11-04 | B3 line numbers matched exactly; no `src/value_ai`. Section B exit target: baseline 5305 + 47 = 5352 passed, 1 skipped |
| **Section A exit** | done | 3 task commits + this docs(plan) commit = 4 (`git log --oneline main..HEAD \| wc -l` printed 3 before it) | **full gate: pytest 5328 passed, 1 skipped (baseline 5305 + 23)**; `ruff check .` clean; `mypy src` 328 source files, clean; protected-file diff empty; `py_compile scripts/run_value.py` silent; `git status --short` clean | 2026-11-04 | Section B entry: new-test running total 23 of 77; baseline for later targets stays 5305. |
| B1 (Task 4) the analyst `src/value_ai/` and its fences | done | `c9ae196` | task gate: 71 passed (value_ai, value_fence, eval_skills, spreads_fence, news_fence, value_config); ruff check + format clean; mypy clean on `src/value_ai`, `config.py`; 11 new tests (9 + 2 fence) | 2026-11-04 | No deviation from the task text; files written whole, fence diffs applied with Edit. Ruling: the red run (Step 2) was skipped for this task, the tests and package were written together and first run green (the other tasks ran red first); cost-if-wrong: none, the tests assert the behaviour either way. The probe test confirms importing the analyst loads only `src.claude.cli` from the reasoning layer. |
| B2 (Task 5) accepting a read: verdicts, opinions, effective verdict, breaker | done | `4cfca99` | red first (`ImportError: cannot import name 'claude_verdicts'`), then task gate: 26 passed (value_claude, value_fence); ruff check + format clean; mypy clean on `claude_verdicts.py`; 9 new tests | 2026-11-04 | No deviation; module and tests written whole as given. The pinned numbers (46.85 x 1.5, uncapped 106.19, 68.72) matched first time. Cost-if-wrong: per rulings 4, 5 and 8 (one function, one branch in `accept`, config numbers). |
| B3 (Task 6) read queue, nightly wiring, process, operator CLI | done | `9034bfd` | red first (`ModuleNotFoundError: src.value.claude_reads`), then task gate: 62 passed (value_claude, value_fence, value_service, value_shadow); `py_compile` of `run_value.py` and `value_claude.py` silent; ruff check + format clean; mypy clean on 4 files; 4 new tests | 2026-11-04 | No deviation; edits to `service.py`, `run_value.py` and the fence test applied with Edit (same content). The existing nightly tests stayed green with the new effective-verdict block (no Claude rows, so Python's baseline is written and the breaker stays ok). `run_value.py` was never imported. Cost-if-wrong: reads inside the night would hold its transaction (ruling 19); otherwise config only. |
| **Section B exit** | done | 3 task commits + this docs(plan) commit = 8 (`git log --oneline main..HEAD \| wc -l` printed 7 before it; plus the uncommitted-at-entry Section B entry row committed with Task 4) | **full gate: pytest 5352 passed, 1 skipped (baseline 5305 + 47)**; `ruff check .` clean; `mypy src` 335 source files, clean; protected-file diff empty; `py_compile scripts/run_value.py scripts/value_claude.py` silent; `git status --short` clean | 2026-11-04 | New-test running total: 23 + 24 = 47 of 77 (Section B added 11 + 9 + 4 = 24). Section C target: baseline 5305 + 63 = 5368. |

## Roadmap (this plan is Part 4 of 6)

Each later part is written **after the previous part merges**, so its code matches reality, with one
exception: Part 5 was written together with this plan (2026-10-30), against this plan's text, and
must be reconciled with this plan's Progress log before it runs (Part 5's first entry check says
how). Every part runs on this execution model (Sonnet orchestrator, one subagent per section with a
model and an effort, stop-and-ask between sections, one Opus whole-branch review).

- **Part 1 — The scorecard and the calibration dry run.** Merged and pushed (`23b1ef3`);
  `value_rules: v1` frozen at `e1a1b3b096b1`.
- **Part 2 — The value process and the shadow record.** Merged and pushed (`7d37f95`);
  `value_rules: v2` frozen at `d07717fe5348`.
- **Part 3 — Re-evaluation and Stage 1b.** Merged and pushed (`da5d3c3`); `value_rules: v3` frozen
  at `ad8841127029`.
- **Part 4 — Stage 2: Claude as the analyst.** This plan. `src/value_ai/`, Claude's bounded drivers
  and Python's clamped fair value, the effective verdict (`value_effective`), the breaker, the read
  queue with model routing and budgets, kill triggers and trigger 6, the `claude` shadow track and
  the report's Claude-vs-baseline section, filing reads with grounded facts (and the research
  worker's `filing_sections` job), Claude's review of a held name (built; idle until Part 5 holds
  one), the interactive skill, and the second written exception in root `CLAUDE.md`.
  `value_rules: v4`. **Moved out:** the `VALUE NOTE` renderer `src/common/value_text.py` and its
  wiring into the wheel's review prompts to Part 6 (its consumers are prompts on the wheel side,
  which first read `value.db` through Part 5's `value_view`; ruling 17); the web button and
  `/value NAME analyse` to Part 6 (Part 4's request path is `python -m scripts.value_claude --read`;
  ruling 16); the BROKEN-review → tap-only sell proposal to Part 5 (a sell needs a position;
  ruling 15); grounded facts adjusting Claude's FCF to a later part (ruling 9); the `prose` call kind
  (ruling 14); the earnings-release text in a standard read (ruling 11).
- **Part 5 — Stage 3: money (paper).** `docs/superpowers/plans/2026-10-29-value-book-5-money-paper.md`
  (written 2026-10-30 with this plan). The operator's 2026-10-30 decision replaces the 70/30 pot
  with **capital release** (no cash held back; selected wheel CSPs at breakeven or better are closed
  through the Rules Engine to fund a valid value buy). It reads `value_effective` (this plan) for the
  buy decision and the size tier, `value_claude_verdicts` in the gate, and `value.claude.apply_live`
  for live; it supplies the held names this plan's review read waits for, and the hourly RTH check of
  triggers 1 and 4 and "pause adds".
- **Part 6 — Web and Telegram.** As before (`src/api/value_db.py`, the strip, the stock page, Home,
  `/value`, cards, digests, a watchdog check, `last_viewed_at`, Part 1 M1's `is_fresh`), **plus,
  moved from Part 4:** `src/common/value_text.py` (the `VALUE NOTE` block) wired into the trade review,
  roll review and `/scan NAME` prompts, the "Run Claude's analysis" button and
  `/value NAME analyse` (an intent the value process reads), and the display of Claude's prose,
  drivers, clamps, kill triggers and grounded facts.

## Rulings made up front (the operator may overturn any of them)

Every ruling was checked against `main` at `da5d3c3` (Part 3 merged) and against a prototype of this
whole plan built in a code-only scratch copy of `main` (every code block below passed its tests,
`ruff check .`, `ruff format --check` on every touched file and `mypy src` there). "Cost if wrong"
is what reversing it would take. Part 3's rulings are "Part 3 ruling N", its review minors as
listed in its Progress log; Part 2's minors "P2-Mn"; Part 1's "P1-Mn".

**The ruleset**

1. **`value_rules: v4` = v3 unchanged + `rules.claude`, frozen in Task 1 at `be30d1eaa915`.** The
   driver bounds, the 1.5x clamp, the kill-trigger threshold ranges and trigger 6's nearness change
   Claude's fair value and so the effective verdict: they are rules (spec §6.8: "every threshold ...
   frozen under a ruleset version"). Whether Claude reads, whether its verdict applies in live, the
   breaker, the models, budgets, timeouts and workdir are operational keys under `value.claude`,
   outside the hash. Tests pin that the rules without `claude` hash to v3's `ad8841127029` (and down
   to v1): **no Python verdict, exit or re-evaluation threshold moves.** v3 shadow entries keep their
   tag. *Cost if wrong: before the first v4 night, re-pin; after it, a v5.*
2. **Units.** New rule keys follow `rules.valuation`: growth, margins and rates are fractions
   (`growth_cap: 0.30`); `*_pts` and `*_pct` are percent. P1-M6 stays deferred (Part 2 ruling 2's
   reasons hold).

**What Claude decides, and how Python bounds it** (spec §6.7, §8.2)

3. **Claude reads are off until the operator turns them on** (`value.claude.enabled: false`, code
   and example). They spend the subscription's tokens (up to 15 standard + 3 filing reads a day,
   Sonnet). The `claude` shadow track opens only while reads are on (ruling 7). *Cost if wrong: one
   key.*
4. **The effective verdict is the stricter of Claude's word and what price and timing allow against
   Claude's fair value** (READY > WATCH > WAIT > NO). Python's NO, UNKNOWN and NOT_APPLICABLE are
   final, including a list-entry NO (spec §6.7: "NO and UNKNOWN from Python are final"). So a Claude
   READY above Claude's own ceiling is WAIT (the margin of safety applies to Claude's number), a
   Claude READY with timing failing is WATCH, a Claude NO on a healthy name is NO, and a Claude WAIT
   stays WAIT though the price falls into range, until Claude reads the name again. A Claude opinion
   whose fair value is unusable (unreliable, no bounds, no Python value) leaves the list on Python's
   baseline. *Cost if wrong: one function (`effective.py`).*
5. **Claude's fair value is recomputed every night from its stored drivers on tonight's scorecard**
   (`claude_verdicts.opinions`), so it moves only when filed inputs (a new accession) or Python's own
   value (the cap) move; "price and news alone never move fair value" holds for Claude too. Between
   filings a re-read whose drivers would value the name **higher** on the same accession is refused
   and the earlier drivers kept (recorded as a clamp); lower is always accepted; a new accession lets
   them move either way (spec §7.1 step 2). *Cost if wrong: one branch in `accept`.*
6. **When a name is re-read** (spec §8.3, §8.5): a new accession, Python's fair value moved more than
   `stale_fv_pct` (5%), or the verdict older than `max_age_days` (30). A verdict state that changed
   with the price alone is **not** a trigger (§8.5: "never on price alone" wins over §8.3's "verdict
   changed"). A stale verdict keeps applying until the re-read lands (a gate that now fails is NO by
   Python anyway). *Cost if wrong: a stale verdict falling back to Python instead, one condition.*
7. **Two readings of Claude's verdict.** `value_effective` (what Part 5 acts on) applies Claude only
   in paper or with `apply_live`, and never while the breaker is tripped. The `claude` shadow track
   applies Claude's opinion always (CLI only), so the record measures Claude's judgement even in live
   and while tripped; it covers the trading universe only (§12: evidence entries count toward the
   baseline only), opens no controls, enters an unread name on Python's READY (it is the effective
   track), and stores the effective verdict, fair value and margin on the entry (`fair_value` stays
   Python's, which every automatic exit reads). *Cost if wrong: per-track entry rules in one
   function.*
8. **The breaker** (spec §8.2) reads the last 20 nightly runs' `claude` counts (stored in
   `value_runs.summary_json`): it trips when Claude's READYs exceed 3x the baseline's **and are at
   least `min_ready` (5)** — a handful of READYs must not trip it while the baseline has none — or when
   the 1.5x cap set more than 25% of Claude's fair values over at least `min_values` (8). Tonight's
   effective verdict uses the state before tonight's check. Once tripped it stays tripped until
   `python -m scripts.value_claude --reset-breaker`. *Cost if wrong: config numbers.*
9. **Grounded facts adjust no number in Part 4.** Claude's FCF base is its bounded margin times TTM
   revenue (spec §8.2's driver table); a one-off cash item reaches it only through the 5-year median,
   which one year cannot move far, and a direct adjustment would need a per-year margin series and a
   bound the spec does not define. Grounded facts feed the `guidance_cut` and `customer_loss` kill
   triggers and the display. *Cost if wrong: an add-back case valued slightly low (the conservative
   side); a later part adds the adjustment.*
10. **The kill-trigger menu** (spec §8.4) is built without `insider_selling_cluster` (no Form 4
    feed). `revenue_growth_below` and `gross_margin_below` read the newest fiscal year (the value
    financials hold annual periods and TTM, not a quarterly series, so "for n quarters" is not
    built). "Near" (trigger 6, `kill_near_pct` 10%): an "above" threshold y is near from 0.9y; a
    "below" threshold x is near up to x + 10% of max(|x|, 10 points); `fcf_ttm_negative` and the
    fact-based kinds fire or not, with no near. A trigger only opens a Minor re-evaluation (or, fired,
    is recorded for Part 6's review card); it never moves a level. *Cost if wrong: one predicate or
    one band.*
11. **The standard read** carries the scorecard as labelled numbers, the driver bounds, the menu, the
    dossier (when one exists), the name's pile 1-2 news clusters of 30 days and its earnings dates.
    The earnings release text (an 8-K exhibit) is not fetched: that needs a new research-worker job,
    and the news clusters and, weeks later, the 10-Q's filing read stand in. *Cost if wrong: a job.*
12. **Filing reads** (spec §8.2, §8.5): the research worker's new `filing_sections` job cuts the
    newest periodic filing of each name in `data/value_filing_reads.json` (effective READY trading
    names; Part 5 adds held names) into 10-K Items 1, 1A, 7 / 10-Q Item 2 / 20-F Items 4, 5 (the
    longest span from each heading to the next: a table of contents names every item too), capped
    at 24K/16K characters a section. One filing read per filing; a read whose sections have not
    arrived waits up to 7 days. `grounding.py` keeps a fact only if its quote is verbatim in that
    filing's text, its number is in the quote, and an XBRL item matches companyfacts within 0.5%.
    *Cost if wrong: a heuristic slice; each part is one regex.*
13. **Ollama never decides** (spec §8.5): `value.claude.ollama_fallback` is off by default; with it
    on (or `claude.backend: ollama`) a reply is stored labelled `backend="ollama"`, and it is never an
    opinion, never grounded, never sets kill triggers or a review state. *Cost if wrong: none.*
14. **Models per call kind** (spec §8.5): `value.claude.models.verdict / filing / review`, each ""
    = `claude.model` (Sonnet). The `prose` call kind is not built: prose comes with each standard
    read, and a prose-only refresh on news would spend reads on wording. *Cost if wrong: a kind.*
15. **Claude's review of a held name** (spec §7.1 step 3) is built and tested: a `review` read at
    priority 1 whose state lands on `value_reevaluations.review_state`. Nothing queues one in Part 4:
    shadow positions make no Claude call (spec §7.1 step 3) and there are no held names before Part 5,
    which also turns BROKEN into a tap-only sell proposal. *Cost if wrong: none.*
16. **On-request reads** use `python -m scripts.value_claude --read SYMBOL` (it queues a request the
    value process runs at its next poll); the web button and `/value NAME analyse` are Part 6.
17. **`src/common/value_text.py` (the `VALUE NOTE` block) moves to Part 6** with its consumers, the
    wheel's review prompts, which first read `value.db` through Part 5's `value_view`. *Cost if wrong:
    the wheel's CSP reviews do not see the value note until Part 6.*
18. **The skill** (spec §8.6) is `.claude/skills/value/` with `SKILL.md` and five `reference/` files;
    it runs `python -m scripts.value_report --symbol SYMBOL --json` (new in Task 12) rather than
    shipping a `scripts/` folder; `reference/output-schema.json` is generated from
    `src/value_ai/prompts.OUTPUT_SCHEMA` and a test keeps the two equal.

**The process and the fences**

19. **Reads run after the night, each in its own transaction** (`claude_reads.run_queue`), through a
    reader `scripts/run_value.py` passes in (it wraps `src.value_ai.analyst.Analyst` with
    `asyncio.run`), so `src/value/` never imports Claude. Requests run on every poll (600 s); the
    automatic set is queued by the night. A night's Claude READY enters the `claude` track on the next
    night (one session later than a baseline READY found the same night). *Cost if wrong: reads
    inside the night would hold its transaction for minutes.*
20. **Fences.** `src/value_ai/` imports nothing from `src.value`, the trading path, `src.notify`,
    `src.ledger`, `src.storage`, `src.research`, `src.spreads*`, `src.api`, `src.reporting`; from
    `src.claude` only `src.claude.cli`; from `src.news` only `store.readonly` and `store.queries`. It
    joins `test_eval_skills.py`'s enrichment list. Importing the analyst loads `src.claude.cli` alone
    from the reasoning layer (a `sys.modules` probe). `src/common/value_ai_types.py` is plain pydantic.
    The value process's existing probe (`src.value` + its feed: no Claude, no `ib_async`) is unchanged.
21. **Review minors.** Part 4's code adds to `service.run_nightly`, `shadow.process`/`step_legs`,
    `report.py` and `value_report.py` without restructuring the paths Part 3's deferred minors sit
    in, so they stay deferred with their reasons: P2-M9 (bar-freshness gate, Part 6's watchdog),
    P2-M10 and P1-M6 (an entry-rule bump), P2-M12, P2-M15, P1-M1 (Part 6's `is_fresh`), trigger 4's
    robustness to late indexing (Part 5, with the hourly check of trigger 4), a halted name never
    receiving tonight's facts, `positions` before `fill_pending`, and the report's re-evaluation
    section comparing closed pairs only. **Fixed here:** a test-isolation gap Part 4 would otherwise
    open (Task 10: `tests/conftest.py` redirects the new `data/value_filing_reads.json` as it already
    redirects `value_keep_fresh.json`).
22. **No web, no Telegram, no API, no command kind.** `README.md`, `docs/web/*`, `How the scan
    works.md`, `UNIVERSE_RESEARCH.md` and `.opencode/` are unchanged.

## Global Constraints

- **The core invariant holds, with its second written exception (Task 13):** nothing in Part 4 can
  place, size or gate an order. `src/engine/`, `src/execution/`, `src/strategies/`,
  `src/orchestrator/`, `src/monitor/`, `src/notify/`, `src/spreads/`, `src/news/` and `src/claude/`
  never import `src.value` or `src.value_ai`.
- `src/value/` imports nothing from `src.claude`, `src.news`, `src.value_ai`, `src.spreads*`,
  `src.notify`, `src.api`, the trading path, `src.ledger`, `src.reporting` or the enrichment
  analytics; from `src.research` only `src.research.ingest.concepts` and `src.research.schemas`. It
  reads `research.db` only through `src/common/value_inputs.py` and exchanges data with Claude only
  through `src/common/value_ai_types.py`.
- `scripts/run_value.py` is the only importer of `src.value_ai`; never import it — check it with
  `.venv/bin/python -m py_compile`.
- **No test runs a real `claude -p` or Ollama call**: every analyst test passes a fake runner.
- The pure modules (`schemas`, `metrics`, `scores`, `gates`, `valuation`, `timing`, `scorecard`,
  `rank`, `funnel`, `ruleset`, `exits`, `ranked`, `report`, `residuals`, `reevaluate`, and now
  `claude_valuation`, `effective`, `kill_triggers`, `grounding`) do no I/O.
- Only `src/value/` constructs `value.db` rows (`scripts/` is scanned too).
- **Unknown is never zero.** A missing driver means no Claude fair value; a missing metric is an
  `unknown` kill trigger; a missing reply means no notes.
- No test may write the operator's `data/` files: `tests/conftest.py` redirects the keep-fresh and
  filing-reads files (Task 10). Never open the main checkout's `data/*.db`; never copy `research.db`.
- Worktree Bash: plain single commands, absolute paths or the worktree root as cwd; no heredocs, no
  `cd x && …`, no compound commands that mention git paths.
- New config keys go into `config/examples/value.yaml` with a code default; the operator's private
  `config/*.yaml` is never edited (operator to-dos at the end).
- **Protected files** (diff against `main` must be empty at every section exit):
  `git diff --stat main...HEAD -- src/engine src/execution src/strategies src/notify
  src/orchestrator src/spreads src/api src/news src/claude src/ledger src/reporting web` prints
  nothing. (Part 4 edits `src/research/` and `src/common/`, which are not protected; nothing else
  outside `src/value/`, `src/value_ai/`, `scripts/`, `tests/`, `config/examples/`, `.claude/skills/`
  and the four docs.)
- Per-task gate: the task's test files + `.venv/bin/ruff check <touched paths>` +
  `.venv/bin/ruff format --check <touched paths>` + `.venv/bin/mypy <touched src paths>`. Full gate
  at section exits only, from the worktree root: `.venv/bin/python -m pytest -q`,
  `.venv/bin/ruff check .`, `.venv/bin/mypy src`.
- `ruff format` only the files a task touches (`scripts/roll_backtest.py`,
  `src/api/routers/portfolio.py` and `system.py` carry pre-existing format drift; leave them).

## Review Focus

1. **A Claude number escapes its bounds or the cap** → every driver clamped and recorded, the value
   capped at 1.5x Python's and that capped value used, unreliable above a 75% terminal share, no
   Claude value without Python's → Task 2 `test_every_driver_out_of_bounds_is_clamped_and_recorded`,
   `test_a_value_above_one_and_a_half_times_pythons_is_capped_and_the_cap_used`,
   `test_a_terminal_value_above_three_quarters_is_unreliable`; Task 5
   `test_a_read_stores_the_bounded_drivers_and_pythons_capped_value`.
2. **Claude lifts a name over a gate** → Python's NO/UNKNOWN/NOT_APPLICABLE final, the margin and
   timing applied to Claude's value → Task 3 `test_the_effective_verdict` (nine cases),
   `test_unknown_and_not_applicable_are_final`.
3. **An Ollama, malformed or between-filings-higher reply decides something** → Task 5
   `test_an_ollama_reply_is_stored_labelled_and_is_never_an_opinion`,
   `test_a_malformed_reply_stores_the_call_and_nothing_else`,
   `test_between_filings_a_reread_can_lower_but_never_raise`; Task 4
   `test_a_failed_cli_falls_back_to_ollama_labelled_and_a_timeout_does_not`.
4. **Claude applies in live, or past the breaker** → Task 5
   `test_claude_applies_in_paper_in_live_only_with_apply_live_and_never_while_tripped`,
   `test_the_breaker_trips_on_the_ready_multiple_and_on_the_clamp_rate`.
5. **Headless Claude loads the repo or the wheel's prompt stack** → Task 4
   `test_a_cli_read_is_labelled_cli_and_runs_slim_from_the_workdir`,
   `test_the_analyst_loads_no_wheel_layer_and_no_value_code`; Task 1
   `test_nonsense_claude_keys_are_refused` (a workdir inside the repo is refused at load).
6. **The full suite writes the operator's `data/value_filing_reads.json`** (a night in a test) →
   Task 10's `tests/conftest.py` redirect; the section exits check `git status --short` is clean.

---

## File structure

```
config/examples/value.yaml                MODIFY  v4, rules.claude, claude (T1)
.claude/skills/value/                     CREATE  SKILL.md, reference/ x5 (T12)
src/
  common/config.py                        MODIFY  ValueClaudeRulesCfg, ValueClaudeCfg, v4 (T1);
                                                  Config.value_ai_workdir (T4)
  common/value_ai_types.py                CREATE  the shapes between src/value and src/value_ai (T2)
  common/value_inputs.py                  MODIFY  latest_periodic, filing_sections (T10)
  common/value_keep_fresh.py              MODIFY  the filing-reads file (T10)
  research/store/models.py                MODIFY  FilingSectionRow (T10)
  research/ingest/filing_sections.py      CREATE  the filing_sections job (T10)
  research/ingest/materialize.py          MODIFY  the drain runs it (T10)
  research/ingest/value_universe.py       MODIFY  the sweep queues it (T10)
  value/ruleset.py                        MODIFY  FROZEN v4 (T1)
  value/scorecard.py                      MODIFY  claude_inputs metrics (T2)
  value/claude_valuation.py               CREATE  bounds, clamp, two-stage DCF, cap; pure (T2)
  value/effective.py                      CREATE  the effective verdict; pure (T3)
  value/store.py                          MODIFY  Claude's seven tables (T3)
  value/claude_verdicts.py                CREATE  accept, opinions, effective, breaker (T5);
                                                  kill triggers (T7); facts (T11)
  value/claude_reads.py                   CREATE  the queue, caps, requests, run_queue (T6);
                                                  filing reads (T11)
  value/kill_triggers.py                  CREATE  the menu evaluated; pure (T7)
  value/reevaluate.py                     MODIFY  trigger 6 (T7)
  value/shadow.py                         MODIFY  the claude track, trigger 6's context (T8)
  value/service.py                        MODIFY  opinions, effective, breaker, queue (T6);
                                                  kill, opinions to the record (T8); filing reads (T11)
  value/report.py                         MODIFY  claude_section (T9)
  value/grounding.py                      CREATE  grounded facts; pure (T11)
  value_ai/__init__.py, context.py,       CREATE  the analyst (T4)
    prompts.py, parse.py, analyst.py
scripts/
  run_value.py                            MODIFY  the reader and the Claude tick (T6); sections (T11)
  value_claude.py                         CREATE  the operator's CLI (T6)
  value_report.py                         MODIFY  Claude beside the baseline (T9); --symbol --json (T12)
tests/
  test_value_config.py                    MODIFY  (+2: 16 -> 18; v3 -> v4)            T1   +2
  test_value_dry_run.py, test_value_service.py   MODIFY  (v3 -> v4)                    T1
  test_value_claude_valuation.py          CREATE  (8)                                  T2   +8
  test_value_scorecard.py                 MODIFY  (+1)                                 T2   +1
  test_value_effective.py                 CREATE  (3 functions, 11 collected)          T3   +11
  test_value_store.py                     MODIFY  (+1)                                 T3   +1
  test_value_ai.py                        CREATE  (9)                                  T4   +9
  test_value_fence.py                     MODIFY  (+2; pure list, rows, types)         T4   +2
  test_eval_skills.py                     MODIFY  (src.value_ai on the list)           T4
  test_value_claude.py                    CREATE  (9), then +4 (T6), +2 (T11)          T5 +9, T6 +4, T11 +2
  test_value_kill_triggers.py             CREATE  (4 functions, 11 collected)          T7   +11
  test_value_reevaluate.py                MODIFY  (+1)                                 T7   +1
  test_value_shadow.py                    MODIFY  (+3)                                 T8   +3
  test_value_report.py                    MODIFY  (+1, then +1)                        T9 +1, T12 +1
  test_research_filing_sections.py        CREATE  (6)                                  T10  +6
  test_value_universe.py, conftest.py     MODIFY  (a count; the file redirect)         T10
  test_value_grounding.py                 CREATE  (4)                                  T11  +4
  test_value_ai.py                        MODIFY  (+1: the skill's schema)             T12  +1
ARCHITECTURE.md, SETUP.md, STATUS.md, CLAUDE.md   MODIFY (T13)
docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md   this plan (Progress log)
```

**77 new tests** in all (baseline + 77 at Section D's exit; the prototype ran 5305 + 1 skipped →
5382 + 1 skipped, mypy 338 source files). Part 4 adds no route, command kind, Telegram command or
top-level directory (ruling 22).

---

## Section A — Ruleset v4, the shapes, Claude's valuation, the effective verdict (Tasks 1–3) · model: sonnet · effort: high

Claude's bounds and clamp go into the config and freeze `value_rules: v4`; the plain shapes between
`src/value/` and `src/value_ai/` are written; the scorecard carries what Claude's bounds read;
Python's arithmetic for Claude's fair value and the effective verdict are built pure; Claude's
tables are added to `value.db`. No Claude call exists yet.

**Spec to read:** §6.7 (the effective verdict), §8.2 (the driver table, the clamp, the breaker,
"Paper and live"), §8.3 (the first paragraph: Claude's tables), §8.4, §16 (the revision 2 and 3
"Claude" bullets).

**Files the subagent reads:** `src/common/config.py` (lines 1600–1740: the value models),
`config/examples/value.yaml`, `src/value/ruleset.py`, `tests/test_value_config.py`,
`src/value/scorecard.py`, `src/value/valuation.py`, `src/value/metrics.py` (lines 1–110, 230–283),
`src/value/schemas.py`, `src/value/store.py`, `tests/value_fixtures.py`,
`tests/test_value_scorecard.py` (lines 60–185), `tests/test_value_store.py` (lines 1–60).

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **A0. Disk, worktrees, and the new one.** From the main checkout:

  ```bash
  df -h .
  git -C "/Users/ianlim/Desktop/IBKR Investments" worktree list
  git -C "/Users/ianlim/Desktop/IBKR Investments" log --oneline -1 main
  git -C "/Users/ianlim/Desktop/IBKR Investments" merge-base --is-ancestor da5d3c3 main
  ```

  `df` must show **at least 8 GiB available** (the filing-sections job stores ~60 KB per filing; the
  margin is for the live research database). `worktree list` must not list
  `.claude/worktrees/value-book-4` already. `main` must contain Part 3 (the `merge-base` exits 0).
  Any fails → stop and ask the operator. Then create the worktree **from `main`** and set it up, one
  command each (the last three from the worktree root):

  ```bash
  git -C "/Users/ianlim/Desktop/IBKR Investments" worktree add "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/value-book-4" -b feat/value-book-4 main
  ln -s "/Users/ianlim/Desktop/IBKR Investments/.venv" .venv
  cp "/Users/ianlim/Desktop/IBKR Investments/docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md" docs/superpowers/plans/
  IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"
  ```

  (No `web/node_modules` link: Part 4 runs no web test. No database copy: Part 4's tests use
  fixtures.)
- [ ] **A1. Branch and a clean start.** `git branch --show-current` prints `feat/value-book-4`;
  `git log --oneline -1` starts with `da5d3c3` (or a later `main` the operator merged — record it);
  `git status --short` prints exactly:

  ```
  ?? docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md
  ```

  (If the operator has committed `docs/superpowers/plans/2026-10-29-value-book-HANDOFF.md` or the
  Part 5 plan on `main` meanwhile, that is fine; record it.)
- [ ] **A2. A green baseline, from the worktree root.** Each passes; record the pytest count in the
  Progress log as **the baseline** (at `da5d3c3`: `5305 passed, 1 skipped`; mypy: `325 source
  files`). Run pytest from the worktree root: run elsewhere, 4 ledger/openapi/web-fence tests fail
  spuriously.

  ```bash
  .venv/bin/python -m pytest -q
  .venv/bin/ruff check .
  .venv/bin/mypy src
  ```

  A red baseline is not this plan's to fix: stop and report it. (Known order-dependent flakes:
  `test_roll_review_fixes.py::test_fallback_leg_prices_net_to_the_actual_combo_fill` and
  `test_scan_timeout`: if one alone fails, rerun once and record.)
- [ ] **A3. The code Section A edits is where this plan says.** Each command prints exactly one line
  with the number shown (line numbers as of `da5d3c3`; a moved line is fine if the text matches —
  record it):

  ```bash
  grep -nF 'class ValueRulesCfg(_ValueModel):' src/common/config.py   # 1668:
  grep -nF '    reevaluation: ValueReevaluationCfg = Field(default_factory=ValueReevaluationCfg)' src/common/config.py   # 1680:
  grep -nF 'class ValueCfg(_ValueModel):' src/common/config.py   # 1728:
  grep -nF '    ruleset_version: str = "v3"' src/common/config.py   # 1732:
  grep -nF '    rules: ValueRulesCfg = Field(default_factory=ValueRulesCfg)' src/common/config.py   # 1738:
  grep -nF 'FROZEN: dict[str, str] = {"v1": "e1a1b3b096b1", "v2": "d07717fe5348", "v3": "ad8841127029"}' src/value/ruleset.py   # 21:
  grep -nF 'ruleset_version: v3' config/examples/value.yaml   # 13:
  grep -nF '    down_shock_atr: 0.5' config/examples/value.yaml   # 211:
  grep -nF 'def test_v1_and_v2_stay_pinned_and_v3_is_frozen() -> None:' tests/test_value_config.py   # 79:
  grep -nF 'def test_v3_changes_no_entry_rule_and_no_exit_threshold() -> None:' tests/test_value_config.py   # 87:
  grep -nF '("dry_run", 1, "v3")' tests/test_value_dry_run.py   # 104:
  grep -nF '("nightly", AS_OF, "v3")' tests/test_value_service.py   # 151:
  grep -nF 'from src.value.metrics import Year, cagr, median_of, roic, stdev_of' src/value/scorecard.py   # 15:
  grep -nF '"reverse_dcf_implied_growth": implied,' src/value/scorecard.py   # 265:
  grep -nF '_engine: Engine | None = None' src/value/store.py   # 251:
  grep -nF 'def test_init_adds_the_plan_columns_to_a_part_2_database(' tests/test_value_store.py   # 137:
  grep -nF 'def test_the_scorecard_is_a_pure_function_of_its_inputs() -> None:' tests/test_value_scorecard.py   # 181:
  ```

  `tail -n 1 config/examples/value.yaml` prints the `down_shock_atr` line (the file ends there).
- [ ] **A4. v3 is what is frozen, and no Part 4 code exists yet.** The first prints `ad8841127029`;
  the second prints nothing:

  ```bash
  .venv/bin/python -c "from src.common.config import ValueCfg; from src.value.ruleset import ruleset_hash; print(ruleset_hash(ValueCfg().rules))"
  grep -rln "ValueClaudeRulesCfg\|claude_valuation\|ValueClaudeVerdictRow\|value_ai_types" src tests scripts
  ```

**Section exit:** three task commits plus the section's final `docs(plan)` commit; full gate green
with pytest = baseline + 23 (2 + 9 + 12); protected-file diff empty;
`.venv/bin/python -m py_compile scripts/run_value.py` silent; `git status --short` clean. Record the
commit count from `git log --oneline main..HEAD | wc -l`.

---

### Task 1: Ruleset v4 — Claude's bounds under `rules`, its switches under `value.claude`

**Files:**
- Modify: `src/common/config.py` (insert before `class ValueRulesCfg`; one line after
  `reevaluation:`; insert before `class ValueCfg`; `ruleset_version` and the `ValueCfg` docstring;
  one line after `rules:`), `src/value/ruleset.py` (the `FROZEN` line),
  `config/examples/value.yaml` (header lines 1–13; append after the last line)
- Modify: `tests/test_value_config.py`, `tests/test_value_dry_run.py` (line 104),
  `tests/test_value_service.py` (line 151)
- Add: this plan (first commit of the branch)

**Interfaces:**
- Produces: `ValueClaudeRulesCfg` at `ValueRulesCfg.claude` (`clamp_multiple`, `growth_floor`,
  `growth_cap`, `growth_over_realised`, `terminal_min`, `terminal_max`, `discount_max`,
  `margin_band_pts`, `rote_band_pts`, `max_kill_triggers`, `kill_bounds: dict[str, tuple[float,
  float]]`, `kill_near_pct`); `ValueClaudeCfg` at `ValueCfg.claude` (`enabled`, `apply_live`,
  `ollama_fallback`, `workdir`, `models: ValueClaudeModelsCfg` (`verdict`, `filing`, `review`),
  `effort`, `timeout_seconds`, `filing_timeout_seconds`, `standard_reads_per_day`,
  `deep_reads_per_day`, `top_per_list`, `stale_fv_pct`, `max_age_days`, `max_headlines`, `breaker:
  ValueClaudeBreakerCfg` (`sessions`, `ready_multiple`, `min_ready`, `clamp_rate_pct`,
  `min_values`)); `ValueCfg.ruleset_version == "v4"`; `FROZEN["v4"] == "be30d1eaa915"`.

- [x] **Step 1: Write the failing tests** — apply this diff (it replaces
  `test_v1_and_v2_stay_pinned_and_v3_is_frozen` and `test_v3_changes_no_entry_rule_and_no_exit_threshold`):

```diff
diff --git a/tests/test_value_config.py b/tests/test_value_config.py
index 8d504ea..7b0c48c 100644
--- a/tests/test_value_config.py
+++ b/tests/test_value_config.py
@@ -1,4 +1,4 @@
-"""config/value.yaml: the typed model, its committed example and the ruleset hash (Parts 1-3)."""
+"""config/value.yaml: the typed model, its committed example and the ruleset hash (Parts 1-4)."""
 
 from __future__ import annotations
 
@@ -26,7 +26,7 @@ def test_the_example_spells_out_exactly_the_model_defaults() -> None:
 
 def test_get_config_loads_the_value_block() -> None:
     cfg = get_config().value
-    assert cfg.ruleset_version == "v3"
+    assert cfg.ruleset_version == "v4"
     assert cfg.rules.margin_of_safety.deep_value[MarketRegime.NORMAL] == 25.0
     assert cfg.rules.margin_of_safety.quality_growth[MarketRegime.CRISIS] == 25.0
     assert cfg.rules.valuation.discount_rate_growth == 0.08
@@ -65,7 +65,7 @@ def test_a_frozen_version_refuses_rules_that_no_longer_match(monkeypatch) -> Non
     monkeypatch.setitem(FROZEN, "v9", "000000000000")
     with pytest.raises(ValueError, match="frozen"):
         ruleset_id(ValueCfg(ruleset_version="v9"))
-    assert ruleset_id(ValueCfg()) == ("v3", ruleset_hash(ValueCfg().rules))
+    assert ruleset_id(ValueCfg()) == ("v4", ruleset_hash(ValueCfg().rules))
 
 
 def _hash_without(*blocks: str) -> str:
@@ -76,20 +76,49 @@ def _hash_without(*blocks: str) -> str:
     return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
 
 
-def test_v1_and_v2_stay_pinned_and_v3_is_frozen() -> None:
-    """Part 1 froze v1 (the entry rules); Part 2 froze v2 = v1 + the exit rules; Part 3 froze
-    v3 = v2 + the re-evaluation rules, before the first re-evaluation (spec §7.1)."""
+def test_v1_to_v3_stay_pinned_and_v4_is_frozen() -> None:
+    """Part 1 froze v1 (the entry rules), Part 2 v2 (+ exits), Part 3 v3 (+ re-evaluation);
+    Part 4 froze v4 = v3 + Claude's bounds, before Claude's first read (spec §8.2)."""
     assert FROZEN["v1"] == "e1a1b3b096b1" and FROZEN["v2"] == "d07717fe5348"
-    assert FROZEN["v3"] == ruleset_hash(ValueCfg().rules)
-    assert ruleset_id(get_config().value) == ("v3", FROZEN["v3"])
+    assert FROZEN["v3"] == "ad8841127029"
+    assert FROZEN["v4"] == ruleset_hash(ValueCfg().rules)
+    assert ruleset_id(get_config().value) == ("v4", FROZEN["v4"])
 
 
-def test_v3_changes_no_entry_rule_and_no_exit_threshold() -> None:
-    """Without the reevaluation block the rules hash exactly as v2's; without exits too, as
-    v1's: no verdict and no exit threshold moves. Part 3's exit-engine changes are code, carried
-    by the version bump (an exit-logic change after the first live row needs one)."""
-    assert _hash_without("reevaluation") == FROZEN["v2"]
-    assert _hash_without("reevaluation", "exits") == FROZEN["v1"]
+def test_v4_changes_no_python_rule() -> None:
+    """Without the claude block the rules hash exactly as v3's, and so on down: no Python
+    verdict, exit threshold or re-evaluation threshold moves."""
+    assert _hash_without("claude") == FROZEN["v3"]
+    assert _hash_without("claude", "reevaluation") == FROZEN["v2"]
+    assert _hash_without("claude", "reevaluation", "exits") == FROZEN["v1"]
+
+
+def test_claudes_bounds_are_in_the_ruleset_and_its_switches_are_not() -> None:
+    """Spec §8.2: the bounds and the clamp are rules (a change is a version bump); whether
+    Claude reads, and whether its verdict applies in live, are not."""
+    cfg = ValueCfg()
+    assert cfg.rules.claude.clamp_multiple == 1.5
+    assert cfg.rules.claude.kill_bounds["dilution_above"] == (1.0, 10.0)
+    for change in ({"clamp_multiple": 1.4}, {"terminal_max": 0.03}, {"kill_near_pct": 5.0}):
+        moved = ValueCfg(**{"rules": {"claude": change}})
+        assert ruleset_hash(moved.rules) != ruleset_hash(cfg.rules)
+    switches = ValueCfg(**{"claude": {"enabled": True, "apply_live": True}})
+    assert ruleset_hash(switches.rules) == ruleset_hash(cfg.rules)
+    assert cfg.claude.enabled is False and cfg.claude.apply_live is False
+
+
+def test_nonsense_claude_keys_are_refused() -> None:
+    for bad in (
+        {"rules": {"claude": {"clamp_multiple": 0.9}}},
+        {"rules": {"claude": {"terminal_max": 0.13}}},
+        {"rules": {"claude": {"kill_bounds": {"revenue_growth_below": [5.0, 1.0]}}}},
+        {"rules": {"claude": {"kill_bounds": {"insider_selling": [1.0, 2.0]}}}},
+        {"claude": {"workdir": "data/value-ai"}},
+        {"claude": {"standard_reads_per_day": -1}},
+        {"claude": {"model": "opus"}},
+    ):
+        with pytest.raises(ValidationError):
+            ValueCfg(**bad)
 
 
 def test_the_reevaluation_rules_are_in_the_ruleset() -> None:
diff --git a/tests/test_value_dry_run.py b/tests/test_value_dry_run.py
index 5b9ad89..f870655 100644
--- a/tests/test_value_dry_run.py
+++ b/tests/test_value_dry_run.py
@@ -101,7 +101,7 @@ def test_the_dry_run_scores_persists_and_prints_the_funnel(dbs, capsys, tmp_path
         assert row is not None and row.universe == "trading"
         assert row.verdict_deep == "WATCH"  # cheap enough; no earnings date is unknown timing
         run = s.query(ValueRunRow).one()
-        assert (run.kind, run.names, run.ruleset_version) == ("dry_run", 1, "v3")
+        assert (run.kind, run.names, run.ruleset_version) == ("dry_run", 1, "v4")
 
 
 def test_no_persist_leaves_value_db_alone(dbs, tmp_path) -> None:
diff --git a/tests/test_value_service.py b/tests/test_value_service.py
index 1d46371..42f3440 100644
--- a/tests/test_value_service.py
+++ b/tests/test_value_service.py
@@ -148,7 +148,7 @@ def test_a_night_scores_persists_and_opens_the_shadow_record(dbs) -> None:
         )
         assert s.scalars(select(ValueTickerHistoryRow)).first() is not None
         run = s.scalars(select(ValueRunRow)).one()
-        assert (run.kind, run.as_of, run.ruleset_version) == ("nightly", AS_OF, "v3")
+        assert (run.kind, run.as_of, run.ruleset_version) == ("nightly", AS_OF, "v4")
         assert {r.status for r in s.scalars(select(ValueShadowRow))} == {"pending"}
     assert service.plan_run(NOW, universe={}) is None  # done for AS_OF
 
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_service.py`
  Expected: FAIL — `AttributeError: 'ValueRulesCfg' object has no attribute 'claude'` (and the v4
  assertions).

- [x] **Step 3: The config model, the frozen hash and the example** — apply:

```diff
diff --git a/config/examples/value.yaml b/config/examples/value.yaml
index 1fedaab..0cecd7e 100644
--- a/config/examples/value.yaml
+++ b/config/examples/value.yaml
@@ -1,16 +1,18 @@
 # The value book (docs/superpowers/specs/2026-10-28-value-swing-book-design.md).
 #
-# Copy to config/value.yaml (git-ignored) to tune it. Parts 1-3 build the scorecard, the shadow
-# record and its re-evaluations only: nothing here can place, size or gate an order.
+# Copy to config/value.yaml (git-ignored) to tune it. Parts 1-4 build the scorecard, the shadow
+# record, its re-evaluations and Claude as the analyst: nothing here can place, size or gate an
+# order.
 #
 # Everything under `rules:` can change a verdict, so it is hashed into the ruleset fingerprint
 # (src/value/ruleset.py). Once `ruleset_version` is frozen, changing any rule is a version bump
 # with a written reason, at most quarterly. v1 (2026-10-29) froze the entry rules after the
 # calibration dry run; v2 (Part 2) adds `rules.exits` before the shadow ledger's first row and
 # changes no entry rule; v3 (Part 3) adds `rules.reevaluation` (spec §7.1) and the exit engine's
-# Part 3 rules (shock stops, the 8-K and going-concern thesis exits), and changes no entry rule.
+# Part 3 rules (shock stops, the 8-K and going-concern thesis exits), and changes no entry rule;
+# v4 (Part 4) adds `rules.claude` (spec §8.2, §8.4) and changes nothing else.
 
-ruleset_version: v3
+ruleset_version: v4
 db_url: sqlite:///data/value.db
 
 universe:
@@ -209,3 +211,48 @@ rules:
     quiet_days: 90           # 8: this many days with no re-evaluation (Minor)
     debounce_sessions: 3     # a trigger this close to an open re-evaluation joins it, unless Major
     down_shock_atr: 0.5      # full only: the stop rises to the shock low - 0.5 x ATR(14) before it
+
+  claude:                    # spec §8.2, §8.4: what Claude's analysis is held to (fractions)
+    clamp_multiple: 1.5      # Claude's fair value is capped at 1.5 x Python's
+    growth_floor: -0.10      # FCF/share growth, years 1-5 (fading to terminal over 6-10) ...
+    growth_cap: 0.30         # ... at most 30% ...
+    growth_over_realised: 0.05   # ... and at most the realised 5-year CAGR + 5 points
+    terminal_min: 0.0
+    terminal_max: 0.025
+    discount_max: 0.12       # the floor is the list's Python rate (9% deep, 8% growth)
+    margin_band_pts: 5.0     # normalised FCF margin: within 5 points of the 5-year median,
+                             # never above the 5-year best
+    rote_band_pts: 4.0       # banks and insurers: sustainable ROTE within 4 points of the median
+    max_kill_triggers: 5
+    kill_bounds:             # the menu's thresholds Claude picks within (percent; a multiple)
+      revenue_growth_below: [-30.0, 10.0]
+      net_debt_to_ebitda_above: [1.0, 6.0]
+      dilution_above: [1.0, 10.0]
+      gross_margin_below: [0.0, 90.0]
+    kill_near_pct: 10.0      # trigger 6: a chosen predicate within 10% of firing (Minor)
+
+claude:                      # spec §8: Claude as the analyst (src/value_ai/). Not rules: when
+                             # Claude reads and whether its verdict applies, never a number
+  enabled: false             # reads spend the subscription's tokens: the operator turns this on
+  apply_live: false          # live: recorded, not applied, until the go-live review (§8.2, §12)
+  ollama_fallback: false     # an Ollama reply is stored labelled and never decides anything
+  workdir: ~/.cache/ibkr-value-ai   # outside the repo: claude walks up from its cwd
+  models:                    # per call kind; "" = claude.model in settings.yaml (Sonnet)
+    verdict: ""
+    filing: ""
+    review: ""
+  effort: ""
+  timeout_seconds: 240.0
+  filing_timeout_seconds: 420.0
+  standard_reads_per_day: 15
+  deep_reads_per_day: 3
+  top_per_list: 15           # the automatic set: the top healthy names per list (trading)
+  stale_fv_pct: 5.0          # Python's fair value moved more than 5%: the name is re-read
+  max_age_days: 30           # a verdict older than this is re-read when the budget allows
+  max_headlines: 12
+  breaker:                   # §8.2: Claude's verdict stops applying until the operator resets it
+    sessions: 20
+    ready_multiple: 3.0      # Claude's READYs above 3 x the baseline's ...
+    min_ready: 5             # ... and at least 5
+    clamp_rate_pct: 25.0     # or the 1.5x clamp binding on more than 25% of Claude's values ...
+    min_values: 8            # ... read over at least 8 of them
diff --git a/src/common/config.py b/src/common/config.py
index a7511c5..2ca14f3 100644
--- a/src/common/config.py
+++ b/src/common/config.py
@@ -1665,6 +1665,53 @@ class ValueReevaluationCfg(_ValueModel):
         return self
 
 
+_KILL_BOUNDS: dict[str, tuple[float, float]] = {
+    # spec §8.4: the menu's numeric predicates and the range Claude's threshold is held to
+    "revenue_growth_below": (-30.0, 10.0),  # latest fiscal year's revenue growth, percent
+    "net_debt_to_ebitda_above": (1.0, 6.0),
+    "dilution_above": (1.0, 10.0),  # diluted share count growth, percent a year
+    "gross_margin_below": (0.0, 90.0),  # latest fiscal year's gross margin, percent
+}
+
+
+class ValueClaudeRulesCfg(_ValueModel):
+    """Spec §8.2 and §8.4: the bounds Claude's valuation drivers are held to, the clamp on
+    Claude's fair value, the kill-trigger menu's threshold ranges and trigger 6's nearness.
+    Under ``rules:``, so every key is in the ruleset fingerprint (v4). Growth and margins are
+    fractions, like ``rules.valuation``; ``*_pts`` and ``*_pct`` are percent."""
+
+    clamp_multiple: float = 1.5  # Claude's fair value is capped at 1.5 x Python's
+    growth_floor: float = -0.10  # FCF/share growth, years 1-5: never below -10% ...
+    growth_cap: float = 0.30  # ... never above 30% ...
+    growth_over_realised: float = 0.05  # ... nor the realised 5-year CAGR + 5 points
+    terminal_min: float = 0.0
+    terminal_max: float = 0.025
+    discount_max: float = 0.12  # the floor is the list's Python rate (rules.valuation)
+    margin_band_pts: float = 5.0  # normalised FCF margin: +-5 points of the 5-year median
+    rote_band_pts: float = 4.0  # banks and insurers: sustainable ROTE +-4 points of the median
+    max_kill_triggers: int = 5
+    kill_bounds: dict[str, tuple[float, float]] = Field(default_factory=lambda: dict(_KILL_BOUNDS))
+    kill_near_pct: float = 10.0  # trigger 6: a predicate within 10% of its threshold
+
+    @model_validator(mode="after")
+    def _sane(self) -> ValueClaudeRulesCfg:
+        if self.clamp_multiple < 1.0:
+            raise ValueError("value rules.claude.clamp_multiple must be >= 1")
+        if not self.growth_floor < 0 < self.growth_cap or self.growth_over_realised < 0:
+            raise ValueError("value rules.claude: growth_floor < 0 < growth_cap")
+        if not 0 <= self.terminal_min <= self.terminal_max < self.discount_max:
+            raise ValueError("value rules.claude: 0 <= terminal_min <= terminal_max < discount_max")
+        if self.margin_band_pts <= 0 or self.rote_band_pts <= 0:
+            raise ValueError("value rules.claude: the margin and ROTE bands must be positive")
+        if not 1 <= self.max_kill_triggers <= 8 or not 0 < self.kill_near_pct < 100:
+            raise ValueError("value rules.claude: 1-8 kill triggers, kill_near_pct in (0, 100)")
+        if set(self.kill_bounds) != set(_KILL_BOUNDS):
+            raise ValueError(f"value rules.claude.kill_bounds keys are {sorted(_KILL_BOUNDS)}")
+        if any(lo >= hi for lo, hi in self.kill_bounds.values()):
+            raise ValueError("value rules.claude.kill_bounds: each low must be below its high")
+        return self
+
+
 class ValueRulesCfg(_ValueModel):
     """Every key that can change a verdict. Hashed into the ruleset fingerprint (spec §6.8)."""
 
@@ -1678,6 +1725,7 @@ class ValueRulesCfg(_ValueModel):
     timing: ValueTimingCfg = Field(default_factory=ValueTimingCfg)
     exits: ValueExitsCfg = Field(default_factory=ValueExitsCfg)
     reevaluation: ValueReevaluationCfg = Field(default_factory=ValueReevaluationCfg)
+    claude: ValueClaudeRulesCfg = Field(default_factory=ValueClaudeRulesCfg)
 
 
 class ValueUniverseCfg(_ValueModel):
@@ -1725,17 +1773,85 @@ class ValueServiceCfg(_ValueModel):
         return self
 
 
+class ValueClaudeModelsCfg(_ValueModel):
+    """Spec §8.5: a model per call kind; "" = ``claude.model``. A cheaper model takes a kind only
+    after it passes the blinded claim-level audit, recorded in STATUS.md."""
+
+    verdict: str = ""
+    filing: str = ""
+    review: str = ""
+
+
+class ValueClaudeBreakerCfg(_ValueModel):
+    """Spec §8.2's breaker: over the last ``sessions`` nightly runs, Claude's READY count above
+    ``ready_multiple`` x the baseline's (and at least ``min_ready``), or the 1.5x clamp binding on
+    more than ``clamp_rate_pct`` of Claude's fair values, stops Claude's verdict applying until
+    the operator resets it (``python -m scripts.value_claude --reset-breaker``)."""
+
+    sessions: int = 20
+    ready_multiple: float = 3.0
+    min_ready: int = 5  # a handful of READYs never trips it while the baseline has none
+    clamp_rate_pct: float = 25.0
+    min_values: int = 8  # the clamp rate is read over at least this many fair values
+
+
+def _outside_repo(v: str, key: str) -> str:
+    p = Path(v).expanduser()
+    if not p.is_absolute():
+        raise ValueError(f"{key} must be absolute or start with ~")
+    if p.resolve() == ROOT or ROOT in p.resolve().parents:
+        raise ValueError(f"{key} must be outside the repo: claude would load the repo's CLAUDE.md")
+    return v
+
+
+class ValueClaudeCfg(_ValueModel):
+    """Spec §8: Claude as the analyst (``src/value_ai/``). Operational keys, not rules: they
+    decide when Claude reads and whether its verdict applies, never how a number is computed."""
+
+    enabled: bool = False  # Claude reads spend the subscription's tokens: on by the operator
+    apply_live: bool = False  # live: Claude's verdict and fair value are recorded, not applied
+    ollama_fallback: bool = False  # an Ollama reply is stored labelled, never effective
+    workdir: str = "~/.cache/ibkr-value-ai"  # outside the repo (cli.build_cmd's rule)
+    models: ValueClaudeModelsCfg = Field(default_factory=ValueClaudeModelsCfg)
+    effort: Literal["", "low", "medium", "high", "xhigh", "max"] = ""
+    timeout_seconds: float = 240.0
+    filing_timeout_seconds: float = 420.0
+    standard_reads_per_day: int = 15
+    deep_reads_per_day: int = 3
+    top_per_list: int = 15  # the automatic set: the top healthy names per list (trading)
+    stale_fv_pct: float = 5.0  # Python's fair value moved more than this: re-read the name
+    max_age_days: int = 30  # a verdict older than this is re-read when the budget allows
+    max_headlines: int = 12
+    breaker: ValueClaudeBreakerCfg = Field(default_factory=ValueClaudeBreakerCfg)
+
+    @field_validator("workdir")
+    @classmethod
+    def _workdir_outside_repo(cls, v: str) -> str:
+        return _outside_repo(v, "value claude.workdir")
+
+    @model_validator(mode="after")
+    def _sane(self) -> ValueClaudeCfg:
+        if self.timeout_seconds <= 0 or self.filing_timeout_seconds <= 0:
+            raise ValueError("value claude: timeouts must be positive")
+        if min(self.standard_reads_per_day, self.deep_reads_per_day, self.top_per_list) < 0:
+            raise ValueError("value claude: budgets must be >= 0")
+        if self.stale_fv_pct <= 0 or self.max_age_days < 1 or self.max_headlines < 0:
+            raise ValueError("value claude: stale_fv_pct > 0, max_age_days >= 1")
+        return self
+
+
 class ValueCfg(_ValueModel):
-    """The value book (config/value.yaml). Parts 1-3: the scorecard, the shadow record and its
-    re-evaluations, nothing that trades."""
+    """The value book (config/value.yaml). Parts 1-4: the scorecard, the shadow record, its
+    re-evaluations and Claude as the analyst; nothing that trades."""
 
-    ruleset_version: str = "v3"
+    ruleset_version: str = "v4"
     db_url: str = "sqlite:///data/value.db"
     universe: ValueUniverseCfg = Field(default_factory=ValueUniverseCfg)
     ticker_file: ValueTickerFileCfg = Field(default_factory=ValueTickerFileCfg)
     research_sweep: ValueResearchSweepCfg = Field(default_factory=ValueResearchSweepCfg)
     service: ValueServiceCfg = Field(default_factory=ValueServiceCfg)
     rules: ValueRulesCfg = Field(default_factory=ValueRulesCfg)
+    claude: ValueClaudeCfg = Field(default_factory=ValueClaudeCfg)
 
 
 class _KeyedCfg(BaseModel):
diff --git a/src/value/ruleset.py b/src/value/ruleset.py
index 93db8a5..ac85fea 100644
--- a/src/value/ruleset.py
+++ b/src/value/ruleset.py
@@ -18,7 +18,14 @@ from src.common.config import ValueCfg, ValueRulesCfg
 # v3 (Part 3): v2 unchanged, plus `rules.reevaluation` (spec §7.1), frozen before the first
 # re-evaluation; it also versions Part 3's exit-engine code (shock stops, the 8-K and
 # going-concern thesis exits, review minors M1 M5 M6 M14), which the hash cannot see.
-FROZEN: dict[str, str] = {"v1": "e1a1b3b096b1", "v2": "d07717fe5348", "v3": "ad8841127029"}
+# v4 (Part 4): v3 unchanged, plus `rules.claude` (spec §8.2 driver bounds and the 1.5x clamp,
+# §8.4 kill-trigger ranges, trigger 6's nearness), frozen before Claude's first read.
+FROZEN: dict[str, str] = {
+    "v1": "e1a1b3b096b1",
+    "v2": "d07717fe5348",
+    "v3": "ad8841127029",
+    "v4": "be30d1eaa915",
+}
 
 
 def ruleset_hash(rules: ValueRulesCfg) -> str:
```

- [x] **Step 4: Run them to see them pass, and check the hash**

  Run: `.venv/bin/python -m pytest -q tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_service.py tests/test_value_scorecard.py tests/test_private_config.py tests/test_config_keys.py`
  Expected: PASS. Then
  `.venv/bin/python -c "from src.common.config import ValueCfg; from src.value.ruleset import ruleset_hash; print(ruleset_hash(ValueCfg().rules))"`
  prints `be30d1eaa915`. If it prints anything else, the config or the example differs from this
  plan: stop and report (do not re-pin).

- [x] **Step 5: Gates and commit**

  Run: `.venv/bin/ruff check src/common/config.py src/value/ruleset.py tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_service.py`,
  the same paths with `.venv/bin/ruff format --check`, and `.venv/bin/mypy src/common/config.py src/value/ruleset.py`.

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md src/common/config.py src/value/ruleset.py config/examples/value.yaml tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_service.py
  git commit -m "feat(value): ruleset v4 - Claude's bounds under rules.claude, its switches under value.claude"
  ```

---

### Task 2: The shapes, the scorecard's inputs for Claude, and Claude's fair value

**Files:**
- Create: `src/common/value_ai_types.py`, `src/value/claude_valuation.py`,
  `tests/test_value_claude_valuation.py`
- Modify: `src/value/scorecard.py` (line 15 import; insert before `def _verdict(` at line 91; one
  line before the `card = card.model_copy(` whose update carries `"reverse_dcf_implied_growth"`,
  line 265), `tests/test_value_scorecard.py` (append)

**Interfaces:**
- Consumes: `ValueClaudeRulesCfg` (Task 1), `valuation.Dcf`, `ValueScorecard`.
- Produces: `value_ai_types` (`Range`, `DriverBounds`, `Drivers`, `FilingSection`,
  `AnalystRequest`, `ListCall`, `KillTrigger`, `ProposedFact`, `AnalystReply`, `AnalystCall`,
  `AnalystResult`, `KILL_KINDS`, `FACT_KINDS`); scorecard `metrics` keys `fcf_margin_median_5y`,
  `fcf_margin_best_5y`, `gfcf_margin_median_5y`, `gfcf_margin_best_5y`, `revenue_ps_ttm`,
  `revenue_growth_1y`, `gross_margin_latest`; `claude_valuation.bounds_for`, `clamp_drivers`,
  `two_stage_dcf`, `claude_fair_value -> ClaudeValue(fair_value, uncapped, python_fair_value,
  clamp_bound, unreliable, clamps, drivers, terminal_share)`.

The pinned numbers (computed on the Steady Co fixture, price 30): deep value's Python fair value is
46.85 (ceiling 35.14); the deep FCF margin (FCF − SBC over revenue) has a 5-year median of 15.59%
and a best of 16.25%; revenue per share is $16; the realised FCF/share CAGR is 14.74%, so Claude's
growth may reach 19.74%. Drivers 15% growth, 2.5% terminal, 9% discount, 16% margin give a base of
$2.56 and an uncapped value of 80.99, capped at 1.5 x 46.85 = 70.28. Drivers 12% / 2% / 9% / 17% on
the growth list give 69.06, below Python's 86.87, so nothing is capped. The bank fixture (HBR) has a
5-year median ROTE of 14.03% and tangible book of $21.50 a share; ROTE 12%, terminal 2%, discount
10% give (0.12 − 0.02) / (0.10 − 0.02) x 21.5 = 26.875.

- [x] **Step 1: Write the failing tests** — create `tests/test_value_claude_valuation.py`:

```python
"""Claude's fair value, computed and clamped by Python (value book spec §8.2)."""

from __future__ import annotations

import pytest

from src.common.config import ValueCfg, get_config
from src.common.value_ai_types import Drivers
from src.value.claude_valuation import bounds_for, clamp_drivers, claude_fair_value, two_stage_dcf
from src.value.scorecard import build_scorecard
from tests.value_fixtures import BANK, financials, inputs

CFG = get_config().value
RULES = CFG.rules
STEADY = build_scorecard(inputs(close=30.0), CFG)  # deep FV 46.85, growth FV 86.87
HBR = build_scorecard(
    inputs(symbol="HBR", fin=financials(BANK), close=40.0, industry="Diversified Banks"), CFG
)


def test_the_bounds_come_from_the_companys_own_history() -> None:
    deep = bounds_for(STEADY, "deep_value", RULES)
    assert deep is not None and deep.method == "dcf"
    assert deep.growth is not None and deep.margin is not None
    # growth: -10% to the lower of 30% and the realised 14.74% CAGR + 5 points
    assert (deep.growth.lo, deep.growth.hi) == (-0.10, pytest.approx(0.19741499781411548))
    # margin: the 5-year median 15.59% +- 5 points, never above the best (16.25%)
    assert deep.margin.lo == pytest.approx(0.10590551181102363)
    assert deep.margin.hi == pytest.approx(0.1625)
    assert (deep.discount.lo, deep.discount.hi) == (0.09, 0.12)  # never below Python's 9%
    growth = bounds_for(STEADY, "quality_growth", RULES)
    assert growth is not None and growth.discount.lo == 0.08  # the growth list's 8%
    assert growth.margin is not None and growth.margin.hi == pytest.approx(0.175)  # half SBC
    bank = bounds_for(HBR, "deep_value", RULES)
    assert bank is not None and bank.method == "ptbv" and bank.rote is not None
    assert (bank.rote.lo, bank.rote.hi) == (
        pytest.approx(0.10025974025974024),
        pytest.approx(0.18025974025974026),
    )


def test_every_driver_out_of_bounds_is_clamped_and_recorded() -> None:
    bounds = bounds_for(STEADY, "deep_value", RULES)
    assert bounds is not None
    kept, clamps = clamp_drivers(
        Drivers(growth=0.40, terminal=0.03, discount=0.07, margin=0.30), bounds
    )
    assert kept is not None
    assert (kept.growth, kept.terminal, kept.discount, kept.margin) == (
        pytest.approx(0.19741499781411548),
        0.025,
        0.09,
        0.1625,
    )
    assert clamps == [
        "growth 0.4000 -> 0.1974",
        "terminal 0.0300 -> 0.0250",
        "discount 0.0700 -> 0.0900",
        "margin 0.3000 -> 0.1625",
    ]
    missing, _ = clamp_drivers(Drivers(growth=0.1, terminal=0.02, discount=0.09), bounds)
    assert missing is None  # a malformed driver set means no Claude fair value


def test_the_two_stage_dcf() -> None:
    # $1 of FCF, 10% for five years then fading to 2.5% by year 10, at 9%.
    out = two_stage_dcf(1.0, 0.10, 0.09, 0.025)
    assert out is not None
    assert out.value == pytest.approx(24.03334204118441)
    assert out.terminal_share == pytest.approx(0.5827978862700297)
    assert two_stage_dcf(1.0, 0.10, 0.025, 0.025) is None  # rate at terminal growth


def test_a_value_above_one_and_a_half_times_pythons_is_capped_and_the_cap_used() -> None:
    v = claude_fair_value(
        STEADY,
        "deep_value",
        Drivers(growth=0.15, terminal=0.025, discount=0.09, margin=0.16),
        RULES,
    )
    assert v.uncapped == pytest.approx(80.98530915510761)
    assert v.fair_value == pytest.approx(1.5 * 46.853626592284414)  # 70.28
    assert v.clamp_bound is True and v.clamps == []


def test_lowering_is_never_capped() -> None:
    v = claude_fair_value(
        STEADY,
        "quality_growth",
        Drivers(growth=0.12, terminal=0.02, discount=0.09, margin=0.17),
        RULES,
    )
    assert v.fair_value == pytest.approx(69.06334253911646)  # below Python's 86.87
    assert v.clamp_bound is False


def test_a_bank_is_valued_on_claudes_rote() -> None:
    v = claude_fair_value(
        HBR, "deep_value", Drivers(rote=0.12, terminal=0.02, discount=0.10), RULES
    )
    assert v.fair_value == pytest.approx((0.12 - 0.02) / (0.10 - 0.02) * 21.5)  # 26.875


def test_a_terminal_value_above_three_quarters_is_unreliable() -> None:
    loose = ValueCfg(
        ruleset_version="test", rules={"claude": {"terminal_max": 0.08, "discount_max": 0.12}}
    ).rules
    v = claude_fair_value(
        STEADY,
        "deep_value",
        Drivers(growth=0.15, terminal=0.08, discount=0.09, margin=0.16),
        loose,
    )
    assert v.fair_value is None and v.unreliable == "terminal value above 75% of the whole"
    assert v.terminal_share is not None and v.terminal_share > 0.75


def test_without_pythons_fair_value_claudes_cannot_be_used() -> None:
    card = STEADY.model_copy(
        update={
            "lists": {
                "deep_value": STEADY.lists["deep_value"].model_copy(update={"fair_value": None})
            }
        }
    )
    v = claude_fair_value(
        card, "deep_value", Drivers(growth=0.1, terminal=0.02, discount=0.09, margin=0.15), RULES
    )
    assert v.fair_value is None and v.unreliable == "Python has no fair value for this list"
    assert bounds_for(STEADY, "no_such_list", RULES) is None
```

  …and append to `tests/test_value_scorecard.py`:

```diff
diff --git a/tests/test_value_scorecard.py b/tests/test_value_scorecard.py
index 06a7083..0d62ffa 100644
--- a/tests/test_value_scorecard.py
+++ b/tests/test_value_scorecard.py
@@ -183,3 +183,16 @@ def test_the_scorecard_is_a_pure_function_of_its_inputs() -> None:
         build_scorecard(inputs(), CFG).model_dump_json()
         == build_scorecard(inputs(), CFG).model_dump_json()
     )
+
+
+def test_the_scorecard_carries_what_claudes_bounds_and_triggers_read() -> None:
+    """Spec §8.2, §8.4: the margins' 5-year median and best on each list's SBC basis, revenue
+    per share, the newest year's revenue growth and gross margin."""
+    m = build_scorecard(inputs(close=30.0), CFG).metrics
+    assert m["fcf_margin_median_5y"] == pytest.approx(0.15590551181102363)  # (FCF - SBC) / rev
+    assert m["fcf_margin_best_5y"] == pytest.approx(0.1625)
+    assert m["gfcf_margin_median_5y"] == pytest.approx(0.16850393700787403)  # half of SBC
+    assert m["gfcf_margin_best_5y"] == pytest.approx(0.175)
+    assert m["revenue_ps_ttm"] == pytest.approx(16.0)
+    assert m["revenue_growth_1y"] == pytest.approx(1600 / 1420 - 1)
+    assert m["gross_margin_latest"] == pytest.approx(0.6)
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_claude_valuation.py tests/test_value_scorecard.py`
  Expected: FAIL — `ModuleNotFoundError: No module named 'src.common.value_ai_types'` (collection
  error) and `KeyError: 'fcf_margin_median_5y'`.

- [x] **Step 3: The shapes** — create `src/common/value_ai_types.py`:

```python
"""Plain shapes between the value book and Claude (value book spec §8).

Neutral on purpose, like ``value_types.py``: standard library and pydantic only, so
``src/value/`` (deterministic, the only writer of value.db) and ``src/value_ai/`` (enrichment,
the only caller of Claude for the value book) share one definition without either importing the
other (tests/test_value_fence.py). Claude never sees a database row and ``src/value/`` never sees
a prompt: a request goes out as an ``AnalystRequest`` and comes back as an ``AnalystResult``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ReadKind = Literal["standard", "filing", "review"]
ClaudeVerdict = Literal["READY", "WATCH", "WAIT", "NO"]
ReviewState = Literal["INTACT", "WEAKENED", "BROKEN"]
Backend = Literal["cli", "ollama"]
KillKind = Literal[
    "revenue_growth_below",
    "fcf_ttm_negative",
    "net_debt_to_ebitda_above",
    "dilution_above",
    "gross_margin_below",
    "guidance_cut",
    "customer_loss",
]
KILL_KINDS: tuple[str, ...] = (
    "revenue_growth_below",
    "fcf_ttm_negative",
    "net_debt_to_ebitda_above",
    "dilution_above",
    "gross_margin_below",
    "guidance_cut",
    "customer_loss",
)
FactKind = Literal[
    "one_off",
    "segment_revenue",
    "guidance",
    "backlog",
    "customer_concentration",
    "covenant",
    "share_class_count",
    "guidance_cut",
    "customer_loss",
]
FACT_KINDS: tuple[str, ...] = (
    "one_off",
    "segment_revenue",
    "guidance",
    "backlog",
    "customer_concentration",
    "covenant",
    "share_class_count",
    "guidance_cut",
    "customer_loss",
)


class Range(BaseModel):
    lo: float
    hi: float


class DriverBounds(BaseModel):
    """Where Claude's drivers for one list must sit (spec §8.2), computed by Python from the
    company's own history. ``method`` ``dcf``: growth, terminal, discount, margin; ``ptbv``
    (banks and insurers): rote, terminal, discount."""

    list_name: str
    method: Literal["dcf", "ptbv"]
    growth: Range | None = None
    terminal: Range
    discount: Range
    margin: Range | None = None
    rote: Range | None = None


class Drivers(BaseModel):
    """Claude's assumptions for one list. Fractions (0.12 = 12%). Unknown is None."""

    growth: float | None = None  # FCF/share growth, years 1-5
    terminal: float | None = None
    discount: float | None = None
    margin: float | None = None  # normalised FCF margin
    rote: float | None = None  # sustainable return on tangible equity


class FilingSection(BaseModel):
    """One slice of a filing the research worker cut out (spec §8.5): Item 1, 1A, 7, ..."""

    accn: str
    form: str
    section: str
    text: str


class AnalystRequest(BaseModel):
    """One read, as the value process hands it to ``src/value_ai/``."""

    read_id: int
    symbol: str
    kind: ReadKind
    reason: str  # request | review | filing | top | stale
    lists: list[str]
    card_text: str  # the scorecard, rendered by src/value as labelled numbers
    bounds: list[DriverBounds] = Field(default_factory=list)
    kill_menu: dict[str, Range | None] = Field(default_factory=dict)
    max_kill_triggers: int = 5
    trigger_text: str = ""  # a review: what fired, the plan before and after
    sections: list[FilingSection] = Field(default_factory=list)  # a filing read
    model: str = ""
    effort: str = ""
    timeout_seconds: float = 240.0


class ListCall(BaseModel):
    list_name: str
    verdict: ClaudeVerdict
    why: str = ""
    drivers: Drivers = Field(default_factory=Drivers)


class KillTrigger(BaseModel):
    kind: KillKind
    threshold: float | None = None  # in the menu's unit; None for the fact-based kinds


class ProposedFact(BaseModel):
    """A number or claim Claude read in a filing, with the accession and a verbatim quote, for
    ``src/value/grounding.py`` to check (spec §8.2 "Grounded facts")."""

    kind: FactKind
    value: float | None = None
    unit: str = ""
    accn: str
    quote: str
    item: str | None = None  # a canonical XBRL item (revenue, sbc, ...) when it is one


class AnalystReply(BaseModel):
    """A reply that passed the shape check. Nothing here has been bounded or verified yet."""

    lists: list[ListCall] = Field(default_factory=list)
    profile: str = ""
    why_cheap: str = ""
    thesis: str = ""
    bear_case: str = ""
    kill_triggers: list[KillTrigger] = Field(default_factory=list)
    review_state: ReviewState | None = None
    review_why: str = ""
    facts: list[ProposedFact] = Field(default_factory=list)


class AnalystCall(BaseModel):
    """What the call cost and who answered. ``backend`` ``ollama`` is never effective."""

    model: str = ""
    backend: Backend = "cli"
    latency_ms: int = 0
    cost_usd: float | None = None
    error: str | None = None
    prompt_version: str = ""
    prompt: str = ""
    raw: str = ""


class AnalystResult(BaseModel):
    read_id: int
    reply: AnalystReply | None = None  # None: no notes (a failure or a malformed reply)
    call: AnalystCall = Field(default_factory=AnalystCall)
```

- [x] **Step 4: The scorecard's inputs for Claude** — apply:

```diff
diff --git a/src/value/scorecard.py b/src/value/scorecard.py
index 852a3d9..6ee8414 100644
--- a/src/value/scorecard.py
+++ b/src/value/scorecard.py
@@ -12,7 +12,7 @@ from src.common.config import ValueCfg
 from src.common.schemas import MarketRegime
 from src.common.value_types import ValueInputs
 from src.value import gates, timing, valuation
-from src.value.metrics import Year, cagr, median_of, roic, stdev_of
+from src.value.metrics import Year, cagr, last_n, median_of, roic, stdev_of
 from src.value.ruleset import ruleset_id
 from src.value.schemas import (
     Check,
@@ -88,6 +88,37 @@ def _fcf_ps_series(years: list[Year]) -> list[float | None]:
     return [None if y.fcf is None or not y.shares else y.fcf / y.shares for y in years]
 
 
+def _fcf_margins(years: list[Year], sbc_share: float) -> list[float | None]:
+    return [
+        None if y.fcf is None or not y.revenue else (y.fcf - sbc_share * (y.sbc or 0.0)) / y.revenue
+        for y in years
+    ]
+
+
+def claude_inputs(
+    inputs: ValueInputs, years: list[Year], per_share: float | None, growth_sbc_share: float
+) -> dict[str, float | None]:
+    """What Claude's drivers are bounded by and Python's kill-trigger menu reads (spec §8.2,
+    §8.4), all from filed history: the normalised FCF margin's 5-year median and best on each
+    list's SBC basis (all of it for deep value, ``growth_sbc_share`` for quality growth), TTM
+    revenue per share, and the newest year's revenue growth and gross margin (fractions)."""
+    out: dict[str, float | None] = {}
+    for prefix, share in (("fcf", 1.0), ("gfcf", growth_sbc_share)):
+        margins = last_n(_fcf_margins(years, share))
+        out[f"{prefix}_margin_median_5y"] = median(margins) if margins else None
+        out[f"{prefix}_margin_best_5y"] = max(margins) if margins else None
+    revenue = _ttm(inputs, "revenue")
+    out["revenue_ps_ttm"] = None if revenue is None or not per_share else revenue / per_share
+    newest, prior = (years[0], years[1]) if len(years) > 1 else (None, None)
+    out["revenue_growth_1y"] = (
+        newest.revenue / prior.revenue - 1.0
+        if newest is not None and prior is not None and newest.revenue and prior.revenue
+        else None
+    )
+    out["gross_margin_latest"] = years[0].gross_margin if years else None
+    return out
+
+
 def _verdict(
     health: GateState,
     health_checks: list[Check],
@@ -259,6 +290,7 @@ def build_scorecard(inputs: ValueInputs, cfg: ValueCfg) -> ValueScorecard:
         "gross_margin_stdev_5y": stdev_of([y.gross_margin for y in years]),
         "revenue_cagr_5y": cagr([y.revenue for y in years]),
     }
+    metrics.update(claude_inputs(inputs, years, per_share, v.growth_sbc_share))
     card = card.model_copy(
         update={
             "metrics": metrics,
```

- [x] **Step 5: Claude's fair value** — create `src/value/claude_valuation.py`:

```python
"""Claude's fair value, computed by Python (spec §8.2). Pure: no I/O.

Claude never returns a fair value. It returns **drivers** (growth, terminal growth, discount
rate, normalised FCF margin; sustainable ROTE for banks and insurers), each held to a bound
Python derives from the company's own filed history. Python clamps every driver into its bound
(recording the clamp), runs the arithmetic, drops the result as ``unreliable`` when the terminal
value is more than 75% of the whole (the validator of spec §6.5), and caps it at
``clamp_multiple`` (1.5) x Python's own fair value for the list. The capped value is the one
that is used; the uncapped one is kept for the operator to read. Where Python has no fair value,
Claude's cannot be used either.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.common.config import ValueRulesCfg
from src.common.value_ai_types import DriverBounds, Drivers, Range
from src.value.schemas import ValueScorecard
from src.value.valuation import Dcf

_FINANCIAL = ("bank", "insurer")
HOLD_YEARS = 5  # Claude's growth holds for years 1-5, then fades to terminal by year 10


@dataclass(frozen=True, slots=True)
class ClaudeValue:
    """One list's Claude fair value. ``fair_value`` is the usable (capped) number, None when
    the drivers were unusable (``unreliable`` says why)."""

    fair_value: float | None
    uncapped: float | None = None
    python_fair_value: float | None = None
    clamp_bound: bool = False  # the 1.5x cap set the value (the breaker counts these)
    unreliable: str | None = None
    clamps: list[str] = field(default_factory=list)  # each driver moved into its bound
    drivers: Drivers = field(default_factory=Drivers)  # after clamping
    terminal_share: float | None = None


def bounds_for(card: ValueScorecard, list_name: str, rules: ValueRulesCfg) -> DriverBounds | None:
    """The bounds for one list (spec §8.2's table), or None when the history needed to set them
    is missing (then Claude's drivers cannot be used for that list)."""
    if card.lists.get(list_name) is None:
        return None
    c, v = rules.claude, rules.valuation
    floor = v.discount_rate_deep if list_name == "deep_value" else v.discount_rate_growth
    terminal = Range(lo=c.terminal_min, hi=c.terminal_max)
    discount = Range(lo=floor, hi=c.discount_max)
    m = card.metrics
    if card.company_class in _FINANCIAL:
        rote = m.get("rote_median_5y")
        if rote is None or m.get("tbv_ps") is None:
            return None
        band = c.rote_band_pts / 100.0
        return DriverBounds(
            list_name=list_name,
            method="ptbv",
            terminal=terminal,
            discount=discount,
            rote=Range(lo=rote - band, hi=rote + band),
        )
    prefix = "fcf" if list_name == "deep_value" else "gfcf"
    median, best = m.get(f"{prefix}_margin_median_5y"), m.get(f"{prefix}_margin_best_5y")
    if median is None or best is None or m.get("revenue_ps_ttm") is None:
        return None
    band = c.margin_band_pts / 100.0
    realised = card.realised_fcf_ps_cagr if card.realised_fcf_ps_cagr is not None else 0.0
    growth_hi = max(c.growth_floor, min(c.growth_cap, realised + c.growth_over_realised))
    return DriverBounds(
        list_name=list_name,
        method="dcf",
        growth=Range(lo=c.growth_floor, hi=growth_hi),
        terminal=terminal,
        discount=discount,
        margin=Range(lo=median - band, hi=min(median + band, best)),
    )


def clamp_drivers(drivers: Drivers, bounds: DriverBounds) -> tuple[Drivers | None, list[str]]:
    """Each driver the method needs, moved into its bound; None when one is missing (a
    malformed driver set means no Claude fair value, never a guess)."""
    names = (
        ("rote", "terminal", "discount")
        if bounds.method == "ptbv"
        else ("growth", "terminal", "discount", "margin")
    )
    out: dict[str, float] = {}
    clamps: list[str] = []
    for name in names:
        value = getattr(drivers, name)
        bound: Range | None = getattr(bounds, name)
        if value is None or bound is None:
            return None, clamps
        kept = min(max(value, bound.lo), bound.hi)
        if kept != value:
            clamps.append(f"{name} {value:.4f} -> {kept:.4f}")
        out[name] = kept
    return Drivers(**out), clamps


def two_stage_dcf(
    base: float, growth: float, rate: float, terminal: float, years: int = 10
) -> Dcf | None:
    """Per-share DCF: *growth* for years 1-5, then fading linearly to *terminal* by the last
    year; the terminal value is the last year's cash flow grown once at *terminal* and
    capitalised at (rate - terminal). None when rate <= terminal or the total is not
    positive."""
    if rate <= terminal or years <= HOLD_YEARS:
        return None
    cash, pv = base, 0.0
    for k in range(1, years + 1):
        g = (
            growth
            if k <= HOLD_YEARS
            else growth + (terminal - growth) * (k - HOLD_YEARS) / (years - HOLD_YEARS)
        )
        cash *= 1.0 + g
        pv += cash / (1.0 + rate) ** k
    pv_terminal = cash * (1.0 + terminal) / (rate - terminal) / (1.0 + rate) ** years
    total = pv + pv_terminal
    if total <= 0:
        return None
    return Dcf(value=total, terminal_share=pv_terminal / total)


def claude_fair_value(
    card: ValueScorecard, list_name: str, drivers: Drivers, rules: ValueRulesCfg
) -> ClaudeValue:
    """Spec §8.2: bound, compute, validate and clamp. Lowering is never capped."""
    ev = card.lists.get(list_name)
    python_fv = ev.fair_value if ev is not None else None
    if python_fv is None:
        return ClaudeValue(None, unreliable="Python has no fair value for this list")
    bounds = bounds_for(card, list_name, rules)
    if bounds is None:
        return ClaudeValue(None, python_fair_value=python_fv, unreliable="no history to bound")
    kept, clamps = clamp_drivers(drivers, bounds)
    if kept is None:
        return ClaudeValue(None, python_fair_value=python_fv, unreliable="a driver is missing")
    terminal_share: float | None = None
    if bounds.method == "ptbv":
        assert kept.rote is not None and kept.terminal is not None and kept.discount is not None
        tbv = card.metrics.get("tbv_ps")
        assert tbv is not None  # bounds_for refused a name without it
        if kept.rote <= kept.terminal or tbv <= 0:
            return ClaudeValue(
                None,
                python_fair_value=python_fv,
                unreliable="ROTE at or below growth",
                clamps=clamps,
                drivers=kept,
            )
        uncapped = (kept.rote - kept.terminal) / (kept.discount - kept.terminal) * tbv
    else:
        assert kept.margin is not None and kept.growth is not None
        assert kept.terminal is not None and kept.discount is not None
        revenue_ps = card.metrics.get("revenue_ps_ttm")
        assert revenue_ps is not None  # bounds_for refused a name without it
        base = kept.margin * revenue_ps
        out = (
            None
            if base <= 0
            else two_stage_dcf(
                base, kept.growth, kept.discount, kept.terminal, rules.valuation.dcf_years
            )
        )
        if out is None:
            return ClaudeValue(
                None,
                python_fair_value=python_fv,
                unreliable="the cash flow is not positive",
                clamps=clamps,
                drivers=kept,
            )
        terminal_share = out.terminal_share
        if terminal_share > rules.valuation.terminal_value_max_share:
            return ClaudeValue(
                None,
                uncapped=out.value,
                python_fair_value=python_fv,
                unreliable="terminal value above 75% of the whole",
                clamps=clamps,
                drivers=kept,
                terminal_share=terminal_share,
            )
        uncapped = out.value
    cap = rules.claude.clamp_multiple * python_fv
    return ClaudeValue(
        fair_value=min(uncapped, cap),
        uncapped=uncapped,
        python_fair_value=python_fv,
        clamp_bound=uncapped > cap,
        clamps=clamps,
        drivers=kept,
        terminal_share=terminal_share,
    )
```

- [x] **Step 6: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_claude_valuation.py tests/test_value_scorecard.py tests/test_value_shadow.py tests/test_value_service.py`
  Expected: PASS (the scorecard's new metrics change no verdict: the shadow and service tests
  confirm).

- [x] **Step 7: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the five touched files;
  `.venv/bin/mypy src/common/value_ai_types.py src/value/scorecard.py src/value/claude_valuation.py`.

  ```bash
  git add src/common/value_ai_types.py src/value/scorecard.py src/value/claude_valuation.py tests/test_value_claude_valuation.py tests/test_value_scorecard.py
  git commit -m "feat(value): Claude's fair value, bounded and clamped by Python (spec 8.2)"
  ```

---

### Task 3: The effective verdict and Claude's tables

**Files:**
- Create: `src/value/effective.py`, `tests/test_value_effective.py`
- Modify: `src/value/store.py` (the module docstring's last paragraph, line 27; insert before
  `_engine: Engine | None = None` at line 251), `tests/test_value_store.py` (append)

**Interfaces:**
- Consumes: `ValueScorecard` (its `lists[...].required_mos_pct`, `timing`, `price`, `health`).
- Produces: `effective.ClaudeOpinion(verdict, fair_value, verdict_id)`,
  `effective.Effective(list_name, verdict, decided_by, python_verdict, fair_value, entry_ceiling,
  margin_of_safety, mos_review, claude_verdict, verdict_id)`, `effective.effective(card, list_name,
  opinion, *, review_above_pct)`; tables `value_claude_reads` (`ValueClaudeReadRow`),
  `value_claude_verdicts` (`ValueClaudeVerdictRow`), `value_claude_notes`, `value_kill_triggers`,
  `value_claude_facts`, `value_effective` (`ValueEffectiveRow`, primary key symbol + list) and
  `value_claude_state`.

The nine pinned cases of `test_the_effective_verdict` are rulings 4 and 7 written down: Steady Co at
40 is Python WAIT (Python's ceiling 35.14); with Claude READY and a fair value of 60 the ceiling is
45, so 40 is READY; with 50 the ceiling is 37.50 and 40 is WAIT; and so on.

- [x] **Step 1: Write the failing tests** — create `tests/test_value_effective.py`:

```python
"""The effective verdict: Python's baseline, then Claude's call (value book spec §6.7)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.common.config import get_config
from src.value.effective import ClaudeOpinion, effective
from src.value.scorecard import build_scorecard
from tests.value_fixtures import AS_OF, financials, inputs

CFG = get_config().value
REVIEW = CFG.rules.margin_of_safety.review_above_pct
# Deep value: Python's fair value 46.85, required 25%, so Python's ceiling is 35.14.
CHEAP = build_scorecard(inputs(close=30.0), CFG)  # Python READY
DEAR = build_scorecard(inputs(close=40.0), CFG)  # Python WAIT (40 > 35.14)
SICK = build_scorecard(inputs(fin=financials(shares_diluted=[110, 104, 98, 92, 86])), CFG)
SOON = build_scorecard(inputs(close=30.0, next_earnings=AS_OF + timedelta(days=3)), CFG)


def _eff(card, verdict, fv, list_name="deep_value"):
    return effective(card, list_name, ClaudeOpinion(verdict, fv, 7), review_above_pct=REVIEW)


@pytest.mark.parametrize(
    ("card", "claude", "fv", "verdict", "by"),
    [
        (CHEAP, None, None, "READY", "python"),  # not read: Python only
        (CHEAP, "NO", 60.0, "NO", "claude"),  # Claude decides on a healthy name
        (DEAR, "READY", 60.0, "READY", "claude"),  # 40 <= 60 x 0.75 = 45: Claude lifts a WAIT
        (DEAR, "READY", 50.0, "WAIT", "claude"),  # 40 > 37.5: the margin applies to Claude's FV
        (CHEAP, "WAIT", 60.0, "WAIT", "claude"),  # Claude's WAIT stands though the price is in
        (CHEAP, "WATCH", 60.0, "WATCH", "claude"),
        (SOON, "READY", 60.0, "WATCH", "claude"),  # Python's timing gate applies on top
        (SICK, "READY", 60.0, "NO", "python"),  # a failed health gate is final
        (CHEAP, "READY", None, "READY", "python"),  # Claude's fair value unusable: baseline
    ],
)
def test_the_effective_verdict(card, claude, fv, verdict, by) -> None:
    opinion = None if claude is None else ClaudeOpinion(claude, fv, 7)
    out = effective(card, "deep_value", opinion, review_above_pct=REVIEW)
    assert (out.verdict, out.decided_by) == (verdict, by)


def test_claudes_fair_value_replaces_pythons_in_the_ceiling_and_the_margin() -> None:
    out = _eff(DEAR, "READY", 60.0)
    assert out.fair_value == 60.0 and out.entry_ceiling == pytest.approx(45.0)
    assert out.margin_of_safety == pytest.approx(1 / 3)
    assert out.python_verdict == "WAIT" and out.claude_verdict == "READY" and out.verdict_id == 7
    assert out.mos_review is False
    assert _eff(CHEAP, "READY", 90.0).mos_review is True  # a 67% margin goes to a human


def test_unknown_and_not_applicable_are_final() -> None:
    unknown = build_scorecard(inputs(yf_market_cap=6000.0), CFG)
    assert _eff(unknown, "READY", 60.0).verdict == "UNKNOWN"
    etf = build_scorecard(inputs(is_etf=True), CFG)
    assert _eff(etf, "READY", 60.0).verdict == "NOT_APPLICABLE"
```

  …and append to `tests/test_value_store.py`:

```diff
diff --git a/tests/test_value_store.py b/tests/test_value_store.py
index cfce7ad..6ec2a64 100644
--- a/tests/test_value_store.py
+++ b/tests/test_value_store.py
@@ -169,3 +169,19 @@ def test_init_adds_the_plan_columns_to_a_part_2_database(tmp_path, monkeypatch)
         assert s.scalars(select(ValueReevaluationRow)).first() is None
         assert s.scalars(select(ValueShadowEventRow)).first() is None
     store.reset_engine()
+
+
+def test_init_creates_claudes_tables(value_db) -> None:
+    """Part 4 (spec §8.3): Claude's half of the ticker file lives in its own tables."""
+    from sqlalchemy import inspect
+
+    names = set(inspect(store.get_value_engine()).get_table_names())
+    assert {
+        "value_claude_reads",
+        "value_claude_verdicts",
+        "value_claude_notes",
+        "value_kill_triggers",
+        "value_claude_facts",
+        "value_effective",
+        "value_claude_state",
+    } <= names
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_effective.py tests/test_value_store.py`
  Expected: FAIL — `ModuleNotFoundError: No module named 'src.value.effective'` and the missing
  tables.

- [x] **Step 3: The effective verdict** — create `src/value/effective.py`:

```python
"""The effective verdict (spec §6.7): Python's baseline, then Claude's call. Pure: no I/O.

- Python's ``NO``, ``UNKNOWN`` and ``NOT_APPLICABLE`` are final: Claude cannot lift a name over
  a health, data or list-entry gate, nor value a name Python cannot.
- On a healthy name with a usable Claude opinion (a CLI verdict that is not superseded, whose
  fair value Python computed and clamped, while the breaker is not tripped and Claude applies in
  this mode), Claude's fair value replaces Python's in the entry ceiling and the margin of
  safety, and the verdict is the **stricter** of Claude's word and what price and timing allow
  against Claude's fair value: Claude decides which state a name is in, Python's gates bound it.
  So a Claude READY with timing failing is WATCH, a Claude READY above Claude's own ceiling is
  WAIT, and a Claude WAIT stays WAIT until Claude reads the name again.
- Anything else keeps Python's baseline, labelled ``python``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.value.schemas import ValueScorecard

_RANK = {"NO": 0, "WAIT": 1, "WATCH": 2, "READY": 3}


@dataclass(frozen=True, slots=True)
class ClaudeOpinion:
    """What a stored Claude verdict says about one list, as the night reads it."""

    verdict: str  # READY | WATCH | WAIT | NO
    fair_value: float | None  # Claude's clamped fair value; None when unusable
    verdict_id: int | None = None


@dataclass(frozen=True, slots=True)
class Effective:
    list_name: str
    verdict: str
    decided_by: Literal["claude", "python"]
    python_verdict: str
    fair_value: float | None
    entry_ceiling: float | None
    margin_of_safety: float | None
    mos_review: bool
    claude_verdict: str | None = None
    verdict_id: int | None = None


def _python(card: ValueScorecard, list_name: str) -> Effective:
    ev = card.lists.get(list_name)
    return Effective(
        list_name=list_name,
        verdict=card.verdict_for(list_name),
        decided_by="python",
        python_verdict=card.verdict_for(list_name),
        fair_value=ev.fair_value if ev else None,
        entry_ceiling=ev.entry_ceiling if ev else None,
        margin_of_safety=ev.margin_of_safety if ev else None,
        mos_review=ev.mos_review if ev else False,
    )


def effective(
    card: ValueScorecard,
    list_name: str,
    opinion: ClaudeOpinion | None,
    *,
    review_above_pct: float,
) -> Effective:
    """One list's effective verdict. *opinion* is None when Claude has not read the name, its
    reply was not usable, the breaker is tripped, or Claude does not apply in this mode."""
    base = _python(card, list_name)
    ev = card.lists.get(list_name)
    if (
        opinion is None
        or opinion.fair_value is None
        or opinion.fair_value <= 0
        or ev is None
        or card.price is None
        or card.health != "pass"
        or base.verdict not in ("READY", "WATCH", "WAIT")
    ):
        return base
    fv = opinion.fair_value
    ceiling = fv * (1.0 - ev.required_mos_pct / 100.0)
    mos = (fv - card.price) / fv
    if card.price > ceiling:
        allowed = "WAIT"
    elif ev.timing != "pass":
        allowed = "WATCH"
    else:
        allowed = "READY"
    verdict = min(opinion.verdict, allowed, key=lambda v: _RANK[v])
    return Effective(
        list_name=list_name,
        verdict=verdict,
        decided_by="claude",
        python_verdict=base.python_verdict,
        fair_value=fv,
        entry_ceiling=ceiling,
        margin_of_safety=mos,
        mos_review=mos * 100.0 > review_above_pct,
        claude_verdict=opinion.verdict,
        verdict_id=opinion.verdict_id,
    )
```

- [x] **Step 4: Claude's tables** — apply:

```diff
diff --git a/src/value/store.py b/src/value/store.py
index 3edfe46..542a38d 100644
--- a/src/value/store.py
+++ b/src/value/store.py
@@ -25,6 +25,21 @@ Part 3 (spec §7.1):
 - ``value_shadow_legs.plan`` / ``value_shadow_events.plan`` - ``main`` (the re-evaluated plan) or
   ``original`` (the twin carried untouched from the first trigger on); added to an existing
   value.db by ``init_value_db``.
+
+Part 4 (spec §8, Claude as the analyst). Claude's half of the ticker file, every table labelled
+``source = claude`` in spirit: read only by display code and Claude's prompts, except
+``value_claude_verdicts``, the one the gate (Part 5) reads:
+- ``value_claude_reads`` - every read: queued, then done / failed / skipped, with the model,
+  the backend, the cost, the prompt and the raw reply;
+- ``value_claude_verdicts`` - per read and list: Claude's verdict, its drivers after Python
+  clamped them, and the fair value Python computed and capped at 1.5x its own;
+- ``value_claude_notes`` - profile, why cheap, thesis, bear case, review state;
+- ``value_kill_triggers`` - the predicates Claude picked from the menu, and Python's last
+  evaluation of each;
+- ``value_claude_facts`` - facts Claude proposed from a filing, each with whether
+  ``grounding.py`` accepted it;
+- ``value_effective`` - the effective verdict per name and list, rewritten every night;
+- ``value_claude_state`` - small key/value state (the breaker).
 """
 
 from __future__ import annotations
@@ -248,6 +263,154 @@ class ValueReevaluationRow(ValueBase):
     created_at: Mapped[datetime] = mapped_column(DateTime)
 
 
+class ValueClaudeReadRow(ValueBase):
+    """One Claude read of one name (spec §8.3, §8.5). ``kind``: standard | filing | review;
+    ``reason``: request | review | filing | top | stale; ``status``: queued | done | failed |
+    skipped. ``backend`` ``ollama`` is stored labelled and never decides anything."""
+
+    __tablename__ = "value_claude_reads"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    symbol: Mapped[str] = mapped_column(String(16), index=True)
+    kind: Mapped[str] = mapped_column(String(16))
+    reason: Mapped[str] = mapped_column(String(16))
+    priority: Mapped[int] = mapped_column(Integer)
+    status: Mapped[str] = mapped_column(String(16), default="queued")
+    detail: Mapped[str] = mapped_column(Text, default="")
+    requested_at: Mapped[datetime] = mapped_column(DateTime)
+    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
+    fingerprint_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
+    accn: Mapped[str | None] = mapped_column(String(32), nullable=True)
+    reevaluation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    model: Mapped[str] = mapped_column(String(64), default="")
+    backend: Mapped[str] = mapped_column(String(8), default="cli")
+    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
+    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
+    error: Mapped[str | None] = mapped_column(String(32), nullable=True)
+    prompt_version: Mapped[str] = mapped_column(String(32), default="")
+    prompt: Mapped[str] = mapped_column(Text, default="")
+    raw: Mapped[str] = mapped_column(Text, default="")
+
+    __table_args__ = (Index("ix_value_claude_reads_status", "status", "priority"),)
+
+
+class ValueClaudeVerdictRow(ValueBase):
+    """Claude's validated verdict on one list (spec §8.2, §8.3): a verdict from a fixed set,
+    the drivers after Python clamped them, and the fair value Python computed and capped. The
+    one Claude table the gate reads (spec §9.4, §16)."""
+
+    __tablename__ = "value_claude_verdicts"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    read_id: Mapped[int] = mapped_column(Integer, index=True)
+    symbol: Mapped[str] = mapped_column(String(16))
+    list_name: Mapped[str] = mapped_column(String(16))
+    verdict: Mapped[str] = mapped_column(String(8))
+    why: Mapped[str] = mapped_column(Text, default="")
+    drivers_json: Mapped[str] = mapped_column(Text)
+    clamps_json: Mapped[str] = mapped_column(Text, default="[]")
+    fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)  # capped: the one used
+    uncapped: Mapped[float | None] = mapped_column(Float, nullable=True)
+    python_fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)
+    clamp_bound: Mapped[bool] = mapped_column(Boolean, default=False)
+    unreliable: Mapped[str | None] = mapped_column(Text, nullable=True)
+    accn: Mapped[str | None] = mapped_column(String(32), nullable=True)
+    fingerprint_key: Mapped[str] = mapped_column(String(16))
+    backend: Mapped[str] = mapped_column(String(8))
+    created_at: Mapped[datetime] = mapped_column(DateTime)
+    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
+
+    __table_args__ = (Index("ix_value_claude_verdicts_key", "symbol", "list_name", "superseded"),)
+
+
+class ValueClaudeNoteRow(ValueBase):
+    """Claude's prose for one read (spec §8.1): display and Claude's own prompts only."""
+
+    __tablename__ = "value_claude_notes"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    read_id: Mapped[int] = mapped_column(Integer, index=True)
+    symbol: Mapped[str] = mapped_column(String(16), index=True)
+    profile: Mapped[str] = mapped_column(Text, default="")
+    why_cheap: Mapped[str] = mapped_column(Text, default="")
+    thesis: Mapped[str] = mapped_column(Text, default="")
+    bear_case: Mapped[str] = mapped_column(Text, default="")
+    review_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
+    review_why: Mapped[str] = mapped_column(Text, default="")
+    backend: Mapped[str] = mapped_column(String(8))
+    created_at: Mapped[datetime] = mapped_column(DateTime)
+
+
+class ValueKillTriggerRow(ValueBase):
+    """A predicate Claude picked from the menu (spec §8.4); Python bounds its threshold and
+    evaluates it every night (``last_state``: fired | near | far | unknown)."""
+
+    __tablename__ = "value_kill_triggers"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    read_id: Mapped[int] = mapped_column(Integer, index=True)
+    symbol: Mapped[str] = mapped_column(String(16), index=True)
+    kind: Mapped[str] = mapped_column(String(32))
+    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
+    chosen_at: Mapped[datetime] = mapped_column(DateTime)
+    active: Mapped[bool] = mapped_column(Boolean, default=True)
+    last_state: Mapped[str | None] = mapped_column(String(8), nullable=True)
+    last_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
+    last_checked: Mapped[date | None] = mapped_column(Date, nullable=True)
+    fired_on: Mapped[date | None] = mapped_column(Date, nullable=True)
+
+
+class ValueClaudeFactRow(ValueBase):
+    """A fact Claude proposed from a filing (spec §8.2 "Grounded facts") and whether
+    ``src/value/grounding.py`` accepted it. Only a grounded fact is ever read again."""
+
+    __tablename__ = "value_claude_facts"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    read_id: Mapped[int] = mapped_column(Integer, index=True)
+    symbol: Mapped[str] = mapped_column(String(16), index=True)
+    accn: Mapped[str] = mapped_column(String(32))
+    kind: Mapped[str] = mapped_column(String(32))
+    value: Mapped[float | None] = mapped_column(Float, nullable=True)
+    unit: Mapped[str] = mapped_column(String(16), default="")
+    quote: Mapped[str] = mapped_column(Text)
+    item: Mapped[str | None] = mapped_column(String(48), nullable=True)
+    grounded: Mapped[bool] = mapped_column(Boolean)
+    why: Mapped[str] = mapped_column(Text, default="")
+    created_at: Mapped[datetime] = mapped_column(DateTime)
+
+
+class ValueEffectiveRow(ValueBase):
+    """The effective verdict per name and list (spec §6.7), rewritten every night: what the
+    strip shows and Stage 3 acts on. ``decided_by`` is ``claude`` or ``python``."""
+
+    __tablename__ = "value_effective"
+
+    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
+    list_name: Mapped[str] = mapped_column(String(16), primary_key=True)
+    as_of: Mapped[date] = mapped_column(Date)
+    verdict: Mapped[str] = mapped_column(String(16))
+    decided_by: Mapped[str] = mapped_column(String(8))
+    python_verdict: Mapped[str] = mapped_column(String(16))
+    claude_verdict: Mapped[str | None] = mapped_column(String(8), nullable=True)
+    verdict_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)
+    entry_ceiling: Mapped[float | None] = mapped_column(Float, nullable=True)
+    margin_of_safety: Mapped[float | None] = mapped_column(Float, nullable=True)
+    mos_review: Mapped[bool] = mapped_column(Boolean, default=False)
+    updated_at: Mapped[datetime] = mapped_column(DateTime)
+
+
+class ValueClaudeStateRow(ValueBase):
+    """Small key/value state of Claude's side: the breaker (spec §8.2)."""
+
+    __tablename__ = "value_claude_state"
+
+    key: Mapped[str] = mapped_column(String(32), primary_key=True)
+    value: Mapped[str] = mapped_column(Text)
+    updated_at: Mapped[datetime] = mapped_column(DateTime)
+
+
 _engine: Engine | None = None
 _SessionLocal: sessionmaker[Session] | None = None
 
```

- [x] **Step 5: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_effective.py tests/test_value_store.py tests/test_value_fence.py`
  Expected: PASS.

- [x] **Step 6: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the four touched files;
  `.venv/bin/mypy src/value/effective.py src/value/store.py`.

  ```bash
  git add src/value/effective.py src/value/store.py tests/test_value_effective.py tests/test_value_store.py
  git commit -m "feat(value): the effective verdict and Claude's tables in value.db"
  ```

- [x] **Section A exit** — run the full gate from the worktree root (pytest = baseline + 23,
  `ruff check .` clean, `mypy src` clean), the protected-file diff (empty), `py_compile` of
  `scripts/run_value.py` (silent) and `git status --short` (clean); fill the Task 3 row and the
  section-exit numbers in the Progress log, then:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md
  git commit -m "docs(plan): value book Part 4 Progress log - Section A"
  ```

---

## Section B — The analyst, acceptance, the read queue (Tasks 4–6) · model: sonnet · effort: high

The analyst package calls Claude through the slim CLI and returns plain data; the value side
accepts a read (bounding, computing, clamping, storing), recomputes Claude's opinions every night,
writes the effective verdict and runs the breaker; the read queue decides who is read, in what
order, within the day's caps; the value process runs the queue after each night and on every poll;
the operator gets a CLI.

**Spec to read:** §5 (the last paragraph), §8 intro, §8.1, §8.2 ("The Claude breaker", "Paper and
live"), §8.3 ("When Part 2 runs", "Tied to the numbers it saw"), §8.5 (all), §16 (the fence
bullets). Root `CLAUDE.md`: "How Claude is invoked in production" and the spreads fence's
`src/spreads_ai/` bullet (the pattern).

**Files the subagent reads:** `src/claude/cli.py`, `src/spreads_ai/picker.py` and `parse.py` (the
pattern), `src/spreads_ai/context.py` (lines 1–75), `src/news/store/queries.py` (lines 141–165,
347–400), `src/common/dossier_text.py` (lines 140–160), `src/common/config.py` (lines 339–420 and
the `spreads_ai_workdir` method), `src/value/service.py`, `scripts/run_value.py`,
`tests/test_value_fence.py`, `tests/test_eval_skills.py` (lines 110–150), `src/value/store.py`
(Claude's tables, Task 3), `src/value/claude_valuation.py`, `src/value/effective.py`.

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **B1. Section A is in.** `git log --oneline main..HEAD | wc -l` equals Section A's recorded
  count; `git status --short` is clean; the hash check of A4 now prints `be30d1eaa915`.
- [ ] **B2. A green start.** The full gate passes with pytest = baseline + 23; record it.
- [ ] **B3. The code Section B edits is where this plan says** (line numbers after Section A):

  ```bash
  grep -nF '    def spreads_ai_workdir(self) -> Path:' src/common/config.py   # 2506:
  grep -nF '    "src.spreads_ai",' tests/test_eval_skills.py   # 129:
  grep -nF 'def test_value_types_is_plain_pydantic() -> None:' tests/test_value_fence.py   # 132:
  grep -nF '        "ValueReevaluationRow(",' tests/test_value_fence.py   # 199:
  grep -nF 'import src.value.residuals, src.value.reevaluate' tests/test_value_fence.py   # 215:
  grep -nF '        "src/common/value_universe.py",' tests/test_value_fence.py   # 125:
  grep -nF 'from src.value import reevaluate, shadow' src/value/service.py   # 31:
  grep -nF '            stepped = reevaluate.regime_stepped(' src/value/service.py   # 284:
  grep -nF '                "shadow": asdict(record),' src/value/service.py   # 314:
  grep -nF 'from src.value.service import plan_run, run_nightly, startup_check' scripts/run_value.py   # 30:
  grep -nF '_facts = FactsCache()' scripts/run_value.py   # 36:
  grep -nF '            _tick()' scripts/run_value.py   # 86:
  ```

- [ ] **B4. No analyst exists yet, and `claude -p` is never run.** `ls src/value_ai` fails (no such
  directory). The subagent's prompt repeats: every analyst test fakes the runner.

**Section exit:** three task commits plus the section's final `docs(plan)` commit; full gate green
with pytest = baseline + 47 (23 + 11 + 9 + 4); protected-file diff empty; `py_compile` of
`scripts/run_value.py` and `scripts/value_claude.py` silent; `git status --short` clean (in
particular no `data/value_filing_reads.json`: that file does not exist before Task 11).

---

### Task 4: The analyst (`src/value_ai/`) and its fences

**Files:**
- Create: `src/value_ai/__init__.py`, `context.py`, `prompts.py`, `parse.py`, `analyst.py`;
  `tests/test_value_ai.py`
- Modify: `src/common/config.py` (insert before `def spreads_ai_workdir`),
  `tests/test_value_fence.py`, `tests/test_eval_skills.py` (after `"src.spreads_ai",`)

**Interfaces:**
- Consumes: `src.claude.cli` (`run_claude`, `run_ollama`, `should_fall_back`, `OllamaSettings`,
  `CliResult`), `src.news.store.readonly.read_only_session`, `queries.latest_dossier`,
  `piled_clusters_for`, `earnings_between`, `src.common.dossier_text.render_dossier`, Task 2's shapes.
- Produces: `Config.value_ai_workdir()`; `context.gather(symbol, now, max_headlines) ->
  AnalystContext`; `prompts.PROMPT_VERSION = "value-v1"`, `prompts.OUTPUT_SCHEMA`,
  `prompts.build_prompt(req, ctx)`; `parse.parse_reply(text, req) -> AnalystReply | None`;
  `analyst.Analyst(...).read(req, now) -> AnalystResult` (never raises),
  `Analyst.from_config(cfg)`.

- [x] **Step 1: Write the failing tests** — create `tests/test_value_ai.py`:

````python
"""The value analyst (src/value_ai/): prompts, strict parsing, the call (value book spec §8)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from src.claude.cli import CliResult, OllamaSettings
from src.common.value_ai_types import AnalystRequest, DriverBounds, FilingSection, Range
from src.value_ai.analyst import Analyst
from src.value_ai.context import AnalystContext, gather
from src.value_ai.parse import parse_reply
from src.value_ai.prompts import OUTPUT_SCHEMA, build_prompt

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
REQ = AnalystRequest(
    read_id=1,
    symbol="STDY",
    kind="standard",
    reason="top",
    lists=["deep_value", "quality_growth"],
    card_text="STDY · price 30.00",
    bounds=[
        DriverBounds(
            list_name="deep_value",
            method="dcf",
            growth=Range(lo=-0.1, hi=0.197),
            terminal=Range(lo=0.0, hi=0.025),
            discount=Range(lo=0.09, hi=0.12),
            margin=Range(lo=0.106, hi=0.1625),
        )
    ],
    kill_menu={"dilution_above": Range(lo=1.0, hi=10.0), "guidance_cut": None},
    model="claude-sonnet-4-6",
)
GOOD = {
    "lists": [
        {
            "list": "deep_value",
            "verdict": "READY",
            "why": "cheap\nand healthy",
            "drivers": {"growth": 0.08, "terminal": 0.02, "discount": 0.1, "margin": 0.15},
        },
        {"list": "quality_growth", "verdict": "MAYBE", "why": "", "drivers": {}},
        {"list": "made_up", "verdict": "READY", "why": "", "drivers": {}},
    ],
    "profile": "Makes software.",
    "thesis": "Margins hold.",
    "kill_triggers": [
        {"kind": "dilution_above", "threshold": 4},
        {"kind": "dilution_above", "threshold": 9},
        {"kind": "insider_selling_cluster", "threshold": 1},
        {"kind": "guidance_cut", "threshold": None},
    ],
    "facts": [{"kind": "one_off", "value": 5, "accn": "x", "quote": "q"}],
}


def test_a_good_reply_parses_name_by_name() -> None:
    reply = parse_reply("```json\n" + json.dumps(GOOD) + "\n```", REQ)
    assert reply is not None
    assert [(c.list_name, c.verdict) for c in reply.lists] == [("deep_value", "READY")]
    assert reply.lists[0].why == "cheap and healthy"  # one line
    assert reply.lists[0].drivers.margin == 0.15
    assert [(t.kind, t.threshold) for t in reply.kill_triggers] == [
        ("dilution_above", 4.0),
        ("guidance_cut", None),
    ]
    assert reply.facts == []  # facts come from a filing read only


def test_a_malformed_or_verdictless_reply_means_no_notes() -> None:
    assert parse_reply("not json", REQ) is None
    assert parse_reply(json.dumps({"lists": []}), REQ) is None
    bad = {"lists": [{"list": "deep_value", "verdict": "BUY", "drivers": {}}]}
    assert parse_reply(json.dumps(bad), REQ) is None


def test_text_and_bools_are_not_numbers() -> None:
    reply = parse_reply(
        json.dumps(
            {
                "lists": [
                    {
                        "list": "deep_value",
                        "verdict": "WAIT",
                        "why": "",
                        "drivers": {"growth": "8%", "terminal": True, "discount": 0.1},
                    }
                ]
            }
        ),
        REQ,
    )
    assert reply is not None
    d = reply.lists[0].drivers
    assert (d.growth, d.terminal, d.discount, d.margin) == (None, None, 0.1, None)


def test_a_review_needs_a_state_and_a_filing_read_keeps_only_facts() -> None:
    review = REQ.model_copy(update={"kind": "review"})
    assert parse_reply(json.dumps(GOOD), review) is None
    ok = parse_reply(json.dumps({**GOOD, "review_state": "BROKEN", "review_why": "x"}), review)
    assert ok is not None and ok.review_state == "BROKEN"
    filing = REQ.model_copy(update={"kind": "filing"})
    facts = parse_reply(json.dumps(GOOD), filing)
    assert facts is not None and facts.lists == [] and facts.kill_triggers == []
    assert [(f.kind, f.value) for f in facts.facts] == [("one_off", 5.0)]


def test_the_prompt_shows_the_bounds_and_the_menu_and_asks_for_no_price() -> None:
    text = build_prompt(REQ, AnalystContext(headlines=["2026-10-30 · a story · 3 source(s)"]))
    assert "growth -0.100..0.197" in text and "margin 0.106..0.163" in text
    assert "dilution_above: threshold in 1..10" in text and "guidance_cut (no threshold" in text
    assert "a story" in text and "(no dossier for this name)" in text
    fields = set(OUTPUT_SCHEMA["properties"]) | set(
        OUTPUT_SCHEMA["properties"]["lists"]["items"]["properties"]
    )
    assert not fields & {"fair_value", "price", "strike", "size", "limit"}
    filing = REQ.model_copy(
        update={
            "kind": "filing",
            "sections": [FilingSection(accn="a1", form="10-K", section="Item 7", text="MD&A")],
        }
    )
    assert "VERBATIM quote" in build_prompt(filing, AnalystContext())


def _analyst(run, *, ollama: bool = False, only: bool = False) -> tuple[Analyst, list[dict]]:
    calls: list[dict] = []

    async def fake_run(prompt: str, **kwargs) -> CliResult:
        calls.append({"prompt": prompt, **kwargs})
        return run()

    async def fake_ollama(prompt: str, **kwargs) -> CliResult:
        calls.append({"ollama": True, **kwargs})
        return CliResult(json.dumps(GOOD), None, 50)

    settings = OllamaSettings("http://localhost:11434", "qwen3.5:4b", "5m", 0.1, 8192)
    return (
        Analyst(
            cli_command="claude",
            disallowed_tools="Bash",
            workdir=Path("/tmp/value-ai-test"),
            ollama=settings if ollama or only else None,
            ollama_only=only,
            run=fake_run,
            ollama_run=fake_ollama,
            context=lambda symbol, now, n: AnalystContext(),
        ),
        calls,
    )


def test_a_cli_read_is_labelled_cli_and_runs_slim_from_the_workdir() -> None:
    analyst, calls = _analyst(lambda: CliResult(json.dumps(GOOD), None, 900, 0.01))
    out = asyncio.run(analyst.read(REQ, NOW))
    assert out.reply is not None and out.call.backend == "cli" and out.call.error is None
    assert out.call.prompt_version == "value-v1" and out.call.cost_usd == 0.01
    (call,) = calls
    assert call["cwd"] == Path("/tmp/value-ai-test") and call["slim"] is True
    assert call["usage_kind"] == "value_standard" and call["model"] == "claude-sonnet-4-6"


def test_a_failed_cli_falls_back_to_ollama_labelled_and_a_timeout_does_not() -> None:
    analyst, _ = _analyst(lambda: CliResult(None, "cli_error", 100), ollama=True)
    out = asyncio.run(analyst.read(REQ, NOW))
    assert out.reply is not None and out.call.backend == "ollama"
    assert out.call.model == "ollama:qwen3.5:4b"
    slow, calls = _analyst(lambda: CliResult(None, "timeout", 240000), ollama=True)
    out = asyncio.run(slow.read(REQ, NOW))
    assert out.reply is None and out.call.error == "timeout" and len(calls) == 1
    only, calls = _analyst(lambda: CliResult(None, "cli_error", 1), only=True)
    out = asyncio.run(only.read(REQ, NOW))
    assert out.call.backend == "ollama" and all(c.get("ollama") for c in calls)


def test_an_unreadable_reply_is_no_notes_with_the_error_named() -> None:
    analyst, _ = _analyst(lambda: CliResult("I think it is cheap.", None, 10))
    out = asyncio.run(analyst.read(REQ, NOW))
    assert out.reply is None and out.call.error == "unparseable"
    assert out.call.raw == "I think it is cheap."


def test_context_without_news_db_says_so(monkeypatch, tmp_path) -> None:
    import src.news.store.readonly as ro

    monkeypatch.setattr(ro, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    ro.reset_engine()
    assert gather("STDY", NOW, 5).unavailable == ["news"]
    ro.reset_engine()
````

  …and apply to the two fence tests:

```diff
diff --git a/tests/test_eval_skills.py b/tests/test_eval_skills.py
index ba22d26..441e939 100644
--- a/tests/test_eval_skills.py
+++ b/tests/test_eval_skills.py
@@ -127,6 +127,8 @@ _ENRICHMENT_ONLY = (
     "src.news",
     # Claude picks the daily spread (2026-10-12 spec §5.4)
     "src.spreads_ai",
+    # Claude as the value book's analyst (2026-10-28 value book spec §8)
+    "src.value_ai",
 )
 
 
diff --git a/tests/test_value_fence.py b/tests/test_value_fence.py
index cd9faa1..7309a72 100644
--- a/tests/test_value_fence.py
+++ b/tests/test_value_fence.py
@@ -34,6 +34,8 @@ PURE = (
     "report",
     "residuals",
     "reevaluate",
+    "claude_valuation",
+    "effective",
 )
 
 FORBIDDEN_FOR_VALUE = (
@@ -123,6 +125,7 @@ def test_the_input_loader_imports_no_enrichment_and_no_value_code() -> None:
         "src/common/value_inputs.py",
         "src/common/value_types.py",
         "src/common/value_universe.py",
+        "src/common/value_ai_types.py",
     ):
         mods = imported_modules(ROOT / rel)
         bad = [m for m in (*ENRICHMENT, "src.value") if _reaches(mods, m)]
@@ -130,8 +133,9 @@ def test_the_input_loader_imports_no_enrichment_and_no_value_code() -> None:
 
 
 def test_value_types_is_plain_pydantic() -> None:
-    mods = imported_modules(ROOT / "src" / "common" / "value_types.py")
-    assert {m.split(".")[0] for m in mods} <= {"__future__", "datetime", "typing", "pydantic"}
+    for name in ("value_types.py", "value_ai_types.py"):
+        mods = imported_modules(ROOT / "src" / "common" / name)
+        assert {m.split(".")[0] for m in mods} <= {"__future__", "datetime", "typing", "pydantic"}
 
 
 def test_value_opens_no_sec_client() -> None:
@@ -197,6 +201,13 @@ def test_only_src_value_constructs_value_rows() -> None:
         "ValueShadowEventRow(",
         "ValueRankedRow(",
         "ValueReevaluationRow(",
+        "ValueClaudeReadRow(",
+        "ValueClaudeVerdictRow(",
+        "ValueClaudeNoteRow(",
+        "ValueKillTriggerRow(",
+        "ValueClaudeFactRow(",
+        "ValueEffectiveRow(",
+        "ValueClaudeStateRow(",
     )
     offenders = []
     for p in [*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")]:
@@ -213,6 +224,7 @@ def test_the_value_scorecard_loads_no_wheel_layer_even_transitively() -> None:
         "import src.value.scorecard, src.value.store, src.value.ticker_file, src.value.funnel\n"
         "import src.value.exits, src.value.shadow, src.value.service, src.value.report\n"
         "import src.value.residuals, src.value.reevaluate\n"
+        "import src.value.claude_valuation, src.value.effective\n"
         "import src.common.value_inputs, src.common.value_universe\n"
         "print(json.dumps(sorted(m for m in sys.modules if m.startswith('src.'))))\n"
     )
@@ -303,3 +315,65 @@ def test_the_research_worker_owns_the_filings_feed() -> None:
         if "FilingIndexRow" in p.read_text(encoding="utf-8")
     ]
     assert readers == []  # only src/common/value_inputs.py names the table
+
+
+VALUE_AI = sorted((ROOT / "src" / "value_ai").rglob("*.py"))
+FORBIDDEN_FOR_VALUE_AI = (
+    "src.value",
+    "src.engine",
+    "src.execution",
+    "src.strategies",
+    "src.orchestrator",
+    "src.monitor",
+    "src.notify",
+    "src.ledger",
+    "src.storage",
+    "src.spreads",
+    "src.spreads_ai",
+    "src.api",
+    "src.reporting",
+    "src.research",
+)
+
+
+def test_value_ai_reaches_claude_only_through_the_cli_and_never_the_value_book() -> None:
+    """Spec §8, §16: src/value_ai/ imports nothing from src.value, the trading path, notify,
+    the ledger or the storage layer; from src.claude only the slim ``src.claude.cli``; it reads
+    news.db only through the read-only engine and the Session-parameterised queries."""
+    assert len(VALUE_AI) >= 5
+    offenders = []
+    for p in VALUE_AI:
+        mods = imported_modules(p)
+        offenders += [f"{p.name} -> {m}" for m in FORBIDDEN_FOR_VALUE_AI if _reaches(mods, m)]
+        offenders += [
+            f"{p.name} -> {m}"
+            for m in mods
+            if _reaches({m}, "src.claude") and not _reaches({m}, "src.claude.cli")
+        ]
+        offenders += [
+            f"{p.name} -> {m}"
+            for m in mods
+            if _reaches({m}, "src.news")
+            and not _reaches({m}, "src.news.store.readonly")
+            and not _reaches({m}, "src.news.store.queries")
+        ]
+    assert offenders == []
+
+
+def test_the_analyst_loads_no_wheel_layer_and_no_value_code() -> None:
+    """Importing the analyst (what scripts/run_value.py does) loads src.claude.cli alone from the
+    reasoning layer: no runner, prompt stack or memory, no src.value, no IBKR client, and never
+    news.db's read-write engine."""
+    probe = (
+        "import json, sys\nimport src.value_ai.analyst\nprint(json.dumps(sorted(sys.modules)))\n"
+    )
+    env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
+    out = subprocess.run(
+        [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True
+    )
+    loaded = set(json.loads(out.stdout.strip().splitlines()[-1]))
+    claude = sorted(m for m in loaded if m.startswith("src.claude."))
+    assert claude == ["src.claude.cli"]
+    bad = [m for m in FORBIDDEN_FOR_VALUE_AI if _reaches(loaded, m)]
+    assert bad == [] and not _reaches(loaded, "ib_async")
+    assert not _reaches(loaded, "src.news.store.session")
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_ai.py tests/test_value_fence.py tests/test_eval_skills.py`
  Expected: FAIL — `ModuleNotFoundError: No module named 'src.value_ai'` (collection error) and the
  two new fence tests (`assert len(VALUE_AI) >= 5`, the probe's import).

- [x] **Step 3: The workdir helper** — apply:

```diff
diff --git a/src/common/config.py b/src/common/config.py
index 2ca14f3..22f26df 100644
--- a/src/common/config.py
+++ b/src/common/config.py
@@ -2503,6 +2503,10 @@ class Config(BaseModel):
         """Where headless ``claude -p`` calls run: ``~`` expanded, outside the repo (validated)."""
         return Path(self.claude.workdir).expanduser()
 
+    def value_ai_workdir(self) -> Path:
+        """Where the value analyst's headless calls run: outside the repo (validated)."""
+        return Path(self.value.claude.workdir).expanduser()
+
     def spreads_ai_workdir(self) -> Path:
         """``~`` is expanded and an absolute path used as-is; a relative path still resolves under
         ROOT (keeps old configs working, but it puts the repo's CLAUDE.md in the picker's context)."""
```

- [x] **Step 4: The package** — create each file whole:

  `src/value_ai/__init__.py`:

```python
"""Claude as the value book's analyst (docs/superpowers/specs/2026-10-28-value-swing-book-design.md §8).

Enrichment only. It gathers news context, prompts ``claude -p`` through ``src.claude.cli`` (slim,
from a workdir outside the repo) and returns plain data: a verdict and valuation drivers per
list, prose, kill-trigger picks, a review state and proposed facts. It never imports
``src.value``, the trading path, ``src.notify``, ``src.ledger`` or ``src.storage``, and it writes
nothing: ``src/value/`` bounds, computes, clamps, verifies and stores every number.
``scripts/run_value.py`` is the only module that imports this package (tests/test_value_fence.py).
"""
```

  `src/value_ai/context.py`:

```python
"""What Claude reads beside the scorecard (spec §8.3): the name's dossier when one exists, the
news clusters the news process filed in pile 1 or 2, and its earnings dates, from news.db through
the read-only engine. Synchronous (SQLite); never raises: a missing source is named in
``unavailable`` so the prompt says what is missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from src.common.config import get_config
from src.common.dossier_text import render_dossier
from src.news.store.queries import earnings_between, latest_dossier, piled_clusters_for
from src.news.store.readonly import read_only_session

log = logging.getLogger(__name__)
NEWS_DAYS = 30
EARNINGS_BACK_DAYS = 120
EARNINGS_AHEAD_DAYS = 90


@dataclass(slots=True)
class AnalystContext:
    dossier: str = ""
    headlines: list[str] = field(default_factory=list)
    earnings: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)


def _clean(text: str, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def gather(symbol: str, now: datetime, max_headlines: int) -> AnalystContext:
    out = AnalystContext()
    try:
        with read_only_session() as s:
            if s is None:
                out.unavailable.append("news")
                return out
            dossier = latest_dossier(s, symbol)
            if dossier is not None:
                out.dossier = render_dossier(
                    dossier,
                    symbol=symbol,
                    now=now,
                    staleness_hours=get_config().news.dossier.staleness_hours,
                    compact=False,
                )
            for c in piled_clusters_for(s, symbol, now - timedelta(days=NEWS_DAYS))[:max_headlines]:
                out.headlines.append(
                    f"{_aware(c.last_seen):%Y-%m-%d} · {_clean(c.headline, 200)} · "
                    f"{c.source_count} source(s)"
                )
            today = now.date()
            for e in earnings_between(
                s,
                today - timedelta(days=EARNINGS_BACK_DAYS),
                today + timedelta(days=EARNINGS_AHEAD_DAYS),
                {symbol.upper()},
            ):
                surprise = (
                    f" · EPS {e.eps_actual} vs {e.eps_est} est"
                    if e.eps_actual is not None and e.eps_est is not None
                    else ""
                )
                out.earnings.append(f"{e.report_date} ({e.status}){surprise}")
    except Exception as exc:  # noqa: BLE001 - enrichment degrades, never raises
        log.warning("value_ai: news read failed for %s: %s", symbol, exc)
        out.unavailable.append("news")
    return out
```

  `src/value_ai/prompts.py`:

```python
"""The versioned prompts of the value book's analyst (spec §8.1, §8.5) and the one output schema
they share with the interactive skill (``.claude/skills/value/reference/output-schema.json`` is
generated from :data:`OUTPUT_SCHEMA`, spec §8.6, and a test keeps the two equal).

Three call kinds, one shape: a ``standard`` read writes the verdict per list, the drivers, the
prose and the kill-trigger picks; a ``review`` (a held name's re-evaluation, spec §7.1 step 3)
adds the review state; a ``filing`` read proposes grounded facts from the sliced sections only.
Claude never returns a fair value, a price, a strike or a size: the schema has no field for one.
"""

from __future__ import annotations

import json
from typing import Any

from src.common.value_ai_types import FACT_KINDS, KILL_KINDS, AnalystRequest
from src.value_ai.context import AnalystContext

PROMPT_VERSION = "value-v1"

_DRIVERS = {
    "type": "object",
    "properties": {
        "growth": {"type": ["number", "null"]},
        "terminal": {"type": ["number", "null"]},
        "discount": {"type": ["number", "null"]},
        "margin": {"type": ["number", "null"]},
        "rote": {"type": ["number", "null"]},
    },
}
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lists": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "list": {"type": "string", "enum": ["deep_value", "quality_growth"]},
                    "verdict": {"type": "string", "enum": ["READY", "WATCH", "WAIT", "NO"]},
                    "why": {"type": "string"},
                    "drivers": _DRIVERS,
                },
                "required": ["list", "verdict", "why", "drivers"],
            },
        },
        "profile": {"type": "string"},
        "why_cheap": {"type": "string"},
        "thesis": {"type": "string"},
        "bear_case": {"type": "string"},
        "kill_triggers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(KILL_KINDS)},
                    "threshold": {"type": ["number", "null"]},
                },
                "required": ["kind"],
            },
        },
        "review_state": {
            "type": ["string", "null"],
            "enum": ["INTACT", "WEAKENED", "BROKEN", None],
        },
        "review_why": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(FACT_KINDS)},
                    "value": {"type": ["number", "null"]},
                    "unit": {"type": "string"},
                    "accn": {"type": "string"},
                    "quote": {"type": "string"},
                    "item": {"type": ["string", "null"]},
                },
                "required": ["kind", "accn", "quote"],
            },
        },
    },
    "required": ["lists"],
}

_RULES = """You are the analyst of a long-only value book. You judge healthy companies only:
Python has already checked health, earnings quality and dilution, and those checks are final.
Use only the numbers and text below. Do not invent figures. Every number you write in prose must
appear below. You never set a price, a fair value, a strike or a size: you choose assumptions
inside the bounds given, and Python does all the arithmetic and caps the result.
Return ONE JSON object and nothing else."""

_VERDICTS = """Verdicts, per list the name is on:
- READY: buy now (Python still applies the margin of safety and timing on top).
- WATCH: the right company; wait for the price to settle.
- WAIT: the right company at the wrong price.
- NO: not a company to own on this list."""

_DRIVER_HELP = """Drivers (fractions: 0.08 means 8%), one set per list, each inside its bound:
- growth: FCF per share growth for years 1-5 (years 6-10 fade to terminal);
- terminal: terminal growth; discount: the discount rate;
- margin: the normalised free-cash-flow margin on revenue;
- rote (banks and insurers, instead of growth and margin): sustainable return on tangible equity.
A driver outside its bound is clamped and the clamp is recorded against you."""


def _bounds(req: AnalystRequest) -> str:
    lines = []
    for b in req.bounds:
        parts = [f"terminal {b.terminal.lo:.3f}..{b.terminal.hi:.3f}"]
        parts.append(f"discount {b.discount.lo:.3f}..{b.discount.hi:.3f}")
        if b.growth is not None:
            parts.append(f"growth {b.growth.lo:.3f}..{b.growth.hi:.3f}")
        if b.margin is not None:
            parts.append(f"margin {b.margin.lo:.3f}..{b.margin.hi:.3f}")
        if b.rote is not None:
            parts.append(f"rote {b.rote.lo:.3f}..{b.rote.hi:.3f}")
        lines.append(f"- {b.list_name} ({b.method}): " + ", ".join(parts))
    return "\n".join(lines) or "(none: give a verdict only)"


def _menu(req: AnalystRequest) -> str:
    lines = []
    for kind, bound in req.kill_menu.items():
        if bound is None:
            lines.append(f"- {kind} (no threshold: fires on a grounded filing fact)")
        else:
            lines.append(f"- {kind}: threshold in {bound.lo:g}..{bound.hi:g}")
    return "\n".join(lines)


def _context(ctx: AnalystContext) -> str:
    parts = [ctx.dossier or "(no dossier for this name)"]
    parts.append("Recent stories (pile 1-2):")
    parts += [f"- {h}" for h in ctx.headlines] or ["- (none)"]
    parts.append("Earnings dates:")
    parts += [f"- {e}" for e in ctx.earnings] or ["- (none known)"]
    if ctx.unavailable:
        parts.append("Unavailable: " + ", ".join(ctx.unavailable))
    return "\n".join(parts)


def _shape(req: AnalystRequest) -> dict[str, Any]:
    lists = [
        {
            "list": name,
            "verdict": "READY|WATCH|WAIT|NO",
            "why": "one line",
            "drivers": {"growth": 0.0, "terminal": 0.0, "discount": 0.0, "margin": 0.0},
        }
        for name in req.lists
    ]
    shape: dict[str, Any] = {
        "lists": lists,
        "profile": "what the business is and what moves it, two sentences",
        "why_cheap": "one paragraph citing the numbers above",
        "thesis": "what has to be true for the price to reach fair value",
        "bear_case": "the strongest case against, in a short seller's voice",
        "kill_triggers": [{"kind": "one of the menu", "threshold": 0.0}],
    }
    if req.kind == "review":
        shape["review_state"] = "INTACT|WEAKENED|BROKEN"
        shape["review_why"] = "one line"
    return shape


def build_prompt(req: AnalystRequest, ctx: AnalystContext) -> str:
    """The prompt for one read. A filing read asks for facts only."""
    if req.kind == "filing":
        sections = "\n\n".join(
            f"--- {s.form} {s.accn} · {s.section} ---\n{s.text}" for s in req.sections
        )
        return "\n\n".join(
            [
                _RULES,
                "Task: extract facts from the filing sections below. Each fact needs the "
                "accession number and a VERBATIM quote (copied exactly, 300 characters at most) "
                "that contains its number. Python checks every quote against the filing and "
                "drops any that does not match. Kinds: " + ", ".join(FACT_KINDS) + ". "
                "Use guidance_cut or customer_loss (value null) only when the text says so "
                "plainly. Give lists as [].",
                f"=== {req.symbol}: SCORECARD ===\n{req.card_text}",
                f"=== FILING SECTIONS ===\n{sections or '(none)'}",
                'Reply shape: {"lists": [], "facts": [{"kind": "...", "value": 0.0, "unit": '
                '"USD|pct|count", "accn": "...", "quote": "...", "item": null}]}',
            ]
        )
    blocks = [
        _RULES,
        _VERDICTS,
        _DRIVER_HELP,
        f"=== {req.symbol}: SCORECARD (Python's numbers) ===\n{req.card_text}",
        f"=== DRIVER BOUNDS ===\n{_bounds(req)}",
        f"=== KILL-TRIGGER MENU (pick up to {req.max_kill_triggers}) ===\n{_menu(req)}",
        f"=== WHAT THE NEWS SAYS ===\n{_context(ctx)}",
    ]
    if req.kind == "review":
        blocks.append(
            "=== RE-EVALUATION (Python decided to re-evaluate; you judge the thesis) ===\n"
            f"{req.trigger_text}\nState INTACT, WEAKENED or BROKEN. A headline alone changes "
            "nothing about what the company is worth."
        )
    blocks.append("Reply shape:\n" + json.dumps(_shape(req), indent=1))
    return "\n\n".join(blocks)
```

  `src/value_ai/parse.py`:

````python
"""Strict parsing of the analyst's replies (spec §8.1: "validated name by name; a malformed or
missing reply means no notes, never a guess"). Shape only: whether a driver is inside its bound,
whether a fact is grounded, whether a verdict may apply, is ``src/value/``'s check.
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.common.value_ai_types import (
    FACT_KINDS,
    KILL_KINDS,
    AnalystReply,
    AnalystRequest,
    Drivers,
    KillTrigger,
    ListCall,
    ProposedFact,
)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_VERDICTS = ("READY", "WATCH", "WAIT", "NO")
_STATES = ("INTACT", "WEAKENED", "BROKEN")


def clean(text: object, limit: int = 1200) -> str:
    """One line, bounded: model text never carries newlines into a card or a prompt."""
    return " ".join(str(text).split())[:limit] if isinstance(text, str) else ""


def extract_json(text: str) -> dict[str, Any] | None:
    t = _FENCE.sub("", (text or "").strip())
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _number(v: object) -> float | None:
    """A plain number: not a bool, not text, not NaN."""
    if isinstance(v, bool) or not isinstance(v, int | float) or v != v:
        return None
    return float(v)


def _drivers(raw: object) -> Drivers:
    d = raw if isinstance(raw, dict) else {}
    return Drivers(**{k: _number(d.get(k)) for k in Drivers.model_fields})


def _lists(raw: object, wanted: list[str]) -> list[ListCall]:
    out: list[ListCall] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name, verdict = item.get("list"), item.get("verdict")
        if name not in wanted or name in seen or verdict not in _VERDICTS:
            continue
        seen.add(name)
        out.append(
            ListCall(
                list_name=name,
                verdict=verdict,
                why=clean(item.get("why"), 300),
                drivers=_drivers(item.get("drivers")),
            )
        )
    return out


def _triggers(raw: object, limit: int) -> list[KillTrigger]:
    out: list[KillTrigger] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("kind") not in KILL_KINDS:
            continue
        if item["kind"] in seen:
            continue
        seen.add(item["kind"])
        out.append(KillTrigger(kind=item["kind"], threshold=_number(item.get("threshold"))))
    return out[:limit]


def _facts(raw: object) -> list[ProposedFact]:
    out: list[ProposedFact] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or item.get("kind") not in FACT_KINDS:
            continue
        accn, quote = item.get("accn"), item.get("quote")
        if not isinstance(accn, str) or not isinstance(quote, str) or not quote.strip():
            continue
        item_name = item.get("item")
        out.append(
            ProposedFact(
                kind=item["kind"],
                value=_number(item.get("value")),
                unit=clean(item.get("unit"), 16),
                accn=accn.strip(),
                quote=quote.strip()[:300],
                item=item_name if isinstance(item_name, str) and item_name else None,
            )
        )
    return out


def parse_reply(text: str | None, req: AnalystRequest) -> AnalystReply | None:
    """The reply as plain data, or None when it is unusable for its kind: a standard read with no
    valid verdict, a review with no valid state, anything that is not a JSON object."""
    obj = extract_json(text or "")
    if obj is None:
        return None
    lists = _lists(obj.get("lists"), req.lists)
    state = obj.get("review_state")
    reply = AnalystReply(
        lists=lists if req.kind != "filing" else [],
        profile=clean(obj.get("profile"), 600),
        why_cheap=clean(obj.get("why_cheap")),
        thesis=clean(obj.get("thesis")),
        bear_case=clean(obj.get("bear_case")),
        kill_triggers=_triggers(obj.get("kill_triggers"), req.max_kill_triggers)
        if req.kind != "filing"
        else [],
        review_state=state if req.kind == "review" and state in _STATES else None,
        review_why=clean(obj.get("review_why"), 300) if req.kind == "review" else "",
        facts=_facts(obj.get("facts")) if req.kind == "filing" else [],
    )
    if req.kind == "standard" and not reply.lists:
        return None
    if req.kind == "review" and reply.review_state is None:
        return None
    return reply
````

  `src/value_ai/analyst.py`:

```python
"""The value book's analyst: one ``claude -p`` read per request (spec §8.1, §8.5).

Never raises: a CLI failure, an unreadable reply or a crashing context source comes back as an
``AnalystResult`` with no reply and the error named. With ``value.claude.ollama_fallback`` on, a
failed CLI call (anything but a timeout) is answered by the local Ollama model instead; that
reply is labelled ``backend="ollama"`` and ``src/value/`` never lets it decide anything (spec
§8.5, the ``claude_cut`` rule). When ``claude.backend`` is ``ollama`` every read is Ollama's.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from src.claude.cli import CliResult, OllamaSettings, run_claude, run_ollama, should_fall_back
from src.common.config import Config
from src.common.value_ai_types import AnalystCall, AnalystRequest, AnalystResult
from src.value_ai.context import AnalystContext, gather
from src.value_ai.parse import parse_reply
from src.value_ai.prompts import OUTPUT_SCHEMA, PROMPT_VERSION, build_prompt

log = logging.getLogger(__name__)

Runner = Callable[..., Awaitable[CliResult]]
Gatherer = Callable[[str, datetime, int], AnalystContext]


class Analyst:
    def __init__(
        self,
        *,
        cli_command: str,
        disallowed_tools: str,
        workdir: Path,
        slim: bool = True,
        max_headlines: int = 12,
        ollama: OllamaSettings | None = None,
        ollama_only: bool = False,
        run: Runner = run_claude,
        ollama_run: Runner = run_ollama,
        context: Gatherer = gather,
    ) -> None:
        self.cli_command = cli_command
        self.disallowed_tools = disallowed_tools
        self.workdir = workdir
        self.slim = slim
        self.max_headlines = max_headlines
        self.ollama = ollama
        self.ollama_only = ollama_only and ollama is not None
        self._run = run
        self._ollama_run = ollama_run
        self._context = context

    @classmethod
    def from_config(cls, cfg: Config) -> Analyst:
        c, v = cfg.claude, cfg.value.claude
        only = c.backend == "ollama"
        ollama = (
            OllamaSettings(
                c.ollama_host,
                c.ollama_model,
                c.ollama_keep_alive,
                c.ollama_temperature,
                c.ollama_num_ctx,
            )
            if v.ollama_fallback or only
            else None
        )
        return cls(
            cli_command=c.cli_command,
            disallowed_tools=c.disallowed_tools,
            workdir=cfg.value_ai_workdir(),
            slim=c.slim_context,
            max_headlines=v.max_headlines,
            ollama=ollama,
            ollama_only=only,
        )

    async def read(self, req: AnalystRequest, now: datetime) -> AnalystResult:
        prompt = ""
        try:
            ctx = await asyncio.to_thread(self._context, req.symbol, now, self.max_headlines)
            prompt = build_prompt(req, ctx)
            if self.ollama_only:
                res = CliResult(None, "disabled", 0)
            else:
                res = await self._run(
                    prompt,
                    cli_command=self.cli_command,
                    model=req.model,
                    effort=req.effort,
                    timeout_seconds=req.timeout_seconds,
                    cwd=self.workdir,
                    disallowed_tools=self.disallowed_tools,
                    slim=self.slim,
                    usage_kind=f"value_{req.kind}",
                )
            backend, model = "cli", req.model
            if self.ollama is not None and (self.ollama_only or should_fall_back(res.error)):
                log.warning("value_ai: %s answered by ollama (%s)", req.symbol, res.error)
                alt = await self._ollama_run(
                    prompt,
                    settings=self.ollama,
                    schema=OUTPUT_SCHEMA,
                    timeout_seconds=req.timeout_seconds,
                )
                res = CliResult(
                    alt.text, alt.error, res.latency_ms + alt.latency_ms, res.cost_usd, alt.raw
                )
                backend, model = "ollama", f"ollama:{self.ollama.model}"
            reply = parse_reply(res.text, req) if res.text is not None else None
            error = res.error or (None if reply is not None else "unparseable")
            return AnalystResult(
                read_id=req.read_id,
                reply=reply,
                call=AnalystCall(
                    model=model,
                    backend=backend,  # type: ignore[arg-type]  # "cli" | "ollama"
                    latency_ms=res.latency_ms,
                    cost_usd=res.cost_usd,
                    error=error,
                    prompt_version=PROMPT_VERSION,
                    prompt=prompt,
                    raw=(res.text if res.text is not None else res.raw)[:20000],
                ),
            )
        except Exception:  # noqa: BLE001 - the analyst never takes the value process down
            log.exception("value_ai: read of %s failed", req.symbol)
            return AnalystResult(
                read_id=req.read_id,
                call=AnalystCall(
                    model=req.model,
                    error="analyst_error",
                    prompt_version=PROMPT_VERSION,
                    prompt=prompt,
                ),
            )
```

- [x] **Step 5: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_ai.py tests/test_value_fence.py tests/test_eval_skills.py tests/test_spreads_fence.py tests/test_news_fence.py tests/test_value_config.py`
  Expected: PASS.

- [x] **Step 6: Gates and commit**

  Run: `.venv/bin/ruff check src/value_ai src/common/config.py tests/test_value_ai.py tests/test_value_fence.py tests/test_eval_skills.py`,
  the same paths with `.venv/bin/ruff format --check`, and `.venv/bin/mypy src/value_ai src/common/config.py`.

  ```bash
  git add src/value_ai src/common/config.py tests/test_value_ai.py tests/test_value_fence.py tests/test_eval_skills.py
  git commit -m "feat(value_ai): Claude as the value book's analyst, through the slim CLI (spec 8)"
  ```

---

### Task 5: Accepting a read — verdicts, opinions, the effective verdict, the breaker

**Files:**
- Create: `src/value/claude_verdicts.py`, `tests/test_value_claude.py`

**Interfaces:**
- Consumes: `claude_valuation.claude_fair_value`, `effective.effective`, Task 3's tables, Task 2's
  `AnalystResult`.
- Produces: `accept(vs, read, result, card, cfg, *, now) -> Accepted`; `bounded_trigger`;
  `opinions(vs, cards, rules) -> dict[(symbol, list), (ClaudeOpinion, ClaudeValue)]`;
  `breaker_state`, `set_breaker`, `reset_breaker`, `applies(vs, cfg, *, is_live)`;
  `night_counts(cards, tags, ops, review_above_pct) -> {ready, baseline_ready, values, clamped}`;
  `check_breaker(vs, cfg, tonight, now) -> bool`; `persist_effective(vs, cards, ops, *, applied,
  as_of, now, review_above_pct) -> dict[(symbol, list), Effective]`.

The breaker test's numbers: three earlier nights of 2 Claude READYs against 1 baseline READY each,
plus tonight: with 2 more (8 against 3) it holds (8 is not above 9); with 4 more (10 against 3) it
trips. The clamp rate: three earlier nights of 2 values and none clamped plus tonight's 3 clamped of
3 is 3 of 9 values (33% > 25%, at least 8 values).

- [x] **Step 1: Write the failing tests** — create `tests/test_value_claude.py`:

```python
"""Claude's reads on the value side: acceptance, opinions, the effective verdict, the breaker and
the queue (value book spec §6.7, §8.2, §8.3, §8.5)."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from sqlalchemy import select

import src.value.store as store
from src.common.config import get_config
from src.common.value_ai_types import (
    AnalystCall,
    AnalystReply,
    AnalystResult,
    Drivers,
    KillTrigger,
    ListCall,
)
from src.value import claude_verdicts as cv
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueClaudeNoteRow,
    ValueClaudeReadRow,
    ValueClaudeVerdictRow,
    ValueEffectiveRow,
    ValueKillTriggerRow,
    ValueReevaluationRow,
    ValueRunRow,
    init_value_db,
    value_session,
)
from tests.value_fixtures import financials, inputs

CFG = get_config().value
NOW = datetime(2026, 11, 2, 15, 0)  # naive UTC, 10:00 ET
CHEAP = build_scorecard(inputs(close=30.0), CFG)  # deep: Python FV 46.85, READY
DEAR = build_scorecard(inputs(close=40.0), CFG)  # deep: Python WAIT
GOOD_DRIVERS = Drivers(growth=0.08, terminal=0.02, discount=0.10, margin=0.15)


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def _result(read_id: int, *, verdict="READY", drivers=GOOD_DRIVERS, backend="cli", **reply):
    return AnalystResult(
        read_id=read_id,
        reply=AnalystReply(
            lists=[ListCall(list_name="deep_value", verdict=verdict, why="w", drivers=drivers)],
            profile="p",
            **reply,
        ),
        call=AnalystCall(model="sonnet", backend=backend, latency_ms=5, prompt="P", raw="R"),
    )


def _accept(card, result, *, kind="standard", reevaluation_id=None):
    with value_session() as s:
        read = ValueClaudeReadRow(
            symbol=card.symbol,
            kind=kind,
            reason="request",
            priority=0,
            requested_at=NOW,
            reevaluation_id=reevaluation_id,
        )
        s.add(read)
        s.flush()
        return cv.accept(
            s, read, result.model_copy(update={"read_id": read.id}), card, CFG, now=NOW
        )


def _verdicts():
    with value_session() as s:
        return list(s.scalars(select(ValueClaudeVerdictRow).order_by(ValueClaudeVerdictRow.id)))


def test_a_read_stores_the_bounded_drivers_and_pythons_capped_value(value_db) -> None:
    wild = Drivers(growth=0.40, terminal=0.03, discount=0.07, margin=0.30)
    out = _accept(CHEAP, _result(0, drivers=wild))
    assert out.verdicts == 1
    (v,) = _verdicts()
    assert v.verdict == "READY" and v.backend == "cli" and v.superseded is False
    assert v.fair_value == pytest.approx(1.5 * 46.853626592284414) and v.clamp_bound is True
    assert v.uncapped == pytest.approx(106.19430864505932)
    assert len(json.loads(v.clamps_json)) == 4  # every driver out of bounds, recorded
    assert v.accn == "0000000001-26-000001"
    with value_session() as s:
        read = s.scalars(select(ValueClaudeReadRow)).one()
        assert (read.status, read.model, read.prompt, read.raw) == ("done", "sonnet", "P", "R")
        assert s.scalars(select(ValueClaudeNoteRow)).one().profile == "p"


def test_a_malformed_reply_stores_the_call_and_nothing_else(value_db) -> None:
    result = AnalystResult(read_id=0, call=AnalystCall(error="unparseable", raw="?"))
    _accept(CHEAP, result)
    assert _verdicts() == []
    with value_session() as s:
        assert s.scalars(select(ValueClaudeReadRow)).one().status == "failed"
        assert s.scalars(select(ValueClaudeNoteRow)).all() == []


def test_between_filings_a_reread_can_lower_but_never_raise(value_db) -> None:
    _accept(
        CHEAP, _result(0, drivers=Drivers(growth=0.05, terminal=0.02, discount=0.10, margin=0.14))
    )
    low = _verdicts()[0].fair_value
    out = _accept(
        CHEAP, _result(0, drivers=Drivers(growth=0.12, terminal=0.025, discount=0.09, margin=0.16))
    )
    assert out.kept_earlier == 1
    first, second = _verdicts()
    assert first.superseded is True and second.fair_value == pytest.approx(low)
    assert "raised between filings" in second.clamps_json
    # a new 10-Q (a new accession) lets the drivers move either way
    filed = build_scorecard(inputs(close=30.0, fin=financials(accn="0000000001-26-000002")), CFG)
    _accept(
        filed, _result(0, drivers=Drivers(growth=0.12, terminal=0.025, discount=0.09, margin=0.16))
    )
    assert _verdicts()[-1].fair_value > low


def test_an_ollama_reply_is_stored_labelled_and_is_never_an_opinion(value_db) -> None:
    _accept(CHEAP, _result(0, backend="ollama"))
    (v,) = _verdicts()
    assert v.backend == "ollama"
    with value_session() as s:
        assert cv.opinions(s, [CHEAP], CFG.rules) == {}


def test_kill_triggers_are_bounded_and_replace_the_old_set(value_db) -> None:
    triggers = [
        KillTrigger(kind="dilution_above", threshold=25.0),  # bounded to 10
        KillTrigger(kind="net_debt_to_ebitda_above", threshold=None),  # no threshold: dropped
        KillTrigger(kind="guidance_cut"),
    ]
    _accept(CHEAP, _result(0, kill_triggers=triggers))
    _accept(CHEAP, _result(0, kill_triggers=[KillTrigger(kind="fcf_ttm_negative")]))
    with value_session() as s:
        rows = s.scalars(select(ValueKillTriggerRow).order_by(ValueKillTriggerRow.id)).all()
        assert [(r.kind, r.threshold, r.active) for r in rows] == [
            ("dilution_above", 10.0, False),
            ("guidance_cut", None, False),
            ("fcf_ttm_negative", None, True),
        ]


def test_a_review_writes_its_state_on_the_reevaluation(value_db) -> None:
    with value_session() as s:
        r = ValueReevaluationRow(
            shadow_id=1,
            symbol="STDY",
            list_name="deep_value",
            session=date(2026, 10, 30),
            last_session=date(2026, 10, 30),
            severity="major",
            triggers_json="[]",
            plan_before_json="{}",
            plan_after_json="{}",
            verdict_at_entry="READY",
            ruleset_version="v4",
            ruleset_hash="x",
            created_at=NOW,
        )
        s.add(r)
        s.flush()
        rid = r.id
    out = _accept(
        CHEAP,
        _result(0, review_state="BROKEN", review_why="lost a customer"),
        kind="review",
        reevaluation_id=rid,
    )
    assert out.review_state == "BROKEN"
    with value_session() as s:
        assert s.get(ValueReevaluationRow, rid).review_state == "BROKEN"


def test_opinions_recompute_on_tonights_card_and_the_effective_verdict_is_written(value_db) -> None:
    _accept(
        DEAR, _result(0, drivers=Drivers(growth=0.12, terminal=0.025, discount=0.09, margin=0.16))
    )
    with value_session() as s:
        ops = cv.opinions(s, [DEAR], CFG.rules)
        opinion, value = ops[("STDY", "deep_value")]
        # 16% x $16 of revenue a share, 12% for five years: 68.72, under the 70.28 cap
        assert opinion.fair_value == value.fair_value == pytest.approx(68.71811198864627)
        eff = cv.persist_effective(
            s, [DEAR], ops, applied=True, as_of=DEAR.as_of, now=NOW, review_above_pct=60.0
        )
        assert eff[("STDY", "deep_value")].verdict == "READY"  # Claude lifts Python's WAIT
        cv.persist_effective(
            s, [DEAR], ops, applied=False, as_of=DEAR.as_of, now=NOW, review_above_pct=60.0
        )
        row = s.get(ValueEffectiveRow, ("STDY", "deep_value"))
        assert (row.verdict, row.decided_by) == ("WAIT", "python")


def test_claude_applies_in_paper_in_live_only_with_apply_live_and_never_while_tripped(
    value_db,
) -> None:
    live_on = CFG.model_copy(update={"claude": CFG.claude.model_copy(update={"apply_live": True})})
    with value_session() as s:
        assert cv.applies(s, CFG, is_live=False) is True
        assert cv.applies(s, CFG, is_live=True) is False  # record-only in live
        assert cv.applies(s, live_on, is_live=True) is True
        cv.set_breaker(s, {"tripped": True, "reason": "x"}, NOW)
        assert cv.applies(s, CFG, is_live=False) is False
        cv.reset_breaker(s, NOW)
        assert cv.applies(s, CFG, is_live=False) is True


def _night(s, as_of: date, **claude: int) -> None:
    s.add(
        ValueRunRow(
            kind="nightly",
            started_at=NOW,
            as_of=as_of,
            ruleset_version="v4",
            ruleset_hash="x",
            summary_json=json.dumps({"claude": claude}),
        )
    )


def test_the_breaker_trips_on_the_ready_multiple_and_on_the_clamp_rate(value_db) -> None:
    with value_session() as s:
        for i in range(3):
            _night(s, date(2026, 10, 20 + i), ready=2, baseline_ready=1, values=2, clamped=0)
        # 6 + 2 READY against 3 baseline: below 3x (9); then tonight's 4 makes 10 > 9
        assert (
            cv.check_breaker(
                s, CFG, {"ready": 2, "baseline_ready": 0, "values": 1, "clamped": 0}, NOW
            )
            is False
        )
        assert (
            cv.check_breaker(
                s, CFG, {"ready": 4, "baseline_ready": 0, "values": 1, "clamped": 0}, NOW
            )
            is True
        )
        assert "Claude READY 10" in cv.breaker_state(s)["reason"]
    with value_session() as s:
        cv.reset_breaker(s, NOW)
        # clamp rate: 3 of 9 values (33% > 25%) with at least 8 values read
        tonight = {"ready": 0, "baseline_ready": 0, "values": 3, "clamped": 3}
        assert cv.check_breaker(s, CFG, tonight, NOW) is True
        assert "set 3 of 9" in cv.breaker_state(s)["reason"]
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_claude.py`
  Expected: FAIL — `ModuleNotFoundError: No module named 'src.value.claude_verdicts'`.

- [x] **Step 3: The module** — create `src/value/claude_verdicts.py`:

```python
"""Accepting Claude's reads, and what they decide (spec §6.7, §8.2, §8.3, §8.5).

``accept`` turns one ``AnalystResult`` into rows: per list, the verdict and the drivers after
Python bounded them, with the fair value Python computed and capped (``claude_valuation``);
the prose; the kill triggers with their thresholds bounded; and, for a review, the review state on
the re-evaluation. Between filings a re-read may lower Claude's value, never raise it: drivers that
would value the name higher on the same accession are refused and the earlier ones kept.

``opinions`` reads the latest usable verdict per name and list and recomputes its fair value from
the stored drivers on **tonight's** scorecard, so Claude's value moves only when the filed inputs
or Python's own value (the cap) move. An Ollama verdict is never an opinion. ``persist_effective``
writes ``value_effective`` every night. The breaker (spec §8.2) is read from the nightly runs'
summaries and, once tripped, stays tripped until the operator resets it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg, ValueRulesCfg
from src.common.value_ai_types import AnalystResult, Drivers, KillTrigger
from src.value.claude_valuation import ClaudeValue, claude_fair_value
from src.value.effective import ClaudeOpinion, Effective, effective
from src.value.schemas import LISTS, ValueScorecard
from src.value.store import (
    ValueClaudeNoteRow,
    ValueClaudeReadRow,
    ValueClaudeStateRow,
    ValueClaudeVerdictRow,
    ValueEffectiveRow,
    ValueKillTriggerRow,
    ValueReevaluationRow,
    ValueRunRow,
)

BREAKER_KEY = "breaker"


@dataclass(slots=True)
class Accepted:
    verdicts: int = 0
    refused: list[str] | None = None  # lists whose verdict was not stored, and why
    kept_earlier: int = 0  # raised between filings: the earlier drivers stand
    triggers: int = 0
    review_state: str | None = None


def _latest_verdict(vs: Session, symbol: str, list_name: str) -> ValueClaudeVerdictRow | None:
    return vs.scalars(
        select(ValueClaudeVerdictRow)
        .where(
            ValueClaudeVerdictRow.symbol == symbol,
            ValueClaudeVerdictRow.list_name == list_name,
            ValueClaudeVerdictRow.superseded.is_(False),
            ValueClaudeVerdictRow.backend == "cli",
        )
        .order_by(ValueClaudeVerdictRow.id.desc())
        .limit(1)
    ).first()


def bounded_trigger(t: KillTrigger, rules: ValueRulesCfg) -> KillTrigger | None:
    """A trigger with its threshold moved into the menu's range; None when a numeric predicate
    came without a threshold. The fact-based kinds carry none."""
    bound = rules.claude.kill_bounds.get(t.kind)
    if bound is None:
        return KillTrigger(kind=t.kind, threshold=None)
    if t.threshold is None:
        return None
    lo, hi = bound
    return KillTrigger(kind=t.kind, threshold=min(max(t.threshold, lo), hi))


def accept(
    vs: Session,
    read: ValueClaudeReadRow,
    result: AnalystResult,
    card: ValueScorecard,
    cfg: ValueCfg,
    *,
    now: datetime,
) -> Accepted:
    """Store one read's outcome. The read row records the call either way; a reply that is None
    (a failure, a malformed reply) stores nothing else: no notes, never a guess."""
    call = result.call
    read.read_at, read.model, read.backend = now, call.model, call.backend
    read.latency_ms, read.cost_usd, read.error = call.latency_ms, call.cost_usd, call.error
    read.prompt_version, read.prompt, read.raw = call.prompt_version, call.prompt, call.raw
    read.status = "done" if result.reply is not None else "failed"
    out = Accepted(refused=[])
    reply = result.reply
    if reply is None:
        return out
    rules = cfg.rules
    accn = card.fingerprint.latest_accn
    for call_list in reply.lists:
        if call_list.list_name not in card.lists:
            out.refused = [*(out.refused or []), f"{call_list.list_name}: not on this list"]
            continue
        value = claude_fair_value(card, call_list.list_name, call_list.drivers, rules)
        drivers = value.drivers
        prev = (
            _latest_verdict(vs, read.symbol, call_list.list_name) if call.backend == "cli" else None
        )
        clamps = list(value.clamps)
        if prev is not None and prev.accn == accn and value.fair_value is not None:
            before = claude_fair_value(
                card, call_list.list_name, Drivers.model_validate_json(prev.drivers_json), rules
            )
            if before.fair_value is not None and value.fair_value > before.fair_value:
                value, drivers = before, before.drivers  # between filings: lower, never raise
                clamps.append("raised between filings: the earlier drivers stand")
                out.kept_earlier += 1
        if prev is not None:
            prev.superseded = True
        vs.add(
            ValueClaudeVerdictRow(
                read_id=read.id,
                symbol=read.symbol,
                list_name=call_list.list_name,
                verdict=call_list.verdict,
                why=call_list.why,
                drivers_json=drivers.model_dump_json(),
                clamps_json=json.dumps(clamps),
                fair_value=value.fair_value,
                uncapped=value.uncapped,
                python_fair_value=value.python_fair_value,
                clamp_bound=value.clamp_bound,
                unreliable=value.unreliable,
                accn=accn,
                fingerprint_key=card.fingerprint.key(),
                backend=call.backend,
                created_at=now,
            )
        )
        out.verdicts += 1
    vs.add(
        ValueClaudeNoteRow(
            read_id=read.id,
            symbol=read.symbol,
            profile=reply.profile,
            why_cheap=reply.why_cheap,
            thesis=reply.thesis,
            bear_case=reply.bear_case,
            review_state=reply.review_state,
            review_why=reply.review_why,
            backend=call.backend,
            created_at=now,
        )
    )
    if reply.kill_triggers and call.backend == "cli":
        for old in vs.scalars(
            select(ValueKillTriggerRow).where(
                ValueKillTriggerRow.symbol == read.symbol, ValueKillTriggerRow.active.is_(True)
            )
        ):
            old.active = False  # a new set replaces the old one
        for t in reply.kill_triggers[: rules.claude.max_kill_triggers]:
            kept = bounded_trigger(t, rules)
            if kept is None:
                continue
            vs.add(
                ValueKillTriggerRow(
                    read_id=read.id,
                    symbol=read.symbol,
                    kind=kept.kind,
                    threshold=kept.threshold,
                    chosen_at=now,
                )
            )
            out.triggers += 1
    if reply.review_state is not None and read.reevaluation_id is not None:
        reeval = vs.get(ValueReevaluationRow, read.reevaluation_id)
        if reeval is not None and call.backend == "cli":
            reeval.review_state = reply.review_state
            out.review_state = reply.review_state
    vs.flush()
    return out


def opinions(
    vs: Session, cards: list[ValueScorecard], rules: ValueRulesCfg
) -> dict[tuple[str, str], tuple[ClaudeOpinion, ClaudeValue]]:
    """Every name's latest usable CLI verdict per list, its fair value recomputed from the
    stored drivers on tonight's scorecard. Ignores the breaker and the live switch: callers
    decide whether an opinion applies (``applies``)."""
    by_symbol = {c.symbol: c for c in cards}
    out: dict[tuple[str, str], tuple[ClaudeOpinion, ClaudeValue]] = {}
    rows = vs.scalars(
        select(ValueClaudeVerdictRow).where(
            ValueClaudeVerdictRow.superseded.is_(False),
            ValueClaudeVerdictRow.backend == "cli",
            ValueClaudeVerdictRow.symbol.in_(list(by_symbol)),
        )
    )
    for row in rows:
        card = by_symbol[row.symbol]
        value = claude_fair_value(
            card, row.list_name, Drivers.model_validate_json(row.drivers_json), rules
        )
        out[(row.symbol, row.list_name)] = (
            ClaudeOpinion(row.verdict, value.fair_value, row.id),
            value,
        )
    return out


def breaker_state(vs: Session) -> dict[str, Any]:
    row = vs.get(ValueClaudeStateRow, BREAKER_KEY)
    return {"tripped": False} if row is None else json.loads(row.value)


def set_breaker(vs: Session, state: dict[str, Any], now: datetime) -> None:
    row = vs.get(ValueClaudeStateRow, BREAKER_KEY)
    blob = json.dumps(state, sort_keys=True)
    if row is None:
        vs.add(ValueClaudeStateRow(key=BREAKER_KEY, value=blob, updated_at=now))
    else:
        row.value, row.updated_at = blob, now


def applies(vs: Session, cfg: ValueCfg, *, is_live: bool) -> bool:
    """Whether Claude's verdict decides what Stage 3 acts on: paper, or live with
    ``apply_live`` on, and the breaker not tripped (spec §8.2)."""
    if is_live and not cfg.claude.apply_live:
        return False
    return not breaker_state(vs).get("tripped", False)


def night_counts(
    cards: list[ValueScorecard],
    tags: dict[str, str],
    ops: dict[tuple[str, str], tuple[ClaudeOpinion, ClaudeValue]],
    review_above_pct: float,
) -> dict[str, int]:
    """Tonight's breaker inputs over the trading universe: Claude-decided READYs (opinions
    applied), the baseline's READYs, Claude's usable fair values and how many the cap set."""
    out = {"ready": 0, "baseline_ready": 0, "values": 0, "clamped": 0}
    for card in cards:
        if tags.get(card.symbol) != "trading":
            continue
        for name in LISTS:
            if card.verdict_for(name) == "READY":
                out["baseline_ready"] += 1
            found = ops.get((card.symbol, name))
            if found is None:
                continue
            opinion, value = found
            if value.fair_value is not None:
                out["values"] += 1
                out["clamped"] += int(value.clamp_bound)
            eff = effective(card, name, opinion, review_above_pct=review_above_pct)
            if eff.decided_by == "claude" and eff.verdict == "READY":
                out["ready"] += 1
    return out


def check_breaker(vs: Session, cfg: ValueCfg, tonight: dict[str, int], now: datetime) -> bool:
    """Trip the breaker when the last ``sessions`` nights (tonight included) breach either
    rate. Returns whether it is tripped after tonight. Never resets itself."""
    state = breaker_state(vs)
    if state.get("tripped"):
        return True
    b = cfg.claude.breaker
    totals = dict(tonight)
    runs = vs.scalars(
        select(ValueRunRow)
        .where(ValueRunRow.kind == "nightly")
        .order_by(ValueRunRow.as_of.desc())
        .limit(b.sessions - 1)
    )
    for run in runs:
        night = json.loads(run.summary_json or "{}").get("claude", {})
        for key in totals:
            totals[key] += int(night.get(key, 0))
    reason = None
    if (
        totals["ready"] >= b.min_ready
        and totals["ready"] > b.ready_multiple * totals["baseline_ready"]
    ):
        reason = (
            f"Claude READY {totals['ready']} > {b.ready_multiple:g} x the baseline's "
            f"{totals['baseline_ready']} over {b.sessions} sessions"
        )
    elif (
        totals["values"] >= b.min_values
        and totals["clamped"] * 100.0 / totals["values"] > b.clamp_rate_pct
    ):
        reason = (
            f"the 1.5x clamp set {totals['clamped']} of {totals['values']} fair values "
            f"(> {b.clamp_rate_pct:g}%) over {b.sessions} sessions"
        )
    if reason is None:
        return False
    set_breaker(vs, {"tripped": True, "since": now.isoformat(), "reason": reason}, now)
    return True


def reset_breaker(vs: Session, now: datetime) -> None:
    set_breaker(vs, {"tripped": False, "reset_at": now.isoformat()}, now)


def persist_effective(
    vs: Session,
    cards: list[ValueScorecard],
    ops: dict[tuple[str, str], tuple[ClaudeOpinion, ClaudeValue]],
    *,
    applied: bool,
    as_of: date,
    now: datetime,
    review_above_pct: float,
) -> dict[tuple[str, str], Effective]:
    """Write ``value_effective`` for every scored name and list; returns it. With *applied*
    False every list keeps Python's baseline (breaker tripped, or live with apply_live off)."""
    out: dict[tuple[str, str], Effective] = {}
    for card in cards:
        for name in LISTS:
            found = ops.get((card.symbol, name)) if applied else None
            eff = effective(
                card, name, found[0] if found else None, review_above_pct=review_above_pct
            )
            out[(card.symbol, name)] = eff
            row = vs.get(ValueEffectiveRow, (card.symbol, name))
            values = dict(
                as_of=as_of,
                verdict=eff.verdict,
                decided_by=eff.decided_by,
                python_verdict=eff.python_verdict,
                claude_verdict=eff.claude_verdict,
                verdict_id=eff.verdict_id,
                fair_value=eff.fair_value,
                entry_ceiling=eff.entry_ceiling,
                margin_of_safety=eff.margin_of_safety,
                mos_review=eff.mos_review,
                updated_at=now,
            )
            if row is None:
                vs.add(ValueEffectiveRow(symbol=card.symbol, list_name=name, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
    return out
```

- [x] **Step 4: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_claude.py tests/test_value_fence.py`
  Expected: PASS.

- [x] **Step 5: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the two files;
  `.venv/bin/mypy src/value/claude_verdicts.py`.

  ```bash
  git add src/value/claude_verdicts.py tests/test_value_claude.py
  git commit -m "feat(value): accept Claude's reads, opinions recomputed nightly, the breaker"
  ```

---

### Task 6: The read queue, the nightly wiring, the process and the operator's CLI

**Files:**
- Create: `src/value/claude_reads.py`, `scripts/value_claude.py`
- Modify: `src/value/service.py` (module docstring; the `from src.value import` line; after the
  ticker files' `vs.flush()`; the summary's `"shadow"` line), `scripts/run_value.py`,
  `tests/test_value_claude.py` (helpers and four tests), `tests/test_value_fence.py` (the
  entrypoint's allowlist and the probe line)

**Interfaces:**
- Consumes: Task 5's `accept`, `opinions`, `night_counts`, `applies`, `persist_effective`,
  `check_breaker`; Task 4's `Analyst`.
- Produces: `claude_reads.PRIORITY`, `render_card`, `kill_menu`, `build_request`, `queue_read`,
  `reads_left`, `stale`, `plan_auto_reads`, `run_queue(reader, *, now, cfg, sections_for=None,
  limit=None)`; `service.run_nightly`'s summary gains `"claude": {ready, baseline_ready, values,
  clamped, applied, breaker, top, stale}`; `scripts/run_value.py::_claude_tick`;
  `scripts/value_claude.py::main(argv)`.

- [x] **Step 1: Write the failing tests** — apply to `tests/test_value_claude.py` and
  `tests/test_value_fence.py`:

```diff
diff --git a/tests/test_value_claude.py b/tests/test_value_claude.py
index 2fc38b3..66f1409 100644
--- a/tests/test_value_claude.py
+++ b/tests/test_value_claude.py
@@ -4,22 +4,31 @@ the queue (value book spec §6.7, §8.2, §8.3, §8.5)."""
 from __future__ import annotations
 
 import json
-from datetime import date, datetime
+from datetime import date, datetime, timedelta
 
 import pytest
 from sqlalchemy import select
 
 import src.value.store as store
-from src.common.config import get_config
+from src.common.config import ValueCfg, get_config
 from src.common.value_ai_types import (
     AnalystCall,
     AnalystReply,
+    AnalystRequest,
     AnalystResult,
     Drivers,
     KillTrigger,
     ListCall,
 )
 from src.value import claude_verdicts as cv
+from src.value.claude_reads import (
+    build_request,
+    plan_auto_reads,
+    queue_read,
+    reads_left,
+    render_card,
+    run_queue,
+)
 from src.value.scorecard import build_scorecard
 from src.value.store import (
     ValueClaudeNoteRow,
@@ -32,9 +41,11 @@ from src.value.store import (
     init_value_db,
     value_session,
 )
+from src.value.ticker_file import persist
 from tests.value_fixtures import financials, inputs
 
 CFG = get_config().value
+ON = CFG.model_copy(update={"claude": CFG.claude.model_copy(update={"enabled": True})})
 NOW = datetime(2026, 11, 2, 15, 0)  # naive UTC, 10:00 ET
 CHEAP = build_scorecard(inputs(close=30.0), CFG)  # deep: Python FV 46.85, READY
 DEAR = build_scorecard(inputs(close=40.0), CFG)  # deep: Python WAIT
@@ -52,6 +63,19 @@ def value_db(tmp_path, monkeypatch):
     store.reset_engine()
 
 
+def _file(card, *, universe: str = "trading", rank: float = 0.9) -> None:
+    with value_session() as s:
+        persist(
+            s,
+            card,
+            universe=universe,
+            ranks={"deep_value": rank, "quality_growth": rank},
+            filed="deep_value",
+            cfg=CFG.ticker_file,
+            session_row=False,
+        )
+
+
 def _result(read_id: int, *, verdict="READY", drivers=GOOD_DRIVERS, backend="cli", **reply):
     return AnalystResult(
         read_id=read_id,
@@ -258,3 +282,69 @@ def test_the_breaker_trips_on_the_ready_multiple_and_on_the_clamp_rate(value_db)
         tonight = {"ready": 0, "baseline_ready": 0, "values": 3, "clamped": 3}
         assert cv.check_breaker(s, CFG, tonight, NOW) is True
         assert "set 3 of 9" in cv.breaker_state(s)["reason"]
+
+
+def test_the_queue_reads_the_top_unread_trading_names_and_stale_ones(value_db) -> None:
+    _file(CHEAP)
+    _file(build_scorecard(inputs(symbol="EVID", close=30.0), CFG), universe="evidence")
+    with value_session() as s:
+        assert plan_auto_reads(s, NOW, ON) == {"top": 1, "stale": 0}
+        assert [r.symbol for r in s.scalars(select(ValueClaudeReadRow))] == ["STDY"]
+    _accept(CHEAP, _result(0))
+    with value_session() as s:
+        assert plan_auto_reads(s, NOW, ON) == {"top": 0, "stale": 0}  # read, nothing changed
+    filed = build_scorecard(inputs(close=30.0, fin=financials(accn="0000000001-26-000002")), CFG)
+    _file(filed)
+    with value_session() as s:
+        assert plan_auto_reads(s, NOW, ON) == {"top": 0, "stale": 1}  # a new filing
+
+
+def test_the_daily_caps_and_a_disabled_switch(value_db) -> None:
+    _file(CHEAP)
+    tight = ON.model_copy(
+        update={"claude": ON.claude.model_copy(update={"standard_reads_per_day": 1})}
+    )
+    seen: list[AnalystRequest] = []
+
+    def reader(req: AnalystRequest) -> AnalystResult:
+        seen.append(req)
+        return _result(req.read_id)
+
+    with value_session() as s:
+        queue_read(s, "STDY", kind="standard", reason="request", now=NOW)
+    assert run_queue(reader, now=NOW, cfg=CFG) == {
+        "done": 0,
+        "failed": 0,
+        "skipped": 0,
+        "waiting": 0,
+    }
+    assert run_queue(reader, now=NOW, cfg=tight)["done"] == 1
+    (req,) = seen
+    assert req.lists == ["deep_value", "quality_growth"] and req.bounds
+    assert req.kill_menu["guidance_cut"] is None and req.model == get_config().claude.model
+    with value_session() as s:
+        assert reads_left(s, NOW, tight) == (0, 3)
+        queue_read(s, "STDY", kind="standard", reason="request", now=NOW)
+    assert run_queue(reader, now=NOW, cfg=tight)["done"] == 0  # today's cap is spent
+    with value_session() as s:
+        assert reads_left(s, NOW + timedelta(days=1), tight) == (1, 3)  # a new ET day
+
+
+def test_the_request_carries_the_card_the_bounds_and_the_kind_model(value_db) -> None:
+    models = ValueCfg(
+        ruleset_version="v4", claude={"models": {"verdict": "claude-opus-4-7"}}
+    ).model_copy(update={"rules": CFG.rules})
+    row = ValueClaudeReadRow(id=9, symbol="STDY", kind="standard", reason="top", priority=3)
+    req = build_request(row, CHEAP, models)
+    assert req.model == "claude-opus-4-7" and req.read_id == 9
+    assert "deep_value: Python READY · fair value 46.85" in req.card_text
+    assert render_card(CHEAP).count("\n") >= 6
+
+
+def test_the_operator_script_queues_a_read_and_resets_the_breaker(value_db, capsys) -> None:
+    from scripts.value_claude import main
+
+    assert main(["--read", "nvda"]) == 0
+    assert main(["--read", "NVDA", "--reset-breaker"]) == 0
+    out = capsys.readouterr().out
+    assert "queued NVDA" in out and "NVDA: already queued" in out and "breaker reset" in out
diff --git a/tests/test_value_fence.py b/tests/test_value_fence.py
index 7309a72..3807034 100644
--- a/tests/test_value_fence.py
+++ b/tests/test_value_fence.py
@@ -224,7 +224,8 @@ def test_the_value_scorecard_loads_no_wheel_layer_even_transitively() -> None:
         "import src.value.scorecard, src.value.store, src.value.ticker_file, src.value.funnel\n"
         "import src.value.exits, src.value.shadow, src.value.service, src.value.report\n"
         "import src.value.residuals, src.value.reevaluate\n"
-        "import src.value.claude_valuation, src.value.effective\n"
+        "import src.value.claude_valuation, src.value.effective, src.value.claude_verdicts\n"
+        "import src.value.claude_reads\n"
         "import src.common.value_inputs, src.common.value_universe\n"
         "print(json.dumps(sorted(m for m in sys.modules if m.startswith('src.'))))\n"
     )
@@ -264,13 +265,18 @@ def test_the_value_entrypoint_imports_only_its_feed_and_the_service() -> None:
     """scripts/run_value.py is never imported (it starts a service), so its own imports are
     checked by name; everything it reaches is in the sys.modules probe below."""
     allowed = (
+        "asyncio",
+        "datetime",
         "logging",
         "signal",
         "threading",
         "scripts.value_feed",
         "src.common.config",
         "src.common.logging",
+        "src.common.value_ai_types",
+        "src.value.claude_reads",
         "src.value.service",
+        "src.value_ai.analyst",
     )
     mods = imported_modules(ROOT / "scripts" / "run_value.py")
     extra = sorted(m for m in mods if not any(m == a or m.startswith(a + ".") for a in allowed))
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_claude.py tests/test_value_fence.py`
  Expected: FAIL — `ModuleNotFoundError: No module named 'src.value.claude_reads'` (collection
  error) and, once that exists, the entrypoint allowlist test.

- [x] **Step 3: The queue** — create `src/value/claude_reads.py`:

```python
"""Which names Claude reads, when, and at what cost (spec §8.3, §8.5).

The queue lives in ``value_claude_reads``. Priority, as the spec orders it: the operator's
requests, then re-evaluations of held names, then filing reads (held and READY names on a new
10-K/10-Q), then the top-ranked healthy names Claude has not read, then stale re-reads. Never the
evidence universe or a shadow position. A name is re-read only when its filings, Python's fair
value (by more than ``stale_fv_pct``) or its age (``max_age_days``) say so, so the steady state is
a handful of reads a day. Caps: ``standard_reads_per_day`` (standard and review reads) and
``deep_reads_per_day`` (filing reads), counted per ET day.

The reads themselves happen in ``run_queue`` through a *reader* the entrypoint passes in
(``scripts/run_value.py`` wraps ``src.value_ai``): this module never imports Claude. Each read is
its own transaction, outside the night's, because a call takes tens of seconds.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg, get_config
from src.common.value_ai_types import (
    KILL_KINDS,
    AnalystRequest,
    AnalystResult,
    FilingSection,
    Range,
)
from src.value.claude_valuation import bounds_for
from src.value.claude_verdicts import accept
from src.value.schemas import LISTS, ValueScorecard
from src.value.store import (
    ValueClaudeReadRow,
    ValueClaudeVerdictRow,
    ValueReevaluationRow,
    ValueTickerFileRow,
    value_session,
)

log = logging.getLogger(__name__)

PRIORITY = {"request": 0, "review": 1, "filing": 2, "top": 3, "stale": 4}
DEEP_KINDS = ("filing",)
Reader = Callable[[AnalystRequest], AnalystResult]
SectionsFor = Callable[[str, str], list[FilingSection]]


def _fmt(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct else f"{v:,.2f}"


def render_card(card: ValueScorecard) -> str:
    """The scorecard as labelled numbers for the prompt (unknown is ``n/a``, never zero)."""
    m = card.metrics
    lines = [
        f"{card.symbol} · {card.classification.sector or 'n/a'} / "
        f"{card.classification.industry or 'n/a'} · class {card.company_class} · as of "
        f"{card.as_of} · price {_fmt(card.price)}",
        f"health {card.health}; data quality {card.data_quality}",
        "health checks: "
        + "; ".join(
            f"{c.id.removeprefix('health.')} {c.state} ({_fmt(c.actual)} vs {_fmt(c.threshold)})"
            for c in card.health_checks
        ),
        f"TTM FCF {_fmt(m.get('fcf_ttm'))}M · SBC {_fmt(m.get('sbc_ttm'))}M · revenue "
        f"{_fmt(m.get('revenue_ttm'))}M · revenue/share {_fmt(m.get('revenue_ps_ttm'))}",
        f"5-year revenue CAGR {_fmt(m.get('revenue_cagr_5y'), True)} · FCF/share CAGR "
        f"{_fmt(card.realised_fcf_ps_cagr, True)} · last year's revenue growth "
        f"{_fmt(m.get('revenue_growth_1y'), True)}",
        f"FCF margin (less SBC) 5y median {_fmt(m.get('fcf_margin_median_5y'), True)}, best "
        f"{_fmt(m.get('fcf_margin_best_5y'), True)} · gross margin "
        f"{_fmt(m.get('gross_margin_latest'), True)} · ROIC 5y median "
        f"{_fmt(m.get('roic_median_5y'), True)}",
        f"the price implies {_fmt(card.reverse_dcf_implied_growth, True)} a year of FCF growth "
        "for ten years (reverse DCF)",
    ]
    if m.get("rote_median_5y") is not None:
        lines.append(
            f"ROTE 5y median {_fmt(m.get('rote_median_5y'), True)} · tangible book/share "
            f"{_fmt(m.get('tbv_ps'))}"
        )
    for name, ev in card.lists.items():
        methods = ", ".join(
            f"{x.method} {_fmt(x.value)} ({x.state})" for x in ev.methods if x.state != "absent"
        )
        lines.append(
            f"{name}: Python {card.verdict_for(name)} · fair value {_fmt(ev.fair_value)} "
            f"[{methods or 'no method'}] · required margin {ev.required_mos_pct:g}% · ceiling "
            f"{_fmt(ev.entry_ceiling)} · timing {ev.timing} · entry rule {ev.entry}"
        )
    return "\n".join(lines)


def kill_menu(cfg: ValueCfg) -> dict[str, Range | None]:
    bounds = cfg.rules.claude.kill_bounds
    return {
        k: (Range(lo=bounds[k][0], hi=bounds[k][1]) if k in bounds else None) for k in KILL_KINDS
    }


def _card(vs: Session, symbol: str) -> ValueScorecard | None:
    row = vs.get(ValueTickerFileRow, symbol)
    return None if row is None else ValueScorecard.model_validate_json(row.scorecard_json)


def _healthy_lists(card: ValueScorecard) -> list[str]:
    return [n for n in LISTS if card.verdict_for(n) in ("READY", "WATCH", "WAIT")]


def build_request(
    row: ValueClaudeReadRow,
    card: ValueScorecard,
    cfg: ValueCfg,
    *,
    trigger_text: str = "",
    sections: list[FilingSection] | None = None,
) -> AnalystRequest:
    lists = _healthy_lists(card)
    kind_model = {"standard": "verdict", "filing": "filing", "review": "review"}[row.kind]
    model = getattr(cfg.claude.models, kind_model) or get_config().claude.model
    return AnalystRequest(
        read_id=row.id,
        symbol=row.symbol,
        kind=row.kind,  # type: ignore[arg-type]  # validated against ReadKind
        reason=row.reason,
        lists=lists,
        card_text=render_card(card),
        bounds=[b for n in lists if (b := bounds_for(card, n, cfg.rules)) is not None],
        kill_menu=kill_menu(cfg),
        max_kill_triggers=cfg.rules.claude.max_kill_triggers,
        trigger_text=trigger_text,
        sections=sections or [],
        model=model,
        effort=cfg.claude.effort,
        timeout_seconds=cfg.claude.filing_timeout_seconds
        if row.kind == "filing"
        else cfg.claude.timeout_seconds,
    )


def queue_read(
    vs: Session,
    symbol: str,
    *,
    kind: str,
    reason: str,
    now: datetime,
    accn: str | None = None,
    reevaluation_id: int | None = None,
) -> ValueClaudeReadRow | None:
    """Queue one read unless the same name already has one queued (requests jump the queue by
    priority, they do not stack)."""
    queued = vs.scalars(
        select(ValueClaudeReadRow).where(
            ValueClaudeReadRow.symbol == symbol,
            ValueClaudeReadRow.kind == kind,
            ValueClaudeReadRow.status == "queued",
        )
    ).first()
    if queued is not None:
        if PRIORITY[reason] < queued.priority:
            queued.reason, queued.priority = reason, PRIORITY[reason]
        return None
    row = ValueClaudeReadRow(
        symbol=symbol,
        kind=kind,
        reason=reason,
        priority=PRIORITY[reason],
        status="queued",
        requested_at=now,
        accn=accn,
        reevaluation_id=reevaluation_id,
    )
    vs.add(row)
    vs.flush()
    return row


def _et_day_start(now: datetime) -> datetime:
    """Midnight ET of *now*'s ET day, as naive UTC (the tables' clock)."""
    tz = ZoneInfo(get_config().scheduler.timezone)
    local = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def reads_left(vs: Session, now: datetime, cfg: ValueCfg) -> tuple[int, int]:
    """(standard and review reads left today, filing reads left today)."""
    since = _et_day_start(now)
    rows = vs.execute(
        select(ValueClaudeReadRow.kind, func.count())
        .where(
            ValueClaudeReadRow.read_at.is_not(None),
            ValueClaudeReadRow.read_at >= since,
        )
        .group_by(ValueClaudeReadRow.kind)
    ).all()
    used = {kind: n for kind, n in rows}
    deep = sum(used.get(k, 0) for k in DEEP_KINDS)
    standard = sum(n for k, n in used.items() if k not in DEEP_KINDS)
    return (
        max(0, cfg.claude.standard_reads_per_day - standard),
        max(0, cfg.claude.deep_reads_per_day - deep),
    )


def stale(
    verdict: ValueClaudeVerdictRow, card: ValueScorecard, cfg: ValueCfg, now: datetime
) -> bool:
    """Spec §8.3 "tied to the numbers it saw": a new filing, Python's fair value moved by more
    than ``stale_fv_pct``, or older than ``max_age_days``. Price alone never makes it stale."""
    if card.fingerprint.latest_accn != verdict.accn:
        return True
    ev = card.lists.get(verdict.list_name)
    now_fv, then_fv = (ev.fair_value if ev else None), verdict.python_fair_value
    if (now_fv is None) != (then_fv is None):
        return True
    if now_fv and then_fv and abs(now_fv / then_fv - 1.0) * 100.0 > cfg.claude.stale_fv_pct:
        return True
    return now - verdict.created_at > timedelta(days=cfg.claude.max_age_days)


def plan_auto_reads(vs: Session, now: datetime, cfg: ValueCfg) -> dict[str, int]:
    """After a night: queue the top-ranked unread healthy trading names per list and the stale
    re-reads; drop yesterday's automatic reads the budget never reached. Requests and reviews
    stay queued."""
    for old in vs.scalars(
        select(ValueClaudeReadRow).where(
            ValueClaudeReadRow.status == "queued",
            ValueClaudeReadRow.reason.in_(("top", "stale")),
        )
    ):
        old.status, old.detail = "skipped", "superseded by the next night's plan"
    files = vs.scalars(
        select(ValueTickerFileRow).where(ValueTickerFileRow.universe == "trading")
    ).all()
    latest: dict[str, list[ValueClaudeVerdictRow]] = {}
    for v in vs.scalars(
        select(ValueClaudeVerdictRow).where(
            ValueClaudeVerdictRow.superseded.is_(False), ValueClaudeVerdictRow.backend == "cli"
        )
    ):
        latest.setdefault(v.symbol, []).append(v)
    counts = {"top": 0, "stale": 0}
    picked: set[str] = set()
    for rank_attr, verdict_attr in (
        ("rank_deep", "verdict_deep"),
        ("rank_growth", "verdict_growth"),
    ):
        healthy = [
            f
            for f in files
            if f.health == "pass"
            and getattr(f, verdict_attr) in ("READY", "WATCH", "WAIT")
            and getattr(f, rank_attr) is not None
        ]
        healthy.sort(key=lambda f: (-getattr(f, rank_attr), f.symbol))
        for f in healthy[: cfg.claude.top_per_list]:
            if f.symbol in picked:
                continue
            card = ValueScorecard.model_validate_json(f.scorecard_json)
            seen = latest.get(f.symbol, [])
            if not seen:
                reason = "top"
            elif any(stale(v, card, cfg, now) for v in seen):
                reason = "stale"
            else:
                continue
            if queue_read(vs, f.symbol, kind="standard", reason=reason, now=now) is not None:
                counts[reason] += 1
            picked.add(f.symbol)
    return counts


def _review_text(vs: Session, reevaluation_id: int | None) -> str:
    if reevaluation_id is None:
        return ""
    r = vs.get(ValueReevaluationRow, reevaluation_id)
    if r is None:
        return ""
    return (
        f"opened {r.session} ({r.severity}); triggers {r.triggers_json}; plan before "
        f"{r.plan_before_json}; plan after {r.plan_after_json}; verdict at entry "
        f"{r.verdict_at_entry}, now {r.verdict_now or 'n/a'}"
    )


def run_queue(
    reader: Reader,
    *,
    now: datetime,
    cfg: ValueCfg,
    sections_for: SectionsFor | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run queued reads, best priority first, within today's caps. A filing read whose sections
    are not in research.db yet waits (the research worker fetches them). Returns counts."""
    summary: dict[str, Any] = {"done": 0, "failed": 0, "skipped": 0, "waiting": 0}
    if not cfg.claude.enabled:
        return summary
    with value_session() as vs:
        ids = list(
            vs.scalars(
                select(ValueClaudeReadRow.id)
                .where(ValueClaudeReadRow.status == "queued")
                .order_by(ValueClaudeReadRow.priority, ValueClaudeReadRow.id)
            )
        )
    for read_id in ids[:limit] if limit is not None else ids:
        with value_session() as vs:
            row = vs.get(ValueClaudeReadRow, read_id)
            if row is None or row.status != "queued":
                continue
            standard_left, deep_left = reads_left(vs, now, cfg)
            if (deep_left if row.kind in DEEP_KINDS else standard_left) <= 0:
                continue
            card = _card(vs, row.symbol)
            if card is None or not _healthy_lists(card) and row.kind != "filing":
                row.status, row.detail = "skipped", "no healthy list to read"
                summary["skipped"] += 1
                continue
            sections: list[FilingSection] = []
            if row.kind == "filing":
                sections = sections_for(row.symbol, row.accn or "") if sections_for else []
                if not sections:
                    summary["waiting"] += 1
                    continue
            req = build_request(
                row,
                card,
                cfg,
                trigger_text=_review_text(vs, row.reevaluation_id),
                sections=sections,
            )
        result = reader(req)  # outside any transaction: a call takes tens of seconds
        with value_session() as vs:
            row = vs.get(ValueClaudeReadRow, read_id)
            card = _card(vs, row.symbol) if row is not None else None
            if row is None or card is None:
                continue
            done = accept(vs, row, result, card, cfg, now=now)
            summary["done" if result.reply is not None else "failed"] += 1
            log.info(
                "value claude read %s %s (%s): %s; %d verdict(s), %d trigger(s)",
                row.symbol,
                row.kind,
                row.reason,
                row.status,
                done.verdicts,
                done.triggers,
            )
    return summary
```

- [x] **Step 4: The night** — apply to `src/value/service.py`:

```diff
diff --git a/src/value/service.py b/src/value/service.py
index 1e90f84..b2670c1 100644
--- a/src/value/service.py
+++ b/src/value/service.py
@@ -8,6 +8,11 @@ news volume from news.db, yfinance market facts) and calls :func:`plan_run` and
 No IBKR connection and no clientId in Parts 1-4 (clientId 31 arrives with Stage 3). Reads
 research.db read-only through ``src/common/value_inputs.py``; writes value.db only. One run is
 one transaction: a run that fails leaves value.db as it was, and the next poll retries it.
+
+Part 4 (spec §6.7, §8): the night also reads Claude's stored verdicts (recomputing each fair value
+on tonight's scorecard), writes the effective verdict of every name and list, checks the breaker,
+and queues tomorrow's automatic reads. The reads themselves run after the night commits
+(``src/value/claude_reads.py::run_queue``, driven by the entrypoint).
 """
 
 from __future__ import annotations
@@ -28,7 +33,8 @@ from src.common.config import get_config
 from src.common.value_keep_fresh import write_keep_fresh
 from src.common.value_types import Classification, MarketFacts, NewsVolume, ValueInputs
 from src.common.value_universe import build_value_universe
-from src.value import reevaluate, shadow
+from src.value import claude_verdicts, reevaluate, shadow
+from src.value.claude_reads import plan_auto_reads
 from src.value.rank import filed_lists, rank_list, rs_cutoff
 from src.value.ruleset import ruleset_id
 from src.value.scorecard import build_scorecard
@@ -281,6 +287,21 @@ def run_nightly(
                     session_row=tag != "lookup",
                 )
             vs.flush()
+            review = vcfg.rules.margin_of_safety.review_above_pct
+            ops = claude_verdicts.opinions(vs, cards, vcfg.rules)
+            claude_night = claude_verdicts.night_counts(cards, plan.tags, ops, review)
+            applied = claude_verdicts.applies(vs, vcfg, is_live=get_config().is_live)
+            claude_verdicts.persist_effective(
+                vs,
+                cards,
+                ops,
+                applied=applied,
+                as_of=plan.as_of,
+                now=started,
+                review_above_pct=review,
+            )
+            tripped = claude_verdicts.check_breaker(vs, vcfg, claude_night, started)
+            queued = plan_auto_reads(vs, started, vcfg) if vcfg.claude.enabled else {}
             stepped = reevaluate.regime_stepped(
                 previous_regime(vs), regime, vcfg.rules.reevaluation
             )
@@ -312,6 +333,7 @@ def run_nightly(
                     1 for i in inputs if not i.classification.is_etf and i.yf_market_cap is None
                 ),
                 "shadow": asdict(record),
+                "claude": {**claude_night, "applied": applied, "breaker": tripped, **queued},
             }
             record_run(
                 vs,
```

- [x] **Step 5: The process** — apply to `scripts/run_value.py` (never import it; it is checked
  with `py_compile`):

```diff
diff --git a/scripts/run_value.py b/scripts/run_value.py
index eab10ba..a4a23a9 100644
--- a/scripts/run_value.py
+++ b/scripts/run_value.py
@@ -7,16 +7,21 @@ No IBKR connection, no clientId (Parts 1-4). Every ``value.service.poll_seconds`
 ``src.value.service.plan_run`` whether a settled session is waiting to be scored; when one is
 (after ``value.service.run_hour_et``), it gathers the plain data ``src/value/`` may not fetch
 itself (``scripts/value_feed.py``: earnings dates, news volume, market facts) and runs the
-night, its §7.1 re-evaluations included. Idles when the ruleset check fails.
+night, its §7.1 re-evaluations included. Then, with ``value.claude.enabled``, it runs Claude's
+queued reads (``src.value.claude_reads.run_queue``) through the analyst in ``src.value_ai``
+(spec §8): the operator's requests on every poll, the automatic set after a night, within the
+day's caps. Idles when the ruleset check fails.
 Runs until SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.
 
-The only module that will import ``src.value_ai`` (Part 4). Never import this file: check it
+The only module that imports ``src.value_ai`` (spec §5, §16). Never import this file: check it
 with ``python -m py_compile``.
 """
 
+import asyncio
 import logging
 import signal
 import threading
+from datetime import UTC, datetime
 
 from scripts.value_feed import (
     FactsCache,
@@ -27,13 +32,35 @@ from scripts.value_feed import (
 )
 from src.common.config import get_config
 from src.common.logging import setup_logging
+from src.common.value_ai_types import AnalystRequest, AnalystResult
+from src.value.claude_reads import run_queue
 from src.value.service import plan_run, run_nightly, startup_check
+from src.value_ai.analyst import Analyst
 
 log = logging.getLogger("value")
 
 
 _retry = NightRetry()
 _facts = FactsCache()
+_analyst: Analyst | None = None
+
+
+def _read(req: AnalystRequest) -> AnalystResult:
+    global _analyst
+    if _analyst is None:
+        _analyst = Analyst.from_config(get_config())
+    return asyncio.run(_analyst.read(req, datetime.now(UTC)))
+
+
+def _claude_tick() -> None:
+    """Claude's queued reads (spec §8.5): requests first, then the automatic set, within the
+    day's caps. Each read commits on its own; a failed read is recorded, never retried blind."""
+    cfg = get_config().value
+    if not cfg.claude.enabled:
+        return
+    summary = run_queue(_read, now=datetime.now(UTC).replace(tzinfo=None), cfg=cfg)
+    if any(summary.values()):
+        log.info("value: claude reads %s", summary)
 
 
 def _tick() -> None:
@@ -86,6 +113,10 @@ def main() -> None:
             _tick()
         except Exception:  # noqa: BLE001 - a failed night is retried at the next poll
             log.exception("value: the nightly run failed; retrying at the next poll")
+        try:
+            _claude_tick()
+        except Exception:  # noqa: BLE001 - a failed read is recorded; the queue waits
+            log.exception("value: claude reads failed; the queue waits for the next poll")
         if stop.wait(poll):
             break
 
```

- [x] **Step 6: The operator's CLI** — create `scripts/value_claude.py`:

```python
"""The operator's handle on Claude's side of the value book (spec §8.2, §8.3, §8.5).

Usage:
    python -m scripts.value_claude                 # the breaker, today's budget, the queue
    python -m scripts.value_claude --read NVDA     # queue a read (first in the queue)
    python -m scripts.value_claude --reset-breaker # Claude's verdict applies again

Writes value.db only through ``src/value/`` (the one writer). The read itself runs in the value
process (``scripts/run_value.py``) at its next poll, with ``value.claude.enabled`` on. Part 6 adds
the same request as a web button and ``/value NAME analyse``.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from src.common.config import get_config
from src.value.claude_reads import queue_read, reads_left
from src.value.claude_verdicts import breaker_state, reset_breaker
from src.value.store import ValueClaudeReadRow, init_value_db, value_session


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--read", metavar="SYMBOL", help="queue a standard read of SYMBOL")
    ap.add_argument("--reset-breaker", action="store_true", help="let Claude's verdict apply")
    args = ap.parse_args(argv)
    cfg = get_config().value
    now = datetime.now(UTC).replace(tzinfo=None)
    init_value_db()
    with value_session() as vs:
        if args.read:
            row = queue_read(vs, args.read.upper(), kind="standard", reason="request", now=now)
            print(f"queued {args.read.upper()}" if row else f"{args.read.upper()}: already queued")
        if args.reset_breaker:
            reset_breaker(vs, now)
            print("breaker reset: Claude's verdict applies again")
        state = breaker_state(vs)
        standard, deep = reads_left(vs, now, cfg)
        queued = vs.scalars(
            select(ValueClaudeReadRow)
            .where(ValueClaudeReadRow.status == "queued")
            .order_by(ValueClaudeReadRow.priority, ValueClaudeReadRow.id)
        ).all()
        print(f"claude reads {'on' if cfg.claude.enabled else 'OFF (value.claude.enabled)'}")
        print(f"breaker: {'TRIPPED: ' + state.get('reason', '') if state.get('tripped') else 'ok'}")
        print(f"left today: {standard} standard, {deep} filing")
        for r in queued:
            print(f"  queued {r.symbol:<6} {r.kind:<8} {r.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 7: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_claude.py tests/test_value_fence.py tests/test_value_service.py tests/test_value_shadow.py`
  and `.venv/bin/python -m py_compile scripts/run_value.py scripts/value_claude.py`.
  Expected: PASS; `py_compile` silent.

- [x] **Step 8: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the six touched files;
  `.venv/bin/mypy src/value/claude_reads.py src/value/service.py scripts/run_value.py scripts/value_claude.py`.

  ```bash
  git add src/value/claude_reads.py src/value/service.py scripts/run_value.py scripts/value_claude.py tests/test_value_claude.py tests/test_value_fence.py
  git commit -m "feat(value): Claude's read queue, the nightly effective verdict, the operator's CLI"
  ```

- [x] **Section B exit** — the full gate (pytest = baseline + 47), the protected-file diff (empty),
  `py_compile` of the two scripts, `git status --short` (clean); fill the Task 6 row and the exit
  numbers, then:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md
  git commit -m "docs(plan): value book Part 4 Progress log - Section B"
  ```

---

## Section C — Kill triggers, the Claude track, the report (Tasks 7–9) · model: sonnet · effort: high

Claude's kill triggers are evaluated by Python every night and a trigger near firing joins §7.1's
re-evaluations as trigger 6; the shadow record gains the `claude` track (Claude's opinion applied,
the trading universe only); the report prints Claude's track beside the baseline's with the
breaker's two rates.

**Spec to read:** §6.8 (the two tracks), §7 ("Which fair value an exit reads"), §7.1 (trigger 6,
the "Fence" paragraph), §8.4, §12 ("Claude vs the baseline"; the track-specific count).

**Files the subagent reads:** `src/value/reevaluate.py`, `src/value/shadow.py`,
`src/value/service.py`, `src/value/claude_verdicts.py`, `src/value/report.py`,
`scripts/value_report.py`, `src/value/exits.py` (lines 50–70, 230–300: `DayFacts` and the half-sale),
`tests/test_value_shadow.py` (lines 1–135, 210–300, 370–410), `tests/test_value_reevaluate.py`
(lines 1–20), `tests/test_value_report.py` (lines 1–80, 215–240).

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **C1. Section B is in.** `git log --oneline main..HEAD | wc -l` equals Section B's recorded
  count; `git status --short` is clean.
- [ ] **C2. A green start.** The full gate passes with pytest = baseline + 47; record it.
- [ ] **C3. The code Section C edits is where this plan says** (line numbers after Section B):

  ```bash
  grep -nF 'TriggerKind = Literal["move", "drift", "earnings", "filing", "news", "regime", "quiet"]' src/value/reevaluate.py   # 23:
  grep -nF '    if regime_stepped:' src/value/reevaluate.py   # 132:
  grep -nF 'from src.value.claude_valuation import ClaudeValue, claude_fair_value' src/value/claude_verdicts.py   # 28:
  grep -nF 'TRACK = "baseline"' src/value/shadow.py   # 72:
  grep -nF 'def blocking_keys(vs: Session, live_policy: str) -> set[tuple[str, str, str]]:' src/value/shadow.py   # 142:
  grep -nF '            regime_stepped=self.ctx.regime_stepped and tonight,' src/value/shadow.py   # 445:
  grep -nF '    out.opened = open_signals(vs, cards, tags, atr, live_policy=live, now=now)' src/value/shadow.py   # 803:
  grep -nF '            tripped = claude_verdicts.check_breaker(vs, vcfg, claude_night, started)' src/value/service.py   # 303:
  grep -nF '                regime_stepped=stepped,' src/value/service.py   # 322:
  grep -nF '    rebases: int = 0,' src/value/report.py   # 369:
  grep -nF '        now: dict[tuple[str, str], float | None] = {}' scripts/value_report.py   # 133:
  ```

**Section exit:** three task commits plus the section's final `docs(plan)` commit; full gate green
with pytest = baseline + 63 (47 + 12 + 3 + 1); protected-file diff empty; `py_compile` of
`scripts/run_value.py` and `scripts/value_report.py` silent; `git status --short` clean.

---

### Task 7: Kill triggers evaluated by Python, and trigger 6

**Files:**
- Create: `src/value/kill_triggers.py`, `tests/test_value_kill_triggers.py`
- Modify: `src/value/reevaluate.py` (module docstring; `TriggerKind`; `session_triggers`'s
  signature, docstring and the trigger before `if regime_stepped:`),
  `src/value/claude_verdicts.py` (imports; append `update_kill_triggers`),
  `tests/test_value_reevaluate.py` (append)

**Interfaces:**
- Consumes: the scorecard's `revenue_growth_1y`, `gross_margin_latest`, `fcf_ttm` metrics and the
  `health.net_debt_to_ebitda` / `health.dilution` checks; `ValueKillTriggerRow`, `ValueClaudeFactRow`.
- Produces: `kill_triggers.check(kind, threshold, card, *, near_pct, facts_since) -> KillCheck(kind,
  threshold, actual, state)` with `KillCheck.line()`; `reevaluate.TriggerKind` gains `"kill"`;
  `session_triggers(..., kill: list[str] | None = None)` adds a Minor `kill` trigger;
  `claude_verdicts.update_kill_triggers(vs, cards, cfg, as_of) -> dict[symbol, list[str]]`.

Steady Co's newest year: revenue grew 1600 / 1420 − 1 = 12.68%, gross margin 60%; so a
`revenue_growth_below` at 15 has fired, at 12 is near (12.68 ≤ 12 + 1.2), at 5 is far (band 1
point); `gross_margin_below` at 56 is near (60 ≤ 61.6).

- [ ] **Step 1: Write the failing tests** — create `tests/test_value_kill_triggers.py`:

```python
"""Claude's kill triggers, evaluated by Python (value book spec §8.4, §7.1 trigger 6)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import select

import src.value.store as store
from src.common.config import get_config
from src.value.claude_verdicts import update_kill_triggers
from src.value.kill_triggers import check
from src.value.scorecard import build_scorecard
from src.value.store import ValueClaudeFactRow, ValueKillTriggerRow, init_value_db, value_session
from tests.value_fixtures import inputs

CFG = get_config().value
CARD = build_scorecard(inputs(close=30.0), CFG)  # revenue growth 12.68%, gross margin 60%
NOW = datetime(2026, 11, 2, 15, 0)


@pytest.mark.parametrize(
    ("kind", "threshold", "state"),
    [
        ("revenue_growth_below", 15.0, "fired"),  # 12.68 < 15
        ("revenue_growth_below", 12.0, "near"),  # 12.68 <= 12 + 10% x 12 = 13.2
        ("revenue_growth_below", 5.0, "far"),  # band 10% x 10 = 1 point: 6.0
        ("gross_margin_below", 56.0, "near"),  # 60 <= 56 + 5.6
        ("gross_margin_below", 50.0, "far"),
        ("dilution_above", 1.0, "far"),  # the share count fell: dilution is negative
        ("fcf_ttm_negative", None, "far"),  # 300 of FCF
        ("guidance_cut", None, "far"),
    ],
)
def test_each_predicate_on_tonights_scorecard(kind, threshold, state) -> None:
    assert check(kind, threshold, CARD, near_pct=10.0, facts_since=set()).state == state


def test_above_predicates_and_unknown_numbers() -> None:
    card = CARD.model_copy(
        update={
            "health_checks": [
                c.model_copy(update={"actual": 2.8}) if c.id == "health.net_debt_to_ebitda" else c
                for c in CARD.health_checks
            ]
        }
    )
    assert (
        check("net_debt_to_ebitda_above", 3.0, card, near_pct=10.0, facts_since=set()).state
        == "near"
    )
    assert (
        check("net_debt_to_ebitda_above", 2.5, card, near_pct=10.0, facts_since=set()).state
        == "fired"
    )
    blank = CARD.model_copy(update={"metrics": {**CARD.metrics, "gross_margin_latest": None}})
    out = check("gross_margin_below", 50.0, blank, near_pct=10.0, facts_since=set())
    assert out.state == "unknown" and out.actual is None  # unknown is never zero


def test_a_fact_based_trigger_fires_on_a_grounded_fact_after_it_was_chosen() -> None:
    assert (
        check("customer_loss", None, CARD, near_pct=10.0, facts_since={"customer_loss"}).state
        == "fired"
    )


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def test_the_night_records_each_trigger_and_hands_trigger_6_its_lines(value_db) -> None:
    with value_session() as s:
        for kind, threshold in (("revenue_growth_below", 12.0), ("gross_margin_below", 50.0)):
            s.add(
                ValueKillTriggerRow(
                    read_id=1, symbol="STDY", kind=kind, threshold=threshold, chosen_at=NOW
                )
            )
        s.add(ValueKillTriggerRow(read_id=1, symbol="STDY", kind="guidance_cut", chosen_at=NOW))
        s.add(
            ValueClaudeFactRow(
                read_id=2,
                symbol="STDY",
                accn="a",
                kind="guidance_cut",
                quote="we now expect",
                grounded=True,
                created_at=NOW,
            )
        )
    with value_session() as s:
        near = update_kill_triggers(s, [CARD], CFG, date(2026, 11, 2))
    assert near == {"STDY": ["revenue_growth_below near (12.68 vs 12)", "guidance_cut fired (n/a)"]}
    with value_session() as s:
        rows = {r.kind: r for r in s.scalars(select(ValueKillTriggerRow))}
        assert rows["gross_margin_below"].last_state == "far"
        assert rows["guidance_cut"].fired_on == date(2026, 11, 2)
```

  …and append to `tests/test_value_reevaluate.py`:

```diff
diff --git a/tests/test_value_reevaluate.py b/tests/test_value_reevaluate.py
index e70568a..581f84d 100644
--- a/tests/test_value_reevaluate.py
+++ b/tests/test_value_reevaluate.py
@@ -235,3 +235,26 @@ def test_an_unknown_low_means_no_shock_level() -> None:
     up = [rv.Trigger(kind="move", severity="major", direction="up")]
     assert rv.plan_actions(down, bar, before, CFG) is None
     assert rv.plan_actions(up, bar, before, CFG) is None
+
+
+def test_trigger_6_is_minor_and_moves_no_level() -> None:
+    """Spec §7.1 trigger 6: a Claude-chosen kill trigger near firing opens a re-evaluation; like
+    news it is plain data, and plan_actions changes nothing for it."""
+    from src.value.reevaluate import plan_actions, session_triggers
+
+    day = date(2026, 4, 6)
+    fired = session_triggers(
+        day=day,
+        after=date(2026, 4, 3),
+        move=None,
+        filings=[],
+        earnings=[],
+        news=None,
+        regime_stepped=False,
+        last_reevaluation=day,
+        cfg=CFG,
+        kill=["revenue_growth_below near (4.20 vs 4)"],
+    )
+    assert [(t.kind, t.severity) for t in fired] == [("kill", "minor")]
+    assert "revenue_growth_below near" in fired[0].detail
+    assert plan_actions(fired, DayBar(date=day, close=10.0, low=9.0), None, CFG) is None
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_kill_triggers.py tests/test_value_reevaluate.py`
  Expected: FAIL — `ModuleNotFoundError: No module named 'src.value.kill_triggers'` and
  `TypeError: session_triggers() got an unexpected keyword argument 'kill'`.

- [ ] **Step 3: The evaluation** — create `src/value/kill_triggers.py`:

```python
"""Claude's kill-triggers, evaluated by Python (spec §8.4, §7.1 trigger 6). Pure: no I/O.

Claude picks up to five predicates from a fixed menu; Python bounds each threshold when the read
is accepted and evaluates every active one on each night's scorecard. A predicate is ``fired``
past its threshold, ``near`` within ``kill_near_pct`` of it (trigger 6, Minor: it opens a
re-evaluation, it never moves a level), ``far`` otherwise, ``unknown`` when the number is missing
(unknown is never zero). The fact-based kinds (``guidance_cut``, ``customer_loss``) fire when a
grounded filing fact of that kind lands after the trigger was chosen; they have no ``near``, and
neither has ``fcf_ttm_negative``, whose threshold is zero.

Units: percent for revenue growth, dilution and gross margin; a multiple for net debt / EBITDA;
dollars (millions, as filed) for TTM FCF.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.value.schemas import ValueScorecard

KillState = Literal["fired", "near", "far", "unknown"]
ABOVE = ("net_debt_to_ebitda_above", "dilution_above")
BELOW = ("revenue_growth_below", "gross_margin_below")
FACT_BASED = ("guidance_cut", "customer_loss")
_BELOW_BAND_FLOOR = 10.0  # a "below" threshold near zero still gets a band of p% of 10 points


@dataclass(frozen=True, slots=True)
class KillCheck:
    kind: str
    threshold: float | None
    actual: float | None
    state: KillState

    def line(self) -> str:
        actual = "n/a" if self.actual is None else f"{self.actual:.2f}"
        threshold = "" if self.threshold is None else f" vs {self.threshold:g}"
        return f"{self.kind} {self.state} ({actual}{threshold})"


def _check_actual(card: ValueScorecard, check_id: str) -> float | None:
    return next((c.actual for c in card.health_checks if c.id == check_id), None)


def actual_for(kind: str, card: ValueScorecard) -> float | None:
    m = card.metrics
    if kind == "revenue_growth_below":
        v = m.get("revenue_growth_1y")
        return None if v is None else v * 100.0
    if kind == "gross_margin_below":
        v = m.get("gross_margin_latest")
        return None if v is None else v * 100.0
    if kind == "fcf_ttm_negative":
        return m.get("fcf_ttm")
    if kind == "net_debt_to_ebitda_above":
        return _check_actual(card, "health.net_debt_to_ebitda")
    if kind == "dilution_above":
        return _check_actual(card, "health.dilution")
    return None


def check(
    kind: str,
    threshold: float | None,
    card: ValueScorecard,
    *,
    near_pct: float,
    facts_since: set[str],
) -> KillCheck:
    """One predicate on tonight's scorecard. *facts_since*: the kinds of grounded facts that
    landed for the name since the trigger was chosen."""
    if kind in FACT_BASED:
        return KillCheck(kind, None, None, "fired" if kind in facts_since else "far")
    actual = actual_for(kind, card)
    if actual is None:
        return KillCheck(kind, threshold, None, "unknown")
    p = near_pct / 100.0
    if kind == "fcf_ttm_negative":
        return KillCheck(kind, 0.0, actual, "fired" if actual < 0 else "far")
    if threshold is None:
        return KillCheck(kind, None, actual, "unknown")
    if kind in ABOVE:
        if actual > threshold:
            state: KillState = "fired"
        elif actual >= threshold * (1.0 - p):
            state = "near"
        else:
            state = "far"
        return KillCheck(kind, threshold, actual, state)
    if actual < threshold:
        state = "fired"
    elif actual <= threshold + p * max(abs(threshold), _BELOW_BAND_FLOOR):
        state = "near"
    else:
        state = "far"
    return KillCheck(kind, threshold, actual, state)
```

- [ ] **Step 4: Trigger 6 and the nightly update** — apply:

```diff
diff --git a/src/value/claude_verdicts.py b/src/value/claude_verdicts.py
index 0ce32ab..8917394 100644
--- a/src/value/claude_verdicts.py
+++ b/src/value/claude_verdicts.py
@@ -25,10 +25,12 @@ from sqlalchemy.orm import Session
 
 from src.common.config import ValueCfg, ValueRulesCfg
 from src.common.value_ai_types import AnalystResult, Drivers, KillTrigger
+from src.value import kill_triggers
 from src.value.claude_valuation import ClaudeValue, claude_fair_value
 from src.value.effective import ClaudeOpinion, Effective, effective
 from src.value.schemas import LISTS, ValueScorecard
 from src.value.store import (
+    ValueClaudeFactRow,
     ValueClaudeNoteRow,
     ValueClaudeReadRow,
     ValueClaudeStateRow,
@@ -346,3 +348,42 @@ def persist_effective(
                 for key, value in values.items():
                     setattr(row, key, value)
     return out
+
+
+def update_kill_triggers(
+    vs: Session, cards: list[ValueScorecard], cfg: ValueCfg, as_of: date
+) -> dict[str, list[str]]:
+    """Evaluate every active kill trigger on tonight's scorecard (spec §8.4) and record the
+    result on its row. Returns, per name, the lines of the triggers that are near or fired:
+    trigger 6's input for tonight's re-evaluations (spec §7.1)."""
+    by_symbol = {c.symbol: c for c in cards}
+    out: dict[str, list[str]] = {}
+    rows = vs.scalars(
+        select(ValueKillTriggerRow).where(
+            ValueKillTriggerRow.active.is_(True),
+            ValueKillTriggerRow.symbol.in_(list(by_symbol)),
+        )
+    ).all()
+    for t in rows:
+        facts = set(
+            vs.scalars(
+                select(ValueClaudeFactRow.kind).where(
+                    ValueClaudeFactRow.symbol == t.symbol,
+                    ValueClaudeFactRow.grounded.is_(True),
+                    ValueClaudeFactRow.created_at >= t.chosen_at,
+                )
+            )
+        )
+        c = kill_triggers.check(
+            t.kind,
+            t.threshold,
+            by_symbol[t.symbol],
+            near_pct=cfg.rules.claude.kill_near_pct,
+            facts_since=facts,
+        )
+        t.last_state, t.last_actual, t.last_checked = c.state, c.actual, as_of
+        if c.state == "fired" and t.fired_on is None:
+            t.fired_on = as_of
+        if c.state in ("near", "fired"):
+            out.setdefault(t.symbol, []).append(c.line())
+    return out
diff --git a/src/value/reevaluate.py b/src/value/reevaluate.py
index 4a9ae0a..7105f42 100644
--- a/src/value/reevaluate.py
+++ b/src/value/reevaluate.py
@@ -2,9 +2,10 @@
 whether it joins the open one, and what it does to the plan. Pure: no I/O. Python decides all of
 it; Claude decides none (Part 4's review only ever reads the record).
 
-Triggers 1-5, 7 and 8 are here. Trigger 6 (a Claude kill-trigger within 10% of firing) needs
-Claude's kill-triggers and arrives with Part 4. Trigger 5 (news volume) and the earnings dates
-arrive as plain data; on their own they only open a re-evaluation: no stop and no exit reads them.
+Triggers 1-8 are here. Trigger 6 (a Claude-chosen kill-trigger within 10% of firing, Part 4) is
+evaluated by Python (``src/value/kill_triggers.py``) and, like trigger 5 (news volume) and the
+earnings dates, arrives as plain data; on their own they only open a re-evaluation: no stop and no
+exit reads them.
 """
 
 from __future__ import annotations
@@ -20,7 +21,7 @@ from src.value.exits import Reeval
 from src.value.residuals import Move
 
 Severity = Literal["minor", "major"]
-TriggerKind = Literal["move", "drift", "earnings", "filing", "news", "regime", "quiet"]
+TriggerKind = Literal["move", "drift", "earnings", "filing", "news", "kill", "regime", "quiet"]
 PERIODIC = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
 EIGHT_K = ("8-K", "8-K/A")
 _RANK: dict[str, int] = {"minor": 1, "major": 2}
@@ -45,10 +46,12 @@ def session_triggers(
     regime_stepped: bool,
     last_reevaluation: date,
     cfg: ValueReevaluationCfg,
+    kill: list[str] | None = None,
 ) -> list[Trigger]:
     """Every trigger that fires on *day* for one position. *after* is the last session already
     checked (a filing or report dated after it and on or before *day* is new);
-    *last_reevaluation* is the last re-evaluation's session, or the entry date."""
+    *last_reevaluation* is the last re-evaluation's session, or the entry date. *kill*: the
+    name's kill triggers near or past firing tonight (trigger 6)."""
     out: list[Trigger] = []
     major_move = False
     if move is not None and move.z is not None:
@@ -129,6 +132,12 @@ def session_triggers(
                 detail=f"{news.last_24h} items in 24h vs a daily median of {news.daily_median_30d:g}",
             )
         )
+    if kill:
+        out.append(
+            Trigger(
+                kind="kill", severity="minor", detail="Claude's kill trigger: " + "; ".join(kill)
+            )
+        )
     if regime_stepped:
         out.append(Trigger(kind="regime", severity="minor", detail="the market regime stepped"))
     if (day - last_reevaluation).days >= cfg.quiet_days:
```

- [ ] **Step 5: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_kill_triggers.py tests/test_value_reevaluate.py tests/test_value_claude.py tests/test_value_fence.py`
  Expected: PASS.

- [ ] **Step 6: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the five touched files;
  `.venv/bin/mypy src/value/kill_triggers.py src/value/reevaluate.py src/value/claude_verdicts.py`.

  ```bash
  git add src/value/kill_triggers.py src/value/reevaluate.py src/value/claude_verdicts.py tests/test_value_kill_triggers.py tests/test_value_reevaluate.py
  git commit -m "feat(value): Claude's kill triggers evaluated by Python, and trigger 6 (spec 8.4, 7.1)"
  ```

---

### Task 8: The Claude track in the shadow record

**Files:**
- Modify: `src/value/shadow.py` (module docstring; imports; the constants; `ReevalContext`;
  `day_facts`; `blocking_keys`; `_entry`; a new `open_claude_signals` after `open_signals`;
  `_Reevaluator.triggers`; `step_legs`'s signature and its `facts`; `process`),
  `src/value/service.py` (the kill triggers after the breaker; `opinions` and `kill` to
  `shadow.process`), `tests/test_value_shadow.py` (append)

**Interfaces:**
- Consumes: Task 5's `opinions`, Task 7's `update_kill_triggers`, `effective.effective`.
- Produces: `shadow.CLAUDE = "claude"`, `shadow.Opinions`, `ReevalContext.kill`,
  `day_facts(card, list_name, going_concern=None, effective_fair_value=None)`,
  `blocking_keys(vs, live_policy, track=BASELINE)`, `_entry(..., *, track, effective_fair_value,
  margin_of_safety, verdict)`, `open_claude_signals(vs, cards, tags, atr, opinions, *, live_policy,
  review_above_pct, now) -> int`, `step_legs(..., claude_fv=None)`, `process(..., opinions=None,
  kill=None)` (its summary's `opened` gains `"claude"` while reads are on).

The two leg tests pin ruling 7 and spec §7: DEAR at 45 is deep-value WAIT for Python (ceiling
35.14); Claude READY at 70 makes the ceiling 52.50, so the claude track enters it with an effective
fair value of 70 and a margin of (70 − 45) / 70; its `value` leg sells half at the close of 71 (at or
above 70), and not at 50, though 50 is above Python's 46.85 (only a re-mark session can sell on
Python's value there).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_value_shadow.py`:

```diff
diff --git a/tests/test_value_shadow.py b/tests/test_value_shadow.py
index 64afb06..8d44c0c 100644
--- a/tests/test_value_shadow.py
+++ b/tests/test_value_shadow.py
@@ -565,3 +565,83 @@ def test_an_entry_whose_legs_all_closed_on_a_fill_is_not_rebased_next_night(valu
         assert not list(
             s.scalars(select(ValueShadowEventRow).where(ValueShadowEventRow.kind == "rebase"))
         )
+
+
+def _ops(entries: dict[tuple[str, str], tuple[str, float]]):
+    from src.value.claude_valuation import ClaudeValue
+    from src.value.effective import ClaudeOpinion
+
+    return {
+        key: (ClaudeOpinion(verdict, fv, i), ClaudeValue(fv))
+        for i, (key, (verdict, fv)) in enumerate(entries.items())
+    }
+
+
+def test_the_claude_track_enters_on_the_effective_verdict(value_db) -> None:
+    """Spec §6.7, §6.8: the claude track enters trading names whose effective verdict, with
+    Claude's opinion applied, is READY; evidence names count toward the baseline only."""
+    dear = ready("DEAR", 45.0)  # Python: deep WAIT (ceiling 35.14), growth READY
+    ops = _ops(
+        {
+            ("DEAR", "deep_value"): ("READY", 70.0),  # 45 <= 70 x 0.75 = 52.50: READY
+            ("DEAR", "quality_growth"): ("NO", 80.0),  # Claude decides: no entry
+        }
+    )
+    tags = {"DEAR": "trading", "EVID": "evidence"}
+    with value_session() as s:
+        args = dict(live_policy="value", review_above_pct=60.0, now=NOW)
+        assert shadow.open_claude_signals(s, [dear, ready("EVID")], tags, {}, ops, **args) == 1
+        assert shadow.open_claude_signals(s, [dear], tags, {}, ops, **args) == 0  # blocked
+    with value_session() as s:
+        row = s.scalars(select(ValueShadowRow)).one()
+        assert (row.track, row.list_name, row.verdict) == ("claude", "deep_value", "READY")
+        assert row.fair_value == pytest.approx(46.853626592284414)  # Python's, for the exits
+        assert row.effective_fair_value == 70.0
+        assert row.margin_of_safety == pytest.approx((70.0 - 45.0) / 70.0)
+    assert _open([dear], tags={"DEAR": "trading"})["ready"] == 1  # the baseline: growth only
+
+
+def test_a_claude_track_leg_sells_half_at_claudes_fair_value_only(value_db) -> None:
+    """Spec §7: the half-sale reads the effective fair value; the close above Python's 46.85
+    sells nothing on its own (no re-mark), the close at Claude's 70 sells half."""
+    dear = ready("DEAR", 45.0)
+    ops = _ops({("DEAR", "deep_value"): ("READY", 70.0)})
+    with value_session() as s:
+        shadow.open_claude_signals(
+            s,
+            [dear],
+            {"DEAR": "trading"},
+            {},
+            ops,
+            live_policy="value",
+            review_above_pct=60.0,
+            now=NOW,
+        )
+    market = {"DEAR": bars([45.0, 46.0, 50.0, 71.0]), "SPY": bars([500.0] * 4)}
+    with value_session() as s:
+        shadow.fill_pending(s, market, CFG)
+    with value_session() as s:
+        shadow.step_legs(
+            s,
+            market,
+            {"DEAR": dear},
+            CFG,
+            as_of=SESSIONS[3],
+            claude_fv={("DEAR", "deep_value"): 70.0},
+        )
+    with value_session() as s:
+        halves = [
+            (e.policy, e.day) for e in s.scalars(select(ValueShadowEventRow)) if e.kind == "half"
+        ]
+    assert ("value", SESSIONS[3]) in halves and all(day == SESSIONS[3] for _, day in halves)
+
+
+def test_a_kill_trigger_near_firing_opens_a_reevaluation_tonight_only(value_db) -> None:
+    _entered()
+    market = {"STDY": bars([30.0, 31.0, 31.2, 31.1]), "SPY": bars([500.0] * 4)}
+    ctx = shadow.ReevalContext(kill={"STDY": ["gross_margin_below near (60.00 vs 56)"]})
+    with value_session() as s:
+        shadow.step_legs(s, market, {}, CFG, as_of=SESSIONS[3], context=ctx)
+    assert {r[2] for r in _reevaluations()} == {SESSIONS[3]}
+    assert _reevaluations()[0][4] == ["kill"]
+    assert all(not leg.pending for leg in _legs("main").values())  # it moves no level
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_shadow.py`
  Expected: FAIL — `AttributeError: module 'src.value.shadow' has no attribute 'open_claude_signals'`
  and `TypeError: ReevalContext.__init__() got an unexpected keyword argument 'kill'`.

- [ ] **Step 3: The record** — apply:

```diff
diff --git a/src/value/service.py b/src/value/service.py
index b2670c1..365c489 100644
--- a/src/value/service.py
+++ b/src/value/service.py
@@ -301,6 +301,7 @@ def run_nightly(
                 review_above_pct=review,
             )
             tripped = claude_verdicts.check_breaker(vs, vcfg, claude_night, started)
+            kill = claude_verdicts.update_kill_triggers(vs, cards, vcfg, plan.as_of)
             queued = plan_auto_reads(vs, started, vcfg) if vcfg.claude.enabled else {}
             stepped = reevaluate.regime_stepped(
                 previous_regime(vs), regime, vcfg.rules.reevaluation
@@ -320,6 +321,8 @@ def run_nightly(
                 earnings=recent_earnings,
                 news=news,
                 regime_stepped=stepped,
+                opinions=ops,
+                kill=kill,
             )
             verdicts = {
                 name: dict(Counter(c.verdict_for(name) for c in cards))
diff --git a/src/value/shadow.py b/src/value/shadow.py
index b9a4155..3b9f3fc 100644
--- a/src/value/shadow.py
+++ b/src/value/shadow.py
@@ -2,8 +2,14 @@
 fixed-horizon returns against SPY, and the ranked monthly record. Writes value.db only; reads
 research.db through the neutral read-only loader.
 
-Part 2 runs Python's **baseline** track alone; Part 4 adds Claude's track beside it. Nothing here
-can place, size or gate an order: every row is hypothetical.
+Two tracks (spec §6.8, §12): Python's **baseline** and, from Part 4, **claude**: the trading
+universe's names entered on the effective verdict with Claude's opinions applied (an Ollama
+verdict never is), whatever the breaker or the live switch say, so the record measures Claude's
+judgement for the go-live review. A Claude-track leg reads Claude's fair value (recomputed
+tonight) for its half-sale only; every exit that sends without a tap reads Python's (spec §7).
+Controls are entered on the baseline track only, and the claude track only while
+``value.claude.enabled`` is on. Nothing here can place, size or gate an order:
+every row is hypothetical.
 
 The rules this module applies (the plan's rulings say why):
 - a READY signal on the night of session D enters at the open of the next session after D;
@@ -45,6 +51,8 @@ from src.common.value_inputs import (
 )
 from src.common.value_types import DayBar, FilingEvent, NewsVolume
 from src.value import reevaluate
+from src.value.claude_valuation import ClaudeValue
+from src.value.effective import ClaudeOpinion, effective
 from src.value.exits import (
     POLICIES,
     DayFacts,
@@ -69,7 +77,9 @@ from src.value.store import (
 )
 
 BENCHMARK = "SPY"
-TRACK = "baseline"
+TRACK = BASELINE = "baseline"
+CLAUDE = "claude"
+Opinions = dict[tuple[str, str], tuple[ClaudeOpinion, ClaudeValue]]
 GRACE_SESSIONS = 5
 SHADOW_UNIVERSES = ("trading", "evidence")
 HELD = ("pending", "open", "rebase_needed")  # entries the record still carries
@@ -103,6 +113,7 @@ class ReevalContext:
     news: dict[str, NewsVolume] = field(default_factory=dict)
     regime_stepped: bool = False
     etf_for: dict[str, str] = field(default_factory=dict)  # symbol -> its sector ETF
+    kill: dict[str, list[str]] = field(default_factory=dict)  # trigger 6, tonight only
 
 
 def _actual(card: ValueScorecard, check_id: str) -> float | None:
@@ -121,16 +132,20 @@ def _missing_components(card: ValueScorecard, check_id: str) -> int:
 
 
 def day_facts(
-    card: ValueScorecard | None, list_name: str, going_concern: bool | None = None
+    card: ValueScorecard | None,
+    list_name: str,
+    going_concern: bool | None = None,
+    effective_fair_value: float | None = None,
 ) -> DayFacts | None:
-    """The night's Python numbers for one list (baseline track: effective = Python's)."""
+    """The night's Python numbers for one list. The effective fair value is Python's on the
+    baseline track and Claude's (recomputed tonight) on the claude track, when it has one."""
     if card is None:
         return None
     ev = card.lists.get(list_name)
     fv = ev.fair_value if ev is not None else None
     return DayFacts(
         python_fair_value=fv,
-        effective_fair_value=fv,
+        effective_fair_value=effective_fair_value if effective_fair_value is not None else fv,
         latest_accn=card.fingerprint.latest_accn,
         piotroski=_actual(card, "health.piotroski"),
         piotroski_missing=_missing_components(card, "health.piotroski"),
@@ -139,12 +154,14 @@ def day_facts(
     )
 
 
-def blocking_keys(vs: Session, live_policy: str) -> set[tuple[str, str, str]]:
-    """(kind, list, symbol) keys that may not enter again tonight."""
+def blocking_keys(
+    vs: Session, live_policy: str, track: str = BASELINE
+) -> set[tuple[str, str, str]]:
+    """(kind, list, symbol) keys of *track* that may not enter again tonight."""
     out: set[tuple[str, str, str]] = set()
     rows = vs.scalars(
         select(ValueShadowRow).where(
-            ValueShadowRow.track == TRACK,
+            ValueShadowRow.track == track,
             ValueShadowRow.status.in_(HELD),
         )
     )
@@ -172,10 +189,17 @@ def _entry(
     universe: str,
     atr14: float | None,
     now: datetime,
+    *,
+    track: str = BASELINE,
+    effective_fair_value: float | None = None,
+    margin_of_safety: float | None = None,
+    verdict: str | None = None,
 ) -> ValueShadowRow:
+    """A pending entry. On the claude track *verdict*, *effective_fair_value* and
+    *margin_of_safety* are the effective ones; ``fair_value`` is always Python's."""
     ev = card.lists[list_name]
     return ValueShadowRow(
-        track=TRACK,
+        track=track,
         kind=kind,
         list_name=list_name,
         symbol=card.symbol,
@@ -183,12 +207,14 @@ def _entry(
         signal_date=card.as_of,
         status="pending",
         status_detail="",
-        verdict=ev.verdict,
+        verdict=verdict or ev.verdict,
         signal_close=card.price,
         atr14=atr14,
         fair_value=ev.fair_value,
-        effective_fair_value=ev.fair_value,
-        margin_of_safety=ev.margin_of_safety,
+        effective_fair_value=effective_fair_value
+        if effective_fair_value is not None
+        else ev.fair_value,
+        margin_of_safety=margin_of_safety if margin_of_safety is not None else ev.margin_of_safety,
         required_mos_pct=ev.required_mos_pct,
         fv_accn=card.fingerprint.latest_accn,
         fingerprint_key=card.fingerprint.key(),
@@ -253,6 +279,52 @@ def open_signals(
     return counts
 
 
+def open_claude_signals(
+    vs: Session,
+    cards: list[ValueScorecard],
+    tags: dict[str, str],
+    atr: dict[str, float | None],
+    opinions: Opinions,
+    *,
+    live_policy: str,
+    review_above_pct: float,
+    now: datetime,
+) -> int:
+    """Tonight's claude-track READY signals: trading-universe names whose effective verdict,
+    with Claude's opinion applied, is READY (an unread name enters on Python's READY, as the
+    effective verdict would). Evidence-universe names count toward the baseline only (§12)."""
+    blocked = blocking_keys(vs, live_policy, CLAUDE)
+    opened = 0
+    for card in cards:
+        if tags.get(card.symbol) != "trading" or card.data_quality != "pass":
+            continue
+        for name in LISTS:
+            found = opinions.get((card.symbol, name))
+            eff = effective(
+                card, name, found[0] if found else None, review_above_pct=review_above_pct
+            )
+            key = ("ready", name, card.symbol)
+            if eff.verdict != "READY" or key in blocked or card.lists.get(name) is None:
+                continue
+            vs.add(
+                _entry(
+                    card,
+                    name,
+                    "ready",
+                    "trading",
+                    atr.get(card.symbol),
+                    now,
+                    track=CLAUDE,
+                    effective_fair_value=eff.fair_value,
+                    margin_of_safety=eff.margin_of_safety,
+                    verdict=eff.verdict,
+                )
+            )
+            blocked.add(key)
+            opened += 1
+    return opened
+
+
 def load_bars(rs: Session, symbols: set[str], as_of: date) -> dict[str, list[DayBar]]:
     return {s: build_day_bars(read_bars(rs, s, as_of)) for s in sorted(symbols)}
 
@@ -445,6 +517,7 @@ class _Reevaluator:
             regime_stepped=self.ctx.regime_stepped and tonight,
             last_reevaluation=self.last_day,
             cfg=self.cfg.rules.reevaluation,
+            kill=self.ctx.kill.get(sym) if tonight else None,
         )
 
     def record(
@@ -502,6 +575,7 @@ def step_legs(
     as_of: date | None = None,
     context: ReevalContext | None = None,
     now: datetime | None = None,
+    claude_fv: dict[tuple[str, str], float | None] | None = None,
 ) -> tuple[int, int]:
     """Run every open leg over the sessions it has not seen. Tonight's facts are read on the
     session dated *as_of* only (the name's newest bar when None, review M1). With a *context*,
@@ -533,6 +607,7 @@ def step_legs(
             card,
             row.list_name,
             None if context is None else context.going_concern.get(row.symbol),
+            (claude_fv or {}).get((row.symbol, row.list_name)) if row.track == CLAUDE else None,
         )
         states = {leg.id: LegState.model_validate_json(leg.state_json) for leg in legs}
         firsts = [leg.last_step for leg in legs]
@@ -758,11 +833,15 @@ def process(
     earnings: dict[str, list[date]] | None = None,
     news: dict[str, NewsVolume] | None = None,
     regime_stepped: bool = False,
+    opinions: Opinions | None = None,
+    kill: dict[str, list[str]] | None = None,
 ) -> ShadowSummary:
     """One night of the shadow record, in order: fill yesterday's signals, rebase what the
     provider rewrote, run the legs with §7.1's re-evaluations, mark the horizons, close what is
-    finished, open tonight's signals, then the ranked record. *earnings* (each name's recent
-    report dates) and *news* (trigger 5) are plain data from the value process."""
+    finished, open tonight's signals (both tracks), then the ranked record. *earnings* (each
+    name's recent report dates) and *news* (trigger 5) are plain data from the value process;
+    *opinions* are Claude's (Part 4: the claude track and its legs' fair values) and *kill* its
+    kill triggers near firing tonight (trigger 6)."""
     out = ShadowSummary()
     by_symbol = {c.symbol: c for c in cards}
     live = cfg.rules.exits.live_policy
@@ -792,15 +871,35 @@ def process(
         news=news or {},
         regime_stepped=regime_stepped,
         etf_for=etf_for,
+        kill=kill or {},
     )
+    ops = opinions or {}
     out.events, out.reevaluations = step_legs(
-        vs, market, by_symbol, cfg, as_of=as_of, context=context, now=now
+        vs,
+        market,
+        by_symbol,
+        cfg,
+        as_of=as_of,
+        context=context,
+        now=now,
+        claude_fv={k: v[1].fair_value for k, v in ops.items()},
     )
     out.marked = mark_horizons(vs, market)
     vs.flush()
     out.closed = close_finished(vs, as_of)
     vs.flush()
     out.opened = open_signals(vs, cards, tags, atr, live_policy=live, now=now)
+    if cfg.claude.enabled:  # no claude track while Claude is not reading: it would copy baseline
+        out.opened["claude"] = open_claude_signals(
+            vs,
+            cards,
+            tags,
+            atr,
+            ops,
+            live_policy=live,
+            review_above_pct=cfg.rules.margin_of_safety.review_above_pct,
+            now=now,
+        )
     out.ranked_formed, out.ranked_closed = run_ranked(
         vs, rs, cards, evidence, as_of=as_of, version=version, digest=digest
     )
```

- [ ] **Step 4: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_shadow.py tests/test_value_service.py tests/test_value_report.py tests/test_value_fence.py`
  Expected: PASS (the existing service test's `opened` is unchanged: reads are off by default, so
  no claude track opens).

- [ ] **Step 5: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the three touched files;
  `.venv/bin/mypy src/value/shadow.py src/value/service.py`.

  ```bash
  git add src/value/shadow.py src/value/service.py tests/test_value_shadow.py
  git commit -m "feat(value): the claude track in the shadow record, and trigger 6 in the night"
  ```

---

### Task 9: The report — Claude beside the baseline

**Files:**
- Modify: `src/value/report.py` (insert `claude_section` before `def render(`; `render`'s
  signature and its tail), `scripts/value_report.py` (docstring; imports; `_entry_view` and
  `_claude_lines` before `load`; `load`), `tests/test_value_report.py` (append)

**Interfaces:**
- Produces: `report.claude_section(baseline, claude, nights, *, breaker, ready_multiple,
  clamp_rate_pct) -> list[str]`; `render(..., claude_lines=None)`; `value_report._entry_view`,
  `_claude_lines(session, ruleset)`.

The pinned lines: the baseline's two trading deep-value entries have 63-session excess returns of
+4% and −2% (mean +1.0%), Claude's +6% and +2% (mean +4.0%); one name and day is shared, one is
Claude's only, one the baseline's only; the evidence entry is excluded. Two nights: 4 Claude READYs
against 2, and the clamp set 1 of 8 values (12%).

- [ ] **Step 1: Write the failing test** — append to `tests/test_value_report.py`:

```diff
diff --git a/tests/test_value_report.py b/tests/test_value_report.py
index c910e69..445bb86 100644
--- a/tests/test_value_report.py
+++ b/tests/test_value_report.py
@@ -315,3 +315,31 @@ def test_a_postmortem_names_the_rebases_that_moved_its_levels() -> None:
     ]
     text = "\n".join(postmortem(e, [], events, None))
     assert f"rebased {D2}: every price level x 0.5" in text
+
+
+def test_claudes_track_is_printed_beside_the_baseline_with_the_breaker_rates() -> None:
+    """Spec §12: per list, both tracks' READY trading entries at 63 sessions, the pairs entered
+    on the same day, and the clamp and READY counts the breaker reads."""
+    from src.value.report import claude_section
+
+    baseline = [
+        _entry(1, D1, 0.05, universe="trading", symbol="AAA"),
+        _entry(2, D2, -0.01, universe="trading", symbol="BBB"),
+        _entry(3, D2, 0.20, universe="evidence", symbol="CCC"),  # evidence: baseline only
+    ]
+    claude = [
+        _entry(4, D1, 0.07, universe="trading", symbol="AAA", track="claude"),
+        _entry(5, D3, 0.03, universe="trading", symbol="DDD", track="claude"),
+    ]
+    nights = [{"ready": 3, "baseline_ready": 2, "values": 8, "clamped": 1}, {"ready": 1}]
+    lines = claude_section(
+        baseline, claude, nights, breaker="ok", ready_multiple=3.0, clamp_rate_pct=25.0
+    )
+    assert lines[1] == (
+        "[deep_value] baseline n 2 excess +1.0% · claude n 2 excess +4.0% · same name and "
+        "day 1 · claude only 1 · baseline only 1"
+    )
+    assert lines[3] == (
+        "Last 2 nights: Claude READY 4 vs the baseline's 2 (breaker at 3x) · the 1.5x clamp "
+        "set 1 of 8 fair values (12%; breaker above 25%) · breaker ok"
+    )
```

- [ ] **Step 2: Run it to see it fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_report.py`
  Expected: FAIL — `ImportError: cannot import name 'claude_section'`.

- [ ] **Step 3: The section and the script** — apply:

```diff
diff --git a/scripts/value_report.py b/scripts/value_report.py
index b3f0376..245d5c2 100644
--- a/scripts/value_report.py
+++ b/scripts/value_report.py
@@ -7,8 +7,9 @@ Reads data/value.db (select only; on a new install it first creates the empty ta
 prints: the survivorship caveat, the
 go-live line of spec §12, fixed-horizon returns against SPY with errors clustered by entry date,
 the three exit policies side by side, the re-evaluations of §7.1 (the re-evaluated plan against the
-original), the ranked monthly record and, with ``--postmortems``, one postmortem per closed
-position. No IBKR connection, no network.
+original), the ranked monthly record, Claude's track beside the baseline's with the breaker's two
+rates (Part 4, §12) and, with ``--postmortems``, one postmortem per closed position. No IBKR
+connection, no network.
 """
 
 from __future__ import annotations
@@ -17,8 +18,10 @@ import argparse
 import json
 
 from sqlalchemy import func, select
+from sqlalchemy.orm import Session
 
 from src.common.config import get_config
+from src.value.claude_verdicts import breaker_state
 from src.value.report import (
     HORIZONS,
     EntryView,
@@ -26,11 +29,13 @@ from src.value.report import (
     LegView,
     RankedView,
     ReevaluationView,
+    claude_section,
     render,
 )
 from src.value.store import (
     ValueRankedRow,
     ValueReevaluationRow,
+    ValueRunRow,
     ValueShadowEventRow,
     ValueShadowLegRow,
     ValueShadowRow,
@@ -40,6 +45,52 @@ from src.value.store import (
 )
 
 
+def _entry_view(r: ValueShadowRow) -> EntryView:
+    return EntryView(
+        id=r.id,
+        track=r.track,
+        kind=r.kind,
+        list_name=r.list_name,
+        symbol=r.symbol,
+        universe=r.universe,
+        status=r.status,
+        signal_date=r.signal_date,
+        entry_date=r.entry_date,
+        entry_price=r.entry_price,
+        fair_value=r.fair_value,
+        margin_of_safety=r.margin_of_safety,
+        ruleset_version=r.ruleset_version,
+        returns={h: getattr(r, f"ret_{h}") for h in HORIZONS},
+        spy={h: getattr(r, f"spy_{h}") for h in HORIZONS},
+        scorecard_json=r.scorecard_json if r.kind == "ready" else "",
+    )
+
+
+def _claude_lines(s: Session, ruleset: str | None) -> list[str]:
+    """Spec §12: Claude's track beside the baseline's, and the breaker's two rates."""
+    vcfg = get_config().value
+    q = select(ValueShadowRow).where(ValueShadowRow.kind == "ready")
+    if ruleset:
+        q = q.where(ValueShadowRow.ruleset_version == ruleset)
+    rows = [_entry_view(r) for r in s.scalars(q)]
+    runs = s.scalars(
+        select(ValueRunRow)
+        .where(ValueRunRow.kind == "nightly")
+        .order_by(ValueRunRow.as_of.desc())
+        .limit(vcfg.claude.breaker.sessions)
+    )
+    nights = [json.loads(r.summary_json or "{}").get("claude", {}) for r in runs]
+    state = breaker_state(s)
+    return claude_section(
+        [e for e in rows if e.track == "baseline"],
+        [e for e in rows if e.track == "claude"],
+        nights,
+        breaker=f"TRIPPED ({state.get('reason', '')})" if state.get("tripped") else "ok",
+        ready_multiple=vcfg.claude.breaker.ready_multiple,
+        clamp_rate_pct=vcfg.claude.breaker.clamp_rate_pct,
+    )
+
+
 def load(args: argparse.Namespace) -> str:
     vcfg = get_config().value
     init_value_db()
@@ -49,27 +100,7 @@ def load(args: argparse.Namespace) -> str:
             q = q.where(ValueShadowRow.universe == args.universe)
         if args.ruleset:
             q = q.where(ValueShadowRow.ruleset_version == args.ruleset)
-        entries = [
-            EntryView(
-                id=r.id,
-                track=r.track,
-                kind=r.kind,
-                list_name=r.list_name,
-                symbol=r.symbol,
-                universe=r.universe,
-                status=r.status,
-                signal_date=r.signal_date,
-                entry_date=r.entry_date,
-                entry_price=r.entry_price,
-                fair_value=r.fair_value,
-                margin_of_safety=r.margin_of_safety,
-                ruleset_version=r.ruleset_version,
-                returns={h: getattr(r, f"ret_{h}") for h in HORIZONS},
-                spy={h: getattr(r, f"spy_{h}") for h in HORIZONS},
-                scorecard_json=r.scorecard_json if r.kind == "ready" else "",
-            )
-            for r in s.scalars(q.order_by(ValueShadowRow.id))
-        ]
+        entries = [_entry_view(r) for r in s.scalars(q.order_by(ValueShadowRow.id))]
         ids = {e.id for e in entries}
         legs = [
             LegView(
@@ -130,6 +161,7 @@ def load(args: argparse.Namespace) -> str:
             .select_from(ValueShadowEventRow)
             .where(ValueShadowEventRow.kind == "rebase", ValueShadowEventRow.shadow_id.in_(ids))
         )
+        claude_lines = _claude_lines(s, args.ruleset)
         now: dict[tuple[str, str], float | None] = {}
         for f in s.scalars(select(ValueTickerFileRow)):
             now[(f.symbol, "deep_value")] = f.fair_value_deep
@@ -145,6 +177,7 @@ def load(args: argparse.Namespace) -> str:
         postmortems=args.postmortems,
         reevaluations=reevaluations,
         rebases=int(rebases or 0),
+        claude_lines=claude_lines,
     )
 
 
diff --git a/src/value/report.py b/src/value/report.py
index c057f9a..a596938 100644
--- a/src/value/report.py
+++ b/src/value/report.py
@@ -355,6 +355,61 @@ def postmortem(
     return lines
 
 
+def claude_section(
+    baseline: list[EntryView],
+    claude: list[EntryView],
+    nights: list[dict[str, int]],
+    *,
+    breaker: str,
+    ready_multiple: float,
+    clamp_rate_pct: float,
+) -> list[str]:
+    """Spec §12, "Claude vs the baseline": per list, the two tracks' READY entries (trading
+    universe) at 63 sessions over SPY, the pairs both tracks entered on the same day, and how
+    often the 1.5x clamp bit and how many READYs Claude made against the baseline over the
+    nights read (*nights*: each nightly run's ``claude`` counts). It is not a pass/fail line;
+    it is what the operator reads before turning ``value.claude.apply_live`` on."""
+    lines = ["-- Claude vs the Python baseline (trading universe, READY, 63 sessions) --"]
+    h = GO_LIVE_HORIZON
+
+    def marked(rows: list[EntryView], list_name: str) -> dict[tuple[str, date], float]:
+        out: dict[tuple[str, date], float] = {}
+        for e in rows:
+            ret, spy = e.returns.get(h), e.spy.get(h)
+            if (
+                e.kind == "ready"
+                and e.universe == "trading"
+                and e.list_name == list_name
+                and e.entry_date is not None
+                and ret is not None
+                and spy is not None
+            ):
+                out[(e.symbol, e.entry_date)] = ret - spy
+        return out
+
+    for list_name in ("deep_value", "quality_growth"):
+        b, c = marked(baseline, list_name), marked(claude, list_name)
+        sb = clustered_mean([(d, x) for (_, d), x in b.items()])
+        sc = clustered_mean([(d, x) for (_, d), x in c.items()])
+        both = sorted(set(b) & set(c))
+        lines.append(
+            f"[{list_name}] baseline n {sb.n} excess {_pct(sb.mean)} · claude n {sc.n} "
+            f"excess {_pct(sc.mean)} · same name and day {len(both)} · claude only "
+            f"{len(set(c) - set(b))} · baseline only {len(set(b) - set(c))}"
+        )
+    ready = sum(n.get("ready", 0) for n in nights)
+    base = sum(n.get("baseline_ready", 0) for n in nights)
+    values = sum(n.get("values", 0) for n in nights)
+    clamped = sum(n.get("clamped", 0) for n in nights)
+    rate = "n/a" if not values else f"{clamped * 100.0 / values:.0f}%"
+    lines.append(
+        f"Last {len(nights)} nights: Claude READY {ready} vs the baseline's {base} (breaker at "
+        f"{ready_multiple:g}x) · the 1.5x clamp set {clamped} of {values} fair values ({rate}; "
+        f"breaker above {clamp_rate_pct:g}%) · breaker {breaker}"
+    )
+    return lines
+
+
 def render(
     entries: list[EntryView],
     legs: list[LegView],
@@ -367,6 +422,7 @@ def render(
     postmortems: bool,
     reevaluations: list[ReevaluationView] | None = None,
     rebases: int = 0,
+    claude_lines: list[str] | None = None,
 ) -> str:
     versions = sorted({e.ruleset_version for e in entries})
     lines = [
@@ -382,6 +438,8 @@ def render(
         "",
         *ranked_section(ranked),
     ]
+    if claude_lines:
+        lines += ["", *claude_lines]
     if postmortems:
         lines += ["", "-- Postmortems (closed positions) --"]
         closed = [e for e in entries if e.kind == "ready" and e.status == "closed"]
```

- [ ] **Step 4: Run it to see it pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_report.py tests/test_value_fence.py` and
  `.venv/bin/python -m py_compile scripts/value_report.py`.
  Expected: PASS; silent.

- [ ] **Step 5: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the three touched files;
  `.venv/bin/mypy src/value/report.py scripts/value_report.py`.

  ```bash
  git add src/value/report.py scripts/value_report.py tests/test_value_report.py
  git commit -m "feat(value): the report prints Claude's track beside the baseline's (spec 12)"
  ```

- [ ] **Section C exit** — the full gate (pytest = baseline + 63), the protected-file diff
  (empty), `py_compile` of `scripts/run_value.py` and `scripts/value_report.py`, `git status --short`
  (clean); fill the Task 9 row and the exit numbers, then:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md
  git commit -m "docs(plan): value book Part 4 Progress log - Section C"
  ```

---

## Section D — Filing reads, grounding, the skill, the docs (Tasks 10–13) · model: sonnet · effort: high

The research worker learns to cut a filing into the sections a filing read needs, for the names a
plain file lists; the value side reads them, queues one filing read per new filing, and keeps a
Claude fact only when the filing says it verbatim; the interactive skill and its one-name JSON land;
the docs, including root `CLAUDE.md`'s second written exception, describe Part 4.

**Spec to read:** §6.9 ("Where the inputs come from"), §8.2 ("Grounded facts"), §8.3 ("Two
depths"), §8.5 ("Spend tokens only on judgement"), §8.6, §18.

**Files the subagent reads:** `src/research/ingest/going_concern.py` (the job pattern and
`html_to_text`), `src/research/ingest/materialize.py` (lines 395–440),
`src/research/ingest/value_universe.py`, `src/research/store/models.py` (lines 190–235),
`src/common/value_keep_fresh.py`, `src/common/value_inputs.py` (lines 1–60, 360–425),
`tests/conftest.py` (lines 75–90), `tests/test_research_submissions.py` (lines 80–115, 167–240: the
fixtures), `src/value/claude_verdicts.py`, `src/value/claude_reads.py`, `src/value/service.py`,
`scripts/run_value.py`, `scripts/value_report.py`, `src/value_ai/prompts.py`, and the four docs'
value-book sections (`CLAUDE.md` lines 105–120 and the value fence; `ARCHITECTURE.md`'s
`src/research/`, `src/common/` and `src/value/` sections; `SETUP.md` §19; `STATUS.md`'s Part 3 entry).

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **D1. Section C is in.** `git log --oneline main..HEAD | wc -l` equals Section C's recorded
  count; `git status --short` is clean.
- [ ] **D2. A green start.** The full gate passes with pytest = baseline + 63; record it.
- [ ] **D3. The code Section D edits is where this plan says** (line numbers after Section C):

  ```bash
  grep -nF 'class SubmissionsStateRow(Base):' src/research/store/models.py   # 223:
  grep -nF '    kind: Mapped[str] = mapped_column(String(32))  # fundamentals|prices|submissions|going_concern' src/research/store/models.py   # 196:
  grep -nF 'from src.research.ingest.going_concern import ingest_going_concern' src/research/ingest/materialize.py   # 36:
  grep -nF '        elif kind == "prices":' src/research/ingest/materialize.py   # 426:
  grep -nF 'from src.common.value_keep_fresh import read_keep_fresh' src/research/ingest/value_universe.py   # 21:
  grep -nF '            if symbol in held:' src/research/ingest/value_universe.py   # 123:
  grep -nF 'KEEP_FRESH_FILE: Path = ROOT / "data" / "value_keep_fresh.json"' src/common/value_keep_fresh.py   # 22:
  grep -nF 'def current_fingerprint_parts(session: Session, symbol: str) -> dict[str, Any]:' src/common/value_inputs.py   # 422:
  grep -nF 'def _value_keep_fresh_in_tmp(monkeypatch, tmp_path_factory):' tests/conftest.py   # 79:
  grep -nF '        "going_concern": 0,' tests/test_value_universe.py   # 172:
  grep -nF 'def _review_text(vs: Session, reevaluation_id: int | None) -> str:' src/value/claude_reads.py   # 283:
  grep -nF '            queued = plan_auto_reads(vs, started, vcfg) if vcfg.claude.enabled else {}' src/value/service.py   # 305:
  grep -nF '    write_keep_fresh(keep_fresh)' src/value/service.py   # 356:
  grep -nF 'def _claude_tick() -> None:' scripts/run_value.py   # 55:
  grep -nF '    for name in ("submissions", "going_concern"):' tests/test_value_fence.py   # 315:
  grep -nF 'def main(argv: list[str] | None = None) -> int:' scripts/value_report.py   # 184:
  grep -nF 'reviewed by a human before the live cutover.' CLAUDE.md   # 116:
  grep -nF '### `src/value/` — The value book (deterministic tier, its own database)' ARCHITECTURE.md   # 1220:
  grep -nF '## 19. The value book, Parts 1–3' SETUP.md   # 2034:
  grep -nF '## Built (2026-10-30 — value book Part 3: re-evaluation and Stage 1b)' STATUS.md   # 350:
  ```

- [ ] **D4. No stray data file.** `ls data/value_filing_reads.json` fails (no such file) in the
  worktree.

**Section exit:** four task commits plus the section's final `docs(plan)` commit; full gate green
with pytest = baseline + 77 (63 + 6 + 6 + 2 + 0); protected-file diff empty; `py_compile` of
`scripts/run_value.py`, `value_feed.py`, `value_report.py`, `value_backtest.py`, `value_dry_run.py`
and `value_claude.py` silent; `git status --short` clean, and **`ls data/value_filing_reads.json`
still fails** (no test wrote it).

---

### Task 10: The research worker's `filing_sections` job

**Files:**
- Create: `src/research/ingest/filing_sections.py`, `tests/test_research_filing_sections.py`
- Modify: `src/research/store/models.py` (insert `FilingSectionRow` before `SubmissionsStateRow`;
  the `IngestJobRow.kind` comment), `src/research/ingest/materialize.py` (import; a branch before
  `elif kind == "prices":`), `src/research/ingest/value_universe.py` (import; docstring; the
  filing-reads set; the counts; the enqueue), `src/common/value_keep_fresh.py` (the second file),
  `src/common/value_inputs.py` (imports; `latest_periodic` and `filing_sections` before
  `current_fingerprint_parts`), `tests/conftest.py` (the redirect), `tests/test_value_universe.py`
  (one count)

**Interfaces:**
- Produces: `FilingSectionRow` (`filing_sections`: `accn`, `cik`, `form`, `section`, `text`,
  `fetched_at`; an empty `section` marks a filing read and found empty);
  `filing_sections.SECTIONS`, `slice_sections(text, form) -> dict[label, text]`,
  `ingest_filing_sections(symbol, cik) -> int`; the job kind `filing_sections`;
  `value_keep_fresh.FILING_READS_FILE`, `write_filing_reads`, `read_filing_reads`;
  `value_inputs.latest_periodic(session, symbols) -> dict[symbol, FilingEvent]`,
  `value_inputs.filing_sections(session, accn) -> list[FilingSection]`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_research_filing_sections.py`:

```python
"""The research worker's ``filing_sections`` job (value book spec §8.2, §8.5): slicing a filing
to the sections a filing read needs, the job, the drain, and the readers on the value side."""

from __future__ import annotations

from datetime import date

import pytest

from src.research.ingest import filing_sections as fs

TOC = "Table of Contents Item 1. Business 3 Item 1A. Risk Factors 9 Item 7. MD&A 30 Item 8. 50 "
BODY = (
    "Item 1. Business We make widgets for hospitals and sell them under contract. "
    "Item 1A. Risk Factors Our largest customer accounted for 18% of revenue. "
    "Item 1B. Unresolved Staff Comments None. "
    "Item 7. Management's Discussion Revenue grew 12% to $1,600 million on volume. "
    "Item 8. Financial Statements ..."
)
TEN_K = f"<html><body><p>{TOC}</p><p>{BODY}</p></body></html>"


def test_a_10k_is_cut_into_items_1_1a_and_7_skipping_the_table_of_contents() -> None:
    out = fs.slice_sections(TOC + BODY, "10-K")
    assert sorted(out) == ["Item 1 Business", "Item 1A Risk Factors", "Item 7 MD&A"]
    assert out["Item 1A Risk Factors"].startswith("Item 1A. Risk Factors Our largest customer")
    assert out["Item 1A Risk Factors"].endswith("18% of revenue.")  # stops at Item 1B
    assert "$1,600 million" in out["Item 7 MD&A"] and "Item 8" not in out["Item 7 MD&A"]


def test_caps_amendments_and_forms_without_items() -> None:
    long = "Item 2. Management's Discussion " + "x" * 30_000 + " Item 3. Quantitative"
    out = fs.slice_sections(long, "10-Q/A")
    assert len(out["Item 2 MD&A"]) == 24_000
    assert fs.slice_sections("Annual report under the MJDS", "40-F") == {}


class _Provider:
    def __init__(self, docs: dict[str, str]) -> None:
        self.docs, self.reads = docs, 0

    def get_filing_text(self, cik: str, accn: str, document: str) -> str:
        self.reads += 1
        return self.docs.get(document, "")


@pytest.fixture()
def research_db(tmp_path, monkeypatch):
    from src.research.store.session import init_research_db

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    return tmp_path / "research.db"


def _index(*rows: tuple[str, str, date, str]) -> None:
    from src.research.store.models import FilingIndexRow, SymbolRow
    from src.research.store.session import research_session

    with research_session() as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001"))
        for accn, form, filed, doc in rows:
            s.add(
                FilingIndexRow(
                    accn=accn, cik="0000000001", form=form, filed=filed, primary_document=doc
                )
            )


def test_the_job_slices_the_newest_periodic_filing_once(research_db, monkeypatch) -> None:
    from src.research.store.models import FilingSectionRow
    from src.research.store.session import research_session

    _index(
        ("0000000001-26-000001", "10-K", date(2026, 2, 10), "k.htm"),
        ("0000000001-26-000002", "8-K", date(2026, 3, 1), "e.htm"),
    )
    provider = _Provider({"k.htm": TEN_K})
    monkeypatch.setattr(fs, "get_filings_provider", lambda: provider)
    assert fs.ingest_filing_sections("STDY", "0000000001") == 3
    assert fs.ingest_filing_sections("STDY", "0000000001") == 0 and provider.reads == 1
    with research_session() as s:
        assert {r.section for r in s.query(FilingSectionRow)} == {
            "Item 1 Business",
            "Item 1A Risk Factors",
            "Item 7 MD&A",
        }


def test_a_missing_document_raises_so_the_drain_retries(research_db, monkeypatch) -> None:
    _index(("0000000001-26-000001", "10-Q", date(2026, 8, 1), "q.htm"))
    monkeypatch.setattr(fs, "get_filings_provider", lambda: _Provider({}))
    with pytest.raises(RuntimeError, match="No document"):
        fs.ingest_filing_sections("STDY", "0000000001")


def test_the_drain_runs_the_job_and_the_sweep_queues_the_files_names(
    research_db, monkeypatch, tmp_path
) -> None:
    from src.common import value_keep_fresh as kf
    from src.research.ingest import materialize, value_universe

    calls: list[str] = []
    monkeypatch.setattr(materialize, "ingest_filing_sections", lambda s, c: calls.append(s) or 1)
    _index()
    materialize.enqueue("STDY", "filing_sections")
    assert materialize.drain_ingest_jobs() == 1 and calls == ["STDY"]
    monkeypatch.setattr(kf, "FILING_READS_FILE", tmp_path / "reads.json")
    monkeypatch.setattr(kf, "KEEP_FRESH_FILE", tmp_path / "keep.json")
    kf.write_filing_reads(["stdy"])
    assert kf.read_filing_reads() == ["STDY"]
    counts = value_universe.enqueue_value_universe(["STDY"], bars_only=())
    assert counts["filing_sections"] == 1


def test_the_value_side_reads_the_newest_periodic_filing_and_its_sections(
    research_db, monkeypatch
) -> None:
    from src.common import value_inputs as vi
    from src.research.store.models import FilingSectionRow
    from src.research.store.session import research_session

    _index(
        ("0000000001-26-000001", "10-K", date(2026, 2, 10), "k.htm"),
        ("0000000001-26-000003", "10-Q", date(2026, 5, 5), "q.htm"),
        ("0000000001-26-000004", "8-K", date(2026, 6, 1), "e.htm"),
    )
    with research_session() as s:
        s.add(
            FilingSectionRow(
                accn="0000000001-26-000003",
                cik="0000000001",
                form="10-Q",
                section="Item 2 MD&A",
                text="Revenue grew.",
                fetched_at=date(2026, 5, 6),
            )
        )
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(research_db))
    vi.reset_engine()
    with vi.research_read() as rs:
        assert rs is not None
        latest = vi.latest_periodic(rs, ["STDY", "NONE"])
        assert list(latest) == ["STDY"] and latest["STDY"].accn == "0000000001-26-000003"
        (sec,) = vi.filing_sections(rs, "0000000001-26-000003")
        assert (sec.form, sec.section, sec.text) == ("10-Q", "Item 2 MD&A", "Revenue grew.")
        assert vi.filing_sections(rs, "0000000001-26-000001") == []
    vi.reset_engine()
```

  …and apply to `tests/conftest.py` and `tests/test_value_universe.py`:

```diff
diff --git a/tests/conftest.py b/tests/conftest.py
index 58cd82b..5ad1f43 100644
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -77,11 +77,14 @@ def _clear_effective_universe_cache():
 
 @pytest.fixture(autouse=True)
 def _value_keep_fresh_in_tmp(monkeypatch, tmp_path_factory):
-    """The value process writes data/value_keep_fresh.json after a night; no test may touch the
-    real one."""
+    """The value process writes data/value_keep_fresh.json and (Part 4)
+    data/value_filing_reads.json after a night; no test may touch the real ones."""
+    folder = tmp_path_factory.mktemp("keep_fresh")
     monkeypatch.setattr(
-        "src.common.value_keep_fresh.KEEP_FRESH_FILE",
-        tmp_path_factory.mktemp("keep_fresh") / "value_keep_fresh.json",
+        "src.common.value_keep_fresh.KEEP_FRESH_FILE", folder / "value_keep_fresh.json"
+    )
+    monkeypatch.setattr(
+        "src.common.value_keep_fresh.FILING_READS_FILE", folder / "value_filing_reads.json"
     )
 
 
diff --git a/tests/test_value_universe.py b/tests/test_value_universe.py
index addfeda..6343e20 100644
--- a/tests/test_value_universe.py
+++ b/tests/test_value_universe.py
@@ -170,6 +170,7 @@ def test_the_sweep_queues_only_what_each_name_lacks(research_db) -> None:
         "fundamentals": 1,
         "submissions": 1,
         "going_concern": 0,
+        "filing_sections": 0,
         "prices": 3,
         "no_cik": 1,
     }
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_research_filing_sections.py tests/test_value_universe.py`
  Expected: FAIL — `ImportError: cannot import name 'filing_sections' from 'src.research.ingest'`
  (collection error) and the counts' missing `filing_sections` key.

- [ ] **Step 3: The job** — create `src/research/ingest/filing_sections.py`:

```python
"""The research worker's ``filing_sections`` job (value book spec §8.2 "Grounded facts", §8.5
"slicing a filing"). For the names the value book wants a filing read of (a plain file the value
process writes, ``src/common/value_keep_fresh.py``), the newest periodic filing's primary document
is fetched once and cut, deterministically, into the sections a reader needs: 10-K Items 1
(Business), 1A (Risk Factors) and 7 (MD&A); 10-Q Item 2 (MD&A); 20-F Items 4 and 5. A 40-F has no
item headings and is not sliced. Each section is capped so a filing read stays at ~15-25K tokens.

The heading match is a heuristic: a filing's table of contents names every item too, so of all
the spans that start at an item's heading and run to the next heading, the longest is kept.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from src.data.factory import get_filings_provider
from src.research.ingest.going_concern import html_to_text
from src.research.store.models import FilingIndexRow, FilingSectionRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

SECTIONS: dict[str, tuple[tuple[str, str, int], ...]] = {
    # form -> (item, label, character cap)
    "10-K": (
        ("1", "Item 1 Business", 24_000),
        ("1A", "Item 1A Risk Factors", 16_000),
        ("7", "Item 7 MD&A", 24_000),
    ),
    "10-Q": (("2", "Item 2 MD&A", 24_000),),
    "20-F": (("4", "Item 4 The Company", 24_000), ("5", "Item 5 Operating Review", 24_000)),
}
_HEADING = re.compile(r"\bItem\s+(\d{1,2}[A-C]?)\s*[.:\-—]", re.I)


def _base_form(form: str) -> str:
    return form.removesuffix("/A")


def slice_sections(text: str, form: str) -> dict[str, str]:
    """The sections of *form* found in *text* (plain text), each the longest span from its
    heading to the next item heading, capped. Missing sections are absent."""
    wanted = SECTIONS.get(_base_form(form), ())
    heads = [(m.start(), m.group(1).upper()) for m in _HEADING.finditer(text)]
    out: dict[str, str] = {}
    for item, label, cap in wanted:
        best = ""
        for i, (start, name) in enumerate(heads):
            if name != item:
                continue
            end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
            span = text[start:end].strip()
            if len(span) > len(best):
                best = span
        if best:
            out[label] = best[:cap]
    return out


def ingest_filing_sections(symbol: str, cik: str) -> int:
    """Slice the filer's newest periodic filing if it has not been sliced. Returns sections
    stored; 0 (no network) when there is nothing new. A document that does not come back raises,
    so the drain retries the job."""
    with research_session() as session:
        newest = (
            session.query(FilingIndexRow)
            .filter(
                FilingIndexRow.cik == cik,
                FilingIndexRow.form.in_([f for base in SECTIONS for f in (base, base + "/A")]),
                FilingIndexRow.primary_document.is_not(None),
            )
            .order_by(FilingIndexRow.filed.desc(), FilingIndexRow.accn.desc())
            .first()
        )
        if newest is None:
            return 0
        accn, form, document = newest.accn, newest.form, newest.primary_document
        done = session.query(FilingSectionRow.id).filter(FilingSectionRow.accn == accn).first()
    if done is not None:
        return 0
    assert document is not None
    raw = get_filings_provider().get_filing_text(cik, accn, document)
    if not raw:
        raise RuntimeError(f"No document for {symbol} {accn}")
    sections = slice_sections(html_to_text(raw), form)
    now = datetime.now(UTC).replace(tzinfo=None)
    with research_session() as session:
        for label, text in sections.items():
            session.add(
                FilingSectionRow(
                    accn=accn, cik=cik, form=form, section=label, text=text, fetched_at=now
                )
            )
        if not sections:  # remember the read: an empty marker row, so it is not refetched
            session.add(
                FilingSectionRow(accn=accn, cik=cik, form=form, section="", text="", fetched_at=now)
            )
    log.info("Filing sections for %s %s: %s", symbol, accn, sorted(sections) or "none found")
    return len(sections)
```

- [ ] **Step 4: The table, the drain, the sweep, the file and the readers** — apply:

```diff
diff --git a/src/common/value_inputs.py b/src/common/value_inputs.py
index 5564fa6..ff3f964 100644
--- a/src/common/value_inputs.py
+++ b/src/common/value_inputs.py
@@ -29,6 +29,7 @@ from sqlalchemy.orm import Session, sessionmaker
 
 from src.analytics.technicals import atr14_series, rsi14_series
 from src.common.config import get_config
+from src.common.value_ai_types import FilingSection
 from src.common.value_types import (
     AnnualPeriod,
     DayBar,
@@ -50,6 +51,7 @@ from src.research.store.models import (
     CompanyFactsRawRow,
     DailyBarRow,
     FilingIndexRow,
+    FilingSectionRow,
     FinancialRow,
     SymbolRow,
 )
@@ -419,6 +421,41 @@ def going_concern_flags(session: Session, symbols: list[str], as_of: date) -> di
     return {symbol: bool(flag) for symbol, flag in rows}  # the newest read wins
 
 
+def latest_periodic(session: Session, symbols: list[str]) -> dict[str, FilingEvent]:
+    """Each symbol's newest indexed periodic filing (10-K, 10-Q, 20-F, 40-F and amendments): what
+    a filing read reads (spec §8.3). Empty before the research worker built the index."""
+    periodic = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
+    if not symbols:
+        return {}
+    try:
+        rows = session.execute(
+            select(SymbolRow.symbol, FilingIndexRow)
+            .join(FilingIndexRow, FilingIndexRow.cik == SymbolRow.cik)
+            .where(SymbolRow.symbol.in_(symbols), FilingIndexRow.form.in_(periodic))
+            .order_by(FilingIndexRow.filed, FilingIndexRow.accn)
+        ).all()
+    except OperationalError:
+        return {}
+    return {
+        symbol: FilingEvent(accn=row.accn, form=row.form, filed=row.filed)
+        for symbol, row in rows  # the newest wins
+    }
+
+
+def filing_sections(session: Session, accn: str) -> list[FilingSection]:
+    """The sections the research worker cut from one filing (spec §8.5); ``[]`` before it has
+    (an empty marker row means it read the filing and found no item headings)."""
+    try:
+        rows = session.scalars(
+            select(FilingSectionRow)
+            .where(FilingSectionRow.accn == accn, FilingSectionRow.section != "")
+            .order_by(FilingSectionRow.id)
+        ).all()
+    except OperationalError:
+        return []
+    return [FilingSection(accn=r.accn, form=r.form, section=r.section, text=r.text) for r in rows]
+
+
 def current_fingerprint_parts(session: Session, symbol: str) -> dict[str, Any]:
     """The cheap half of the ticker-file fingerprint (spec §6.9): the newest accession in
     ``financials`` and the newest bar, without parsing the raw payload."""
diff --git a/src/common/value_keep_fresh.py b/src/common/value_keep_fresh.py
index 58d488b..e886428 100644
--- a/src/common/value_keep_fresh.py
+++ b/src/common/value_keep_fresh.py
@@ -20,24 +20,43 @@ from src.common.config import ROOT
 log = logging.getLogger(__name__)
 
 KEEP_FRESH_FILE: Path = ROOT / "data" / "value_keep_fresh.json"
+# Part 4 (spec §8.3, §8.5): the names the value book wants a filing read of (held and READY
+# names); the research sweep queues a ``filing_sections`` job for each.
+FILING_READS_FILE: Path = ROOT / "data" / "value_filing_reads.json"
 
 
-def write_keep_fresh(symbols: Iterable[str]) -> None:
-    """Replace the list atomically (write a sibling temp file, then rename)."""
-    path = KEEP_FRESH_FILE
+def _write(path: Path, symbols: Iterable[str]) -> None:
     path.parent.mkdir(parents=True, exist_ok=True)
     tmp = path.with_name(path.name + ".tmp")
     tmp.write_text(json.dumps(sorted({s.upper() for s in symbols})), encoding="utf-8")
     os.replace(tmp, path)
 
 
-def read_keep_fresh() -> list[str]:
-    """The list, or ``[]`` when the file is missing or unreadable (the sweep then covers the
-    universes alone, as before)."""
+def _read(path: Path) -> list[str]:
     try:
-        data = json.loads(KEEP_FRESH_FILE.read_text(encoding="utf-8"))
+        data = json.loads(path.read_text(encoding="utf-8"))
     except (OSError, ValueError):
         return []
     if not isinstance(data, list):
         return []
     return sorted({s.upper() for s in data if isinstance(s, str) and s})
+
+
+def write_keep_fresh(symbols: Iterable[str]) -> None:
+    """Replace the list atomically (write a sibling temp file, then rename)."""
+    _write(KEEP_FRESH_FILE, symbols)
+
+
+def read_keep_fresh() -> list[str]:
+    """The list, or ``[]`` when the file is missing or unreadable (the sweep then covers the
+    universes alone, as before)."""
+    return _read(KEEP_FRESH_FILE)
+
+
+def write_filing_reads(symbols: Iterable[str]) -> None:
+    _write(FILING_READS_FILE, symbols)
+
+
+def read_filing_reads() -> list[str]:
+    """The names to slice filings for, or ``[]`` (no file: no filing reads)."""
+    return _read(FILING_READS_FILE)
diff --git a/src/research/ingest/materialize.py b/src/research/ingest/materialize.py
index 04f1c44..411bba5 100644
--- a/src/research/ingest/materialize.py
+++ b/src/research/ingest/materialize.py
@@ -32,6 +32,7 @@ from pydantic import BaseModel
 
 from src.common.config import get_config
 from src.research.checks.payload import ChecksPayload, build_checks_payload
+from src.research.ingest.filing_sections import ingest_filing_sections
 from src.research.ingest.fundamentals import ingest_fundamentals, load_cached_financials
 from src.research.ingest.going_concern import ingest_going_concern
 from src.research.ingest.prices import ingest_daily_bars
@@ -423,6 +424,12 @@ def drain_ingest_jobs(max_jobs: int = 20) -> int:
                 ingest_going_concern(symbol, cik)
             except Exception as exc:
                 error = str(exc)
+        elif kind == "filing_sections" and cik:
+            # The newest periodic filing cut into the sections a filing read needs (§8.5).
+            try:
+                ingest_filing_sections(symbol, cik)
+            except Exception as exc:
+                error = str(exc)
         elif kind == "prices":
             # Daily bars for a name no warm tier covers (the value book's universes, spec §6.1).
             try:
diff --git a/src/research/ingest/value_universe.py b/src/research/ingest/value_universe.py
index 2ace4d0..d0f0e73 100644
--- a/src/research/ingest/value_universe.py
+++ b/src/research/ingest/value_universe.py
@@ -18,7 +18,7 @@ from datetime import UTC, date, datetime, timedelta
 from sqlalchemy import func, select
 
 from src.common.config import get_config
-from src.common.value_keep_fresh import read_keep_fresh
+from src.common.value_keep_fresh import read_filing_reads, read_keep_fresh
 from src.common.value_universe import build_value_universe
 from src.research.ingest.materialize import enqueue
 from src.research.store.models import (
@@ -72,13 +72,14 @@ def enqueue_value_universe(
     bars_only: tuple[str, ...] | None = None,
 ) -> dict[str, int]:
     """Queue what each name lacks. Returns counts: fundamentals, submissions, going_concern,
-    prices, no_cik.
+    filing_sections, prices, no_cik.
 
     Bars are refetched until the newest is past the last weekday before *today*: a bar dated
     that weekday may have been written while its session was still forming (review M2), and the
     value book marks its shadow record every session. The nightly call (no *names*) also
     refreshes the benchmarks' bars (*bars_only*, default ``benchmark_names()``)."""
     held = set(read_keep_fresh())
+    filing_reads = set(read_filing_reads())
     if names is None:
         names = value_names()
         bars_only = benchmark_names() if bars_only is None else bars_only
@@ -86,7 +87,14 @@ def enqueue_value_universe(
     today = today or datetime.now(UTC).date()
     due = last_weekday_before(today)
     now = datetime.now(UTC).replace(tzinfo=None)
-    counts = {"fundamentals": 0, "submissions": 0, "going_concern": 0, "prices": 0, "no_cik": 0}
+    counts = {
+        "fundamentals": 0,
+        "submissions": 0,
+        "going_concern": 0,
+        "filing_sections": 0,
+        "prices": 0,
+        "no_cik": 0,
+    }
     with research_session() as s:
         ciks = {r.symbol: r.cik for r in s.query(SymbolRow).filter(SymbolRow.symbol.in_(names))}
         fetched = {
@@ -123,6 +131,9 @@ def enqueue_value_universe(
             if symbol in held:
                 enqueue(symbol, "going_concern")
                 counts["going_concern"] += 1
+            if symbol in filing_reads:  # a no-op once the newest filing is sliced (spec §8.5)
+                enqueue(symbol, "filing_sections")
+                counts["filing_sections"] += 1
     for symbol in [*names, *extra]:
         n, last = bars.get(symbol, (0, None))
         if n < MIN_BARS or last is None or last <= due:
diff --git a/src/research/store/models.py b/src/research/store/models.py
index 2845f87..bd6f8a7 100644
--- a/src/research/store/models.py
+++ b/src/research/store/models.py
@@ -193,7 +193,9 @@ class IngestJobRow(Base):
 
     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
     symbol: Mapped[str] = mapped_column(String(16), index=True)
-    kind: Mapped[str] = mapped_column(String(32))  # fundamentals|prices|submissions|going_concern
+    kind: Mapped[str] = mapped_column(
+        String(32)
+    )  # fundamentals|prices|submissions|going_concern|filing_sections
     status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
     attempts: Mapped[int] = mapped_column(Integer, default=0)
     last_error: Mapped[str | None] = mapped_column(Text)
@@ -220,6 +222,22 @@ class FilingIndexRow(Base):
     __table_args__ = (Index("ix_filing_index_cik_filed", "cik", "filed"),)
 
 
+class FilingSectionRow(Base):
+    """One slice of a periodic filing (value book spec §8.2, §8.5): the sections a filing read
+    needs (10-K Items 1, 1A and 7; 10-Q Item 2; 20-F Items 4 and 5), cut by the
+    ``filing_sections`` job so no model pays to read boilerplate."""
+
+    __tablename__ = "filing_sections"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    accn: Mapped[str] = mapped_column(String(32), index=True)
+    cik: Mapped[str] = mapped_column(String(10))
+    form: Mapped[str] = mapped_column(String(16))
+    section: Mapped[str] = mapped_column(String(32))
+    text: Mapped[str] = mapped_column(Text)
+    fetched_at: Mapped[datetime] = mapped_column(DateTime)
+
+
 class SubmissionsStateRow(Base):
     """When each filer's ``submissions`` feed was last read, and its ETag (a 304 is free)."""
 
```

- [ ] **Step 5: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_research_filing_sections.py tests/test_value_universe.py tests/test_research_submissions.py tests/test_value_keep_fresh.py tests/test_value_inputs.py tests/test_value_fence.py tests/test_value_service.py`
  Expected: PASS; then `ls data/value_filing_reads.json` fails (the conftest redirect holds).

- [ ] **Step 6: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the nine touched files;
  `.venv/bin/mypy src/research src/common/value_keep_fresh.py src/common/value_inputs.py`.

  ```bash
  git add src/research/ingest/filing_sections.py src/research/store/models.py src/research/ingest/materialize.py src/research/ingest/value_universe.py src/common/value_keep_fresh.py src/common/value_inputs.py tests/test_research_filing_sections.py tests/conftest.py tests/test_value_universe.py
  git commit -m "feat(research): the filing_sections job - a filing sliced for the value book's filing reads"
  ```

---

### Task 11: Grounded facts and filing reads

**Files:**
- Create: `src/value/grounding.py`, `tests/test_value_grounding.py`
- Modify: `src/value/claude_verdicts.py` (imports; `Accepted`; `accept`'s signature and the facts
  before the note), `src/value/claude_reads.py` (imports; constants; `plan_filing_reads` before
  `_review_text`; `run_queue`'s signature, the filing wait and `accept`'s call),
  `src/value/service.py` (import; `effective` and `deep_reads` after `persist_effective`; the queued
  reads; `write_filing_reads` after `write_keep_fresh`), `scripts/run_value.py` (imports;
  `_sections` and `_financials`; `run_queue`'s call), `tests/test_value_claude.py` (append two),
  `tests/test_value_fence.py` (the allowlist, the pure list, the research-worker check)

**Interfaces:**
- Consumes: Task 10's readers; Task 2's `ProposedFact`, `FilingSection`; `ValueClaudeFactRow`.
- Produces: `grounding.check_fact(fact, sections, fin=None) -> (bool, why)`, `number_in_quote`,
  `xbrl_value`, `SCALE`; `accept(..., sections=None, financials=None)` with `Accepted.facts` and
  `.dropped`; `claude_reads.plan_filing_reads(vs, latest, now) -> int`, `FILING_WAIT_DAYS = 7`,
  `run_queue(..., financials_for=None)`; the night writes `data/value_filing_reads.json` (effective
  READY trading names) and queues filing reads (`summary["claude"]["filing"]`).

- [ ] **Step 1: Write the failing tests** — create `tests/test_value_grounding.py`:

```python
"""Grounded facts (value book spec §8.2): verbatim quotes, numbers in the quote, XBRL matches."""

from __future__ import annotations

from src.common.value_ai_types import FilingSection, ProposedFact
from src.value.grounding import check_fact, number_in_quote
from tests.value_fixtures import financials

ACCN = "0000000001-26-000001"
SECTIONS = [
    FilingSection(
        accn=ACCN,
        form="10-K",
        section="Item 7 MD&A",
        text="Revenue grew 12% to $1,600 million. We recorded a one-time   restructuring "
        "charge of $45.2 million in the fourth quarter. We now expect revenue to decline.",
    )
]


def _fact(**kw) -> ProposedFact:
    base = dict(
        kind="one_off",
        value=45.2,
        unit="USD_millions",
        accn=ACCN,
        quote="a one-time restructuring charge of $45.2 million",
    )
    base.update(kw)
    return ProposedFact(**base)


def test_a_verbatim_quote_with_its_number_is_grounded() -> None:
    assert check_fact(_fact(), SECTIONS) == (True, "")  # whitespace normalised, nothing else


def test_a_paraphrase_a_wrong_number_or_a_wrong_filing_is_dropped() -> None:
    assert check_fact(_fact(quote="a restructuring charge of $45.2 million"), SECTIONS)[1] == (
        "the quote is not in the filing verbatim"
    )
    assert check_fact(_fact(value=52.4), SECTIONS)[1] == "the number is not in the quote"
    assert check_fact(_fact(accn="0000000001-25-000009"), SECTIONS)[1] == (
        "the accession is not a filing this read was given"
    )
    cut = _fact(kind="guidance_cut", value=None, quote="We now expect revenue to decline.")
    assert check_fact(cut, SECTIONS) == (True, "")


def test_an_xbrl_item_must_match_companyfacts_for_that_filing() -> None:
    fin = financials()  # revenue 1600 tagged by ACCN (the fixture's units are $ millions)
    good = _fact(
        kind="segment_revenue",
        value=1600,
        unit="USD",
        item="revenue",
        quote="Revenue grew 12% to $1,600 million",
    )
    assert check_fact(good, SECTIONS, fin) == (True, "")
    bad = good.model_copy(update={"unit": "USD_millions"})  # 1.6e9 against a tagged 1,600
    ok, why = check_fact(bad, SECTIONS, fin)
    assert not ok and why == "companyfacts tags revenue 1,600 for this filing"


def test_a_number_is_matched_to_the_precision_written() -> None:
    assert number_in_quote(1600.0, "to $1,600 million")
    assert number_in_quote(45.2, "$45.2 million") and not number_in_quote(45.3, "$45.2 million")
    assert number_in_quote(18.0, "18% of revenue")
```

  …and apply to `tests/test_value_claude.py` and `tests/test_value_fence.py`:

```diff
diff --git a/tests/test_value_claude.py b/tests/test_value_claude.py
index 66f1409..8814ecd 100644
--- a/tests/test_value_claude.py
+++ b/tests/test_value_claude.py
@@ -348,3 +348,74 @@ def test_the_operator_script_queues_a_read_and_resets_the_breaker(value_db, caps
     assert main(["--read", "NVDA", "--reset-breaker"]) == 0
     out = capsys.readouterr().out
     assert "queued NVDA" in out and "NVDA: already queued" in out and "breaker reset" in out
+
+
+def test_a_filing_read_stores_each_fact_with_its_grounding(value_db) -> None:
+    from src.common.value_ai_types import FilingSection, ProposedFact
+    from src.value.store import ValueClaudeFactRow
+
+    sections = [
+        FilingSection(
+            accn="0000000001-26-000001",
+            form="10-K",
+            section="Item 7 MD&A",
+            text="We now expect revenue to decline. A customer that was 18% of sales left.",
+        )
+    ]
+    facts = [
+        ProposedFact(
+            kind="guidance_cut",
+            accn="0000000001-26-000001",
+            quote="We now expect revenue to decline.",
+        ),
+        ProposedFact(
+            kind="customer_concentration",
+            value=21.0,
+            unit="pct",
+            accn="0000000001-26-000001",
+            quote="A customer that was 18% of sales left.",
+        ),
+    ]
+    result = AnalystResult(
+        read_id=0,
+        reply=AnalystReply(facts=facts),
+        call=AnalystCall(model="sonnet", backend="cli"),
+    )
+    with value_session() as s:
+        read = ValueClaudeReadRow(
+            symbol="STDY",
+            kind="filing",
+            reason="filing",
+            priority=2,
+            requested_at=NOW,
+            accn="0000000001-26-000001",
+        )
+        s.add(read)
+        s.flush()
+        out = cv.accept(s, read, result, CHEAP, CFG, now=NOW, sections=sections)
+        assert (out.facts, out.dropped) == (1, 1)
+    with value_session() as s:
+        rows = {r.kind: (r.grounded, r.why) for r in s.scalars(select(ValueClaudeFactRow))}
+        assert rows == {
+            "guidance_cut": (True, ""),
+            "customer_concentration": (False, "the number is not in the quote"),
+        }
+        assert s.scalars(select(ValueClaudeNoteRow)).all() == []  # a filing read writes no prose
+
+
+def test_filing_reads_are_queued_once_per_filing_and_wait_for_their_sections(value_db) -> None:
+    from src.common.value_types import FilingEvent
+    from src.value.claude_reads import plan_filing_reads
+
+    _file(CHEAP)
+    q10 = FilingEvent(accn="0000000001-26-000003", form="10-Q", filed=date(2026, 5, 5))
+    with value_session() as s:
+        assert plan_filing_reads(s, {"STDY": q10}, NOW) == 1
+        assert plan_filing_reads(s, {"STDY": q10}, NOW) == 0  # already queued for that filing
+    calls: list[AnalystRequest] = []
+    no_sections = run_queue(calls.append, now=NOW, cfg=ON, sections_for=lambda sym, accn: [])
+    assert no_sections["waiting"] == 1 and calls == []
+    later = run_queue(
+        calls.append, now=NOW + timedelta(days=8), cfg=ON, sections_for=lambda sym, accn: []
+    )
+    assert later["skipped"] == 1  # the sections never came: dropped after a week
diff --git a/tests/test_value_fence.py b/tests/test_value_fence.py
index 3807034..290eaf6 100644
--- a/tests/test_value_fence.py
+++ b/tests/test_value_fence.py
@@ -36,6 +36,8 @@ PURE = (
     "reevaluate",
     "claude_valuation",
     "effective",
+    "kill_triggers",
+    "grounding",
 )
 
 FORBIDDEN_FOR_VALUE = (
@@ -274,6 +276,8 @@ def test_the_value_entrypoint_imports_only_its_feed_and_the_service() -> None:
         "src.common.config",
         "src.common.logging",
         "src.common.value_ai_types",
+        "src.common.value_inputs",
+        "src.common.value_types",
         "src.value.claude_reads",
         "src.value.service",
         "src.value_ai.analyst",
@@ -312,15 +316,16 @@ def test_the_value_process_loads_no_wheel_layer_and_no_ibkr() -> None:
 def test_the_research_worker_owns_the_filings_feed() -> None:
     """Spec §6.9: the submissions and going-concern jobs live in src/research and fetch through
     src/data; the value side reads their table only through the neutral loader."""
-    for name in ("submissions", "going_concern"):
+    for name in ("submissions", "going_concern", "filing_sections"):
         mods = imported_modules(ROOT / "src" / "research" / "ingest" / f"{name}.py")
         assert _reaches(mods, "src.data.factory") and not _reaches(mods, "src.value")
     readers = [
         str(p.relative_to(ROOT))
         for p in [*VALUE, *(ROOT / "scripts").glob("value_*.py")]
         if "FilingIndexRow" in p.read_text(encoding="utf-8")
+        or "FilingSectionRow" in p.read_text(encoding="utf-8")
     ]
-    assert readers == []  # only src/common/value_inputs.py names the table
+    assert readers == []  # only src/common/value_inputs.py names the tables
 
 
 VALUE_AI = sorted((ROOT / "src" / "value_ai").rglob("*.py"))
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_grounding.py tests/test_value_claude.py tests/test_value_fence.py`
  Expected: FAIL — `ModuleNotFoundError: No module named 'src.value.grounding'`, `accept()` has no
  `sections`, `plan_filing_reads` is missing, and the pure list's `grounding` file is missing.

- [ ] **Step 3: The checker** — create `src/value/grounding.py`:

```python
"""Grounded facts (spec §8.2): every fact Claude proposes from a filing is checked here, and any
failure drops it. Pure: no I/O.

- The accession must be one of the filing's the read was given, and the quote must appear
  **verbatim** in that filing's sliced text (whitespace and curly quotes normalised, nothing else).
- A fact with a number must have that number in its quote (the ``src/news/grounding.py::grounded``
  rule, restated here: ``src/value/`` may not import ``src.news``).
- A fact naming a canonical XBRL item that the filing tagged must match companyfacts for that
  accession within 0.5% (after its unit's scale), whatever the quote says.

A grounded fact is stored and read again (the kill triggers ``guidance_cut`` and
``customer_loss``; the display). In Part 4 it adjusts no number (the plan's ruling 9).
"""

from __future__ import annotations

import re

from src.common.value_ai_types import FilingSection, ProposedFact
from src.common.value_types import ValueFinancials

XBRL_TOLERANCE = 0.005
_NUM = re.compile(r"(?<![A-Za-z0-9])[-+]?\d[\d,]*(?:\.(\d+))?")
_SPACE = re.compile(r"\s+")
SCALE = {
    "USD": 1.0,
    "USD_thousands": 1e3,
    "USD_millions": 1e6,
    "USD_billions": 1e9,
}


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"')
    return _SPACE.sub(" ", text.replace("”", '"')).strip()


def numbers_in(text: str) -> list[tuple[float, int]]:
    out: list[tuple[float, int]] = []
    for m in _NUM.finditer(text):
        try:
            out.append((float(m.group(0).replace(",", "")), len(m.group(1) or "")))
        except ValueError:
            continue
    return out


def number_in_quote(value: float, quote: str) -> bool:
    """*value* written in *quote*, to the precision the quote shows (within half a unit of its
    last digit), sign aside."""
    for found, decimals in numbers_in(quote):
        if abs(abs(found) - abs(value)) <= 0.5 * 10.0**-decimals:
            return True
    return False


def xbrl_value(fin: ValueFinancials | None, item: str, accn: str) -> float | None:
    """The value companyfacts carries for *item* from the filing *accn* (an annual period whose
    item that filing reported), or None when the filing did not tag it."""
    if fin is None:
        return None
    for period in fin.annual:
        if period.accns.get(item) == accn and item in period.items:
            return period.items[item]
    return None


def check_fact(
    fact: ProposedFact, sections: list[FilingSection], fin: ValueFinancials | None = None
) -> tuple[bool, str]:
    """(grounded, why not). Why is "" for a grounded fact."""
    text = " ".join(s.text for s in sections if s.accn == fact.accn)
    if not text:
        return False, "the accession is not a filing this read was given"
    if _norm(fact.quote) not in _norm(text):
        return False, "the quote is not in the filing verbatim"
    if fact.value is not None and not number_in_quote(fact.value, fact.quote):
        return False, "the number is not in the quote"
    if fact.item is not None and fact.value is not None:
        tagged = xbrl_value(fin, fact.item, fact.accn)
        scale = SCALE.get(fact.unit)
        if tagged is not None and scale is not None and tagged != 0:
            if abs(fact.value * scale - tagged) / abs(tagged) > XBRL_TOLERANCE:
                return False, f"companyfacts tags {fact.item} {tagged:,.0f} for this filing"
    return True, ""
```

- [ ] **Step 4: The wiring** — apply:

```diff
diff --git a/scripts/run_value.py b/scripts/run_value.py
index a4a23a9..79bd152 100644
--- a/scripts/run_value.py
+++ b/scripts/run_value.py
@@ -23,6 +23,7 @@ import signal
 import threading
 from datetime import UTC, datetime
 
+import src.common.value_inputs as vi
 from scripts.value_feed import (
     FactsCache,
     NightRetry,
@@ -32,7 +33,8 @@ from scripts.value_feed import (
 )
 from src.common.config import get_config
 from src.common.logging import setup_logging
-from src.common.value_ai_types import AnalystRequest, AnalystResult
+from src.common.value_ai_types import AnalystRequest, AnalystResult, FilingSection
+from src.common.value_types import ValueFinancials
 from src.value.claude_reads import run_queue
 from src.value.service import plan_run, run_nightly, startup_check
 from src.value_ai.analyst import Analyst
@@ -52,13 +54,36 @@ def _read(req: AnalystRequest) -> AnalystResult:
     return asyncio.run(_analyst.read(req, datetime.now(UTC)))
 
 
+def _sections(symbol: str, accn: str) -> list[FilingSection]:
+    with vi.research_read() as rs:
+        return [] if rs is None else vi.filing_sections(rs, accn)
+
+
+def _financials(symbol: str) -> ValueFinancials | None:
+    """The filings as known today, for grounding's XBRL check (spec §8.2)."""
+    stale = get_config().value.rules.data_quality.stale_item_days
+    with vi.research_read() as rs:
+        if rs is None:
+            return None
+        _, payload = vi.read_payload(rs, symbol)
+    if payload is None:
+        return None
+    return vi.build_value_financials(payload, as_of=datetime.now(UTC).date(), stale_item_days=stale)
+
+
 def _claude_tick() -> None:
     """Claude's queued reads (spec §8.5): requests first, then the automatic set, within the
     day's caps. Each read commits on its own; a failed read is recorded, never retried blind."""
     cfg = get_config().value
     if not cfg.claude.enabled:
         return
-    summary = run_queue(_read, now=datetime.now(UTC).replace(tzinfo=None), cfg=cfg)
+    summary = run_queue(
+        _read,
+        now=datetime.now(UTC).replace(tzinfo=None),
+        cfg=cfg,
+        sections_for=_sections,
+        financials_for=_financials,
+    )
     if any(summary.values()):
         log.info("value: claude reads %s", summary)
 
diff --git a/src/value/claude_reads.py b/src/value/claude_reads.py
index e8e1305..618a18b 100644
--- a/src/value/claude_reads.py
+++ b/src/value/claude_reads.py
@@ -32,6 +32,7 @@ from src.common.value_ai_types import (
     FilingSection,
     Range,
 )
+from src.common.value_types import FilingEvent, ValueFinancials
 from src.value.claude_valuation import bounds_for
 from src.value.claude_verdicts import accept
 from src.value.schemas import LISTS, ValueScorecard
@@ -47,8 +48,10 @@ log = logging.getLogger(__name__)
 
 PRIORITY = {"request": 0, "review": 1, "filing": 2, "top": 3, "stale": 4}
 DEEP_KINDS = ("filing",)
+FILING_WAIT_DAYS = 7  # a filing read whose sections never arrive is dropped after a week
 Reader = Callable[[AnalystRequest], AnalystResult]
 SectionsFor = Callable[[str, str], list[FilingSection]]
+FinancialsFor = Callable[[str], ValueFinancials | None]
 
 
 def _fmt(v: float | None, pct: bool = False) -> str:
@@ -280,6 +283,29 @@ def plan_auto_reads(vs: Session, now: datetime, cfg: ValueCfg) -> dict[str, int]
     return counts
 
 
+def plan_filing_reads(vs: Session, latest: dict[str, FilingEvent], now: datetime) -> int:
+    """Queue a filing read of each name's newest periodic filing that has not had one (held and
+    READY names, spec §8.3: "a filing read on each new 10-K/10-Q"). *latest*: from
+    ``value_inputs.latest_periodic`` for the names that qualify tonight."""
+    queued = 0
+    for symbol, filing in sorted(latest.items()):
+        seen = vs.scalars(
+            select(ValueClaudeReadRow.id).where(
+                ValueClaudeReadRow.symbol == symbol,
+                ValueClaudeReadRow.kind == "filing",
+                ValueClaudeReadRow.accn == filing.accn,
+            )
+        ).first()
+        if seen is not None:
+            continue
+        if (
+            queue_read(vs, symbol, kind="filing", reason="filing", now=now, accn=filing.accn)
+            is not None
+        ):
+            queued += 1
+    return queued
+
+
 def _review_text(vs: Session, reevaluation_id: int | None) -> str:
     if reevaluation_id is None:
         return ""
@@ -299,6 +325,7 @@ def run_queue(
     now: datetime,
     cfg: ValueCfg,
     sections_for: SectionsFor | None = None,
+    financials_for: FinancialsFor | None = None,
     limit: int | None = None,
 ) -> dict[str, Any]:
     """Run queued reads, best priority first, within today's caps. A filing read whose sections
@@ -331,7 +358,11 @@ def run_queue(
             if row.kind == "filing":
                 sections = sections_for(row.symbol, row.accn or "") if sections_for else []
                 if not sections:
-                    summary["waiting"] += 1
+                    if now - row.requested_at > timedelta(days=FILING_WAIT_DAYS):
+                        row.status, row.detail = "skipped", "the filing's sections never arrived"
+                        summary["skipped"] += 1
+                    else:
+                        summary["waiting"] += 1
                     continue
             req = build_request(
                 row,
@@ -346,7 +377,18 @@ def run_queue(
             card = _card(vs, row.symbol) if row is not None else None
             if row is None or card is None:
                 continue
-            done = accept(vs, row, result, card, cfg, now=now)
+            done = accept(
+                vs,
+                row,
+                result,
+                card,
+                cfg,
+                now=now,
+                sections=sections,
+                financials=financials_for(row.symbol)
+                if financials_for and row.kind == "filing"
+                else None,
+            )
             summary["done" if result.reply is not None else "failed"] += 1
             log.info(
                 "value claude read %s %s (%s): %s; %d verdict(s), %d trigger(s)",
diff --git a/src/value/claude_verdicts.py b/src/value/claude_verdicts.py
index 8917394..633c9cb 100644
--- a/src/value/claude_verdicts.py
+++ b/src/value/claude_verdicts.py
@@ -24,8 +24,9 @@ from sqlalchemy import select
 from sqlalchemy.orm import Session
 
 from src.common.config import ValueCfg, ValueRulesCfg
-from src.common.value_ai_types import AnalystResult, Drivers, KillTrigger
-from src.value import kill_triggers
+from src.common.value_ai_types import AnalystResult, Drivers, FilingSection, KillTrigger
+from src.common.value_types import ValueFinancials
+from src.value import grounding, kill_triggers
 from src.value.claude_valuation import ClaudeValue, claude_fair_value
 from src.value.effective import ClaudeOpinion, Effective, effective
 from src.value.schemas import LISTS, ValueScorecard
@@ -51,6 +52,8 @@ class Accepted:
     kept_earlier: int = 0  # raised between filings: the earlier drivers stand
     triggers: int = 0
     review_state: str | None = None
+    facts: int = 0  # grounded facts stored
+    dropped: int = 0  # facts that failed grounding (stored, marked ungrounded)
 
 
 def _latest_verdict(vs: Session, symbol: str, list_name: str) -> ValueClaudeVerdictRow | None:
@@ -87,9 +90,12 @@ def accept(
     cfg: ValueCfg,
     *,
     now: datetime,
+    sections: list[FilingSection] | None = None,
+    financials: ValueFinancials | None = None,
 ) -> Accepted:
     """Store one read's outcome. The read row records the call either way; a reply that is None
-    (a failure, a malformed reply) stores nothing else: no notes, never a guess."""
+    (a failure, a malformed reply) stores nothing else: no notes, never a guess. A filing read's
+    facts are checked against *sections* (and *financials* for XBRL items) by ``grounding``."""
     call = result.call
     read.read_at, read.model, read.backend = now, call.model, call.backend
     read.latency_ms, read.cost_usd, read.error = call.latency_ms, call.cost_usd, call.error
@@ -142,6 +148,30 @@ def accept(
             )
         )
         out.verdicts += 1
+    for fact in reply.facts:
+        ok, why = grounding.check_fact(fact, sections or [], financials)
+        vs.add(
+            ValueClaudeFactRow(
+                read_id=read.id,
+                symbol=read.symbol,
+                accn=fact.accn,
+                kind=fact.kind,
+                value=fact.value,
+                unit=fact.unit,
+                quote=fact.quote,
+                item=fact.item,
+                grounded=ok and call.backend == "cli",
+                why=why or ("" if call.backend == "cli" else "an Ollama reply is never grounded"),
+                created_at=now,
+            )
+        )
+        if ok and call.backend == "cli":
+            out.facts += 1
+        else:
+            out.dropped += 1
+    if read.kind == "filing":
+        vs.flush()
+        return out
     vs.add(
         ValueClaudeNoteRow(
             read_id=read.id,
diff --git a/src/value/service.py b/src/value/service.py
index 365c489..c384006 100644
--- a/src/value/service.py
+++ b/src/value/service.py
@@ -30,11 +30,11 @@ from sqlalchemy.orm import Session
 
 from src.common import value_inputs as vi
 from src.common.config import get_config
-from src.common.value_keep_fresh import write_keep_fresh
+from src.common.value_keep_fresh import write_filing_reads, write_keep_fresh
 from src.common.value_types import Classification, MarketFacts, NewsVolume, ValueInputs
 from src.common.value_universe import build_value_universe
 from src.value import claude_verdicts, reevaluate, shadow
-from src.value.claude_reads import plan_auto_reads
+from src.value.claude_reads import plan_auto_reads, plan_filing_reads
 from src.value.rank import filed_lists, rank_list, rs_cutoff
 from src.value.ruleset import ruleset_id
 from src.value.scorecard import build_scorecard
@@ -291,7 +291,7 @@ def run_nightly(
             ops = claude_verdicts.opinions(vs, cards, vcfg.rules)
             claude_night = claude_verdicts.night_counts(cards, plan.tags, ops, review)
             applied = claude_verdicts.applies(vs, vcfg, is_live=get_config().is_live)
-            claude_verdicts.persist_effective(
+            effective = claude_verdicts.persist_effective(
                 vs,
                 cards,
                 ops,
@@ -300,9 +300,21 @@ def run_nightly(
                 now=started,
                 review_above_pct=review,
             )
+            deep_reads = sorted(
+                {
+                    sym
+                    for (sym, _), eff in effective.items()
+                    if eff.verdict == "READY" and plan.tags.get(sym) == "trading"
+                }
+            )
             tripped = claude_verdicts.check_breaker(vs, vcfg, claude_night, started)
             kill = claude_verdicts.update_kill_triggers(vs, cards, vcfg, plan.as_of)
-            queued = plan_auto_reads(vs, started, vcfg) if vcfg.claude.enabled else {}
+            queued: dict[str, int] = {}
+            if vcfg.claude.enabled:
+                queued = plan_auto_reads(vs, started, vcfg)
+                queued["filing"] = plan_filing_reads(
+                    vs, vi.latest_periodic(rs, deep_reads), started
+                )
             stepped = reevaluate.regime_stepped(
                 previous_regime(vs), regime, vcfg.rules.reevaluation
             )
@@ -354,5 +366,6 @@ def run_nightly(
     # After the commit: a failed night leaves the previous list in place. The research sweep
     # reads this file to keep held names' bars and filings current (spec §6.9).
     write_keep_fresh(keep_fresh)
+    write_filing_reads(deep_reads if vcfg.claude.enabled else [])
     log.info("value nightly %s: %d names; %s", plan.as_of, len(cards), json.dumps(summary))
     return summary
```

- [ ] **Step 5: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_grounding.py tests/test_value_claude.py tests/test_value_fence.py tests/test_value_service.py tests/test_value_kill_triggers.py`
  and `.venv/bin/python -m py_compile scripts/run_value.py`.
  Expected: PASS; silent; `ls data/value_filing_reads.json` still fails.

- [ ] **Step 6: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the eight touched files;
  `.venv/bin/mypy src/value scripts/run_value.py`.

  ```bash
  git add src/value/grounding.py src/value/claude_verdicts.py src/value/claude_reads.py src/value/service.py scripts/run_value.py tests/test_value_grounding.py tests/test_value_claude.py tests/test_value_fence.py
  git commit -m "feat(value): filing reads with grounded facts, checked verbatim against the filing (spec 8.2)"
  ```

---

### Task 12: The interactive skill and one ticker file as JSON

**Files:**
- Create: `.claude/skills/value/SKILL.md`, `.claude/skills/value/reference/trigger-vocabulary.md`,
  `sector-rules.md`, `reverse-dcf-reading.md`, `forensic-checklist.md`, `output-schema.json`
  (generated)
- Modify: `scripts/value_report.py` (docstring; imports; `symbol_json` before `main`; two
  arguments), `tests/test_value_report.py`, `tests/test_value_ai.py` (append one each)

**Interfaces:**
- Produces: `value_report.symbol_json(symbol) -> str` (`--symbol SYMBOL --json`): the ticker file's
  scorecard, the effective verdict per list, Claude's current verdicts, latest notes and active
  kill triggers, with `"source": {"scorecard": "python", "claude": "claude"}`.

- [ ] **Step 1: Write the failing tests** — apply:

```diff
diff --git a/tests/test_value_ai.py b/tests/test_value_ai.py
index 454dee8..f3ce5f0 100644
--- a/tests/test_value_ai.py
+++ b/tests/test_value_ai.py
@@ -192,3 +192,11 @@ def test_context_without_news_db_says_so(monkeypatch, tmp_path) -> None:
     ro.reset_engine()
     assert gather("STDY", NOW, 5).unavailable == ["news"]
     ro.reset_engine()
+
+
+def test_the_skill_reads_the_same_schema_the_headless_prompt_uses() -> None:
+    """Spec §8.6: .claude/skills/value/reference/output-schema.json is generated from the prompts
+    (regenerate it with the plan's one-liner when OUTPUT_SCHEMA changes)."""
+    root = Path(__file__).resolve().parents[1]
+    path = root / ".claude" / "skills" / "value" / "reference" / "output-schema.json"
+    assert json.loads(path.read_text(encoding="utf-8")) == OUTPUT_SCHEMA
diff --git a/tests/test_value_report.py b/tests/test_value_report.py
index 445bb86..2e496a5 100644
--- a/tests/test_value_report.py
+++ b/tests/test_value_report.py
@@ -343,3 +343,44 @@ def test_claudes_track_is_printed_beside_the_baseline_with_the_breaker_rates() -
         "Last 2 nights: Claude READY 4 vs the baseline's 2 (breaker at 3x) · the 1.5x clamp "
         "set 1 of 8 fair values (12%; breaker above 25%) · breaker ok"
     )
+
+
+def test_one_ticker_file_prints_as_json_with_each_half_labelled(value_db) -> None:
+    """Spec §8.6: the skill reads this instead of re-computing anything."""
+    import json
+
+    from src.value.store import ValueClaudeVerdictRow
+    from src.value.ticker_file import persist
+
+    card = build_scorecard(inputs(close=30.0), get_config().value)
+    with value_session() as s:
+        persist(
+            s,
+            card,
+            universe="trading",
+            ranks={},
+            filed="deep_value",
+            cfg=get_config().value.ticker_file,
+            session_row=False,
+        )
+        s.add(
+            ValueClaudeVerdictRow(
+                read_id=1,
+                symbol="STDY",
+                list_name="deep_value",
+                verdict="READY",
+                drivers_json="{}",
+                fingerprint_key="k",
+                backend="cli",
+                fair_value=60.0,
+                created_at=datetime(2026, 11, 2),
+            )
+        )
+    out = json.loads(value_report.symbol_json("stdy"))
+    assert out["source"] == {"scorecard": "python", "claude": "claude"}
+    assert out["scorecard"]["symbol"] == "STDY"
+    assert out["claude"]["verdicts"][0]["fair_value"] == 60.0
+    assert json.loads(value_report.symbol_json("NONE")) == {
+        "symbol": "NONE",
+        "error": "no ticker file",
+    }
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_report.py tests/test_value_ai.py`
  Expected: FAIL — `AttributeError: module 'scripts.value_report' has no attribute 'symbol_json'`
  and `FileNotFoundError` for the skill's schema.

- [ ] **Step 3: One ticker file as JSON** — apply:

```diff
diff --git a/scripts/value_report.py b/scripts/value_report.py
index 245d5c2..eaf7902 100644
--- a/scripts/value_report.py
+++ b/scripts/value_report.py
@@ -2,6 +2,8 @@
 
     python -m scripts.value_report [--track baseline] [--universe all|trading|evidence]
         [--ruleset VERSION] [--postmortems]
+    python -m scripts.value_report --symbol NVDA --json   # one ticker file, both halves
+
 
 Reads data/value.db (select only; on a new install it first creates the empty tables) and
 prints: the survivorship caveat, the
@@ -33,6 +35,10 @@ from src.value.report import (
     render,
 )
 from src.value.store import (
+    ValueClaudeNoteRow,
+    ValueClaudeVerdictRow,
+    ValueEffectiveRow,
+    ValueKillTriggerRow,
     ValueRankedRow,
     ValueReevaluationRow,
     ValueRunRow,
@@ -181,14 +187,94 @@ def load(args: argparse.Namespace) -> str:
     )
 
 
+def symbol_json(symbol: str) -> str:
+    """One name's ticker file as JSON (spec §8.6: what the interactive skill reads instead of
+    re-computing anything): Part 1 (the scorecard), the effective verdict per list, and Claude's
+    latest verdicts, notes and active kill triggers, each labelled with its source."""
+    init_value_db()
+    sym = symbol.upper()
+    with value_session() as s:
+        f = s.get(ValueTickerFileRow, sym)
+        if f is None:
+            return json.dumps({"symbol": sym, "error": "no ticker file"})
+        effective = {
+            e.list_name: {
+                "verdict": e.verdict,
+                "decided_by": e.decided_by,
+                "fair_value": e.fair_value,
+                "entry_ceiling": e.entry_ceiling,
+                "margin_of_safety": e.margin_of_safety,
+            }
+            for e in s.scalars(select(ValueEffectiveRow).where(ValueEffectiveRow.symbol == sym))
+        }
+        verdicts = [
+            {
+                "list": v.list_name,
+                "verdict": v.verdict,
+                "why": v.why,
+                "fair_value": v.fair_value,
+                "uncapped": v.uncapped,
+                "clamp_bound": v.clamp_bound,
+                "drivers": json.loads(v.drivers_json),
+                "backend": v.backend,
+                "written": v.created_at.isoformat(),
+            }
+            for v in s.scalars(
+                select(ValueClaudeVerdictRow).where(
+                    ValueClaudeVerdictRow.symbol == sym, ValueClaudeVerdictRow.superseded.is_(False)
+                )
+            )
+        ]
+        note = s.scalars(
+            select(ValueClaudeNoteRow)
+            .where(ValueClaudeNoteRow.symbol == sym)
+            .order_by(ValueClaudeNoteRow.id.desc())
+            .limit(1)
+        ).first()
+        triggers = [
+            {"kind": t.kind, "threshold": t.threshold, "state": t.last_state}
+            for t in s.scalars(
+                select(ValueKillTriggerRow).where(
+                    ValueKillTriggerRow.symbol == sym, ValueKillTriggerRow.active.is_(True)
+                )
+            )
+        ]
+        return json.dumps(
+            {
+                "symbol": sym,
+                "as_of": f.as_of.isoformat(),
+                "source": {"scorecard": "python", "claude": "claude"},
+                "scorecard": json.loads(f.scorecard_json),
+                "effective": effective,
+                "claude": {
+                    "verdicts": verdicts,
+                    "notes": None
+                    if note is None
+                    else {
+                        "profile": note.profile,
+                        "why_cheap": note.why_cheap,
+                        "thesis": note.thesis,
+                        "bear_case": note.bear_case,
+                        "review_state": note.review_state,
+                        "written": note.created_at.isoformat(),
+                    },
+                    "kill_triggers": triggers,
+                },
+            },
+            indent=1,
+        )
+
+
 def main(argv: list[str] | None = None) -> int:
     parser = argparse.ArgumentParser(description="The value book's shadow record (spec §6.8)")
     parser.add_argument("--track", default="baseline", choices=("baseline", "claude"))
     parser.add_argument("--universe", default="all", choices=("all", "trading", "evidence"))
     parser.add_argument("--ruleset", default=None, help="only this ruleset version")
     parser.add_argument("--postmortems", action="store_true")
+    parser.add_argument("--symbol", default=None, help="one ticker file (with --json)")
+    parser.add_argument("--json", action="store_true", help="with --symbol: print JSON")
     args = parser.parse_args(argv)
-    print(load(args))
+    print(symbol_json(args.symbol) if args.symbol else load(args))
     return 0
 
 
```

- [ ] **Step 4: The skill** — create each file whole.

  `.claude/skills/value/SKILL.md`:

```markdown
---
name: value
description: Interactive value-book analysis of one stock in this repo - a deep dive into its 10-K, the bear case, the thesis and kill triggers, a review of a held name (INTACT/WEAKENED/BROKEN), a postmortem, or a plain-English reading of its scorecard. Use when the operator types /value SYMBOL or asks what the value book thinks of a company. Interactive only; the headless value reads use src/value_ai/ instead.
---

# The value skill (value book spec §8.6)

You are helping the operator read one company the way the value book does. The numbers are
**Python's**: never compute a fair value, a margin of safety or a DCF yourself, and never
re-implement a calculator. Two valuations that disagree are worse than none.

## First, always

1. Run `python -m scripts.value_report --symbol SYMBOL --json` and read it. It holds Part 1 of the
   ticker file (the scorecard: every gate with its number and bar, each valuation method, the
   baseline verdict per list), the effective verdict per list (`decided_by` claude or python),
   and Claude's latest verdicts, notes and kill triggers, each labelled with its source.
   `"error": "no ticker file"` means the value process has not scored the name: say so, and
   suggest `python -m scripts.value_claude --read SYMBOL` once it is in a universe or looked up.
2. Read `config/value.yaml` (`rules`, `claude`) for the bars and the driver bounds. Do not ask the
   operator for anything that file answers.

## Modes

| Mode | What you do | Reference |
|---|---|---|
| `explain` (default) | A plain-English reading of the scorecard: is the business healthy (the gates), what is it worth (Python's methods and median, Claude's drivers and the 1.5x cap), how much and when (timing, the regime's margin) | `reference/reverse-dcf-reading.md`, `reference/sector-rules.md` |
| `deep-dive` | Read the newest 10-K/10-Q the operator points you at and propose facts in `reference/output-schema.json`'s `facts` shape: each with the accession and a verbatim quote containing its number | `reference/forensic-checklist.md` |
| `bear` | The strongest case against, in a short seller's voice, from the numbers in the ticker file | |
| `thesis` | What has to be true for the price to reach fair value, and up to five kill triggers from the menu, with thresholds inside their ranges | `reference/trigger-vocabulary.md` |
| `review` | For a held name after a re-evaluation: INTACT, WEAKENED or BROKEN with one line why. A headline alone changes nothing about what the company is worth | |
| `postmortem` | For a closed position: `python -m scripts.value_report --postmortems`, then which gate was closest to wrong | |

## Rules

- Health and earnings-quality gates are final: never argue a name over one.
- Anything you would save (a fact, a request for a read) goes through
  `python -m scripts.value_claude` or the value process; never open a database.
- Label everything you write as Claude's. Unknown is `n/a`, never zero.
```

  `.claude/skills/value/reference/trigger-vocabulary.md`:

```markdown
# Kill-trigger vocabulary (spec §8.4)

Up to five, chosen from this menu only. Python bounds each threshold into its range
(`config/value.yaml → rules.claude.kill_bounds`) and evaluates every one each night; a trigger
within 10% of firing opens a Minor re-evaluation (§7.1 trigger 6), a fired one raises a review
card. None of them sells anything on its own.

| Kind | Fires when | Threshold (range) |
|---|---|---|
| `revenue_growth_below` | the newest fiscal year's revenue growth is below x% | -30 to 10 |
| `fcf_ttm_negative` | TTM free cash flow is below zero | none |
| `net_debt_to_ebitda_above` | net debt / EBITDA is above y | 1 to 6 |
| `dilution_above` | the diluted share count grows more than z% a year | 1 to 10 |
| `gross_margin_below` | the newest fiscal year's gross margin is below m% | 0 to 90 |
| `guidance_cut` | a grounded filing fact says guidance was cut | none |
| `customer_loss` | a grounded filing fact says a material customer was lost | none |

`insider_selling_cluster` (in the spec's menu) is not built: there is no Form 4 feed yet.
```

  `.claude/skills/value/reference/sector-rules.md`:

```markdown
# Sector rules (spec §6.4-§6.5)

- **Banks and insurers:** no FCF methods; fair value is justified P/TBV = (ROTE - g) / (r - g) x
  tangible book per share. Their own health set: profitable 4 of 5 years, ROTE median >= 10% with
  sd <= 4 points, tangible book growing, charge-offs not above 1.5x their median, combined ratio
  (insurers). Claude's driver is a sustainable ROTE within 4 points of the 5-year median.
- **Cyclicals** (sector list, or volatile FCF margins): judged across the cycle, valued on the
  5-year median FCF margin times TTM revenue, so a trough year does not fail them.
- **REITs:** not applicable (FFO is not reliably tagged). **Pre-profit:** ineligible; only the
  reverse-DCF line is shown.
```

  `.claude/skills/value/reference/reverse-dcf-reading.md`:

```markdown
# Reading the reverse DCF (spec §6.5, method B)

The scorecard's `reverse_dcf_implied_growth` is the ten-year FCF/share growth (fading to 2.5%, at
9%) the price assumes. Set it beside `realised_fcf_ps_cagr`: a price that implies more than 0.7x
what the company has delivered has "run ahead of earnings", the operator's own words. It is shown,
never a second gate: it is the same fact as "price above fair value B" seen from the other side.
```

  `.claude/skills/value/reference/forensic-checklist.md`:

```markdown
# Forensic checklist for a deep dive (spec §8.2)

Propose a fact only with its accession and a verbatim quote that contains its number; Python drops
anything it cannot find in the filing. Look for: one-off items (asset sales, tax benefits,
restructuring and legal charges), segment revenue, guidance ranges and any cut, backlog, customer
concentration and any lost customer, covenant terms, share-class counts. Units: `USD`,
`USD_thousands`, `USD_millions`, `USD_billions`, `pct`, `count`. Name a canonical XBRL item
(`revenue`, `sbc`, ...) only when the figure is one; Python then checks it against companyfacts.
```

  Then generate `output-schema.json` from the prompts (spec §8.6: the same file the headless prompt
  uses), from the worktree root:

  ```bash
  .venv/bin/python -c "import json; from src.value_ai.prompts import OUTPUT_SCHEMA; print(json.dumps(OUTPUT_SCHEMA, indent=2))" > .claude/skills/value/reference/output-schema.json
  ```

- [ ] **Step 5: Run them to see them pass**

  Run: `.venv/bin/python -m pytest -q tests/test_value_report.py tests/test_value_ai.py` and
  `.venv/bin/python -m py_compile scripts/value_report.py`.
  Expected: PASS; silent.

- [ ] **Step 6: Gates and commit**

  Run: `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the three Python files;
  `.venv/bin/mypy scripts/value_report.py`.

  ```bash
  git add .claude/skills/value scripts/value_report.py tests/test_value_report.py tests/test_value_ai.py
  git commit -m "feat(value): the interactive /value skill and one ticker file as JSON (spec 8.6)"
  ```

---

### Task 13: Docs — the second written exception, the value fence, the folder guide, §19, STATUS

**Files:**
- Modify: `CLAUDE.md` (after the `claude_cut` exception paragraph; the doc-update table's value row;
  the value fence's process bullet and its last bullet), `ARCHITECTURE.md` (`src/research/`,
  `src/common/` and `src/value/` sections, a new `src/value_ai/` section), `SETUP.md` (§19's title
  and intro, a step 9, the scripts table), `STATUS.md` (a Part 4 entry above Part 3's; Part 3's
  limitation line)

The trigger table matches these four files for Part 4's changes (new modules under `src/value/`,
`src/value_ai/`, `src/research/ingest/`, `src/common/`; new keys in `config/examples/value.yaml`; a
new script; a new feature). No Telegram command, command kind, route, top-level directory or
`universe.yaml` change: `README.md`, `docs/web/*`, `How the scan works.md` and
`UNIVERSE_RESEARCH.md` are unchanged (ruling 22).

- [ ] **Step 1: Apply the doc diff:**

```diff
diff --git a/ARCHITECTURE.md b/ARCHITECTURE.md
index d610999..ad2eb9d 100644
--- a/ARCHITECTURE.md
+++ b/ARCHITECTURE.md
@@ -989,11 +989,12 @@ never take the scheduler, or every other registered job, down with it — a hear
 |---|
 | `schemas.py` | The shapes the research layer passes between its own modules: `Fact` (frozen dataclass — one XBRL fact; `start` is `None` for instant/balance-sheet facts), `LineItemValue` (one normalised line item for one period, traceable to its filing via `concept`/`accn`/`filed`/`form`), `PeriodStatement` (every line item for one period), and `NormalizedFinancials` (a filer's annual + quarterly statements). **Roll redesign (2026-10-11):** `PositionSnapshot.con_id` (from `portfolio.get_positions`), `FundamentalStats.dividend_per_share`, `RollOrigin` (the short a roll closes + its chain position) carried as `TradeCandidate.roll_from`, `RollAction`/`RollDecision` (the roll policy's answer: action, stable reason code, candidate, rejection counts, human detail), and `CloseReason.DEFENSIVE` (operator-tapped close from a roll-policy `close` card). **Web Home follow-ups (2026-10-15):** `IncomeTarget` (`off` / `fixed` / `pct_of_account` / `pct_of_amount`, validated so a stored row can never disagree with itself; `MonthPay` gained `target_mode`/`target_amount`/`target_base`), `DayTrade` with `DayFact`, `DayReview` and `DayRolledTo` (one executed trade as a Home card; money is whole-position USD and positive, unknown is `None`), and `DayCalendarDay`/`MonthCalendar` (a month of daily realised P&L). |
 | `income_target.py` | **Web Home follow-ups (2026-10-15).** The monthly income target's stored form (`system_settings.income_target`, JSON), `parse_income_target`, `resolve_income_target(stored, config_pct)` (a web row wins, an explicit `off` beats the legacy `web.monthly_income_target_pct`, nothing else is none) and `target_value(target, month_start_value)` (`None` when it cannot be worked out, never 0). Pure, so the API reads the row through its own read-only session and `src/storage/system_settings.py` writes it through the drain, both through one reading. Display only: nothing in the trading path imports it. |
-| `store/models.py` | Research-database ORM: the symbol directory (`symbols`), raw EDGAR companyfacts (`company_facts_raw` — carries an `etag` so a 304 is free on re-ingest), normalised line items (`financials` — carries `form` alongside `concept`/`accn`/`filed` so the cache can rebuild `LineItemValue` fully without a network fetch), daily bars (`daily_bars`), delayed quotes (`quotes`), news items (`news_items`), the assembled analysis cache (`analysis_cache`), deterministic check results (`check_results`), AI summaries (`summaries`), watchlists + items, recently-viewed, the ingest job queue (`ingest_jobs`), and the single-row `worker_heartbeat` (`beat_at`, `last_job`) written only on a successful job. 14 tables. Value book Part 3 adds `filing_index` (one row per recent 10-K/10-Q/20-F/40-F/8-K from a filer's EDGAR submissions feed: form, dates, 8-K item tags, the going-concern read) and `submissions_state` (each feed's last read and ETag); the job kinds are `fundamentals`, `prices`, `submissions` and `going_concern`. |
+| `store/models.py` | Research-database ORM: the symbol directory (`symbols`), raw EDGAR companyfacts (`company_facts_raw` — carries an `etag` so a 304 is free on re-ingest), normalised line items (`financials` — carries `form` alongside `concept`/`accn`/`filed` so the cache can rebuild `LineItemValue` fully without a network fetch), daily bars (`daily_bars`), delayed quotes (`quotes`), news items (`news_items`), the assembled analysis cache (`analysis_cache`), deterministic check results (`check_results`), AI summaries (`summaries`), watchlists + items, recently-viewed, the ingest job queue (`ingest_jobs`), and the single-row `worker_heartbeat` (`beat_at`, `last_job`) written only on a successful job. 14 tables. Value book Part 3 adds `filing_index` (one row per recent 10-K/10-Q/20-F/40-F/8-K from a filer's EDGAR submissions feed: form, dates, 8-K item tags, the going-concern read) and `submissions_state` (each feed's last read and ETag); the job kinds are `fundamentals`, `prices`, `submissions` and `going_concern`. Part 4 adds `filing_sections` (the sliced sections of a filing a filing read needs) and the job kind of the same name. |
 | `store/session.py` | Engine + session factory for `data/research.db` (`get_research_engine`, `init_research_db`, `research_session` context manager). WAL mode + `foreign_keys=ON`, matching the trading database, so the API can read while a worker writes. `init_research_db()` also backfills columns a later milestone added to an already-existing table (`ALTER TABLE ... ADD COLUMN` against a diff of the ORM metadata vs `PRAGMA table_info`) — `create_all()` alone only creates missing tables, so a database file left over from an earlier milestone would otherwise keep the old schema and raise `OperationalError: no such column`. No migration framework in this project; this is deliberately the minimal fix. |
 | `ingest/symbols.py` | `refresh_symbol_directory() -> int` — upserts the SEC filer directory from `get_symbol_directory_provider()` into `symbols`. An upsert (not truncate-and-reload) so locally enriched columns (`sector`, `industry`, `is_etf`) survive a refresh; a failed fetch (empty list) leaves existing rows intact rather than emptying the table search depends on. Returns the provider-sourced row count only. **After** the provider upsert, it also seeds `config/symbol_directory_overrides.yaml` (2026-09-13) — a small hand-maintained list for tickers EDGAR's directory omits entirely (verified against both `company_tickers.json` and `company_tickers_exchange.json`: leveraged/inverse ETFs like `TQQQ`/`SOXL`/`UPRO`, share classes of a shared trust CIK rather than individually-registered filers, appear in neither). An override is inserted only when the symbol has no row yet from the provider or a prior run — it never overwrites one, so real EDGAR coverage always wins going forward — and carries no `cik` (there isn't one to give it) and `is_etf: true`. This step runs even when the provider fetch itself failed, since the override list has no network dependency. |
 | `ingest/concepts.py` | XBRL fact parsing and concept resolution. `LineItemSpec` (Pydantic) maps a canonical line item to an ordered list of us-gaap concept candidates and a `kind` (`duration` for start+end facts — income/cash flow, `instant` for end-only — balance sheet). `load_concept_map()` reads and caches `config/research_concepts.yaml` — adding a mapping is a config change, not a code change. `parse_facts()` skips malformed entries individually (one bad date in a filer's history must not cost the other forty facts). `resolve_line_item()` pools facts across **every** candidate concept in the list rather than stopping at the first one with any data — a filer can switch which us-gaap tag it reports a line item under between fiscal years (NVIDIA tags revenue `RevenueFromContractWithCustomerExcludingAssessedTax` for FY19-22 and `Revenues` for FY23-26; stopping at the first match used to silently drop the other tag's periods entirely), so each `Fact` now carries its own `concept` and `select_periods()`'s existing latest-`filed`-wins rule is what arbitrates the rare case where two aliases both report the same period. Returns `None` when no alias has any facts (honest absence — the caller renders UNKNOWN, never a zero). `select_periods()` picks one fact per period, newest first, with two correctness rules: `kind` is enforced (summing four quarterly durations into "total assets" produces plausible nonsense), and ties on `end` are broken by the **latest `filed`**, so a restatement becomes the current answer instead of silently reverting. `assert_units_supported()` rejects units outside `{USD, USD/shares, shares, pure}` — a EUR revenue silently treated as USD is worse than no number at all. `select_periods(..., as_of=)` keeps only facts filed on or before `as_of` (point in time, value book §6.2); `select_ttm` gives trailing twelve months as fiscal year + this year-to-date − last year's (10-Q cash flows are year-to-date). |
 | `ingest/submissions.py` | **Value book Part 3 (spec §7.1, §8.5).** The `submissions` job: `parse_submissions(payload, since=)` keeps a filer's 10-K/10-Q/20-F/40-F (and amendments) and 8-K filings of the last `KEEP_DAYS` (400) with their item tags; `ingest_submissions(symbol, cik)` upserts them into `filing_index` (ETag-reused through `submissions_state`; a 304 stamps the read; a failure raises so the drain retries: `EdgarClient.get_json_status` tells a failure from a 304 and `get_submissions` returns `({}, None)` on a failure, so a stored ETag cannot pass it off as unchanged). No text is read. |
+| `ingest/filing_sections.py` | **Value book Part 4 (spec §8.5).** The `filing_sections` job, for the names in `data/value_filing_reads.json` (held and READY names): the newest periodic filing's primary document is cut into Items 1, 1A and 7 (10-K), Item 2 (10-Q) or Items 4 and 5 (20-F), each the longest span from its heading to the next (the table of contents names every item too) and capped, into `filing_sections`; read once per filing. |
 | `ingest/going_concern.py` | **Value book Part 3 (spec §7).** The `going_concern` job, for the names the shadow record holds: each unread recent periodic filing's primary document is read once (`MAX_PER_JOB` 2 a job) and `detect_going_concern` looks for a sentence that **asserts** substantial doubt about the ability to continue as a going concern ("raise(s/d)", no hedge or negation: could, may, if, whether, no, not, alleviated, evaluated…); only the flag and the sentence are stored on `filing_index`. |
 | `ingest/fundamentals.py` | `normalize(payload, symbol)` turns a companyfacts document into `NormalizedFinancials` (annual + quarterly `PeriodStatement`s, newest first); unmapped line items are absent, never zero. `load_cached_financials(symbol)` rebuilds `NormalizedFinancials` from the `financials` table alone — the **warm path**: no network, no SEC fetch, no re-normalisation. `ingest_fundamentals(symbol, cik)` is the **cold path**: fetches via `get_filings_provider()` honouring the cached ETag (a 304 reuses the cached raw payload rather than treating it as "no facts"), caches the raw payload in `company_facts_raw` (so normalisation is replayable when the concept map gains a mapping), normalises, and persists `FinancialRow`s (carrying `form` so the cache can rebuild `LineItemValue` fully) — replacing the symbol's rows wholesale so a re-ingest leaves exactly one row per (period, line item). Returns `None` when the filer has no XBRL facts (ETFs, foreign filers). |
 | `ingest/materialize.py` | Cold-tier materialisation with a wall-clock budget. `SectionState` (`ready`/`pending`/`unavailable`), `MaterializeResult`, `materialize(symbol, *, budget_seconds)` — **cache-first**: a warm view serves from `load_cached_financials` with no SEC fetch; only a cache miss calls `ingest_fundamentals` inside `research.tiers.materialization_budget_seconds` (default 8s). A finished ingest is always `READY` with its data, even if it overran the budget (a background `IngestJobRow` is queued so the *next* view is instant; `PENDING` never carries data — the old PENDING-with-data contract caused the client to poll and re-fetch indefinitely). `reason` is a fixed user-facing string, never `str(exc)` — an exception carrying a CIK or transport detail must not reach the browser. `enqueue()` deduplicates on `(symbol, kind, pending)`. `drain_ingest_jobs()` runs queued jobs, records the error and increments `attempts` on failure, and gives up at `MAX_ATTEMPTS=3` (`status=failed`). M4 adds the enrichment sections (`_technicals`/`_sentiment`/`_news`/`_quote`) each guarded by `_section()` so one outage cannot cascade — a sentiment failure leaves technicals rendering; a news outage leaves sentiment rendering; and so on. Sentiment is enrichment-tier and is never passed into technicals or fundamentals (a structural test inspects `materialize`'s source to enforce this). `_quote()` returns `(price, as_of, reason)` — `MaterializeResult.quote_as_of` carries the warm-tier `QuoteRow`'s actual capture time through to the API layer, which is what lets `GET /research/{symbol}` stamp the quote's `Sourced` value with its real age instead of the request time. M5 (Task 5.5/5.7) adds `metrics`/`checks`/`checks_state`/`checks_reason`: `_checks_metrics()` calls `get_iv_stats`/`get_fundamental_stats` (`src/analytics/`) and `build_metrics()` (`src.research.checks.metrics`) to assemble the flat metrics dict — a failure here degrades to `{}`, never a page failure — and `_checks()` (guarded by `_section()`, same as the other enrichment sources) turns that dict into a `ChecksPayload` via `build_checks_payload()`. `is_etf` is read once alongside `cik` in `materialize()` (same `SymbolRow` query) and threaded through every `_enrich()` call site, since `build_metrics` needs it to skip XBRL extraction and gate the ETF-only fund fields. **`materialize()` distinguishes "no directory row at all" from "a known symbol with no CIK"** (2026-09-13): the former (nothing search or the watchlist could ever have found) returns immediately with only `fundamentals_state=unavailable` set, same as always; the latter (e.g. an override-seeded symbol like `TQQQ` — see `ingest/symbols.py`) still marks fundamentals `unavailable`/`No SEC filer record for this symbol` but proceeds into `_enrich()`, since technicals/sentiment/news/quote/checks need a price and a symbol, never a CIK. Without this split, a symbol the override file makes searchable would still render an entirely blank stock page. `drain_ingest_jobs` runs two job kinds, `fundamentals` and `prices` (the value book's backfill and nightly sweep, 2026-10-29). |
@@ -1035,9 +1036,10 @@ outstanding).
 | `dossier_text.py` | **The one neutral rendering of a ticker dossier (2026-10-22).** `render_dossier` / `render_dossiers`: a *compact* note (about 80 words: kind and health, the story, dated events, up to three key facts) for the many names of a full-scan prompt, and a *full* note (about 220 words: adds the profile, labelled as Claude's general knowledge, every fact that fits and the 7-day news sentiment) for the one name of a deep-dive or a roll. The word budget is enforced here: facts give way first, then extra events, then extra reported figures, then the story is shortened. Figures quoted from the news print on their own line, labelled `Reported in news (not computed by the system)`, never inside the story. A dated event prints as `<id> <title> (title: Claude; date <day> found in <cluster>)`: only the date was checked against the cited news, the title is Claude's, and the line says which is which. Imports only `src.common.schemas`. |
 | `schemas.py` (market picture build, 2026-10-22) | The schemas added by the market picture build: `MarketRegime` (normal / cautious / stressed / crisis: not the per-ticker `Regime`), `RegimeInputs`, `IndexRegime`, `RegimeChange` and `RegimeState` (the persisted regime); `ScaleInZone`, `SizingNote` (how the regime, the leveraged ceiling, the ladder and Claude's cut shaped one CSP: `pre_regime_contracts`, `regime`, `per_trade_cap`, `leverage_tier`, `ceiling_kind`, `floor_lot`, `scale_in`, `bottoming` (`market` or `name`), `vrp_waived`, `claude_suggested` / `claude_reason`) and `SizingContext` (everything the sizer and the gate read), with `TradeCandidate.sizing` and `TradeCandidate.cc_breakout` (`CcBreakout`); `ClaudeReview.max_contracts` / `size_reason` / `backend`; and the news-written `MarketPicture` family (`PictureFact`, `SeasonalityView`, `PictureStory`, `NoiseSummary`, `PictureRegime`) and `TickerDossier` (with `DossierFact`, `DossierEvent` and `DossierReported`). |
 | `config.py` (market picture build, 2026-10-22) | The config classes added by the market picture build: `RegimeCfg` (with `RegimeCspCfg`, `RegimeThresholdsCfg`, `RegimeIntradayCfg`, `RegimeLadderCfg` and `RegimeBottomingCfg`), `LeveragedSizingCfg`, `ClaudeCutCfg` and `CcTimingCfg` / `CcBreakoutCfg` (all `_KeyedCfg`: an unknown key raises) read through `get_regime_cfg()`, `get_leveraged_sizing_cfg()`, `get_claude_cut_cfg()` and `get_cc_timing_cfg()`; `NewsTriageCfg`, `NewsPictureCfg`, `NewsDossierCfg` (with `NewsDossierHealthCfg`) and `NewsLlmCfg.reserved_for_picture`, whose `max_calls_per_day` code default is now 44. |
+| `value_ai_types.py` | Part 4: the plain shapes between `src/value/` and `src/value_ai/` (`AnalystRequest`, `DriverBounds`, `Drivers`, `AnalystReply`, `KillTrigger`, `ProposedFact`, `FilingSection`, `AnalystCall`, `AnalystResult`). Imports only pydantic, so neither package imports the other. |
 | `value_types.py` | The value book's plain input shapes (`ValueFinancials`, `PriceSeries`, `DayBar` (with `high`/`low` since Part 3), `FilingEvent`, `NewsVolume`, `Classification`, `MarketFacts`, `ValueInputs`). Imports only pydantic, so the scorecard, the loader and (Part 6) the API share them. |
-| `value_inputs.py` | The value book's one read-only input loader: research.db opened `mode=ro` (the raw companyfacts payload through `select_periods(as_of=)` / `select_ttm`, daily bars), the regime through `load_regime_state`, fixed-window technicals through `src/analytics/technicals.py`, and `fetch_market_facts` (yfinance market cap, industry, next earnings, through `src/data`). Part 2 adds `build_day_bars` (one session at a time with its technicals, for the exit engine), `newest_bar_before`, `closes_on`, `filings_coverage` and `symbol_is_etf`; Part 3 `filings_between` (the filing index, trigger 4) and `going_concern_flags` (the newest read periodic filing's flag; a name with none read is absent, never "no doubt"), both empty when the research worker has not created `filing_index` yet. Imports no enrichment and no `src.value`. |
-| `value_keep_fresh.py` | The "keep fresh" list (stdlib only): `write_keep_fresh` / `read_keep_fresh` over `data/value_keep_fresh.json`. The value process writes the symbols of its pending/open shadow entries after each night; the research sweep (`value_names`) reads them so a held name that left the universe keeps getting bars and filings. The only channel between the two: no `src.value` import, no `value.db`, no `research.db` write. |
+| `value_inputs.py` | The value book's one read-only input loader: research.db opened `mode=ro` (the raw companyfacts payload through `select_periods(as_of=)` / `select_ttm`, daily bars), the regime through `load_regime_state`, fixed-window technicals through `src/analytics/technicals.py`, and `fetch_market_facts` (yfinance market cap, industry, next earnings, through `src/data`). Part 2 adds `build_day_bars` (one session at a time with its technicals, for the exit engine), `newest_bar_before`, `closes_on`, `filings_coverage` and `symbol_is_etf`; Part 3 `filings_between` (the filing index, trigger 4) and `going_concern_flags` (the newest read periodic filing's flag; a name with none read is absent, never "no doubt"), both empty when the research worker has not created `filing_index` yet. Part 4: `latest_periodic` and `filing_sections` (a filing read's input). Imports no enrichment and no `src.value`. |
+| `value_keep_fresh.py` | The "keep fresh" list (stdlib only): `write_keep_fresh` / `read_keep_fresh` over `data/value_keep_fresh.json`, and (Part 4) `write_filing_reads` / `read_filing_reads` over `data/value_filing_reads.json`, the names to slice filings for. The value process writes the symbols of its pending/open shadow entries after each night; the research sweep (`value_names`) reads them so a held name that left the universe keeps getting bars and filings. The only channel between the two: no `src.value` import, no `value.db`, no `research.db` write. |
 | `value_universe.py` | The value book's trading universe (`would_own` + `watchlist` + the S&P 100 snapshot) and evidence universe (the S&P 500 snapshot), share-class aliases mapped to one ticker. |
 
 **Rule:** Modules never pass raw IBKR objects to each other — they always convert to these shared
@@ -1220,8 +1222,9 @@ clientId.
 ### `src/value/` — The value book (deterministic tier, its own database)
 
 The value book (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`) scores healthy
-companies against what they are worth. **Parts 1–3 (2026-10-29/30) are the scorecard, the
-shadow record and its re-evaluations: nothing in them can place, size or gate an order.** `src/value/` is deterministic, imports no enrichment and
+companies against what they are worth. **Parts 1–4 (2026-10-29/30) are the scorecard, the
+shadow record, its re-evaluations and Claude as the analyst: nothing in them can place, size or
+gate an order.** `src/value/` is deterministic, imports no enrichment and
 no other system, reads `src.research` only through `ingest/concepts.py` and `schemas.py`, and is
 the only writer of `data/value.db` (its own `ValueBase`). Enforced by `tests/test_value_fence.py`.
 
@@ -1235,17 +1238,23 @@ the only writer of `data/value.db` (its own `ValueBase`). Enforced by `tests/tes
 | `valuation.py` | The fading DCF, the reverse DCF, methods A (earnings power), B (haircut DCF), C (absent until point-in-time prices exist), D (growth DCF) and justified P/TBV; fair value = median of the list's methods. |
 | `timing.py` | The earnings window, deep value's strict timing, quality growth's soft timing. |
 | `rank.py` | The cross-sectional rank score per list, the filed list, the run's relative-strength line. |
-| `store.py` | `value.db`: `value_ticker_files` (latest), `value_ticker_history` (append-only), `value_runs`; `record_run` is the one way a script logs a run. Part 2's shadow record: `value_shadow` (one hypothetical entry per READY signal or control-group name, with its 21/63/126-session returns against SPY), `value_shadow_legs` (one per entry and exit policy, the exit engine's state as JSON), `value_shadow_events` (every exit event and fill), `value_ranked` (the ranked monthly portfolios). Part 3: `value_reevaluations` (one row per §7.1 re-evaluation of a shadow entry: triggers, severity, the plan before and after the session's close, the verdict at entry and now; `review_state` waits for Part 4) and a `plan` column (`main` or `original`) on the legs and events, added to an existing database by `init_value_db` (`_ADDED_COLUMNS`). |
+| `store.py` | `value.db`: `value_ticker_files` (latest), `value_ticker_history` (append-only), `value_runs`; `record_run` is the one way a script logs a run. Part 2's shadow record: `value_shadow` (one hypothetical entry per READY signal or control-group name, with its 21/63/126-session returns against SPY), `value_shadow_legs` (one per entry and exit policy, the exit engine's state as JSON), `value_shadow_events` (every exit event and fill), `value_ranked` (the ranked monthly portfolios). Part 3: `value_reevaluations` (one row per §7.1 re-evaluation of a shadow entry: triggers, severity, the plan before and after the session's close, the verdict at entry and now; `review_state` is Claude's, Part 4) and a `plan` column (`main` or `original`) on the legs and events, added to an existing database by `init_value_db` (`_ADDED_COLUMNS`). Part 4, Claude's half: `value_claude_reads` (the queue and every call's model, backend, cost, prompt and reply), `value_claude_verdicts` (the one Claude table the gate reads), `value_claude_notes`, `value_kill_triggers`, `value_claude_facts`, `value_effective` (the effective verdict per name and list, nightly) and `value_claude_state` (the breaker). |
+| `claude_valuation.py` | Part 4, pure (spec §8.2): `bounds_for` (each list's driver bounds from the company's own history: growth -10% to min(30%, realised CAGR + 5 points), terminal 0-2.5%, discount from the list's Python rate to 12%, the normalised FCF margin within 5 points of its 5-year median and never above its best; sustainable ROTE within 4 points for banks and insurers), `clamp_drivers` (records every clamp), `two_stage_dcf` (growth held five years, fading to terminal by year ten), `claude_fair_value` (unreliable above a 75% terminal share; capped at 1.5x Python's fair value, the capped value the one used). |
+| `effective.py` | Part 4, pure (spec §6.7): the effective verdict. Python's NO / UNKNOWN / NOT_APPLICABLE are final; on a healthy name with a usable Claude opinion the verdict is the stricter of Claude's word and what price and timing allow against Claude's fair value (READY > WATCH > WAIT > NO), and Claude's fair value sets the ceiling and the margin. |
+| `claude_verdicts.py` | Part 4: `accept` (one read into rows: verdicts with clamped drivers and the capped value, prose, bounded kill triggers that replace the old set, grounded facts, a review's state on its re-evaluation; between filings a re-read may lower, never raise), `opinions` (each name's latest CLI verdict, its value recomputed on tonight's scorecard; Ollama never), `persist_effective` (`value_effective`), `applies` (paper, or live with `apply_live`, and the breaker not tripped), `night_counts` / `check_breaker` / `reset_breaker` (spec §8.2's breaker over the last 20 nights), `update_kill_triggers` (trigger 6's input). |
+| `claude_reads.py` | Part 4 (spec §8.3, §8.5): the read queue in `value_claude_reads` (requests, reviews, filing reads, the top 15 unread healthy trading names per list, stale re-reads, in that order), the per-ET-day caps, `render_card` (the scorecard as labelled numbers), `build_request` (the model per call kind), `plan_auto_reads`, `plan_filing_reads`, `run_queue` (each read its own transaction, through a reader the entrypoint passes; it never imports Claude). |
+| `kill_triggers.py` | Part 4, pure (spec §8.4): each menu predicate on tonight's scorecard: fired, near (within `kill_near_pct`, trigger 6), far or unknown; the fact-based kinds fire on a grounded filing fact. |
+| `grounding.py` | Part 4, pure (spec §8.2): a proposed fact is kept only if its quote is verbatim in the sliced filing, its number is in the quote, and an XBRL item matches companyfacts for that accession within 0.5%. |
 | `ticker_file.py` | Writes the latest row and history (a full row on any verdict, fair value, margin band or gate change; a compact row once a session); `is_fresh` compares fingerprints. |
 | `funnel.py` | The calibration dry run's pass funnel and per-name detail. |
 | `ruleset.py` | The ruleset fingerprint: `ruleset_version` + a hash of the `rules:` block; `FROZEN` pins a frozen version's hash (v1: the entry rules; v2: v1 + `rules.exits`). |
 | `exits.py` | The exit engine (spec §7), pure: one `LegState` per policy (`full`, `value` — the pre-registered live policy — and `hold12`), stepped once a session on the close; a sale fills at the next open. Every exit that would send reads Python's fair value (`full`'s peak signal and its 2 x ATR tightening included); the half-sale reads the effective one; an exit only the effective (Claude) value would fire is a `proposal`. Fair value is re-marked only on a new accession, and the static "value below 90% of the price, price under SMA50" thesis rule fires only on such a re-mark session. A leg also keeps its last stepped close for the rebase. Part 3 (v3): a session's `Reeval` (from `reevaluate.plan_actions`) applies an 8-K thesis exit under every policy and, under `full` only, the down-shock stop floor and the up-shock trail arm, at the close; a going-concern doubt in the filing is a thesis exit; the F-score exit counts unknown components against it (M5); the Altman Z exit is read only when a new filing lands (M6); the effective-only proposal is noted once per episode (M14); `LegState.rebased(ratio)` scales every price level. |
 | `residuals.py` | Part 3, pure: the sector-ETF residual model of triggers 1–2 (spec §7.1): alpha and beta over the 250 aligned returns before the day, the residual's sd over the last 60, the day's z and the 5-session drift z (fitted before the drift window); too short a history leaves the raw move. |
-| `reevaluate.py` | Part 3, pure: `session_triggers` (the move, drift, earnings, filing, news, regime and quiet triggers with their severities; trigger 6 waits for Part 4's kill-triggers), `regime_stepped`, `severity`, `joins` (the three-session debounce), `plan_actions` (a Major move is a shock, a Major 8-K item a thesis exit; nothing else changes a level). |
+| `reevaluate.py` | Part 3, pure: `session_triggers` (the move, drift, earnings, filing, news, kill (trigger 6, Part 4: a Claude-chosen kill trigger near firing, plain data like news), regime and quiet triggers with their severities), `regime_stepped`, `severity`, `joins` (the three-session debounce), `plan_actions` (a Major move is a shock, a Major 8-K item a thesis exit; nothing else changes a level). |
 | `ranked.py` | The ranked monthly record's arithmetic, pure: the top and bottom tenth and the whole list, equal-weight returns with dropped members counted, the first-run-of-the-month formation. |
-| `shadow.py` | The shadow record (spec §6.8, §12): READY entries and control groups at the next session's open, the three legs, fixed-horizon returns against SPY from the bars as they stand, the ranked record's formation and close. Part 3: `rebase` multiplies every recorded price level of an entry and its legs by the ratio the provider rewrote its bars by (a split or a dividend adjustment; Part 2's `rebase_needed` entries are re-opened), and `step_legs` checks each session of a READY entry's main legs for §7.1's triggers, records `value_reevaluations`, applies the plan actions and, from the first trigger, steps an `original` twin of every leg with none; tonight's facts are read on the session dated as_of only (M1); controls are never frozen (M7); SPY's entry price is read from the bars as they stand (M8). Writes `value.db`; reads `research.db` through `value_inputs`. Baseline track only until Part 4. |
-| `service.py` | The value process's nightly run: `plan_run` (a settled SPY session not yet scored, after `service.run_hour_et`, once the sweep has filings for `min_filings_coverage_pct` of the universe), `run_nightly` (score both universes, the followed names and every shadow name; persist the ticker files with a session history row; run the shadow record; log `value_runs`, all in one transaction), `startup_check`. Part 3: `RunPlan.positions` (the open READY entries the feed reads news for), `previous_regime` (trigger 7 steps from it), and `run_nightly(recent_earnings=, news=)`. |
-| `report.py` | The report, pure: fixed-horizon returns with errors clustered by entry date, the go-live line (spec §12), the three policies side by side, the re-evaluations with each policy's re-evaluated plan against the original (Part 3), the ranked record, and a postmortem per closed position with the gate closest to wrong (spec §11). |
+| `shadow.py` | The shadow record (spec §6.8, §12): READY entries and control groups at the next session's open, the three legs, fixed-horizon returns against SPY from the bars as they stand, the ranked record's formation and close. Part 3: `rebase` multiplies every recorded price level of an entry and its legs by the ratio the provider rewrote its bars by (a split or a dividend adjustment; Part 2's `rebase_needed` entries are re-opened), and `step_legs` checks each session of a READY entry's main legs for §7.1's triggers, records `value_reevaluations`, applies the plan actions and, from the first trigger, steps an `original` twin of every leg with none; tonight's facts are read on the session dated as_of only (M1); controls are never frozen (M7); SPY's entry price is read from the bars as they stand (M8). Writes `value.db`; reads `research.db` through `value_inputs`. Part 4 adds the `claude` track while `value.claude.enabled`: trading names entered on the effective verdict with Claude's opinion applied (whatever the breaker or the live switch say, so the record measures Claude), Claude's recomputed fair value reaching the legs' half-sale only, and trigger 6 from the kill triggers. |
+| `service.py` | The value process's nightly run: `plan_run` (a settled SPY session not yet scored, after `service.run_hour_et`, once the sweep has filings for `min_filings_coverage_pct` of the universe), `run_nightly` (score both universes, the followed names and every shadow name; persist the ticker files with a session history row; run the shadow record; log `value_runs`, all in one transaction), `startup_check`. Part 3: `RunPlan.positions` (the open READY entries the feed reads news for), `previous_regime` (trigger 7 steps from it), and `run_nightly(recent_earnings=, news=)`. Part 4: the night also computes Claude's opinions, writes `value_effective`, checks the breaker, evaluates the kill triggers, queues tomorrow's automatic and filing reads, and writes `data/value_filing_reads.json` for the research sweep. |
+| `report.py` | The report, pure: fixed-horizon returns with errors clustered by entry date, the go-live line (spec §12), the three policies side by side, the re-evaluations with each policy's re-evaluated plan against the original (Part 3), the ranked record, a postmortem per closed position with the gate closest to wrong (spec §11), and (Part 4) `claude_section`: Claude's track beside the baseline's per list and the breaker's two rates. |
 | `backtest.py` | Part 3, Stage 1b (spec §12): Python's rules point in time. On the first session of each month every name is scored on the filings first filed by then and the bars up to then; READY entries are marked at 21/63/126 sessions against SPY and the ranked tenths held to the next formation, all printed by `report.py`'s sections under the caveats (survivorship twice, the earnings-date and market-cap stand-ins, a normal regime, today's classification, prices adjusted for later dividends, no Claude). The bars are split-adjusted while the filings are as filed, so `split_filing_dates` finds the filings whose diluted share count jumps by 1.8x or more against the period before, and a name is not scored at any formation that precedes such a filing (counted per name and printed in the caveats). No I/O of its own. |
 
 **The value process** (`scripts/run_value.py`, Part 2) holds no IBKR connection and no clientId: it
@@ -1266,6 +1275,26 @@ Inputs come from `src/common/value_inputs.py` (read-only) in the plain shapes of
 `src/common/value_types.py`; the universes from `src/common/value_universe.py`. The research
 worker owns every SEC and price fetch for it.
 
+**Claude's reads (Part 4)** run in the same process after the night, with `value.claude.enabled`:
+`scripts/run_value.py` (the only importer of `src/value_ai/`) passes `claude_reads.run_queue` a
+reader that calls the analyst, and the operator queues a read with `python -m scripts.value_claude
+--read SYMBOL` (also `--reset-breaker`). `python -m scripts.value_report --symbol SYMBOL --json`
+prints one ticker file (both halves, labelled) for the interactive skill `.claude/skills/value/`.
+
+### `src/value_ai/` — Claude as the value book's analyst (enrichment)
+
+Part 4 (spec §8). Imports nothing from `src.value`, the trading path, `src.notify`, `src.ledger`,
+`src.storage` or `src.research`; reaches Claude only through `src.claude.cli` (slim, from
+`value.claude.workdir`, outside the repo); reads `news.db` only through the read-only engine and
+`queries`. Its in- and outputs are the plain shapes of `src/common/value_ai_types.py`.
+
+| File | What it does |
+|---|---|
+| `context.py` | `gather`: the name's dossier (rendered by `src/common/dossier_text.py`), its pile 1-2 news clusters of the last 30 days and its earnings dates; never raises (`unavailable` names what is missing). |
+| `prompts.py` | `PROMPT_VERSION`, `OUTPUT_SCHEMA` (no field for a price, a fair value, a strike or a size; the skill's `reference/output-schema.json` is generated from it), `build_prompt` for the standard, review and filing reads. |
+| `parse.py` | `parse_reply`: strict JSON, name by name; a standard read with no valid verdict or a review with no state is no notes. |
+| `analyst.py` | `Analyst.read`: one `claude -p` call (the model per call kind comes on the request); with `value.claude.ollama_fallback` a failed call is answered by Ollama and labelled `backend="ollama"`, which `src/value/` never lets decide anything. Never raises. |
+
 ### `src/ops/` — The out-of-process watchdog and the Gateway restarter
 
 **Scan-loop remediation Task 5.** Everything else in this repo that watches for trouble —
diff --git a/CLAUDE.md b/CLAUDE.md
index 8d220c8..5513324 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -54,7 +54,7 @@ row that matches:
 | **New module under `src/reporting/`** | `ARCHITECTURE.md` folder guide · root `CLAUDE.md` analytics-tier section |
 | **New module under `src/news/`** or a new key in `config/examples/news.yaml` | `ARCHITECTURE.md` `src/news/` section · `SETUP.md` §17 News thread if operator-facing · root `CLAUDE.md` news-fence section if it changes what the package may import |
 | **New module under `src/spreads/`** or a new key in `config/examples/spreads.yaml` | `ARCHITECTURE.md` `src/spreads/` section · `SETUP.md` §16 if operator-facing · root `CLAUDE.md` spreads-fence section if it changes what the package may import |
-| **New module under `src/value/`** or a new key in `config/examples/value.yaml` | `ARCHITECTURE.md` `src/value/` section · `SETUP.md` §19 if operator-facing · root `CLAUDE.md` value-fence section if it changes what the package may import · a `rules:` key also bumps `ruleset_version` once v1 is frozen |
+| **New module under `src/value/` or `src/value_ai/`** or a new key in `config/examples/value.yaml` | `ARCHITECTURE.md` `src/value/` section · `SETUP.md` §19 if operator-facing · root `CLAUDE.md` value-fence section if it changes what the package may import · a `rules:` key also bumps `ruleset_version` once v1 is frozen |
 
 The goal: a user reading `README.md` or `ARCHITECTURE.md` should always get an accurate picture
 of the current codebase, not a stale one.
@@ -115,6 +115,23 @@ Claude still never places, prices, gates any other field, or touches a close, a
 covered call. Every override is recorded in `sizing_actions` (`scripts/sizing_report.py`) and
 reviewed by a human before the live cutover.
 
+**A second written exception: Claude's value verdict (operator decisions 2026-10-28/29 —
+`docs/superpowers/specs/2026-10-28-value-swing-book-design.md` §8.2, §18).** On a name that passed
+every Python health, earnings-quality, list-entry and data gate, Claude's validated verdict decides
+the value book's effective verdict (READY / WATCH / WAIT / NO), bounded by Python's price and timing
+gates, and its fair value replaces Python's in the entry ceiling and the margin of safety, and from
+Part 5 the size tier and the wheel's value-suggested put ceiling. That fair value is never a number
+Claude typed: Claude returns drivers, Python clamps each into a bound taken from the company's own
+filed history, does the arithmetic and caps the result at 1.5x Python's own
+(`src/value/claude_valuation.py`). It is applied in paper and **record-only in live**
+(`value.claude.apply_live: false`) until the go-live review has read the Claude-vs-baseline record;
+a breaker stops it applying when Claude's READYs run away from the baseline's or the cap binds too
+often; an Ollama-produced verdict, a malformed reply or a missing driver means Python's baseline.
+Claude never lifts a name over a gate, sets a price, a strike or a size directly, moves a stop, or
+causes an automatic sale (an exit only Claude's value would fire waits for a tap). Every verdict is
+recorded in `value_claude_verdicts` beside Python's baseline, and the `claude` shadow track measures
+it (`python -m scripts.value_report`).
+
 ## The fence — the enrichment learning loop may not touch the deterministic layer
 
 `src/claude/eval/` closes a read-only feedback loop around Claude's reviews: an **outcome ledger**
@@ -393,8 +410,16 @@ the value book. It is **deterministic tier**:
 - The value process (`scripts/run_value.py`, Part 2) holds no IBKR connection: it hands
   `src/value/` earnings dates from `news.db` and yfinance market facts as plain data
   (`scripts/value_feed.py`), so `src/value/` never imports `src.news` or `src.data`. It is the only
-  module that may import `src.value_ai` (Part 4), it is never imported itself, and its whole
-  process loads no wheel layer, no Claude and no `ib_async` (a `sys.modules` test).
+  module that imports `src.value_ai` (Part 4), it is never imported itself, and `src/value/` with
+  its feed loads no wheel layer, no Claude and no `ib_async` (a `sys.modules` test).
+- **`src/value_ai/` (Part 4) is enrichment** (on `tests/test_eval_skills.py`'s list): Claude as the
+  analyst. It reaches Claude only through `src.claude.cli` (slim, from `value.claude.workdir`,
+  outside the repo), reads `news.db` only through `src.news.store.readonly` and `queries`, and
+  imports nothing from `src.value`, the trading path, `src.notify`, `src.ledger`, `src.storage` or
+  `src.research`. It returns plain data (`src/common/value_ai_types.py`, pydantic only); `src/value/`
+  bounds, computes, clamps, grounds (`grounding.py`) and stores it, and reads its reads' cost and
+  priority itself (`claude_reads.py`). Importing the analyst loads `src.claude.cli` alone from the
+  reasoning layer (a `sys.modules` test).
 - The exit engine (`src/value/exits.py`) is pure; every exit that would send reads Python's fair
   value (the half-sale target alone reads the effective one), and an exit only Claude's value would
   fire is a tap proposal (spec §7, revision 3). That covers `full`'s peak signal and its 2 x ATR
@@ -412,8 +437,9 @@ the value book. It is **deterministic tier**:
   re-evaluation. The EDGAR filing list and the going-concern read are research-worker jobs
   (`src/research/ingest/submissions.py`, `going_concern.py`); `src/value/` reads their table only
   through `src/common/value_inputs.py`.
-- Parts 1–3 place, size and gate nothing: every shadow row is hypothetical. The written exception
-  for Claude's value verdict (spec §8.2, §18) is added with Part 4.
+- Parts 1–4 place, size and gate nothing: every shadow row is hypothetical. Claude's verdict (the
+  second written exception under the core invariant) decides the effective verdict, the `claude`
+  shadow track and `value_effective`; Part 5 is the first part where it can reach an order.
 
 Enforced by `tests/test_value_fence.py` — keep it green.
 
diff --git a/SETUP.md b/SETUP.md
index 3eee0d0..9b18062 100644
--- a/SETUP.md
+++ b/SETUP.md
@@ -2031,13 +2031,13 @@ that survived checking.
 
 ---
 
-## 19. The value book, Parts 1–3: the scorecard, the nightly process, the shadow record and its re-evaluations
+## 19. The value book, Parts 1–4: the scorecard, the nightly process, the shadow record, its re-evaluations and Claude as the analyst
 
 The value book scores healthy companies against what they are worth
 (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`). Part 1 is the scorecard and
 a one-off **calibration dry run**; Part 2 adds a nightly process and the **shadow record**; Part 3
-adds **re-evaluations** (spec §7.1) and **Stage 1b**, the point-in-time backtest. None of them
-places an order or sends a message.
+adds **re-evaluations** (spec §7.1) and **Stage 1b**, the point-in-time backtest; Part 4 adds
+**Claude as the analyst** (spec §8). None of them places an order or sends a message.
 
 1. `cp config/examples/value.yaml config/value.yaml` (git-ignored; every key has a code default).
 2. The research worker refreshes the value universes nightly (`research_sweep.enabled`, on since
@@ -2083,6 +2083,24 @@ places an order or sends a message.
    It reads `research.db` read-only and caches ten years of bars in `data/value_backtest/`
    (`--bars research` uses only what research.db holds; `--limit N` or `--names A,B` for a quick run).
    The full evidence universe takes a while and fetches ~500 price histories the first time.
+9. **Claude as the analyst (Part 4).** `ruleset_version` becomes `v4` (v3 + `rules.claude`: the
+   driver bounds, the 1.5x clamp, the kill-trigger ranges): refresh the private copy
+   (`cp config/examples/value.yaml config/value.yaml`) before restarting. Claude reads are **off**
+   until you set `claude.enabled: true` in `config/value.yaml` (they spend your subscription's
+   tokens: at most `standard_reads_per_day` 15 and `deep_reads_per_day` 3, Sonnet by default). Then,
+   after each night, the value process reads the top 15 healthy trading names per list Claude has not
+   read (and re-reads a name when a new filing lands, Python's fair value moves more than 5%, or the
+   verdict is a month old), and a filing read of each READY name's newest 10-K/10-Q once the research
+   worker has sliced it. Claude picks a verdict and valuation drivers; Python bounds the drivers,
+   computes the fair value and caps it at 1.5x its own. On a healthy name Claude's verdict becomes
+   the **effective** verdict (in paper; in live only with `claude.apply_live: true`), recorded in
+   `value_effective`, and a `claude` shadow track runs beside the baseline. A breaker stops Claude's
+   verdict applying if its READYs run past 3x the baseline's or the cap binds on more than 25% of its
+   values; `python -m scripts.value_claude` shows the breaker, today's budget and the queue,
+   `--read SYMBOL` queues a read (run at the next poll) and `--reset-breaker` lets Claude's verdict
+   apply again. `python -m scripts.value_report` prints Claude's track beside the baseline's. In
+   Claude Code, `/value SYMBOL` runs the interactive skill (`.claude/skills/value/`), which reads
+   `python -m scripts.value_report --symbol SYMBOL --json`.
 
 ### Scripts
 
@@ -2092,7 +2110,8 @@ places an order or sends a message.
 | `python -m scripts.value_dry_run run [--as-of DATE] [--names A,B] [--limit N] [--no-persist] [--out cards.json] [--report report.txt]` | Scores every name, ranks both lists, writes `data/value.db`, prints the funnel. |
 | `python -m scripts.value_universe_snapshot` | Rebuilds the two committed universe CSVs from Wikipedia. |
 | `python -m scripts.run_value` | The value process. Normally started by `scripts.start` / `./ibkr restart`; `--no-value` skips it. Logs to `logs/value.log` (`./ibkr logs value`). |
-| `python -m scripts.value_report [--track baseline] [--universe all\|trading\|evidence] [--ruleset V] [--postmortems]` | Prints the shadow record from `data/value.db` (read only). |
+| `python -m scripts.value_report [--track baseline\|claude] [--universe all\|trading\|evidence] [--ruleset V] [--postmortems]` | Prints the shadow record from `data/value.db` (read only), with Claude's track beside the baseline's (Part 4). `--symbol NVDA --json` prints one ticker file. |
+| `python -m scripts.value_claude [--read SYMBOL] [--reset-breaker]` | Claude's side of the value book (Part 4): the breaker, today's read budget and the queue; queues a read; resets the breaker. |
 | `python -m scripts.value_backtest [--universe evidence\|trading] [--names A,B] [--limit N] [--start D] [--end D] [--bars provider\|research] [--refresh] [--out F]` | Stage 1b: the point-in-time backtest of Python's rules (Part 3). |
 
 ## Troubleshooting
diff --git a/STATUS.md b/STATUS.md
index 59d6847..2f26fcc 100644
--- a/STATUS.md
+++ b/STATUS.md
@@ -347,6 +347,34 @@ MCP so the headless `claude -p` subprocess can do ad-hoc lookups (`ib_portfolio`
 
 ---
 
+## Built (2026-10-30 — value book Part 4: Claude as the analyst)
+
+Plan: `docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md`. Record-only: no order,
+no Telegram, no web, no IBKR connection.
+
+- `value_rules: v4` = v3 + `rules.claude` (driver bounds, the 1.5x clamp, kill-trigger ranges,
+  trigger 6's nearness), frozen at `be30d1eaa915`; v1-v3 still hash as pinned.
+- `src/value_ai/` (enrichment): the analyst, through the slim `src.claude.cli` from
+  `value.claude.workdir`; versioned prompts with one output schema (shared with the skill); strict
+  parsing; an Ollama fallback that is labelled and never decides.
+- `src/value/`: Claude's fair value computed by Python from bounded drivers and capped
+  (`claude_valuation.py`); the effective verdict (`effective.py`, `value_effective`); acceptance,
+  the between-filings rule, opinions recomputed nightly, the breaker (`claude_verdicts.py`); the
+  read queue with priorities and per-day caps (`claude_reads.py`); kill triggers evaluated nightly
+  and trigger 6 (`kill_triggers.py`); grounded facts (`grounding.py`); the `claude` shadow track and
+  the report's Claude-vs-baseline section.
+- The research worker's `filing_sections` job (the newest 10-K/10-Q of held and READY names, sliced).
+- `scripts/value_claude.py`, `value_report --symbol --json`, the interactive skill
+  `.claude/skills/value/`. Root `CLAUDE.md` carries the second written exception under the core
+  invariant.
+- Known limitations: reads are off until `value.claude.enabled`; the standard read does not read the
+  earnings release itself (the news clusters and, weeks later, the 10-Q's filing read stand in);
+  grounded facts adjust no number yet (they feed `guidance_cut` / `customer_loss` and the display);
+  `insider_selling_cluster` is not on the menu (no Form 4 feed); Claude's review of a held name
+  (§7.1 step 3) is built and tested but has no held name to read until Part 5; the effective verdict
+  is used by nothing that trades until Part 5; cheaper models per call kind wait for the blinded
+  audit (spec §8.5); the claude track opens only while reads are on, so its record starts then.
+
 ## Built (2026-10-30 — value book Part 3: re-evaluation and Stage 1b)
 
 Plan: `docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md`. Deterministic only: no
@@ -372,7 +400,7 @@ order, no Claude, no Telegram, no web, no IBKR connection.
 - Stage 1b: `src/value/backtest.py` and `scripts/value_backtest.py` (ten years of bars, cached in
   `data/value_backtest/`; the yfinance provider gained a 10y period).
 - `value_report` prints the re-evaluations and each policy's re-evaluated vs original plan.
-- Known limitations: trigger 6 (a Claude kill-trigger near firing) waits for Part 4; the hourly RTH
+- Known limitations: trigger 6 (a Claude kill-trigger near firing) waited for Part 4 (built there); the hourly RTH
   check of triggers 1 and 4 and "pause adds" wait for held positions (Part 5); cards for Major and
   Minor re-evaluations wait for Part 6; the residual model needs 120 aligned sessions (the 10% raw
   move stands in before that); a single bar the provider corrects (not a corporate action) is
```

- [ ] **Step 2: Check the docs against the code** — every module named exists:
  `ls src/value/claude_valuation.py src/value/effective.py src/value/claude_verdicts.py src/value/claude_reads.py src/value/kill_triggers.py src/value/grounding.py src/value_ai/analyst.py src/research/ingest/filing_sections.py scripts/value_claude.py .claude/skills/value/SKILL.md`
  prints ten paths; `grep -c "be30d1eaa915" STATUS.md src/value/ruleset.py` prints 1 for each.

- [ ] **Step 3: Commit**

  ```bash
  git add CLAUDE.md ARCHITECTURE.md SETUP.md STATUS.md
  git commit -m "docs: value book Part 4 - Claude as the analyst, and the second written exception"
  ```

- [ ] **Section D exit** — the full gate (pytest = baseline + 77, `ruff check .`, `mypy src`), the
  protected-file diff (empty), `py_compile` of the six value scripts, `git status --short` (clean),
  `ls data/value_filing_reads.json` (fails); fill the Task 13 row and the exit numbers, then:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md
  git commit -m "docs(plan): value book Part 4 Progress log - Section D"
  ```

---

## Whole-branch review · model: opus · effort: high, then one sonnet fix pass · effort: high

- [ ] **R1.** Spawn one **opus** subagent with `effort: "high"`: "Review branch `feat/value-book-4`
  against `main` for correctness, using superpowers:requesting-code-review. Read the plan's
  Rulings, Global Constraints and Review Focus, the spec §§6.7, 7, 7.1, 8 (all), 12, 13, 16, 18, root
  `CLAUDE.md`'s core invariant and value fence, and `git diff main...HEAD`. Check: every Claude
  number is a driver Python clamped into a bound from the company's own history, the arithmetic is
  Python's, the cap is 1.5x Python's fair value and the capped value is the one used, a 75% terminal
  share is unreliable, no Claude value exists without Python's (rulings 4, 5); the effective verdict
  against ruling 4 case by case (Python's NO/UNKNOWN/NOT_APPLICABLE final, the margin and timing on
  Claude's value, the stricter-of rule); between filings a re-read never raises; an Ollama reply,
  a malformed one or a missing driver decides nothing anywhere (opinions, kill triggers, facts,
  review state); `value_effective` honours `apply_live` and the breaker while the `claude` track
  ignores both (ruling 7); the breaker's arithmetic against ruling 8 and that it never resets
  itself; the queue's priorities, caps per ET day and the stale rule (ruling 6: never price
  alone); each read is its own transaction and never runs inside the night's; the headless call
  (slim `cli.build_cmd` via `run_claude`, `value.claude.workdir` outside the repo, the model per
  call kind); kill triggers against ruling 10 and that trigger 6 moves no level; the claude track
  (trading only, no controls, Python's `fair_value` on the entry so every automatic exit reads
  Python's, Claude's value reaching the half-sale only); the filing slicer's false positives
  (a table of contents, Part II's Item 2 of a 10-Q) and that a read waits then drops; grounding
  (verbatim after whitespace only, the number at the quote's precision, the XBRL scale); the
  fences (src/value_ai's imports and its probe, src/value importing no Claude, run_value the only
  importer, the test-isolation of `data/value_filing_reads.json`); the v4 hash and that v4 changes
  no Python rule; the second written exception in `CLAUDE.md` against spec §18; the docs against
  the code. Report Critical / Important / Minor findings with file:line. Do not edit."
- [ ] **R2.** Record the findings in the Progress log. Spawn one **sonnet** subagent with
  `effort: "high"` to fix every Critical and Important finding in **one** commit
  (`fix(value): whole-branch review fixes`), TDD where a finding is a behaviour, with the full gate
  green. A fix that changes a key under `rules:` moves the v4 hash: it must re-run Task 1 Step 4,
  re-pin `FROZEN["v4"]` with the new value (v4 has produced no live row yet), update the hash in
  `STATUS.md`, and say so as a ruling. Minor findings are listed as deferred in the Progress log
  unless trivial.
- [ ] **R3.** Verify the fix commit yourself (log, status, full gate with pytest = baseline + 77 +
  the fix pass's new tests, protected diff, `py_compile` of the six scripts, no
  `data/value_filing_reads.json`), then **ask the operator whether to merge `feat/value-book-4` into
  `main` and whether to push. Do neither without a yes.** Then tell the operator that Part 5's plan
  must be reconciled with this Progress log before it runs (Part 5's entry check A1 says how).

---

## Operator to-dos

**Before Part 4 starts (the orchestrator checks these at A0):**

0. Part 3's to-dos done (HANDOFF §2): `./ibkr restart` onto Part 3, a few real nights of the shadow
   record read (`python -m scripts.value_report`), Stage 1b run (`python -m scripts.value_backtest`).
   At least 8 GiB free (`df -h .`).

**After the merge, before the restart:**

1. Refresh the private config: `cp config/examples/value.yaml config/value.yaml`. A private file
   still saying `ruleset_version: v3` makes the value process idle with a CRITICAL line in
   `logs/value.log` (v3's pin no longer matches rules that include `claude`). Re-apply any key you
   had changed (an entry-rule change is a new version: say so first).
2. Restart: `./ibkr restart`. The research worker creates `filing_sections` on start.

**Turning Claude on (when you are ready to spend the tokens):**

3. In `config/value.yaml` set `claude.enabled: true` (leave `apply_live: false`; it only matters
   in live, which stays off). Optionally pin `claude.models.verdict` etc.; "" uses
   `config/settings.yaml → claude.model`. Restart the value process (`./ibkr restart`).
4. The next night queues up to 15 standard reads a day (the top healthy trading names per list) and
   a filing read of each READY name's newest 10-K/10-Q once the research worker has sliced it
   (`data/value_filing_reads.json` tells it which; the 02:00 sweep after the night). Watch
   `python -m scripts.claude_usage` (call kinds `value_standard`, `value_filing`) and
   `python -m scripts.value_claude` (the breaker, today's budget, the queue). `--read NVDA` queues one
   name for the next poll.
5. Read the record: `python -m scripts.value_report` now ends with "Claude vs the Python baseline";
   `--track claude` prints the claude track alone; `--symbol NVDA --json` prints one ticker file. In
   Claude Code, `/value NVDA` runs the interactive skill.
6. If the breaker trips (`breaker: TRIPPED` in `scripts.value_claude`), Claude's verdict stops
   deciding `value_effective` until you read why and run `python -m scripts.value_claude
   --reset-breaker`. The `claude` track keeps recording either way.

---

## Self-review (run by the plan's author, 2026-10-30)

- **Spec coverage (Part 4's scope).** §8.1 → Tasks 4 (prompts, parse), 5 (stored); every output
  labelled `backend` and kept in Claude's tables. §8.2 drivers, bounds, arithmetic, the 75% check,
  the single clamp rule → Tasks 1, 2; the breaker → Tasks 5, 6; grounded facts → Tasks 10, 11 (they
  adjust no number: ruling 9); "where Claude's fair value reaches" → the effective verdict and the
  claude track here, the size tier and the put ceiling in Part 5; "Paper and live" → Task 5's
  `applies`, Task 13's written exception. §8.3 → Tasks 3 (tables), 6 (the automatic set, requests,
  the stale rule), 11 (filing reads); `VALUE NOTE` → Part 6 (ruling 17). §8.4 → Tasks 5 (bounded on
  acceptance), 7 (evaluated, trigger 6). §8.5 → Task 6 (priorities, caps, models per kind), Task 4
  (Ollama never decides), Task 10 (Python slices the filing). §8.6 → Task 12. §6.7 → Task 3. §6.8's
  two tracks and §12's comparison → Tasks 8, 9. §7.1 trigger 6 → Tasks 7, 8; step 3 (Claude's
  review) → Tasks 5, 6 (built, idle until Part 5). §13 failure mode 5 → the bounds, the clamp, the
  required margin on Claude's value (Task 3), the baseline beside it (Task 8), record-only in live.
  §16's Claude tests → Tasks 2–8, 11. §18 → Task 13.
- **Placeholders.** None in Tasks 1–13: every module and test is given whole or as an exact diff
  and was run green — 5305 + 77 = 5382 passed and 1 skipped, `ruff check .` clean, `ruff format
  --check` clean on every touched file (only the pre-existing `scripts/roll_backtest.py` drift
  remains), `mypy src` clean (338 files) — on a code-only scratch copy of `main` at `da5d3c3`, with
  each section's end state (after Tasks 3, 6, 9 and 13) and Tasks 4 and 5 run on their own. The
  only values a run supplies are the commit counts.
- **Type consistency.** `ValueClaudeRulesCfg` (Task 1) is what `claude_valuation.bounds_for`
  (Task 2), `claude_verdicts.bounded_trigger` (Task 5) and `kill_triggers.check`'s caller (Task 7)
  read; `ValueClaudeCfg` is what `claude_reads` (Task 6), `Analyst.from_config` (Task 4) and the
  breaker (Task 5) read; `value_ai_types` (Task 2) is the only shape crossing between `src/value`
  and `src/value_ai`; `ClaudeOpinion`/`Effective` (Task 3) are what `claude_verdicts.opinions` and
  `persist_effective` (Task 5) and `shadow.open_claude_signals` (Task 8) use; `run_queue`'s reader
  (Task 6) is `scripts/run_value.py::_read`; `FilingSection` (Task 2) is what
  `value_inputs.filing_sections` (Task 10) returns and `grounding.check_fact` (Task 11) reads.
- **Review Focus.** Each of the six lines names the test that pins it.
- **Proportion.** Complete code by the operator's brief; the spec is cited, not restated. New
  modules are given whole; modified files as exact diffs whose anchors the entry checks grep.
