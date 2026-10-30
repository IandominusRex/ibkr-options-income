# Value Book, Part 3: Re-evaluation and Stage 1b — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan **section by section** (one subagent per section, never per task — see "Execution model"). Every section opens with **entry checks** the orchestrator runs itself before it spawns the section's subagent. Each section carries a **model** and an **effort** label; the orchestrator passes both when it spawns. No section of Part 3 touches `web/`; if one ever does, its subagent invokes the `da-vinci` skill first and its prompt says so, and nobody runs `next build` inside `web/`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-evaluate every open shadow position the way spec §7.1 says — a sector-ETF residual
model, EDGAR filings and 8-K item tags, earnings, news volume, the regime and a quiet clock, with a
debounce and a severity — record each re-evaluation, carry the original plan beside the
re-evaluated one, apply `full`'s shock stops and the 8-K and going-concern thesis exits, rebase the
legs mechanically on splits and dividend adjustments (un-freezing Part 2's `rebase_needed`
entries), and build Stage 1b: a point-in-time backtest of Python's rules with its caveats printed.

**Architecture:** The research worker gains two job kinds on the existing `IngestJobRow` queue:
`submissions` (each filer's EDGAR `submissions/CIK*.json` feed → `filing_index` rows with forms and
8-K items, nightly) and `going_concern` (the shadow record's names only: each new 10-K/10-Q read once
for a doubt the filing asserts). `src/common/value_inputs.py` reads that table read-only. In
`src/value/`, two pure modules decide (`residuals.py`: the residual model; `reevaluate.py`:
triggers, severity, debounce, plan actions), the pure exit engine applies a session's `Reeval`, and
`shadow.py` records `value_reevaluations`, steps an `original` twin of every leg from the first
trigger, and replaces Part 2's freeze with a mechanical `rebase`. The value process hands in
earnings dates and news volume as plain data. `src/value/backtest.py` + `scripts/value_backtest.py`
score the frozen rules on the first session of each month over ~8 years. The ruleset becomes
`value_rules: v3` = v2 + `rules.reevaluation`, frozen before the first re-evaluation. Nothing in
Part 3 can place, size or gate an order: every row is hypothetical.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 (SQLite, WAL; `mode=ro` URIs), pandas,
httpx (the research worker's EDGAR client only), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` (revisions 1–3; §19/§20
hold the operator's answers; no open decisions). Part 3 implements §7.1 (all but trigger 6, the
hourly RTH check, Claude's review and the cards: rulings 3–4), §7's going-concern thesis exit, the
§8.5 parsing bullet for the submissions feed and 8-K item tags, §12's Stage 1b, and §16/§18 for
what Part 3 builds. **Part 2's plan** (`docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md`,
on `main`) and its Progress log are the ground truth for the code Part 3 builds on; its Roadmap is
Part 3's scope. Executors read the spec sections each section cites, not the whole spec.

## Execution model

| Section | Tasks | Model | Effort | Why this model | Why this effort |
|---|---|---|---|---|---|
| **Orchestrator** (the main session) | — | **sonnet** | **high** | Runs entry checks, spawns, verifies, asks the operator; writes no product code. | It is the one reader of every subagent's report and the protected-file diff; a missed red gate ships. |
| **A — Ruleset v3, the filings feed, the readers** | 1–3 | **sonnet** | **high** | Every line of code and every test is given; the risk is wiring. | Wires into `config.py`, the frozen ruleset, the EDGAR client, the research worker's drain and sweep, and the neutral loader: a slip moves the frozen hash or breaks the live research worker. |
| **B — The exit engine's Part 3 rules, the re-evaluation logic, the store** | 4–6 | **sonnet** | **high** | Pure functions and pattern-following storage, every number pinned by a test the plan's author ran. | The exit engine is the riskiest logic in the value book (it sells automatically in Stage 3) and the store migrates a live `value.db`. |
| **C — The shadow record's re-evaluations, the process, the report** | 7–9 | **sonnet** | **high** | `shadow.py` rewritten around a per-session loop, the service and feed wiring, the fences, the report. | The per-session loop drives triggers, twins, rebases and legs in one transaction against a live `value.db`. |
| **D — Stage 1b and the docs** | 10–12 | **sonnet** | **medium** | A module with pinned arithmetic, a read-only script and a doc sweep given as text. | Pinned pure functions and pattern-following script and docs. |
| **Whole-branch review** | after D | **opus** | **high** | One review of the whole branch; no per-task reviews. | Reads the triggers, the rebase, the twins and the fences against the spec end to end. |
| **Review fix pass** | after the review | **sonnet** | **high** | Critical/Important findings fixed in one commit. | Fixes land in the riskiest code with the full gate as the only check. |
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

   > You are executing Section [X] of `docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md`
   > in the git worktree `.claude/worktrees/value-book-3` (branch `feat/value-book-3`). Read, in this
   > order: the plan's "Rulings made up front", "Global Constraints" and Section [X] in full; the spec
   > sections Section [X] cites; and only the files its tasks list. Do the tasks in order, TDD as
   > written: each failing test first, then the code, then the gates the task names. Apply each diff
   > with the Edit tool, or save it with the Write tool to a file in your scratchpad (outside the
   > worktree) and run `git apply <that file>` from the worktree root; a new file is written whole
   > with the Write tool. Run pytest from the worktree root. One commit per task, message ending
   > `Co-Authored-By: <your model name> <noreply@anthropic.com>`. After each task tick its checkboxes
   > and fill its Progress-log row (status, commit, gate counts, date, every ruling with its
   > cost-if-wrong) and commit that with the next task (the last task's row goes in a final
   > `docs(plan)` commit). Never import a `scripts.run_*` module; never touch `data/*.db` of the main
   > checkout; never edit a private `config/*.yaml`; never copy `research.db`. If an entry-check fact
   > turns out false mid-task, stop and report instead of improvising. Report: commits, gate counts,
   > rulings, anything left undone.

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
verify it and **ask the operator before merging or pushing**. Part 3 has no calibration section:
Stage 1b and the first real re-evaluations run after the merge and restart (operator to-dos;
ruling 22).

**Counts go stale, so recompute them.** Each section adds one final `docs(plan)` commit and a
Progress-log row beyond its task commits, and the review fix pass adds its own. Never trust a fixed
total in this plan: at every entry check and exit, take the commit count from
`git log --oneline main..HEAD | wc -l` and record it, and state pytest targets as **baseline + N**,
where the baseline is the count recorded at A2 and N is the sum of the "new tests" of the tasks
done so far (File structure lists N per task; 59 in all).

**Commits.** Each task is one commit; Task 1's commit also adds this plan file. Every commit
message ends with the trailer `Co-Authored-By: <model> <noreply@anthropic.com>`, where `<model>`
is the executing agent's own model name.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **A entry checks** | passed | 0 commits (branch at `1dad9dc`) | A2 baseline: pytest 5239 passed, 1 skipped; ruff clean; mypy 320 files; A3 greps all match; A4 hash `d07717fe5348`, no Part 3 code; 34 GiB free | 2026-10-30 | Operator asked to execute the plan; the two "rulings to confirm" (dividend rebase, strict going-concern) are taken at the plan defaults. Plan targets: Section A exit = baseline + 14 = 5253 |
| 1 Ruleset v3: the re-evaluation rules | done | `3c3d25d` | tests/test_value_config + dry_run + service + private_config + scorecard 59 passed; hash printed `ad8841127029` as planned; ruff check/format and mypy (2 files) clean | 2026-10-30 | No deviations. Applied by Edit rather than `git apply`; the plan's diffs were reproduced exactly. Ruling 1 (v3 = v2 + `rules.reevaluation`): cost if wrong is a re-pin before the first v3 night, a v4 after. |
| 2 The research worker's filings feed | done | `c681018` | 86 passed (test_research_submissions 9 new, test_value_universe 13, plus edgar/materialize/store/fundamentals/worker/fence); ruff check/format clean on 9 files; mypy src/data src/research clean (46 files) | 2026-10-30 | No deviations; the plan's code reproduced exactly (value_universe.py written whole, same content as the diff). Rulings 7 (20h submissions age, 400-day keep, ETag), 8 (SPDR eleven + SPY), 9 (P2-M2: refetch the bar on the last weekday, `last <= due`), 5 (strict going-concern pattern; cost if wrong is one regex) applied as written. |
| 3 The readers: filings, the going-concern flag, the day's low | done | `a78750e` | tests/test_value_inputs + shadow + fence 42 passed; ruff check/format clean; mypy clean. **Section A exit full gate:** pytest 5253 passed, 1 skipped (baseline 5239 + 14); `ruff check .` clean; `mypy src` 322 files clean; protected-file diff empty; `py_compile scripts/run_value.py` silent; 3 task commits on `main..HEAD` before this docs commit | 2026-10-30 | No deviations. Ruling 10 (readers tolerate an unmigrated research.db: `{}` on `OperationalError`) implemented and tested. `build_day_bars` reads `bars["high"]`/`["low"]` unconditionally (as the ATR line already did). |
| **B entry checks** | passed | 4 commits on `main..HEAD` | B2: pytest 5253 passed, 1 skipped (baseline + 14); ruff clean; mypy 322 files; FROZEN holds v3 `ad8841127029`; B3/B4 greps all match. Section A protected-file diff empty | 2026-10-30 | Section B exit target: baseline + 39 = 5278 |
| 4 The exit engine's Part 3 rules | done | `ec73f68` | tests/test_value_exits (43 collected) + shadow + fence 70 passed; ruff check/format clean; mypy exits.py clean | 2026-10-30 | No deviations. Applied by `git apply` of the plan's diffs, extracted verbatim. The commit also carried the orchestrator's "B entry checks" row. `LegState` gained `fv_proposed`, `seen_accn`, `trail_floor`, all defaulted so Part 2's stored legs load; `open_leg` seeds `seen_accn=fv_accn`. Cost-if-wrong notes: ruling 14 (shock stop uses the ATR on the bar before; no ATR means no shock stop) and ruling 15 (8-K thesis exit under every policy) are each one branch in `_shock`/`step`. |
| 5 The residual model and the triggers | done | `252b910` | tests/test_value_reevaluate (10) + fence 24 passed; ruff check/format clean on 3 files; mypy residuals.py and reevaluate.py clean | 2026-10-30 | No deviations; the plan's files reproduced exactly (extracted verbatim). Ruling 11 (residual model: 250-session fit before the day, 60-session sigma, min 120 returns, raw 10% backstop): cost if wrong is the `ValueReevaluationCfg` numbers. Ruling 3 (trigger 6 deferred to Part 4): `TriggerKind` has no `kill` member; adding one is a Literal entry. Both new modules are added to the fence's pure list in Task 8. |
| 6 The store: `value_reevaluations` and the plan column | | | | | |
| **C entry checks** | | | | | |
| 7 The shadow record: rebase, re-evaluations, the original twin | | | | | |
| 8 The process: plain data, the regime step, the fences | | | | | |
| 9 The report: re-evaluated against original | | | | | |
| **D entry checks** | | | | | |
| 10 Stage 1b: the point-in-time backtest | | | | | |
| 11 The backtest script and ten years of bars | | | | | |
| 12 Docs | | | | | |
| **Whole-branch review (opus)** | | | | | |
| **Review fix pass (sonnet)** | | | | | |

## Roadmap (this plan is Part 3 of 6)

Each later part is written **after the previous part merges**, so its code matches reality. Every
part runs on this execution model (Sonnet orchestrator, one subagent per section with a model and
an effort, stop-and-ask between sections, one Opus whole-branch review).

- **Part 1 — The scorecard and the calibration dry run.** Merged and pushed (`23b1ef3`);
  `value_rules: v1` frozen at `e1a1b3b096b1`.
- **Part 2 — The value process and the shadow record.** Merged and pushed (`7d37f95`);
  `value_rules: v2` frozen at `d07717fe5348`.
- **Part 3 — Re-evaluation and Stage 1b.** This plan. The `submissions/CIK*.json` job kind and 8-K
  item tags, the sector-ETF residual model, triggers 1–5, 7 and 8 with debounce and severity,
  `value_reevaluations`, the original-plan shadow twin, §7.1's shock stops (under `full` only), the
  mechanical rebase (un-freezing Part 2's `rebase_needed` entries), the going-concern thesis exit
  (a `going_concern` job kind), the 8-K thesis exit, and Stage 1b's point-in-time backtest with the
  survivorship caveat printed. `value_rules: v3`. **Moved out:** trigger 6 (a Claude kill-trigger
  within 10% of firing) to Part 4, which builds Claude's kill-triggers (ruling 3); the hourly RTH
  check of triggers 1 and 4 and "pause adds" to Part 5, the first part with held positions and
  tranches (ruling 4); Major/Minor re-evaluation cards to Part 6 (ruling 4).
- **Part 4 — Stage 2: Claude as the analyst.** As before, plus: §7.1 step 3 (Claude's review of a
  held name's re-evaluation, INTACT/WEAKENED/BROKEN, written to `value_reevaluations.review_state`);
  trigger 6 (kill-trigger near), whose input arrives as plain data like trigger 5; the Claude track
  of the shadow record (`effective_fair_value` from Claude's clamped value — the exit engine reads it
  only for the half-sale). Shadow positions and the regime trigger make no Claude call (spec §7.1).
- **Part 5 — Stage 3: money (paper).** As before, plus the hourly RTH check of triggers 1 and 4 for
  held names (delayed quotes from the bulk provider; an hourly hit only opens the re-evaluation and
  pauses adds — levels wait for the close), and "pause adds" for tranches. `value_reevaluations`
  gains a held-position key then. It reads `rules.exits.live_policy` (`value`) to choose the one
  policy whose exits may reach an order.
- **Part 6 — Web and Telegram.** As before (`last_viewed_at`, digests, review cards, a watchdog
  check), plus the re-evaluation cards of §7.1 step 4 (Major → `TELEGRAM_THREAD_VALUE` the same day,
  Minor → the daily digest) read from `value_reevaluations`, and Part 1 M1's `is_fresh` decision
  (ruling 19).

## Rulings made up front (the operator may overturn any of them)

Every ruling was checked against `main` at `1dad9dc` (Part 2's code plus one unrelated web fix) and
against a prototype of this whole plan built in a code-only scratch copy of `main` (every code block
below passed its tests, `ruff check .`, `ruff format --check` on every touched file and `mypy src`
there). "Cost if wrong" is what reversing it would take. Part 2's rulings are cited as "Part 2
ruling N", its review minors as "P2-Mn"; Part 1's minors as "P1-Mn".

**The ruleset**

1. **`value_rules: v3` = v2 unchanged + `rules.reevaluation`, frozen in Task 1 at
   `ad8841127029`.** Spec §7.1 puts every re-evaluation threshold "in `config/value.yaml →
   reevaluation`, under the ruleset version", so the block goes under `rules:` and moves the hash.
   Tests pin that the rules without `reevaluation` still hash to v2's `d07717fe5348` and without
   `reevaluation` and `exits` to v1's `e1a1b3b096b1`: **no entry rule and no exit threshold moves.**
   v3 also versions Part 3's exit-engine code (shock stops, the 8-K and going-concern thesis exits,
   P2-M1/M5/M6/M14), which the hash cannot see (the HANDOFF rule: an exit-logic change after the
   first live row needs a `value_rules` bump). **Entries already in `value.db` under v2** keep their
   `ruleset_version` tag and step under v3's code from the first v3 night; `value_report --ruleset v3`
   reads the v3 entries alone. *Cost if wrong: before the first v3 night, re-pin; after it, a v4.*
2. **P1-M6 (fractions in config) stays deferred** (Part 2 ruling 2's reasons hold: renaming a v1
   key would stop every process running on a stale private `value.yaml`). Every **new** Part 3 key
   follows the convention: percents are `*_pct` in percent (`raw_move_pct`), z-scores, multiples,
   sessions and days are plain.

**The boundary (re-checked against the merged code)**

3. **Trigger 6 (a Claude kill-trigger within 10% of firing) moves to Part 4.** Its predicates are
   Claude-chosen (§8.4) and do not exist until Part 4. `reevaluate.TriggerKind` leaves room for it.
   *Cost if wrong: none; there is nothing to evaluate.*
4. **§7.1's held-position steps move with the held positions:** the hourly RTH check of triggers 1
   and 4 and "pause adds" (Part 5: there are no held names or tranches before it), Claude's review
   (Part 4; shadow positions make no Claude call, spec §7.1 step 3), the Major/Minor cards (Part 6).
   Part 3 records every re-evaluation (step 5) so those parts read it. *Cost if wrong: none.*
5. **The going-concern thesis exit stays in Part 3** (Part 2 ruling 14), built as a research-worker
   job, not a text model: for the shadow record's names only (the keep-fresh list), each recent
   10-K/10-Q's primary document is read **once** and a sentence must **assert** the doubt ("…raise(s)
   substantial doubt about … ability to continue as a going concern", with no hedge or negation:
   could, may, if, whether, no, not, alleviated, evaluated, …). Healthy 10-Ks carry ASC 205-40
   boilerplate and risk-factor hypotheticals that a looser match would sell on; a missed doubt still
   meets the F-score, Z, 8-K 1.03 and catastrophe exits. Only the flag and the sentence are stored.
   *Cost if wrong: a looser pattern is one regex.*
6. **"A gate now failing flips the verdict to NO → the existing thesis exit"** (§7.1 step 2) adds no
   exit rule: the re-evaluation records `verdict_now` beside `verdict_at_entry`, and a sale still
   happens only through §7's thesis exits. *Cost if wrong: one more exit branch.*

**The filings feed** (owned by the research worker, spec §6.9)

7. **`submissions` job:** every value name with a CIK, read when the last read is over **20 hours**
   old (the sweep runs at 02:00; a one-day age would skip every other night, which is what the
   `fundamentals` job does today), ETag-reused (a 304 only stamps the read). Kept: 10-K, 10-Q, 20-F,
   40-F (and amendments) and 8-K/8-K/A filed in the last 400 days, with `items` as EDGAR tags them.
   A failure raises, so the drain retries (3 attempts). No text is read. *Cost if wrong: one
   constant each.*
8. **The sector ETFs** are the SPDR eleven, keyed by both GICS sector names (the snapshots) and
   yfinance's (names outside them), in `rules.reevaluation.sector_etfs`; SPY where none fits
   (`fallback_etf`). The sweep fetches their bars with SPY's (`benchmark_names()`).
9. **P2-M2 fixed:** the sweep refetches the bar dated the last weekday every night (`last <= due`),
   so a bar written while its session was forming never survives as a settled one. It costs nothing
   extra on a normal night (that bar is new then anyway).
10. **Readers tolerate a research.db the worker has not migrated**: `filings_between` and
    `going_concern_flags` return `{}` on `OperationalError`, because `./ibkr restart` may start the
    value process before the research worker has created `filing_index`.

**Re-evaluation** (spec §7.1)

11. **The residual model** (`residuals.py`): daily returns aligned with the sector ETF's;
    `e = r - (alpha + beta x r_etf)` with alpha and beta fitted by least squares over the 250
    aligned returns **before** the day; sigma = the sample sd of the residual over the last 60 of
    them (the day excluded); trigger 1's `z = e / sigma`. Trigger 2 sums the residual over 5 sessions
    with a fit that ends where the window starts, scaled by `sigma x sqrt(5)`. Fewer than 120 aligned
    returns (or a day the ETF has no bar) → no z; the raw move (≥ 10%) is the backstop then.
12. **Which sessions, which positions.** Every open READY entry's **main** legs are checked on every
    session they step (catch-up nights step several). Controls carry no legs and are not
    re-evaluated. A filing or a report counts on the first session on or after its date
    (`after < date <= day`, `after` = the previous session, or the signal date for the entry
    session). News volume and the regime step are measured tonight, so they count on the session
    dated tonight's as_of only. "Quiet" counts 90 days from the last re-evaluation, else the entry.
13. **One re-evaluation per entry, not per name.** Each list's READY entry has its own plan, so the
    debounce, the record and the twin are per `value_shadow` row. A trigger within 3 sessions of the
    open re-evaluation joins it (its triggers appended, `last_session` and `plan_after` updated)
    unless more severe. **A joined trigger still applies its plan actions** (stops only tighten).
14. **The shocks** (`full` only, at the close, after that close's own exit checks: "level changes
    wait for the close"): a Major down-move raises the stop to at least the shock session's low −
    0.5 × the ATR(14) on the bar **before** it; no ATR there → no shock stop (unknown is never zero).
    A Major up-move arms the trail at once with the **shock low as its floor** (instead of the
    breakeven, which an up-shock under water would put above the price); once the close reaches the
    half-way mark, §7's breakeven floor takes over. An already armed leg ignores an up-shock.
15. **A Major 8-K item (1.03, 3.01, 4.02) is a thesis exit under every policy**, on the main plan
    only (the original twin does not re-evaluate). A **going-concern** doubt is a §7 thesis exit: it
    reaches both plans through the night's facts.
16. **The original twin.** At an entry's first trigger, each open main leg is copied as a
    `plan = "original"` leg (its state before that session) and stepped from then on with no
    re-evaluation. A `plan` column on `value_shadow_legs` and `value_shadow_events` (default `main`,
    added to the live database by `init_value_db`, the `src/spreads/store.py` pattern) keeps the two
    apart. Re-entry blocking, the policy section and postmortems read the main plan only; an entry
    closes when every leg, twins included, has exited.

**The rebase** (spec §7.1: corporate actions are not triggers)

17. **`rebase` replaces Part 2's freeze.** Ratio = the bar now on the newest stepped session ÷ the
    close the leg saw there (the entry bar ÷ the entry price before any step). When |ratio − 1| >
    1e-4, every recorded price level of the entry (entry price, signal close, ATR, fair values) and
    of its legs (`LegState.rebased`: entry, fair values, stop, trail floor, highest close, last
    close, proceeds) is multiplied by it, and a `rebase` event (policy `all`) is recorded. yfinance's
    bars are adjusted for **dividends** too, so ordinary ex-dates rebase as well (each ~1%): the legs
    stay on the bars' basis. Part 2's `rebase_needed` entries are rebased and re-opened; one with no
    reference bar left stays frozen and is counted. **P2-M7 fixed** (nothing freezes now; horizons
    already read both ends from the bars as they stand) and **P2-M8 fixed** (SPY's entry price for a
    leg's benchmark is read from the bars as they stand). *Known limitation: a single bar the
    provider corrects (not a corporate action) rebases the levels too. Cost if wrong: a tolerance.*

**The review minors**

18. **Part 2's: fixed** M1 (tonight's facts are read on the session dated as_of only), M2 (ruling
    9), M5 (an F-score exit fires only if F-score + unknown components ≤ 3), M6 (the Altman Z exit is
    read only on a session a new accession lands: `LegState.seen_accn`), M7 and M8 (ruling 17), M11
    (the `sys.modules` probe also loads the lazy `src.common.universe` and `src.storage.regime_state`;
    neither reaches a wheel layer), M13 (STATUS documents the SEC cadence), M14 (the effective-only
    proposal is noted once per episode, and never when Python's own value says the same). **Deferred:**
    M9 (a bar-freshness gate: a monitoring concern for Part 6's watchdog), M10 (the `rs_cutoff`
    population is an entry rule: changing it moves verdicts, so it rides the next entry-rule bump with
    P1-M6), M12 (`value_report`'s `init_value_db` is now load-bearing: it migrates the `plan`
    column), M15 (a missing SPY bar voids an entry: `fill_pending` is untouched). M3, M4 were fixed in
    Part 2.
19. **Part 1's:** M1 (two "latest accession" fingerprints) stays deferred to Part 6's `is_fresh`, its
    consumer. Part 3 adds a third accession source (`filing_index`) but compares none: trigger 4
    reads the index, the re-mark reads the scorecard's own fingerprint. Recommendation for Part 6:
    the scorecard's raw-payload accession wins (it is what fair value was computed from). M2–M4, M7,
    M8 unchanged (Part 2 ruling 4).

**Stage 1b and the process**

20. **Stage 1b** (`backtest.py` + `scripts/value_backtest.py`): formations on the first session of
    each month; every name scored as it stood (`select_periods(as_of=)` on the raw payload, read
    read-only one name at a time; bars up to that close; the formation's own relative-strength line);
    READY entries at the next session's open, marked at 21/63/126 SPY sessions; the ranked tenths
    held to the next formation; printed through `report.py`'s sections. **Stand-ins, printed as
    caveats:** the next 10-Q/10-K's filing date for the earnings date; EDGAR's own count × price for
    the market-cap cross-check; a normal regime; today's classification and universe (survivorship
    twice). Bars: ten years from the bulk provider (a `10y` period added to
    `_period_for_lookback`, cached in `data/value_backtest/`, git-ignored) or `--bars research`.
    It writes nothing to `value.db` and refuses a ruleset that is not frozen. *Cost if wrong: a
    script.*
21. **The plain data** (spec §7.1 fence): `scripts/value_feed.py` gains `recent_earnings` (report
    dates of the last 14 days for the open positions, from `earnings_events`) and `news_volume` (24-hour
    items against the median of the 30 daily counts before them, from
    `queries.ticker_sentiment_rows`: the deterministic columns, scored items only). `run_value.py`
    passes both; its import allowlist is unchanged. Trigger 7 steps from the regime the **previous
    nightly run** recorded (`value_runs.summary_json`), and an unknown previous regime is never a step.
22. **No calibration section.** The live `research.db` gains `filing_index` only after the merge and
    the research worker's restart, so a pre-merge run would exercise empty tables; Stage 1b reads
    payloads the live sweep fetched. Both run after the merge (operator to-dos). Nothing in this plan
    copies `research.db` or opens the main checkout's databases.
23. **No web, no Telegram, no API, no command kind.** `README.md`, `docs/web/*`, `How the scan
    works.md`, `UNIVERSE_RESEARCH.md` and `.opencode/` are unchanged.

## Global Constraints

- **The core invariant holds unchanged:** nothing in Part 3 can place, size or gate an order.
  `src/engine/`, `src/execution/`, `src/strategies/`, `src/orchestrator/`, `src/monitor/`,
  `src/notify/`, `src/spreads/`, `src/news/` and `src/claude/` never import `src.value`.
- `src/value/` imports nothing from `src.claude`, `src.news`, `src.value_ai`, `src.spreads*`,
  `src.notify`, `src.api`, the trading path, `src.ledger`, `src.reporting` or the enrichment
  analytics; from `src.research` only `src.research.ingest.concepts` and `src.research.schemas`. It
  reads `research.db` (bars, payloads, `filing_index`) only through `src/common/value_inputs.py`,
  and opens no SEC client and no data provider: the research worker owns every SEC fetch.
  Earnings dates and news volume reach it only as plain data from `scripts/run_value.py` (via
  `scripts/value_feed.py`).
- `src/research/` imports no `src.value`; it learns of held names only through
  `data/value_keep_fresh.json` (`src/common/value_keep_fresh.py`).
- `src.value_ai` does not exist; do not create it.
- The pure modules (`schemas`, `metrics`, `scores`, `gates`, `valuation`, `timing`, `scorecard`,
  `rank`, `funnel`, `ruleset`, `exits`, `ranked`, `report`, and now `residuals`, `reevaluate`) do no
  I/O. `backtest.py` does no I/O either but imports the loader's pure builders, so it is not on the
  pure list.
- Only `src/value/` constructs `value.db` rows (`scripts/` is scanned too).
- **Unknown is never zero.** A missing figure is `None`; a missing ATR means no shock stop; a name
  with no going-concern read is absent, never "no doubt".
- **Never import `scripts.run_*`.** Check `scripts/run_value.py` with `.venv/bin/python -m
  py_compile`. Never open the main checkout's `data/*.db`; never copy `research.db`.
- Worktree Bash: plain single commands, absolute paths or the worktree root as cwd; no heredocs, no
  `cd x && …`, no compound commands that mention git paths.
- New config keys go into `config/examples/value.yaml` with a code default; the operator's private
  `config/*.yaml` is never edited (operator to-dos at the end).
- **Protected files** (diff against `main` must be empty at every section exit):
  `git diff --stat main...HEAD -- src/engine src/execution src/strategies src/notify
  src/orchestrator src/spreads src/api src/news src/claude web` prints nothing. (Part 3 edits
  `src/research/` and `src/data/`, which are not protected; nothing else outside `src/value/`,
  `src/common/`, `scripts/`, `tests/`, `config/examples/`, `.gitignore` and the four docs.)
- Per-task gate: the task's test files + `.venv/bin/ruff check <touched paths>` +
  `.venv/bin/ruff format --check <touched paths>` + `.venv/bin/mypy <touched src paths>`. Full gate
  at section exits only, from the worktree root: `.venv/bin/python -m pytest -q`,
  `.venv/bin/ruff check .`, `.venv/bin/mypy src`.
- `ruff format` only the files a task touches (`src/api/routers/portfolio.py` and `system.py` carry
  pre-existing format drift; leave them).

## Review Focus

1. **`./ibkr restart` starts the value process before the research worker has created
   `filing_index`** → the night reads no filings and no going-concern flags, and does not crash →
   Task 3 `test_a_research_db_without_the_filings_index_reads_as_empty`.
2. **The live `value.db` is Part 2's** (legs and events without `plan`, entries frozen as
   `rebase_needed`) → `init_value_db` adds the column, old rows read `main`, frozen entries are
   rebased and re-opened → Task 6 `test_init_adds_the_plan_columns_to_a_part_2_database`; Task 7
   `test_a_part_2_frozen_entry_is_rebased_and_reopened`.
3. **A dividend ex-date** (not only a split) rewrites the provider's history the night it lands →
   the legs are rebased by the ratio, no spurious stop → Task 7
   `test_a_rewrite_after_the_entry_bar_left_the_window_still_rebases`,
   `test_a_split_rebases_the_entry_instead_of_firing_its_stop`.
4. **A catch-up night after the laptop slept** → each session is checked on its own bar, a filing
   counts on the session it landed, news and the regime count on tonight's session, tonight's facts
   only on tonight's bar → Task 7 `test_triggers_within_three_sessions_join_the_open_reevaluation`,
   `test_news_and_the_regime_count_on_tonights_session_only`,
   `test_a_catch_up_night_reads_tonights_facts_on_tonights_session_only`.
5. **A healthy company's 10-K carries going-concern boilerplate** ("management evaluated whether…",
   "could raise substantial doubt…") → no flag, no sale → Task 2
   `test_a_going_concern_doubt_is_flagged_only_when_the_filing_asserts_it`.

---

## File structure

```
config/examples/value.yaml                MODIFY  v3, rules.reevaluation (T1)
.gitignore                                MODIFY  data/value_backtest/ (T11)
src/
  common/config.py                        MODIFY  ValueReevaluationCfg under rules, v3 (T1)
  common/value_types.py                   MODIFY  DayBar.high/low, FilingEvent, NewsVolume (T3)
  common/value_inputs.py                  MODIFY  build_day_bars high/low, filings_between,
                                                  going_concern_flags (T3)
  data/edgar_backend.py                   MODIFY  EdgarClient._get/get_text, get_submissions,
                                                  get_filing_text (T2)
  data/protocols.py                       MODIFY  FilingsProvider gains the two methods (T2)
  data/yfinance_backend.py                MODIFY  a 10y period (T11)
  research/store/models.py                MODIFY  FilingIndexRow, SubmissionsStateRow (T2)
  research/ingest/submissions.py          CREATE  the submissions job (T2)
  research/ingest/going_concern.py        CREATE  the going-concern job and detector (T2)
  research/ingest/materialize.py          MODIFY  the drain runs both kinds (T2)
  research/ingest/value_universe.py       MODIFY  submissions, going_concern, sector ETFs, M2 (T2)
  value/ruleset.py                        MODIFY  FROZEN v3 (T1)
  value/exits.py                          MODIFY  Reeval, shocks, 8-K and going-concern exits,
                                                  M5 M6 M14, LegState.rebased (T4)
  value/residuals.py                      CREATE  the sector-ETF residual model, pure (T5)
  value/reevaluate.py                     CREATE  triggers, severity, debounce, actions, pure (T5)
  value/store.py                          MODIFY  value_reevaluations, the plan column (T6)
  value/shadow.py                         REWRITE rebase, per-session loop, twins, M1 M7 M8 (T7)
  value/service.py                        MODIFY  positions, previous_regime, plain data (T8)
  value/report.py                         MODIFY  the re-evaluation section, plans (T9)
  value/backtest.py                       CREATE  Stage 1b (T10)
scripts/
  value_feed.py                           MODIFY  recent_earnings, news_volume (T8)
  run_value.py                            MODIFY  passes them (T8)
  value_report.py                         MODIFY  loads re-evaluations, plans, rebases (T9)
  value_backtest.py                       CREATE  Stage 1b's script (T11)
tests/
  test_value_config.py                    MODIFY  (+2: 14 -> 16)              T1   +2
  test_value_dry_run.py                   MODIFY  (v2 -> v3)                  T1
  test_research_submissions.py            CREATE  (9)                         T2   +9
  test_value_universe.py                  MODIFY  (+1; two tests change)      T2   +1
  test_value_inputs.py                    MODIFY  (+2)                        T3   +2
  test_value_exits.py                     MODIFY  (+14 collected)             T4   +14
  test_value_reevaluate.py                CREATE  (10)                        T5   +10
  test_value_store.py                     MODIFY  (+1)                        T6   +1
  test_value_shadow.py                    MODIFY  (+7; two split tests become rebase tests)  T7 +7
  test_value_feed.py                      MODIFY  (+2)                        T8   +2
  test_value_service.py                   MODIFY  (+1; v2 -> v3)              T8   +1
  test_value_fence.py                     MODIFY  (+1; pure list, rows, probes)  T8 +1
  test_value_report.py                    MODIFY  (+2)                        T9   +2
  test_value_backtest.py                  CREATE  (4, then +3)                T10  +4, T11 +3
  test_data_providers.py                  MODIFY  (two cases in one test)     T11
ARCHITECTURE.md, SETUP.md, STATUS.md, CLAUDE.md   MODIFY (T12)
docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md   this plan (Progress log)
```

**59 new tests** in all (baseline + 59 at Section D's exit; the prototype ran 5239 + 1 skipped →
5298 + 1 skipped, mypy 325 source files). Part 3 adds no route, command kind, Telegram command or
top-level directory (ruling 23).

---

## Section A — Ruleset v3, the filings feed, the readers (Tasks 1–3) · model: sonnet · effort: high

The re-evaluation rules go into the config and freeze `value_rules: v3`; the research worker learns
to read each filer's EDGAR submissions feed and, for the shadow record's names, each new periodic
filing's going-concern language; the neutral loader learns to hand the value book the filings, the
going-concern flag and each day's high and low. Nothing here re-evaluates anything yet.

**Spec to read:** §6.9 (the "Where the inputs come from" bullet), §7 (the thesis-exit bullet),
§7.1 (the trigger table and the paragraph under it), §8.5 (the "Deterministic recompute" bullet and
"Spend tokens only on judgement"), §16 (the re-evaluation and fence bullets).

**Files the subagent reads:** `src/common/config.py` (lines 1572–1673: the value models),
`config/examples/value.yaml`, `src/value/ruleset.py`, `tests/test_value_config.py`,
`src/data/edgar_backend.py`, `src/data/protocols.py` (lines 140–170), `src/research/store/models.py`,
`src/research/ingest/materialize.py` (lines 100–118, 383–435), `src/research/ingest/value_universe.py`,
`src/research/ingest/fundamentals.py` (the job pattern), `tests/test_value_universe.py` (lines
125–234), `tests/test_edgar_companyfacts.py` (the client pattern), `src/common/value_types.py`,
`src/common/value_inputs.py`, `tests/test_value_inputs.py` (lines 200–300).

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **A0. Disk, worktrees, and the new one.** From the main checkout:

  ```bash
  df -h .
  git -C "/Users/ianlim/Desktop/IBKR Investments" worktree list
  git -C "/Users/ianlim/Desktop/IBKR Investments" log --oneline -1 main
  ```

  `df` must show **at least 8 GiB available** (Part 2's first sweeps add ~2 GB to the live
  `research.db`; Stage 1b's bar cache is ~30 MB). `worktree list` must not list
  `.claude/worktrees/value-book-3` already. `main` must contain Part 2 (`7d37f95` is an ancestor:
  `git -C "/Users/ianlim/Desktop/IBKR Investments" merge-base --is-ancestor 7d37f95 main` exits 0).
  Any fails → stop and ask the operator. Then create the worktree **from `main`** (the main checkout
  sits on another branch; HANDOFF §1) and set it up, one command each (the last four from the
  worktree root):

  ```bash
  git -C "/Users/ianlim/Desktop/IBKR Investments" worktree add "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/value-book-3" -b feat/value-book-3 main
  ln -s "/Users/ianlim/Desktop/IBKR Investments/.venv" .venv
  cp "/Users/ianlim/Desktop/IBKR Investments/docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md" docs/superpowers/plans/
  IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"
  ```

  (No `web/node_modules` link: Part 3 runs no web test. No database copy: Part 3's tests use
  fixtures.)
- [ ] **A1. Branch and a clean start.** `git branch --show-current` prints `feat/value-book-3`;
  `git log --oneline -1` starts with `1dad9dc` (or a later `main` the operator merged — record it);
  `git status --short` prints exactly:

  ```
  ?? docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md
  ```

- [ ] **A2. A green baseline, from the worktree root.** Each passes; record the pytest count in the
  Progress log as **the baseline** (at `1dad9dc`: `5239 passed, 1 skipped`; mypy: `320 source
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
- [ ] **A3. The code Section A edits is where this plan says.** Each command prints exactly the
  line shown (line numbers as of `1dad9dc`; a moved line is fine if the text matches — record it):

  ```bash
  grep -n "^class ValueRulesCfg(_ValueModel):$" src/common/config.py                       # 1603:
  grep -n "^    exits: ValueExitsCfg = Field(default_factory=ValueExitsCfg)$" src/common/config.py   # 1614:
  grep -n '^    ruleset_version: str = "v2"$' src/common/config.py                         # 1666:
  grep -n '^FROZEN: dict\[str, str\] = {"v1": "e1a1b3b096b1", "v2": "d07717fe5348"}$' src/value/ruleset.py   # 18:
  grep -n "^ruleset_version: v2$" config/examples/value.yaml                               # 12:
  tail -n 1 config/examples/value.yaml                                                     #     hold12_sessions: 252
  grep -n "^def test_v1_stays_pinned_and_v2_is_frozen() -> None:$" tests/test_value_config.py   # 71:
  grep -n "^def test_v2_changes_no_entry_rule() -> None:$" tests/test_value_config.py      # 79:
  grep -n '("dry_run", 1, "v2")' tests/test_value_dry_run.py                               # 104:
  grep -n "^    def get_json(self, url: str, \*, etag: str | None = None)" src/data/edgar_backend.py   # 81:
  grep -n "^class EdgarFilingsProvider:$" src/data/edgar_backend.py                        # 154:
  grep -n "^class FilingsProvider(Protocol):$" src/data/protocols.py                       # 148:
  grep -n "^class IngestJobRow(Base):$" src/research/store/models.py                       # 191:
  grep -n '^        elif kind == "prices":$' src/research/ingest/materialize.py            # 412:
  grep -n '^BENCHMARKS = ("SPY",)$' src/research/ingest/value_universe.py                  # 30:
  grep -n "^        if n < MIN_BARS or last is None or last < due:$" src/research/ingest/value_universe.py   # 95:
  grep -n '^    assert counts == {"fundamentals": 1, "prices": 2, "no_cik": 1}$' tests/test_value_universe.py   # 162:
  grep -n "^def test_the_nightly_sweep_refreshes_yesterdays_bars_and_spys" tests/test_value_universe.py   # 216:
  grep -n "^class DayBar(BaseModel):$" src/common/value_types.py                           # 69:
  grep -n "^class Classification(BaseModel):$" src/common/value_types.py                   # 82:
  grep -n "^from sqlalchemy.engine import Engine$" src/common/value_inputs.py              # 26:
  grep -n '^    opens = _column(bars\["open"\]) if "open" in bars.columns else \[None\] \* len(close)$' src/common/value_inputs.py   # 211:
  grep -n "^def current_fingerprint_parts(" src/common/value_inputs.py                     # 351:
  grep -n "^def test_a_missing_research_db_is_none_not_an_error(" tests/test_value_inputs.py   # 284:
  ```

- [ ] **A4. v2 is what is frozen, and no Part 3 code exists yet.** The first prints
  `d07717fe5348`; the second prints nothing:

  ```bash
  .venv/bin/python -c "from src.common.config import ValueCfg; from src.value.ruleset import ruleset_hash; print(ruleset_hash(ValueCfg().rules))"
  grep -rln "ValueReevaluationCfg\|FilingIndexRow\|ingest_submissions\|src\.value\.reevaluate\|value_backtest" src tests scripts
  ```

**Section exit:** three task commits plus the section's final `docs(plan)` commit; full gate green
with pytest = baseline + 14 (2 + 10 + 2); protected-file diff empty;
`.venv/bin/python -m py_compile scripts/run_value.py` silent. Record the commit count from
`git log --oneline main..HEAD | wc -l`.

---

### Task 1: Ruleset v3 — the re-evaluation rules

**Files:**
- Modify: `src/common/config.py` (insert before line 1603; after line 1614; lines 1662–1666)
- Modify: `config/examples/value.yaml` (lines 1–12; append after line 172), `src/value/ruleset.py`
  (lines 15–18)
- Modify: `tests/test_value_config.py` (lines 1, 27, 69, 71–84), `tests/test_value_dry_run.py`
  (line 104), `tests/test_value_service.py` (line 151)
- Add: this plan (first commit of the branch)

**Interfaces:**
- Produces: `ValueReevaluationCfg` at `ValueRulesCfg.reevaluation` with `abnormal_z`,
  `raw_move_pct`, `drift_z`, `drift_sessions`, `beta_sessions`, `sigma_sessions`,
  `min_history_sessions`, `sector_etfs: dict[str, str]`, `fallback_etf`, `major_8k_items`,
  `minor_8k_items`, `news_multiple`, `news_min_items`, `regime_states: list[MarketRegime]`,
  `quiet_days`, `debounce_sessions`, `down_shock_atr`; `ValueCfg.ruleset_version == "v3"`;
  `FROZEN["v3"] == "ad8841127029"`.

- [x] **Step 1: Write the failing tests** — apply this diff to `tests/test_value_config.py` (it
  replaces `test_v1_stays_pinned_and_v2_is_frozen` and `test_v2_changes_no_entry_rule`):

```diff
diff --git a/tests/test_value_config.py b/tests/test_value_config.py
index dcee9d2..8d504ea 100644
--- a/tests/test_value_config.py
+++ b/tests/test_value_config.py
@@ -1,4 +1,4 @@
-"""config/value.yaml: the typed model, its committed example and the ruleset hash (Parts 1-2)."""
+"""config/value.yaml: the typed model, its committed example and the ruleset hash (Parts 1-3)."""
 
 from __future__ import annotations
 
@@ -26,7 +26,7 @@ def test_the_example_spells_out_exactly_the_model_defaults() -> None:
 
 def test_get_config_loads_the_value_block() -> None:
     cfg = get_config().value
-    assert cfg.ruleset_version == "v2"
+    assert cfg.ruleset_version == "v3"
     assert cfg.rules.margin_of_safety.deep_value[MarketRegime.NORMAL] == 25.0
     assert cfg.rules.margin_of_safety.quality_growth[MarketRegime.CRISIS] == 25.0
     assert cfg.rules.valuation.discount_rate_growth == 0.08
@@ -65,23 +65,54 @@ def test_a_frozen_version_refuses_rules_that_no_longer_match(monkeypatch) -> Non
     monkeypatch.setitem(FROZEN, "v9", "000000000000")
     with pytest.raises(ValueError, match="frozen"):
         ruleset_id(ValueCfg(ruleset_version="v9"))
-    assert ruleset_id(ValueCfg()) == ("v2", ruleset_hash(ValueCfg().rules))
+    assert ruleset_id(ValueCfg()) == ("v3", ruleset_hash(ValueCfg().rules))
 
 
-def test_v1_stays_pinned_and_v2_is_frozen() -> None:
-    """Part 1 froze v1 (the entry rules) after the calibration dry run; Part 2 froze v2 = v1 +
-    the exit rules, before the shadow ledger's first row."""
-    assert FROZEN["v1"] == "e1a1b3b096b1"
-    assert FROZEN["v2"] == ruleset_hash(ValueCfg().rules)
-    assert ruleset_id(get_config().value) == ("v2", FROZEN["v2"])
-
-
-def test_v2_changes_no_entry_rule() -> None:
-    """Every rule but the new exits block hashes exactly as v1 did: no verdict moves."""
+def _hash_without(*blocks: str) -> str:
     rules = ValueCfg().rules.model_dump(mode="json")
-    del rules["exits"]
+    for block in blocks:
+        del rules[block]
     blob = json.dumps(rules, sort_keys=True, separators=(",", ":"))
-    assert hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12] == FROZEN["v1"]
+    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
+
+
+def test_v1_and_v2_stay_pinned_and_v3_is_frozen() -> None:
+    """Part 1 froze v1 (the entry rules); Part 2 froze v2 = v1 + the exit rules; Part 3 froze
+    v3 = v2 + the re-evaluation rules, before the first re-evaluation (spec §7.1)."""
+    assert FROZEN["v1"] == "e1a1b3b096b1" and FROZEN["v2"] == "d07717fe5348"
+    assert FROZEN["v3"] == ruleset_hash(ValueCfg().rules)
+    assert ruleset_id(get_config().value) == ("v3", FROZEN["v3"])
+
+
+def test_v3_changes_no_entry_rule_and_no_exit_threshold() -> None:
+    """Without the reevaluation block the rules hash exactly as v2's; without exits too, as
+    v1's: no verdict and no exit threshold moves. Part 3's exit-engine changes are code, carried
+    by the version bump (an exit-logic change after the first live row needs one)."""
+    assert _hash_without("reevaluation") == FROZEN["v2"]
+    assert _hash_without("reevaluation", "exits") == FROZEN["v1"]
+
+
+def test_the_reevaluation_rules_are_in_the_ruleset() -> None:
+    """Spec §7.1: every re-evaluation threshold is under the ruleset version."""
+    cfg = ValueCfg()
+    assert cfg.rules.reevaluation.sector_etfs["Information Technology"] == "XLK"
+    for change in ({"abnormal_z": 2.5}, {"major_8k_items": ["1.03"]}, {"quiet_days": 60}):
+        moved = ValueCfg(**{"rules": {"reevaluation": change}})
+        assert ruleset_hash(moved.rules) != ruleset_hash(cfg.rules)
+
+
+def test_nonsense_reevaluation_keys_are_refused() -> None:
+    for bad in (
+        {"abnormal_z": 0.0},
+        {"drift_sessions": 1},
+        {"min_history_sessions": 30},
+        {"beta_sessions": 100},
+        {"minor_8k_items": ["1.03"]},
+        {"regime_states": ["panic"]},
+        {"sigma_window": 60},
+    ):
+        with pytest.raises(ValidationError):
+            ValueCfg(**{"rules": {"reevaluation": bad}})
 
 
 def test_the_exit_rules_are_in_the_ruleset() -> None:
```

  …and this one to `tests/test_value_dry_run.py`:

```diff
diff --git a/tests/test_value_dry_run.py b/tests/test_value_dry_run.py
index 645c80f..5b9ad89 100644
--- a/tests/test_value_dry_run.py
+++ b/tests/test_value_dry_run.py
@@ -101,7 +101,7 @@ def test_the_dry_run_scores_persists_and_prints_the_funnel(dbs, capsys, tmp_path
         assert row is not None and row.universe == "trading"
         assert row.verdict_deep == "WATCH"  # cheap enough; no earnings date is unknown timing
         run = s.query(ValueRunRow).one()
-        assert (run.kind, run.names, run.ruleset_version) == ("dry_run", 1, "v2")
+        assert (run.kind, run.names, run.ruleset_version) == ("dry_run", 1, "v3")
 
 
 def test_no_persist_leaves_value_db_alone(dbs, tmp_path) -> None:
```

  …and in `tests/test_value_service.py` line 151 (a night now records v3) replace

  ```python
          assert (run.kind, run.as_of, run.ruleset_version) == ("nightly", AS_OF, "v2")
  ```

  with

  ```python
          assert (run.kind, run.as_of, run.ruleset_version) == ("nightly", AS_OF, "v3")
  ```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_service.py`
  Expected: FAIL — `AttributeError: 'ValueRulesCfg' object has no attribute 'reevaluation'` (and the
  v3 assertions).

- [x] **Step 3: The config model** — apply to `src/common/config.py`:

```diff
diff --git a/src/common/config.py b/src/common/config.py
index 7bbb6ad..a7511c5 100644
--- a/src/common/config.py
+++ b/src/common/config.py
@@ -1600,6 +1600,71 @@ class ValueExitsCfg(_ValueModel):
         return self
 
 
+_SECTOR_ETFS = {
+    # GICS sectors (the snapshots) and yfinance's names (names outside them), SPDR sector ETFs.
+    "Communication Services": "XLC",
+    "Consumer Discretionary": "XLY",
+    "Consumer Cyclical": "XLY",
+    "Consumer Staples": "XLP",
+    "Consumer Defensive": "XLP",
+    "Energy": "XLE",
+    "Financials": "XLF",
+    "Financial Services": "XLF",
+    "Health Care": "XLV",
+    "Healthcare": "XLV",
+    "Industrials": "XLI",
+    "Information Technology": "XLK",
+    "Technology": "XLK",
+    "Materials": "XLB",
+    "Basic Materials": "XLB",
+    "Real Estate": "XLRE",
+    "Utilities": "XLU",
+}
+
+
+class ValueReevaluationCfg(_ValueModel):
+    """Spec §7.1: when a held or shadow position's plan is re-evaluated, and how. Under
+    ``rules:``, so every key is in the ruleset fingerprint (v3)."""
+
+    abnormal_z: float = 3.0  # trigger 1: |one-session residual z| at or above this is Major
+    raw_move_pct: float = 10.0  # ... the backstop when the history is too short for a z
+    drift_z: float = 3.0  # trigger 2: |cumulative residual z| over drift_sessions, Minor
+    drift_sessions: int = 5
+    beta_sessions: int = 250  # the residual model's beta window (sessions before the day)
+    sigma_sessions: int = 60  # the residual's standard deviation, prior sessions, day excluded
+    min_history_sessions: int = 120  # fewer aligned returns than this: the raw backstop only
+    sector_etfs: dict[str, str] = Field(default_factory=lambda: dict(_SECTOR_ETFS))
+    fallback_etf: str = "SPY"  # a sector with no ETF in the map
+    major_8k_items: list[str] = Field(default_factory=lambda: ["1.03", "3.01", "4.02"])
+    minor_8k_items: list[str] = Field(
+        default_factory=lambda: ["1.01", "2.01", "2.05", "2.06", "4.01", "5.02"]
+    )
+    news_multiple: float = 4.0  # trigger 5: 24-hour items at least 4 x the 30-day daily median
+    news_min_items: int = 5  # ... and at least 5 items
+    regime_states: list[MarketRegime] = Field(
+        default_factory=lambda: [MarketRegime.STRESSED, MarketRegime.CRISIS]
+    )
+    quiet_days: int = 90  # trigger 8: this many days with no re-evaluation
+    debounce_sessions: int = 3  # a trigger this close to an open re-evaluation joins it
+    down_shock_atr: float = 0.5  # full only: the stop rises to the shock low - 0.5 x ATR before
+
+    @model_validator(mode="after")
+    def _sane(self) -> ValueReevaluationCfg:
+        if min(self.abnormal_z, self.drift_z, self.raw_move_pct, self.news_multiple) <= 0:
+            raise ValueError("value reevaluation thresholds must be positive")
+        if self.drift_sessions < 2 or self.sigma_sessions < 10:
+            raise ValueError("value reevaluation.drift_sessions >= 2, sigma_sessions >= 10")
+        if self.min_history_sessions < self.sigma_sessions + 2:
+            raise ValueError("value reevaluation.min_history_sessions must exceed sigma_sessions")
+        if self.beta_sessions < self.min_history_sessions:
+            raise ValueError("value reevaluation.beta_sessions must be >= min_history_sessions")
+        if set(self.major_8k_items) & set(self.minor_8k_items):
+            raise ValueError("value reevaluation: an 8-K item is either major or minor")
+        if self.debounce_sessions < 0 or self.quiet_days < 1 or self.down_shock_atr < 0:
+            raise ValueError("value reevaluation: debounce >= 0, quiet_days >= 1, shock ATR >= 0")
+        return self
+
+
 class ValueRulesCfg(_ValueModel):
     """Every key that can change a verdict. Hashed into the ruleset fingerprint (spec §6.8)."""
 
@@ -1612,6 +1677,7 @@ class ValueRulesCfg(_ValueModel):
     margin_of_safety: ValueMarginCfg = Field(default_factory=ValueMarginCfg)
     timing: ValueTimingCfg = Field(default_factory=ValueTimingCfg)
     exits: ValueExitsCfg = Field(default_factory=ValueExitsCfg)
+    reevaluation: ValueReevaluationCfg = Field(default_factory=ValueReevaluationCfg)
 
 
 class ValueUniverseCfg(_ValueModel):
@@ -1660,10 +1726,10 @@ class ValueServiceCfg(_ValueModel):
 
 
 class ValueCfg(_ValueModel):
-    """The value book (config/value.yaml). Parts 1-2: the scorecard and the shadow record,
-    nothing that trades."""
+    """The value book (config/value.yaml). Parts 1-3: the scorecard, the shadow record and its
+    re-evaluations, nothing that trades."""
 
-    ruleset_version: str = "v2"
+    ruleset_version: str = "v3"
     db_url: str = "sqlite:///data/value.db"
     universe: ValueUniverseCfg = Field(default_factory=ValueUniverseCfg)
     ticker_file: ValueTickerFileCfg = Field(default_factory=ValueTickerFileCfg)
```

- [x] **Step 4: The example file** — apply to `config/examples/value.yaml` (the keys must equal the
  model defaults: `test_the_example_spells_out_exactly_the_model_defaults`):

```diff
diff --git a/config/examples/value.yaml b/config/examples/value.yaml
index ef80f88..1fedaab 100644
--- a/config/examples/value.yaml
+++ b/config/examples/value.yaml
@@ -1,15 +1,16 @@
 # The value book (docs/superpowers/specs/2026-10-28-value-swing-book-design.md).
 #
-# Copy to config/value.yaml (git-ignored) to tune it. Parts 1-2 build the scorecard and the shadow
-# record only: nothing here can place, size or gate an order.
+# Copy to config/value.yaml (git-ignored) to tune it. Parts 1-3 build the scorecard, the shadow
+# record and its re-evaluations only: nothing here can place, size or gate an order.
 #
 # Everything under `rules:` can change a verdict, so it is hashed into the ruleset fingerprint
 # (src/value/ruleset.py). Once `ruleset_version` is frozen, changing any rule is a version bump
 # with a written reason, at most quarterly. v1 (2026-10-29) froze the entry rules after the
 # calibration dry run; v2 (Part 2) adds `rules.exits` before the shadow ledger's first row and
-# changes no entry rule.
+# changes no entry rule; v3 (Part 3) adds `rules.reevaluation` (spec §7.1) and the exit engine's
+# Part 3 rules (shock stops, the 8-K and going-concern thesis exits), and changes no entry rule.
 
-ruleset_version: v2
+ruleset_version: v3
 db_url: sqlite:///data/value.db
 
 universe:
@@ -170,3 +171,41 @@ rules:
     thesis_fv_below_price_pct: 90.0  # ... fair value below 90% of the price, under the 50-day SMA
     catastrophe_stop_pct: 30.0   # value and hold12: a close 30% below the average cost
     hold12_sessions: 252
+
+  reevaluation:              # spec §7.1: when a held or shadow position's plan is re-evaluated
+    abnormal_z: 3.0          # 1: |one-session return net of the sector ETF, in residual sds| (Major)
+    raw_move_pct: 10.0       # ... a raw move this large when the history is too short (Major)
+    drift_z: 3.0             # 2: |cumulative residual over drift_sessions| in the same units (Minor)
+    drift_sessions: 5
+    beta_sessions: 250       # the residual model's beta window, sessions before the day
+    sigma_sessions: 60       # the residual's sd over the prior 60 sessions, the day excluded
+    min_history_sessions: 120    # fewer aligned returns: the raw backstop only
+    sector_etfs:             # GICS (snapshots) and yfinance sector names -> SPDR sector ETF
+      Communication Services: XLC
+      Consumer Discretionary: XLY
+      Consumer Cyclical: XLY
+      Consumer Staples: XLP
+      Consumer Defensive: XLP
+      Energy: XLE
+      Financials: XLF
+      Financial Services: XLF
+      Health Care: XLV
+      Healthcare: XLV
+      Industrials: XLI
+      Information Technology: XLK
+      Technology: XLK
+      Materials: XLB
+      Basic Materials: XLB
+      Real Estate: XLRE
+      Utilities: XLU
+    fallback_etf: SPY        # a sector the map lacks
+    major_8k_items: ["1.03", "3.01", "4.02"]   # 4: bankruptcy, delisting, non-reliance (Major;
+                                               # a thesis exit under every policy)
+    minor_8k_items: ["1.01", "2.01", "2.05", "2.06", "4.01", "5.02"]   # deals, restructuring,
+                                               # impairment, auditor, CEO/CFO (Minor)
+    news_multiple: 4.0       # 5: 24-hour items >= 4 x the 30-day daily median ...
+    news_min_items: 5        # ... and >= 5 items (Minor)
+    regime_states: [stressed, crisis]          # 7: the market regime steps into one (Minor)
+    quiet_days: 90           # 8: this many days with no re-evaluation (Minor)
+    debounce_sessions: 3     # a trigger this close to an open re-evaluation joins it, unless Major
+    down_shock_atr: 0.5      # full only: the stop rises to the shock low - 0.5 x ATR(14) before it
```

- [x] **Step 5: Check the hash, then pin it.** Run:

  ```bash
  .venv/bin/python -c "from src.common.config import ValueCfg; from src.value.ruleset import ruleset_hash; print(ruleset_hash(ValueCfg().rules))"
  ```

  It prints `ad8841127029`. Any other value means a default differs from this plan: stop and
  report (do not pin a different hash). Then apply to `src/value/ruleset.py`:

```diff
diff --git a/src/value/ruleset.py b/src/value/ruleset.py
index 124aad6..93db8a5 100644
--- a/src/value/ruleset.py
+++ b/src/value/ruleset.py
@@ -15,7 +15,10 @@ from src.common.config import ValueCfg, ValueRulesCfg
 # Task 16). A rule change is a new version with a written reason, at most quarterly (spec §6.8).
 # v2 (Part 2): v1's entry rules unchanged, plus `rules.exits` (spec §7), frozen before the shadow
 # ledger's first row so every shadow entry carries the exit rules it was simulated under.
-FROZEN: dict[str, str] = {"v1": "e1a1b3b096b1", "v2": "d07717fe5348"}
+# v3 (Part 3): v2 unchanged, plus `rules.reevaluation` (spec §7.1), frozen before the first
+# re-evaluation; it also versions Part 3's exit-engine code (shock stops, the 8-K and
+# going-concern thesis exits, review minors M1 M5 M6 M14), which the hash cannot see.
+FROZEN: dict[str, str] = {"v1": "e1a1b3b096b1", "v2": "d07717fe5348", "v3": "ad8841127029"}
 
 
 def ruleset_hash(rules: ValueRulesCfg) -> str:
```

- [x] **Step 6: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_service.py tests/test_private_config.py tests/test_value_scorecard.py`
  Expected: PASS (`test_value_config.py` 16 tests). Then `.venv/bin/ruff check src/common/config.py
  src/value/ruleset.py tests/test_value_config.py tests/test_value_dry_run.py
  tests/test_value_service.py`, `.venv/bin/ruff format --check` on the same files, and
  `.venv/bin/mypy src/common/config.py src/value/ruleset.py` — all clean.

- [x] **Step 7: Commit**

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md src/common/config.py config/examples/value.yaml src/value/ruleset.py tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_service.py
  git commit -m "feat(value): value_rules v3 adds the re-evaluation rules"
  ```

---

### Task 2: The research worker's filings feed

**Files:**
- Modify: `src/data/edgar_backend.py` (line 25; lines 81–119 become `_get` + `get_json` +
  `get_text`; lines 154–156; append after line 167), `src/data/protocols.py` (after line 160)
- Modify: `src/research/store/models.py` (line 196; append after line 200)
- Create: `src/research/ingest/submissions.py`, `src/research/ingest/going_concern.py`
- Modify: `src/research/ingest/materialize.py` (after lines 35 and 36; before line 412),
  `src/research/ingest/value_universe.py` (lines 3–8, 21, after 27, after 30, 56–98)
- Create: `tests/test_research_submissions.py`; modify `tests/test_value_universe.py` (lines
  142–162, 216–234)

**Interfaces:**
- Produces: `EdgarFilingsProvider.get_submissions(cik, *, etag=None) -> tuple[dict, str | None]`
  and `get_filing_text(cik, accn, document) -> str` (both on the `FilingsProvider` Protocol);
  `EdgarClient.get_text(url) -> str | None`; research tables `filing_index` (`FilingIndexRow`:
  `accn` PK, `cik`, `form`, `filed`, `report_date`, `items` "a,b", `primary_document`,
  `going_concern: bool | None`, `going_concern_detail`) and `submissions_state`;
  `submissions.KEEP_DAYS = 400`, `PERIODIC_FORMS`, `parse_submissions`, `ingest_submissions`;
  `going_concern.detect_going_concern(raw) -> str | None`, `ingest_going_concern`; job kinds
  `submissions` and `going_concern`; `value_universe.benchmark_names() -> tuple[str, ...]`;
  `enqueue_value_universe` counts gain `submissions` and `going_concern`.

- [x] **Step 1: Write the failing tests** — create `tests/test_research_submissions.py`:

```python
"""The research worker's EDGAR submissions feed and going-concern read (value book spec §7, §7.1,
§8.5): the client, the parser, the two jobs, the drain."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from src.data.edgar_backend import EdgarClient, EdgarFilingsProvider
from src.research.ingest import going_concern as gc
from src.research.ingest import submissions as sub

FEED = {
    "cik": "320193",
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-26-000010",
                "0000320193-26-000009",
                "0000320193-26-000008",
                "0000320193-25-000001",
                "0000320193-26-000007",
            ],
            "filingDate": ["2026-10-20", "2026-10-02", "2026-08-01", "2025-05-01", "bad"],
            "reportDate": ["2026-10-17", "", "2026-06-28", "2025-03-29", ""],
            "form": ["8-K", "4", "10-Q", "10-Q", "8-K"],
            "items": ["5.02,9.01", "", "", "", "1.03"],
            "primaryDocument": ["a8k.htm", "x.xml", "a10q.htm", "old.htm", "b.htm"],
        }
    },
}


@pytest.fixture(autouse=True)
def _contact(monkeypatch):
    monkeypatch.setattr("src.data.edgar_backend._contact_email", lambda: "t@example.com")


def test_the_client_reads_the_feed_and_a_filing_document() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "submissions" in str(request.url):
            return httpx.Response(200, json=FEED, headers={"ETag": "e1"})
        return httpx.Response(200, text="<p>hello</p>")

    p = EdgarFilingsProvider(client=EdgarClient(transport=httpx.MockTransport(handler)))
    payload, etag = p.get_submissions("320193")
    assert payload["name"] == "Apple Inc." and etag == "e1"
    assert seen[0] == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert p.get_filing_text("0000320193", "0000320193-26-000008", "a10q.htm") == "<p>hello</p>"
    assert seen[1] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000008/a10q.htm"
    assert p.get_filing_text("", "x", "y") == ""


def test_a_failed_document_read_is_empty_not_an_error() -> None:
    p = EdgarFilingsProvider(
        client=EdgarClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(404)), max_retries=0
        )
    )
    assert p.get_filing_text("320193", "0000320193-26-000008", "a10q.htm") == ""
    assert p.get_submissions("320193") == ({}, None)


def test_the_parser_keeps_recent_periodic_and_8k_filings_with_their_items() -> None:
    out = sub.parse_submissions(FEED, since=date(2025, 10, 1))
    assert [(f.accn[-2:], f.form, f.items) for f in out] == [
        ("10", "8-K", ("5.02", "9.01")),
        ("08", "10-Q", ()),
    ]  # a Form 4 is skipped, a filing older than *since* too, and a row with a bad date
    assert out[1].report_date == date(2026, 6, 28) and out[0].primary_document == "a8k.htm"
    assert sub.parse_submissions({}, since=date(2025, 1, 1)) == []


class _Provider:
    def __init__(self, feeds: list[tuple[dict, str | None]], docs: dict[str, str] | None = None):
        self.feeds = feeds
        self.docs = docs or {}
        self.etags: list[str | None] = []

    def get_submissions(self, cik: str, *, etag: str | None = None) -> tuple[dict, str | None]:
        self.etags.append(etag)
        return self.feeds.pop(0)

    def get_filing_text(self, cik: str, accn: str, document: str) -> str:
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


def _index() -> list[tuple[str, str, str, bool | None]]:
    from src.research.store.models import FilingIndexRow
    from src.research.store.session import research_session

    with research_session() as s:
        return [
            (r.accn[-2:], r.form, r.items, r.going_concern)
            for r in s.query(FilingIndexRow).order_by(FilingIndexRow.accn)
        ]


def test_the_submissions_job_indexes_reuses_the_etag_and_keeps_a_read_flag(
    research_db, monkeypatch
) -> None:
    from src.research.store.models import FilingIndexRow
    from src.research.store.session import research_session

    provider = _Provider([(FEED, "e1"), ({}, "e1"), (FEED, "e2")])
    monkeypatch.setattr(sub, "get_filings_provider", lambda: provider)
    today = date(2026, 10, 30)
    assert sub.ingest_submissions("AAPL", "0000320193", today=today) == 2
    assert _index() == [("08", "10-Q", "", None), ("10", "8-K", "5.02,9.01", None)]
    assert sub.ingest_submissions("AAPL", "0000320193", today=today) == 0  # a 304
    with research_session() as s:
        s.get(FilingIndexRow, "0000320193-26-000008").going_concern = False
    assert sub.ingest_submissions("AAPL", "0000320193", today=today) == 2
    assert provider.etags == [None, "e1", "e1"]
    assert _index()[0] == ("08", "10-Q", "", False)  # a re-read keeps the going-concern read


def test_a_failed_feed_raises_so_the_drain_retries(research_db, monkeypatch) -> None:
    monkeypatch.setattr(sub, "get_filings_provider", lambda: _Provider([({}, None)]))
    with pytest.raises(RuntimeError, match="No submissions feed"):
        sub.ingest_submissions("AAPL", "0000320193", today=date(2026, 10, 30))


AUDITOR = (
    "<html><body><p>The accompanying financial statements have been prepared assuming that the "
    "Company will continue as a going concern. As discussed in Note 1, the Company has suffered "
    "recurring losses from operations that raise substantial doubt about its ability to continue "
    "as a going concern.</p></body></html>"
)
BOILERPLATE = (
    "<p>Management evaluated whether there are conditions that raise substantial doubt about the "
    "Company&#8217;s ability to continue as a going concern. There is no substantial doubt.</p>"
    "<p>A prolonged downturn could raise substantial doubt about our ability to continue as a "
    "going concern.</p><p>These matters have alleviated the substantial doubt that was raised "
    "about our ability to continue as a going concern.</p>"
)


def test_a_going_concern_doubt_is_flagged_only_when_the_filing_asserts_it() -> None:
    found = gc.detect_going_concern(AUDITOR)
    assert found is not None and found.startswith("As discussed in Note 1")
    assert gc.detect_going_concern(BOILERPLATE) is None
    management = "<div>These conditions raise substantial doubt about the Company’s ability to "
    management += "continue as a going concern within one year after the date of issuance.</div>"
    assert gc.detect_going_concern(management) is not None
    assert gc.html_to_text("<script>x</script><b>A&amp;B</b>") == "A&B"


def test_the_going_concern_job_reads_each_unread_periodic_filing_once(
    research_db, monkeypatch
) -> None:
    from src.research.store.models import FilingIndexRow
    from src.research.store.session import research_session

    with research_session() as s:
        for accn, form, filed, doc in (
            ("0000000001-26-000003", "10-Q", date(2026, 8, 1), "q.htm"),
            ("0000000001-26-000002", "8-K", date(2026, 8, 5), "k.htm"),
            ("0000000001-26-000001", "10-K", date(2026, 2, 10), "k10.htm"),
        ):
            s.add(
                FilingIndexRow(
                    accn=accn, cik="0000000001", form=form, filed=filed, primary_document=doc
                )
            )
    provider = _Provider([], docs={"q.htm": AUDITOR, "k10.htm": "<p>All good.</p>"})
    monkeypatch.setattr(gc, "get_filings_provider", lambda: provider)
    assert gc.ingest_going_concern("SICK", "0000000001", today=date(2026, 10, 30)) == 2
    assert gc.ingest_going_concern("SICK", "0000000001", today=date(2026, 10, 30)) == 0
    with research_session() as s:
        flags = {
            r.form: (r.going_concern, r.going_concern_detail is not None)
            for r in s.query(FilingIndexRow)
        }
    assert flags == {"10-Q": (True, True), "10-K": (False, False), "8-K": (None, False)}


def test_a_missing_document_raises_so_the_drain_retries(research_db, monkeypatch) -> None:
    from src.research.store.models import FilingIndexRow
    from src.research.store.session import research_session

    with research_session() as s:
        s.add(
            FilingIndexRow(
                accn="0000000001-26-000003",
                cik="0000000001",
                form="10-Q",
                filed=date(2026, 8, 1),
                primary_document="q.htm",
            )
        )
    monkeypatch.setattr(gc, "get_filings_provider", lambda: _Provider([]))
    with pytest.raises(RuntimeError, match="No document"):
        gc.ingest_going_concern("SICK", "0000000001", today=date(2026, 10, 30))


def test_the_drain_runs_both_new_job_kinds(research_db, monkeypatch) -> None:
    from src.research.ingest import materialize
    from src.research.store.models import IngestJobRow, SymbolRow
    from src.research.store.session import research_session

    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        materialize, "ingest_submissions", lambda s, c: calls.append(("sub", s, c)) or 3
    )
    monkeypatch.setattr(
        materialize, "ingest_going_concern", lambda s, c: calls.append(("gc", s, c)) or 1
    )
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193"))
    materialize.enqueue("AAPL", "submissions")
    materialize.enqueue("AAPL", "going_concern")
    materialize.enqueue("NOCIK", "submissions")
    assert materialize.drain_ingest_jobs() == 2
    assert calls == [("sub", "AAPL", "0000320193"), ("gc", "AAPL", "0000320193")]
    with research_session() as s:
        failed = s.query(IngestJobRow).filter_by(symbol="NOCIK").one()
    assert "Cannot run job kind" in (failed.last_error or "")
```

  …and apply to `tests/test_value_universe.py` (FRESH's bar on the due weekday is now refetched:
  review M2; the nightly test now covers the sector ETFs; a new test covers the held names'
  going-concern job):

```diff
diff --git a/tests/test_value_universe.py b/tests/test_value_universe.py
index ed9cf55..addfeda 100644
--- a/tests/test_value_universe.py
+++ b/tests/test_value_universe.py
@@ -142,7 +142,13 @@ def research_db(tmp_path, monkeypatch):
 
 def test_the_sweep_queues_only_what_each_name_lacks(research_db) -> None:
     from src.research.ingest.value_universe import enqueue_value_universe
-    from src.research.store.models import CompanyFactsRawRow, DailyBarRow, IngestJobRow, SymbolRow
+    from src.research.store.models import (
+        CompanyFactsRawRow,
+        DailyBarRow,
+        IngestJobRow,
+        SubmissionsStateRow,
+        SymbolRow,
+    )
     from src.research.store.session import research_session
 
     today = date(2026, 10, 29)
@@ -158,11 +164,26 @@ def test_the_sweep_queues_only_what_each_name_lacks(research_db) -> None:
         )
         for i in range(260):
             s.add(DailyBarRow(symbol="FRESH", date=today - timedelta(days=260 - i), close=1.0))
+        s.add(SubmissionsStateRow(cik="0000000001", fetched_at=now))
     counts = enqueue_value_universe(["FRESH", "STALE", "NOCIK"], today=today)
-    assert counts == {"fundamentals": 1, "prices": 2, "no_cik": 1}
+    assert counts == {
+        "fundamentals": 1,
+        "submissions": 1,
+        "going_concern": 0,
+        "prices": 3,
+        "no_cik": 1,
+    }
     with research_session() as s:
         jobs = sorted((j.symbol, j.kind) for j in s.query(IngestJobRow))
-    assert jobs == [("NOCIK", "prices"), ("STALE", "fundamentals"), ("STALE", "prices")]
+    # FRESH's bars end on the due weekday: refetched, since that bar may have been written while
+    # its session was still forming (review M2).
+    assert jobs == [
+        ("FRESH", "prices"),
+        ("NOCIK", "prices"),
+        ("STALE", "fundamentals"),
+        ("STALE", "prices"),
+        ("STALE", "submissions"),
+    ]
 
 
 def test_the_drain_runs_a_prices_job(research_db, monkeypatch) -> None:
@@ -213,22 +234,40 @@ def test_bars_are_stale_once_they_miss_the_last_weekday() -> None:
     assert last_weekday_before(date(2026, 11, 4)) == date(2026, 11, 3)
 
 
-def test_the_nightly_sweep_refreshes_yesterdays_bars_and_spys(research_db, monkeypatch) -> None:
+def test_the_nightly_sweep_refreshes_every_bar_and_the_benchmarks(research_db, monkeypatch) -> None:
     from src.research.ingest import value_universe as sweep
     from src.research.store.models import DailyBarRow, IngestJobRow
     from src.research.store.session import research_session
 
     monday = date(2026, 11, 2)
     with research_session() as s:
-        for symbol, last in (("FRESH", date(2026, 10, 30)), ("OLD", date(2026, 10, 29))):
+        for symbol, last in (("TODAY", monday), ("OLD", date(2026, 10, 29))):
             for i in range(260):
                 s.add(DailyBarRow(symbol=symbol, date=last - timedelta(days=i), close=1.0))
-    monkeypatch.setattr(sweep, "value_names", lambda: ["FRESH", "OLD"])
-    assert sweep.enqueue_value_universe(today=monday) == {
-        "fundamentals": 0,
-        "prices": 2,
-        "no_cik": 2,
-    }
+    monkeypatch.setattr(sweep, "value_names", lambda: ["TODAY", "OLD"])
+    counts = sweep.enqueue_value_universe(today=monday)
+    etfs = sweep.benchmark_names()
+    assert etfs[0] == "SPY" and "XLK" in etfs and "XLRE" in etfs and len(etfs) == 12
+    assert counts["prices"] == 1 + len(etfs) and counts["no_cik"] == 2
     with research_session() as s:
-        jobs = sorted((j.symbol, j.kind) for j in s.query(IngestJobRow))
-    assert jobs == [("OLD", "prices"), ("SPY", "prices")]  # SPY's bars, never its filings
+        jobs = {(j.symbol, j.kind) for j in s.query(IngestJobRow)}
+    # SPY's and the sector ETFs' bars, never their filings; a bar dated today is not refetched.
+    assert jobs == {("OLD", "prices"), *((e, "prices") for e in etfs)}
+
+
+def test_the_sweep_reads_held_names_filings_for_a_going_concern_doubt(
+    research_db, monkeypatch
+) -> None:
+    from src.research.ingest import value_universe as sweep
+    from src.research.store.models import IngestJobRow, SymbolRow
+    from src.research.store.session import research_session
+
+    with research_session() as s:
+        s.add(SymbolRow(symbol="HELD", cik="0000000001"))
+        s.add(SymbolRow(symbol="FREE", cik="0000000002"))
+    monkeypatch.setattr(sweep, "read_keep_fresh", lambda: ["HELD"])
+    counts = sweep.enqueue_value_universe(["HELD", "FREE"], today=date(2026, 11, 2))
+    assert counts["going_concern"] == 1 and counts["submissions"] == 2
+    with research_session() as s:
+        kinds = {j.kind for j in s.query(IngestJobRow).filter_by(symbol="HELD")}
+    assert kinds == {"fundamentals", "submissions", "going_concern", "prices"}
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_research_submissions.py tests/test_value_universe.py`
  Expected: FAIL — `ImportError: cannot import name 'going_concern' from 'src.research.ingest'`
  (and the sweep counts).

- [x] **Step 3: The EDGAR client** — apply to `src/data/edgar_backend.py` (`get_json` keeps its
  contract; the GET, the limiter, the breaker and the retries move to `_get`, which `get_text`
  shares):

```diff
diff --git a/src/data/edgar_backend.py b/src/data/edgar_backend.py
index 380484f..0f7723e 100644
--- a/src/data/edgar_backend.py
+++ b/src/data/edgar_backend.py
@@ -23,6 +23,8 @@ log = logging.getLogger(__name__)
 
 DIRECTORY_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
 COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
+SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
+ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{document}"
 
 
 def _contact_email() -> str:
@@ -78,12 +80,13 @@ class EdgarClient:
         )
         self._max_retries = max_retries
 
-    def get_json(self, url: str, *, etag: str | None = None) -> tuple[dict | None, str | None]:
-        """Fetch JSON. Returns (payload, etag); (None, etag) on 304 or on failure."""
+    def _get(self, url: str, *, etag: str | None = None) -> httpx.Response | None:
+        """One GET under the rate limit and the circuit breaker, retried on a throttle or a
+        transient outage. The 200 or 304 response; None on any failure or an open circuit."""
         breaker = get_breaker("edgar")
         if not breaker.allow():
             # Open circuit: no network call. The affected section renders UNAVAILABLE.
-            return None, etag
+            return None
 
         headers = {"User-Agent": user_agent()}
         if etag:
@@ -96,14 +99,11 @@ class EdgarClient:
             except httpx.HTTPError as exc:
                 log.warning("EDGAR request failed for %s: %s", url, exc)
                 breaker.record_failure()
-                return None, etag
+                return None
 
-            if resp.status_code == 304:
+            if resp.status_code in (200, 304):
                 breaker.record_success()
-                return None, etag
-            if resp.status_code == 200:
-                breaker.record_success()
-                return resp.json(), resp.headers.get("ETag", etag)
+                return resp
             if resp.status_code in (403, 429, 500, 502, 503, 504) and attempt < self._max_retries:
                 # 403/429: throttle. 5xx: EDGAR transient outage. Retry with backoff.
                 retry_after = resp.headers.get("Retry-After")
@@ -114,9 +114,23 @@ class EdgarClient:
                 continue
             log.warning("EDGAR returned %s for %s", resp.status_code, url)
             breaker.record_failure()
-            return None, etag
+            return None
         breaker.record_failure()
-        return None, etag
+        return None
+
+    def get_json(self, url: str, *, etag: str | None = None) -> tuple[dict | None, str | None]:
+        """Fetch JSON. Returns (payload, etag); (None, etag) on 304 or on failure."""
+        resp = self._get(url, etag=etag)
+        if resp is None or resp.status_code == 304:
+            return None, etag
+        return resp.json(), resp.headers.get("ETag", etag)
+
+    def get_text(self, url: str) -> str | None:
+        """Fetch a document as text (a filing's primary document). None on failure."""
+        resp = self._get(url)
+        if resp is None or resp.status_code != 200:
+            return None
+        return resp.text
 
 
 class EdgarSymbolDirectoryProvider:
@@ -152,7 +166,9 @@ class EdgarSymbolDirectoryProvider:
 
 
 class EdgarFilingsProvider:
-    """XBRL company facts. One document per filer, sometimes tens of megabytes."""
+    """XBRL company facts (one document per filer, sometimes tens of megabytes), the filer's
+    ``submissions`` feed (its recent filings with form, dates and 8-K item tags) and a filing's
+    primary document."""
 
     def __init__(self, client: EdgarClient | None = None) -> None:
         self._client = client or EdgarClient()
@@ -165,3 +181,22 @@ class EdgarFilingsProvider:
             COMPANYFACTS_URL.format(cik=cik.zfill(10)), etag=etag
         )
         return payload or {}, new_etag
+
+    def get_submissions(self, cik: str, *, etag: str | None = None) -> tuple[dict, str | None]:
+        """The filer's ``submissions/CIK##########.json``: its recent filings. Same contract as
+        :meth:`get_company_facts` (``({}, etag)`` on a 304 or a failure)."""
+        cik = (cik or "").strip()
+        if not cik:
+            return {}, None
+        payload, new_etag = self._client.get_json(
+            SUBMISSIONS_URL.format(cik=cik.zfill(10)), etag=etag
+        )
+        return payload or {}, new_etag
+
+    def get_filing_text(self, cik: str, accn: str, document: str) -> str:
+        """A filing's primary document as text; ``""`` when unavailable. Never raises."""
+        cik = (cik or "").strip().lstrip("0")
+        if not cik or not accn or not document:
+            return ""
+        url = ARCHIVE_URL.format(cik=cik, accn=accn.replace("-", ""), document=document)
+        return self._client.get_text(url) or ""
```

  …and to `src/data/protocols.py`:

```diff
diff --git a/src/data/protocols.py b/src/data/protocols.py
index f72ef3c..bc33dc5 100644
--- a/src/data/protocols.py
+++ b/src/data/protocols.py
@@ -158,6 +158,15 @@ class FilingsProvider(Protocol):
         """
         ...
 
+    def get_submissions(self, cik: str, *, etag: str | None = None) -> tuple[dict, str | None]:
+        """The filer's recent filings (EDGAR's ``submissions`` feed): forms, dates, 8-K item
+        tags, primary documents. Same ``(payload, etag)`` contract as ``get_company_facts``."""
+        ...
+
+    def get_filing_text(self, cik: str, accn: str, document: str) -> str:
+        """One filing's primary document as text; ``""`` when unavailable. Never raises."""
+        ...
+
 
 @runtime_checkable
 class BulkPriceProvider(Protocol):
```

- [x] **Step 4: The research tables** — apply to `src/research/store/models.py`
  (`init_research_db` creates new tables with `create_all`; no migration is needed):

```diff
diff --git a/src/research/store/models.py b/src/research/store/models.py
index 7fe50d2..2845f87 100644
--- a/src/research/store/models.py
+++ b/src/research/store/models.py
@@ -193,8 +193,38 @@ class IngestJobRow(Base):
 
     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
     symbol: Mapped[str] = mapped_column(String(16), index=True)
-    kind: Mapped[str] = mapped_column(String(32))  # fundamentals | prices | news | quote
+    kind: Mapped[str] = mapped_column(String(32))  # fundamentals|prices|submissions|going_concern
     status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
     attempts: Mapped[int] = mapped_column(Integer, default=0)
     last_error: Mapped[str | None] = mapped_column(Text)
     enqueued_at: Mapped[datetime] = mapped_column(DateTime)
+
+
+class FilingIndexRow(Base):
+    """One filing from a filer's EDGAR ``submissions`` feed (value book spec §7.1, §8.5): its form,
+    dates and 8-K item tags, kept for ``submissions.KEEP_DAYS``. Written by the ``submissions``
+    job; a periodic filing's ``going_concern`` by the ``going_concern`` job (None: not read)."""
+
+    __tablename__ = "filing_index"
+
+    accn: Mapped[str] = mapped_column(String(32), primary_key=True)
+    cik: Mapped[str] = mapped_column(String(10))
+    form: Mapped[str] = mapped_column(String(16))
+    filed: Mapped[date] = mapped_column(Date)
+    report_date: Mapped[date | None] = mapped_column(Date)
+    items: Mapped[str] = mapped_column(String(128), default="")  # 8-K item tags, "2.02,9.01"
+    primary_document: Mapped[str | None] = mapped_column(String(200))
+    going_concern: Mapped[bool | None] = mapped_column(Boolean)
+    going_concern_detail: Mapped[str | None] = mapped_column(Text)
+
+    __table_args__ = (Index("ix_filing_index_cik_filed", "cik", "filed"),)
+
+
+class SubmissionsStateRow(Base):
+    """When each filer's ``submissions`` feed was last read, and its ETag (a 304 is free)."""
+
+    __tablename__ = "submissions_state"
+
+    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
+    etag: Mapped[str | None] = mapped_column(String(128))
+    fetched_at: Mapped[datetime] = mapped_column(DateTime)
```

- [x] **Step 5: The two jobs** — create `src/research/ingest/submissions.py`:

```python
"""The research worker's ``submissions`` job (value book spec §7.1 trigger 4, §8.5): each filer's
EDGAR ``submissions/CIK##########.json`` feed, read daily, kept as one ``filing_index`` row per
recent filing with its form, dates and 8-K item tags. No text is read here: the item tags come
with the feed.

The research worker owns every SEC fetch (spec §6.9); the value process reads ``filing_index``
read-only through ``src/common/value_inputs.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from src.data.factory import get_filings_provider
from src.research.store.models import FilingIndexRow, SubmissionsStateRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

KEEP_DAYS = 400  # a filing older than this is dropped from the index
PERIODIC_FORMS = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
EVENT_FORMS = ("8-K", "8-K/A")
FORMS = (*PERIODIC_FORMS, *EVENT_FORMS)


@dataclass(frozen=True, slots=True)
class ParsedFiling:
    accn: str
    form: str
    filed: date
    report_date: date | None
    items: tuple[str, ...]
    primary_document: str | None


def _date(raw: object) -> date | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def parse_submissions(payload: dict, *, since: date) -> list[ParsedFiling]:
    """The periodic and 8-K filings in the feed's ``filings.recent`` block filed on or after
    *since*. The block is column arrays of equal length; a malformed row is skipped."""
    recent = (payload.get("filings") or {}).get("recent") or {}
    accns = recent.get("accessionNumber") or []
    out: list[ParsedFiling] = []
    for i, accn in enumerate(accns):

        def col(name: str, i: int = i) -> object:
            values = recent.get(name) or []
            return values[i] if i < len(values) else None

        form = col("form")
        filed = _date(col("filingDate"))
        if not isinstance(accn, str) or form not in FORMS or filed is None or filed < since:
            continue
        items = col("items")
        doc = col("primaryDocument")
        out.append(
            ParsedFiling(
                accn=accn,
                form=str(form),
                filed=filed,
                report_date=_date(col("reportDate")),
                items=tuple(
                    t.strip() for t in (items if isinstance(items, str) else "").split(",") if t
                ),
                primary_document=doc if isinstance(doc, str) and doc else None,
            )
        )
    return out


def ingest_submissions(symbol: str, cik: str, *, today: date | None = None) -> int:
    """Read the feed (ETag-reused) and upsert the index. Returns rows written. A 304 only
    stamps the read; a failure raises so the drain retries the job."""
    today = today or datetime.now(UTC).date()
    with research_session() as session:
        state = session.get(SubmissionsStateRow, cik)
        etag_in = state.etag if state is not None else None
    payload, etag = get_filings_provider().get_submissions(cik, etag=etag_in)
    now = datetime.now(UTC).replace(tzinfo=None)
    if not payload:
        if etag_in is not None and etag == etag_in:
            with research_session() as session:
                seen = session.get(SubmissionsStateRow, cik)
                if seen is not None:
                    seen.fetched_at = now
            return 0
        raise RuntimeError(f"No submissions feed for {symbol} (CIK {cik})")
    since = today - timedelta(days=KEEP_DAYS)
    filings = parse_submissions(payload, since=since)
    with research_session() as session:
        for f in filings:
            row = session.get(FilingIndexRow, f.accn)
            if row is None:
                session.add(
                    FilingIndexRow(
                        accn=f.accn,
                        cik=cik,
                        form=f.form,
                        filed=f.filed,
                        report_date=f.report_date,
                        items=",".join(f.items),
                        primary_document=f.primary_document,
                    )
                )
            else:  # the feed's facts may be corrected; a going-concern read is kept
                row.form, row.filed, row.report_date = f.form, f.filed, f.report_date
                row.items, row.primary_document = ",".join(f.items), f.primary_document
        session.query(FilingIndexRow).filter(
            FilingIndexRow.cik == cik, FilingIndexRow.filed < since
        ).delete()
        state = session.get(SubmissionsStateRow, cik)
        if state is None:
            session.add(SubmissionsStateRow(cik=cik, etag=etag, fetched_at=now))
        else:
            state.etag, state.fetched_at = etag, now
    log.info("Submissions for %s: %d filings indexed", symbol, len(filings))
    return len(filings)
```

  …and `src/research/ingest/going_concern.py`:

```python
"""The research worker's ``going_concern`` job (value book spec §7: "a going-concern flag in the
filing" is a thesis exit). For the names the value book holds in its shadow record (the keep-fresh
list), each recent 10-K/10-Q's primary document is read once and scanned, deterministically, for a
going-concern doubt that the filing **asserts** (the auditor's paragraph or management's
conclusion), never one it merely mentions: a sentence must say the conditions "raise" substantial
doubt about the ability to continue as a going concern, with no hedge or negation in it ("could",
"may", "if", "whether", "no", "not", "alleviated", ...). Only the flag and the sentence are stored.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import UTC, date, datetime, timedelta

from src.data.factory import get_filings_provider
from src.research.ingest.submissions import KEEP_DAYS, PERIODIC_FORMS
from src.research.store.models import FilingIndexRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

MAX_PER_JOB = 2  # filings read per job (a 10-K can be tens of megabytes)
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_DOUBT = re.compile(r"substantial\s+doubt\b.*\bgoing\s+concern\b", re.I)
_ASSERT = re.compile(r"\braise[sd]?\b", re.I)
_HEDGE = re.compile(
    r"\b(no|not|none|could|can|may|might|would|should|if|whether|unless|absent|absence|"
    r"alleviat\w*|mitigat\w*|evaluat\w*|assess\w*)\b",
    re.I,
)


def html_to_text(raw: str) -> str:
    """Tags out, entities decoded, whitespace collapsed (curly apostrophes made plain)."""
    text = _TAG.sub(" ", _SCRIPT.sub(" ", raw))
    return _SPACE.sub(" ", html.unescape(text)).replace("’", "'").strip()


def detect_going_concern(raw: str) -> str | None:
    """The first sentence asserting substantial doubt about the ability to continue as a going
    concern, cut to 300 characters; None when the filing asserts none."""
    for sentence in _SENTENCE.split(html_to_text(raw)):
        if _DOUBT.search(sentence) and _ASSERT.search(sentence) and not _HEDGE.search(sentence):
            return sentence[:300]
    return None


def ingest_going_concern(symbol: str, cik: str, *, today: date | None = None) -> int:
    """Read the unread recent periodic filings of one filer (newest first, ``MAX_PER_JOB`` at a
    time). Returns how many were read; 0 (no network) when none is unread. A document that does
    not come back raises, so the drain retries the job."""
    today = today or datetime.now(UTC).date()
    since = today - timedelta(days=KEEP_DAYS)
    with research_session() as session:
        todo = [
            (r.accn, r.primary_document)
            for r in session.query(FilingIndexRow)
            .filter(
                FilingIndexRow.cik == cik,
                FilingIndexRow.form.in_(PERIODIC_FORMS),
                FilingIndexRow.going_concern.is_(None),
                FilingIndexRow.primary_document.is_not(None),
                FilingIndexRow.filed >= since,
            )
            .order_by(FilingIndexRow.filed.desc())
            .limit(MAX_PER_JOB)
        ]
    provider = get_filings_provider()
    for accn, document in todo:
        assert document is not None
        text = provider.get_filing_text(cik, accn, document)
        if not text:
            raise RuntimeError(f"No document for {symbol} {accn}")
        found = detect_going_concern(text)
        with research_session() as session:
            row = session.get(FilingIndexRow, accn)
            if row is not None:
                row.going_concern = found is not None
                row.going_concern_detail = found
        if found:
            log.warning("Going-concern doubt in %s %s: %s", symbol, accn, found)
    return len(todo)
```

- [x] **Step 6: The drain and the sweep** — apply to `src/research/ingest/materialize.py`:

```diff
diff --git a/src/research/ingest/materialize.py b/src/research/ingest/materialize.py
index f228e45..04f1c44 100644
--- a/src/research/ingest/materialize.py
+++ b/src/research/ingest/materialize.py
@@ -33,7 +33,9 @@ from pydantic import BaseModel
 from src.common.config import get_config
 from src.research.checks.payload import ChecksPayload, build_checks_payload
 from src.research.ingest.fundamentals import ingest_fundamentals, load_cached_financials
+from src.research.ingest.going_concern import ingest_going_concern
 from src.research.ingest.prices import ingest_daily_bars
+from src.research.ingest.submissions import ingest_submissions
 from src.research.schemas import NormalizedFinancials
 from src.research.store.models import IngestJobRow, QuoteRow, SymbolRow
 from src.research.store.session import research_session
@@ -409,6 +411,18 @@ def drain_ingest_jobs(max_jobs: int = 20) -> int:
                 ingest_fundamentals(symbol, cik)
             except Exception as exc:
                 error = str(exc)
+        elif kind == "submissions" and cik:
+            # The filer's EDGAR submissions feed: filings and 8-K item tags (value book §7.1).
+            try:
+                ingest_submissions(symbol, cik)
+            except Exception as exc:
+                error = str(exc)
+        elif kind == "going_concern" and cik:
+            # A held name's newest periodic filings, read once for a going-concern doubt (§7).
+            try:
+                ingest_going_concern(symbol, cik)
+            except Exception as exc:
+                error = str(exc)
         elif kind == "prices":
             # Daily bars for a name no warm tier covers (the value book's universes, spec §6.1).
             try:
```

  …and to `src/research/ingest/value_universe.py`:

```diff
diff --git a/src/research/ingest/value_universe.py b/src/research/ingest/value_universe.py
index 256f37c..2ace4d0 100644
--- a/src/research/ingest/value_universe.py
+++ b/src/research/ingest/value_universe.py
@@ -2,9 +2,12 @@
 
 The research worker owns every SEC and price fetch; the value process only reads research.db.
 This queues a ``fundamentals`` job (companyfacts, ETag-reused) for every name whose raw payload
-is missing or older than a day, and a ``prices`` job for every name whose daily bars are short
-or stale, across both value universes. ``drain_ingest_jobs`` runs them at its own pace (EDGAR is
-rate-limited to 10 requests a second in ``EdgarClient``).
+is missing or older than a day, a ``submissions`` job (the filer's recent filings and 8-K item
+tags, spec §7.1) on the same daily cadence, and a ``prices`` job for every name whose daily bars
+are short or not yet settled through the last weekday, across both value universes; the names the
+shadow record holds also get a ``going_concern`` job (a no-op once their newest filings are read).
+``drain_ingest_jobs`` runs them at its own pace (EDGAR is rate-limited to 10 requests a second in
+``EdgarClient``).
 """
 
 from __future__ import annotations
@@ -18,18 +21,32 @@ from src.common.config import get_config
 from src.common.value_keep_fresh import read_keep_fresh
 from src.common.value_universe import build_value_universe
 from src.research.ingest.materialize import enqueue
-from src.research.store.models import CompanyFactsRawRow, DailyBarRow, SymbolRow
+from src.research.store.models import (
+    CompanyFactsRawRow,
+    DailyBarRow,
+    SubmissionsStateRow,
+    SymbolRow,
+)
 from src.research.store.session import research_session
 
 log = logging.getLogger(__name__)
 
 MIN_BARS = 260
 FACTS_MAX_AGE = timedelta(days=1)
+# The submissions feed is read every night (spec §8.5 "poll daily"): a read at 02:05 is 23h55m
+# old at the next 02:00 sweep, so a one-day age would skip every other night.
+SUBMISSIONS_MAX_AGE = timedelta(hours=20)
 # The value book's benchmark (spec §6.8): its bars are refreshed with the universe's, never its
 # filings (an ETF has none). SPY is the spreads book's underlying, so it is never in universe.yaml.
 BENCHMARKS = ("SPY",)
 
 
+def benchmark_names() -> tuple[str, ...]:
+    """SPY and every sector ETF the re-evaluation's residual model reads (spec §7.1)."""
+    etfs = get_config().value.rules.reevaluation
+    return tuple(dict.fromkeys([*BENCHMARKS, etfs.fallback_etf, *etfs.sector_etfs.values()]))
+
+
 def last_weekday_before(today: date) -> date:
     """The newest weekday strictly before *today*: the session a nightly sweep must have."""
     day = today - timedelta(days=1)
@@ -54,25 +71,34 @@ def enqueue_value_universe(
     today: date | None = None,
     bars_only: tuple[str, ...] | None = None,
 ) -> dict[str, int]:
-    """Queue what each name lacks. Returns counts: fundamentals, prices, no_cik.
+    """Queue what each name lacks. Returns counts: fundamentals, submissions, going_concern,
+    prices, no_cik.
 
-    Bars are stale once the newest is older than the last weekday before *today* (the value
-    book marks its shadow record every session). The nightly call (no *names*) also refreshes
-    the benchmark's bars (*bars_only*, default ``BENCHMARKS``)."""
+    Bars are refetched until the newest is past the last weekday before *today*: a bar dated
+    that weekday may have been written while its session was still forming (review M2), and the
+    value book marks its shadow record every session. The nightly call (no *names*) also
+    refreshes the benchmarks' bars (*bars_only*, default ``benchmark_names()``)."""
+    held = set(read_keep_fresh())
     if names is None:
         names = value_names()
-        bars_only = BENCHMARKS if bars_only is None else bars_only
+        bars_only = benchmark_names() if bars_only is None else bars_only
     extra = [s for s in (bars_only or ()) if s not in names]
     today = today or datetime.now(UTC).date()
     due = last_weekday_before(today)
     now = datetime.now(UTC).replace(tzinfo=None)
-    counts = {"fundamentals": 0, "prices": 0, "no_cik": 0}
+    counts = {"fundamentals": 0, "submissions": 0, "going_concern": 0, "prices": 0, "no_cik": 0}
     with research_session() as s:
         ciks = {r.symbol: r.cik for r in s.query(SymbolRow).filter(SymbolRow.symbol.in_(names))}
         fetched = {
             cik: at
             for cik, at in s.execute(select(CompanyFactsRawRow.cik, CompanyFactsRawRow.fetched_at))
         }
+        read = {
+            cik: at
+            for cik, at in s.execute(
+                select(SubmissionsStateRow.cik, SubmissionsStateRow.fetched_at)
+            )
+        }
         bars = {
             sym: (n, last)
             for sym, n, last in s.execute(
@@ -86,13 +112,20 @@ def enqueue_value_universe(
         if not cik:
             counts["no_cik"] += 1
         else:
-            at = fetched.get(cik)
-            if at is None or now - at.replace(tzinfo=None) > FACTS_MAX_AGE:
-                enqueue(symbol, "fundamentals")
-                counts["fundamentals"] += 1
+            for kind, seen, age in (
+                ("fundamentals", fetched, FACTS_MAX_AGE),
+                ("submissions", read, SUBMISSIONS_MAX_AGE),
+            ):
+                at = seen.get(cik)
+                if at is None or now - at.replace(tzinfo=None) > age:
+                    enqueue(symbol, kind)
+                    counts[kind] += 1
+            if symbol in held:
+                enqueue(symbol, "going_concern")
+                counts["going_concern"] += 1
     for symbol in [*names, *extra]:
         n, last = bars.get(symbol, (0, None))
-        if n < MIN_BARS or last is None or last < due:
+        if n < MIN_BARS or last is None or last <= due:
             enqueue(symbol, "prices")
             counts["prices"] += 1
     log.info("Value sweep queued %s for %d names", counts, len(names))
```

- [x] **Step 7: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_research_submissions.py tests/test_value_universe.py tests/test_edgar_backend.py tests/test_edgar_companyfacts.py tests/test_research_materialize.py tests/test_research_store.py tests/test_ingest_fundamentals.py tests/test_research_worker.py tests/test_value_fence.py`
  Expected: PASS (`test_research_submissions.py` 9, `test_value_universe.py` 13). Then
  `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the nine touched files and
  `.venv/bin/mypy src/data src/research` — all clean.

- [x] **Step 8: Commit**

  ```bash
  git add src/data/edgar_backend.py src/data/protocols.py src/research/store/models.py src/research/ingest/submissions.py src/research/ingest/going_concern.py src/research/ingest/materialize.py src/research/ingest/value_universe.py tests/test_research_submissions.py tests/test_value_universe.py
  git commit -m "feat(research): the EDGAR submissions feed, the going-concern read, the sector ETFs' bars"
  ```

---

### Task 3: The readers — filings, the going-concern flag, the day's low

**Files:**
- Modify: `src/common/value_types.py` (lines 73–75; insert before line 82)
- Modify: `src/common/value_inputs.py` (after line 26; the import blocks at 31–39 and 47; after
  line 211; lines 224–225; insert before line 351)
- Modify: `tests/test_value_inputs.py` (the import block at 18–24; after line 194; insert before
  line 284)

**Interfaces:**
- Consumes: `FilingIndexRow` (Task 2).
- Produces: `DayBar.high` / `DayBar.low` (`float | None`); `FilingEvent(accn, form, filed, items:
  list[str], going_concern: bool | None)`; `NewsVolume(last_24h: int, daily_median_30d: float)`;
  `value_inputs.filings_between(session, symbols, start, end) -> dict[str, list[FilingEvent]]`
  (filed after *start*, on or before *end*, oldest first; `{}` without the table);
  `value_inputs.going_concern_flags(session, symbols, as_of) -> dict[str, bool]` (the newest **read**
  periodic filing; a name with none read is absent).

- [x] **Step 1: Write the failing tests** — apply to `tests/test_value_inputs.py`:

```diff
diff --git a/tests/test_value_inputs.py b/tests/test_value_inputs.py
index d401fc7..fc723a3 100644
--- a/tests/test_value_inputs.py
+++ b/tests/test_value_inputs.py
@@ -19,6 +19,7 @@ from src.research.store.models import (
     Base,
     CompanyFactsRawRow,
     DailyBarRow,
+    FilingIndexRow,
     FinancialRow,
     SymbolRow,
 )
@@ -192,6 +193,8 @@ def test_day_bars_carry_the_technicals_measured_at_each_close() -> None:
     later = vi.build_day_bars(bars, after=days[57].date)
     assert [d.date for d in later] == [days[58].date, days[59].date]
     assert later[0].sma50 == days[58].sma50  # measured on the whole history, not the tail
+    assert days[5].high == pytest.approx(bars["high"].iloc[5])  # the shock rules read the low
+    assert days[5].low == pytest.approx(bars["low"].iloc[5])
     no_open = vi.build_day_bars(bars.drop(columns=["open"]))
     assert no_open[0].open is None  # unknown, never zero
     assert vi.build_day_bars(bars.iloc[:0]) == []
@@ -281,6 +284,56 @@ def test_the_shadow_records_readers(research_file) -> None:
         assert vi.filings_coverage(s, []) == (0, 0)
 
 
+def test_the_filings_feed_readers(research_file) -> None:
+    engine = create_engine(f"sqlite:///{research_file}")
+    with Session(engine) as s:
+        for accn, form, filed, items, gc in (
+            ("a1", "10-Q", date(2025, 5, 5), "", False),
+            ("a2", "8-K", date(2025, 8, 26), "5.02,9.01", None),
+            ("a3", "10-Q", date(2025, 8, 28), "", True),
+            ("a4", "10-Q", date(2025, 11, 4), "", None),  # filed later, not read yet
+        ):
+            s.add(
+                FilingIndexRow(
+                    accn=accn,
+                    cik="0000000001",
+                    form=form,
+                    filed=filed,
+                    items=items,
+                    going_concern=gc,
+                )
+            )
+        s.commit()
+    with vi.research_read() as s:
+        assert s is not None
+        got = vi.filings_between(s, ["STDY", "NONE"], date(2025, 8, 1), date(2025, 8, 28))
+        assert [(f.accn, f.form, f.items) for f in got["STDY"]] == [
+            ("a2", "8-K", ["5.02", "9.01"]),
+            ("a3", "10-Q", []),
+        ]  # after the start, on or before the end, oldest first
+        assert (
+            "NONE" not in got
+            and vi.filings_between(s, [], date(2025, 1, 1), date(2026, 1, 1)) == {}
+        )
+        assert vi.going_concern_flags(s, ["STDY"], date(2025, 8, 27)) == {"STDY": False}
+        assert vi.going_concern_flags(s, ["STDY"], date(2025, 12, 1)) == {"STDY": True}
+        assert vi.going_concern_flags(s, ["STDY"], date(2025, 5, 1)) == {}  # unknown, not "no"
+
+
+def test_a_research_db_without_the_filings_index_reads_as_empty(tmp_path, monkeypatch) -> None:
+    """The value process may run before the research worker has created the new table."""
+    path = tmp_path / "old.db"
+    engine = create_engine(f"sqlite:///{path}")
+    SymbolRow.__table__.create(engine)
+    monkeypatch.setattr(vi, "_resolve_path", lambda: str(path))
+    vi.reset_engine()
+    with vi.research_read() as s:
+        assert s is not None
+        assert vi.filings_between(s, ["STDY"], date(2025, 1, 1), date(2026, 1, 1)) == {}
+        assert vi.going_concern_flags(s, ["STDY"], date(2026, 1, 1)) == {}
+    vi.reset_engine()
+
+
 def test_a_missing_research_db_is_none_not_an_error(tmp_path, monkeypatch) -> None:
     monkeypatch.setattr(vi, "_resolve_path", lambda: str(tmp_path / "absent.db"))
     vi.reset_engine()
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_inputs.py`
  Expected: FAIL — `AttributeError: 'DayBar' object has no attribute 'high'` and
  `module 'src.common.value_inputs' has no attribute 'filings_between'`.

- [x] **Step 3: The shapes** — apply to `src/common/value_types.py` (it still imports only the
  standard library and pydantic: `test_value_types_is_plain_pydantic`):

```diff
diff --git a/src/common/value_types.py b/src/common/value_types.py
index cad7621..2496552 100644
--- a/src/common/value_types.py
+++ b/src/common/value_types.py
@@ -72,6 +72,8 @@ class DayBar(BaseModel):
 
     date: date
     open: float | None = None
+    high: float | None = None
+    low: float | None = None
     close: float
     sma20: float | None = None
     sma50: float | None = None
@@ -79,6 +81,26 @@ class DayBar(BaseModel):
     atr14: float | None = None
 
 
+class FilingEvent(BaseModel):
+    """One filing from EDGAR's submissions feed (spec §7.1 trigger 4): a periodic report or an
+    8-K with its item tags. ``going_concern`` is the research worker's read of a periodic filing
+    (None: not read, or not a periodic filing)."""
+
+    accn: str
+    form: str
+    filed: date
+    items: list[str] = Field(default_factory=list)
+    going_concern: bool | None = None
+
+
+class NewsVolume(BaseModel):
+    """Spec §7.1 trigger 5, handed in as plain data by the value process: one name's news items
+    over the last 24 hours and its daily median over the 30 days before them."""
+
+    last_24h: int
+    daily_median_30d: float
+
+
 class Classification(BaseModel):
     sector: str | None = None
     industry: str | None = None
```

- [x] **Step 4: The readers** — apply to `src/common/value_inputs.py`:

```diff
diff --git a/src/common/value_inputs.py b/src/common/value_inputs.py
index 47eb429..5564fa6 100644
--- a/src/common/value_inputs.py
+++ b/src/common/value_inputs.py
@@ -24,6 +24,7 @@ from typing import Any
 import pandas as pd
 from sqlalchemy import create_engine, func, select
 from sqlalchemy.engine import Engine
+from sqlalchemy.exc import OperationalError
 from sqlalchemy.orm import Session, sessionmaker
 
 from src.analytics.technicals import atr14_series, rsi14_series
@@ -31,6 +32,7 @@ from src.common.config import get_config
 from src.common.value_types import (
     AnnualPeriod,
     DayBar,
+    FilingEvent,
     InstantPoint,
     MarketFacts,
     PriceSeries,
@@ -44,7 +46,13 @@ from src.research.ingest.concepts import (
     select_ttm,
 )
 from src.research.schemas import Fact
-from src.research.store.models import CompanyFactsRawRow, DailyBarRow, FinancialRow, SymbolRow
+from src.research.store.models import (
+    CompanyFactsRawRow,
+    DailyBarRow,
+    FilingIndexRow,
+    FinancialRow,
+    SymbolRow,
+)
 
 log = logging.getLogger(__name__)
 
@@ -209,6 +217,8 @@ def build_day_bars(bars: pd.DataFrame, after: date | None = None) -> list[DayBar
         return []
     close = bars["close"].astype(float)
     opens = _column(bars["open"]) if "open" in bars.columns else [None] * len(close)
+    highs = _column(bars["high"].astype(float))
+    lows = _column(bars["low"].astype(float))
     sma20 = _column(close.rolling(20).mean())
     sma50 = _column(close.rolling(50).mean())
     rsi = _column(rsi14_series(close), 15)
@@ -222,6 +232,8 @@ def build_day_bars(bars: pd.DataFrame, after: date | None = None) -> list[DayBar
             DayBar(
                 date=day,
                 open=opens[i],
+                high=highs[i],
+                low=lows[i],
                 close=float(close.iloc[i]),
                 sma20=sma20[i],
                 sma50=sma50[i],
@@ -348,6 +360,65 @@ def closes_on(session: Session, symbols: list[str], day: date) -> dict[str, floa
     return {symbol: float(close) for symbol, close in rows if close is not None}
 
 
+def filings_between(
+    session: Session, symbols: list[str], start: date, end: date
+) -> dict[str, list[FilingEvent]]:
+    """Each symbol's indexed filings filed after *start* and on or before *end*, oldest first
+    (spec §7.1 trigger 4). Empty when the research worker has not built the index yet."""
+    if not symbols:
+        return {}
+    try:
+        rows = session.execute(
+            select(SymbolRow.symbol, FilingIndexRow)
+            .join(FilingIndexRow, FilingIndexRow.cik == SymbolRow.cik)
+            .where(
+                SymbolRow.symbol.in_(symbols),
+                FilingIndexRow.filed > start,
+                FilingIndexRow.filed <= end,
+            )
+            .order_by(FilingIndexRow.filed, FilingIndexRow.accn)
+        ).all()
+    except OperationalError:  # a research.db the worker has not migrated yet
+        log.warning("value_inputs: research.db has no filing_index yet")
+        return {}
+    out: dict[str, list[FilingEvent]] = {}
+    for symbol, row in rows:
+        out.setdefault(symbol, []).append(
+            FilingEvent(
+                accn=row.accn,
+                form=row.form,
+                filed=row.filed,
+                items=[t for t in row.items.split(",") if t],
+                going_concern=row.going_concern,
+            )
+        )
+    return out
+
+
+def going_concern_flags(session: Session, symbols: list[str], as_of: date) -> dict[str, bool]:
+    """Each symbol's going-concern read of its newest **read** periodic filing filed on or before
+    *as_of* (spec §7). A name none of whose recent periodic filings has been read is absent:
+    unknown, never "no doubt"."""
+    periodic = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
+    if not symbols:
+        return {}
+    try:
+        rows = session.execute(
+            select(SymbolRow.symbol, FilingIndexRow.going_concern)
+            .join(FilingIndexRow, FilingIndexRow.cik == SymbolRow.cik)
+            .where(
+                SymbolRow.symbol.in_(symbols),
+                FilingIndexRow.form.in_(periodic),
+                FilingIndexRow.filed <= as_of,
+                FilingIndexRow.going_concern.is_not(None),
+            )
+            .order_by(FilingIndexRow.filed, FilingIndexRow.accn)
+        ).all()
+    except OperationalError:
+        return {}
+    return {symbol: bool(flag) for symbol, flag in rows}  # the newest read wins
+
+
 def current_fingerprint_parts(session: Session, symbol: str) -> dict[str, Any]:
     """The cheap half of the ticker-file fingerprint (spec §6.9): the newest accession in
     ``financials`` and the newest bar, without parsing the raw payload."""
```

- [x] **Step 5: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_inputs.py tests/test_value_shadow.py tests/test_value_fence.py`
  Expected: PASS (`test_value_inputs.py` 15). Then ruff check/format and `.venv/bin/mypy
  src/common/value_types.py src/common/value_inputs.py` — clean.

- [x] **Step 6: Commit, then the section's Progress-log commit**

  ```bash
  git add src/common/value_types.py src/common/value_inputs.py tests/test_value_inputs.py
  git commit -m "feat(value): the filings and going-concern readers; a day's high and low"
  ```

  Then run the **Section A exit** full gate, fill Task 3's row, and commit the plan alone
  (`git add docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md`, then
  `git commit -m "docs(plan): value book Part 3 Progress log - Section A"`).

---

## Section B — The exit engine's Part 3 rules, the re-evaluation logic, the store (Tasks 4–6) · model: sonnet · effort: high

The exit engine learns what a re-evaluation does to a leg (an 8-K thesis exit under every policy,
`full`'s shock stops at the close), the going-concern thesis exit, the rebase, and Part 2's exit
minors M5, M6 and M14. Two new pure modules decide when a re-evaluation opens and what it changes.
`value.db` gains `value_reevaluations` and the `plan` column, migrated on a live database. After this
section every piece is tested alone; Section C wires them into the night.

**Spec to read:** §7 (the bullets from "Initial stop" to "Thesis exits"), §7.1 (all), §16 (the
re-evaluation and revision-3 "Exits" bullets).

**Files the subagent reads:** this section; `src/value/exits.py`, `tests/test_value_exits.py`,
`src/common/config.py` (`ValueExitsCfg`, `ValueReevaluationCfg`), `src/common/value_types.py`
(`DayBar`, `FilingEvent`, `NewsVolume`), `src/value/store.py`, `src/spreads/store.py` (lines
244–262: the `_ADDED_COLUMNS` pattern), `tests/test_value_store.py` (the `value_db` fixture).

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **B1. Section A landed.** Tasks 1–3 ticked; record `git log --oneline main..HEAD | wc -l`
  (three task commits + one `docs(plan)` = 4 if nothing else was needed).
- [ ] **B2. Green, from the worktree root.** `.venv/bin/python -m pytest -q` = baseline + 14,
  `.venv/bin/ruff check .`, `.venv/bin/mypy src`; `FROZEN` holds v3:
  `.venv/bin/python -c "from src.value.ruleset import FROZEN; print(FROZEN)"` prints
  `{'v1': 'e1a1b3b096b1', 'v2': 'd07717fe5348', 'v3': 'ad8841127029'}`.
- [ ] **B3. The code Section B edits is where this plan says.** Each prints the line shown:

  ```bash
  grep -n "^def step($" src/value/exits.py                                                  # 134:
  grep -n "^    # Thesis exits: every policy, Python's numbers only.$" src/value/exits.py    # 196:
  grep -n "^def _full($" src/value/exits.py                                                 # 242:
  grep -n '^        (DayFacts(altman_z=1.5), None, "Altman Z 1.50"),$' tests/test_value_exits.py   # 115:
  grep -n "^class ValueShadowLegRow(ValueBase):$" src/value/store.py                        # 160:
  grep -n "^def init_value_db() -> None:$" src/value/store.py                               # 249:
  ```

- [ ] **B4. The pieces Section B builds on exist.** Each prints at least one line:

  ```bash
  grep -n "^class ValueReevaluationCfg" src/common/config.py
  grep -n "^class FilingEvent\|^class NewsVolume\|    low: float | None = None" src/common/value_types.py
  grep -n "^_ADDED_COLUMNS" src/spreads/store.py
  ```

**Section exit:** three more task commits plus the section's `docs(plan)` commit; full gate green
with pytest = baseline + 39 (14 + 14 + 10 + 1); protected-file diff empty. Record the commit count.

---

### Task 4: The exit engine's Part 3 rules

**Files:** Modify `src/value/exits.py`, `tests/test_value_exits.py`

**Interfaces:**
- Consumes: `DayBar` (with `low`), `ValueExitsCfg`.
- Produces: `Reeval(stop_at_least: float | None, arm_from: float | None, thesis: str | None)`;
  `step(state, day, facts, cfg, reeval: Reeval | None = None)`; `DayFacts.piotroski_missing: int`
  and `DayFacts.going_concern: bool | None`; `LegState.fv_proposed`, `seen_accn`, `trail_floor`
  (all defaulted, so Part 2's stored legs load) and `LegState.rebased(ratio) -> LegState`; event
  kind `shock`.

The transitions this task adds (on top of Part 2's Task 4 table), in the order `step` runs them:

| # | When | Policy | Effect |
|---|---|---|---|
| 1 | a new accession (≠ `seen_accn`) | all | `seen_accn` moves; Altman Z is read only on such a session (M6) |
| 2 | F-score + unknown components ≤ 3 | all | sell all, `thesis` (M5: unknowns count against the exit) |
| 3 | `facts.going_concern` | all | sell all, `thesis` |
| 4 | `reeval.thesis` (an 8-K Major item) | all (main plan) | sell all, `thesis` |
| 5 | effective FV < 90% of the price under SMA50, Python's not | all | one `proposal` per episode (M14) |
| 6 | close ≥ the half-way mark while armed by an up-shock | full | the trail floor gives way to the breakeven |
| 7 | after the close's own checks, nothing sold in full | full | `stop_at_least` raises the stop (never lowers it); `arm_from` arms an unarmed leg with that floor; each a `shock` event |

- [x] **Step 1: Write the failing tests** — apply to `tests/test_value_exits.py`:

```diff
diff --git a/tests/test_value_exits.py b/tests/test_value_exits.py
index 5a50411..ddaf4ec 100644
--- a/tests/test_value_exits.py
+++ b/tests/test_value_exits.py
@@ -1,6 +1,7 @@
-"""The exit engine as a state machine (value book spec §7, §16): stop, arm, half at fair value,
-trail, peak, thesis, catastrophe, time; fair value re-marked only on a new filing; no automatic
-exit reads the effective (Claude) fair value."""
+"""The exit engine as a state machine (value book spec §7, §7.1, §16): stop, arm, half at fair
+value, trail, peak, thesis, catastrophe, time; fair value re-marked only on a new filing; no
+automatic exit reads the effective (Claude) fair value; Part 3's shock stops (full only), the 8-K
+and going-concern thesis exits, and the rebase."""
 
 from __future__ import annotations
 
@@ -14,6 +15,7 @@ from src.value.exits import (
     POLICIES,
     DayFacts,
     LegState,
+    Reeval,
     benchmark_return,
     open_leg,
     step,
@@ -112,7 +114,8 @@ def test_the_peak_signal_when_rsi_falls_back_through_seventy() -> None:
     ("facts", "sma50", "detail"),
     [
         (DayFacts(piotroski=3.0), None, "F-score 3"),
-        (DayFacts(altman_z=1.5), None, "Altman Z 1.50"),
+        (DayFacts(altman_z=1.5, latest_accn="0000000001-26-000002"), None, "Altman Z 1.50"),
+        (DayFacts(going_concern=True), None, "going-concern"),
         # a fair value re-marked from a new filing to below 90% of the price, price under SMA50
         (DayFacts(python_fair_value=90.0, latest_accn="0000000001-26-000002"), 120.0, "fair value"),
     ],
@@ -234,3 +237,90 @@ def test_the_benchmark_return_matches_the_fills() -> None:
     assert benchmark_return([(d1, 0.5), (d2, 0.5)], opens, 500.0) == pytest.approx(0.02)
     assert benchmark_return([(d1, 0.5), (D0, 0.5)], opens, 500.0) is None
     assert benchmark_return([], opens, 500.0) is None
+
+
+def test_an_unknown_f_score_component_counts_against_the_exit() -> None:
+    """Review M5: an unknown component scores 0, so F-score 3 with one unknown could be 4."""
+    _, events = run(leg("value"), [bar(1, 105.0)], DayFacts(piotroski=3.0, piotroski_missing=1))
+    assert events == []
+    _, events = run(leg("value"), [bar(1, 105.0)], DayFacts(piotroski=2.0, piotroski_missing=1))
+    assert events == [("thesis", 1.0)]
+
+
+def test_the_altman_z_exit_is_read_only_when_a_new_filing_lands() -> None:
+    """Review M6: Z carries the market cap. A new filing with Z 2.0 holds; the price then falls
+    and tonight's Z reads 1.5 on the same filing: no sale until the next filing says so."""
+    newer = "0000000001-26-000002"
+    state, events = run(leg("value"), [bar(1, 105.0)], DayFacts(altman_z=2.0, latest_accn=newer))
+    assert events == [] and state.seen_accn == newer
+    state, events = run(state, [bar(2, 95.0)], DayFacts(altman_z=1.5, latest_accn=newer))
+    assert events == []
+    third = DayFacts(altman_z=1.5, latest_accn="0000000001-26-000003")
+    _, events = run(state, [bar(3, 95.0)], third)
+    assert events == [("thesis", 1.0)]
+
+
+@pytest.mark.parametrize("policy", POLICIES)
+def test_an_8k_thesis_item_sells_under_every_policy(policy) -> None:
+    state, events = step(leg(policy), bar(1, 104.0), None, CFG, Reeval(thesis="8-K item 1.03"))
+    assert [(e.kind, e.fraction, e.detail) for e in events] == [("thesis", 1.0, "8-K item 1.03")]
+    assert state.pending == 1.0
+
+
+@pytest.mark.parametrize("policy", POLICIES)
+def test_a_down_shock_raises_only_fulls_stop_and_never_lowers_it(policy) -> None:
+    """Spec §7.1: shock stops apply under full only; the stop tightens, never loosens."""
+    state, events = step(leg(policy), bar(1, 99.0), None, CFG, Reeval(stop_at_least=96.0))
+    if policy == "full":
+        assert state.stop == pytest.approx(96.0) and [e.kind for e in events] == ["shock"]
+        state, events = step(state, bar(2, 98.0), None, CFG, Reeval(stop_at_least=90.0))
+        assert state.stop == pytest.approx(96.0) and events == []
+        _, events = step(state, bar(3, 95.5), None, CFG)
+        assert [(e.kind, e.fraction) for e in events] == [("stop", 1.0)]
+    else:
+        assert state.stop is None and events == []
+
+
+def test_an_up_shock_arms_the_trail_from_the_shock_low() -> None:
+    """Spec §7.1: the trail arms at once, trailing from the shock session's low; at the half-way
+    mark §7's breakeven floor takes over."""
+    state, events = step(leg(), bar(1, 101.0, low=97.0), None, CFG, Reeval(arm_from=97.0))
+    assert [e.kind for e in events] == ["shock"]
+    assert state.armed and state.trail_floor == 97.0 and state.stop == pytest.approx(97.0)
+    _, events = step(state, bar(2, 96.5), None, CFG)
+    assert [(e.kind, e.fraction) for e in events] == [("trail", 1.0)]
+    later, events = step(state, bar(2, 111.0, atr14=2.0), None, CFG)
+    assert events == [] and later.trail_floor is None
+    assert later.stop == pytest.approx(105.0)  # 111 - 3 x 2, above the breakeven
+
+
+def test_the_effective_only_proposal_is_noted_once_per_episode() -> None:
+    """Review M14: one tap proposal per episode, and none on the baseline track, where Python's
+    value says the same thing (its exit waits for a re-mark)."""
+    closes = [115.0, 116.0, 105.0, 115.0]
+    _, events = run(
+        leg("hold12", fv=120.0, effective=100.0),
+        [bar(i + 1, c, sma50=120.0) for i, c in enumerate(closes)],
+    )
+    assert events == [("proposal", 0.0), ("proposal", 0.0)]
+    _, events = run(
+        leg("hold12", fv=100.0), [bar(i + 1, c, sma50=120.0) for i, c in enumerate(closes)]
+    )
+    assert events == []
+
+
+def test_a_rebase_scales_every_price_level_and_no_return() -> None:
+    state, _ = run(leg(), [bar(1, 121.0, atr14=2.0), bar(2, 123.0, open=122.0, atr14=2.0)])
+    half = state.rebased(0.5)
+    assert (half.entry_price, half.fair_value, half.stop, half.highest_close) == (
+        50.0,
+        60.0,
+        pytest.approx(state.stop / 2),
+        61.5,
+    )
+    assert half.last_close == 61.5 and half.proceeds == pytest.approx(state.proceeds / 2)
+    assert (half.remaining, half.max_drawdown, half.peak_value) == (
+        state.remaining,
+        state.max_drawdown,
+        state.peak_value,
+    )
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_exits.py`
  Expected: FAIL — `ImportError: cannot import name 'Reeval' from 'src.value.exits'`.

- [x] **Step 3: The engine** — apply to `src/value/exits.py`:

```diff
diff --git a/src/value/exits.py b/src/value/exits.py
index bb68d5e..52ed1b8 100644
--- a/src/value/exits.py
+++ b/src/value/exits.py
@@ -13,7 +13,13 @@ Every exit that would send without a tap reads **Python's** fair value only (rev
 half-sale target reads the effective fair value (Python's on the baseline track; Claude's
 clamped value on Part 4's track). An exit only the effective value would fire is a ``proposal``
 event: it waits for a tap and sells nothing. Fair value is re-marked only when a new filing lands
-(a new accession). §7.1's shock stops and re-evaluations are Part 3.
+(a new accession).
+
+Part 3 (spec §7.1, ``value_rules`` v3): a session's re-evaluation reaches a leg as a ``Reeval``.
+Its 8-K thesis exit (items 1.03, 3.01, 4.02) sells under every policy; its shock stops apply under
+``full`` only, at the close: a down-shock raises the stop to the shock low - 0.5 x ATR(14) measured
+before the shock, an up-shock arms the trail from the shock low. A going-concern doubt the filing
+asserts is a thesis exit under every policy (§7).
 """
 
 from __future__ import annotations
@@ -42,6 +48,7 @@ EventKind = Literal[
     "time",
     "proposal",
     "fill",
+    "shock",
 ]
 _DONE = 1e-9
 
@@ -57,7 +64,18 @@ class DayFacts(BaseModel):
     effective_fair_value: float | None = None
     latest_accn: str | None = None
     piotroski: float | None = None
+    piotroski_missing: int = 0  # F-score components unknown (each scored 0 in ``piotroski``)
     altman_z: float | None = None
+    going_concern: bool | None = None  # the newest read periodic filing asserts a doubt
+
+
+class Reeval(BaseModel):
+    """What one session's re-evaluation (spec §7.1) does to a leg at that session's close: built
+    by ``src.value.reevaluate.plan_actions`` from Python's triggers only."""
+
+    stop_at_least: float | None = None  # full: a down-shock's floor for the stop
+    arm_from: float | None = None  # full: an up-shock arms the trail from this low
+    thesis: str | None = None  # every policy: an 8-K item that is a thesis exit on its own
 
 
 class ExitEvent(BaseModel):
@@ -83,7 +101,10 @@ class LegState(BaseModel):
     half_sold: bool = False
     above_fv_seen: bool = False  # a close at or above PYTHON's fair value (not the effective one)
     peak_proposed: bool = False  # the effective-only crossing has been noted once
-    last_close: float | None = None  # the last stepped close: the split guard's reference
+    fv_proposed: bool = False  # the effective-only thesis proposal is noted once per episode
+    seen_accn: str | None = None  # the newest accession this leg has read (the Z exit's clock)
+    trail_floor: float | None = None  # an up-shock's trail floor until the half-way mark
+    last_close: float | None = None  # the last stepped close: the rebase's reference
     rsi_hot: bool = False
     highest_close: float
     sessions: int = 0
@@ -101,6 +122,26 @@ class LegState(BaseModel):
         """Return over cost once every share is sold; None while any is held."""
         return self.proceeds / self.entry_price - 1.0 if self.closed else None
 
+    def rebased(self, ratio: float) -> LegState:
+        """Every absolute price level times *ratio* (a split or a dividend adjustment rewrote
+        the bars, spec §7.1): returns, fractions and drawdowns are unchanged."""
+
+        def times(v: float | None) -> float | None:
+            return None if v is None else v * ratio
+
+        return self.model_copy(
+            update={
+                "entry_price": self.entry_price * ratio,
+                "fair_value": times(self.fair_value),
+                "effective_fair_value": times(self.effective_fair_value),
+                "stop": times(self.stop),
+                "trail_floor": times(self.trail_floor),
+                "highest_close": self.highest_close * ratio,
+                "last_close": times(self.last_close),
+                "proceeds": self.proceeds * ratio,
+            }
+        )
+
 
 def open_leg(
     policy: Policy,
@@ -126,16 +167,22 @@ def open_leg(
         fair_value=fair_value,
         effective_fair_value=effective_fair_value,
         fv_accn=fv_accn,
+        seen_accn=fv_accn,
         stop=stop,
         highest_close=entry_price,
     )
 
 
 def step(
-    state: LegState, day: DayBar, facts: DayFacts | None, cfg: ValueExitsCfg
+    state: LegState,
+    day: DayBar,
+    facts: DayFacts | None,
+    cfg: ValueExitsCfg,
+    reeval: Reeval | None = None,
 ) -> tuple[LegState, list[ExitEvent]]:
     """Advance one leg by one session: fill yesterday's signal at today's open, then read
-    today's close. Never mutates *state*."""
+    today's close, then apply the session's re-evaluation (*reeval*, spec §7.1). Never mutates
+    *state*."""
     if state.closed:
         return state, []
     s = state.model_copy()
@@ -176,6 +223,10 @@ def step(
         events.append(ExitEvent(day=day.date, kind=kind, price=close, detail=detail))
 
     # A new filing re-marks fair value, up or down (spec §7). Price and news never do.
+    filed = facts is not None and facts.latest_accn is not None and facts.latest_accn != s.seen_accn
+    if filed:
+        assert facts is not None
+        s.seen_accn = facts.latest_accn
     remarked = False
     if (
         facts is not None
@@ -195,12 +246,23 @@ def step(
 
     # Thesis exits: every policy, Python's numbers only.
     if facts is not None:
-        if facts.piotroski is not None and facts.piotroski <= cfg.thesis_piotroski_max:
-            sell(s.remaining, "thesis", f"F-score {facts.piotroski:.0f}")
+        f_score = facts.piotroski
+        # An unknown component scores 0 in the F-score: fire only if it would still be at or
+        # under the bar with every unknown component a point (review M5).
+        if f_score is not None and f_score + facts.piotroski_missing <= cfg.thesis_piotroski_max:
+            sell(s.remaining, "thesis", f"F-score {f_score:.0f}")
             return s, events
-        if facts.altman_z is not None and facts.altman_z < cfg.thesis_altman_z_below:
+        # Altman Z carries the market cap, so it is read when a new filing lands, not every
+        # session the price moves (review M6).
+        if filed and facts.altman_z is not None and facts.altman_z < cfg.thesis_altman_z_below:
             sell(s.remaining, "thesis", f"Altman Z {facts.altman_z:.2f}")
             return s, events
+        if facts.going_concern:
+            sell(s.remaining, "thesis", "the filing asserts a going-concern doubt")
+            return s, events
+    if reeval is not None and reeval.thesis is not None:
+        sell(s.remaining, "thesis", reeval.thesis)
+        return s, events
     bar = cfg.thesis_fv_below_price_pct / 100.0
     below_trend = day.sma50 is not None and close < day.sma50
     # Only on a session that re-marked fair value from a new filing (review I5): a static value
@@ -208,8 +270,16 @@ def step(
     if remarked and below_trend and s.fair_value is not None and s.fair_value < close * bar:
         sell(s.remaining, "thesis", f"fair value {s.fair_value:.2f} below {bar:.0%} of the price")
         return s, events
-    if below_trend and s.effective_fair_value is not None and s.effective_fair_value < close * bar:
+    # The tap proposal is for what only the effective value says, once per episode (M14).
+    effective_only = (
+        below_trend
+        and s.effective_fair_value is not None
+        and s.effective_fair_value < close * bar
+        and not (s.fair_value is not None and s.fair_value < close * bar)
+    )
+    if effective_only and not s.fv_proposed:
         note("proposal", "the effective fair value alone is below 90% of the price: a tap")
+    s.fv_proposed = effective_only
 
     if s.policy == "full":
         _full(s, close, day, cfg, sell, note)
@@ -229,9 +299,24 @@ def step(
             sell(s.remaining, "catastrophe", f"close {close:.2f} <= {floor:.2f}")
         elif s.sessions >= cfg.hold12_sessions:
             sell(s.remaining, "time", f"{s.sessions} sessions")
+    if s.policy == "full" and reeval is not None and s.pending < s.remaining - _DONE:
+        _shock(s, reeval, note)
     return s, events
 
 
+def _shock(s: LegState, reeval: Reeval, note: Note) -> None:
+    """Spec §7.1, ``full`` only, at the close: a stop never loosens."""
+    if reeval.stop_at_least is not None and (s.stop is None or reeval.stop_at_least > s.stop):
+        s.stop = reeval.stop_at_least
+        note("shock", f"down-shock: stop raised to {s.stop:.2f}")
+    if reeval.arm_from is not None and not s.armed:
+        s.armed = True
+        s.trail_floor = reeval.arm_from
+        if s.stop is None or reeval.arm_from > s.stop:
+            s.stop = reeval.arm_from
+        note("shock", f"up-shock: trail armed from the shock low {reeval.arm_from:.2f}")
+
+
 def _half_at_fair_value(s: LegState, close: float, cfg: ValueExitsCfg, sell: Sell) -> None:
     target = s.effective_fair_value
     if not s.half_sold and target is not None and close >= target:
@@ -247,16 +332,17 @@ def _full(
         sell(s.remaining, kind, f"close {close:.2f} < stop {s.stop:.2f}")
         return
     fv = s.fair_value
-    if (
-        not s.armed
-        and fv is not None
+    halfway = (
+        fv is not None
         and fv > s.entry_price
         and close >= s.entry_price + cfg.arm_at_pct / 100.0 * (fv - s.entry_price)
-    ):
-        s.armed = True
+    )
+    if halfway and (not s.armed or s.trail_floor is not None):
+        if not s.armed:
+            note("arm", f"close {close:.2f} past the half-way mark to {fv:.2f}")
+        s.armed, s.trail_floor = True, None  # an up-shock's floor gives way to the breakeven
         if s.stop is None or s.stop < s.entry_price:
             s.stop = s.entry_price  # armed: never below breakeven, even when ATR is unknown (M3)
-        note("arm", f"close {close:.2f} past the half-way mark to {fv:.2f}")
     _half_at_fair_value(s, close, cfg, sell)
     # The peak signal and the 2 x ATR tightening sell without a tap, so they read Python's fair
     # value only (revision 3); a price that crossed just the effective value is one proposal.
@@ -273,7 +359,8 @@ def _full(
         return
     k = cfg.trail_atr_after_half if s.half_sold and s.above_fv_seen else cfg.trail_atr
     if day.atr14 is not None:
-        chandelier = max(s.highest_close - k * day.atr14, s.entry_price)
+        floor = s.entry_price if s.trail_floor is None else s.trail_floor
+        chandelier = max(s.highest_close - k * day.atr14, floor)
         if s.stop is None or chandelier > s.stop:
             s.stop = chandelier  # a stop is never lowered
     if day.rsi14 is not None and day.rsi14 > cfg.peak_rsi_high:
```

- [x] **Step 4: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_exits.py tests/test_value_shadow.py tests/test_value_fence.py`
  Expected: PASS (`test_value_exits.py` 43 collected). Then ruff check/format and `.venv/bin/mypy
  src/value/exits.py` — clean.

- [x] **Step 5: Commit**

  ```bash
  git add src/value/exits.py tests/test_value_exits.py
  git commit -m "feat(value): the exit engine's Part 3 rules - shocks, the 8-K and going-concern exits, M5 M6 M14"
  ```

---

### Task 5: The residual model and the triggers

**Files:** Create `src/value/residuals.py`, `src/value/reevaluate.py`, `tests/test_value_reevaluate.py`

**Interfaces:**
- Consumes: `ValueReevaluationCfg` (Task 1), `DayBar`, `FilingEvent`, `NewsVolume` (Task 3),
  `exits.Reeval` (Task 4).
- Produces: `residuals.Move(day, ret, z, drift_z, beta)`, `residuals.daily_returns(closes)`,
  `residuals.moves(name, etf, days, cfg) -> dict[date, Move]` (closes as ascending `(date, close)`
  lists); `reevaluate.Trigger(kind, severity, direction, item, detail)` with `kind` in `move, drift,
  earnings, filing, news, regime, quiet`; `reevaluate.session_triggers(*, day, after, move, filings,
  earnings, news, regime_stepped, last_reevaluation, cfg) -> list[Trigger]`;
  `regime_stepped(previous, now, cfg) -> bool`; `severity(triggers) -> "minor" | "major" | None`;
  `joins(open_severity, sessions_since_open, new, cfg) -> bool`;
  `plan_actions(triggers, bar, before, cfg) -> Reeval | None`.

The fixture the residual tests pin (computed by hand, then run): the ETF's returns repeat +1%, +1%,
−1%, −1%; the name's are 1.5 × the ETF's plus a residual of +0.5%, −0.5%, …; over whole cycles the
two are uncorrelated, so least squares gives β = 1.5 and α = 0 exactly, and the residual's sample sd
over 60 sessions is σ = 0.005 × √(60/59) = 0.0050422. A −4% day on a flat sector is
z = −0.04 / σ = −7.93 (Major, down); five days of −0.8% net of the sector is a drift of
−0.04 / (σ × √5) = −3.55 (Minor) while no single day reaches |z| = 3.

- [x] **Step 1: Write the failing tests** — create `tests/test_value_reevaluate.py`:

```python
"""Re-evaluation (value book spec §7.1, §16): the sector-ETF residual model, every trigger on a
fixture, severity and the debounce, the plan actions, and that news or earnings alone change no
level."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from src.common.config import ValueExitsCfg, ValueReevaluationCfg
from src.common.value_types import DayBar, FilingEvent, NewsVolume
from src.value import reevaluate as rv
from src.value.exits import open_leg, step
from src.value.residuals import Move, daily_returns, moves

CFG = ValueReevaluationCfg()
D0 = date(2026, 1, 1)
# The ETF's returns repeat +1%, +1%, -1%, -1%; the name's are 1.5x the ETF's plus a residual of
# +0.5%, -0.5%, ... Over whole cycles the two are uncorrelated, so least squares gives beta 1.5 and
# alpha 0 exactly, and the residual's sample sd over 60 sessions is 0.005 x sqrt(60 / 59).
SIGMA = 0.005 * math.sqrt(60 / 59)


def _series(extra_etf: list[float], extra_name: list[float]):
    etf_r = [(0.01, 0.01, -0.01, -0.01)[i % 4] for i in range(124)] + extra_etf
    noise = [(0.005, -0.005)[i % 2] for i in range(124)]
    name_r = [1.5 * e + n for e, n in zip(etf_r, noise, strict=False)] + extra_name
    days = [D0 + timedelta(days=i) for i in range(len(etf_r) + 1)]

    def closes(rets: list[float]) -> list[tuple[date, float]]:
        out, c = [(days[0], 100.0)], 100.0
        for d, r in zip(days[1:], rets, strict=True):
            c *= 1.0 + r
            out.append((d, c))
        return out

    return closes(name_r), closes(etf_r), days


def test_a_shock_day_is_measured_in_residual_standard_deviations() -> None:
    name, etf, days = _series([0.0, -0.01], [-0.04, -0.012])
    out = moves(name, etf, [days[125], days[126]], CFG)
    shock = out[days[125]]
    assert shock.beta == pytest.approx(1.5) and shock.ret == pytest.approx(-0.04)
    assert shock.z == pytest.approx(-0.04 / SIGMA)  # -7.93: Major, down
    calm = out[days[126]]  # -1.2% on a -1% sector day is +0.3% net of 1.5 x the ETF
    assert calm.z is not None and abs(calm.z) < 3.0


def test_a_slow_bleed_is_a_drift_no_single_day_flags() -> None:
    """Five sessions of -0.8% net of the sector: no day reaches |z| 3, the sum does
    (-0.04 / (sigma x sqrt 5) = -3.55), measured with the fit from before the window."""
    name, etf, days = _series([0.0] * 5, [-0.008] * 5)
    out = moves(name, etf, days[125:130], CFG)
    assert all(m.z is not None and abs(m.z) < CFG.abnormal_z for m in out.values())
    assert out[days[129]].drift_z == pytest.approx(-0.04 / (SIGMA * math.sqrt(5)))


def test_a_short_history_has_no_z_and_a_missing_etf_day_keeps_the_raw_move() -> None:
    name, etf, days = _series([0.0], [-0.04])
    short = moves(name[-50:], etf[-50:], [days[125]], CFG)[days[125]]
    assert short.z is None and short.ret == pytest.approx(-0.04)
    gap = moves(name, etf[:-1], [days[125]], CFG)[days[125]]
    assert gap.z is None and gap.ret == pytest.approx(-0.04)
    assert daily_returns([(D0, 10.0), (D0 + timedelta(days=1), 11.0)]) == {
        D0 + timedelta(days=1): pytest.approx(0.1)
    }


DAY = date(2026, 3, 10)


def _fire(**kw) -> list[tuple[str, str, str | None]]:
    base: dict = {
        "day": DAY,
        "after": DAY - timedelta(days=1),
        "move": None,
        "filings": [],
        "earnings": [],
        "news": None,
        "regime_stepped": False,
        "last_reevaluation": DAY - timedelta(days=10),
        "cfg": CFG,
    }
    base.update(kw)
    return [(t.kind, t.severity, t.direction) for t in rv.session_triggers(**base)]


def test_each_trigger_fires_on_its_own_fixture() -> None:
    assert _fire(move=Move(DAY, -0.05, -3.2, None, 1.1)) == [("move", "major", "down")]
    assert _fire(move=Move(DAY, 0.02, 2.9, None, 1.1)) == []
    assert _fire(move=Move(DAY, 0.12, None, None, None)) == [("move", "major", "up")]  # backstop
    assert _fire(move=Move(DAY, 0.09, None, None, None)) == []
    assert _fire(move=Move(DAY, -0.01, -0.5, -3.1, 1.0)) == [("drift", "minor", "down")]
    assert _fire(earnings=[DAY]) == [("earnings", "minor", None)]
    assert _fire(earnings=[DAY - timedelta(days=1)]) == []  # already checked
    assert _fire(earnings=[DAY], move=Move(DAY, -0.05, -3.2, None, 1.1)) == [
        ("move", "major", "down"),
        ("earnings", "major", None),  # Minor, Major with trigger 1
    ]
    assert _fire(news=NewsVolume(last_24h=12, daily_median_30d=3.0)) == [("news", "minor", None)]
    assert _fire(news=NewsVolume(last_24h=11, daily_median_30d=3.0)) == []  # below 4 x 3
    assert _fire(news=NewsVolume(last_24h=4, daily_median_30d=0.0)) == []  # below 5 items
    assert _fire(regime_stepped=True) == [("regime", "minor", None)]
    assert _fire(last_reevaluation=DAY - timedelta(days=90)) == [("quiet", "minor", None)]
    assert _fire(last_reevaluation=DAY - timedelta(days=89)) == []


def test_filings_by_form_and_8k_item() -> None:
    def f(form: str, items: list[str], filed: date = DAY) -> FilingEvent:
        return FilingEvent(accn="a", form=form, filed=filed, items=items)

    assert _fire(filings=[f("10-Q", [])]) == [("filing", "minor", None)]
    assert _fire(filings=[f("8-K", ["2.02", "9.01"])]) == []  # results, exhibits: no trigger
    assert _fire(filings=[f("8-K", ["5.02"])]) == [("filing", "minor", None)]
    assert _fire(filings=[f("8-K/A", ["9.01", "4.02"])]) == [("filing", "major", None)]
    assert _fire(filings=[f("10-K", [], DAY - timedelta(days=1))]) == []
    got = rv.session_triggers(
        day=DAY,
        after=DAY - timedelta(days=3),
        move=None,
        filings=[f("8-K", ["1.03"], DAY - timedelta(days=2))],
        earnings=[],
        news=None,
        regime_stepped=False,
        last_reevaluation=DAY,
        cfg=CFG,
    )
    assert [(t.item, t.detail) for t in got] == [("1.03", "8-K item 1.03 (a)")]


def test_the_regime_trigger_fires_on_a_step_into_stressed_or_crisis() -> None:
    assert rv.regime_stepped("cautious", "stressed", CFG)
    assert rv.regime_stepped("stressed", "crisis", CFG)
    assert not rv.regime_stepped("stressed", "stressed", CFG)  # no step
    assert not rv.regime_stepped("crisis", "stressed", CFG)  # easing is not a step into
    assert not rv.regime_stepped("normal", "cautious", CFG)
    assert not rv.regime_stepped(None, "crisis", CFG) and not rv.regime_stepped(
        "unknown", "crisis", CFG
    )


def test_severity_and_the_debounce() -> None:
    minor = rv.Trigger(kind="news", severity="minor")
    major = rv.Trigger(kind="move", severity="major", direction="down")
    assert rv.severity([]) is None and rv.severity([minor]) == "minor"
    assert rv.severity([minor, major]) == "major"
    assert rv.joins("minor", 3, "minor", CFG) and rv.joins("major", 1, "minor", CFG)
    assert not rv.joins("minor", 4, "minor", CFG)  # more than three sessions on
    assert not rv.joins("minor", 1, "major", CFG)  # a higher severity opens a new one
    assert not rv.joins(None, None, "minor", CFG)


def test_the_plan_actions_of_a_session() -> None:
    bar = DayBar(date=DAY, close=92.0, low=90.0)
    before = DayBar(date=DAY - timedelta(days=1), close=100.0, atr14=2.0)
    down = [rv.Trigger(kind="move", severity="major", direction="down")]
    act = rv.plan_actions(down, bar, before, CFG)
    assert act is not None and act.stop_at_least == pytest.approx(89.0)  # 90 - 0.5 x 2
    assert rv.plan_actions(down, bar, DayBar(date=DAY, close=100.0), CFG) is None  # no ATR
    up = [rv.Trigger(kind="move", severity="major", direction="up")]
    act = rv.plan_actions(up, DayBar(date=DAY, close=110.0, low=103.0), before, CFG)
    assert act is not None and act.arm_from == 103.0 and act.stop_at_least is None
    k8 = [rv.Trigger(kind="filing", severity="major", item="4.02")]
    act = rv.plan_actions(k8, bar, before, CFG)
    assert act is not None and act.thesis == "8-K item 4.02"
    minor = [
        rv.Trigger(kind="news", severity="minor"),
        rv.Trigger(kind="earnings", severity="minor"),
        rv.Trigger(kind="drift", severity="minor", direction="down"),
        rv.Trigger(kind="filing", severity="minor", item="5.02"),
    ]
    assert rv.plan_actions(minor, bar, before, CFG) is None


def test_news_or_earnings_alone_move_no_level_under_any_policy() -> None:
    """Spec §7.1 fence: trigger 5 may only open a re-evaluation; it moves no stop, no fair value
    and sends nothing."""
    triggers = [
        rv.Trigger(kind="news", severity="minor"),
        rv.Trigger(kind="earnings", severity="minor"),
    ]
    bar = DayBar(date=DAY, close=99.0, low=95.0, atr14=2.0)
    assert rv.plan_actions(triggers, bar, bar, CFG) is None
    for policy in ("full", "value", "hold12"):
        leg = open_leg(
            policy,  # type: ignore[arg-type]
            entry_date=DAY,
            entry_price=100.0,
            atr14=2.0,
            fair_value=120.0,
            effective_fair_value=120.0,
            fv_accn="a",
            cfg=ValueExitsCfg(),
        )
        after, events = step(leg, bar, None, ValueExitsCfg(), None)
        assert (after.stop, after.fair_value, after.pending, events) == (leg.stop, 120.0, 0.0, [])


def test_a_level_change_waits_for_the_close() -> None:
    """The shock session's low exists only at its close: the raised stop is tested from the next
    session, never against the close that set it."""
    leg = open_leg(
        "full",
        entry_date=DAY,
        entry_price=100.0,
        atr14=2.0,
        fair_value=120.0,
        effective_fair_value=120.0,
        fv_accn="a",
        cfg=ValueExitsCfg(),
    )
    bar = DayBar(date=DAY, close=95.0, low=94.5)
    act = rv.plan_actions(
        [rv.Trigger(kind="move", severity="major", direction="down")],
        bar,
        DayBar(date=DAY, close=100.0, atr14=0.2),
        CFG,
    )
    assert act is not None and act.stop_at_least == pytest.approx(94.4)
    after, events = step(leg, bar, None, ValueExitsCfg(), act)
    assert [e.kind for e in events] == ["shock"] and after.pending == 0.0
    _, events = step(after, DayBar(date=DAY + timedelta(days=1), close=94.3), None, ValueExitsCfg())
    assert [(e.kind, e.fraction) for e in events] == [("stop", 1.0)]
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_reevaluate.py`
  Expected: FAIL — `ModuleNotFoundError: No module named 'src.value.residuals'`.

- [x] **Step 3: The residual model** — create `src/value/residuals.py`:

```python
"""The sector-ETF residual model behind re-evaluation triggers 1 and 2 (spec §7.1). Pure: no I/O.

A name's daily return net of what its sector ETF explains: ``e = r - (alpha + beta x r_etf)``, with
alpha and beta fitted by least squares over the ``beta_sessions`` aligned returns before the day
(the day itself excluded) and the residual's standard deviation over the last ``sigma_sessions``
of them. Trigger 1 reads the day's residual in those units (``z``); trigger 2 reads the residual
summed over ``drift_sessions`` sessions, scaled by ``sigma x sqrt(n)`` from a fit that ends where
the drift window starts. Fewer than ``min_history_sessions`` aligned returns leaves both None:
the raw move is the backstop then.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from statistics import fmean, stdev

from src.common.config import ValueReevaluationCfg


@dataclass(frozen=True, slots=True)
class Move:
    day: date
    ret: float | None  # the name's close over its previous close, minus one
    z: float | None  # the day's residual in residual standard deviations
    drift_z: float | None  # the residual summed over drift_sessions, in the same units
    beta: float | None


@dataclass(frozen=True, slots=True)
class _Fit:
    alpha: float
    beta: float
    sigma: float


def daily_returns(closes: list[tuple[date, float]]) -> dict[date, float]:
    """Close over the previous close, minus one, keyed by the later date."""
    out: dict[date, float] = {}
    for (_, prev), (day, close) in zip(closes, closes[1:], strict=False):
        if prev > 0:
            out[day] = close / prev - 1.0
    return out


def _fit(xs: list[float], ys: list[float], cfg: ValueReevaluationCfg) -> _Fit | None:
    if len(xs) < cfg.min_history_sessions:
        return None
    mx, my = fmean(xs), fmean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return None
    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / var
    alpha = my - beta * mx
    tail = list(zip(xs, ys, strict=True))[-cfg.sigma_sessions :]
    sigma = stdev([y - alpha - beta * x for x, y in tail])
    return _Fit(alpha, beta, sigma) if sigma > 0 else None


def moves(
    name: list[tuple[date, float]],
    etf: list[tuple[date, float]],
    days: list[date],
    cfg: ValueReevaluationCfg,
) -> dict[date, Move]:
    """Each of *days*' move for a name (ascending ``(date, close)`` lists, the ETF's likewise).
    A day the ETF has no bar for keeps its raw return with no z."""
    rn, re = daily_returns(name), daily_returns(etf)
    aligned = sorted(d for d in rn if d in re)
    index = {d: i for i, d in enumerate(aligned)}

    def fit_before(i: int) -> _Fit | None:
        window = aligned[max(0, i - cfg.beta_sessions) : i]
        return _fit([re[d] for d in window], [rn[d] for d in window], cfg)

    def resid(f: _Fit, d: date) -> float:
        return rn[d] - f.alpha - f.beta * re[d]

    out: dict[date, Move] = {}
    for day in days:
        i = index.get(day)
        if i is None:
            out[day] = Move(day, rn.get(day), None, None, None)
            continue
        f = fit_before(i)
        z = None if f is None else resid(f, day) / f.sigma
        start = i - cfg.drift_sessions + 1
        drift = None
        if start >= 0:
            g = fit_before(start)
            if g is not None:
                total = sum(resid(g, d) for d in aligned[start : i + 1])
                drift = total / (g.sigma * math.sqrt(cfg.drift_sessions))
        out[day] = Move(day, rn[day], z, drift, None if f is None else f.beta)
    return out
```

- [x] **Step 4: The triggers** — create `src/value/reevaluate.py`:

```python
"""Re-evaluation (spec §7.1): which triggers fire on a session, how severe the re-evaluation is,
whether it joins the open one, and what it does to the plan. Pure: no I/O. Python decides all of
it; Claude decides none (Part 4's review only ever reads the record).

Triggers 1-5, 7 and 8 are here. Trigger 6 (a Claude kill-trigger within 10% of firing) needs
Claude's kill-triggers and arrives with Part 4. Trigger 5 (news volume) and the earnings dates
arrive as plain data; on their own they only open a re-evaluation: no stop and no exit reads them.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from src.common.config import ValueReevaluationCfg
from src.common.value_types import DayBar, FilingEvent, NewsVolume
from src.value.exits import Reeval
from src.value.residuals import Move

Severity = Literal["minor", "major"]
TriggerKind = Literal["move", "drift", "earnings", "filing", "news", "regime", "quiet"]
PERIODIC = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
EIGHT_K = ("8-K", "8-K/A")
_RANK: dict[str, int] = {"minor": 1, "major": 2}


class Trigger(BaseModel):
    kind: TriggerKind
    severity: Severity
    direction: Literal["up", "down"] | None = None
    item: str | None = None  # the 8-K item a filing trigger fired on
    detail: str = ""


def session_triggers(
    *,
    day: date,
    after: date,
    move: Move | None,
    filings: list[FilingEvent],
    earnings: list[date],
    news: NewsVolume | None,
    regime_stepped: bool,
    last_reevaluation: date,
    cfg: ValueReevaluationCfg,
) -> list[Trigger]:
    """Every trigger that fires on *day* for one position. *after* is the last session already
    checked (a filing or report dated after it and on or before *day* is new);
    *last_reevaluation* is the last re-evaluation's session, or the entry date."""
    out: list[Trigger] = []
    major_move = False
    if move is not None and move.z is not None:
        if abs(move.z) >= cfg.abnormal_z:
            major_move = True
            out.append(
                Trigger(
                    kind="move",
                    severity="major",
                    direction="up" if move.z > 0 else "down",
                    detail=f"residual z {move.z:+.2f} vs the sector ETF (beta {move.beta:.2f})",
                )
            )
    elif move is not None and move.ret is not None and abs(move.ret) * 100 >= cfg.raw_move_pct:
        major_move = True  # the backstop: the history is too short for a residual
        out.append(
            Trigger(
                kind="move",
                severity="major",
                direction="up" if move.ret > 0 else "down",
                detail=f"raw move {move.ret:+.1%} (history too short for a residual)",
            )
        )
    if move is not None and move.drift_z is not None and abs(move.drift_z) >= cfg.drift_z:
        out.append(
            Trigger(
                kind="drift",
                severity="minor",
                direction="up" if move.drift_z > 0 else "down",
                detail=f"{cfg.drift_sessions}-session residual z {move.drift_z:+.2f}",
            )
        )
    for report in earnings:
        if after < report <= day:
            out.append(
                Trigger(
                    kind="earnings",
                    severity="major" if major_move else "minor",
                    detail=f"earnings reported {report}",
                )
            )
            break
    for f in filings:
        if not after < f.filed <= day:
            continue
        if f.form in PERIODIC:
            out.append(Trigger(kind="filing", severity="minor", detail=f"{f.form} {f.accn}"))
        elif f.form in EIGHT_K:
            major = [i for i in f.items if i in cfg.major_8k_items]
            minor = [i for i in f.items if i in cfg.minor_8k_items]
            if major:
                out.append(
                    Trigger(
                        kind="filing",
                        severity="major",
                        item=major[0],
                        detail=f"8-K item {major[0]} ({f.accn})",
                    )
                )
            elif minor:
                out.append(
                    Trigger(
                        kind="filing",
                        severity="minor",
                        item=minor[0],
                        detail=f"8-K item {minor[0]} ({f.accn})",
                    )
                )
    if (
        news is not None
        and news.last_24h >= cfg.news_min_items
        and news.last_24h >= cfg.news_multiple * news.daily_median_30d
    ):
        out.append(
            Trigger(
                kind="news",
                severity="minor",
                detail=f"{news.last_24h} items in 24h vs a daily median of {news.daily_median_30d:g}",
            )
        )
    if regime_stepped:
        out.append(Trigger(kind="regime", severity="minor", detail="the market regime stepped"))
    if (day - last_reevaluation).days >= cfg.quiet_days:
        out.append(
            Trigger(
                kind="quiet",
                severity="minor",
                detail=f"no re-evaluation since {last_reevaluation}",
            )
        )
    return out


_REGIME_ORDER = ("normal", "cautious", "stressed", "crisis")


def regime_stepped(previous: str | None, now: str, cfg: ValueReevaluationCfg) -> bool:
    """Trigger 7: the market regime stepped *into* one of ``regime_states`` (stressed to crisis
    included) since the previous night. An unknown previous regime is never a step."""
    states = {str(r) for r in cfg.regime_states}
    if previous is None or now not in states or previous not in _REGIME_ORDER:
        return False
    return _REGIME_ORDER.index(now) > _REGIME_ORDER.index(previous)


def severity(triggers: list[Trigger]) -> Severity | None:
    """The re-evaluation's severity: its most severe trigger's; None when nothing fired."""
    if not triggers:
        return None
    return "major" if any(t.severity == "major" for t in triggers) else "minor"


def joins(
    open_severity: Severity | None,
    sessions_since_open: int | None,
    new: Severity,
    cfg: ValueReevaluationCfg,
) -> bool:
    """One re-evaluation is open per position at a time: a trigger within ``debounce_sessions``
    of the open one joins it, unless its severity is higher (spec §7.1)."""
    if open_severity is None or sessions_since_open is None:
        return False
    return sessions_since_open <= cfg.debounce_sessions and _RANK[new] <= _RANK[open_severity]


def plan_actions(
    triggers: list[Trigger],
    bar: DayBar,
    before: DayBar | None,
    cfg: ValueReevaluationCfg,
) -> Reeval | None:
    """What the session's triggers do to the plan at its close (spec §7.1, "What a
    re-evaluation does"). A Major move is a shock: down, the stop rises to at least the shock
    session's low - ``down_shock_atr`` x ATR(14) measured before the shock (no ATR, no shock
    stop: unknown is never zero); up, the trail arms from the shock low. A Major 8-K item is a
    thesis exit. Every other trigger changes nothing but the record. None when nothing changes."""
    shock = next((t for t in triggers if t.kind == "move" and t.severity == "major"), None)
    thesis = next(
        (t for t in triggers if t.kind == "filing" and t.severity == "major" and t.item), None
    )
    low = bar.low if bar.low is not None else bar.close
    atr = before.atr14 if before is not None else None
    stop = None
    arm = None
    if shock is not None and shock.direction == "down" and atr is not None:
        stop = low - cfg.down_shock_atr * atr
    if shock is not None and shock.direction == "up":
        arm = low
    if stop is None and arm is None and thesis is None:
        return None
    return Reeval(
        stop_at_least=stop,
        arm_from=arm,
        thesis=None if thesis is None else f"8-K item {thesis.item}",
    )
```

- [x] **Step 5: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_reevaluate.py tests/test_value_fence.py`
  Expected: PASS (10 + the fence). Then ruff check/format and `.venv/bin/mypy src/value/residuals.py
  src/value/reevaluate.py` — clean. (Task 8 adds both modules to the fence's pure list.)

- [x] **Step 6: Commit**

  ```bash
  git add src/value/residuals.py src/value/reevaluate.py tests/test_value_reevaluate.py
  git commit -m "feat(value): the sector-ETF residual model and the re-evaluation triggers"
  ```

---

### Task 6: The store — `value_reevaluations` and the plan column

**Files:** Modify `src/value/store.py`, `tests/test_value_store.py` (append)

**Interfaces:**
- Produces: `ValueReevaluationRow` (`value_reevaluations`: `shadow_id`, `symbol`, `list_name`,
  `session`, `last_session`, `severity`, `triggers_json`, `plan_before_json`, `plan_after_json`,
  `verdict_at_entry`, `verdict_now`, `review_state` (Part 4), `ruleset_version`, `ruleset_hash`,
  `created_at`); `ValueShadowLegRow.plan` and `ValueShadowEventRow.plan` (`main` | `original`,
  default `main`); `init_value_db()` adds the two columns to an existing database.

- [ ] **Step 1: Write the failing test** — apply to `tests/test_value_store.py`:

```diff
diff --git a/tests/test_value_store.py b/tests/test_value_store.py
index 841e6d7..cfce7ad 100644
--- a/tests/test_value_store.py
+++ b/tests/test_value_store.py
@@ -132,3 +132,40 @@ def test_record_run_adds_one_value_runs_row(value_db) -> None:
         row = s.query(ValueRunRow).one()
         assert (row.kind, row.names, row.rs_cutoff_6m) == ("dry_run", 3, -0.02)
         assert row.as_of == date(2026, 10, 29)
+
+
+def test_init_adds_the_plan_columns_to_a_part_2_database(tmp_path, monkeypatch) -> None:
+    """Part 3 adds ``plan`` to two tables a live value.db already has: create_all never alters
+    a table, so init_value_db adds the column, and a Part 2 row reads as the main plan."""
+    from sqlalchemy import create_engine, select, text
+
+    from src.value.store import ValueReevaluationRow, ValueShadowEventRow, ValueShadowLegRow
+
+    path = tmp_path / "value.db"
+    engine = create_engine(f"sqlite:///{path.as_posix()}")
+    with engine.begin() as c:
+        c.execute(
+            text(
+                "CREATE TABLE value_shadow_legs (id INTEGER PRIMARY KEY, shadow_id INTEGER, "
+                "policy VARCHAR(8), state_json TEXT, last_step DATE, closed BOOLEAN, "
+                "exit_date DATE, ret_exit FLOAT, spy_ret_exit FLOAT, max_drawdown FLOAT, "
+                "sessions INTEGER, sells INTEGER)"
+            )
+        )
+        c.execute(
+            text(
+                "INSERT INTO value_shadow_legs (id, shadow_id, policy, state_json, closed, "
+                "sessions, sells) VALUES (1, 7, 'value', '{}', 0, 0, 0)"
+            )
+        )
+    engine.dispose()
+    monkeypatch.setattr(store, "_resolve_url", lambda: f"sqlite:///{path.as_posix()}")
+    store.reset_engine()
+    init_value_db()
+    init_value_db()  # idempotent
+    with value_session() as s:
+        leg = s.get(ValueShadowLegRow, 1)
+        assert leg is not None and leg.plan == "main"
+        assert s.scalars(select(ValueReevaluationRow)).first() is None
+        assert s.scalars(select(ValueShadowEventRow)).first() is None
+    store.reset_engine()
```

- [ ] **Step 2: Run it to see it fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_store.py`
  Expected: FAIL — `ImportError: cannot import name 'ValueReevaluationRow'`.

- [ ] **Step 3: The tables** — apply to `src/value/store.py`:

```diff
diff --git a/src/value/store.py b/src/value/store.py
index 6556e50..3edfe46 100644
--- a/src/value/store.py
+++ b/src/value/store.py
@@ -18,6 +18,13 @@ Part 2 tables (the shadow record, spec §6.8, §7, §12):
 - ``value_shadow_events`` - every exit event and fill, append-only;
 - ``value_ranked`` - the ranked monthly record: top tenth, bottom tenth and the whole universe
   per list, each held to the next formation.
+
+Part 3 (spec §7.1):
+- ``value_reevaluations`` - one row per re-evaluation of a shadow entry: the triggers, the
+  severity, the plan before and after the session's close;
+- ``value_shadow_legs.plan`` / ``value_shadow_events.plan`` - ``main`` (the re-evaluated plan) or
+  ``original`` (the twin carried untouched from the first trigger on); added to an existing
+  value.db by ``init_value_db``.
 """
 
 from __future__ import annotations
@@ -38,6 +45,8 @@ from sqlalchemy import (
     Text,
     create_engine,
     event,
+    inspect,
+    text,
 )
 from sqlalchemy.engine import Engine
 from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
@@ -165,6 +174,7 @@ class ValueShadowLegRow(ValueBase):
     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
     shadow_id: Mapped[int] = mapped_column(Integer, index=True)
     policy: Mapped[str] = mapped_column(String(8))  # full | value | hold12
+    plan: Mapped[str] = mapped_column(String(8), default="main")  # main | original (Part 3)
     state_json: Mapped[str] = mapped_column(Text)  # src.value.exits.LegState
     last_step: Mapped[date | None] = mapped_column(Date, nullable=True)
     closed: Mapped[bool] = mapped_column(Boolean, default=False)
@@ -183,7 +193,8 @@ class ValueShadowEventRow(ValueBase):
 
     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
     shadow_id: Mapped[int] = mapped_column(Integer, index=True)
-    policy: Mapped[str] = mapped_column(String(8))
+    policy: Mapped[str] = mapped_column(String(8))  # full | value | hold12 | all (a rebase)
+    plan: Mapped[str] = mapped_column(String(8), default="main")  # main | original (Part 3)
     day: Mapped[date] = mapped_column(Date)
     kind: Mapped[str] = mapped_column(String(16))
     price: Mapped[float | None] = mapped_column(Float, nullable=True)
@@ -212,9 +223,41 @@ class ValueRankedRow(ValueBase):
     missing: Mapped[int] = mapped_column(Integer, default=0)  # members without a bar at an end
 
 
+class ValueReevaluationRow(ValueBase):
+    """One re-evaluation (spec §7.1) of a shadow entry. A trigger within ``debounce_sessions``
+    that is not more severe joins the open row (``last_session``, ``triggers_json``) instead of
+    opening a new one. ``review_state`` is Claude's, for held names, from Part 4 on."""
+
+    __tablename__ = "value_reevaluations"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    shadow_id: Mapped[int] = mapped_column(Integer, index=True)
+    symbol: Mapped[str] = mapped_column(String(16))
+    list_name: Mapped[str] = mapped_column(String(16))
+    session: Mapped[date] = mapped_column(Date)  # the session it opened on
+    last_session: Mapped[date] = mapped_column(Date)  # the newest session a trigger joined
+    severity: Mapped[str] = mapped_column(String(8))  # minor | major
+    triggers_json: Mapped[str] = mapped_column(Text)  # [{day, kind, severity, ...}]
+    plan_before_json: Mapped[str] = mapped_column(Text)  # {policy: {stop, armed, ...}}
+    plan_after_json: Mapped[str] = mapped_column(Text)
+    verdict_at_entry: Mapped[str] = mapped_column(String(16))
+    verdict_now: Mapped[str | None] = mapped_column(String(16), nullable=True)
+    review_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
+    ruleset_version: Mapped[str] = mapped_column(String(32))
+    ruleset_hash: Mapped[str] = mapped_column(String(12))
+    created_at: Mapped[datetime] = mapped_column(DateTime)
+
+
 _engine: Engine | None = None
 _SessionLocal: sessionmaker[Session] | None = None
 
+# Columns added after a table's first release: create_all never ALTERs an existing table
+# (the src/spreads/store.py pattern).
+_ADDED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
+    "value_shadow_legs": (("plan", "VARCHAR(8) NOT NULL DEFAULT 'main'"),),
+    "value_shadow_events": (("plan", "VARCHAR(8) NOT NULL DEFAULT 'main'"),),
+}
+
 
 def _resolve_url() -> str:
     """Absolute sqlite URL for the value database. Patched in tests."""
@@ -246,8 +289,22 @@ def reset_engine() -> None:
     _engine, _SessionLocal = None, None
 
 
+def _add_missing_columns(engine: Engine) -> None:
+    insp = inspect(engine)
+    for table, cols in _ADDED_COLUMNS.items():
+        if not insp.has_table(table):
+            continue
+        have = {c["name"] for c in insp.get_columns(table)}
+        for name, ddl in cols:
+            if name not in have:
+                with engine.begin() as conn:
+                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
+
+
 def init_value_db() -> None:
-    ValueBase.metadata.create_all(get_value_engine())
+    engine = get_value_engine()
+    ValueBase.metadata.create_all(engine)
+    _add_missing_columns(engine)
 
 
 @contextmanager
```

- [ ] **Step 4: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_store.py tests/test_value_shadow.py tests/test_value_report.py tests/test_value_fence.py`
  Expected: PASS (`test_value_store.py` 8). Then ruff check/format and `.venv/bin/mypy
  src/value/store.py` — clean.

- [ ] **Step 5: Commit, then the section's Progress-log commit**

  ```bash
  git add src/value/store.py tests/test_value_store.py
  git commit -m "feat(value): value_reevaluations and the plan column, migrated on a live value.db"
  ```

  Then the **Section B exit** full gate, Task 6's row, and
  `git commit -m "docs(plan): value book Part 3 Progress log - Section B"` (the plan alone).

---

## Section C — The shadow record's re-evaluations, the process, the report (Tasks 7–9) · model: sonnet · effort: high

`shadow.py` replaces Part 2's freeze with the mechanical rebase and steps each READY entry session
by session through §7.1: triggers, the record, the original twin, the plan actions. The service and
the feed hand in earnings dates, news volume and the regime step; the fences cover the new modules;
the report sets each policy's re-evaluated plan against the original one.

**Spec to read:** §6.8 (first paragraph), §7.1 (all, especially "Fence" and "Measured like
everything else"), §12 (the first bullets), §16 (the re-evaluation bullet).

**Files the subagent reads:** this section; `src/value/shadow.py` (all: it is replaced),
`tests/test_value_shadow.py`, `src/value/exits.py`, `src/value/residuals.py`,
`src/value/reevaluate.py`, `src/value/store.py`, `src/value/service.py`, `scripts/value_feed.py`,
`scripts/run_value.py`, `tests/test_value_feed.py`, `tests/test_value_service.py`,
`tests/test_value_fence.py`, `src/news/store/queries.py` (`earnings_between`,
`ticker_sentiment_rows` — read, never edited), `src/value/report.py`, `scripts/value_report.py`,
`tests/test_value_report.py`.

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **C1. Section B landed.** Tasks 4–6 ticked; record the commit count (8 if nothing else).
- [ ] **C2. Green, from the worktree root.** pytest = baseline + 39, `ruff check .`, `mypy src`.
- [ ] **C3. The code Section C edits is where this plan says.** Each prints the line shown:

  ```bash
  grep -n "^def step_legs($" src/value/shadow.py                                            # 281:
  grep -n "^def process($" src/value/shadow.py                                              # 467:
  grep -n "^def test_a_split_freezes_the_entry_instead_of_firing_its_stop(value_db) -> None:$" tests/test_value_shadow.py   # 211:
  grep -n "        assert shadow.mark_horizons(s, market) == (2, 0)" tests/test_value_shadow.py   # 169:
  grep -n "^def shadow_names(vs: Session) -> dict\[str, str\]:$" src/value/service.py      # 109:
  grep -n "^            record = shadow.process($" src/value/service.py                      # 251:
  grep -n "^class NightRetry:$" scripts/value_feed.py                                       # 44:
  grep -n "^from scripts.value_feed import FactsCache, NightRetry, earnings_dates$" scripts/run_value.py   # 20:
  grep -n '^    "report",$' tests/test_value_fence.py                                        # 34:
  grep -n '^        "ValueRankedRow(",$' tests/test_value_fence.py                           # 196:
  grep -n "^def ranked_section(rows: list\[RankedView\]) -> list\[str\]:$" src/value/report.py   # 213:
  grep -n "^from src.value.report import HORIZONS, EntryView, EventView, LegView, RankedView, render$" scripts/value_report.py   # 20:
  ```

- [ ] **C4. The pieces Section C builds on exist.** Each prints at least one line:

  ```bash
  grep -n "^def session_triggers\|^def plan_actions\|^def regime_stepped" src/value/reevaluate.py
  grep -n "^def moves" src/value/residuals.py
  grep -n "^class Reeval\|    def rebased" src/value/exits.py
  grep -n "^class ValueReevaluationRow\|^_ADDED_COLUMNS" src/value/store.py
  grep -n "^def filings_between\|^def going_concern_flags" src/common/value_inputs.py
  ```

**Section exit:** three more task commits plus the section's `docs(plan)` commit; full gate green
with pytest = baseline + 52 (39 + 7 + 4 + 2); `.venv/bin/python -m py_compile scripts/run_value.py
scripts/value_feed.py scripts/value_report.py` silent; protected-file diff empty. Record the commit
count.

---

### Task 7: The shadow record — rebase, re-evaluations, the original twin

**Files:** Replace `src/value/shadow.py` (rulings 12–17 and P2-M1, M7, M8); modify
`tests/test_value_shadow.py`

**Interfaces:**
- Consumes: Tasks 3–6.
- Produces: `shadow.HELD = ("pending", "open", "rebase_needed")`, `MAIN`, `ORIGINAL`,
  `REBASE_TOLERANCE = 1e-4`; `ReevalContext(filings, going_concern, earnings, news,
  regime_stepped, etf_for)`; `rebase(vs, market, day) -> tuple[int, int]` (rebased, still frozen);
  `step_legs(vs, market, cards, cfg, *, as_of=None, context=None, now=None) -> tuple[int, int]`
  (events, re-evaluations opened); `mark_horizons(vs, market) -> int`;
  `day_facts(card, list_name, going_concern=None)`; `process(..., earnings=None, news=None,
  regime_stepped=False)`; `ShadowSummary.rebased`, `.reevaluations` (and `.rebase_needed` now
  counts entries still frozen).

The night's order (`process`): fill yesterday's signals → **rebase** → step every open READY
entry's legs session by session (for each session: tonight's facts only on the session dated as_of;
the main legs' triggers → a re-evaluation row, joined or new → the twins at the first one → the
plan actions on the main legs, none on the twins) → mark the horizons → close what is finished →
open tonight's signals → the ranked record.

- [ ] **Step 1: Write the failing tests** — apply to `tests/test_value_shadow.py` (the two split
  tests become rebase tests; `mark_horizons` returns a count; seven tests are new):

```diff
diff --git a/tests/test_value_shadow.py b/tests/test_value_shadow.py
index 1f3ec2e..ee3f273 100644
--- a/tests/test_value_shadow.py
+++ b/tests/test_value_shadow.py
@@ -1,6 +1,6 @@
-"""The shadow record (value book spec §6.8, §7, §12): READY entries at the next open, control
-groups, re-entry, the three policies' legs, fixed-horizon returns against SPY, the split guard
-and the ranked monthly record."""
+"""The shadow record (value book spec §6.8, §7, §7.1, §12): READY entries at the next open,
+control groups, re-entry, the three policies' legs, fixed-horizon returns against SPY, the
+mechanical rebase, re-evaluations with the original-plan twin, and the ranked monthly record."""
 
 from __future__ import annotations
 
@@ -14,12 +14,14 @@ from sqlalchemy.orm import Session
 
 import src.value.store as store
 from src.common.config import get_config
-from src.common.value_types import DayBar
+from src.common.value_types import DayBar, FilingEvent, NewsVolume
 from src.research.store.models import Base, DailyBarRow
 from src.value import shadow
+from src.value.exits import LegState
 from src.value.scorecard import build_scorecard
 from src.value.store import (
     ValueRankedRow,
+    ValueReevaluationRow,
     ValueShadowEventRow,
     ValueShadowLegRow,
     ValueShadowRow,
@@ -166,7 +168,7 @@ def test_horizons_mark_h_sessions_after_the_entry_session_against_spy(value_db)
     with value_session() as s:
         shadow.fill_pending(s, market, CFG)  # entry: SESSIONS[1] at 31.00, SPY 500.00
     with value_session() as s:
-        assert shadow.mark_horizons(s, market) == (2, 0)  # 21 for both lists; 63 not yet
+        assert shadow.mark_horizons(s, market) == 2  # 21 for both lists; 63 not yet
     with value_session() as s:
         row = s.scalars(select(ValueShadowRow)).first()
         assert row.ret_21 == pytest.approx(33.0 / 31.0 - 1.0)  # SESSIONS[22]'s close
@@ -180,9 +182,9 @@ def test_a_horizon_waits_for_the_names_bar_then_settles_for_the_last_close(value
     with value_session() as s:
         shadow.fill_pending(s, {"STDY": stdy, "SPY": bars([500.0] * 2)}, CFG)
     with value_session() as s:  # h21 is SESSIONS[22]; only 2 SPY sessions after it so far
-        assert shadow.mark_horizons(s, {"STDY": stdy, "SPY": bars([500.0] * 25)}) == (0, 0)
+        assert shadow.mark_horizons(s, {"STDY": stdy, "SPY": bars([500.0] * 25)}) == 0
     with value_session() as s:  # 5 SPY sessions after it: settle for the last close
-        assert shadow.mark_horizons(s, {"STDY": stdy, "SPY": bars([500.0] * 28)}) == (2, 0)
+        assert shadow.mark_horizons(s, {"STDY": stdy, "SPY": bars([500.0] * 28)}) == 2
     with value_session() as s:
         row = s.scalars(select(ValueShadowRow)).first()
         assert row.ret_21 == pytest.approx(29.0 / 31.0 - 1.0)
@@ -208,48 +210,196 @@ def test_an_entry_closes_once_every_horizon_is_marked_and_every_leg_has_exited(v
     assert {r[3] for r in _rows()} == {"closed"}
 
 
-def test_a_split_freezes_the_entry_instead_of_firing_its_stop(value_db) -> None:
-    _open([ready()])
+def _legs(plan: str = "main") -> dict[tuple[str, str], LegState]:
+    with value_session() as s:
+        rows = {r.id: r.list_name for r in s.scalars(select(ValueShadowRow))}
+        return {
+            (rows[g.shadow_id], g.policy): LegState.model_validate_json(g.state_json)
+            for g in s.scalars(select(ValueShadowLegRow).where(ValueShadowLegRow.plan == plan))
+        }
+
+
+def test_a_split_rebases_the_entry_instead_of_firing_its_stop(value_db) -> None:
+    """Spec §7.1: a corporate action is not a trigger; the levels are rebased mechanically."""
+    _open([ready()], atr={"STDY": 0.6})  # full's stop: max(31 - 1.8, 31 x 0.85) = 29.2
     with value_session() as s:
         shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
     split = {"STDY": bars([15.0, 15.5, 15.4]), "SPY": bars([500.0] * 3)}  # 2-for-1 rewrite
     with value_session() as s:
-        assert shadow.step_legs(s, split, {}, CFG) == (0, 2)
-    assert {r[3] for r in _rows()} == {"rebase_needed"}
+        assert shadow.rebase(s, split, SESSIONS[2]) == (2, 0)
+    with value_session() as s:
+        assert shadow.step_legs(s, split, {}, CFG) == (0, 0)  # 15.40 is above the halved 14.60
+    assert {r[3] for r in _rows()} == {"open"}
+    legs = _legs()
+    assert legs[("deep_value", "full")].stop == pytest.approx(14.6)
+    assert legs[("deep_value", "value")].entry_price == pytest.approx(15.5)
     with value_session() as s:
-        assert s.scalars(select(ValueShadowEventRow)).first() is None
+        row = s.scalars(select(ValueShadowRow)).first()
+        assert row.entry_price == pytest.approx(15.5) and row.atr14 == pytest.approx(0.3)
+        kinds = [(e.kind, e.policy) for e in s.scalars(select(ValueShadowEventRow))]
+    assert kinds == [("rebase", "all"), ("rebase", "all")]
+    with value_session() as s:  # the same bars again: nothing more to rebase
+        assert shadow.rebase(s, split, SESSIONS[2]) == (0, 0)
 
 
-def test_a_split_after_the_entry_bar_left_the_providers_window_still_freezes(value_db) -> None:
-    """Review I3: the provider serves ~2 years, so a long-held entry's bar is no longer in the
-    window to compare. The guard compares the bar now on the leg's last stepped session with the
-    close the leg last saw there."""
+def test_a_rewrite_after_the_entry_bar_left_the_window_still_rebases(value_db) -> None:
+    """The provider serves ~2 years, so a long-held entry's own bar leaves the window: the
+    reference is the bar on the legs' last stepped session against the close they saw there.
+    A dividend adjustment (x 0.99) is rebased the same way as a split."""
     _open([ready()])
     with value_session() as s:
         shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
     market = {"STDY": bars([30.0, 31.0, 32.0, 33.0]), "SPY": bars([500.0] * 4)}
     with value_session() as s:
         shadow.step_legs(s, market, {}, CFG)
-    with value_session() as s:
-        legs = list(s.scalars(select(ValueShadowLegRow)))
-        assert all(json.loads(leg.state_json)["last_close"] == 33.0 for leg in legs)
-    # A 2-for-1 split: every bar halves, and the window no longer reaches back to the entry bar.
+    assert all(leg.last_close == 33.0 for leg in _legs().values())
     split = {"STDY": bars([16.0, 16.5, 16.6], start=2), "SPY": bars([500.0] * 3, start=2)}
     with value_session() as s:
-        assert shadow.step_legs(s, split, {}, CFG) == (0, 2)
-    assert {r[3] for r in _rows()} == {"rebase_needed"}
+        assert shadow.rebase(s, split, SESSIONS[4]) == (2, 0)
+    assert _legs()[("deep_value", "value")].entry_price == pytest.approx(15.5)
     with value_session() as s:
-        assert s.scalars(select(ValueShadowEventRow)).first() is None
-    # An ordinary move on that bar does not freeze.
-    _open([ready("OTHR", 30.0)])
+        shadow.step_legs(s, split, {}, CFG)  # the legs now last saw 16.60 on SESSIONS[4]
+    # An ex-dividend bar arrives on SESSIONS[5] and the provider adjusts every bar before it.
+    adjusted = {"STDY": bars([16.6 * 0.99, 16.4], start=4), "SPY": bars([500.0] * 2, start=4)}
     with value_session() as s:
-        shadow.fill_pending(s, {"OTHR": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
-    calm = {"OTHR": bars([30.0, 31.0, 32.0, 33.0]), "SPY": bars([500.0] * 4)}
+        assert shadow.rebase(s, adjusted, SESSIONS[5]) == (2, 0)
+    assert _legs()[("deep_value", "value")].entry_price == pytest.approx(15.5 * 0.99)
+
+
+def test_a_part_2_frozen_entry_is_rebased_and_reopened(value_db) -> None:
+    """Part 2 froze an entry as rebase_needed (ruling 16); Part 3 un-freezes it. One with no
+    bar left to measure against stays frozen and says so in the count."""
+    _open([ready()])
     with value_session() as s:
-        shadow.step_legs(s, calm, {}, CFG)
-    later = {"OTHR": bars([31.0, 32.0, 36.0, 36.5], start=1), "SPY": bars([500.0] * 4, start=1)}
+        shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
+        for row in s.scalars(select(ValueShadowRow)):
+            row.status = "rebase_needed"
     with value_session() as s:
-        assert shadow.step_legs(s, later, {}, CFG)[1] == 0
+        assert shadow.rebase(s, {"STDY": bars([10.0], start=5)}, SESSIONS[5]) == (0, 2)
+    with value_session() as s:
+        assert shadow.rebase(s, {"STDY": bars([15.0, 15.5])}, SESSIONS[5]) == (2, 0)
+    assert {r[3] for r in _rows()} == {"open"}
+
+
+def _reevaluations() -> list[tuple[str, str, date, date, list[str]]]:
+    with value_session() as s:
+        return [
+            (
+                r.list_name,
+                r.severity,
+                r.session,
+                r.last_session,
+                [t["kind"] for t in json.loads(r.triggers_json)],
+            )
+            for r in s.scalars(select(ValueReevaluationRow).order_by(ValueReevaluationRow.id))
+        ]
+
+
+def _entered(atr: float = 2.0) -> None:
+    _open([ready()], atr={"STDY": atr})  # full's stop: max(31 - 3 x 2, 31 x 0.85) = 26.35
+    with value_session() as s:
+        shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
+
+
+def test_a_down_shock_raises_fulls_main_stop_and_starts_the_original_twin(value_db) -> None:
+    """Spec §7.1: a Major down-move (here the raw 10% backstop: the history is short) opens a
+    re-evaluation; under full the stop rises to the shock low - 0.5 x the ATR before the shock
+    (27.00 - 0.5 x 0.60 = 26.70); the original plan keeps 26.35. The next close, 26.60, sells
+    the re-evaluated full leg only."""
+    _entered()
+    stdy = [
+        DayBar(date=SESSIONS[0], close=30.0, open=30.0),
+        DayBar(date=SESSIONS[1], close=31.0, open=31.0, atr14=0.6),
+        DayBar(date=SESSIONS[2], close=27.2, open=30.0, low=27.0, atr14=1.0),
+        DayBar(date=SESSIONS[3], close=26.6, open=27.0, low=26.5, atr14=1.0),
+    ]
+    market = {"STDY": stdy, "SPY": bars([500.0] * 4)}
+    ctx = shadow.ReevalContext(etf_for={"STDY": "XLK"})
+    with value_session() as s:
+        events, opened = shadow.step_legs(s, market, {}, CFG, as_of=SESSIONS[3], context=ctx)
+    assert opened == 2  # one per entry: the deep-value and quality-growth READY entries
+    assert _reevaluations() == [
+        ("deep_value", "major", SESSIONS[2], SESSIONS[2], ["move"]),
+        ("quality_growth", "major", SESSIONS[2], SESSIONS[2], ["move"]),
+    ]
+    main, original = _legs("main"), _legs("original")
+    assert main[("deep_value", "full")].pending == 1.0  # sold on the 26.60 close
+    assert original[("deep_value", "full")].stop == pytest.approx(26.35)
+    assert original[("deep_value", "full")].pending == 0.0
+    assert main[("deep_value", "value")].pending == 0.0  # value: no tight stop to move
+    with value_session() as s:
+        r = s.scalars(select(ValueReevaluationRow)).first()
+        before, after = json.loads(r.plan_before_json), json.loads(r.plan_after_json)
+    assert before["full"]["stop"] == pytest.approx(26.35)
+    assert after["full"]["stop"] == pytest.approx(26.7)
+    assert after["value"] == before["value"]
+
+
+def test_an_8k_bankruptcy_item_exits_every_main_leg_and_no_original_one(value_db) -> None:
+    """Spec §7.1: an 8-K item 1.03 is a thesis exit on its own, under every policy. The original
+    twins hold: that is the comparison the report reads. The live leg's exit frees the key."""
+    _entered()
+    market = {"STDY": bars([30.0, 31.0, 31.5, 31.2]), "SPY": bars([500.0] * 4)}
+    filing = FilingEvent(accn="0000000001-26-000009", form="8-K", filed=SESSIONS[2], items=["1.03"])
+    ctx = shadow.ReevalContext(filings={"STDY": [filing]})
+    with value_session() as s:
+        shadow.step_legs(s, market, {}, CFG, as_of=SESSIONS[3], context=ctx)
+    main, original = _legs("main"), _legs("original")
+    assert all(leg.closed for leg in main.values())  # sold at SESSIONS[3]'s open
+    assert not any(leg.closed or leg.pending for leg in original.values())
+    assert _reevaluations()[0][1:] == ("major", SESSIONS[2], SESSIONS[2], ["filing"])
+    assert _open([ready()])["ready"] == 2  # the live (value) main legs have exited
+
+
+def test_triggers_within_three_sessions_join_the_open_reevaluation(value_db) -> None:
+    """Spec §7.1: one re-evaluation is open per position; a trigger within three sessions joins
+    it unless it is more severe. Earnings on SESSIONS[2] open one; a 10-Q two sessions later
+    joins; a Major 8-K a session after that opens a second; a 10-Q six sessions on, a third."""
+    _entered()
+    market = {"STDY": bars([30.0] + [31.0] * 11), "SPY": bars([500.0] * 12)}
+    filings = [
+        FilingEvent(accn="q", form="10-Q", filed=SESSIONS[4]),
+        FilingEvent(accn="k", form="8-K", filed=SESSIONS[5], items=["4.02"]),
+        FilingEvent(accn="q2", form="10-Q/A", filed=SESSIONS[11]),
+    ]
+    ctx = shadow.ReevalContext(filings={"STDY": filings}, earnings={"STDY": [SESSIONS[2]]})
+    with value_session() as s:
+        shadow.step_legs(s, market, {}, CFG, as_of=SESSIONS[11], context=ctx)
+    deep = [r for r in _reevaluations() if r[0] == "deep_value"]
+    assert [r[1:] for r in deep] == [
+        ("minor", SESSIONS[2], SESSIONS[4], ["earnings", "filing"]),
+        ("major", SESSIONS[5], SESSIONS[5], ["filing"]),
+    ]  # the 8-K 4.02 sold every main leg, so nothing re-evaluates after it
+    assert _legs("original")[("deep_value", "value")].closed is False
+
+
+def test_news_and_the_regime_count_on_tonights_session_only(value_db) -> None:
+    """They are measured tonight: a catch-up night attributes them to the session dated as_of."""
+    _entered()
+    market = {"STDY": bars([30.0, 31.0, 31.2, 31.1]), "SPY": bars([500.0] * 4)}
+    ctx = shadow.ReevalContext(
+        news={"STDY": NewsVolume(last_24h=20, daily_median_30d=2.0)}, regime_stepped=True
+    )
+    with value_session() as s:
+        shadow.step_legs(s, market, {}, CFG, as_of=SESSIONS[3], context=ctx)
+    assert {r[2] for r in _reevaluations()} == {SESSIONS[3]}
+    assert _reevaluations()[0][4] == ["news", "regime"]
+    assert all(not leg.pending for leg in _legs("main").values())  # neither moves a level
+
+
+def test_a_catch_up_night_reads_tonights_facts_on_tonights_session_only(value_db) -> None:
+    """Review M1: a filing scored tonight is not known on the sessions the night steps over.
+    The re-mark lands on SESSIONS[3] (tonight), not on the entry session."""
+    _entered()
+    market = {"STDY": bars([30.0, 31.0, 31.5, 31.4]), "SPY": bars([500.0] * 4)}
+    newer = build_scorecard(
+        inputs(symbol="STDY", close=31.4, fin=financials(accn="0000000001-26-000002")), CFG
+    )
+    with value_session() as s:
+        shadow.step_legs(s, market, {"STDY": newer}, CFG, as_of=SESSIONS[3])
+    with value_session() as s:
+        remarks = {e.day for e in s.scalars(select(ValueShadowEventRow)) if e.kind == "remark"}
+    assert remarks == {SESSIONS[3]}
 
 
 def test_a_signal_that_never_gets_a_bar_is_voided(value_db) -> None:
@@ -346,3 +496,49 @@ def test_process_runs_a_night_in_order(value_db, research) -> None:
         )
     assert (out.filled, out.opened["ready"]) == (2, 0)
     assert out.events == 0  # the entry session's close is read; nothing fires
+
+
+def test_process_reads_the_filings_feed_and_the_going_concern_flag(value_db, research) -> None:
+    """The night reads research.db's filing index: an 8-K 1.03 filed on the session re-evaluates
+    and exits the main legs; a going-concern doubt in the newest read 10-Q exits every leg."""
+    from src.research.store.models import FilingIndexRow, SymbolRow
+
+    for i, d in enumerate(SESSIONS[:3]):
+        _bar(research, "STDY", d, 30.0 + i)
+        _bar(research, "SPY", d, 500.0)
+    research.add(SymbolRow(symbol="STDY", cik="0000000001"))
+    research.add(
+        FilingIndexRow(
+            accn="0000000001-26-000009",
+            cik="0000000001",
+            form="8-K",
+            filed=SESSIONS[2],
+            items="1.03,9.01",
+        )
+    )
+    research.flush()
+    night = {"tags": {"STDY": "trading"}, "atr": {}, "evidence": set(), "cfg": CFG}
+    for day in SESSIONS[:3]:
+        with value_session() as s:
+            out = shadow.process(
+                s, research, [ready()], as_of=day, version="v3", digest="x", now=NOW, **night
+            )
+    assert out.reevaluations == 2 and out.events == 6  # a thesis exit on each main leg
+    assert {r[1] for r in _reevaluations()} == {"major"}
+    research.add(
+        FilingIndexRow(
+            accn="0000000001-26-000008",
+            cik="0000000001",
+            form="10-Q",
+            filed=SESSIONS[1],
+            going_concern=True,
+        )
+    )
+    _bar(research, "STDY", SESSIONS[3], 33.0)
+    _bar(research, "SPY", SESSIONS[3], 500.0)
+    research.flush()
+    with value_session() as s:
+        shadow.process(
+            s, research, [ready()], as_of=SESSIONS[3], version="v3", digest="x", now=NOW, **night
+        )
+    assert all(leg.pending == 1.0 for leg in _legs("original").values())
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_shadow.py`
  Expected: FAIL — `AttributeError: module 'src.value.shadow' has no attribute 'rebase'` (and
  `ReevalContext`, the `mark_horizons` count).

- [ ] **Step 3: The shadow record** — replace `src/value/shadow.py` with:

```python
"""The shadow record (spec §6.8, §7, §12): hypothetical entries, the exit engine's three policies,
fixed-horizon returns against SPY, and the ranked monthly record. Writes value.db only; reads
research.db through the neutral read-only loader.

Part 2 runs Python's **baseline** track alone; Part 4 adds Claude's track beside it. Nothing here
can place, size or gate an order: every row is hypothetical.

The rules this module applies (the plan's rulings say why):
- a READY signal on the night of session D enters at the open of the next session after D;
- control groups enter on the nights a list gets a new READY entry: every name on that list that
  is healthy but too dear (WAIT), and every name cheap enough whose health failed;
- a key (kind, list, symbol) re-enters only once its previous entry stops blocking: a READY
  entry blocks while its live-policy leg holds, a control entry until its horizons are marked;
- horizon h is marked at the close of the h-th session after the entry session (SPY's sessions),
  from the bars as they stand that night, so a split adjusts both ends alike;
- (Part 3) a leg's absolute levels are **rebased** mechanically when the provider rewrote the
  bars (a split, a special or ordinary dividend adjustment): the bar now on a leg's last stepped
  session against the close the leg saw there (the entry bar for an entry not yet stepped) gives
  the ratio, and every recorded price level of the entry and its legs is multiplied by it. Part 2's
  ``rebase_needed`` entries are rebased and re-opened the same way;
- (Part 3) every session a READY entry's main legs step is checked for §7.1's triggers; a
  re-evaluation is recorded in ``value_reevaluations``, applies its plan actions to the main legs,
  and from the first one on the entry also carries an ``original`` twin of each leg, stepped with
  no re-evaluation, so the report can say whether re-evaluating saved money or only churned;
- (review M1) tonight's scorecard facts are read only on the session dated tonight's as_of: a
  catch-up night steps the earlier sessions on price alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg
from src.common.value_inputs import (
    build_day_bars,
    closes_on,
    filings_between,
    going_concern_flags,
    read_bars,
)
from src.common.value_types import DayBar, FilingEvent, NewsVolume
from src.value import reevaluate
from src.value.exits import (
    POLICIES,
    DayFacts,
    ExitEvent,
    LegState,
    Reeval,
    benchmark_return,
    open_leg,
    step,
)
from src.value.rank import rank_list
from src.value.ranked import BUCKETS, buckets, equal_weight_return, is_new_month
from src.value.report import HORIZONS
from src.value.residuals import Move, moves
from src.value.schemas import LISTS, ValueScorecard
from src.value.store import (
    ValueRankedRow,
    ValueReevaluationRow,
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
)

BENCHMARK = "SPY"
TRACK = "baseline"
GRACE_SESSIONS = 5
SHADOW_UNIVERSES = ("trading", "evidence")
HELD = ("pending", "open", "rebase_needed")  # entries the record still carries
REBASE_TOLERANCE = 1e-4  # a ratio this close to 1 is float noise, not a rewrite
MAIN, ORIGINAL = "main", "original"


@dataclass(slots=True)
class ShadowSummary:
    opened: dict[str, int] = field(default_factory=dict)
    filled: int = 0
    voided: int = 0
    events: int = 0
    marked: int = 0
    closed: int = 0
    rebased: int = 0
    rebase_needed: int = 0  # entries still frozen: no bar left to measure a rebase against
    reevaluations: int = 0
    ranked_formed: int = 0
    ranked_closed: int = 0


@dataclass(slots=True)
class ReevalContext:
    """What tonight's re-evaluations read beyond the bars (spec §7.1): filings and going-concern
    reads from research.db, and the plain data the value process hands in."""

    filings: dict[str, list[FilingEvent]] = field(default_factory=dict)
    going_concern: dict[str, bool] = field(default_factory=dict)
    earnings: dict[str, list[date]] = field(default_factory=dict)
    news: dict[str, NewsVolume] = field(default_factory=dict)
    regime_stepped: bool = False
    etf_for: dict[str, str] = field(default_factory=dict)  # symbol -> its sector ETF


def _actual(card: ValueScorecard, check_id: str) -> float | None:
    for c in card.health_checks:
        if c.id == check_id:
            return c.actual
    return None


def _missing_components(card: ValueScorecard, check_id: str) -> int:
    """How many F-score components were unknown (the check's detail lists them, comma-joined)."""
    for c in card.health_checks:
        if c.id == check_id and c.actual is not None:
            return len([p for p in c.detail.split(", ") if p])
    return 0


def day_facts(
    card: ValueScorecard | None, list_name: str, going_concern: bool | None = None
) -> DayFacts | None:
    """The night's Python numbers for one list (baseline track: effective = Python's)."""
    if card is None:
        return None
    ev = card.lists.get(list_name)
    fv = ev.fair_value if ev is not None else None
    return DayFacts(
        python_fair_value=fv,
        effective_fair_value=fv,
        latest_accn=card.fingerprint.latest_accn,
        piotroski=_actual(card, "health.piotroski"),
        piotroski_missing=_missing_components(card, "health.piotroski"),
        altman_z=_actual(card, "health.altman_z"),
        going_concern=going_concern,
    )


def blocking_keys(vs: Session, live_policy: str) -> set[tuple[str, str, str]]:
    """(kind, list, symbol) keys that may not enter again tonight."""
    out: set[tuple[str, str, str]] = set()
    rows = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.track == TRACK,
            ValueShadowRow.status.in_(HELD),
        )
    )
    for row in rows:
        key = (row.kind, row.list_name, row.symbol)
        if row.kind != "ready" or row.status != "open":
            out.add(key)
            continue
        live = vs.scalar(
            select(ValueShadowLegRow.closed).where(
                ValueShadowLegRow.shadow_id == row.id,
                ValueShadowLegRow.policy == live_policy,
                ValueShadowLegRow.plan == MAIN,
            )
        )
        if not live:
            out.add(key)
    return out


def _entry(
    card: ValueScorecard,
    list_name: str,
    kind: str,
    universe: str,
    atr14: float | None,
    now: datetime,
) -> ValueShadowRow:
    ev = card.lists[list_name]
    return ValueShadowRow(
        track=TRACK,
        kind=kind,
        list_name=list_name,
        symbol=card.symbol,
        universe=universe,
        signal_date=card.as_of,
        status="pending",
        status_detail="",
        verdict=ev.verdict,
        signal_close=card.price,
        atr14=atr14,
        fair_value=ev.fair_value,
        effective_fair_value=ev.fair_value,
        margin_of_safety=ev.margin_of_safety,
        required_mos_pct=ev.required_mos_pct,
        fv_accn=card.fingerprint.latest_accn,
        fingerprint_key=card.fingerprint.key(),
        ruleset_version=card.ruleset_version,
        ruleset_hash=card.ruleset_hash,
        scorecard_json=card.model_dump_json(),
        created_at=now,
    )


def open_signals(
    vs: Session,
    cards: list[ValueScorecard],
    tags: dict[str, str],
    atr: dict[str, float | None],
    *,
    live_policy: str,
    now: datetime,
) -> dict[str, int]:
    """Tonight's READY signals, then the control groups for every list that got one. Only the
    trading and evidence universes enter (a followed lookup does not)."""
    blocked = blocking_keys(vs, live_policy)
    counts = {"ready": 0, "control_valuation": 0, "control_health": 0}
    eligible = [
        c
        for c in cards
        if tags.get(c.symbol) in SHADOW_UNIVERSES
        and c.data_quality == "pass"
        and c.not_applicable_reason is None
    ]

    def add(card: ValueScorecard, list_name: str, kind: str) -> None:
        key = (kind, list_name, card.symbol)
        if key in blocked:
            return
        vs.add(_entry(card, list_name, kind, tags[card.symbol], atr.get(card.symbol), now))
        blocked.add(key)
        counts[kind] += 1

    ready_lists: set[str] = set()
    for card in eligible:
        for name in LISTS:
            if card.verdict_for(name) == "READY":
                before = counts["ready"]
                add(card, name, "ready")
                if counts["ready"] > before:
                    ready_lists.add(name)
    for name in (n for n in LISTS if n in ready_lists):
        for card in eligible:
            ev = card.lists.get(name)
            if ev is None:
                continue
            if ev.verdict == "WAIT":
                add(card, name, "control_valuation")
            elif (
                card.health == "fail"
                and ev.entry_ceiling is not None
                and card.price is not None
                and card.price <= ev.entry_ceiling
            ):
                add(card, name, "control_health")
    return counts


def load_bars(rs: Session, symbols: set[str], as_of: date) -> dict[str, list[DayBar]]:
    return {s: build_day_bars(read_bars(rs, s, as_of)) for s in sorted(symbols)}


def _bar_on(bars: list[DayBar], day: date) -> DayBar | None:
    return next((b for b in bars if b.date == day), None)


def _price(bar: DayBar) -> float:
    return bar.open if bar.open is not None else bar.close


def fill_pending(vs: Session, market: dict[str, list[DayBar]], cfg: ValueCfg) -> tuple[int, int]:
    """Enter yesterday's signals at the next session's open; void one that gets no bar within
    ``GRACE_SESSIONS`` of SPY's sessions."""
    spy = market.get(BENCHMARK, [])
    filled = voided = 0
    for row in vs.scalars(select(ValueShadowRow).where(ValueShadowRow.status == "pending")):
        after = [b for b in market.get(row.symbol, []) if b.date > row.signal_date]
        spy_bar = _bar_on(spy, after[0].date) if after else None
        if after and spy_bar is not None:
            first = after[0]
            row.entry_date = first.date
            row.entry_price = _price(first)
            row.spy_entry_price = _price(spy_bar)
            row.status = "open"
            filled += 1
            if row.kind == "ready":
                for policy in POLICIES:
                    state = open_leg(
                        policy,
                        entry_date=first.date,
                        entry_price=row.entry_price,
                        atr14=row.atr14,
                        fair_value=row.fair_value,
                        effective_fair_value=row.effective_fair_value,
                        fv_accn=row.fv_accn,
                        cfg=cfg.rules.exits,
                    )
                    vs.add(
                        ValueShadowLegRow(
                            shadow_id=row.id, policy=policy, state_json=state.model_dump_json()
                        )
                    )
        elif sum(1 for b in spy if b.date > row.signal_date) >= GRACE_SESSIONS:
            row.status = "void"
            row.status_detail = f"no {row.symbol} bar within {GRACE_SESSIONS} sessions"
            voided += 1
    vs.flush()
    return filled, voided


def _ratio(row: ValueShadowRow, legs: list[ValueShadowLegRow], bars: list[DayBar]) -> float | None:
    """How far the provider rewrote this entry's bars: the bar now on the newest stepped session
    over the close a leg saw there; for an entry no leg has stepped yet, the entry bar over the
    recorded entry price. None when no reference bar is left."""
    stepped = [g for g in legs if g.last_step is not None]
    if stepped:
        leg = max(stepped, key=lambda g: (g.last_step, not g.closed))
        assert leg.last_step is not None
        seen = LegState.model_validate_json(leg.state_json).last_close
        bar = _bar_on(bars, leg.last_step)
        if seen and bar is not None:
            return bar.close / seen
    if row.entry_date is None or not row.entry_price:
        return None
    entry = _bar_on(bars, row.entry_date)
    return None if entry is None else _price(entry) / row.entry_price


def _times(v: float | None, ratio: float) -> float | None:
    return None if v is None else v * ratio


def rebase(vs: Session, market: dict[str, list[DayBar]], day: date) -> tuple[int, int]:
    """Spec §7.1: corporate actions are not triggers; levels are rebased mechanically and the
    rebase is recorded. Re-opens Part 2's ``rebase_needed`` entries. Returns (rebased, still
    frozen)."""
    rebased = frozen = 0
    rows = vs.scalars(
        select(ValueShadowRow).where(ValueShadowRow.status.in_(("open", "rebase_needed")))
    ).all()
    for row in rows:
        legs = vs.scalars(
            select(ValueShadowLegRow).where(ValueShadowLegRow.shadow_id == row.id)
        ).all()
        ratio = _ratio(row, list(legs), market.get(row.symbol, []))
        if ratio is None or ratio <= 0:
            if row.status == "rebase_needed":
                frozen += 1
            continue
        if abs(ratio - 1.0) > REBASE_TOLERANCE:
            assert row.entry_price is not None
            row.entry_price *= ratio
            row.signal_close = _times(row.signal_close, ratio)
            row.atr14 = _times(row.atr14, ratio)
            row.fair_value = _times(row.fair_value, ratio)
            row.effective_fair_value = _times(row.effective_fair_value, ratio)
            for leg in legs:
                state = LegState.model_validate_json(leg.state_json).rebased(ratio)
                leg.state_json = state.model_dump_json()
            vs.add(
                ValueShadowEventRow(
                    shadow_id=row.id,
                    policy="all",
                    plan=MAIN,
                    day=day,
                    kind="rebase",
                    fraction=0.0,
                    detail=f"every price level x {ratio:.6f}: the bars were rewritten "
                    "(a split or a dividend adjustment)",
                )
            )
            rebased += 1
        if row.status == "rebase_needed":
            row.status = "open"
            row.status_detail += " Rebased and re-opened (Part 3)."
    vs.flush()
    return rebased, frozen


def _plan(states: dict[int, LegState]) -> dict[str, dict[str, object]]:
    return {
        s.policy: {
            "stop": s.stop,
            "armed": s.armed,
            "fair_value": s.fair_value,
            "remaining": s.remaining,
            "pending": s.pending,
            "closed": s.closed,
        }
        for s in states.values()
    }


def _closes(bars: list[DayBar]) -> list[tuple[date, float]]:
    return [(b.date, b.close) for b in bars]


def _record_events(
    vs: Session, row: ValueShadowRow, leg: ValueShadowLegRow, events: list[ExitEvent]
) -> None:
    for e in events:
        vs.add(
            ValueShadowEventRow(
                shadow_id=row.id,
                policy=leg.policy,
                plan=leg.plan,
                day=e.day,
                kind=e.kind,
                price=e.price,
                fraction=e.fraction,
                detail=e.detail,
            )
        )


class _Reevaluator:
    """One READY entry's §7.1 bookkeeping across the sessions of one night."""

    def __init__(
        self, vs: Session, row: ValueShadowRow, cfg: ValueCfg, ctx: ReevalContext, now: datetime
    ) -> None:
        self.vs, self.row, self.cfg, self.ctx, self.now = vs, row, cfg, ctx, now
        self.open = vs.scalars(
            select(ValueReevaluationRow)
            .where(ValueReevaluationRow.shadow_id == row.id)
            .order_by(ValueReevaluationRow.session.desc(), ValueReevaluationRow.id.desc())
            .limit(1)
        ).first()
        assert row.entry_date is not None
        self.last_day: date = self.open.session if self.open is not None else row.entry_date
        self.count = 0

    def triggers(
        self,
        bar: DayBar,
        after: date,
        move: Move | None,
        tonight: bool,
    ) -> list[reevaluate.Trigger]:
        sym = self.row.symbol
        return reevaluate.session_triggers(
            day=bar.date,
            after=after,
            move=move,
            filings=self.ctx.filings.get(sym, []),
            earnings=self.ctx.earnings.get(sym, []),
            news=self.ctx.news.get(sym) if tonight else None,
            regime_stepped=self.ctx.regime_stepped and tonight,
            last_reevaluation=self.last_day,
            cfg=self.cfg.rules.reevaluation,
        )

    def record(
        self,
        day: date,
        fired: list[reevaluate.Trigger],
        before: dict[str, dict[str, object]],
        after: dict[str, dict[str, object]],
        sessions_since: int | None,
        verdict_now: str | None,
    ) -> None:
        sev = reevaluate.severity(fired)
        assert sev is not None
        items = [{"day": day.isoformat(), **t.model_dump()} for t in fired]
        current = self.open
        if current is not None and reevaluate.joins(
            current.severity,  # type: ignore[arg-type]
            sessions_since,
            sev,
            self.cfg.rules.reevaluation,
        ):
            current.triggers_json = json.dumps([*json.loads(current.triggers_json), *items])
            current.last_session = day
            current.plan_after_json = json.dumps(after)
            if verdict_now is not None:
                current.verdict_now = verdict_now
            return
        self.open = ValueReevaluationRow(
            shadow_id=self.row.id,
            symbol=self.row.symbol,
            list_name=self.row.list_name,
            session=day,
            last_session=day,
            severity=sev,
            triggers_json=json.dumps(items),
            plan_before_json=json.dumps(before),
            plan_after_json=json.dumps(after),
            verdict_at_entry=self.row.verdict,
            verdict_now=verdict_now,
            ruleset_version=self.row.ruleset_version,
            ruleset_hash=self.row.ruleset_hash,
            created_at=self.now,
        )
        self.vs.add(self.open)
        self.last_day = day
        self.count += 1


def step_legs(
    vs: Session,
    market: dict[str, list[DayBar]],
    cards: dict[str, ValueScorecard],
    cfg: ValueCfg,
    *,
    as_of: date | None = None,
    context: ReevalContext | None = None,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Run every open leg over the sessions it has not seen. Tonight's facts are read on the
    session dated *as_of* only (the name's newest bar when None, review M1). With a *context*,
    each session of a READY entry's main legs is checked for §7.1's triggers. Returns (events,
    re-evaluations opened)."""
    spy_open = {b.date: _price(b) for b in market.get(BENCHMARK, [])}
    rcfg = cfg.rules.reevaluation
    n_events = n_reevals = 0
    rows = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.status == "open", ValueShadowRow.kind == "ready"
        )
    ).all()
    for row in rows:
        bars = market.get(row.symbol, [])
        assert row.entry_date is not None and row.spy_entry_price is not None
        legs = list(
            vs.scalars(
                select(ValueShadowLegRow).where(
                    ValueShadowLegRow.shadow_id == row.id, ValueShadowLegRow.closed.is_(False)
                )
            )
        )
        if not legs or not bars:
            continue
        tonight = as_of if as_of is not None else bars[-1].date
        card = cards.get(row.symbol)
        facts = day_facts(
            card,
            row.list_name,
            None if context is None else context.going_concern.get(row.symbol),
        )
        states = {leg.id: LegState.model_validate_json(leg.state_json) for leg in legs}
        firsts = [leg.last_step for leg in legs]
        start = None if any(f is None for f in firsts) else min(f for f in firsts if f)
        days = [b for b in bars if b.date >= row.entry_date and (start is None or b.date > start)]
        reeval = None
        found: dict[date, Move] = {}
        if context is not None and days and any(leg.plan == MAIN for leg in legs):
            reeval = _Reevaluator(vs, row, cfg, context, now or datetime.now())
            etf = market.get(context.etf_for.get(row.symbol, rcfg.fallback_etf), [])
            found = moves(_closes(bars), _closes(etf), [b.date for b in days], rcfg)
        index = {b.date: i for i, b in enumerate(bars)}
        for b in days:
            i = index[b.date]
            previous = bars[i - 1] if i > 0 else None
            after = (
                previous.date if previous and previous.date >= row.entry_date else row.signal_date
            )
            mains = [leg for leg in legs if leg.plan == MAIN and not states[leg.id].closed]
            action: Reeval | None = None
            fired: list[reevaluate.Trigger] = []
            if reeval is not None and mains:
                fired = reeval.triggers(b, after, found.get(b.date), b.date == tonight)
                if fired:
                    action = reevaluate.plan_actions(fired, b, previous, rcfg)
                    if not any(leg.plan == ORIGINAL for leg in legs):
                        for leg in mains:  # the original plan, untouched from here on
                            twin = ValueShadowLegRow(
                                shadow_id=row.id,
                                policy=leg.policy,
                                plan=ORIGINAL,
                                state_json=states[leg.id].model_dump_json(),
                                last_step=leg.last_step,
                                closed=False,
                                sessions=leg.sessions,
                                sells=leg.sells,
                                max_drawdown=leg.max_drawdown,
                            )
                            vs.add(twin)
                            vs.flush()
                            legs.append(twin)
                            states[twin.id] = states[leg.id]
            before = _plan({leg.id: states[leg.id] for leg in mains})
            for leg in legs:
                if leg.last_step is not None and b.date <= leg.last_step:
                    continue
                state = states[leg.id]
                if state.closed:
                    continue
                state, events = step(
                    state,
                    b,
                    facts if b.date == tonight else None,
                    cfg.rules.exits,
                    action if leg.plan == MAIN else None,
                )
                states[leg.id] = state
                leg.last_step = b.date
                _record_events(vs, row, leg, events)
                n_events += len(events)
            if fired and reeval is not None:
                opened = reeval.open.session if reeval.open is not None else None
                since = (
                    None if opened is None else sum(1 for d in bars if opened < d.date <= b.date)
                )
                reeval.record(
                    b.date,
                    fired,
                    before,
                    _plan({leg.id: states[leg.id] for leg in mains}),
                    since,
                    card.verdict_for(row.list_name)
                    if card is not None and b.date == tonight
                    else None,
                )
        if reeval is not None:
            n_reevals += reeval.count
        spy_entry = spy_open.get(row.entry_date, row.spy_entry_price)  # one basis (review M8)
        for leg in legs:
            state = states[leg.id]
            leg.state_json = state.model_dump_json()
            leg.sessions, leg.sells = state.sessions, state.sells
            leg.max_drawdown = state.max_drawdown
            if state.closed and not leg.closed:
                vs.flush()
                fills = [
                    (d, f)
                    for d, f in vs.execute(
                        select(ValueShadowEventRow.day, ValueShadowEventRow.fraction).where(
                            ValueShadowEventRow.shadow_id == row.id,
                            ValueShadowEventRow.policy == leg.policy,
                            ValueShadowEventRow.plan == leg.plan,
                            ValueShadowEventRow.kind == "fill",
                        )
                    )
                ]
                leg.closed, leg.exit_date = True, state.exit_date
                leg.ret_exit = state.exit_return()
                leg.spy_ret_exit = benchmark_return(fills, spy_open, spy_entry)
    vs.flush()
    return n_events, n_reevals


def _close_on_or_before(bars: list[DayBar], day: date) -> float | None:
    before = [b for b in bars if b.date <= day]
    return before[-1].close if before else None


def mark_horizons(vs: Session, market: dict[str, list[DayBar]]) -> int:
    """Mark-to-market returns at 21/63/126 sessions (spec §12), against SPY, for every open
    entry: READY and control alike. Both ends are read from the bars as they stand, so a split
    or a dividend adjustment needs no rebase here (controls are never frozen: review M7)."""
    spy = market.get(BENCHMARK, [])
    marked = 0
    for row in vs.scalars(select(ValueShadowRow).where(ValueShadowRow.status == "open")).all():
        assert row.entry_date is not None and row.entry_price is not None
        bars = market.get(row.symbol, [])
        sessions = [b for b in spy if b.date >= row.entry_date]
        entry_bar = _bar_on(bars, row.entry_date)
        entry_px = _price(entry_bar) if entry_bar is not None else row.entry_price
        spy_entry = _price(sessions[0]) if sessions else row.spy_entry_price
        for h in HORIZONS:
            if getattr(row, f"ret_{h}") is not None or len(sessions) <= h:
                continue
            mark = sessions[h]
            seen_since = any(b.date >= mark.date for b in bars)
            late = sum(1 for b in spy if b.date > mark.date) >= GRACE_SESSIONS
            if not seen_since and not late:
                continue  # the name's bars may still arrive
            close = _close_on_or_before(bars, mark.date)
            if close is None or not spy_entry:
                continue
            setattr(row, f"ret_{h}", close / entry_px - 1.0)
            setattr(row, f"spy_{h}", mark.close / spy_entry - 1.0)
            if not seen_since:
                row.status_detail += f" h{h}: no bar since; last close used."
            marked += 1
    vs.flush()
    return marked


def close_finished(vs: Session, as_of: date) -> int:
    """An entry closes once all three horizons are marked and every leg has exited."""
    closed = 0
    for row in vs.scalars(select(ValueShadowRow).where(ValueShadowRow.status == "open")).all():
        if any(getattr(row, f"ret_{h}") is None for h in HORIZONS):
            continue
        open_legs = vs.scalar(
            select(func.count())
            .select_from(ValueShadowLegRow)
            .where(ValueShadowLegRow.shadow_id == row.id, ValueShadowLegRow.closed.is_(False))
        )
        if open_legs:
            continue
        row.status, row.closed_on = "closed", as_of
        closed += 1
    return closed


def run_ranked(
    vs: Session,
    rs: Session,
    cards: list[ValueScorecard],
    evidence: set[str],
    *,
    as_of: date,
    version: str,
    digest: str,
) -> tuple[int, int]:
    """On the first run of a new month: close the open portfolios at tonight's closes and form
    the next ones from tonight's ranks (spec §6.8)."""
    last = vs.scalar(select(func.max(ValueRankedRow.formed_on)))
    if not is_new_month(last, as_of):
        return 0, 0
    closed = 0
    spy_end = closes_on(rs, [BENCHMARK], as_of).get(BENCHMARK)
    open_rows = vs.scalars(select(ValueRankedRow).where(ValueRankedRow.closed_on.is_(None))).all()
    for row in open_rows:
        members = json.loads(row.members_json)
        start = closes_on(rs, members, row.formed_on)
        end = closes_on(rs, members, as_of)
        row.ret, row.missing = equal_weight_return(members, start, end)
        spy_start = closes_on(rs, [BENCHMARK], row.formed_on).get(BENCHMARK)
        row.spy_ret = spy_end / spy_start - 1.0 if spy_end and spy_start else None
        row.closed_on = as_of
        closed += 1
    formed = 0
    population = [c for c in cards if c.symbol in evidence]
    for name in LISTS:
        ranks = rank_list(population, name)
        picked = buckets({s: e.score for s, e in ranks.items()})
        if picked is None:
            continue
        for bucket in BUCKETS:
            vs.add(
                ValueRankedRow(
                    formed_on=as_of,
                    list_name=name,
                    bucket=bucket,
                    members_json=json.dumps(picked[bucket]),
                    n=len(picked[bucket]),
                    ruleset_version=version,
                    ruleset_hash=digest,
                )
            )
            formed += 1
    return formed, closed


def process(
    vs: Session,
    rs: Session,
    cards: list[ValueScorecard],
    *,
    tags: dict[str, str],
    atr: dict[str, float | None],
    evidence: set[str],
    as_of: date,
    cfg: ValueCfg,
    version: str,
    digest: str,
    now: datetime,
    earnings: dict[str, list[date]] | None = None,
    news: dict[str, NewsVolume] | None = None,
    regime_stepped: bool = False,
) -> ShadowSummary:
    """One night of the shadow record, in order: fill yesterday's signals, rebase what the
    provider rewrote, run the legs with §7.1's re-evaluations, mark the horizons, close what is
    finished, open tonight's signals, then the ranked record. *earnings* (each name's recent
    report dates) and *news* (trigger 5) are plain data from the value process."""
    out = ShadowSummary()
    by_symbol = {c.symbol: c for c in cards}
    live = cfg.rules.exits.live_policy
    rcfg = cfg.rules.reevaluation
    held = set(vs.scalars(select(ValueShadowRow.symbol).where(ValueShadowRow.status.in_(HELD))))
    etf_for = {
        s: rcfg.sector_etfs.get(
            (by_symbol[s].classification.sector or "") if s in by_symbol else "",
            rcfg.fallback_etf,
        )
        for s in held
    }
    market = load_bars(rs, held | {BENCHMARK} | set(etf_for.values()), as_of)
    out.filled, out.voided = fill_pending(vs, market, cfg)
    out.rebased, out.rebase_needed = rebase(vs, market, as_of)
    open_ready = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.status == "open", ValueShadowRow.kind == "ready"
        )
    ).all()
    symbols = sorted({r.symbol for r in open_ready})
    oldest = min((r.signal_date for r in open_ready), default=as_of)
    context = ReevalContext(
        filings=filings_between(rs, symbols, oldest, as_of),
        going_concern=going_concern_flags(rs, symbols, as_of),
        earnings=earnings or {},
        news=news or {},
        regime_stepped=regime_stepped,
        etf_for=etf_for,
    )
    out.events, out.reevaluations = step_legs(
        vs, market, by_symbol, cfg, as_of=as_of, context=context, now=now
    )
    out.marked = mark_horizons(vs, market)
    vs.flush()
    out.closed = close_finished(vs, as_of)
    vs.flush()
    out.opened = open_signals(vs, cards, tags, atr, live_policy=live, now=now)
    out.ranked_formed, out.ranked_closed = run_ranked(
        vs, rs, cards, evidence, as_of=as_of, version=version, digest=digest
    )
    return out
```

- [ ] **Step 4: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_shadow.py tests/test_value_service.py tests/test_value_store.py tests/test_value_report.py tests/test_value_fence.py`
  Expected: PASS (`test_value_shadow.py` 20). Then ruff check/format and `.venv/bin/mypy
  src/value/shadow.py` — clean.

- [ ] **Step 5: Commit**

  ```bash
  git add src/value/shadow.py tests/test_value_shadow.py
  git commit -m "feat(value): re-evaluations, the original twin and the mechanical rebase in the shadow record"
  ```

---

### Task 8: The process — plain data, the regime step, the fences

**Files:** Modify `src/value/service.py`, `scripts/value_feed.py`, `scripts/run_value.py`,
`tests/test_value_feed.py`, `tests/test_value_service.py`, `tests/test_value_fence.py`

**Interfaces:**
- Consumes: `shadow.process(..., earnings=, news=, regime_stepped=)`, `shadow.HELD` (Task 7),
  `reevaluate.regime_stepped` (Task 5), `NewsVolume` (Task 3).
- Produces: `RunPlan.positions: set[str]` (the open READY entries); `service.open_positions(vs)`,
  `service.previous_regime(vs) -> str | None`; `shadow_names` now includes `rebase_needed`;
  `run_nightly(plan, *, facts, earnings, now=None, recent_earnings=None, news=None)`;
  `value_feed.recent_earnings(as_of, symbols) -> dict[str, list[date]]`,
  `value_feed.news_volume(symbols, now=None) -> dict[str, NewsVolume]`.

- [ ] **Step 1: Write the failing tests** — apply to `tests/test_value_feed.py`:

```diff
diff --git a/tests/test_value_feed.py b/tests/test_value_feed.py
index 8cf314b..b29c6dc 100644
--- a/tests/test_value_feed.py
+++ b/tests/test_value_feed.py
@@ -1,14 +1,14 @@
 """scripts/value_feed.py: the plain data the value process hands to src/value/ (value book spec
-§6.6). ``scripts/run_value.py`` itself is never imported: it is compiled only."""
+§6.6, §7.1). ``scripts/run_value.py`` itself is never imported: it is compiled only."""
 
 from __future__ import annotations
 
 import py_compile
-from datetime import date
+from datetime import UTC, date, datetime, timedelta
 
 import src.common.value_inputs as vi
 from scripts import value_feed
-from src.common.value_types import MarketFacts
+from src.common.value_types import MarketFacts, NewsVolume
 
 
 def test_the_entrypoint_compiles() -> None:
@@ -30,6 +30,67 @@ def test_earnings_come_from_news_db_earliest_first(news_db) -> None:
 
 def test_an_unreadable_news_db_means_no_dates_not_a_crash() -> None:
     assert value_feed.earnings_dates(date(2026, 11, 2)) == {}  # conftest points at no file
+    assert value_feed.recent_earnings(date(2026, 11, 2), {"MU"}) == {}
+    assert value_feed.news_volume(["MU"]) == {}
+
+
+def test_recent_report_dates_are_the_fortnight_up_to_the_session(news_db) -> None:
+    from src.news.store.models import EarningsEventRow
+    from src.news.store.session import news_session
+
+    with news_session() as s:
+        s.add(EarningsEventRow(symbol="MU", report_date=date(2026, 10, 29)))
+        s.add(EarningsEventRow(symbol="MU", report_date=date(2026, 12, 17)))  # still ahead
+        s.add(EarningsEventRow(symbol="BAC", report_date=date(2026, 10, 14)))  # 19 days back
+        s.add(EarningsEventRow(symbol="AMD", report_date=date(2026, 11, 2)))  # not a position
+    assert value_feed.recent_earnings(date(2026, 11, 2), {"MU", "BAC"}) == {
+        "MU": [date(2026, 10, 29)]
+    }
+    assert value_feed.recent_earnings(date(2026, 11, 2), set()) == {}
+
+
+def test_news_volume_counts_the_last_day_against_the_monthly_daily_median(news_db) -> None:
+    """Trigger 5's inputs: 6 items in the last 24 hours; over the 30 days before, one item on each
+    of 20 days and none on 10: a daily median of 1."""
+    from src.news.store.models import NewsItemRow
+    from src.news.store.session import news_session
+
+    now = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
+    stamps = [now - timedelta(hours=h) for h in (1, 2, 3, 5, 8, 20)]
+    stamps += [now - timedelta(days=d, hours=2) for d in range(1, 21)]
+    stamps += [now - timedelta(days=40)]  # outside the window
+    with news_session() as s:
+        for i, ts in enumerate(stamps):
+            s.add(
+                NewsItemRow(
+                    url_hash=f"u{i}",
+                    title_hash=f"t{i}",
+                    title=f"MU item {i}",
+                    category="ticker",
+                    origin="rss",
+                    published_at=ts.replace(tzinfo=None),
+                    fetched_at=ts.replace(tzinfo=None),
+                    tickers=["MU"],
+                    det_sentiment=0.1,
+                )
+            )
+        s.add(
+            NewsItemRow(
+                url_hash="x",
+                title_hash="x",
+                title="no score",
+                category="ticker",
+                origin="rss",
+                published_at=(now - timedelta(hours=1)).replace(tzinfo=None),
+                fetched_at=(now - timedelta(hours=1)).replace(tzinfo=None),
+                tickers=["MU"],
+                det_sentiment=None,  # the sentiment rule reads scored items only
+            )
+        )
+    assert value_feed.news_volume(["MU", "BAC"], now) == {
+        "MU": NewsVolume(last_24h=6, daily_median_30d=1.0),
+        "BAC": NewsVolume(last_24h=0, daily_median_30d=0.0),
+    }
 
 
 class Clock:
```

  …to `tests/test_value_service.py` (Task 1 already flipped line 151 to v3):

```diff
diff --git a/tests/test_value_service.py b/tests/test_value_service.py
index a214c4f..1d46371 100644
--- a/tests/test_value_service.py
+++ b/tests/test_value_service.py
@@ -14,7 +14,7 @@ from sqlalchemy.orm import Session
 import src.common.value_inputs as vi
 import src.value.store as store
 from src.common.config import get_config
-from src.common.value_types import MarketFacts
+from src.common.value_types import MarketFacts, NewsVolume
 from src.common.value_universe import ValueUniverse
 from src.research.store.models import Base, CompanyFactsRawRow, DailyBarRow, SymbolRow
 from src.value import service
@@ -220,6 +220,52 @@ def test_a_failed_night_leaves_value_db_as_it_was(dbs, monkeypatch) -> None:
     assert service.plan_run(NOW, universe={}) is not None  # the next poll retries
 
 
+def test_a_night_hands_the_reevaluation_inputs_to_the_shadow_record(dbs, monkeypatch) -> None:
+    """Spec §7.1: earnings dates and news volume arrive as plain data; the regime trigger fires
+    on a step from the regime the previous night recorded."""
+    with value_session() as s:
+        record_run(
+            s,
+            kind="nightly",
+            started_at=NOW,
+            finished_at=NOW,
+            as_of=AS_OF - timedelta(days=1),
+            ruleset_version="v3",
+            ruleset_hash="x",
+            names=1,
+            rs_cutoff_6m=None,
+            summary_json=json.dumps({"regime": "cautious"}),
+        )
+        assert service.previous_regime(s) == "cautious"
+    monkeypatch.setattr(vi, "load_regime", lambda: "stressed")
+    seen: dict = {}
+    real = service.shadow.process
+
+    def spy(*a, **k):
+        seen.update(k)
+        return real(*a, **k)
+
+    monkeypatch.setattr(service.shadow, "process", spy)
+    plan = service.plan_run(NOW, universe={})
+    assert plan is not None and plan.positions == set()
+    news = {"STDY": NewsVolume(last_24h=9, daily_median_30d=1.0)}
+    service.run_nightly(
+        plan,
+        facts={"STDY": MarketFacts(market_cap=3.0e9)},
+        earnings={"STDY": AS_OF + timedelta(days=60)},
+        now=NOW,
+        recent_earnings={"STDY": [AS_OF]},
+        news=news,
+    )
+    assert seen["regime_stepped"] is True
+    assert (seen["news"], seen["earnings"]) == (news, {"STDY": [AS_OF]})
+    with value_session() as s:
+        for row in s.scalars(select(ValueShadowRow)):
+            row.status = "open"
+        assert service.open_positions(s) == {"STDY"}
+        assert service.previous_regime(s) == "stressed"
+
+
 def test_an_old_private_config_idles_the_process_instead_of_crash_looping(monkeypatch) -> None:
     monkeypatch.setattr(get_config().value, "ruleset_version", "v1")  # v1's pin, v2's rules
     problem = service.startup_check()
```

  …and to `tests/test_value_fence.py` (the new pure modules, the new row class, the probes — the
  process probe now also loads the service's lazy imports, review M11 — and a test that the filings
  feed lives in the research worker):

```diff
diff --git a/tests/test_value_fence.py b/tests/test_value_fence.py
index c88173d..cd9faa1 100644
--- a/tests/test_value_fence.py
+++ b/tests/test_value_fence.py
@@ -32,6 +32,8 @@ PURE = (
     "exits",
     "ranked",
     "report",
+    "residuals",
+    "reevaluate",
 )
 
 FORBIDDEN_FOR_VALUE = (
@@ -194,6 +196,7 @@ def test_only_src_value_constructs_value_rows() -> None:
         "ValueShadowLegRow(",
         "ValueShadowEventRow(",
         "ValueRankedRow(",
+        "ValueReevaluationRow(",
     )
     offenders = []
     for p in [*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")]:
@@ -209,6 +212,7 @@ def test_the_value_scorecard_loads_no_wheel_layer_even_transitively() -> None:
         "import json, sys\n"
         "import src.value.scorecard, src.value.store, src.value.ticker_file, src.value.funnel\n"
         "import src.value.exits, src.value.shadow, src.value.service, src.value.report\n"
+        "import src.value.residuals, src.value.reevaluate\n"
         "import src.common.value_inputs, src.common.value_universe\n"
         "print(json.dumps(sorted(m for m in sys.modules if m.startswith('src.'))))\n"
     )
@@ -272,6 +276,8 @@ def test_the_value_process_loads_no_wheel_layer_and_no_ibkr() -> None:
         "    importlib.import_module(m.name)\n"
         "import scripts.value_feed\n"
         "import src.news.store.readonly, src.news.store.queries, src.data.factory\n"
+        # what the service imports lazily, inside functions (review M11)
+        "import src.common.universe, src.storage.regime_state\n"
         "print(json.dumps(sorted(sys.modules)))\n"
     )
     env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
@@ -283,3 +289,17 @@ def test_the_value_process_loads_no_wheel_layer_and_no_ibkr() -> None:
     assert [m for m in forbidden if _reaches(loaded, m)] == []
     assert not _reaches(loaded, "src.news.store.session")
     assert not _reaches(loaded, "ib_async")
+
+
+def test_the_research_worker_owns_the_filings_feed() -> None:
+    """Spec §6.9: the submissions and going-concern jobs live in src/research and fetch through
+    src/data; the value side reads their table only through the neutral loader."""
+    for name in ("submissions", "going_concern"):
+        mods = imported_modules(ROOT / "src" / "research" / "ingest" / f"{name}.py")
+        assert _reaches(mods, "src.data.factory") and not _reaches(mods, "src.value")
+    readers = [
+        str(p.relative_to(ROOT))
+        for p in [*VALUE, *(ROOT / "scripts").glob("value_*.py")]
+        if "FilingIndexRow" in p.read_text(encoding="utf-8")
+    ]
+    assert readers == []  # only src/common/value_inputs.py names the table
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_feed.py tests/test_value_service.py tests/test_value_fence.py`
  Expected: FAIL — `AttributeError: module 'scripts.value_feed' has no attribute 'recent_earnings'`,
  `RunPlan` has no `positions`. The fence tests pass at once (record that).

- [ ] **Step 3: The service** — apply to `src/value/service.py`:

```diff
diff --git a/src/value/service.py b/src/value/service.py
index df02bfc..1e90f84 100644
--- a/src/value/service.py
+++ b/src/value/service.py
@@ -1,8 +1,9 @@
 """The value process's nightly run (spec §6.8, §6.9, §9.7): score both universes, the followed
 names and every shadow name once a session has closed, write the ticker files, run the shadow
-record and log the run. ``scripts/run_value.py`` is the thin entrypoint: it gathers the plain
-data this module may not fetch itself (earnings dates from news.db, yfinance market facts) and
-calls :func:`plan_run` and :func:`run_nightly`.
+record (with its §7.1 re-evaluations, Part 3) and log the run. ``scripts/run_value.py`` is the
+thin entrypoint: it gathers the plain data this module may not fetch itself (earnings dates and
+news volume from news.db, yfinance market facts) and calls :func:`plan_run` and
+:func:`run_nightly`.
 
 No IBKR connection and no clientId in Parts 1-4 (clientId 31 arrives with Stage 3). Reads
 research.db read-only through ``src/common/value_inputs.py``; writes value.db only. One run is
@@ -25,9 +26,9 @@ from sqlalchemy.orm import Session
 from src.common import value_inputs as vi
 from src.common.config import get_config
 from src.common.value_keep_fresh import write_keep_fresh
-from src.common.value_types import Classification, MarketFacts, ValueInputs
+from src.common.value_types import Classification, MarketFacts, NewsVolume, ValueInputs
 from src.common.value_universe import build_value_universe
-from src.value import shadow
+from src.value import reevaluate, shadow
 from src.value.rank import filed_lists, rank_list, rs_cutoff
 from src.value.ruleset import ruleset_id
 from src.value.scorecard import build_scorecard
@@ -55,6 +56,7 @@ class RunPlan:
     etfs: set[str] = field(default_factory=set)
     evidence: set[str] = field(default_factory=set)
     classification: dict[str, tuple[str, str]] = field(default_factory=dict)
+    positions: set[str] = field(default_factory=set)  # open READY entries: re-evaluated tonight
 
     @property
     def names(self) -> list[str]:
@@ -107,16 +109,42 @@ def followed_names(vs: Session, now: datetime, follow_days: int) -> list[str]:
 
 
 def shadow_names(vs: Session) -> dict[str, str]:
-    """Every name with a pending or open shadow entry, and the universe it entered from: held
-    and shadow names stay fresh even after they leave the universe (spec §6.9)."""
+    """Every name with a shadow entry the record still carries (pending, open, or frozen for a
+    rebase), and the universe it entered from: held and shadow names stay fresh even after they
+    leave the universe (spec §6.9)."""
     rows = vs.execute(
         select(ValueShadowRow.symbol, ValueShadowRow.universe).where(
-            ValueShadowRow.status.in_(("pending", "open"))
+            ValueShadowRow.status.in_(shadow.HELD)
         )
     )
     return {symbol: universe for symbol, universe in rows}
 
 
+def open_positions(vs: Session) -> set[str]:
+    """The names with an open READY entry: the positions §7.1 re-evaluates tonight."""
+    return set(
+        vs.scalars(
+            select(ValueShadowRow.symbol).where(
+                ValueShadowRow.status == "open", ValueShadowRow.kind == "ready"
+            )
+        )
+    )
+
+
+def previous_regime(vs: Session) -> str | None:
+    """The regime the last nightly run recorded (trigger 7 fires on a step from it)."""
+    row = vs.scalars(
+        select(ValueRunRow)
+        .where(ValueRunRow.kind == "nightly")
+        .order_by(ValueRunRow.as_of.desc())
+        .limit(1)
+    ).first()
+    if row is None:
+        return None
+    regime = json.loads(row.summary_json or "{}").get("regime")
+    return regime if isinstance(regime, str) else None
+
+
 def plan_run(now: datetime | None = None, universe: dict[str, Any] | None = None) -> RunPlan | None:
     """Tonight's plan, or None when no newly settled session is waiting. *as_of* is SPY's newest
     bar dated before today (ET): a bar dated today may still be forming."""
@@ -145,6 +173,7 @@ def plan_run(now: datetime | None = None, universe: dict[str, Any] | None = None
             tags.setdefault(symbol, f"held:{entered_from}")
         for symbol in followed_names(vs, now, vcfg.ticker_file.follow_days):
             tags.setdefault(symbol, "lookup")
+        positions = open_positions(vs)
     companies = [s for s in u.all_names() if s not in u.etfs]
     with vi.research_read() as rs:
         assert rs is not None
@@ -163,6 +192,7 @@ def plan_run(now: datetime | None = None, universe: dict[str, Any] | None = None
         etfs=set(u.etfs),
         evidence=set(u.evidence),
         classification=dict(u.classification),
+        positions=positions,
     )
 
 
@@ -214,9 +244,12 @@ def run_nightly(
     facts: dict[str, MarketFacts],
     earnings: dict[str, date],
     now: datetime | None = None,
+    recent_earnings: dict[str, list[date]] | None = None,
+    news: dict[str, NewsVolume] | None = None,
 ) -> dict[str, Any]:
     """Score, rank, persist the ticker files, run the shadow record and log the run, all in one
-    value.db transaction. Returns the run's summary."""
+    value.db transaction. Returns the run's summary. *recent_earnings* (report dates up to the
+    session) and *news* (trigger 5) are the plain data §7.1's re-evaluations read."""
     vcfg = get_config().value
     version, digest = ruleset_id(vcfg)
     started = now or _now()
@@ -248,6 +281,9 @@ def run_nightly(
                     session_row=tag != "lookup",
                 )
             vs.flush()
+            stepped = reevaluate.regime_stepped(
+                previous_regime(vs), regime, vcfg.rules.reevaluation
+            )
             record = shadow.process(
                 vs,
                 rs,
@@ -260,6 +296,9 @@ def run_nightly(
                 version=version,
                 digest=digest,
                 now=started,
+                earnings=recent_earnings,
+                news=news,
+                regime_stepped=stepped,
             )
             verdicts = {
                 name: dict(Counter(c.verdict_for(name) for c in cards))
```

- [ ] **Step 4: The feed and the entrypoint** — apply to `scripts/value_feed.py`:

```diff
diff --git a/scripts/value_feed.py b/scripts/value_feed.py
index 8cd02ee..50234da 100644
--- a/scripts/value_feed.py
+++ b/scripts/value_feed.py
@@ -1,7 +1,9 @@
-"""The plain data the value process hands to ``src/value/`` (spec §6.6, §6.9): earnings dates
-from news.db and yfinance market facts. ``src/value/`` may fetch neither itself: news.db is
-enrichment's database and yfinance is a network provider, so ``scripts/run_value.py`` gathers
-both here and passes them in as dicts.
+"""The plain data the value process hands to ``src/value/`` (spec §6.6, §6.9, §7.1): earnings
+dates and news volume from news.db, and yfinance market facts. ``src/value/`` may fetch none of
+them itself: news.db is enrichment's database and yfinance is a network provider, so
+``scripts/run_value.py`` gathers them here and passes them in as dicts. News volume only ever
+opens a re-evaluation (spec §7.1, trigger 5): it reads the deterministic ``news_items`` columns
+(``src.analytics.sentiment``'s rule), never a post or an explanation.
 
 Importable (no side effects at import), so it is tested and fenced; ``scripts/run_value.py`` is
 not imported by anything.
@@ -13,13 +15,16 @@ import logging
 import time
 from collections.abc import Callable
 from concurrent.futures import ThreadPoolExecutor
-from datetime import date, timedelta
+from datetime import UTC, date, datetime, timedelta
+from statistics import median
 
-from src.common.value_types import MarketFacts
+from src.common.value_types import MarketFacts, NewsVolume
 
 log = logging.getLogger(__name__)
 
 EARNINGS_HORIZON_DAYS = 180
+RECENT_EARNINGS_DAYS = 14  # report dates a catch-up night may step over (spec §7.1 trigger 3)
+NEWS_BASELINE_DAYS = 30  # trigger 5: the daily median is over the 30 days before the last 24h
 RETRY_SECONDS = 3600.0  # a failed night is retried at most once an hour
 CRITICAL_AFTER = 3  # failures for one session before the log turns CRITICAL
 
@@ -41,6 +46,49 @@ def earnings_dates(as_of: date) -> dict[str, date]:
     return out
 
 
+def recent_earnings(as_of: date, symbols: set[str]) -> dict[str, list[date]]:
+    """Each name's report dates in the ``RECENT_EARNINGS_DAYS`` up to *as_of* (spec §7.1
+    trigger 3: "the earnings_events date passes"). Unreadable news.db: an empty dict."""
+    import src.news.store.queries as queries
+    from src.news.store.readonly import read_only_session
+
+    out: dict[str, list[date]] = {}
+    if not symbols:
+        return out
+    with read_only_session() as s:
+        if s is None:
+            return out
+        start = as_of - timedelta(days=RECENT_EARNINGS_DAYS)
+        for e in queries.earnings_between(s, start, as_of, symbols):
+            out.setdefault(e.symbol, []).append(e.report_date)
+    return out
+
+
+def news_volume(symbols: list[str], now: datetime | None = None) -> dict[str, NewsVolume]:
+    """Each name's news items over the 24 hours to *now* and the median of its daily counts over
+    the ``NEWS_BASELINE_DAYS`` before them, from the deterministic ``news_items`` columns only
+    (spec §7.1 trigger 5). Unreadable news.db: an empty dict, so no trigger fires."""
+    import src.news.store.queries as queries
+    from src.news.store.readonly import read_only_session
+
+    now = now or datetime.now(UTC)
+    day = timedelta(days=1)
+    since = now - day * (NEWS_BASELINE_DAYS + 1)
+    out: dict[str, NewsVolume] = {}
+    with read_only_session() as s:
+        if s is None:
+            return out
+        for symbol in symbols:
+            stamps = [ts for _, ts, _, _ in queries.ticker_sentiment_rows(s, symbol, since)]
+            counts = [0] * (NEWS_BASELINE_DAYS + 1)  # [0] = the last 24 hours
+            for ts in stamps:
+                k = int((now - ts) / day)
+                if 0 <= k <= NEWS_BASELINE_DAYS and ts <= now:
+                    counts[k] += 1
+            out[symbol] = NewsVolume(last_24h=counts[0], daily_median_30d=median(counts[1:]))
+    return out
+
+
 class NightRetry:
     """Back-off for a night that keeps failing (review I2). Without it a failure that repeats
     every night (a bad row, a lock) would refetch ~1,000 names from yfinance every poll, all
```

  …and to `scripts/run_value.py` (its imports stay inside the fence's allowlist):

```diff
diff --git a/scripts/run_value.py b/scripts/run_value.py
index 6127944..eab10ba 100644
--- a/scripts/run_value.py
+++ b/scripts/run_value.py
@@ -6,7 +6,8 @@ Usage:
 No IBKR connection, no clientId (Parts 1-4). Every ``value.service.poll_seconds`` it asks
 ``src.value.service.plan_run`` whether a settled session is waiting to be scored; when one is
 (after ``value.service.run_hour_et``), it gathers the plain data ``src/value/`` may not fetch
-itself (``scripts/value_feed.py``) and runs the night. Idles when the ruleset check fails.
+itself (``scripts/value_feed.py``: earnings dates, news volume, market facts) and runs the
+night, its §7.1 re-evaluations included. Idles when the ruleset check fails.
 Runs until SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.
 
 The only module that will import ``src.value_ai`` (Part 4). Never import this file: check it
@@ -17,7 +18,13 @@ import logging
 import signal
 import threading
 
-from scripts.value_feed import FactsCache, NightRetry, earnings_dates
+from scripts.value_feed import (
+    FactsCache,
+    NightRetry,
+    earnings_dates,
+    news_volume,
+    recent_earnings,
+)
 from src.common.config import get_config
 from src.common.logging import setup_logging
 from src.value.service import plan_run, run_nightly, startup_check
@@ -39,7 +46,13 @@ def _tick() -> None:
     log.info("value: scoring %d names for %s", len(plan.names), plan.as_of)
     try:
         facts = _facts.get(plan.as_of, plan.fetch_names, workers)
-        run_nightly(plan, facts=facts, earnings=earnings_dates(plan.as_of))
+        run_nightly(
+            plan,
+            facts=facts,
+            earnings=earnings_dates(plan.as_of),
+            recent_earnings=recent_earnings(plan.as_of, plan.positions),
+            news=news_volume(sorted(plan.positions)),
+        )
     except Exception:
         n = _retry.failed(plan.as_of)
         level = logging.CRITICAL if n >= _retry.critical_after else logging.ERROR
```

- [ ] **Step 5: Run the tests and the probes**

  Run: `.venv/bin/python -m pytest -q tests/test_value_feed.py tests/test_value_service.py tests/test_value_fence.py tests/test_news_fence.py tests/test_web_fence.py tests/test_eval_skills.py`
  Expected: PASS (`test_value_feed.py` 9, `test_value_service.py` 11, `test_value_fence.py` 15).
  `.venv/bin/python -m py_compile scripts/run_value.py scripts/value_feed.py` silent; ruff
  check/format on the six files and `.venv/bin/mypy src/value/service.py scripts/value_feed.py
  scripts/run_value.py` clean. **Red runs to record:** add `import src.engine.risk_engine` to
  `src/value/reevaluate.py` → the fence fails; remove it.

- [ ] **Step 6: Commit**

  ```bash
  git add src/value/service.py scripts/value_feed.py scripts/run_value.py tests/test_value_feed.py tests/test_value_service.py tests/test_value_fence.py
  git commit -m "feat(value): earnings dates, news volume and the regime step reach the night; the fences cover Part 3"
  ```

---

### Task 9: The report — re-evaluated against original

**Files:** Modify `src/value/report.py`, `scripts/value_report.py`, `tests/test_value_report.py`

**Interfaces:**
- Consumes: `ValueReevaluationRow`, the `plan` columns (Task 6).
- Produces: `LegView.plan`, `EventView.plan` (default `main`); `ReevaluationView(shadow_id,
  list_name, severity, kinds)`; `reevaluation_section(legs, reevaluations, rebases) -> list[str]`;
  `render(..., reevaluations=None, rebases=0)`. The policy section and postmortems read the main
  plan only.

The pinned numbers: two closed `full` pairs, re-evaluated −5% and +2% against original −12% and
+2%: means −1.5% vs −5.0%, so re-evaluation saved 3.5% an entry.

- [ ] **Step 1: Write the failing tests** — apply to `tests/test_value_report.py`:

```diff
diff --git a/tests/test_value_report.py b/tests/test_value_report.py
index ec8da2f..9961806 100644
--- a/tests/test_value_report.py
+++ b/tests/test_value_report.py
@@ -1,5 +1,6 @@
-"""The shadow record's report (value book spec §6.8, §7, §11, §12): clustered errors, the go-live
-line, the three policies side by side, the ranked record, postmortems, and the script."""
+"""The shadow record's report (value book spec §6.8, §7, §7.1, §11, §12): clustered errors, the
+go-live line, the three policies side by side, the re-evaluations against the original plan, the
+ranked record, postmortems, and the script."""
 
 from __future__ import annotations
 
@@ -16,15 +17,18 @@ from src.value.report import (
     EventView,
     LegView,
     RankedView,
+    ReevaluationView,
     closest_gate,
     clustered_mean,
     go_live_line,
     postmortem,
     ranked_section,
+    reevaluation_section,
     render,
 )
 from src.value.scorecard import build_scorecard
 from src.value.store import (
+    ValueReevaluationRow,
     ValueShadowEventRow,
     ValueShadowLegRow,
     ValueShadowRow,
@@ -98,6 +102,55 @@ def test_the_ranked_section_shows_each_bucket_and_the_spread() -> None:
     assert "no month closed yet" in "\n".join(ranked_section([]))
 
 
+def test_the_reevaluation_section_sets_each_policys_plan_against_the_original() -> None:
+    """Spec §7.1: the shadow ledger carries the position twice from the first trigger, so the
+    report can say whether re-evaluation saved money or only churned. Two closed full pairs:
+    re-evaluated -5% and +2% vs original -12% and +2%: re-evaluation saved 3.5% an entry."""
+
+    def leg(i: int, policy: str, plan: str, ret: float | None) -> LegView:
+        return LegView(shadow_id=i, policy=policy, plan=plan, closed=ret is not None, ret=ret)
+
+    legs = [
+        leg(1, "full", "main", -0.05),
+        leg(1, "full", "original", -0.12),
+        leg(2, "full", "main", 0.02),
+        leg(2, "full", "original", 0.02),
+        leg(1, "value", "main", None),
+        leg(1, "value", "original", None),
+    ]
+    reevals = [
+        ReevaluationView(shadow_id=1, list_name="deep_value", severity="major", kinds=["move"]),
+        ReevaluationView(
+            shadow_id=2, list_name="deep_value", severity="minor", kinds=["earnings", "filing"]
+        ),
+    ]
+    text = "\n".join(reevaluation_section(legs, reevals, rebases=3))
+    assert "2 re-evaluation(s), 1 major; triggers earnings 1, filing 1, move 1; 3 rebase(s)" in text
+    assert "full     2 closed pair(s): re-evaluated -1.5% vs original -5.0%" in text
+    assert "re-evaluation saved +3.5% an entry" in text
+    assert "value    no entry with both plans closed yet" in text
+    assert "none yet; 0 rebase(s)" in "\n".join(reevaluation_section([], [], 0))
+
+
+def test_the_policy_section_reads_the_main_plan_only() -> None:
+    entries = [_entry(1, D1, 0.05)]
+    legs = [
+        LegView(shadow_id=1, policy="value", closed=True, ret=0.1, spy_ret=0.0, sessions=5),
+        LegView(shadow_id=1, policy="value", plan="original", closed=True, ret=-0.3, sessions=5),
+    ]
+    text = render(
+        entries,
+        legs,
+        [],
+        [],
+        fair_values_now={},
+        live_policy="value",
+        track="baseline",
+        postmortems=False,
+    )
+    assert "value (live)         closed 1/1  return +10.0%" in text
+
+
 def test_the_gate_closest_to_wrong_is_the_passing_check_with_least_room() -> None:
     card = build_scorecard(inputs(), get_config().value)
     deep = closest_gate(card, "deep_value")
@@ -227,3 +280,25 @@ def test_the_script_reads_value_db_and_prints_the_record(value_db, capsys) -> No
     assert SURVIVORSHIP in out
     assert "[baseline · deep_value · ready] 1 entries" in out
     assert "## STDY deep_value #1" in out and "2026-01-07 fill 100% @ 33.00" in out
+    assert "-- Re-evaluations (spec §7.1" in out and "none yet; 0 rebase(s)" in out
+    with value_session() as s:
+        s.add(
+            ValueReevaluationRow(
+                shadow_id=1,
+                symbol="STDY",
+                list_name="deep_value",
+                session=D2,
+                last_session=D2,
+                severity="major",
+                triggers_json='[{"kind": "move"}]',
+                plan_before_json="{}",
+                plan_after_json="{}",
+                verdict_at_entry="READY",
+                ruleset_version="v3",
+                ruleset_hash="x",
+                created_at=datetime(2026, 1, 6),
+            )
+        )
+        s.add(ValueShadowEventRow(shadow_id=1, policy="all", day=D3, kind="rebase"))
+    assert value_report.main([]) == 0
+    assert "1 re-evaluation(s), 1 major; triggers move 1; 1 rebase(s)" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_report.py`
  Expected: FAIL — `ImportError: cannot import name 'ReevaluationView'`.

- [ ] **Step 3: The report** — apply to `src/value/report.py`:

```diff
diff --git a/src/value/report.py b/src/value/report.py
index 974c789..84a02e6 100644
--- a/src/value/report.py
+++ b/src/value/report.py
@@ -3,8 +3,9 @@
 ``scripts/value_report.py`` reads value.db and hands plain views in. Returns are measured at
 fixed horizons on every entry, marked to market, with standard errors clustered by entry date
 (spec §12); the three exit policies side by side on the same READY entries (spec §7); the
-ranked monthly record (spec §6.8); and a postmortem per closed position (spec §11). The report
-proves nothing on its own: it is what a human reads before any go-live decision.
+ranked monthly record (spec §6.8); a postmortem per closed position (spec §11); and (Part 3) the
+re-evaluations of §7.1 with the re-evaluated plan beside the original one. The report proves
+nothing on its own: it is what a human reads before any go-live decision.
 """
 
 from __future__ import annotations
@@ -50,6 +51,7 @@ class EntryView(BaseModel):
 class LegView(BaseModel):
     shadow_id: int
     policy: str
+    plan: str = "main"  # main | original (the twin carried untouched from the first trigger)
     closed: bool
     exit_date: date | None = None
     ret: float | None = None
@@ -62,6 +64,7 @@ class LegView(BaseModel):
 class EventView(BaseModel):
     shadow_id: int
     policy: str
+    plan: str = "main"
     day: date
     kind: str
     price: float | None = None
@@ -69,6 +72,13 @@ class EventView(BaseModel):
     detail: str = ""
 
 
+class ReevaluationView(BaseModel):
+    shadow_id: int
+    list_name: str
+    severity: str
+    kinds: list[str] = Field(default_factory=list)
+
+
 class RankedView(BaseModel):
     formed_on: date
     list_name: str
@@ -188,7 +198,7 @@ def policy_section(entries: list[EntryView], legs: list[LegView], live_policy: s
     groups: dict[tuple[str, str], list[LegView]] = defaultdict(list)
     for leg in legs:
         e = by_id.get(leg.shadow_id)
-        if e is not None:
+        if e is not None and leg.plan == "main":
             groups[(e.list_name, leg.policy)].append(leg)
     if not groups:
         return [*lines, "  no READY entries yet"]
@@ -210,6 +220,44 @@ def policy_section(entries: list[EntryView], legs: list[LegView], live_policy: s
     return lines
 
 
+def reevaluation_section(
+    legs: list[LegView], reevaluations: list[ReevaluationView], rebases: int
+) -> list[str]:
+    """Spec §7.1, "measured like everything else": how often each trigger fired, and per policy
+    the re-evaluated plan against the original one on the entries that have both, closed."""
+    lines = ["-- Re-evaluations (spec §7.1; the original plan carried beside the re-evaluated) --"]
+    if not reevaluations:
+        return [*lines, f"  none yet; {rebases} rebase(s) of a split or a dividend adjustment"]
+    kinds: dict[str, int] = defaultdict(int)
+    for r in reevaluations:
+        for k in r.kinds:
+            kinds[k] += 1
+    major = sum(1 for r in reevaluations if r.severity == "major")
+    lines.append(
+        f"  {len(reevaluations)} re-evaluation(s), {major} major; triggers "
+        + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items()))
+        + f"; {rebases} rebase(s)"
+    )
+    pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
+    main = {(g.shadow_id, g.policy): g for g in legs if g.plan == "main"}
+    for twin in (g for g in legs if g.plan == "original"):
+        m = main.get((twin.shadow_id, twin.policy))
+        if m is not None and m.ret is not None and twin.ret is not None:
+            pairs[twin.policy].append((m.ret, twin.ret))
+    for policy in sorted({g.policy for g in legs if g.plan == "original"}):
+        done = pairs.get(policy, [])
+        if not done:
+            lines.append(f"  {policy:<8} no entry with both plans closed yet")
+            continue
+        saved = mean(a - b for a, b in done)
+        lines.append(
+            f"  {policy:<8} {len(done)} closed pair(s): re-evaluated {_pct(mean(a for a, _ in done))}"
+            f" vs original {_pct(mean(b for _, b in done))}: re-evaluation "
+            f"{'saved' if saved > 0 else 'cost'} {_pct(abs(saved))} an entry"
+        )
+    return lines
+
+
 def ranked_section(rows: list[RankedView]) -> list[str]:
     """Top tenth, bottom tenth and the whole scored universe per list, month by month (spec
     §6.8): the decile test of whether the method picks better companies."""
@@ -279,7 +327,7 @@ def postmortem(
         f" now {fair_value_now}",
     ]
     for leg in sorted(legs, key=lambda g: g.policy):
-        mine = [e for e in events if e.policy == leg.policy]
+        mine = [e for e in events if e.policy == leg.policy and e.plan == leg.plan]
         story = "; ".join(
             f"{e.day} {e.kind}"
             + (f" {e.fraction:.0%} @ {e.price:.2f}" if e.kind == "fill" and e.price else "")
@@ -314,6 +362,8 @@ def render(
     live_policy: str,
     track: str,
     postmortems: bool,
+    reevaluations: list[ReevaluationView] | None = None,
+    rebases: int = 0,
 ) -> str:
     versions = sorted({e.ruleset_version for e in entries})
     lines = [
@@ -325,6 +375,8 @@ def render(
         "",
         *policy_section(entries, legs, live_policy),
         "",
+        *reevaluation_section(legs, reevaluations or [], rebases),
+        "",
         *ranked_section(ranked),
     ]
     if postmortems:
@@ -333,7 +385,7 @@ def render(
         for e in closed:
             lines += postmortem(
                 e,
-                [g for g in legs if g.shadow_id == e.id],
+                [g for g in legs if g.shadow_id == e.id and g.plan == "main"],
                 [v for v in events if v.shadow_id == e.id],
                 fair_values_now.get((e.symbol, e.list_name)),
             )
```

  …and to `scripts/value_report.py`:

```diff
diff --git a/scripts/value_report.py b/scripts/value_report.py
index 69685fc..b3f0376 100644
--- a/scripts/value_report.py
+++ b/scripts/value_report.py
@@ -6,20 +6,31 @@
 Reads data/value.db (select only; on a new install it first creates the empty tables) and
 prints: the survivorship caveat, the
 go-live line of spec §12, fixed-horizon returns against SPY with errors clustered by entry date,
-the three exit policies side by side, the ranked monthly record and, with ``--postmortems``, one
-postmortem per closed position. No IBKR connection, no network.
+the three exit policies side by side, the re-evaluations of §7.1 (the re-evaluated plan against the
+original), the ranked monthly record and, with ``--postmortems``, one postmortem per closed
+position. No IBKR connection, no network.
 """
 
 from __future__ import annotations
 
 import argparse
+import json
 
-from sqlalchemy import select
+from sqlalchemy import func, select
 
 from src.common.config import get_config
-from src.value.report import HORIZONS, EntryView, EventView, LegView, RankedView, render
+from src.value.report import (
+    HORIZONS,
+    EntryView,
+    EventView,
+    LegView,
+    RankedView,
+    ReevaluationView,
+    render,
+)
 from src.value.store import (
     ValueRankedRow,
+    ValueReevaluationRow,
     ValueShadowEventRow,
     ValueShadowLegRow,
     ValueShadowRow,
@@ -64,6 +75,7 @@ def load(args: argparse.Namespace) -> str:
             LegView(
                 shadow_id=g.shadow_id,
                 policy=g.policy,
+                plan=g.plan,
                 closed=g.closed,
                 exit_date=g.exit_date,
                 ret=g.ret_exit,
@@ -79,6 +91,7 @@ def load(args: argparse.Namespace) -> str:
             EventView(
                 shadow_id=v.shadow_id,
                 policy=v.policy,
+                plan=v.plan,
                 day=v.day,
                 kind=v.kind,
                 price=v.price,
@@ -102,6 +115,21 @@ def load(args: argparse.Namespace) -> str:
             for r in s.scalars(select(ValueRankedRow).order_by(ValueRankedRow.formed_on))
             if not args.ruleset or r.ruleset_version == args.ruleset
         ]
+        reevaluations = [
+            ReevaluationView(
+                shadow_id=r.shadow_id,
+                list_name=r.list_name,
+                severity=r.severity,
+                kinds=[t["kind"] for t in json.loads(r.triggers_json)],
+            )
+            for r in s.scalars(select(ValueReevaluationRow))
+            if r.shadow_id in ids
+        ]
+        rebases = s.scalar(
+            select(func.count())
+            .select_from(ValueShadowEventRow)
+            .where(ValueShadowEventRow.kind == "rebase", ValueShadowEventRow.shadow_id.in_(ids))
+        )
         now: dict[tuple[str, str], float | None] = {}
         for f in s.scalars(select(ValueTickerFileRow)):
             now[(f.symbol, "deep_value")] = f.fair_value_deep
@@ -115,6 +143,8 @@ def load(args: argparse.Namespace) -> str:
         live_policy=vcfg.rules.exits.live_policy,
         track=args.track,
         postmortems=args.postmortems,
+        reevaluations=reevaluations,
+        rebases=int(rebases or 0),
     )
 
 
```

- [ ] **Step 4: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_report.py tests/test_value_shadow.py tests/test_value_fence.py`
  Expected: PASS (`test_value_report.py` 10). `py_compile scripts/value_report.py` silent; ruff
  check/format and `.venv/bin/mypy src/value/report.py scripts/value_report.py` clean.

- [ ] **Step 5: Commit, then the section's Progress-log commit**

  ```bash
  git add src/value/report.py scripts/value_report.py tests/test_value_report.py
  git commit -m "feat(value): the report sets the re-evaluated plan against the original"
  ```

  Then the **Section C exit** full gate, Task 9's row, and
  `git commit -m "docs(plan): value book Part 3 Progress log - Section C"` (the plan alone).

---

## Section D — Stage 1b and the docs (Tasks 10–12) · model: sonnet · effort: medium

Stage 1b (spec §12): Python's rules scored point in time on the first session of each month,
READY entries marked at 21/63/126 sessions against SPY and the ranked tenths held a month, printed
under its caveats. Then the doc sweep.

**Spec to read:** §6.2 (point-in-time honesty), §12 (all), §17 (the Stage 1b sentence), §18.

**Files the subagent reads:** this section; `src/value/report.py` (the sections it reuses),
`src/value/rank.py`, `src/value/ranked.py`, `src/value/gates.py` (`edgar_shares`),
`src/common/value_inputs.py` (`build_value_financials`, `build_price_series`, `read_bars`,
`read_payload`), `tests/value_fixtures.py`, `src/data/yfinance_backend.py` (lines 23–45),
`tests/test_data_providers.py` (lines 253–268), `scripts/value_report.py` (the script pattern), and
for Task 12 the four docs at the anchors its entry check greps.

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **D1. Section C landed.** Tasks 7–9 ticked; record the commit count (12 if nothing else).
- [ ] **D2. Green, from the worktree root.** pytest = baseline + 52, `ruff check .`, `mypy src`.
- [ ] **D3. The code and docs Section D edits are where this plan says.** Each prints the line
  shown:

  ```bash
  grep -n '^    return "5y"$' src/data/yfinance_backend.py                                   # 45:
  grep -n '^            (999, "5y"),$' tests/test_data_providers.py                          # 262:
  grep -n "^data/value_keep_fresh.json.tmp$" .gitignore                                     # 55:
  grep -n "^| \*\*Value book Parts 3–6\*\* |" STATUS.md                                    # 346:
  grep -n "^## Built (2026-10-29 — value book Part 2: the value process and the shadow record)$" STATUS.md   # 350:
  grep -n "^## 19. The value book, Parts 1–2" SETUP.md                                      # 2034:
  grep -n "^- Parts 1–2 place, size and gate nothing" CLAUDE.md                             # 409:
  grep -n "^### \`src/value/\` — The value book" ARCHITECTURE.md                            # 1218:
  grep -n "^12\. \*\*The value fence\.\*\*" ARCHITECTURE.md                                # 1763:
  ```

**Section exit:** three more task commits plus the section's `docs(plan)` commit; full gate green
with pytest = baseline + 59 (52 + 4 + 3); `.venv/bin/python -m py_compile scripts/run_value.py
scripts/value_feed.py scripts/value_report.py scripts/value_backtest.py scripts/value_dry_run.py`
silent; protected-file diff empty. Record the commit count.

---

### Task 10: Stage 1b — the point-in-time backtest

**Files:** Create `src/value/backtest.py`, `tests/test_value_backtest.py`

**Interfaces:**
- Consumes: `report.horizon_section`, `ranked_section`, `clustered_mean`, `EntryView`,
  `RankedView`, `SURVIVORSHIP`, `HORIZONS`, `GO_LIVE_HORIZON`; `rank_list`, `rs_cutoff`, `buckets`,
  `equal_weight_return`; `build_value_financials`, `build_price_series`; `gates.edgar_shares`.
- Produces: `BacktestName(symbol, sector, industry)`, `BacktestResult`, `CAVEATS`,
  `formation_dates(sessions, start, end)`, `next_periodic_filing(payload, after)`,
  `price_at(bars, spy, as_of)`, `inputs_at(name, payload, price, as_of, cfg, cutoff)`,
  `slim(card)`, `forward_returns(bars, spy, signal)`, `run(names, *, bars, spy, load_payload, dates,
  cfg, version, digest, score=build_scorecard) -> BacktestResult`, `render(result) -> str`.
  Frames are `read_bars`-shaped: lower-case `open, high, low, close, volume`, a `date` index.

The pinned numbers: ten names at 20, 22, … 38 (deep value READY for S0–S7, quality growth for all),
two formations (2025-02-03, 2025-03-03); only S0 moves, 20 to 22 from the February entry on. So
16 deep-value entries over two dates with one at +10%: a mean excess of 0.625%, and with two
clusters whose residual sums are +5% and −5% the clustered SE is 0.625% too, t = 1.00. The February
deep-value top tenth (S0 alone) returns +10%, the whole list +1%.

- [ ] **Step 1: Write the failing tests** — create `tests/test_value_backtest.py`:

```python
"""Stage 1b (value book spec §12): the point-in-time backtest of Python's rules."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.common.config import get_config
from src.value import backtest as bt
from src.value.scorecard import build_scorecard
from tests.value_fixtures import companyfacts, inputs

CFG = get_config().value
SESSIONS = [d.date() for d in pd.bdate_range("2025-01-01", periods=180)]


def frame(closes: list[float], opens: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "open": opens or closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1e6] * n,
        },
        index=pd.Index(SESSIONS[:n]),
    )


def test_formations_are_each_months_first_session_in_the_window() -> None:
    got = bt.formation_dates(SESSIONS, date(2025, 2, 1), date(2025, 4, 30))
    assert got == [date(2025, 2, 3), date(2025, 3, 3), date(2025, 4, 1)]


def test_inputs_are_the_filings_and_prices_as_they_stood() -> None:
    """Spec §6.2: on 2024-06-03 only the 10-Ks filed by then exist (FY2021-FY2023, the last on
    2024-02-10); the next one, filed 2025-02-10, stands in for the earnings date; the market-cap
    cross-check reads EDGAR's own count (FY2023's 102 million diluted shares) x the close."""
    payload = companyfacts()
    days = [d.date() for d in pd.bdate_range("2023-01-02", "2024-06-28")]
    bars = pd.DataFrame(
        {"open": 30.0, "high": 30.5, "low": 29.5, "close": 30.0, "volume": 1e6},
        index=pd.Index(days),
    )
    spy = bars.copy()
    as_of = date(2024, 6, 3)
    price = bt.price_at(bars, spy, as_of)
    assert price is not None and price.as_of == as_of
    got = bt.inputs_at(
        bt.BacktestName("STDY", "Information Technology", "Application Software"),
        payload,
        price,
        as_of,
        CFG,
        None,
    )
    assert got.financials is not None and len(got.financials.annual) == 3
    assert got.financials.latest_filed == date(2024, 2, 10)
    assert got.next_earnings == date(2025, 2, 10)
    assert got.yf_market_cap == pytest.approx(102e6 * 30.0)
    assert got.regime == "normal"
    card = build_scorecard(got, CFG)
    assert card.data_quality == "unknown"  # three annual periods then, five needed: honest
    assert bt.next_periodic_filing(payload, date(2026, 3, 1)) is None
    assert bt.next_periodic_filing(None, date(2026, 3, 1)) is None


def test_forward_returns_enter_at_the_next_open_and_mark_against_spy() -> None:
    closes = [20.0] * 24 + [22.0] * 156  # 2025-02-03 is SESSIONS[23], the entry SESSIONS[24]
    opens = [20.0] * 25 + [22.0] * 155
    name = frame(closes, opens)
    spy = frame([500.0] * 100 + [510.0] * 80)
    entry, px, rets, spys = bt.forward_returns(name, spy, date(2025, 2, 3))
    assert (entry, px) == (SESSIONS[24], 20.0)
    assert rets == {21: pytest.approx(0.10), 63: pytest.approx(0.10), 126: pytest.approx(0.10)}
    assert spys == {21: 0.0, 63: 0.0, 126: pytest.approx(0.02)}  # SESSIONS[150] is past 100
    short = frame(closes[:60], opens[:60])  # the name's bars stop: later horizons stay unmarked
    _, _, rets, _ = bt.forward_returns(short, spy, date(2025, 2, 3))
    assert rets[21] == pytest.approx(0.10) and rets[63] is None and rets[126] is None
    assert bt.forward_returns(name, spy, SESSIONS[-1]) == (None, None, {}, {})


def test_a_run_scores_each_formation_records_ready_entries_and_the_ranked_record() -> None:
    """Ten names, two formations (2025-02-03 and 2025-03-03). S0 is the cheapest, so it tops
    both lists, and the only one that moves: 20 to 22 from the February entry on."""
    names = [bt.BacktestName(f"S{i}") for i in range(10)]
    price = {f"S{i}": 20.0 + 2 * i for i in range(10)}
    bars = {s: frame([p] * 180) for s, p in price.items()}
    bars["S0"] = frame([20.0] * 24 + [22.0] * 156, [20.0] * 25 + [22.0] * 155)
    spy = frame([500.0] * 180)
    cards = {s: build_scorecard(inputs(symbol=s, close=p), CFG) for s, p in price.items()}
    loaded: list[str] = []
    dates = bt.formation_dates(SESSIONS, date(2025, 2, 1), date(2025, 3, 31))
    result = bt.run(
        names,
        bars=bars,
        spy=spy,
        load_payload=lambda s: loaded.append(s) or None,
        dates=dates,
        cfg=CFG,
        version="v3",
        digest="x",
        score=lambda i, cfg: cards[i.symbol],
    )
    assert loaded == [f"S{i}" for i in range(10)]  # one payload per name, not per date
    assert result.scored == 20 and len(result.dates) == 2
    s0 = [e for e in result.entries if e.symbol == "S0" and e.list_name == "deep_value"]
    assert [(e.signal_date, e.entry_date, e.entry_price) for e in s0] == [
        (date(2025, 2, 3), SESSIONS[24], 20.0),
        (date(2025, 3, 3), SESSIONS[44], 22.0),
    ]
    assert s0[0].returns[21] == pytest.approx(0.10) and s0[1].returns[21] == pytest.approx(0.0)
    assert {e.symbol for e in result.entries if e.list_name == "deep_value"} == {
        f"S{i}" for i in range(8)
    }  # S8 and S9 are WAIT on deep value
    feb = {(r.list_name, r.bucket): r for r in result.ranked if r.formed_on == date(2025, 2, 3)}
    assert feb[("deep_value", "top")].n == 1 and feb[("deep_value", "top")].ret == pytest.approx(
        0.10
    )
    assert feb[("deep_value", "all")].ret == pytest.approx(0.01)  # 10% on one name of ten
    assert feb[("deep_value", "top")].spy_ret == 0.0
    march = [r for r in result.ranked if r.formed_on == date(2025, 3, 3)]
    assert march and all(r.closed_on is None and r.ret is None for r in march)
    text = bt.render(result)
    assert text.splitlines()[0].startswith("== Value book Stage 1b: point-in-time backtest")
    assert "! Prices carry yfinance's survivorship bias" in text
    # 16 deep-value entries over two dates, one of them +10%: a mean of 0.625%; the clustered
    # SE is 0.625% too (two clusters, residual sums +5% and -5%), so t = 1.00.
    assert "deep_value      n 16 (2 dates) mean excess +0.6% t 1.00: the rules beat SPY" in text
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_backtest.py`
  Expected: FAIL — `ImportError: cannot import name 'backtest' from 'src.value'`.

- [ ] **Step 3: The backtest** — create `src/value/backtest.py`:

```python
"""Stage 1b (spec §12): a point-in-time backtest of Python's rules. No I/O of its own:
``scripts/value_backtest.py`` hands in the bars, the raw companyfacts payloads (read-only, one
name at a time) and the frozen config.

On the first session of each month in the window every name is scored as it stood then: filings
first filed on or before that day (``select_periods(as_of=)``), bars up to its close, the run's
own relative-strength line. A READY verdict enters at the next session's open, exactly as the
shadow record does, and is marked at 21/63/126 sessions against SPY; the ranked record's top
tenth, bottom tenth and whole list are held to the next formation. The report is
``src/value/report.py``'s, under the caveats below. Claude is never backtested (spec §12).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src.common.config import ValueCfg
from src.common.value_inputs import build_price_series, build_value_financials
from src.common.value_types import Classification, PriceSeries, ValueInputs
from src.value import gates
from src.value.rank import rank_list, rs_cutoff
from src.value.ranked import BUCKETS, buckets, equal_weight_return
from src.value.report import (
    GO_LIVE_HORIZON,
    HORIZONS,
    SURVIVORSHIP,
    EntryView,
    RankedView,
    clustered_mean,
    horizon_section,
    ranked_section,
)
from src.value.schemas import LISTS, ListEvaluation, ValueScorecard
from src.value.scorecard import build_scorecard

TRACK = "backtest"
PERIODIC_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")
CAVEATS = (
    SURVIVORSHIP,
    "The universe is today's snapshot: names that left the index (failed, acquired, demoted) "
    "are missing, a second survivorship bias on top of the prices'.",
    "Earnings dates are not known point-in-time: the next 10-Q/10-K's filing date stands in, and "
    "it follows the release, so the earnings window errs late.",
    "The market-cap cross-check (spec §6.3) has no historical yfinance value: EDGAR's own count "
    "times the price stands in, so it always passes.",
    "The regime is taken as normal throughout (no point-in-time regime record): the required "
    "margins are the normal regime's.",
    "Classification (sector, industry) is today's.",
    "Claude cannot be backtested (its training data holds the outcomes): this is Python's "
    "baseline only.",
)


@dataclass(frozen=True, slots=True)
class BacktestName:
    symbol: str
    sector: str | None = None
    industry: str | None = None


@dataclass(slots=True)
class BacktestResult:
    version: str
    digest: str
    dates: list[date]
    names: int
    scored: int = 0  # scorecards whose data quality passed
    entries: list[EntryView] = field(default_factory=list)
    ranked: list[RankedView] = field(default_factory=list)


Scorer = Callable[[ValueInputs, ValueCfg], ValueScorecard]


def formation_dates(sessions: Iterable[date], start: date, end: date) -> list[date]:
    """The first session of each month within [start, end]."""
    out: list[date] = []
    for day in sorted(sessions):
        if start <= day <= end and (
            not out or (day.year, day.month) != (out[-1].year, out[-1].month)
        ):
            out.append(day)
    return out


def next_periodic_filing(payload: dict | None, after: date) -> date | None:
    """The first 10-Q/10-K filed after *after* in the payload: the earnings-date stand-in."""
    best: date | None = None
    for taxonomy in ((payload or {}).get("facts") or {}).values():
        for concept in (taxonomy or {}).values():
            for entries in ((concept or {}).get("units") or {}).values():
                for e in entries or []:
                    raw = e.get("filed") if isinstance(e, dict) else None
                    if e.get("form") not in PERIODIC_FORMS or not isinstance(raw, str):
                        continue
                    filed = date.fromisoformat(raw)
                    if filed > after and (best is None or filed < best):
                        best = filed
    return best


def _cut(bars: pd.DataFrame, as_of: date) -> pd.DataFrame:
    return bars[bars.index <= as_of]


def price_at(bars: pd.DataFrame, spy: pd.DataFrame, as_of: date) -> PriceSeries | None:
    return build_price_series(_cut(bars, as_of), _cut(spy, as_of))


def inputs_at(
    name: BacktestName,
    payload: dict | None,
    price: PriceSeries | None,
    as_of: date,
    cfg: ValueCfg,
    cutoff: float | None,
) -> ValueInputs:
    """One name as it stood on *as_of* (the caveats say what stands in for what is unknown)."""
    stale = cfg.rules.data_quality.stale_item_days
    fin = (
        None
        if payload is None
        else build_value_financials(payload, as_of=as_of, stale_item_days=stale)
    )
    draft = ValueInputs(
        symbol=name.symbol,
        as_of=as_of,
        financials=fin,
        price=price,
        classification=Classification(
            sector=name.sector,
            industry=name.industry,
            source="snapshot" if name.industry else "none",
        ),
        next_earnings=next_periodic_filing(payload, as_of),
        regime="normal",
        rs_cutoff_6m=cutoff,
    )
    shares = gates.edgar_shares(draft)
    cap = shares * price.close if shares and price is not None else None
    return draft.model_copy(update={"yf_market_cap": cap})


def slim(card: ValueScorecard) -> ValueScorecard:
    """What the backtest keeps of a scorecard: the verdicts and what the rank score reads."""
    lists = {
        k: ListEvaluation(
            list_name=ev.list_name,
            entry=ev.entry,
            fair_value=ev.fair_value,
            required_mos_pct=ev.required_mos_pct,
            margin_of_safety=ev.margin_of_safety,
            verdict=ev.verdict,
        )
        for k, ev in card.lists.items()
    }
    return card.model_copy(update={"lists": lists, "data_quality_checks": [], "adjustments": []})


def _open_or_close(row: pd.Series) -> float:
    o = row.get("open")
    return float(row["close"]) if o is None or pd.isna(o) else float(o)


def forward_returns(
    bars: pd.DataFrame, spy: pd.DataFrame, signal: date
) -> tuple[date | None, float | None, dict[int, float | None], dict[int, float | None]]:
    """Entry at the open of the name's first session after *signal* (SPY must have that
    session too); horizon h is the close of the h-th SPY session after the entry session, the
    name's close on or before it (None once the name's bars stop before it)."""
    after = [d for d in bars.index if d > signal]
    if not after or after[0] not in spy.index:
        return None, None, {}, {}
    entry = after[0]
    px, spy_px = _open_or_close(bars.loc[entry]), _open_or_close(spy.loc[entry])
    sessions = [d for d in spy.index if d >= entry]
    rets: dict[int, float | None] = {}
    spys: dict[int, float | None] = {}
    last = bars.index[-1]
    for h in HORIZONS:
        if len(sessions) <= h or last < sessions[h]:
            rets[h] = spys[h] = None
            continue
        mark = sessions[h]
        close = float(_cut(bars, mark)["close"].iloc[-1])
        rets[h] = close / px - 1.0
        spys[h] = float(spy.loc[mark]["close"]) / spy_px - 1.0
    return entry, px, rets, spys


def run(
    names: list[BacktestName],
    *,
    bars: dict[str, pd.DataFrame],
    spy: pd.DataFrame,
    load_payload: Callable[[str], dict | None],
    dates: list[date],
    cfg: ValueCfg,
    version: str,
    digest: str,
    score: Scorer = build_scorecard,
) -> BacktestResult:
    """Two passes, so only one payload is held at a time: the run's relative-strength line per
    date from every name's prices, then each name scored on every date."""
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    cutoffs = {
        d: rs_cutoff(
            [price_at(bars.get(n.symbol, empty), spy, d) for n in names],
            cfg.rules.timing.rs_bottom_pct,
        )
        for d in dates
    }
    cards: dict[date, list[ValueScorecard]] = {d: [] for d in dates}
    for n in names:
        frame = bars.get(n.symbol, empty)
        payload = load_payload(n.symbol)
        for d in dates:
            price = price_at(frame, spy, d)
            cards[d].append(slim(score(inputs_at(n, payload, price, d, cfg, cutoffs[d]), cfg)))
    out = BacktestResult(version=version, digest=digest, dates=dates, names=len(names))
    entry_id = 0
    for k, d in enumerate(dates):
        out.scored += sum(1 for c in cards[d] if c.data_quality == "pass")
        for c in cards[d]:
            for list_name in LISTS:
                if c.verdict_for(list_name) != "READY":
                    continue
                entry, px, rets, spys = forward_returns(bars.get(c.symbol, empty), spy, d)
                entry_id += 1
                ev = c.lists[list_name]
                out.entries.append(
                    EntryView(
                        id=entry_id,
                        track=TRACK,
                        kind="ready",
                        list_name=list_name,
                        symbol=c.symbol,
                        universe="backtest",
                        status="closed" if entry else "void",
                        signal_date=d,
                        entry_date=entry,
                        entry_price=px,
                        fair_value=ev.fair_value,
                        margin_of_safety=ev.margin_of_safety,
                        ruleset_version=version,
                        returns=rets,
                        spy=spys,
                    )
                )
        end = dates[k + 1] if k + 1 < len(dates) else None
        for list_name in LISTS:
            picked = buckets({s: e.score for s, e in rank_list(cards[d], list_name).items()})
            if picked is None:
                continue
            for bucket in BUCKETS:
                members = picked[bucket]
                ret = spy_ret = None
                missing = 0
                if end is not None:
                    start_px = _closes(bars, members, d)
                    end_px = _closes(bars, members, end)
                    ret, missing = equal_weight_return(members, start_px, end_px)
                    s0, s1 = _close(spy, d), _close(spy, end)
                    spy_ret = s1 / s0 - 1.0 if s0 and s1 else None
                out.ranked.append(
                    RankedView(
                        formed_on=d,
                        list_name=list_name,
                        bucket=bucket,
                        n=len(members),
                        closed_on=end,
                        ret=ret,
                        spy_ret=spy_ret,
                        missing=missing,
                    )
                )
    return out


def _close(frame: pd.DataFrame, day: date) -> float | None:
    return float(frame.loc[day]["close"]) if day in frame.index else None


def _closes(bars: dict[str, pd.DataFrame], symbols: list[str], day: date) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in symbols:
        c = _close(bars[s], day) if s in bars else None
        if c is not None:
            out[s] = c
    return out


def render(result: BacktestResult) -> str:
    """The backtest's report: the caveats first, then the shadow report's sections."""
    span = f"{result.dates[0]}..{result.dates[-1]}" if result.dates else "no dates"
    lines = [
        f"== Value book Stage 1b: point-in-time backtest of value_rules {result.version} "
        f"({result.digest}) ==",
        f"{result.names} names, {len(result.dates)} monthly formations {span}, "
        f"{result.scored} scorecards with data quality passing",
        *(f"! {c}" for c in CAVEATS),
        "",
        *horizon_section(result.entries),
        "",
        *ranked_section(result.ranked),
        "",
        f"-- Spec §12: do the rules lose to SPY? ({GO_LIVE_HORIZON}-session excess, READY) --",
    ]
    for list_name in LISTS:
        points = [
            (
                e.entry_date,
                (e.returns.get(GO_LIVE_HORIZON) or 0.0) - (e.spy.get(GO_LIVE_HORIZON) or 0.0),
            )
            for e in result.entries
            if e.list_name == list_name
            and e.entry_date is not None
            and e.returns.get(GO_LIVE_HORIZON) is not None
            and e.spy.get(GO_LIVE_HORIZON) is not None
        ]
        s = clustered_mean(points)
        if s.mean is None:
            lines.append(f"  {list_name:<15} no marked entries")
            continue
        t = "n/a" if s.t is None else f"{s.t:.2f}"
        verdict = "the rules beat SPY" if s.mean > 0 else "the rules lose to SPY: do not go live"
        lines.append(
            f"  {list_name:<15} n {s.n} ({s.clusters} dates) mean excess {s.mean * 100:+.1f}% "
            f"t {t}: {verdict}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_backtest.py tests/test_value_fence.py`
  Expected: PASS (4 + the fence). ruff check/format and `.venv/bin/mypy src/value/backtest.py` clean.

- [ ] **Step 5: Commit**

  ```bash
  git add src/value/backtest.py tests/test_value_backtest.py
  git commit -m "feat(value): Stage 1b, the point-in-time backtest of Python's rules"
  ```

---

### Task 11: The backtest script and ten years of bars

**Files:** Create `scripts/value_backtest.py`; modify `src/data/yfinance_backend.py` (line 45),
`tests/test_data_providers.py` (line 262), `.gitignore` (after line 55),
`tests/test_value_backtest.py` (append)

**Interfaces:**
- Consumes: Task 10's `run`, `render`, `formation_dates`, `BacktestName`.
- Produces: `python -m scripts.value_backtest [--universe evidence|trading] [--names A,B]
  [--limit N] [--start D] [--end D] [--bars provider|research] [--refresh] [--out F]`;
  `provider_bars(symbols, *, cache, refresh, fetch)`, `research_bars(symbols, as_of)`,
  `load_payload(symbol)`, `main(argv, *, fetch) -> int` (2 when the ruleset is not frozen or SPY has
  no bars); `_period_for_lookback(3660) == "10y"`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_value_backtest.py`:

```python
def test_provider_bars_are_cached_and_normalised(tmp_path) -> None:
    from scripts import value_backtest as script

    calls: list[str] = []

    def fetch(symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        idx = pd.DatetimeIndex(["2025-01-02", "2025-01-03"], name="Date")
        return pd.DataFrame(
            {
                "Open": [1.0, 2.0],
                "High": [1.5, 2.5],
                "Low": [0.5, 1.5],
                "Close": [1.2, 2.2],
                "Volume": [10, 20],
                "Dividends": [0, 0],
            },
            index=idx,
        )

    first = script.provider_bars(["MU"], cache=tmp_path, fetch=fetch)
    assert list(first["MU"].columns) == ["open", "high", "low", "close", "volume"]
    assert list(first["MU"].index) == [date(2025, 1, 2), date(2025, 1, 3)]
    again = script.provider_bars(["MU"], cache=tmp_path, fetch=fetch)
    assert calls == ["MU"] and again["MU"]["close"].tolist() == [1.2, 2.2]
    script.provider_bars(["MU"], cache=tmp_path, fetch=fetch, refresh=True)
    assert calls == ["MU", "MU"]
    empty = script.provider_bars(["NONE"], cache=tmp_path, fetch=lambda s: pd.DataFrame())
    assert empty == {} and not (tmp_path / "NONE.csv").exists()


@pytest.fixture()
def research(tmp_path, monkeypatch):
    import json
    from datetime import datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import src.common.value_inputs as vi
    from src.research.store.models import Base, CompanyFactsRawRow, DailyBarRow, SymbolRow

    path = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001"))
        s.add(
            CompanyFactsRawRow(
                cik="0000000001",
                payload_json=json.dumps(companyfacts()),
                fetched_at=datetime(2026, 1, 1),
            )
        )
        for d in pd.bdate_range("2024-01-01", "2025-12-31").date:
            for sym, px in (("STDY", 30.0), ("SPY", 500.0)):
                s.add(
                    DailyBarRow(symbol=sym, date=d, open=px, high=px, low=px, close=px, volume=1e6)
                )
        s.commit()
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(path))
    vi.reset_engine()
    yield path
    vi.reset_engine()


def test_the_script_runs_read_only_on_research_bars(research, capsys) -> None:
    from scripts import value_backtest as script

    argv = ["--bars", "research", "--names", "STDY", "--start", "2025-06-01", "--end", "2025-06-30"]
    assert script.main(argv) == 0
    out = capsys.readouterr().out
    assert "1 names, 1 monthly formations 2025-06-02..2025-06-02" in out
    assert out.index("! Prices carry") < out.index("-- Fixed horizons")


def test_the_script_refuses_a_ruleset_that_is_not_frozen(monkeypatch, capsys) -> None:
    from scripts import value_backtest as script

    monkeypatch.setattr(get_config().value, "ruleset_version", "v2")  # v2's pin, v3's rules
    assert script.main(["--bars", "research", "--names", "STDY"]) == 2
    assert "frozen" in capsys.readouterr().out
```

  …and apply to `tests/test_data_providers.py`:

```diff
diff --git a/tests/test_data_providers.py b/tests/test_data_providers.py
index 1d34633..604791f 100644
--- a/tests/test_data_providers.py
+++ b/tests/test_data_providers.py
@@ -260,6 +260,8 @@ class TestYFinancePriceProviderGoldenMaster:
             (400, "2y"),  # BulkPriceProvider's documented default lookback (Task 4.1)
             (730, "2y"),
             (999, "5y"),
+            (1830, "5y"),
+            (3660, "10y"),  # the value book's Stage 1b backtest
         ]
         for lookback, expected in cases:
             ticker = _make_ticker(history_df=pd.DataFrame())
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_backtest.py tests/test_data_providers.py`
  Expected: FAIL — `ImportError: cannot import name 'value_backtest' from 'scripts'` and
  `3660→10y`.

- [ ] **Step 3: The period, the cache's ignore line, the script** — apply to
  `src/data/yfinance_backend.py`:

```diff
diff --git a/src/data/yfinance_backend.py b/src/data/yfinance_backend.py
index a814440..07a84a0 100644
--- a/src/data/yfinance_backend.py
+++ b/src/data/yfinance_backend.py
@@ -42,7 +42,9 @@ def _period_for_lookback(lookback_days: int) -> str:
         return "1y"
     if lookback_days <= 730:
         return "2y"
-    return "5y"
+    if lookback_days <= 1830:
+        return "5y"
+    return "10y"  # the value book's Stage 1b backtest (scripts/value_backtest.py)
 
 
 class YFinancePriceProvider:
```

  …to `.gitignore`:

```diff
diff --git a/.gitignore b/.gitignore
index 7cdbbac..c0d6325 100644
--- a/.gitignore
+++ b/.gitignore
@@ -53,6 +53,7 @@ data/watchdog_state.json
 data/sentiment_history.json
 data/value_keep_fresh.json
 data/value_keep_fresh.json.tmp
+data/value_backtest/
 data/backups/
 # Daily credit spreads: the ThetaData cache (licensed market data), exported trade CSVs, the halt switch
 data/spreads_bt/
```

  …and create `scripts/value_backtest.py` (importable: no side effect at import, `main` behind the
  `__main__` guard):

```python
"""Stage 1b: the point-in-time backtest of Python's value rules (spec §12), printed for a human.

    python -m scripts.value_backtest [--universe evidence|trading] [--names A,B] [--limit N]
        [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--bars provider|research] [--refresh]
        [--out entries.json]

Filings come from the raw companyfacts payloads already in ``data/research.db``, opened read-only
one name at a time (``select_periods(as_of=)``: what was first filed by each date). Prices: with
``--bars provider`` (the default) ten years of daily bars from the bulk price provider, cached in
``data/value_backtest/`` (``--refresh`` refetches); with ``--bars research`` the ~2 years
research.db already holds (no network). The frozen ruleset is the one scored. Writes nothing but
the cache and ``--out``; no IBKR, no Telegram, no value.db. The caveats print first.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.common import value_inputs as vi
from src.common.config import ROOT, get_config
from src.common.value_universe import build_value_universe
from src.value import backtest as bt
from src.value.ruleset import ruleset_id

log = logging.getLogger(__name__)

LOOKBACK_DAYS = 3660  # ten years: the provider's 10y period
CACHE_DIR = ROOT / "data" / "value_backtest"
WARMUP_DAYS = 400  # calendar days of bars before the first formation (210 sessions and SMA200)
FORWARD_DAYS = 190  # calendar days after the last formation (126 sessions to mark)
COLUMNS = ["open", "high", "low", "close", "volume"]

Fetch = Callable[[str], pd.DataFrame]


def _provider_fetch(symbol: str) -> pd.DataFrame:
    from src.data.factory import get_bulk_price_provider

    return get_bulk_price_provider().get_daily_bars(symbol, lookback_days=LOOKBACK_DAYS)


def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
    """The provider's ``Open..Volume`` frame as ``read_bars``'s: lower-case, a date index."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=COLUMNS)
    frame = raw.rename(columns=str.lower)[COLUMNS].astype(float)
    frame.index = pd.Index([pd.Timestamp(i).date() for i in raw.index])
    return frame.sort_index()


def provider_bars(
    symbols: list[str],
    *,
    cache: Path = CACHE_DIR,
    refresh: bool = False,
    fetch: Fetch = _provider_fetch,
) -> dict[str, pd.DataFrame]:
    """Ten years of bars per symbol, from the cache unless *refresh* or absent."""
    cache.mkdir(parents=True, exist_ok=True)
    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        path = cache / f"{symbol}.csv"
        if path.exists() and not refresh:
            frame = pd.read_csv(path, index_col=0)
            frame.index = pd.Index([date.fromisoformat(str(d)[:10]) for d in frame.index])
        else:
            frame = _normalise(fetch(symbol))
            if not frame.empty:
                frame.to_csv(path)
        if not frame.empty:
            out[symbol] = frame
    return out


def research_bars(symbols: list[str], as_of: date) -> dict[str, pd.DataFrame]:
    """The bars research.db already holds (read-only), up to *as_of*."""
    out: dict[str, pd.DataFrame] = {}
    with vi.research_read() as rs:
        if rs is None:
            return out
        for symbol in symbols:
            frame = vi.read_bars(rs, symbol, as_of)
            if not frame.empty:
                out[symbol] = frame
    return out


def load_payload(symbol: str) -> dict | None:
    with vi.research_read() as rs:
        return None if rs is None else vi.read_payload(rs, symbol)[1]


def _names(args: argparse.Namespace) -> list[bt.BacktestName]:
    from src.common.universe import effective_universe

    u = build_value_universe(get_config().value, effective_universe())
    pool = u.trading if args.universe == "trading" else u.evidence
    if args.names:
        pool = [s.strip().upper() for s in args.names.split(",") if s.strip()]
    pool = [s for s in pool if s not in u.etfs]
    if args.limit:
        pool = pool[: args.limit]
    return [bt.BacktestName(s, *u.classification.get(s, (None, None))) for s in pool]


def main(argv: list[str] | None = None, *, fetch: Fetch = _provider_fetch) -> int:
    parser = argparse.ArgumentParser(description="Stage 1b: the value rules, point in time")
    parser.add_argument("--universe", default="evidence", choices=("evidence", "trading"))
    parser.add_argument("--names", default=None, help="comma-separated symbols instead")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--bars", default="provider", choices=("provider", "research"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    cfg = get_config().value
    try:
        version, digest = ruleset_id(cfg)
    except ValueError as exc:
        print(f"value_backtest: {exc}")
        return 2
    names = _names(args)
    symbols = [n.symbol for n in names]
    if args.bars == "research":
        bars = research_bars([*symbols, "SPY"], date.today())
    else:
        bars = provider_bars([*symbols, "SPY"], refresh=args.refresh, fetch=fetch)
    spy = bars.pop("SPY", None)
    if spy is None or spy.empty:
        print("value_backtest: no SPY bars")
        return 2
    sessions = list(spy.index)
    start = args.start or sessions[0] + timedelta(days=WARMUP_DAYS)
    end = args.end or sessions[-1] - timedelta(days=FORWARD_DAYS)
    dates = bt.formation_dates(sessions, start, end)
    result = bt.run(
        names,
        bars=bars,
        spy=spy,
        load_payload=load_payload,
        dates=dates,
        cfg=cfg,
        version=version,
        digest=digest,
    )
    print(bt.render(result))
    if args.out:
        args.out.write_text(
            json.dumps([e.model_dump(mode="json") for e in result.entries], indent=1),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_backtest.py tests/test_data_providers.py tests/test_value_fence.py`
  Expected: PASS (`test_value_backtest.py` 7). `py_compile scripts/value_backtest.py` silent; ruff
  check/format and `.venv/bin/mypy scripts/value_backtest.py src/data/yfinance_backend.py` clean.
  **Do not run the script against the live `research.db` or fetch real bars here** (ruling 22: the
  operator runs it after the merge).

- [ ] **Step 5: Commit**

  ```bash
  git add scripts/value_backtest.py src/data/yfinance_backend.py tests/test_data_providers.py .gitignore tests/test_value_backtest.py
  git commit -m "feat(value): scripts/value_backtest.py with ten years of cached bars"
  ```

---

### Task 12: Docs

**Files:** `ARCHITECTURE.md`, `SETUP.md`, `STATUS.md`, `CLAUDE.md` (the mandatory doc-update
table: new modules under `src/value/` and `src/research/ingest/` → ARCHITECTURE folder guide and the
CLAUDE value fence; new config keys → the committed example (Task 1) and ARCHITECTURE `config/`; a
new script → SETUP scripts table and ARCHITECTURE `scripts/`; features built → STATUS). `README.md`,
`docs/web/*`, `How the scan works.md`, `UNIVERSE_RESEARCH.md` and `.opencode/` are unchanged
(ruling 23) — record that as a ruling.

- [ ] **Step 1: ARCHITECTURE.md** — apply:

```diff
diff --git a/ARCHITECTURE.md b/ARCHITECTURE.md
index 9795705..de26984 100644
--- a/ARCHITECTURE.md
+++ b/ARCHITECTURE.md
@@ -584,7 +584,7 @@ what ships) and given a code default. The table below names the files by their p
 | `spreads.yaml` (private) / `examples/spreads.yaml` (committed) | **Daily credit spreads** (docs/superpowers/plans/2026-10-07-daily-credit-spreads.md), typed as `SpreadsCfg` in `src/common/config.py`. `enabled` (ships `false`), `mode` (`shadow` records simulated, cost-realistic fills; `paper` places real combo orders on the paper account), the traded underlying (`SPY`, read as a stock) and GEX source (`gex.symbol: SPX`, `SPXW` dailies, × the live SPY/SPX ratio when `scale_to_underlying` is `null`), `book_underlyings` (must not appear in `universe.yaml` — refused at load), `max_market_data_lines` (30), `reserved_monitor_lines` (20), `order_ref_prefix` (`CS:`; the service also spots its own still-working orders by it), the ET `schedule` (map 09:31, entries 09:35–13:30, time stop 15:45), `entry` (the trigger: `move` = sell only after a move of 0.5–1.5 × the day's expected move that has stalled 10 minutes, one side; `always` = the original every-check rule; `gap_day_pct` tag), `gex.negative_gamma_action` (`allow` = traded and tagged; `skip`), `selection` (width, delta cap, expected-move multiple, wall buffer, minimum credit), `risk` (sizing from the book's own capital: `starting_capital_usd` plus realized P&L, with per-trade/total/daily loss as shares of it, a `max_contracts` ceiling; trades per day, `one_side_per_day`, excess-liquidity floor, `events` with an optional `until` time, `ex_dividend_dates`), `exits` (profit take, stop, strike touch, `max_hold_minutes`, `let_expire` off for SPY), `execution` (price ladder, shadow slippage, commission), `selection.menu_size` (the pick menu: one strike inside the baseline pick, the pick, up to two further out), `ai` (Claude picks from the gate-approved menu: `enabled` ships `false`; per-call `brief_model`/`brief_effort` and `pick_model`/`pick_effort`, default Opus/high; `fallback_model`/`fallback_effort` (default `claude-sonnet-5-5`/`high`), one retry on a `cli_error` such as an Opus usage limit, inside the same timeout and only with 15 s or more left, with the model actually used recorded on the call and split out as a `--compare` condition (`""` disables it); `pick_timeout_seconds` 45, which must be shorter than an entry check; `max_pick_calls_per_day` 4 (pick decisions; a fallback retry is not counted separately); `max_headlines`; `workdir`, the cwd for `claude -p`, default `~/.cache/ibkr-spreads-ai`: outside the repo, because `claude -p` walks up from its cwd and would load the project `CLAUDE.md`; `~` is expanded, a relative path resolves under the repo root and is not recommended) and `backtest` (ThetaData). The isolation checks run at every config load: `book_underlyings` may never appear in `universe.yaml`, and with `enabled: true` `market_data.chain_batch_size + max_market_data_lines + reserved_monitor_lines` (40 + 30 + 20) must stay ≤ `market_data.max_concurrent_lines` (90) — `reserved_monitor_lines` is the wheel monitor's standing lines — and `ibkr.client_ids.spreads` (30) must exist. A missing private file falls back to the example. `ai.ollama_fallback` (default true): Ollama answers the picker when the Claude calls fail. |
 | `news.yaml` (private) / `examples/news.yaml` (committed) | **The News thread** (docs/superpowers/specs/2026-10-09-news-thread-design.md, SETUP.md §17), typed as `NewsCfg` in `src/common/config.py`. `enabled` (ships `true`; the service idles when false), `db_url` (`data/news.db`), `charts_dir`, `retention_days` (30), per-category `lookback_hours`, `source_rank` (preferred outlets for a card's primary link), tape symbol lists; `sources` (RSS feed list with a category each, Google News macro queries, poll cadences, the Nasdaq date-key offsets `nasdaq_econ_date_offset_days` (1, re-derived by `scripts.news_probe`) / `nasdaq_earnings_date_offset_days`, `finnhub_per_minute`); `cluster` (Jaccard `similarity` 0.5 within `window_hours` 48, on title tokens minus template words); `tagging` (rumor / forward-looking term lists, topic keyword lists, manual ticker `aliases`, `noise_terms` — law-firm class-action solicitations kept out of ticker cards, writer headlines and digests); `alerts` (`macro_max_late_minutes` 180 — a print first seen later than that after release is not alerted, index levels, VIX jump/levels, held/universe σ thresholds, breaking-news `geo_min_sources`/`geo_reaction_pct`/`geo_reaction_window_min`/`geo_topics`, `max_per_hour` 6, `max_edits` 3); `reaction` (`window_min` 15, `max_wait_min` 35, RTH and extended-hours instrument maps); `quiet_hours` (Asia/Singapore 00:00–07:00, validated tz and HH:MM); `digests` (ET times, validated; `max_late_minutes` 120 — a digest missed by more than that while the service was down is skipped, not posted stale); `llm` (`backend` `cli`/`ollama`/`cli_then_ollama`, `model`, `ollama_model`, `timeout_seconds`, `max_calls_per_day` 44, `reserved_for_picture` 10 — see the market-picture keys below); `sentiment` (`model` `vader`/`finbert`, `lookback_hours`, `half_life_hours`); `grounding.rel_tol`; `flags` thresholds; `briefs` (`poll_seconds`, `dedupe_minutes`). **Market picture build (2026-10-22), keys with code defaults (a private `news.yaml` needs `llm.max_calls_per_day: 44` if it spells out its `llm:` line, since a file that says 40 keeps 40; the `dossier:`, `triage:` and `picture:` blocks have code defaults identical to the example, so copying them is for visibility and tuning):** `llm.reserved_for_picture` (10) keeps that many of the day's calls for triage and picture builds: general calls (card writer, digests, briefs) stop at `max_calls_per_day - reserved_for_picture - dossier.max_calls_per_day` (30 of 44 at the shipped values; never below one a day); `triage` (`enabled`, `batch_size` 40, `rth_batch_times` 10:30 / 12:30 / 14:30 ET, and the noise-check keys `promote_index_move_pct` 1.0, `promote_ticker_residual_pct` 3.0, `promote_window_min` 60, `max_promotions_per_hour` 2); `picture` (`enabled`, `max_rebuilds_per_day` 4, `max_stories` 5, `story_window_days` 7, `story_min_new_clusters` 2, `story_match_jaccard` 0.3, `staleness_hours` 26); `dossier` (`enabled`, `batch_size` 6 names per call, `max_calls_per_day` 4, `facts_refresh_min` 60, `prose_min_interval_hours` 6, `profile_days` 7, `story_window_days` 7, `max_event_days` 45, `staleness_hours` 26, `max_names_in_review` 8, `keep_days` 30, `health` with the debt-to-equity bands `de_strong` 100 and `de_weak` 200 in yfinance's percent unit). A disabled dossier hands its four calls back to the general budget. Nothing in it reaches the risk engine, scoring or sizing. **Research touches (2026-10-27):** `dossier.touch_enabled` (true), `dossier.researched_min_interval_min` (180), `dossier.touch_keep_days` (3) and `picture.touch_min_age_min` (90) — a /scan or a Claude review of a name makes its dossier due early (and the picture, once old enough), still under the daily caps. |
 | `news_playbook.yaml` (committed reference data) | The 📘 playbook: per US release (FOMC, CPI, core CPI, NFP, core PCE, PCE, unemployment, average hourly earnings, PPI, GDP, retail sales, ISM, claims, JOLTS, UoM) its title `aliases`, `tolerance` for in-line, `inverse` (a lower print is "hot"), and the textbook first-reaction direction of stocks/bonds/dollar/gold/oil/vol on a hot and on a cold print, with a one-line rationale each. Loaded by `src/news/playbook.py`; not operator tuning, so not private. |
-| `value.yaml` | The value book (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`). The `rules:` block (data quality, the classification lists, the health thresholds for operating companies, cyclicals, banks and insurers, valuation rates, the quality-growth entry rule, the margin of safety by regime, timing) is hashed into the ruleset fingerprint beside `ruleset_version`; changing a rule after the freeze is a version bump. Since v2 the `rules:` block also holds `exits` (the three exit policies' thresholds and the pre-registered `live_policy`). Also the universe snapshots, the ticker-file history bands, `research_sweep.enabled` (the research worker's nightly value sweep: filings, and every name's bars plus SPY's each session; on since Part 2) and `service` (the value process: run hour, poll interval, yfinance workers, the filings-coverage gate). Every model forbids unknown keys. |
+| `value.yaml` | The value book (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`). The `rules:` block (data quality, the classification lists, the health thresholds for operating companies, cyclicals, banks and insurers, valuation rates, the quality-growth entry rule, the margin of safety by regime, timing) is hashed into the ruleset fingerprint beside `ruleset_version`; changing a rule after the freeze is a version bump. Since v2 the `rules:` block also holds `exits` (the three exit policies' thresholds and the pre-registered `live_policy`). Also the universe snapshots, the ticker-file history bands, `research_sweep.enabled` (the research worker's nightly value sweep: filings, and every name's bars plus SPY's each session; on since Part 2) and `service` (the value process: run hour, poll interval, yfinance workers, the filings-coverage gate). Since v3 (Part 3) `rules:` also holds `reevaluation` (spec §7.1: the residual model's z bars, windows and raw-move backstop, the sector→ETF map, the Major and Minor 8-K items, the news-volume multiple, the regime states, the quiet days, the debounce, the down-shock ATR multiple). Every model forbids unknown keys. |
 | `value_universe.csv` / `value_evidence_universe.csv` | Committed snapshots of the S&P 100 (the value book's trading universe, with `universe.yaml`'s `would_own` + `watchlist`) and the S&P 500 (its evidence universe): symbol, name, GICS sector and sub-industry, CIK, with the as-of date on line 1. Rebuilt by `python -m scripts.value_universe_snapshot`. |
 | `symbol_directory_overrides.yaml` | **2026-09-13.** A hand-maintained `overrides:` list of `{symbol, name, exchange, is_etf}` for tickers SEC EDGAR's directory omits entirely — verified directly against both `company_tickers.json` and `company_tickers_exchange.json`, neither lists `TQQQ`/`SOXL`/`UPRO` (share classes of a shared trust CIK, not individually-registered filers), which is why the web research console's `GET /research/search` couldn't find them despite all three being part of the live scan universe (`universe.yaml → leveraged_etfs`). No `cik` field — there isn't one to give them. Loaded by `src/research/ingest/symbols.py::refresh_symbol_directory`, which seeds a row only when the symbol has no directory row yet (never overwrites EDGAR-sourced data). Read directly with `yaml.safe_load`, not through `get_config()` — it's a data supplement, not a tunable. |
 
@@ -630,7 +630,7 @@ in ``src/ibkr/market_data.py`` still calls ``yfinance`` directly and is out of s
 | `finnhub_backend.py` | **News thread.** `FinnhubClient` for the free tier (personal use, 60/min; a client-side token bucket keeps it at `news.sources.finnhub_per_minute`, 50): `company_news` (headline, summary, image), `general_news`, `earnings_calendar` (timing, EPS/revenue estimates **and actuals**, the only source of earnings actuals). The key travels only as the `token` query parameter; failures log only the exception type, since httpx messages embed the URL (httpx's own request log is pinned to WARNING in `src/common/logging.py`). |
 | `forexfactory_backend.py` | **News thread.** `ForexFactoryScheduleProvider.this_week()` — the unofficial weekly calendar JSON (title, country, ET time, impact, forecast, previous; **no actuals**, probed 2026-10-09), cached 30 min in-process behind the `forexfactory` breaker. |
 | `nasdaq_backend.py` | **News thread.** Nasdaq's undocumented calendar API with browser-like headers, behind the `nasdaq` breaker: `NasdaqEconActualsProvider.actuals(et_day)` requests `et_day + news.sources.nasdaq_econ_date_offset_days` (probed 2026-10-09: `date=D` returns ET day D−1's US releases, and the `gmt` column is ET) and maps `"&nbsp;"`/blank/`N/A` to `None`; `NasdaqEarningsProvider.on(et_day)` gives timing (`bmo`/`amc`) and consensus EPS. |
-| `edgar_backend.py` | SEC EDGAR backend: ``EdgarSymbolDirectoryProvider`` (the active ``SymbolDirectoryProvider``), ``EdgarFilingsProvider`` (the active ``FilingsProvider`` — fetches one filer's XBRL companyfacts at ``COMPANYFACTS_URL`` with the same ``EdgarClient`` as the symbol directory, CIK zero-padded to 10, returns ``(payload, etag)``; empty payload on 404/missing-XBRL/304 rather than raising), ``EdgarClient`` (rate-limited, ETag-aware JSON client — never raises on an HTTP failure, degrades to ``(None, etag)`` on a 304/429/5xx instead; retries 403/429/5xx with exponential backoff, honouring ``Retry-After`` capped at 10s; wired to the ``edgar`` circuit breaker so an open circuit returns ``(None, etag)`` without a network call), ``RateLimiter`` (thread-safe minimum-interval limiter, default under SEC's 10 req/s ceiling), and ``user_agent()`` (raises if ``SEC_CONTACT_EMAIL`` is unset — SEC blocks anonymous callers). |
+| `edgar_backend.py` | SEC EDGAR backend: ``EdgarSymbolDirectoryProvider`` (the active ``SymbolDirectoryProvider``), ``EdgarFilingsProvider`` (the active ``FilingsProvider`` — fetches one filer's XBRL companyfacts at ``COMPANYFACTS_URL`` with the same ``EdgarClient`` as the symbol directory, CIK zero-padded to 10, returns ``(payload, etag)``; empty payload on 404/missing-XBRL/304 rather than raising), ``EdgarClient`` (rate-limited, ETag-aware JSON client — never raises on an HTTP failure, degrades to ``(None, etag)`` on a 304/429/5xx instead; retries 403/429/5xx with exponential backoff, honouring ``Retry-After`` capped at 10s; wired to the ``edgar`` circuit breaker so an open circuit returns ``(None, etag)`` without a network call), ``RateLimiter`` (thread-safe minimum-interval limiter, default under SEC's 10 req/s ceiling), and ``user_agent()`` (raises if ``SEC_CONTACT_EMAIL`` is unset — SEC blocks anonymous callers). **Value book Part 3:** ``EdgarFilingsProvider.get_submissions(cik, etag=)`` (a filer's ``submissions/CIK##########.json`` feed: recent filings with form, dates, 8-K item tags) and ``get_filing_text(cik, accn, document)`` (one filing's primary document, ``""`` when unavailable), both on the ``FilingsProvider`` Protocol; ``EdgarClient._get`` is the one rate-limited, breaker-guarded GET that ``get_json`` and ``get_text`` share. |
 | `breaker.py` | Per-provider circuit breakers (M4). ``CircuitBreaker(name, threshold=3, cooldown_seconds=300.0)`` — consecutive-failure counter (not a rate), states ``closed``/``open``/``half_open``, ``allow()``/``record_success()``/``record_failure()``. ``get_breaker(name)`` returns a process-wide instance from a registry; ``breaker_states()`` snapshots every breaker's state for ``GET /health → providers``. Mirrors the existing ``market_data.max_consecutive_chain_timeouts`` pattern. An open breaker returns the documented empty value (empty dict, empty frame, empty list) **without a network call**, so the affected section renders ``UNAVAILABLE`` while every other section still renders. |
 
 ---
@@ -989,13 +989,15 @@ never take the scheduler, or every other registered job, down with it — a hear
 |---|
 | `schemas.py` | The shapes the research layer passes between its own modules: `Fact` (frozen dataclass — one XBRL fact; `start` is `None` for instant/balance-sheet facts), `LineItemValue` (one normalised line item for one period, traceable to its filing via `concept`/`accn`/`filed`/`form`), `PeriodStatement` (every line item for one period), and `NormalizedFinancials` (a filer's annual + quarterly statements). **Roll redesign (2026-10-11):** `PositionSnapshot.con_id` (from `portfolio.get_positions`), `FundamentalStats.dividend_per_share`, `RollOrigin` (the short a roll closes + its chain position) carried as `TradeCandidate.roll_from`, `RollAction`/`RollDecision` (the roll policy's answer: action, stable reason code, candidate, rejection counts, human detail), and `CloseReason.DEFENSIVE` (operator-tapped close from a roll-policy `close` card). **Web Home follow-ups (2026-10-15):** `IncomeTarget` (`off` / `fixed` / `pct_of_account` / `pct_of_amount`, validated so a stored row can never disagree with itself; `MonthPay` gained `target_mode`/`target_amount`/`target_base`), `DayTrade` with `DayFact`, `DayReview` and `DayRolledTo` (one executed trade as a Home card; money is whole-position USD and positive, unknown is `None`), and `DayCalendarDay`/`MonthCalendar` (a month of daily realised P&L). |
 | `income_target.py` | **Web Home follow-ups (2026-10-15).** The monthly income target's stored form (`system_settings.income_target`, JSON), `parse_income_target`, `resolve_income_target(stored, config_pct)` (a web row wins, an explicit `off` beats the legacy `web.monthly_income_target_pct`, nothing else is none) and `target_value(target, month_start_value)` (`None` when it cannot be worked out, never 0). Pure, so the API reads the row through its own read-only session and `src/storage/system_settings.py` writes it through the drain, both through one reading. Display only: nothing in the trading path imports it. |
-| `store/models.py` | Research-database ORM: the symbol directory (`symbols`), raw EDGAR companyfacts (`company_facts_raw` — carries an `etag` so a 304 is free on re-ingest), normalised line items (`financials` — carries `form` alongside `concept`/`accn`/`filed` so the cache can rebuild `LineItemValue` fully without a network fetch), daily bars (`daily_bars`), delayed quotes (`quotes`), news items (`news_items`), the assembled analysis cache (`analysis_cache`), deterministic check results (`check_results`), AI summaries (`summaries`), watchlists + items, recently-viewed, the ingest job queue (`ingest_jobs`), and the single-row `worker_heartbeat` (`beat_at`, `last_job`) written only on a successful job. 14 tables. |
+| `store/models.py` | Research-database ORM: the symbol directory (`symbols`), raw EDGAR companyfacts (`company_facts_raw` — carries an `etag` so a 304 is free on re-ingest), normalised line items (`financials` — carries `form` alongside `concept`/`accn`/`filed` so the cache can rebuild `LineItemValue` fully without a network fetch), daily bars (`daily_bars`), delayed quotes (`quotes`), news items (`news_items`), the assembled analysis cache (`analysis_cache`), deterministic check results (`check_results`), AI summaries (`summaries`), watchlists + items, recently-viewed, the ingest job queue (`ingest_jobs`), and the single-row `worker_heartbeat` (`beat_at`, `last_job`) written only on a successful job. 14 tables. Value book Part 3 adds `filing_index` (one row per recent 10-K/10-Q/20-F/40-F/8-K from a filer's EDGAR submissions feed: form, dates, 8-K item tags, the going-concern read) and `submissions_state` (each feed's last read and ETag); the job kinds are `fundamentals`, `prices`, `submissions` and `going_concern`. |
 | `store/session.py` | Engine + session factory for `data/research.db` (`get_research_engine`, `init_research_db`, `research_session` context manager). WAL mode + `foreign_keys=ON`, matching the trading database, so the API can read while a worker writes. `init_research_db()` also backfills columns a later milestone added to an already-existing table (`ALTER TABLE ... ADD COLUMN` against a diff of the ORM metadata vs `PRAGMA table_info`) — `create_all()` alone only creates missing tables, so a database file left over from an earlier milestone would otherwise keep the old schema and raise `OperationalError: no such column`. No migration framework in this project; this is deliberately the minimal fix. |
 | `ingest/symbols.py` | `refresh_symbol_directory() -> int` — upserts the SEC filer directory from `get_symbol_directory_provider()` into `symbols`. An upsert (not truncate-and-reload) so locally enriched columns (`sector`, `industry`, `is_etf`) survive a refresh; a failed fetch (empty list) leaves existing rows intact rather than emptying the table search depends on. Returns the provider-sourced row count only. **After** the provider upsert, it also seeds `config/symbol_directory_overrides.yaml` (2026-09-13) — a small hand-maintained list for tickers EDGAR's directory omits entirely (verified against both `company_tickers.json` and `company_tickers_exchange.json`: leveraged/inverse ETFs like `TQQQ`/`SOXL`/`UPRO`, share classes of a shared trust CIK rather than individually-registered filers, appear in neither). An override is inserted only when the symbol has no row yet from the provider or a prior run — it never overwrites one, so real EDGAR coverage always wins going forward — and carries no `cik` (there isn't one to give it) and `is_etf: true`. This step runs even when the provider fetch itself failed, since the override list has no network dependency. |
 | `ingest/concepts.py` | XBRL fact parsing and concept resolution. `LineItemSpec` (Pydantic) maps a canonical line item to an ordered list of us-gaap concept candidates and a `kind` (`duration` for start+end facts — income/cash flow, `instant` for end-only — balance sheet). `load_concept_map()` reads and caches `config/research_concepts.yaml` — adding a mapping is a config change, not a code change. `parse_facts()` skips malformed entries individually (one bad date in a filer's history must not cost the other forty facts). `resolve_line_item()` pools facts across **every** candidate concept in the list rather than stopping at the first one with any data — a filer can switch which us-gaap tag it reports a line item under between fiscal years (NVIDIA tags revenue `RevenueFromContractWithCustomerExcludingAssessedTax` for FY19-22 and `Revenues` for FY23-26; stopping at the first match used to silently drop the other tag's periods entirely), so each `Fact` now carries its own `concept` and `select_periods()`'s existing latest-`filed`-wins rule is what arbitrates the rare case where two aliases both report the same period. Returns `None` when no alias has any facts (honest absence — the caller renders UNKNOWN, never a zero). `select_periods()` picks one fact per period, newest first, with two correctness rules: `kind` is enforced (summing four quarterly durations into "total assets" produces plausible nonsense), and ties on `end` are broken by the **latest `filed`**, so a restatement becomes the current answer instead of silently reverting. `assert_units_supported()` rejects units outside `{USD, USD/shares, shares, pure}` — a EUR revenue silently treated as USD is worse than no number at all. `select_periods(..., as_of=)` keeps only facts filed on or before `as_of` (point in time, value book §6.2); `select_ttm` gives trailing twelve months as fiscal year + this year-to-date − last year's (10-Q cash flows are year-to-date). |
+| `ingest/submissions.py` | **Value book Part 3 (spec §7.1, §8.5).** The `submissions` job: `parse_submissions(payload, since=)` keeps a filer's 10-K/10-Q/20-F/40-F (and amendments) and 8-K filings of the last `KEEP_DAYS` (400) with their item tags; `ingest_submissions(symbol, cik)` upserts them into `filing_index` (ETag-reused through `submissions_state`; a 304 stamps the read; a failure raises so the drain retries). No text is read. |
+| `ingest/going_concern.py` | **Value book Part 3 (spec §7).** The `going_concern` job, for the names the shadow record holds: each unread recent periodic filing's primary document is read once (`MAX_PER_JOB` 2 a job) and `detect_going_concern` looks for a sentence that **asserts** substantial doubt about the ability to continue as a going concern ("raise(s/d)", no hedge or negation: could, may, if, whether, no, not, alleviated, evaluated…); only the flag and the sentence are stored on `filing_index`. |
 | `ingest/fundamentals.py` | `normalize(payload, symbol)` turns a companyfacts document into `NormalizedFinancials` (annual + quarterly `PeriodStatement`s, newest first); unmapped line items are absent, never zero. `load_cached_financials(symbol)` rebuilds `NormalizedFinancials` from the `financials` table alone — the **warm path**: no network, no SEC fetch, no re-normalisation. `ingest_fundamentals(symbol, cik)` is the **cold path**: fetches via `get_filings_provider()` honouring the cached ETag (a 304 reuses the cached raw payload rather than treating it as "no facts"), caches the raw payload in `company_facts_raw` (so normalisation is replayable when the concept map gains a mapping), normalises, and persists `FinancialRow`s (carrying `form` so the cache can rebuild `LineItemValue` fully) — replacing the symbol's rows wholesale so a re-ingest leaves exactly one row per (period, line item). Returns `None` when the filer has no XBRL facts (ETFs, foreign filers). |
 | `ingest/materialize.py` | Cold-tier materialisation with a wall-clock budget. `SectionState` (`ready`/`pending`/`unavailable`), `MaterializeResult`, `materialize(symbol, *, budget_seconds)` — **cache-first**: a warm view serves from `load_cached_financials` with no SEC fetch; only a cache miss calls `ingest_fundamentals` inside `research.tiers.materialization_budget_seconds` (default 8s). A finished ingest is always `READY` with its data, even if it overran the budget (a background `IngestJobRow` is queued so the *next* view is instant; `PENDING` never carries data — the old PENDING-with-data contract caused the client to poll and re-fetch indefinitely). `reason` is a fixed user-facing string, never `str(exc)` — an exception carrying a CIK or transport detail must not reach the browser. `enqueue()` deduplicates on `(symbol, kind, pending)`. `drain_ingest_jobs()` runs queued jobs, records the error and increments `attempts` on failure, and gives up at `MAX_ATTEMPTS=3` (`status=failed`). M4 adds the enrichment sections (`_technicals`/`_sentiment`/`_news`/`_quote`) each guarded by `_section()` so one outage cannot cascade — a sentiment failure leaves technicals rendering; a news outage leaves sentiment rendering; and so on. Sentiment is enrichment-tier and is never passed into technicals or fundamentals (a structural test inspects `materialize`'s source to enforce this). `_quote()` returns `(price, as_of, reason)` — `MaterializeResult.quote_as_of` carries the warm-tier `QuoteRow`'s actual capture time through to the API layer, which is what lets `GET /research/{symbol}` stamp the quote's `Sourced` value with its real age instead of the request time. M5 (Task 5.5/5.7) adds `metrics`/`checks`/`checks_state`/`checks_reason`: `_checks_metrics()` calls `get_iv_stats`/`get_fundamental_stats` (`src/analytics/`) and `build_metrics()` (`src.research.checks.metrics`) to assemble the flat metrics dict — a failure here degrades to `{}`, never a page failure — and `_checks()` (guarded by `_section()`, same as the other enrichment sources) turns that dict into a `ChecksPayload` via `build_checks_payload()`. `is_etf` is read once alongside `cik` in `materialize()` (same `SymbolRow` query) and threaded through every `_enrich()` call site, since `build_metrics` needs it to skip XBRL extraction and gate the ETF-only fund fields. **`materialize()` distinguishes "no directory row at all" from "a known symbol with no CIK"** (2026-09-13): the former (nothing search or the watchlist could ever have found) returns immediately with only `fundamentals_state=unavailable` set, same as always; the latter (e.g. an override-seeded symbol like `TQQQ` — see `ingest/symbols.py`) still marks fundamentals `unavailable`/`No SEC filer record for this symbol` but proceeds into `_enrich()`, since technicals/sentiment/news/quote/checks need a price and a symbol, never a CIK. Without this split, a symbol the override file makes searchable would still render an entirely blank stock page. `drain_ingest_jobs` runs two job kinds, `fundamentals` and `prices` (the value book's backfill and nightly sweep, 2026-10-29). |
-| `ingest/value_universe.py` | `enqueue_value_universe`: queues `fundamentals` (raw payload missing or a day old) and `prices` (fewer than 260 bars or 4+ days stale) for both value-book universes. Scheduled as the `value_sweep` cron job only when `config/value.yaml → research_sweep.enabled`. |
+| `ingest/value_universe.py` | `enqueue_value_universe`: queues `fundamentals` (raw payload missing or a day old), `submissions` (the EDGAR feed, read nightly: older than 20 hours), `prices` (fewer than 260 bars, or not yet past the last weekday: a bar dated that day may have been written while forming, review M2) and, for the names the shadow record holds (`data/value_keep_fresh.json`), `going_concern`, for both value-book universes; the benchmarks' bars ride along (`benchmark_names()`: SPY and the sector ETFs of `rules.reevaluation.sector_etfs`). Scheduled as the `value_sweep` cron job only when `config/value.yaml → research_sweep.enabled`. |
 | `ingest/prices.py` | `ingest_daily_bars(symbol) -> int` — pulls daily OHLCV from the active `BulkPriceProvider` and upserts into `daily_bars` on `(symbol, date)`. Returns 0 and **never deletes existing history** when the fetch is empty (a transient provider outage must not erase a ticker's price series). |
 | `ingest/quotes.py` | Warm-tier data: watchlisted + recently viewed symbols. `warm_symbols()` = watchlisted + recently viewed (last 7 days, via `RecentlyViewedRow` — written by `GET /research/{symbol}` in `routers/research.py`). `refresh_quotes() -> int` is guarded by `is_rth()` (no-op outside regular trading hours) and registered on a 15-min `IntervalTrigger` in `jobs.py`. A missing quote (`None`) is not a price of zero and writes no row. **On-demand single-symbol seed (2026-09-14):** `refresh_quote_for(symbol) -> bool` is `materialize()`'s cold-path counterpart to `refresh_quotes`'s periodic sweep — called from `ingest/materialize.py::_quote()` the first time a symbol with no `QuoteRow` at all is viewed, so a first-ever view doesn't sit blank for up to 15 minutes waiting on the next RTH poll. Deliberately **not** RTH-gated (a quiet-hours view should still show the last close). `change_pct` (both here and in the periodic sweep) is `_day_change_pct()`: the change versus the most recent *completed* trading session's close in `daily_bars` (via `_prior_close()`, which itself seeds `daily_bars` on demand — the same cold-path backfill the `/bars` route uses — when none exist yet), never the delta between two consecutive polls that the field used to carry (a number that drifted further from a real day change every cycle, and stayed `None` for a symbol's entire first cycle since there was no earlier poll to diff against). The **nightly warm-tier refresh** also lives here: `refresh_warm_bars(symbols=None)` re-ingests daily bars and `refresh_warm_news(symbols=None)` persists news for every warm symbol, each with per-symbol isolation (one symbol's outage never stops the rest), and `refresh_warm_tier()` runs both as one job (never raises; returns per-part counts for the log). Scheduled by `jobs.py` at `research.tiers.warm_refresh_hour_et` (default 04:00 ET) — the P0-P1 design's "warm tier — refreshed nightly," which fills `daily_bars`/`news_items` for warm names so the ticker page's chart and persisted news have data. **`book_symbols()` (2026-10-27)** = `would_own` + `actively_wheeling` from `universe.yaml`: the nightly `refresh_warm_tier` fetches **bars** for the warm tier plus these (quotes and news stay warm-tier only), so a position page opens on a current chart. `GET /research/{symbol}/bars` also refreshes a stale symbol on demand (`_bars_need_refresh`: no bars, or the newest older than the last closed session, at most every 30 min per symbol). |
 | `ingest/news.py` | `ingest_news(symbol, limit=25) -> int` and `recent_news(symbol, limit=25) -> list[dict]` — reads `get_news_provider().get_headlines`, handles both yfinance shapes (legacy flat `title` and newer `{"content": {...}}` nesting), scores each headline with the VADER helper in `src/analytics/sentiment.py`, sorts newest-first (the provider's own ordering isn't a documented contract, so this isn't relied on; an unparseable date sorts last), and upserts `NewsItemRow` deduplicated on `(symbol, url)`. Enrichment tier — never reaches the deterministic engine. |
@@ -1033,8 +1035,8 @@ outstanding).
 | `dossier_text.py` | **The one neutral rendering of a ticker dossier (2026-10-22).** `render_dossier` / `render_dossiers`: a *compact* note (about 80 words: kind and health, the story, dated events, up to three key facts) for the many names of a full-scan prompt, and a *full* note (about 220 words: adds the profile, labelled as Claude's general knowledge, every fact that fits and the 7-day news sentiment) for the one name of a deep-dive or a roll. The word budget is enforced here: facts give way first, then extra events, then extra reported figures, then the story is shortened. Figures quoted from the news print on their own line, labelled `Reported in news (not computed by the system)`, never inside the story. A dated event prints as `<id> <title> (title: Claude; date <day> found in <cluster>)`: only the date was checked against the cited news, the title is Claude's, and the line says which is which. Imports only `src.common.schemas`. |
 | `schemas.py` (market picture build, 2026-10-22) | The schemas added by the market picture build: `MarketRegime` (normal / cautious / stressed / crisis: not the per-ticker `Regime`), `RegimeInputs`, `IndexRegime`, `RegimeChange` and `RegimeState` (the persisted regime); `ScaleInZone`, `SizingNote` (how the regime, the leveraged ceiling, the ladder and Claude's cut shaped one CSP: `pre_regime_contracts`, `regime`, `per_trade_cap`, `leverage_tier`, `ceiling_kind`, `floor_lot`, `scale_in`, `bottoming` (`market` or `name`), `vrp_waived`, `claude_suggested` / `claude_reason`) and `SizingContext` (everything the sizer and the gate read), with `TradeCandidate.sizing` and `TradeCandidate.cc_breakout` (`CcBreakout`); `ClaudeReview.max_contracts` / `size_reason` / `backend`; and the news-written `MarketPicture` family (`PictureFact`, `SeasonalityView`, `PictureStory`, `NoiseSummary`, `PictureRegime`) and `TickerDossier` (with `DossierFact`, `DossierEvent` and `DossierReported`). |
 | `config.py` (market picture build, 2026-10-22) | The config classes added by the market picture build: `RegimeCfg` (with `RegimeCspCfg`, `RegimeThresholdsCfg`, `RegimeIntradayCfg`, `RegimeLadderCfg` and `RegimeBottomingCfg`), `LeveragedSizingCfg`, `ClaudeCutCfg` and `CcTimingCfg` / `CcBreakoutCfg` (all `_KeyedCfg`: an unknown key raises) read through `get_regime_cfg()`, `get_leveraged_sizing_cfg()`, `get_claude_cut_cfg()` and `get_cc_timing_cfg()`; `NewsTriageCfg`, `NewsPictureCfg`, `NewsDossierCfg` (with `NewsDossierHealthCfg`) and `NewsLlmCfg.reserved_for_picture`, whose `max_calls_per_day` code default is now 44. |
-| `value_types.py` | The value book's plain input shapes (`ValueFinancials`, `PriceSeries`, `DayBar`, `Classification`, `MarketFacts`, `ValueInputs`). Imports only pydantic, so the scorecard, the loader and (Part 6) the API share them. |
-| `value_inputs.py` | The value book's one read-only input loader: research.db opened `mode=ro` (the raw companyfacts payload through `select_periods(as_of=)` / `select_ttm`, daily bars), the regime through `load_regime_state`, fixed-window technicals through `src/analytics/technicals.py`, and `fetch_market_facts` (yfinance market cap, industry, next earnings, through `src/data`). Part 2 adds `build_day_bars` (one session at a time with its technicals, for the exit engine), `newest_bar_before`, `closes_on`, `filings_coverage` and `symbol_is_etf`. Imports no enrichment and no `src.value`. |
+| `value_types.py` | The value book's plain input shapes (`ValueFinancials`, `PriceSeries`, `DayBar` (with `high`/`low` since Part 3), `FilingEvent`, `NewsVolume`, `Classification`, `MarketFacts`, `ValueInputs`). Imports only pydantic, so the scorecard, the loader and (Part 6) the API share them. |
+| `value_inputs.py` | The value book's one read-only input loader: research.db opened `mode=ro` (the raw companyfacts payload through `select_periods(as_of=)` / `select_ttm`, daily bars), the regime through `load_regime_state`, fixed-window technicals through `src/analytics/technicals.py`, and `fetch_market_facts` (yfinance market cap, industry, next earnings, through `src/data`). Part 2 adds `build_day_bars` (one session at a time with its technicals, for the exit engine), `newest_bar_before`, `closes_on`, `filings_coverage` and `symbol_is_etf`; Part 3 `filings_between` (the filing index, trigger 4) and `going_concern_flags` (the newest read periodic filing's flag; a name with none read is absent, never "no doubt"), both empty when the research worker has not created `filing_index` yet. Imports no enrichment and no `src.value`. |
 | `value_keep_fresh.py` | The "keep fresh" list (stdlib only): `write_keep_fresh` / `read_keep_fresh` over `data/value_keep_fresh.json`. The value process writes the symbols of its pending/open shadow entries after each night; the research sweep (`value_names`) reads them so a held name that left the universe keeps getting bars and filings. The only channel between the two: no `src.value` import, no `value.db`, no `research.db` write. |
 | `value_universe.py` | The value book's trading universe (`would_own` + `watchlist` + the S&P 100 snapshot) and evidence universe (the S&P 500 snapshot), share-class aliases mapped to one ticker. |
 
@@ -1218,8 +1220,8 @@ clientId.
 ### `src/value/` — The value book (deterministic tier, its own database)
 
 The value book (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`) scores healthy
-companies against what they are worth. **Parts 1–2 (2026-10-29) are the scorecard and the
-shadow record: nothing in them can place, size or gate an order.** `src/value/` is deterministic, imports no enrichment and
+companies against what they are worth. **Parts 1–3 (2026-10-29/30) are the scorecard, the
+shadow record and its re-evaluations: nothing in them can place, size or gate an order.** `src/value/` is deterministic, imports no enrichment and
 no other system, reads `src.research` only through `ingest/concepts.py` and `schemas.py`, and is
 the only writer of `data/value.db` (its own `ValueBase`). Enforced by `tests/test_value_fence.py`.
 
@@ -1233,19 +1235,23 @@ the only writer of `data/value.db` (its own `ValueBase`). Enforced by `tests/tes
 | `valuation.py` | The fading DCF, the reverse DCF, methods A (earnings power), B (haircut DCF), C (absent until point-in-time prices exist), D (growth DCF) and justified P/TBV; fair value = median of the list's methods. |
 | `timing.py` | The earnings window, deep value's strict timing, quality growth's soft timing. |
 | `rank.py` | The cross-sectional rank score per list, the filed list, the run's relative-strength line. |
-| `store.py` | `value.db`: `value_ticker_files` (latest), `value_ticker_history` (append-only), `value_runs`; `record_run` is the one way a script logs a run. Part 2's shadow record: `value_shadow` (one hypothetical entry per READY signal or control-group name, with its 21/63/126-session returns against SPY), `value_shadow_legs` (one per entry and exit policy, the exit engine's state as JSON), `value_shadow_events` (every exit event and fill), `value_ranked` (the ranked monthly portfolios). |
+| `store.py` | `value.db`: `value_ticker_files` (latest), `value_ticker_history` (append-only), `value_runs`; `record_run` is the one way a script logs a run. Part 2's shadow record: `value_shadow` (one hypothetical entry per READY signal or control-group name, with its 21/63/126-session returns against SPY), `value_shadow_legs` (one per entry and exit policy, the exit engine's state as JSON), `value_shadow_events` (every exit event and fill), `value_ranked` (the ranked monthly portfolios). Part 3: `value_reevaluations` (one row per §7.1 re-evaluation of a shadow entry: triggers, severity, the plan before and after the session's close, the verdict at entry and now; `review_state` waits for Part 4) and a `plan` column (`main` or `original`) on the legs and events, added to an existing database by `init_value_db` (`_ADDED_COLUMNS`). |
 | `ticker_file.py` | Writes the latest row and history (a full row on any verdict, fair value, margin band or gate change; a compact row once a session); `is_fresh` compares fingerprints. |
 | `funnel.py` | The calibration dry run's pass funnel and per-name detail. |
 | `ruleset.py` | The ruleset fingerprint: `ruleset_version` + a hash of the `rules:` block; `FROZEN` pins a frozen version's hash (v1: the entry rules; v2: v1 + `rules.exits`). |
-| `exits.py` | The exit engine (spec §7), pure: one `LegState` per policy (`full`, `value` — the pre-registered live policy — and `hold12`), stepped once a session on the close; a sale fills at the next open. Every exit that would send reads Python's fair value (`full`'s peak signal and its 2 x ATR tightening included); the half-sale reads the effective one; an exit only the effective (Claude) value would fire is a `proposal`. Fair value is re-marked only on a new accession, and the static "value below 90% of the price, price under SMA50" thesis rule fires only on such a re-mark session. A leg also keeps its last stepped close for the split guard. |
+| `exits.py` | The exit engine (spec §7), pure: one `LegState` per policy (`full`, `value` — the pre-registered live policy — and `hold12`), stepped once a session on the close; a sale fills at the next open. Every exit that would send reads Python's fair value (`full`'s peak signal and its 2 x ATR tightening included); the half-sale reads the effective one; an exit only the effective (Claude) value would fire is a `proposal`. Fair value is re-marked only on a new accession, and the static "value below 90% of the price, price under SMA50" thesis rule fires only on such a re-mark session. A leg also keeps its last stepped close for the rebase. Part 3 (v3): a session's `Reeval` (from `reevaluate.plan_actions`) applies an 8-K thesis exit under every policy and, under `full` only, the down-shock stop floor and the up-shock trail arm, at the close; a going-concern doubt in the filing is a thesis exit; the F-score exit counts unknown components against it (M5); the Altman Z exit is read only when a new filing lands (M6); the effective-only proposal is noted once per episode (M14); `LegState.rebased(ratio)` scales every price level. |
+| `residuals.py` | Part 3, pure: the sector-ETF residual model of triggers 1–2 (spec §7.1): alpha and beta over the 250 aligned returns before the day, the residual's sd over the last 60, the day's z and the 5-session drift z (fitted before the drift window); too short a history leaves the raw move. |
+| `reevaluate.py` | Part 3, pure: `session_triggers` (the move, drift, earnings, filing, news, regime and quiet triggers with their severities; trigger 6 waits for Part 4's kill-triggers), `regime_stepped`, `severity`, `joins` (the three-session debounce), `plan_actions` (a Major move is a shock, a Major 8-K item a thesis exit; nothing else changes a level). |
 | `ranked.py` | The ranked monthly record's arithmetic, pure: the top and bottom tenth and the whole list, equal-weight returns with dropped members counted, the first-run-of-the-month formation. |
-| `shadow.py` | The shadow record (spec §6.8, §12): READY entries and control groups at the next session's open, the three legs, fixed-horizon returns against SPY from the bars as they stand, `rebase_needed` when a split moves the entry bar or the bar on a leg's last stepped session (more than 25%), the ranked record's formation and close. Writes `value.db`; reads `research.db` through `value_inputs`. Baseline track only until Part 4. |
-| `service.py` | The value process's nightly run: `plan_run` (a settled SPY session not yet scored, after `service.run_hour_et`, once the sweep has filings for `min_filings_coverage_pct` of the universe), `run_nightly` (score both universes, the followed names and every shadow name; persist the ticker files with a session history row; run the shadow record; log `value_runs`, all in one transaction), `startup_check`. |
-| `report.py` | The report, pure: fixed-horizon returns with errors clustered by entry date, the go-live line (spec §12), the three policies side by side, the ranked record, and a postmortem per closed position with the gate closest to wrong (spec §11). |
+| `shadow.py` | The shadow record (spec §6.8, §12): READY entries and control groups at the next session's open, the three legs, fixed-horizon returns against SPY from the bars as they stand, the ranked record's formation and close. Part 3: `rebase` multiplies every recorded price level of an entry and its legs by the ratio the provider rewrote its bars by (a split or a dividend adjustment; Part 2's `rebase_needed` entries are re-opened), and `step_legs` checks each session of a READY entry's main legs for §7.1's triggers, records `value_reevaluations`, applies the plan actions and, from the first trigger, steps an `original` twin of every leg with none; tonight's facts are read on the session dated as_of only (M1); controls are never frozen (M7); SPY's entry price is read from the bars as they stand (M8). Writes `value.db`; reads `research.db` through `value_inputs`. Baseline track only until Part 4. |
+| `service.py` | The value process's nightly run: `plan_run` (a settled SPY session not yet scored, after `service.run_hour_et`, once the sweep has filings for `min_filings_coverage_pct` of the universe), `run_nightly` (score both universes, the followed names and every shadow name; persist the ticker files with a session history row; run the shadow record; log `value_runs`, all in one transaction), `startup_check`. Part 3: `RunPlan.positions` (the open READY entries the feed reads news for), `previous_regime` (trigger 7 steps from it), and `run_nightly(recent_earnings=, news=)`. |
+| `report.py` | The report, pure: fixed-horizon returns with errors clustered by entry date, the go-live line (spec §12), the three policies side by side, the re-evaluations with each policy's re-evaluated plan against the original (Part 3), the ranked record, and a postmortem per closed position with the gate closest to wrong (spec §11). |
+| `backtest.py` | Part 3, Stage 1b (spec §12): Python's rules point in time. On the first session of each month every name is scored on the filings first filed by then and the bars up to then; READY entries are marked at 21/63/126 sessions against SPY and the ranked tenths held to the next formation, all printed by `report.py`'s sections under the caveats (survivorship twice, the earnings-date and market-cap stand-ins, a normal regime, today's classification, no Claude). No I/O of its own. |
 
 **The value process** (`scripts/run_value.py`, Part 2) holds no IBKR connection and no clientId: it
 polls `service.plan_run`, gathers what `src/value/` may not fetch through `scripts/value_feed.py`
-(earnings dates from `news.db`, read-only; yfinance market facts) and calls `run_nightly`. It
+(earnings dates and, Part 3, news volume from `news.db`, read-only; yfinance market facts) and
+calls `run_nightly`. It
 sends no message (Telegram is Part 6) and idles if the frozen ruleset no longer matches the config.
 A night that fails is retried at most once an hour per session (`NightRetry`, CRITICAL log after
 three failures) and its market facts are cached for the session (`FactsCache`), so a failure that
@@ -1602,8 +1608,9 @@ plus `logs`/`watchdog`/`autonomy`); see the `launchd.py` row below and `SETUP.md
 | `value_dry_run.py` | `python -m scripts.value_dry_run backfill\|run [...]` | The value book's calibration dry run (spec §17). `backfill` drains the research worker's own jobs for both universes in-process; `run` scores every name read-only, ranks both lists, writes the ticker files to `value.db` and prints the pass funnel, GOOGL/META/BAC/MU with every number, storage and run time. No IBKR, no Telegram. Run on database copies (`SETUP.md` §19). |
 | `value_universe_snapshot.py` | `python -m scripts.value_universe_snapshot` | Rebuilds `config/value_universe.csv` (S&P 100) and `config/value_evidence_universe.csv` (S&P 500) from Wikipedia's MediaWiki API. Review the diff before committing. |
 | `run_value.py` | `python -m scripts.run_value` | The value book's process (Part 2): no IBKR, no clientId, supervised by `scripts.start` (`value_service`, `logs/value.log`, `--no-value`). Each poll asks `src.value.service.plan_run` whether a settled session waits; runs the night with `scripts/value_feed.py`'s plain data. Never imported (it starts a service): checked with `py_compile`; the only future importer of `src.value_ai`. |
-| `value_feed.py` | (imported by `run_value.py`) | The plain data `src/value/` may not fetch: `earnings_dates` from `news.db` (read-only) and `market_facts` from yfinance; plus `NightRetry` (at most one retry an hour per session after a failed night) and `FactsCache` (market facts held per session so a retry does not refetch). |
-| `value_report.py` | `python -m scripts.value_report [--track baseline] [--universe all\|trading\|evidence] [--ruleset V] [--postmortems]` | Prints the shadow record: the survivorship caveat, the go-live line, fixed-horizon returns with clustered errors, the three exit policies, the ranked record and per-position postmortems. Reads `value.db` only. |
+| `value_backtest.py` | `python -m scripts.value_backtest [--universe evidence\|trading] [--names A,B] [--limit N] [--start D] [--end D] [--bars provider\|research] [--refresh] [--out F]` | Stage 1b (Part 3): Python's value rules point in time, printed with the caveats first. Payloads read-only from `research.db`, one name at a time; ten years of bars from the bulk provider cached in `data/value_backtest/` (or `--bars research`, no network). Writes nothing else. |
+| `value_feed.py` | (imported by `run_value.py`) | The plain data `src/value/` may not fetch: `earnings_dates` from `news.db` (read-only) and `market_facts` from yfinance; plus `NightRetry` (at most one retry an hour per session after a failed night) and `FactsCache` (market facts held per session so a retry does not refetch). Part 3: `recent_earnings` (report dates of the last fortnight, trigger 3) and `news_volume` (24-hour items against the 30-day daily median from the deterministic `news_items` columns, trigger 5). |
+| `value_report.py` | `python -m scripts.value_report [--track baseline] [--universe all\|trading\|evidence] [--ruleset V] [--postmortems]` | Prints the shadow record: the survivorship caveat, the go-live line, fixed-horizon returns with clustered errors, the three exit policies, the re-evaluations (re-evaluated vs original plan, rebases), the ranked record and per-position postmortems. Reads `value.db` only. |
 
 ---
 
@@ -1762,8 +1769,8 @@ Telegram renderer and the web page draw from.
     writer. Enforced by `tests/test_regime_fence.py`.
 12. **The value fence.** `src/value/` is deterministic: it imports no enrichment, no other system
     and no trading-path module, nothing on the trading path imports it, and it is the only writer
-    of `data/value.db`. Its scorecard and exit engine are pure functions. Parts 1–2 place no
-    order and the value process holds no IBKR connection. Enforced by
+    of `data/value.db`. Its scorecard, exit engine and re-evaluation logic are pure functions.
+    Parts 1–3 place no order and the value process holds no IBKR connection. Enforced by
     `tests/test_value_fence.py`.
 
 ---
```

- [ ] **Step 2: SETUP.md** — apply:

```diff
diff --git a/SETUP.md b/SETUP.md
index 6f4ff15..f26e730 100644
--- a/SETUP.md
+++ b/SETUP.md
@@ -2031,11 +2031,12 @@ that survived checking.
 
 ---
 
-## 19. The value book, Parts 1–2: the scorecard, the nightly process and the shadow record
+## 19. The value book, Parts 1–3: the scorecard, the nightly process, the shadow record and its re-evaluations
 
 The value book scores healthy companies against what they are worth
 (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`). Part 1 is the scorecard and
-a one-off **calibration dry run**; Part 2 adds a nightly process and the **shadow record**. Neither
+a one-off **calibration dry run**; Part 2 adds a nightly process and the **shadow record**; Part 3
+adds **re-evaluations** (spec §7.1) and **Stage 1b**, the point-in-time backtest. None of them
 places an order or sends a message.
 
 1. `cp config/examples/value.yaml config/value.yaml` (git-ignored; every key has a code default).
@@ -2046,11 +2047,12 @@ places an order or sends a message.
    `python -m scripts.value_dry_run run --report value_dry_run.txt`. It prints how many names
    fall at each gate per list, GOOGL, META, BAC and MU with every number, the raw companyfacts
    storage and the run time.
-4. `ruleset_version` is frozen at `v2` (`src/value/ruleset.py::FROZEN`: v1 = the entry rules the
-   operator froze after the dry run, v2 = v1 + `rules.exits`); a rule change is a version bump with
-   a written reason. **After pulling Part 2, refresh the private copy before restarting:**
-   `cp config/examples/value.yaml config/value.yaml` (a private file still saying v1 makes the
-   value process idle with a CRITICAL line in `logs/value.log`).
+4. `ruleset_version` is frozen at `v3` (`src/value/ruleset.py::FROZEN`: v1 = the entry rules the
+   operator froze after the dry run, v2 = v1 + `rules.exits`, v3 = v2 + `rules.reevaluation` and
+   Part 3's exit-engine rules); a rule change is a version bump with a written reason. **After
+   pulling Part 2 or Part 3, refresh the private copy before restarting:**
+   `cp config/examples/value.yaml config/value.yaml` (a private file still saying v1 or v2 makes
+   the value process idle with a CRITICAL line in `logs/value.log`).
 5. **The nightly process (Part 2).** `scripts.start` / `./ibkr restart` runs `value_service`
    (`python -m scripts.run_value`; `--no-value` skips it). With `research_sweep.enabled: true` the
    research worker fetches every value name's filings and bars at 02:00 ET (the first sweep stores
@@ -2066,6 +2068,21 @@ places an order or sends a message.
    process writes their symbols to `data/value_keep_fresh.json` (git-ignored) for the research sweep.
 6. **Read the record:** `python -m scripts.value_report` (add `--postmortems` for one postmortem per
    closed position). It proves nothing for months; spec §12 says what it can and cannot show.
+7. **Re-evaluations (Part 3).** Each night every open READY shadow entry is checked, session by
+   session, for spec §7.1's triggers: a move net of its sector ETF (XLK, XLF, ...: the research
+   sweep now fetches their bars, and every name's EDGAR filing list, each night), a five-session
+   drift, an earnings report, a 10-Q/10-K or an 8-K item, a news-volume spike, a step into a stressed
+   or crisis regime, 90 quiet days. A re-evaluation is recorded in `value_reevaluations`; a Major 8-K
+   item (1.03, 3.01, 4.02) sells every policy's shadow position; under `full` only, a shock moves the
+   stop. From the first trigger the entry also carries its **original plan** untouched, and
+   `value_report` prints whether re-evaluating saved money. Splits and dividend adjustments are
+   rebased mechanically. For the names the record holds, the research worker reads each new
+   10-K/10-Q once for a going-concern doubt the filing asserts; one is a thesis exit.
+8. **Stage 1b:** `python -m scripts.value_backtest` scores Python's rules on the first session of
+   each month over ~8 years, point in time, and prints the caveats first (survivorship, stand-ins).
+   It reads `research.db` read-only and caches ten years of bars in `data/value_backtest/`
+   (`--bars research` uses only what research.db holds; `--limit N` or `--names A,B` for a quick run).
+   The full evidence universe takes a while and fetches ~500 price histories the first time.
 
 ### Scripts
 
@@ -2076,6 +2093,7 @@ places an order or sends a message.
 | `python -m scripts.value_universe_snapshot` | Rebuilds the two committed universe CSVs from Wikipedia. |
 | `python -m scripts.run_value` | The value process. Normally started by `scripts.start` / `./ibkr restart`; `--no-value` skips it. Logs to `logs/value.log` (`./ibkr logs value`). |
 | `python -m scripts.value_report [--track baseline] [--universe all\|trading\|evidence] [--ruleset V] [--postmortems]` | Prints the shadow record from `data/value.db` (read only). |
+| `python -m scripts.value_backtest [--universe evidence\|trading] [--names A,B] [--limit N] [--start D] [--end D] [--bars provider\|research] [--refresh] [--out F]` | Stage 1b: the point-in-time backtest of Python's rules (Part 3). |
 
 ## Troubleshooting
 
```

- [ ] **Step 3: STATUS.md** — apply:

```diff
diff --git a/STATUS.md b/STATUS.md
index f86112b..9c28c1e 100644
--- a/STATUS.md
+++ b/STATUS.md
@@ -343,10 +343,45 @@ MCP so the headless `claude -p` subprocess can do ad-hoc lookups (`ib_portfolio`
 | **Live trading for the spreads system; flow-based GEX; spreads web pages** | **Deliberately not built.** `src/spreads/service.py::run()` refuses `LIVE_TRADING=true` (shadow/paper only until a separate live plan exists). Intraday flow-based GEX needs a paid vendor feed — the map uses prior-close open interest. The spreads book has no web pages beyond the ledger's Book filter; `scripts.spreads_report` and the Telegram thread are its read side. |
 | **Trade ledger web dashboard** (`/ledger`, `/ledger/trades`, `/ledger/ticker/[symbol]`, `/ledger/import`) | **Built (Tasks 13-16 of docs/superpowers/plans/2026-10-05-trade-ledger.md, on `feat/trade-ledger`).** Overview (tiles, cumulative-P&L curve, monthly bars, ticker table), the filterable trades table with CSV export and a trade panel that edits annotations (`ledger_annotate`), the per-ticker drill-down (wheel cost-basis walk, lots, dividends, every trade) and the import page (CSV upload via `ledger_import`, feed status, corporate actions with a mark-reviewed button, import history). All reads go through `GET /ledger/*`; all writes through the command queue. See `web/CLAUDE.md`/`ARCHITECTURE.md` `web/`. |
 | **Trade ledger fence test** (`tests/test_web_fence.py::test_the_trading_path_never_imports_the_ledger`, `::test_the_ledger_never_imports_the_enrichment_layer`, `::test_only_the_ledger_package_writes_the_ledger_tables`) | **Built (Task 17 Step 1).** Asserts `engine/`/`execution/`/`strategies/` never import `src.ledger` or `trade_ledger`, `src/ledger/` imports nothing from `src.claude`, and only `src/ledger/` (plus the ORM definitions in `models.py`) constructs the six ledger-table rows. `test_reporting_never_writes_anything` separately covers `trade_ledger.py`'s no-writes rule. |
-| **Value book Parts 3–6** | Re-evaluation, shock stops, the corporate-action rebase and Stage 1b; Claude as the analyst (and the Claude track of the shadow record); Stage 3 money (paper); web and Telegram (with the follow window's `last_viewed_at`, digests, review cards and a watchdog check) — the roadmap in the Part 2 plan; each part is planned after the previous one merges. |
+| **Value book Parts 4–6** | Claude as the analyst (and the Claude track of the shadow record); Stage 3 money (paper); web and Telegram (with the follow window's `last_viewed_at`, digests, review cards and a watchdog check) — the roadmap in the Part 2 plan; each part is planned after the previous one merges. |
 
 ---
 
+## Built (2026-10-30 — value book Part 3: re-evaluation and Stage 1b)
+
+Plan: `docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md`. Deterministic only: no
+order, no Claude, no Telegram, no web, no IBKR connection.
+
+- `value_rules: v3` = v2 + `rules.reevaluation`, frozen at `ad8841127029` (v1 and v2 still hash as
+  pinned once the new blocks are removed); it also versions the exit-engine code below.
+- The research worker's EDGAR `submissions` job (every value name, nightly: `filing_index` with
+  forms and 8-K items) and `going_concern` job (the shadow record's names: each new 10-K/10-Q read
+  once for an asserted doubt); the sweep also fetches SPY's and eleven sector ETFs' bars, and
+  refetches the last weekday's bar every night (M2).
+- Re-evaluation (spec §7.1) on every open READY shadow entry, every session: the sector-ETF residual
+  model (z of 3, five-session drift, a 10% raw backstop), earnings, filings and 8-K items, news
+  volume, the regime step, 90 quiet days; the three-session debounce; `value_reevaluations`; the
+  original-plan twin of each leg; shock stops under `full` only; the 8-K 1.03/3.01/4.02 and
+  going-concern thesis exits under every policy.
+- The corporate-action rebase: every recorded price level is multiplied by the ratio the provider
+  rewrote the bars by (splits and dividend adjustments alike); Part 2's `rebase_needed` entries are
+  re-opened. Controls are never frozen (M7); SPY's entry price is read on one basis (M8).
+- Exit-engine minors: tonight's facts on tonight's session only (M1), unknown F-score components
+  count against the exit (M5), Altman Z read on a new filing only (M6), the effective-only proposal
+  once per episode (M14). M11's `sys.modules` probe now loads the lazy imports.
+- Stage 1b: `src/value/backtest.py` and `scripts/value_backtest.py` (ten years of bars, cached in
+  `data/value_backtest/`; the yfinance provider gained a 10y period).
+- `value_report` prints the re-evaluations and each policy's re-evaluated vs original plan.
+- Known limitations: trigger 6 (a Claude kill-trigger near firing) waits for Part 4; the hourly RTH
+  check of triggers 1 and 4 and "pause adds" wait for held positions (Part 5); cards for Major and
+  Minor re-evaluations wait for Part 6; the residual model needs 120 aligned sessions (the 10% raw
+  move stands in before that); a single bar the provider corrects (not a corporate action) is
+  rebased too; the going-concern read is a strict sentence pattern (it can miss a doubt phrased with
+  "evaluated" or "could", by design, rather than sell on boilerplate); the backtest's caveats
+  (survivorship twice, earnings and market-cap stand-ins, a normal regime) print with it. SEC load
+  (M13): companyfacts every second night for ~520 filers (~1 GB), the submissions feed nightly
+  (~520 small JSON reads), a handful of filing documents for held names.
+
 ## Built (2026-10-29 — value book Part 2: the value process and the shadow record)
 
 Plan: `docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md`. Deterministic only: no
```

- [ ] **Step 4: CLAUDE.md** — apply:

```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index be9f433..8d220c8 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -406,7 +406,13 @@ the value book. It is **deterministic tier**:
   the value process writes `data/value_keep_fresh.json` (`src/common/value_keep_fresh.py`, stdlib
   only) after each night and the research sweep reads it. They are scored under `held:<universe>`
   and never open a new entry.
-- Parts 1–2 place, size and gate nothing: every shadow row is hypothetical. The written exception
+- Re-evaluation (Part 3, spec §7.1) is Python's: `src/value/residuals.py` and `reevaluate.py` are
+  pure, and only a Major move (a shock, `full` only) or a Major 8-K item changes a plan. News volume
+  and earnings dates arrive as plain data from `scripts/value_feed.py` and only ever open a
+  re-evaluation. The EDGAR filing list and the going-concern read are research-worker jobs
+  (`src/research/ingest/submissions.py`, `going_concern.py`); `src/value/` reads their table only
+  through `src/common/value_inputs.py`.
+- Parts 1–3 place, size and gate nothing: every shadow row is hypothetical. The written exception
   for Claude's value verdict (spec §8.2, §18) is added with Part 4.
 
 Enforced by `tests/test_value_fence.py` — keep it green.
```

- [ ] **Step 5: The full gate** (Section exit) and a re-read of the trigger table in `CLAUDE.md`
  against `git diff --stat main...HEAD`: every row that matches has its doc edited.

- [ ] **Step 6: Commit, then the section's Progress-log commit**

  ```bash
  git add ARCHITECTURE.md SETUP.md STATUS.md CLAUDE.md docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md
  git commit -m "docs: value book Part 3 - re-evaluation and Stage 1b"
  ```

  Then Task 12's row, and one command each:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-3-reevaluation.md
  git commit -m "docs(plan): value book Part 3 Progress log - Section D"
  ```

---

## Whole-branch review · model: opus · effort: high, then one sonnet fix pass · effort: high

- [ ] **R1.** Spawn one **opus** subagent with `effort: "high"`: "Review branch `feat/value-book-3`
  against `main` for correctness, using superpowers:requesting-code-review. Read the plan's
  Rulings, Global Constraints and Review Focus, the spec §§7, 7.1, 8.5, 12, 16, and
  `git diff main...HEAD`. Check: the residual model and every trigger against §7.1 and rulings
  11–13 (which sessions, `after`, tonight-only news and regime, the quiet clock, the debounce); the
  shock rules against ruling 14 transition by transition (Task 4's table): a stop never loosens,
  levels wait for the close, `full` only; that the 8-K thesis exit reaches the main plan only and
  going-concern both; the twin (created once, from the state before the trigger's session, stepped
  with no re-evaluation, kept apart by `plan` everywhere the record is read: blocking, benchmark
  fills, the report, postmortems); the rebase (the ratio's reference, every level scaled, nothing
  else, `rebase_needed` re-opened); P2-M1/M5/M6/M7/M8/M14; that one night is still one transaction;
  the research jobs (ETag, 304, retries, the 400-day window, the going-concern detector's false
  positives and negatives); the migration on a Part 2 `value.db`; the fences (nothing on the
  trading path imports `src.value`; `src/value/` opens no SEC client and reads `filing_index` only
  through `value_inputs`; news volume reads only deterministic columns; the process loads no wheel
  layer and no `ib_async`); Stage 1b's point-in-time discipline (no filing filed after the formation
  date, no bar after it, the stand-ins printed); unknown-never-zero; the v3 hash and that v3 changes
  no entry rule and no exit threshold; the docs against the code. Report Critical / Important /
  Minor findings with file:line. Do not edit."
- [ ] **R2.** Record the findings in the Progress log. Spawn one **sonnet** subagent with
  `effort: "high"` to fix every Critical and Important finding in **one** commit
  (`fix(value): whole-branch review fixes`), TDD where a finding is a behaviour, with the full gate
  green. A fix that changes a key under `rules:` moves the v3 hash: it must re-run Task 1 Step 5,
  re-pin `FROZEN["v3"]` with the new value (v3 has produced no live row yet) and say so as a ruling;
  an exit-logic fix needs no re-pin before the merge (v3 has no live row yet) but must say so.
  Minor findings are listed as deferred in the Progress log unless trivial.
- [ ] **R3.** Verify the fix commit yourself (log, status, full gate with pytest = baseline + 59 +
  the fix pass's new tests, protected diff, `py_compile` of the five scripts), then **ask the
  operator whether to merge `feat/value-book-3` into `main` and whether to push. Do neither without
  a yes.** (The main checkout sits on another branch: merge by the method the operator chooses;
  Part 2 used `git update-ref` after a fast-forward check.)

---

## Operator to-dos

**Before Part 3 starts (the orchestrator checks these at A0):**

0. Part 2's to-dos done (HANDOFF §2): the private `config/value.yaml` refreshed to v2, `./ibkr
   restart`, and a few real nights of the shadow record read (`python -m scripts.value_report`).
   At least 8 GiB free (`df -h .`).

**After the merge, before the restart:**

1. Refresh the private config: `cp config/examples/value.yaml config/value.yaml`. A private file
   still saying `ruleset_version: v2` makes the value process idle with a CRITICAL line in
   `logs/value.log` (v2's pin no longer matches rules that include `reevaluation`). If you had
   changed any key, re-apply it to the new copy (an entry-rule change is a new version: say so first).
2. Restart: `./ibkr restart` (daemons do not hot-reload). The research worker creates
   `filing_index` and `submissions_state` on start; until its first sweep reads the feeds, the value
   process sees no filings (that is safe: ruling 10).

**The first nights:**

3. The 02:00 ET sweep now also queues ~520 `submissions` jobs (small JSON reads, ~1 minute at
   EDGAR's 10 a second), the eleven sector ETFs' bars, and a `going_concern` job per held name (a
   handful of filing documents the first night, then only new 10-Ks/10-Qs). Watch `df -h .` and
   `./ibkr logs research`.
4. The first v3 night rebases every open entry once by the dividend adjustments since its entry
   (the `rebase` count in the night's summary), re-opens any `rebase_needed` entry, and starts
   recording re-evaluations: `python -m scripts.value_report` shows a "Re-evaluations" section
   (`--ruleset v3` for the v3 entries alone; v2 entries keep their tag and step under v3's code,
   ruling 1).
5. **Run Stage 1b** (spec §12 makes it mandatory before any money): a quick look first,
   `python -m scripts.value_backtest --universe trading --limit 30`, then the full evidence universe
   `python -m scripts.value_backtest --out data/value_backtest/entries.json` (it fetches ten years of
   bars for ~500 names once, ~30 MB in `data/value_backtest/`, and takes a while). Read the caveats
   first; the last block answers §12's "Stage 1b shows the rules losing to SPY".

---

## Self-review (run by the plan's author, 2026-10-30)

- **Spec coverage (Part 3's scope).** §7.1 triggers 1–5, 7, 8 → Tasks 5 (pure), 7 (per session), 8
  (plain data, the regime step); trigger 6 → Part 4 (ruling 3). Debounce and severity → Tasks 5, 7.
  "What a re-evaluation does": pause adds → Part 5; recompute → the night's scorecard, `verdict_now`
  (ruling 6); fair value only on filed data → Part 2's re-mark, unchanged; the stop never loosens and
  the shock rules under `full` only → Task 4; an 8-K 1.03/3.01/4.02 thesis exit under every policy →
  Tasks 4, 5, 7; Claude's review → Part 4; cards → Part 6; recorded in `value_reevaluations` → Tasks
  6, 7. Corporate actions rebased mechanically and recorded → Task 7. The original-plan twin and the
  report's comparison → Tasks 6, 7, 9. The fence (trigger 5 and Claude's review cannot move a stop)
  → Task 5 `test_news_or_earnings_alone_move_no_level_under_any_policy`, Task 8's fences. §7's
  going-concern thesis exit → Tasks 2, 3, 4, 7. §8.5's submissions feed and 8-K item tags, no text
  reading → Task 2. §12 Stage 1b with the survivorship caveat printed → Tasks 10, 11. §16's tests:
  every trigger on fixtures, debounce, "fair value never moves on price or news alone" (Part 2's
  test plus Task 5's), "the stop never loosens", down- and up-shock, trigger 5 alone → Tasks 4, 5;
  shock stops under `full` only, level changes wait for the close → Tasks 4, 5. §18 docs → Task 12.
- **Placeholders.** None in Tasks 1–12: every module and test is given whole or as an exact diff and
  was run green — 5239 + 59 = 5298 passed and 1 skipped, `ruff check .` clean, `ruff format
  --check` clean on every touched file, `mypy src` clean (325 files) — on a code-only scratch copy
  of `main` at `1dad9dc`, and each section's end state (after Tasks 3, 4, 6 and 7) was re-run on
  its own. The only values a run supplies are the commit counts.
- **Type consistency.** `ValueReevaluationCfg` (Task 1) is what `residuals.moves`,
  `reevaluate.*` and `shadow.process` read; `FilingEvent`/`NewsVolume` (Task 3) are what
  `session_triggers` (Task 5), `ReevalContext` (Task 7) and `value_feed.news_volume` (Task 8) carry;
  `exits.Reeval` (Task 4) is what `plan_actions` (Task 5) returns and `step` consumes;
  `ValueReevaluationRow` and `plan` (Task 6) are what `shadow.step_legs` (Task 7) and
  `value_report` (Task 9) write and read; `shadow.HELD` (Task 7) is what `service.shadow_names`
  (Task 8) reads; `report.horizon_section`/`ranked_section` are what `backtest.render` (Task 10)
  reuses.
- **Review Focus.** Each of the five lines names the test that pins it, in the task that owns the
  code.
- **Proportion.** Complete code by the operator's brief (Sonnet executors with no room for doubt);
  the spec is cited, not restated. Modified files are given as exact diffs whose anchors the entry
  checks grep; `shadow.py`, rewritten around a per-session loop, is given whole.
