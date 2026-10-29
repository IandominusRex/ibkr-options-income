# Value Book, Part 2: The Value Process and the Shadow Record — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan **section by section** (one subagent per section, never per task — see "Execution model"). Every section opens with **entry checks** the orchestrator runs itself before it spawns the section's subagent. Each section carries a **model** and an **effort** label; the orchestrator passes both when it spawns. No section of Part 2 touches `web/`; if one ever does, its subagent invokes the `da-vinci` skill first and its prompt says so. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the value book every night as its own process — score both universes, the followed
names and every shadow name once a session has settled, keep the ticker files and their session
history, and start the shadow record: Python's baseline READY entries and the control groups at the
next session's open, the exit engine's three policies on every READY entry, fixed-horizon returns
against SPY, the ranked monthly record, and a report with a postmortem per closed position.

**Architecture:** `scripts/run_value.py` is a thin entrypoint (no IBKR connection, no clientId,
supervised by `scripts.start`): every `service.poll_seconds` it asks `src/value/service.py::plan_run`
whether a settled session is waiting, gathers the plain data `src/value/` may not fetch
(`scripts/value_feed.py`: earnings dates from `news.db`, yfinance market facts) and calls
`run_nightly`, which scores, ranks, persists the ticker files and runs `src/value/shadow.py` in one
`value.db` transaction. The exit engine (`src/value/exits.py`) is a pure state machine, one leg per
policy; the ranked arithmetic (`ranked.py`) and the report (`report.py`) are pure too. The ruleset
becomes `value_rules: v2` = v1's entry rules unchanged + `rules.exits`, frozen before the first
shadow row. Nothing in Part 2 can place, size or gate an order: every shadow row is hypothetical.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 (SQLite, WAL; `mode=ro` URIs), pandas,
pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` (revisions 1–3; §19/§20
hold the operator's answers; no open decisions). Part 2 implements §6.8 (the shadow ledger, the
ranked record, the report), §6.9's follow window and session rows, §7 (not §7.1), §9.7's process
bullets for Stages 1–2, §11's postmortem and §12's measurement (fixed horizons, clustered errors,
the go-live line), plus §16's tests and §18's docs for what Part 2 builds. **Part 1's plan**
(`docs/superpowers/plans/2026-10-29-value-book-1-scorecard.md`) and its Progress log are the ground
truth for the code Part 2 builds on. Executors read the spec sections each section cites, not the
whole spec.

## Execution model

| Section | Tasks | Model | Effort | Why this model | Why this effort |
|---|---|---|---|---|---|
| **Orchestrator** (the main session) | — | **sonnet** | **high** | Runs entry checks, spawns, verifies, asks the operator; writes no product code. | It is the one reader of every subagent's report and the protected-file diff; a missed red gate ships. |
| **A — Ruleset v2, day bars, the nightly sweep** | 1–3 | **sonnet** | **high** | Every line of code and every test is given; the risk is wiring. | Wires into `config.py`, the frozen ruleset, the neutral loader and the research worker's sweep: a slip moves the frozen hash or starves the record of bars. |
| **B — The exit engine and the shadow record** | 4–6 | **sonnet** | **high** | Pure functions and storage with every number pinned by a test the plan's author ran. | The exit-engine state machine and its wiring into `value.db` are the riskiest logic in this part. |
| **C — The value process** | 7–9 | **sonnet** | **high** | A service on the `src/news/` no-IBKR pattern, registered in the supervisor, and the fence tests. | Wires into `scripts/start.py`, `./ibkr`, the ticker file and two databases at once, inside one transaction. |
| **D — The report, the postmortem and the docs** | 10–11 | **sonnet** | **medium** | A pure module with pinned statistics, a read-only script and a doc sweep given as text. | Pinned pure functions and pattern-following script and docs. |
| **Whole-branch review** | after D | **opus** | **high** | One review of the whole branch; no per-task reviews. | Reads the state machine, the shadow rules and the fences against the spec end to end. |
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

   > You are executing Section [X] of `docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md`
   > in the git worktree `.claude/worktrees/value-book-2` (branch `feat/value-book-2`). Read, in this
   > order: the plan's "Rulings made up front", "Global Constraints" and Section [X] in full; the spec
   > sections Section [X] cites; and only the files its tasks list. Do the tasks in order, TDD as
   > written: each failing test first, then the code, then the gates the task names. Run pytest from
   > the worktree root. One commit per task, message ending `Co-Authored-By: <your model name>
   > <noreply@anthropic.com>`. After each task tick its checkboxes and fill its Progress-log row
   > (status, commit, gate counts, date, every ruling with its cost-if-wrong) and commit that with the
   > next task (the last task's row goes in a final `docs(plan)` commit). Never import a
   > `scripts.run_*` module; never touch `data/*.db` of the main checkout; never edit a private
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
verify it and **ask the operator before merging or pushing**. Part 2 has no calibration section:
its first real night runs after the merge and restart (operator to-dos; ruling 20).

**Counts go stale, so recompute them.** Each section adds one final `docs(plan)` commit and a
Progress-log row beyond its task commits, and the review fix pass adds its own. Never trust a fixed
total in this plan: at every entry check and exit, take the commit count from
`git log --oneline main..HEAD | wc -l` and record it, and state pytest targets as **baseline + N**,
where the baseline is the count recorded at A2 and N is the sum of the "new tests" of the tasks
done so far (File structure lists N per file; 69 in all).

**Commits.** Each task is one commit; Task 1's commit also adds this plan file. Every commit
message ends with the trailer `Co-Authored-By: <model> <noreply@anthropic.com>`, where `<model>`
is the executing agent's own model name.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **A entry checks** | pass | 0 commits on `feat/value-book-2` (HEAD `23b1ef3`) | baseline pytest 5150 passed, 1 skipped; ruff clean; mypy 314 files clean; A3 greps all match plan line numbers; A4: hash `e1a1b3b096b1`, no Part 2 code | 2026-10-29 | disk 36 GiB free; value-book-1 worktree absent; section exit target = baseline 5150 + 8 = 5158 passed, 1 skipped |
| 1 Ruleset v2: the exit rules, the service block, the sweep on | done | `8334bcb` | task tests 57 passed (`test_value_config.py` 14); ruff check/format and mypy clean; `ruleset_hash(ValueCfg().rules)` printed `d07717fe5348` as the plan says | 2026-10-30 | No deviation. Test edits were applied as the diffs gave them (the `test_v1_is_frozen` replacement, the dry-run `v2` assertion, the flipped scheduler test). Step 5's hash check was run before pinning `FROZEN["v2"]`. *Cost if wrong: none found (v2 pin is the plan's; reversing it is ruling 1's cost).* |
| 2 Day bars and the readers the record needs | done | `4330f34` | task tests 26 passed (`test_value_inputs.py` 13, with `test_value_dry_run.py` and `test_value_fence.py`); ruff check/format and mypy clean on the touched files | 2026-10-30 | No deviation; tests seen failing first (`AttributeError ... build_day_bars`), then the plan's code applied verbatim. `read_bars` gains an `open` column (nullable, so `build_day_bars` yields `open=None` when a bar has none). *Cost if wrong: none found.* |
| 3 The nightly sweep keeps every bar fresh, SPY's too | done | `53037fc` | task tests 34 passed (`test_value_universe.py` 12 + research worker/materialize + dry run); section exit full gate: pytest 5158 passed, 1 skipped (= baseline 5150 + 8); ruff clean; mypy 314 files clean; `py_compile scripts/value_dry_run.py` silent; protected-file diff empty; `BARS_MAX_AGE_DAYS` has no remaining reference | 2026-10-30 | No deviation. Section A: 3 task commits (`8334bcb`, `4330f34`, `53037fc`) + this docs(plan) commit; commit count on `main..HEAD` recorded in the report. Heads-up: the existing `test_the_sweep_queues_only_what_each_name_lacks` still passes unchanged. *Cost if wrong: the staleness rule is one constant/function.* |
| **B entry checks** | pass | 4 commits on `feat/value-book-2` (HEAD `ea3066b`) | pytest 5158 passed, 1 skipped (baseline 5150 + 8); ruff, mypy clean; FROZEN = v1 `e1a1b3b096b1`, v2 `d07717fe5348`; B3/B4 greps match | 2026-10-30 | section exit target = 5150 + 8 + 47 = 5205 passed, 1 skipped |
| 4 The exit engine | done | `972e4ee` | task tests 24 passed (`test_value_exits.py`) + `test_value_fence.py` 10 passed; ruff check/format and mypy clean on `src/value/exits.py` | 2026-10-30 | No deviation: test file written verbatim, seen failing (`No module named 'src.value.exits'`), then the plan's engine verbatim. The orchestrator's B-entry row rode in this commit. *Cost if wrong: each exit rule is one branch in `step`/`_full`, all pinned by the tests.* |
| 5 The ranked arithmetic and the filed list (M5) | done | `c10ba05` | task tests 21 passed (`test_value_ranked.py` 3, `test_value_rank.py` 5, `test_value_dry_run.py` 3, `test_value_fence.py` 10); ruff check/format and mypy clean on the touched files | 2026-10-30 | No deviation. Seen failing first (`No module named 'src.value.ranked'`; M5 test alone: `assert 'ETF' not in {...}`). The dry run still passes unchanged after M5. *Cost if wrong: M5 is one guard in `filed_lists`.* |
| 6 The shadow tables and the shadow record | done | `a7d8003` | task tests 29 passed (`test_value_shadow.py` 12, `test_value_store.py`, `test_value_fence.py` 10); `ruff check src/value`, ruff format and `mypy src/value` (17 files) clean. **Section B exit full gate: pytest 5197 passed, 1 skipped (= 5150 baseline + 47); ruff clean; mypy 318 files clean; protected-file diff empty; 8 commits on `main..HEAD` after this docs commit** | 2026-10-30 | No deviation: tests verbatim (seen failing on import of `src.value.shadow`), tables, `report.py` stub and `shadow.py` as the plan gave them. **Ruling (arithmetic):** the section's target was stated as 5150 + 8 + 47 = 5205, but the plan's "baseline + 47 (8 + 24 + 3 + 12)" already counts Section A's 8, so the right target is 5150 + 47 = 5197 = 5158 + 39 (24 + 3 + 12); Section C's and D's targets follow from 5197, not 5205. *Cost if wrong: none; a miscount of tests, not of behaviour.* *Cost if wrong: the record's rules are the plan's rulings 10-13, each one function in `shadow.py`.* |
| **C entry checks** | pass | 8 commits on `feat/value-book-2` (HEAD `e3c3500`) | pytest 5197 passed, 1 skipped (baseline 5150 + 47); ruff, mypy (318 files) clean; protected diff empty; C3/C4 greps match | 2026-10-30 | section exit target = baseline 5150 + 62 = 5212 passed, 1 skipped (5197 + 7 + 5 + 3); the orchestrator's B-section target of 5205 was an arithmetic slip (double-counted A's 8) |
| 7 The nightly run | done | `d559bc2` | task tests 26 passed (`test_value_service.py` 7, `test_value_shadow.py` 12, `test_value_store.py` 7); `ruff check src/value`, ruff format and `mypy src/value` (18 files) clean | 2026-10-30 | No deviation: tests verbatim, seen failing (`cannot import name 'service' from 'src.value'`), service verbatim. The orchestrator's C-entry row rode in this commit. *Cost if wrong: the hour, the poll and the coverage gate are config values; the as-of rule is `newest_bar_before` in one place.* |
| 8 The entrypoint, its feed and the supervisor | done | `da69f89` | task tests 44 passed (`test_value_feed.py` 4, `test_start_launcher.py`, `test_watchdog.py`); `py_compile scripts/run_value.py scripts/value_feed.py` silent; `bash -n ibkr` silent; ruff check/format on the five Python files and `mypy scripts/value_feed.py scripts/run_value.py` clean | 2026-10-30 | No deviation: tests seen failing first (`cannot import name 'value_feed' from 'scripts'`), then feed, entrypoint, `scripts/start.py` and `ibkr` edits as the plan gave them. The one launcher test was appended with a shell append rather than the Edit tool (the contents are the plan's). *Cost if wrong: the supervisor entry and the flag are three lines each.* |
| 9 The fences | done | `0ac7fd8` | fence suites 73 passed (`test_value_fence.py` 13 + spreads, news, regime, web, eval_skills). **Section C exit full gate: pytest 5212 passed, 1 skipped (= 5150 baseline + 62); ruff clean; mypy 319 files clean; `py_compile scripts/run_value.py scripts/value_feed.py` silent; `bash -n ibkr` silent; protected-file diff empty; 12 commits on `main..HEAD` after this docs commit** | 2026-10-30 | No deviation. The new tests passed at once; red runs recorded: with `import src.engine.risk_engine` added to `src/value/exits.py`, 3 tests failed (`test_value_imports_no_enrichment_and_no_other_system`, `test_the_value_scorecard_loads_no_wheel_layer_even_transitively`, `test_the_value_process_loads_no_wheel_layer_and_no_ibkr`); with `import os` added to `scripts/run_value.py`, `test_the_value_entrypoint_imports_only_its_feed_and_the_service` failed (4 failed, 9 passed in all); both probes removed, worktree clean. *Cost if wrong: the allowlist is one tuple.* |
| **D entry checks** | pass | 12 commits on `feat/value-book-2` (HEAD `3811ba9`) | pytest 5212 passed, 1 skipped (baseline 5150 + 62); ruff, mypy (319 files) clean; py_compile and `bash -n ibkr` silent; protected diff empty; D3 doc anchors all match | 2026-10-30 | section exit target = baseline 5150 + 69 = 5219 passed, 1 skipped (5212 + 7 for Task 10) |
| 10 The report and the postmortem | | | | | |
| 11 Docs | | | | | |
| **Whole-branch review (opus)** | | | | | |
| **Review fix pass (sonnet)** | | | | | |

## Roadmap (this plan is Part 2 of 6)

Each later part is written **after the previous part merges**, so its code matches reality. Every
part runs on this execution model (Sonnet orchestrator, one subagent per section with a model and
an effort, stop-and-ask between sections, one Opus whole-branch review).

- **Part 1 — The scorecard and the calibration dry run.** Merged and pushed (`23b1ef3`);
  `value_rules: v1` frozen at `e1a1b3b096b1`.
- **Part 2 — The value process and the shadow record.** This plan. `scripts/run_value.py` (no
  IBKR; nightly scoring of both universes, the followed names and every shadow name; `value_runs`;
  the follow window; session history rows; registered in `./ibkr`; `research_sweep.enabled: true`),
  earnings dates from `news.db` as plain data, the shadow ledger `value_shadow` (the baseline track;
  control groups; evidence-universe entries; returns at 21/63/126 sessions and at exit, against SPY,
  errors clustered by entry date), the ranked monthly record, the exit engine as a state machine
  with the three policies, `scripts/value_report.py` and the per-position postmortem. Spec §6.8,
  §6.9 (follow window), §7 (not §7.1), §11's postmortem, §12's measurement. **Moved in:** the
  research sweep's nightly bar refresh and SPY's bars (the record marks every session; ruling 18);
  `value_rules: v2` (ruling 1). **Moved out:** see Parts 3 and 6.
- **Part 3 — Re-evaluation and Stage 1b.** As before (the `submissions/CIK*.json` job kind and 8-K
  item tags, the sector-ETF residual model, the eight §7.1 triggers with debounce and severity,
  `value_reevaluations`, the original-plan shadow twin, Stage 1b's point-in-time backtest with the
  survivorship caveat printed), **plus, moved from Part 2:** §7.1's shock stops (under `full`
  only); the mechanical rebase of corporate actions, which un-freezes the shadow entries Part 2
  marks `rebase_needed` (ruling 16); the going-concern thesis exit, whose input (filing text or an
  8-K item) only Part 3's filings feed provides (ruling 14). Its `reevaluation:` thresholds go under
  `rules:` (spec §7.1), so Part 3 freezes `value_rules: v3` before its first re-evaluation.
- **Part 4 — Stage 2: Claude as the analyst.** As before, and it adds the **Claude track** to the
  shadow ledger: `value_shadow.track = "claude"` rows and `effective_fair_value` from Claude's
  clamped value (the exit engine already reads it only for the half-sale, and turns any other
  Claude-only exit into a `proposal` event — ruling 15). `scripts/run_value.py` becomes the only
  importer of `src.value_ai` (the fence test already allows exactly that).
- **Part 5 — Stage 3: money (paper).** Unchanged. It reads `rules.exits.live_policy` (`value`,
  pre-registered and hashed in v2) to choose the one policy whose exits may reach an order.
- **Part 6 — Web and Telegram.** As before, **plus, moved from Part 2:** setting `last_viewed_at`
  (the follow window's input: Part 2 reads it, Part 6's `value_snapshot` intents write it), the
  daily digest and review cards §7 names ("nine months with no progress", "fair value falls but the
  price has not"), and a watchdog check that the nightly run happened (ruling 19).

## Rulings made up front (the operator may overturn any of them)

Every ruling was checked against `main` at `23b1ef3` and against a prototype of this whole plan
built in a code-only scratch copy of `main` (every code block below passed its tests, `ruff check .`
and `mypy src` there). "Cost if wrong" is what reversing it would take. Part 1's rulings are cited
as "Part 1 ruling N".

**The ruleset**

1. **`value_rules: v2` = v1's entry rules unchanged + `rules.exits`, frozen in Task 1.** Spec §7
   puts every exit threshold "in config" and makes "changing the live policy a version bump"; §7.1
   puts its thresholds "under the ruleset version". So the exit rules belong in the hashed `rules:`
   block, and adding them moves the hash: v1 cannot be kept. The bump lands before the shadow
   ledger's first row, so no recorded outcome is split, and "rules changed before any outcome are
   not tweaking after a loss" (§17). A test pins that every rule but `exits` still hashes to v1's
   `e1a1b3b096b1`: no verdict moves. `FROZEN` keeps v1's pin as history and adds
   `v2 = d07717fe5348`. *Cost if wrong: move `exits` to its own fingerprint and restore v1, before
   the first nightly run; after it, a v3 and a split record.*
2. **M6 (fractions in config) is deferred, not fixed.** The fraction-valued keys (`valuation.*`,
   `market_cap_tolerance`, `assumed_interest_rate`) are frozen in v1 and v2. Converting them in
   place keeps their names and flips the meaning of the operator's private `config/value.yaml` by
   100×; renaming them (`*_pct`) is the safe form, but every process loads `value.yaml` through
   `get_config()`, so a stale private file would then stop the wheel from starting. The fix needs a
   tolerant loader or a migration and rides the next bump that changes an entry rule. Every **new**
   Part 2 key follows the convention: percents are `*_pct` in percent, multiples and counts are
   plain. *Cost if wrong: none now; the inconsistency stays documented in the example file.*

**Part 1's deferred minors (Part 1 Progress log, the review rows)**

3. **M5 fixed (Task 5):** `rank.filed_lists` no longer files an ETF, a REIT, a pre-profit name or a
   data-quality UNKNOWN on `deep_value`; such a name is filed on neither list (`filed_list` NULL).
   The ranked record does not read `filed_lists` at all (ruling 17), but the nightly ticker files
   do. The test that pinned the old behaviour is updated. *Cost if wrong: one guard.*
4. **M1, M2, M3, M4, M7, M8 stay deferred.** M1 (two "latest accession" fingerprints) needs Part 6's
   `is_fresh` consumer to decide which wins; Part 2's re-mark reads the scorecard's own fingerprint,
   so it is consistent within the value process. M2/M3 live in the research selection layer and
   want real payloads. M4 is a spec call (an unknown growth entry rule reads NO). M7 is valuation
   design. M8 is the dry run's `--as-of <past>`; the nightly run is always as of the newest session,
   where today's market cap and earnings are the right ones. M9 and M10 were fixed in Part 1.
   *Cost if wrong: none (unchanged from Part 1).*

**The process**

5. **When a night runs.** `as_of` is SPY's newest bar dated **before today (ET)**: the research
   page's on-demand refresh can write a bar for today while it is still forming. A night is due when
   that session has no `value_runs` row of kind `nightly` and the ET hour is at least
   `service.run_hour_et` (06:00, after the 02:00 sweep has drained). The process polls every
   `service.poll_seconds` (600) instead of a cron: a laptop that slept catches up on wake, a holiday
   is skipped on its own (no new SPY bar), and a session is never scored twice. Missed sessions are
   not back-filled one by one: the next night scores the newest session, and the exit legs step over
   every bar they have not seen (ruling 13). *Cost if wrong: the hour or the poll.*
6. **No thin first night.** `plan_run` waits until the research sweep has a raw companyfacts
   payload for `service.min_filings_coverage_pct` (90%) of the universe's non-ETF names. The live
   `research.db` holds almost no value payloads today; without the gate the first night after the
   restart would score most names UNKNOWN and lock that month's ranked formation to a handful of
   names. Steady state is ~98% (the dry run: 502 of 510). *Cost if wrong: one config value.*
7. **One night is one `value.db` transaction** (ticker files, history, shadow, ranked, the run row).
   A failure leaves `value.db` as it was and the next poll retries. *Cost if wrong: none found.*
8. **The entrypoint is thin and never imported.** Logic lives in `src/value/service.py`; the plain
   data `src/value/` may not fetch (earnings from `news.db`, yfinance market facts) is gathered by
   `scripts/value_feed.py`, which is importable and tested; `scripts/run_value.py` only wires them,
   is checked with `py_compile`, and is fenced by an `ast` allowlist of its imports. A frozen ruleset
   that no longer matches (a private `value.yaml` still saying v1) **idles** the process with a
   CRITICAL log instead of crash-looping under the supervisor. Part 2 sends no Telegram message.
9. **Market facts are fetched at run time**, not as of `as_of`; for a night scored the morning
   after the session that is the right market cap (Part 1's M8 concerns only the dry run). Earnings:
   `news.db` first, yfinance's calendar as the fallback (spec §6.6, Part 1 ruling 30).

**The shadow record** (spec §6.8, §12)

10. **Entries.** A READY baseline verdict on the night of session D is a signal; it enters at the
    **open of the next session after D** (the close when the bar has no open), SPY at the same
    open. Only the trading and evidence universes enter; a followed lookup never does. A signal
    that gets no bar within 5 SPY sessions is `void`. Held and shadow names stay scored nightly
    even after leaving the universe (spec §6.9), under the universe they entered from.
11. **Control groups** (spec §6.8) enter only on a night when that list got at least one new READY
    entry: every name on that list that is **healthy but too dear** (`control_valuation`: verdict
    WAIT) and every name **cheap enough whose health failed** (`control_health`: health `fail`,
    price at or below the list's entry ceiling). Controls carry fixed-horizon returns only, no exit
    legs: the policy comparison is about READY entries. *Cost if wrong: add legs for controls.*
12. **Re-entry.** A key (kind, list, symbol) enters again only once its previous entry stops
    blocking: a pending entry blocks; a READY entry blocks while its **live-policy** leg
    (`rules.exits.live_policy`, `value`) still holds — what the live book would do; a control blocks
    until its horizons are marked; `rebase_needed` blocks until Part 3 rebases it.
13. **Horizons and exits.** Horizon h is marked at the close of the **h-th session after the entry
    session**, on SPY's sessions, from the bars as they stand that night (one fetch, so a split or a
    dividend adjustment touches both ends alike; total-return-like). A name with no bar on or after
    the mark date waits up to 5 SPY sessions, then settles for its last close and says so in
    `status_detail` (a halt or a delisting: survivorship, printed). Exit legs step once per session
    on the close; a sale signalled on a close fills at the **next session's open**; the facts for
    every session a catch-up night steps over are that night's scorecard. Leg returns are price
    returns from the recorded fills; SPY's benchmark is the same fractions at the same fill dates'
    opens. An entry closes when all three horizons are marked and every leg has exited.
14. **The exit engine** (spec §7), Python's numbers only: `full` = the initial stop (cost − 3 ×
    ATR(14) at the signal, never more than 15% below cost), the half-way arm into a Chandelier trail
    (highest close − 3 × ATR, never below cost, **never lowered**), half sold at the first close at
    or above fair value with the trail tightened to 2 × ATR, the peak signals while armed (a close
    below the 20-day SMA after a close at or above fair value; RSI(14) back under 70 after one above
    75 while armed), and the thesis exits. `value` = half at fair value; the rest only on a thesis
    exit, a **re-mark** that lands below the price (the static fair value sitting below a price that
    ran past it is the ride, not an exit), or the catastrophe stop (a close 30% below cost).
    `hold12` = 252 sessions, earlier only on a thesis exit or the catastrophe stop. `full` has no
    catastrophe stop (its own stop is never wider than 15%). **Thesis exits fire under every
    policy** ("`value` and `hold12` use … the thesis exits", §7): F-score ≤ 3, Altman Z below 1.8,
    or fair value below 90% of the price with the price under its 50-day SMA; banks and insurers
    have no F-score or Z, so only the fair-value rule applies to them. **The going-concern flag is
    absent** until Part 3's filings feed provides it. Fair value is **re-marked only on a new
    accession** (§7: "only when a new filing lands"); price and news never move it. In the shadow
    record a deterministic exit "sends" (auto mode, §14 q4). *Cost if wrong: one rule each, all
    pinned by `tests/test_value_exits.py`.*
15. **Which fair value an exit reads** (revision 3). The half-sale target reads the **effective**
    fair value; every other exit reads **Python's**. An exit only the effective value would fire is
    a `proposal` event that sells nothing. On the baseline track effective = Python, so proposals
    never fire there; the hook and its test exist now so Part 4's Claude track cannot get it wrong.
16. **A split freezes, never fires.** A leg's stop and highest close are absolute prices; yfinance
    rewrites history on a split. An entry whose entry bar's price has moved more than 25% from the
    recorded entry price is frozen as `rebase_needed` (no event, no sale) for Part 3's rebase.
17. **The ranked monthly record.** Formed on the **first nightly run whose session falls in a new
    month** (a calendar month-end needs tomorrow's knowledge; the first run of a new month is one
    session later and uses only what was known). Population: the evidence snapshot's names scored
    that night with data quality passing and not `not_applicable`, ranked per list by
    `rank.rank_list` (the scores the ticker files carry, never `filed_lists`). Top and bottom tenth =
    `n // 10` names (none below ten), ties by symbol; plus the whole scored list. Each is held to the
    next formation, returns from the bars as they stand then at both ends; a member without a close
    at either end is dropped and counted. The first formation is mid-month, so the first period is
    partial. *Cost if wrong: the formation trigger is one function.*
18. **The research sweep** (owned by the research worker, Part 1 ruling 31) turns on
    (`research_sweep.enabled: true`) and now wants **the last weekday's bar** every night instead of
    tolerating 4 stale days: the record marks every session. SPY's bars ride along (prices only — an
    ETF has no filings), because SPY is the spreads book's underlying and never in `universe.yaml`.
    The first sweep fetches ~2 GB of raw payloads into the live `research.db` (accepted at Part 1's
    Q6). *Cost if wrong: one constant.*

**Out of Part 2, and the report**

19. **Moved out:** the Claude track (Part 4); shock stops, re-evaluations, the rebase and the
    going-concern input (Part 3); setting `last_viewed_at`, digests, review cards and a watchdog
    check (Part 6). Part 2 *reads* `last_viewed_at` for the follow window (`service.followed_names`)
    and tests its expiry on rows a test writes.
20. **No calibration section.** The live `research.db` has almost none of the value payloads (the
    dry run's 2 GB lived in a worktree copy), so a pre-merge real-data night would only exercise
    missing-data paths; Part 2's real first night runs after the merge and restart, read by the
    operator (to-dos). The disk is nearly full: nothing in this plan copies `research.db`.
21. **The report** groups fixed-horizon returns by (track, list, kind), prints the mean return,
    SPY's, and the excess with its standard error **clustered by entry date**
    (SE² = G/(G−1) × Σ_g (Σ residuals in g)² / n²; none below two dates), the go-live line of §12
    (63-session excess of the track's READY entries, n of 30), the three policies side by side
    (live one marked), the ranked record with the top − bottom spread, and with `--postmortems` one
    postmortem per closed READY entry: entry, fair value then and now, every exit event, return vs
    SPY per policy, the horizons, and **the gate closest to wrong** = the passing check at entry with
    the least relative room to its bar (|actual − bar| / |bar|; absolute when the bar is 0). The
    survivorship caveat is the report's second line.
22. **The dry run is left alone.** Its input loading duplicates `service.load_inputs`; folding it in
    is a refactor of a tested one-off tool with no Part 2 consumer. *Cost if wrong: ~40 duplicated
    lines.*

## Global Constraints

- **The core invariant holds unchanged:** nothing in Part 2 can place, size or gate an order.
  `src/engine/`, `src/execution/`, `src/strategies/`, `src/orchestrator/`, `src/monitor/`,
  `src/notify/`, `src/spreads/`, `src/news/` and `src/claude/` never import `src.value`.
- `src/value/` imports nothing from `src.claude`, `src.news`, `src.value_ai`, `src.spreads*`,
  `src.notify`, `src.api`, the trading path, `src.ledger`, `src.reporting` or the enrichment
  analytics; from `src.research` only `src.research.ingest.concepts` and `src.research.schemas`
  (it reads `research.db` through `src/common/value_inputs.py`). Earnings dates and anything from
  `news.db` reach it only as plain data from `scripts/run_value.py` (via `scripts/value_feed.py`).
- `src.value_ai` does not exist; do not create it. Only `scripts/run_value.py` may ever import it.
- The pure modules (`schemas`, `metrics`, `scores`, `gates`, `valuation`, `timing`, `scorecard`,
  `rank`, `funnel`, `ruleset`, and now `exits`, `ranked`, `report`) do no I/O.
- Only `src/value/` constructs `value.db` rows (`scripts/` is scanned too). The research worker owns
  every SEC and price fetch; `src/value/` opens no SEC client and no data provider.
- **Unknown is never zero.** A missing figure is `None`.
- Percent in config, fractions in code, every conversion explicit — except the v1 keys ruling 2
  leaves as fractions.
- **Never import `scripts.run_*`.** Check `scripts/run_value.py` with `.venv/bin/python -m
  py_compile`. Never open the main checkout's `data/*.db`; never copy `research.db`.
- Worktree Bash: plain single commands, absolute paths or the worktree root as cwd; no heredocs, no
  `cd x && …`, no compound commands that mention git paths.
- New config keys go into `config/examples/value.yaml` with a code default; the operator's private
  `config/*.yaml` is never edited (operator to-dos at the end).
- **Protected files** (diff against `main` must be empty at every section exit):
  `git diff --stat main...HEAD -- src/engine src/execution src/strategies src/notify
  src/orchestrator src/spreads src/api src/news src/claude web` prints nothing.
- Per-task gate: the task's test files + `.venv/bin/ruff check <touched paths>` +
  `.venv/bin/ruff format --check <touched paths>` + `.venv/bin/mypy <touched src paths>`. Full gate
  at section exits only, from the worktree root: `.venv/bin/python -m pytest -q`,
  `.venv/bin/ruff check .`, `.venv/bin/mypy src`.
- `ruff format` only the files a task touches (`src/api/routers/portfolio.py` and `system.py` carry
  pre-existing format drift; leave them).

## Review Focus

1. **The laptop slept, or the process was down for days:** the next night scores only the newest
   settled session, and every open leg steps over each bar it missed → Task 7
   `test_a_session_already_scored_is_not_run_again`; Task 6
   `test_the_legs_run_each_policy_and_record_every_event` (four sessions in one call).
2. **A bar dated today, still forming,** must never become a scored session → Task 7
   `test_the_plan_scores_the_newest_settled_session_and_every_name`; Task 2
   `test_the_shadow_records_readers`.
3. **A split while a position is held** must not fire a −50% stop → Task 6
   `test_a_split_freezes_the_entry_instead_of_firing_its_stop`.
4. **A name that stops getting bars** (halted, delisted, a failed fetch) → Task 6
   `test_a_signal_that_never_gets_a_bar_is_voided`,
   `test_a_horizon_waits_for_the_names_bar_then_settles_for_the_last_close`.
5. **The operator restarts before refreshing the private `value.yaml`** (still v1) → Task 7
   `test_an_old_private_config_idles_the_process_instead_of_crash_looping`; and the first night
   after the restart, before the sweep has filled `research.db` → Task 7
   `test_a_night_waits_until_the_research_sweep_has_filed_the_universe`.

---

## File structure

```
config/examples/value.yaml                MODIFY  v2, research_sweep on, service:, rules.exits (T1)
src/
  common/config.py                        MODIFY  ValueExitsCfg, ValueServiceCfg, sweep on, v2 (T1)
  common/value_types.py                   MODIFY  DayBar (T2)
  common/value_inputs.py                  MODIFY  build_day_bars, read_bars' open, newest_bar_before,
                                                  closes_on, filings_coverage, symbol_is_etf (T2)
  research/ingest/value_universe.py       MODIFY  nightly bars, SPY bars only (T3)
  value/ruleset.py                        MODIFY  FROZEN v2 (T1)
  value/exits.py                          CREATE  the exit engine, pure (T4)
  value/ranked.py                         CREATE  tenths, equal-weight returns, formation, pure (T5)
  value/rank.py                           MODIFY  filed_lists skips unscored names: M5 (T5)
  value/store.py                          MODIFY  value_shadow, _legs, _events, value_ranked (T6)
  value/shadow.py                         CREATE  the shadow record and the ranked record's I/O (T6)
  value/service.py                        CREATE  plan_run, run_nightly, the follow window (T7)
  value/report.py                         CREATE  the report and the postmortem, pure (T10)
scripts/
  value_feed.py                           CREATE  earnings from news.db, yfinance market facts (T8)
  run_value.py                            CREATE  the thin entrypoint (T8)
  start.py                                MODIFY  the value_service, --no-value (T8)
  value_report.py                         CREATE  prints the record (T10)
ibkr                                      MODIFY  `logs value` (T8)
tests/
  test_value_config.py                    MODIFY  (+4: 10 -> 14)
  test_value_dry_run.py                   MODIFY  (v1 -> v2)
  test_value_universe.py                  MODIFY  (+2; the scheduler test flips)
  test_value_inputs.py                    MODIFY  (+2)
  test_value_exits.py                     CREATE  (24)
  test_value_ranked.py                    CREATE  (3)
  test_value_rank.py                      MODIFY  (M5)
  test_value_shadow.py                    CREATE  (12)
  test_value_service.py                   CREATE  (7)
  test_value_feed.py                      CREATE  (4)
  test_start_launcher.py                  MODIFY  (+1)
  test_value_fence.py                     MODIFY  (+3)
  test_value_report.py                    CREATE  (7)
ARCHITECTURE.md, SETUP.md, STATUS.md, CLAUDE.md   MODIFY (T11)
docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md   this plan (Progress log)
```

**69 new tests** in all (baseline + 69 at Section D's exit; the prototype ran 5150 + 1 skipped →
5219 + 1 skipped). Part 2 adds a process but no API route, no command kind, no Telegram command
and no top-level directory, so `README.md`, `docs/web/commands.md` and `docs/web/api.md` are
unchanged.

---

## Section A — Ruleset v2, day bars, the nightly sweep (Tasks 1–3) · model: sonnet · effort: high

The exit rules and the service block go into the config and freeze `value_rules: v2`; the neutral
loader learns to hand the exit engine a session at a time; the research sweep keeps every name's
bars (and SPY's) one session fresh. Nothing here scores or records anything yet.

**Spec to read:** §6.8 (last paragraph: the ruleset), §7 (first three paragraphs and the `full`
bullets), §9.7 (the `scripts/run_value.py` and config bullets), §17 (last sentence of the first
paragraph).

**Files the subagent reads:** `src/common/config.py` (lines 1385–1620: the value models),
`config/examples/value.yaml`, `src/value/ruleset.py`, `tests/test_value_config.py`,
`tests/test_value_dry_run.py` (line 104), `src/common/value_types.py`,
`src/common/value_inputs.py`, `tests/test_value_inputs.py` (lines 147–260),
`src/research/ingest/value_universe.py`, `tests/test_value_universe.py` (lines 125–205).

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **A0. Disk, the old worktree, and the new one.** From the main checkout:

  ```bash
  df -h .
  git -C "/Users/ianlim/Desktop/IBKR Investments" worktree list
  ```

  `df` must show **at least 8 GiB available** (the old worktree's ~2 GB of database copies gone,
  plus room for the ~2 GB the live sweep will add after the merge). `worktree list` must **not**
  list `.claude/worktrees/value-book-1` (operator to-do 0). Either fails → stop and ask the operator.
  Then create the worktree and set it up, one command each (the last four from the worktree root):

  ```bash
  git -C "/Users/ianlim/Desktop/IBKR Investments" worktree add "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/value-book-2" -b feat/value-book-2
  ln -s "/Users/ianlim/Desktop/IBKR Investments/.venv" .venv
  cp "/Users/ianlim/Desktop/IBKR Investments/docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md" docs/superpowers/plans/
  IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"
  ```

  (No `web/node_modules` link: Part 2 runs no web test. No database copy: Part 2's tests use
  fixtures.)
- [ ] **A1. Branch and a clean start.** `git branch --show-current` prints `feat/value-book-2`;
  `git log --oneline -1` starts with `23b1ef3` (or a later `main` the operator merged — record it);
  `git status --short` prints exactly:

  ```
  ?? docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  ```

- [ ] **A2. A green baseline, from the worktree root.** Each passes; record the pytest count in the
  Progress log as **the baseline** (at `23b1ef3`: `5150 passed, 1 skipped`; mypy: `314 source
  files`). Run pytest from the worktree root: run elsewhere, 4 ledger/openapi/web-fence tests fail
  spuriously.

  ```bash
  .venv/bin/python -m pytest -q
  .venv/bin/ruff check .
  .venv/bin/mypy src
  ```

  A red baseline is not this plan's to fix: stop and report it. (`tests/test_roll_review_fixes.py::
  test_fallback_leg_prices_net_to_the_actual_combo_fill` failed once in the prototype's full run and
  passed alone and on the rerun: an order-dependent flake. If it alone fails, rerun once and record.)
- [ ] **A3. The code Section A edits is where this plan says.** Each command prints exactly the
  line(s) shown (line numbers as of `23b1ef3`; a moved line is fine if the text matches — record it):

  ```bash
  grep -n "^class ValueRulesCfg(_ValueModel):$" src/common/config.py                       # 1572:
  grep -n "^    timing: ValueTimingCfg = Field(default_factory=ValueTimingCfg)$" src/common/config.py   # 1582:
  grep -n "^class ValueResearchSweepCfg(_ValueModel):$" src/common/config.py               # 1604:
  sed -n 1607p src/common/config.py                                                        #     enabled: bool = False
  grep -n "^class ValueCfg(_ValueModel):$" src/common/config.py                            # 1611:
  grep -n '^    ruleset_version: str = "v1"$' src/common/config.py                         # 1614:
  grep -n '^FROZEN: dict\[str, str\] = {"v1": "e1a1b3b096b1"}$' src/value/ruleset.py       # 16:
  grep -n "^ruleset_version: v1$" config/examples/value.yaml                               # 10:
  grep -n "^  enabled: false             # the research worker's nightly enqueue (Part 2 turns it on)$" config/examples/value.yaml   # 30:
  tail -n 1 config/examples/value.yaml                                                     #     new_low_window_sessions: 5
  grep -n 'assert cfg.ruleset_version == "v1"' tests/test_value_config.py                  # 26:
  grep -n "^def test_v1_is_frozen() -> None:$" tests/test_value_config.py                  # 68:
  grep -n '("dry_run", 1, "v1")' tests/test_value_dry_run.py                               # 104:
  grep -n 'assert "value_sweep" not in {j.id for j in build_scheduler().get_jobs()}' tests/test_value_universe.py   # 203:
  grep -n "^class Classification(BaseModel):$" src/common/value_types.py                   # 69:
  grep -n "^from sqlalchemy import create_engine, select$" src/common/value_inputs.py      # 25:
  grep -n "^# ── I/O: read-only research.db" src/common/value_inputs.py                     # 198:
  grep -n "^        (r.date, r.high, r.low, r.close, r.volume or 0.0)$" src/common/value_inputs.py   # 262:
  grep -n "^def current_fingerprint_parts(" src/common/value_inputs.py                     # 270:
  grep -n "^def test_price_series_is_none_without_bars() -> None:$" tests/test_value_inputs.py   # 183:
  grep -n "^def test_a_missing_research_db_is_none_not_an_error(" tests/test_value_inputs.py     # 253:
  grep -n "^BARS_MAX_AGE_DAYS = 4  # a long weekend is not stale$" src/research/ingest/value_universe.py   # 27:
  grep -n "^    names = names if names is not None else value_names()$" src/research/ingest/value_universe.py   # 41:
  grep -n "(today - last).days > BARS_MAX_AGE_DAYS" src/research/ingest/value_universe.py  # 69:
  ```

- [ ] **A4. v1 is what is frozen, and no Part 2 code exists yet.** The first prints `e1a1b3b096b1`;
  the second prints nothing; the third prints only the two `value_universe.py` lines of A3:

  ```bash
  .venv/bin/python -c "from src.common.config import ValueCfg; from src.value.ruleset import ruleset_hash; print(ruleset_hash(ValueCfg().rules))"
  grep -rln "ValueExitsCfg\|src\.value\.shadow\|run_value\|value_feed\|DayBar" src tests scripts ibkr
  grep -rn "BARS_MAX_AGE_DAYS" src tests scripts
  ```

**Section exit:** three task commits plus the section's final `docs(plan)` commit; full gate green
with pytest = baseline + 8; `.venv/bin/python -m py_compile scripts/value_dry_run.py` silent;
protected-file diff empty. Record the commit count from `git log --oneline main..HEAD | wc -l`.

---

### Task 1: Ruleset v2 — the exit rules, the service block, the sweep on

**Files:**
- Modify: `src/common/config.py` (insert before line 1572; after line 1582; line 1607; insert
  before line 1611; lines 1612–1619)
- Modify: `config/examples/value.yaml` (lines 3–10, 30, after 148), `src/value/ruleset.py` (line 16)
- Modify: `tests/test_value_config.py`, `tests/test_value_dry_run.py` (line 104),
  `tests/test_value_universe.py` (lines 199–205: the scheduler test flips)
- Add: this plan (first commit of the branch)

**Interfaces:**
- Produces: `ValueExitsCfg` (`live_policy: Literal["full", "value", "hold12"]`, `initial_stop_atr`,
  `initial_stop_max_pct`, `arm_at_pct`, `trail_atr`, `trail_atr_after_half`, `half_sell_pct`,
  `peak_rsi_high`, `peak_rsi_cross`, `thesis_piotroski_max`, `thesis_altman_z_below`,
  `thesis_fv_below_price_pct`, `catastrophe_stop_pct`, `hold12_sessions`) at
  `ValueRulesCfg.exits`; `ValueServiceCfg` (`run_hour_et`, `poll_seconds`, `market_facts_workers`,
  `min_filings_coverage_pct`) at `ValueCfg.service`; `ValueCfg.ruleset_version == "v2"`;
  `FROZEN["v2"] == "d07717fe5348"`.

- [x] **Step 1: Write the failing tests** — apply this diff to `tests/test_value_config.py` (it
  replaces `test_v1_is_frozen`):

```diff
diff --git a/tests/test_value_config.py b/tests/test_value_config.py
--- a/tests/test_value_config.py
+++ b/tests/test_value_config.py
@@ -1,6 +1,9 @@
-"""config/value.yaml: the typed model, its committed example and the ruleset hash (Part 1)."""
+"""config/value.yaml: the typed model, its committed example and the ruleset hash (Parts 1-2)."""
 
 from __future__ import annotations
 
+import hashlib
+import json
+
 import pytest
 import yaml
@@ -24,5 +27,5 @@ def test_the_example_spells_out_exactly_the_model_defaults() -> None:
 def test_get_config_loads_the_value_block() -> None:
     cfg = get_config().value
-    assert cfg.ruleset_version == "v1"
+    assert cfg.ruleset_version == "v2"
     assert cfg.rules.margin_of_safety.deep_value[MarketRegime.NORMAL] == 25.0
     assert cfg.rules.margin_of_safety.quality_growth[MarketRegime.CRISIS] == 25.0
@@ -63,9 +66,45 @@ def test_a_frozen_version_refuses_rules_that_no_longer_match(monkeypatch) -> Non
     with pytest.raises(ValueError, match="frozen"):
         ruleset_id(ValueCfg(ruleset_version="v9"))
-    assert ruleset_id(ValueCfg()) == ("v1", ruleset_hash(ValueCfg().rules))
+    assert ruleset_id(ValueCfg()) == ("v2", ruleset_hash(ValueCfg().rules))
+
+
+def test_v1_stays_pinned_and_v2_is_frozen() -> None:
+    """Part 1 froze v1 (the entry rules) after the calibration dry run; Part 2 froze v2 = v1 +
+    the exit rules, before the shadow ledger's first row."""
+    assert FROZEN["v1"] == "e1a1b3b096b1"
+    assert FROZEN["v2"] == ruleset_hash(ValueCfg().rules)
+    assert ruleset_id(get_config().value) == ("v2", FROZEN["v2"])
+
+
+def test_v2_changes_no_entry_rule() -> None:
+    """Every rule but the new exits block hashes exactly as v1 did: no verdict moves."""
+    rules = ValueCfg().rules.model_dump(mode="json")
+    del rules["exits"]
+    blob = json.dumps(rules, sort_keys=True, separators=(",", ":"))
+    assert hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12] == FROZEN["v1"]
+
+
+def test_the_exit_rules_are_in_the_ruleset() -> None:
+    """Spec §7: changing an exit rule, or the live policy, is a version bump."""
+    cfg = ValueCfg()
+    assert cfg.rules.exits.live_policy == "value"
+    for change in ({"live_policy": "full"}, {"catastrophe_stop_pct": 25.0}):
+        moved = ValueCfg(**{"rules": {"exits": change}})
+        assert ruleset_hash(moved.rules) != ruleset_hash(cfg.rules)
+
+
+def test_nonsense_exit_and_service_keys_are_refused() -> None:
+    for bad in (
+        {"rules": {"exits": {"live_policy": "hold6"}}},
+        {"rules": {"exits": {"half_sell_pct": 0.5e3}}},
+        {"rules": {"exits": {"peak_rsi_cross": 80.0}}},
+        {"service": {"run_hour_et": 24}},
+        {"service": {"poll_seconds": 5}},
+    ):
+        with pytest.raises(ValidationError):
+            ValueCfg(**bad)
 
 
-def test_v1_is_frozen() -> None:
-    """Part 1, Task 16: the operator froze value_rules v1 after the calibration dry run."""
-    assert FROZEN["v1"] == ruleset_hash(ValueCfg().rules)
-    assert ruleset_id(get_config().value) == ("v1", FROZEN["v1"])
+def test_part_2_turns_the_research_sweep_on() -> None:
+    assert ValueCfg().research_sweep.enabled is True
+    assert ValueCfg().service.run_hour_et == 6
```

  …this one to `tests/test_value_dry_run.py`:

```diff
diff --git a/tests/test_value_dry_run.py b/tests/test_value_dry_run.py
--- a/tests/test_value_dry_run.py
+++ b/tests/test_value_dry_run.py
@@ -102,5 +102,5 @@ def test_the_dry_run_scores_persists_and_prints_the_funnel(dbs, capsys, tmp_path
         assert row.verdict_deep == "WATCH"  # cheap enough; no earnings date is unknown timing
         run = s.query(ValueRunRow).one()
-        assert (run.kind, run.names, run.ruleset_version) == ("dry_run", 1, "v1")
+        assert (run.kind, run.names, run.ruleset_version) == ("dry_run", 1, "v2")
 
 
```

  …and in `tests/test_value_universe.py` replace lines 203–205 (the sweep is on by default now):

  ```python
      assert "value_sweep" not in {j.id for j in build_scheduler().get_jobs()}
      monkeypatch.setattr(get_config().value.research_sweep, "enabled", True)
      assert "value_sweep" in {j.id for j in build_scheduler().get_jobs()}
  ```

  with:

  ```python
      assert get_config().value.research_sweep.enabled  # on since Part 2
      assert "value_sweep" in {j.id for j in build_scheduler().get_jobs()}
      monkeypatch.setattr(get_config().value.research_sweep, "enabled", False)
      assert "value_sweep" not in {j.id for j in build_scheduler().get_jobs()}
  ```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_universe.py`
  Expected: FAIL — `AttributeError: 'ValueRulesCfg' object has no attribute 'exits'` (and the v2
  and sweep assertions).

- [x] **Step 3: The config models** — apply to `src/common/config.py`:

```diff
diff --git a/src/common/config.py b/src/common/config.py
--- a/src/common/config.py
+++ b/src/common/config.py
@@ -1570,4 +1570,35 @@ class ValueTimingCfg(_ValueModel):
 
 
+class ValueExitsCfg(_ValueModel):
+    """Spec §7: the exit engine's three policies. Under ``rules:``, so every key is in the
+    ruleset fingerprint: changing an exit, or the live policy, is a version bump (spec §7)."""
+
+    live_policy: Literal["full", "value", "hold12"] = "value"  # pre-registered (revision 3)
+    initial_stop_atr: float = 3.0  # full: average cost - 3 x ATR(14) ...
+    initial_stop_max_pct: float = 15.0  # ... never wider than 15% below it
+    arm_at_pct: float = 50.0  # full: arm the trail at entry + 50% of the way to fair value
+    trail_atr: float = 3.0  # full: highest close since entry - 3 x ATR(14), never below cost
+    trail_atr_after_half: float = 2.0  # ... tightened to 2 x ATR(14) once half is sold
+    half_sell_pct: float = 50.0  # full and value: the share sold at the first close >= fair value
+    peak_rsi_high: float = 75.0  # full: RSI(14) above this while armed ...
+    peak_rsi_cross: float = 70.0  # ... then back below this sells the rest
+    thesis_piotroski_max: int = 3  # every policy: F-score at or below this is a thesis exit
+    thesis_altman_z_below: float = 1.8  # ... Altman Z below this (distress)
+    thesis_fv_below_price_pct: float = 90.0  # ... fair value below 90% of the price, under SMA50
+    catastrophe_stop_pct: float = 30.0  # value and hold12: close 30% below the average cost
+    hold12_sessions: int = 252
+
+    @model_validator(mode="after")
+    def _sane(self) -> ValueExitsCfg:
+        for name in ("initial_stop_max_pct", "arm_at_pct", "half_sell_pct"):
+            if not 0.0 < getattr(self, name) <= 100.0:
+                raise ValueError(f"value exits.{name} must be in (0, 100]")
+        if not 0.0 < self.catastrophe_stop_pct < 100.0:
+            raise ValueError("value exits.catastrophe_stop_pct must be in (0, 100)")
+        if self.peak_rsi_cross >= self.peak_rsi_high:
+            raise ValueError("value exits.peak_rsi_cross must be below peak_rsi_high")
+        return self
+
+
 class ValueRulesCfg(_ValueModel):
     """Every key that can change a verdict. Hashed into the ruleset fingerprint (spec §6.8)."""
@@ -1581,4 +1612,5 @@ class ValueRulesCfg(_ValueModel):
     margin_of_safety: ValueMarginCfg = Field(default_factory=ValueMarginCfg)
     timing: ValueTimingCfg = Field(default_factory=ValueTimingCfg)
+    exits: ValueExitsCfg = Field(default_factory=ValueExitsCfg)
 
 
@@ -1605,16 +1637,37 @@ class ValueResearchSweepCfg(_ValueModel):
     """The research worker's nightly enqueue of every value name's filings and bars."""
 
-    enabled: bool = False
+    enabled: bool = True
     hour_et: int = 2
 
 
+class ValueServiceCfg(_ValueModel):
+    """The value process (``scripts/run_value.py``, Part 2): no IBKR connection, no clientId."""
+
+    run_hour_et: int = 6  # score once the research worker's 02:00 sweep has drained
+    poll_seconds: int = 600  # how often the process checks whether a new session has closed
+    market_facts_workers: int = 4  # parallel yfinance reads for market cap and earnings
+    min_filings_coverage_pct: float = 90.0  # wait until the sweep has filed this share of names
+
+    @model_validator(mode="after")
+    def _sane(self) -> ValueServiceCfg:
+        if not 0 <= self.run_hour_et <= 23:
+            raise ValueError("value service.run_hour_et must be 0-23")
+        if not 0.0 <= self.min_filings_coverage_pct <= 100.0:
+            raise ValueError("value service.min_filings_coverage_pct must be 0-100")
+        if self.poll_seconds < 30 or self.market_facts_workers < 1:
+            raise ValueError("value service.poll_seconds >= 30 and market_facts_workers >= 1")
+        return self
+
+
 class ValueCfg(_ValueModel):
-    """The value book (config/value.yaml). Part 1: the scorecard, nothing that trades."""
+    """The value book (config/value.yaml). Parts 1-2: the scorecard and the shadow record,
+    nothing that trades."""
 
-    ruleset_version: str = "v1"
+    ruleset_version: str = "v2"
     db_url: str = "sqlite:///data/value.db"
     universe: ValueUniverseCfg = Field(default_factory=ValueUniverseCfg)
     ticker_file: ValueTickerFileCfg = Field(default_factory=ValueTickerFileCfg)
     research_sweep: ValueResearchSweepCfg = Field(default_factory=ValueResearchSweepCfg)
+    service: ValueServiceCfg = Field(default_factory=ValueServiceCfg)
     rules: ValueRulesCfg = Field(default_factory=ValueRulesCfg)
 
```

- [x] **Step 4: The example file** — apply to `config/examples/value.yaml` (the keys must equal the
  model defaults: `test_the_example_spells_out_exactly_the_model_defaults`):

```diff
diff --git a/config/examples/value.yaml b/config/examples/value.yaml
--- a/config/examples/value.yaml
+++ b/config/examples/value.yaml
@@ -1,12 +1,14 @@
 # The value book (docs/superpowers/specs/2026-10-28-value-swing-book-design.md).
 #
-# Copy to config/value.yaml (git-ignored) to tune it. Part 1 builds the scorecard only: nothing
-# here can place, size or gate an order.
+# Copy to config/value.yaml (git-ignored) to tune it. Parts 1-2 build the scorecard and the shadow
+# record only: nothing here can place, size or gate an order.
 #
 # Everything under `rules:` can change a verdict, so it is hashed into the ruleset fingerprint
-# (src/value/ruleset.py). Once `ruleset_version` is frozen (v1, after the calibration dry run,
-# spec §17), changing any rule is a version bump with a written reason, at most quarterly.
+# (src/value/ruleset.py). Once `ruleset_version` is frozen, changing any rule is a version bump
+# with a written reason, at most quarterly. v1 (2026-10-29) froze the entry rules after the
+# calibration dry run; v2 (Part 2) adds `rules.exits` before the shadow ledger's first row and
+# changes no entry rule.
 
-ruleset_version: v1
+ruleset_version: v2
 db_url: sqlite:///data/value.db
 
@@ -28,7 +30,13 @@ ticker_file:
 
 research_sweep:
-  enabled: false             # the research worker's nightly enqueue (Part 2 turns it on)
+  enabled: true              # the research worker's nightly enqueue of filings and daily bars
   hour_et: 2
 
+service:                     # scripts/run_value.py: no IBKR connection, no clientId
+  run_hour_et: 6             # score once the 02:00 sweep has drained (ET)
+  poll_seconds: 600          # how often the process checks whether a new session has closed
+  market_facts_workers: 4    # parallel yfinance reads (market cap, next earnings)
+  min_filings_coverage_pct: 90.0  # no night until the sweep has filings for 90% of the names
+
 rules:
   data_quality:              # spec §6.3: a failure is UNKNOWN, never FAIL
@@ -147,2 +155,18 @@ rules:
     low_lookback_sessions: 63
     new_low_window_sessions: 5
+
+  exits:                     # spec §7: three policies shadowed side by side; percent where a %
+    live_policy: value       # pre-registered (revision 3); full and hold12 are diagnostics only
+    initial_stop_atr: 3.0    # full: average cost - 3 x ATR(14) ...
+    initial_stop_max_pct: 15.0   # ... never wider than 15% below it
+    arm_at_pct: 50.0         # full: the trail arms at entry + 50% of the way to fair value
+    trail_atr: 3.0           # full: highest close - 3 x ATR(14), never below the average cost
+    trail_atr_after_half: 2.0    # ... 2 x ATR(14) once half is sold
+    half_sell_pct: 50.0      # full and value: sold at the first close at or above fair value
+    peak_rsi_high: 75.0      # full: RSI(14) above 75 while armed ...
+    peak_rsi_cross: 70.0     # ... then back below 70 sells the rest
+    thesis_piotroski_max: 3  # every policy: F-score <= 3 is a thesis exit
+    thesis_altman_z_below: 1.8   # ... Altman Z below 1.8 (distress)
+    thesis_fv_below_price_pct: 90.0  # ... fair value below 90% of the price, under the 50-day SMA
+    catastrophe_stop_pct: 30.0   # value and hold12: a close 30% below the average cost
+    hold12_sessions: 252
```

- [x] **Step 5: Check the hash, then pin it.** Run:

  ```bash
  .venv/bin/python -c "from src.common.config import ValueCfg; from src.value.ruleset import ruleset_hash; print(ruleset_hash(ValueCfg().rules))"
  ```

  It prints `d07717fe5348`. Any other value means a default differs from this plan: stop and
  report (do not pin a different hash). Then apply to `src/value/ruleset.py`:

```diff
diff --git a/src/value/ruleset.py b/src/value/ruleset.py
--- a/src/value/ruleset.py
+++ b/src/value/ruleset.py
@@ -14,5 +14,7 @@ from src.common.config import ValueCfg, ValueRulesCfg
 # value_rules v1, frozen 2026-10-29 by the operator after the calibration dry run (Part 1,
 # Task 16). A rule change is a new version with a written reason, at most quarterly (spec §6.8).
-FROZEN: dict[str, str] = {"v1": "e1a1b3b096b1"}
+# v2 (Part 2): v1's entry rules unchanged, plus `rules.exits` (spec §7), frozen before the shadow
+# ledger's first row so every shadow entry carries the exit rules it was simulated under.
+FROZEN: dict[str, str] = {"v1": "e1a1b3b096b1", "v2": "d07717fe5348"}
 
 
```

- [x] **Step 6: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_universe.py tests/test_private_config.py tests/test_value_scorecard.py`
  Expected: PASS (`test_value_config.py` 14 tests). Then `.venv/bin/ruff check src/common/config.py
  src/value/ruleset.py tests/test_value_config.py tests/test_value_dry_run.py
  tests/test_value_universe.py`, `.venv/bin/ruff format --check` on the same files, and
  `.venv/bin/mypy src/common/config.py src/value/ruleset.py` — all clean.

- [x] **Step 7: Commit**

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md src/common/config.py config/examples/value.yaml src/value/ruleset.py tests/test_value_config.py tests/test_value_dry_run.py tests/test_value_universe.py
  git commit -m "feat(value): value_rules v2 adds the exit rules; the service block; the sweep on"
  ```

---

### Task 2: Day bars and the readers the record needs

**Files:**
- Modify: `src/common/value_types.py` (insert before line 69)
- Modify: `src/common/value_inputs.py` (line 25; the import block at 31–39; insert before line 198;
  lines 261–266; insert before line 270)
- Modify: `tests/test_value_inputs.py` (insert before lines 183 and 253)

**Interfaces:**
- Produces: `DayBar(date, open: float | None, close, sma20, sma50, rsi14, atr14)` in
  `src.common.value_types`; in `src.common.value_inputs`:
  `build_day_bars(bars: pd.DataFrame, after: date | None = None) -> list[DayBar]`;
  `read_bars` frames gain an `open` column; `newest_bar_before(session, symbol, before: date) ->
  date | None`; `closes_on(session, symbols: list[str], day: date) -> dict[str, float]`;
  `filings_coverage(session, symbols: list[str]) -> tuple[int, int]`;
  `symbol_is_etf(session, symbol: str) -> bool`.

- [x] **Step 1: Write the failing tests** — apply to `tests/test_value_inputs.py`:

```diff
diff --git a/tests/test_value_inputs.py b/tests/test_value_inputs.py
--- a/tests/test_value_inputs.py
+++ b/tests/test_value_inputs.py
@@ -181,4 +181,21 @@ def test_price_series_computes_the_fixed_window_technicals() -> None:
 
 
+def test_day_bars_carry_the_technicals_measured_at_each_close() -> None:
+    bars, _ = _bars(60)
+    close = bars["close"]
+    bars.insert(0, "open", [c - 0.5 for c in close])
+    days = vi.build_day_bars(bars)
+    assert len(days) == 60 and days[0].open == pytest.approx(close.iloc[0] - 0.5)
+    assert days[18].sma20 is None and days[19].sma20 == pytest.approx(close.iloc[:20].mean())
+    assert days[48].sma50 is None and days[49].sma50 == pytest.approx(close.iloc[:50].mean())
+    assert days[13].atr14 is None and days[14].atr14 is not None
+    later = vi.build_day_bars(bars, after=days[57].date)
+    assert [d.date for d in later] == [days[58].date, days[59].date]
+    assert later[0].sma50 == days[58].sma50  # measured on the whole history, not the tail
+    no_open = vi.build_day_bars(bars.drop(columns=["open"]))
+    assert no_open[0].open is None  # unknown, never zero
+    assert vi.build_day_bars(bars.iloc[:0]) == []
+
+
 def test_price_series_is_none_without_bars() -> None:
     empty = pd.DataFrame(columns=["high", "low", "close", "volume"])
@@ -251,4 +268,18 @@ def test_reads_come_from_a_read_only_research_db(research_file) -> None:
 
 
+def test_the_shadow_records_readers(research_file) -> None:
+    with vi.research_read() as s:
+        assert s is not None
+        # 2025-09-01's bar may still be forming on 2025-09-01: the newest settled one is Friday's.
+        assert vi.newest_bar_before(s, "STDY", date(2025, 9, 1)) == date(2025, 8, 29)
+        assert vi.newest_bar_before(s, "NONE", date(2025, 9, 1)) is None
+        assert vi.closes_on(s, ["STDY", "NONE"], date(2025, 8, 27)) == {"STDY": 12.0}
+        assert vi.closes_on(s, [], date(2025, 8, 27)) == {}
+        assert list(vi.read_bars(s, "STDY", date(2025, 8, 26))["open"]) == [10.0, 10.0]
+        assert vi.symbol_is_etf(s, "STDY") is False and vi.symbol_is_etf(s, "NONE") is False
+        assert vi.filings_coverage(s, ["STDY", "NONE"]) == (1, 2)
+        assert vi.filings_coverage(s, []) == (0, 0)
+
+
 def test_a_missing_research_db_is_none_not_an_error(tmp_path, monkeypatch) -> None:
     monkeypatch.setattr(vi, "_resolve_path", lambda: str(tmp_path / "absent.db"))
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_inputs.py`
  Expected: FAIL — `AttributeError: module 'src.common.value_inputs' has no attribute
  'build_day_bars'` (and `newest_bar_before`).

- [x] **Step 3: The shape** — apply to `src/common/value_types.py`:

```diff
diff --git a/src/common/value_types.py b/src/common/value_types.py
--- a/src/common/value_types.py
+++ b/src/common/value_types.py
@@ -67,4 +67,17 @@ class PriceSeries(BaseModel):
 
 
+class DayBar(BaseModel):
+    """One settled session for the exit engine and the shadow record (spec §7, §6.8): the bar
+    and the technicals measured at its close. Unknown is None, never zero."""
+
+    date: date
+    open: float | None = None
+    close: float
+    sma20: float | None = None
+    sma50: float | None = None
+    rsi14: float | None = None
+    atr14: float | None = None
+
+
 class Classification(BaseModel):
     sector: str | None = None
```

- [x] **Step 4: The readers** — apply to `src/common/value_inputs.py` (everything stays read-only
  and imports no `src.value`; `build_day_bars` measures each technical on the whole history it is
  given, then returns only the sessions after `after`):

```diff
diff --git a/src/common/value_inputs.py b/src/common/value_inputs.py
--- a/src/common/value_inputs.py
+++ b/src/common/value_inputs.py
@@ -23,5 +23,5 @@ from typing import Any
 
 import pandas as pd
-from sqlalchemy import create_engine, select
+from sqlalchemy import create_engine, func, select
 from sqlalchemy.engine import Engine
 from sqlalchemy.orm import Session, sessionmaker
@@ -31,4 +31,5 @@ from src.common.config import get_config
 from src.common.value_types import (
     AnnualPeriod,
+    DayBar,
     InstantPoint,
     MarketFacts,
@@ -196,4 +197,40 @@ def build_price_series(bars: pd.DataFrame, spy: pd.DataFrame | None) -> PriceSer
 
 
+def _column(series: pd.Series, warmup: int = 0) -> list[float | None]:
+    """A series as floats, None where it is NaN or inside its first *warmup* rows."""
+    return [None if k + 1 < warmup or pd.isna(v) else float(v) for k, v in enumerate(series)]
+
+
+def build_day_bars(bars: pd.DataFrame, after: date | None = None) -> list[DayBar]:
+    """Every settled session after *after* (all of them when None) with the technicals the exit
+    engine reads at its close. *bars* is ``read_bars``'s frame: the whole history up to the
+    run's as_of, so a 50-day average is measured on real history, not on the days returned."""
+    if bars.empty:
+        return []
+    close = bars["close"].astype(float)
+    opens = _column(bars["open"]) if "open" in bars.columns else [None] * len(close)
+    sma20 = _column(close.rolling(20).mean())
+    sma50 = _column(close.rolling(50).mean())
+    rsi = _column(rsi14_series(close), 15)
+    atr = _column(atr14_series(bars["high"].astype(float), bars["low"].astype(float), close), 15)
+    out: list[DayBar] = []
+    for i, idx in enumerate(bars.index):
+        day = pd.Timestamp(idx).date()
+        if after is not None and day <= after:
+            continue
+        out.append(
+            DayBar(
+                date=day,
+                open=opens[i],
+                close=float(close.iloc[i]),
+                sma20=sma20[i],
+                sma50=sma50[i],
+                rsi14=rsi[i],
+                atr14=atr[i],
+            )
+        )
+    return out
+
+
 # ── I/O: read-only research.db ───────────────────────────────────────────────────────────────
 
@@ -260,12 +297,56 @@ def read_bars(session: Session, symbol: str, as_of: date) -> pd.DataFrame:
     ).scalars()
     data = [
-        (r.date, r.high, r.low, r.close, r.volume or 0.0)
+        (r.date, r.open, r.high, r.low, r.close, r.volume or 0.0)
         for r in rows
         if r.close is not None and r.high is not None and r.low is not None
     ]
-    frame = pd.DataFrame(data, columns=["date", "high", "low", "close", "volume"])
+    frame = pd.DataFrame(data, columns=["date", "open", "high", "low", "close", "volume"])
     return frame.set_index("date")
 
 
+def filings_coverage(session: Session, symbols: list[str]) -> tuple[int, int]:
+    """(names with a raw companyfacts payload, names asked about): how far the research worker's
+    sweep has filled research.db for a universe."""
+    if not symbols:
+        return 0, 0
+    have = session.scalar(
+        select(func.count())
+        .select_from(SymbolRow)
+        .join(CompanyFactsRawRow, CompanyFactsRawRow.cik == SymbolRow.cik)
+        .where(SymbolRow.symbol.in_(symbols))
+    )
+    return int(have or 0), len(symbols)
+
+
+def symbol_is_etf(session: Session, symbol: str) -> bool:
+    """The research directory's own ETF flag (spec §6.1: ETFs are not applicable)."""
+    row = session.get(SymbolRow, symbol)
+    return bool(row is not None and row.is_etf)
+
+
+def newest_bar_before(session: Session, symbol: str, before: date) -> date | None:
+    """The newest settled bar's date strictly before *before* (a bar dated today may still be
+    forming: the research page's on-demand refresh writes it during the session)."""
+    return session.execute(
+        select(DailyBarRow.date)
+        .where(DailyBarRow.symbol == symbol, DailyBarRow.date < before)
+        .order_by(DailyBarRow.date.desc())
+        .limit(1)
+    ).scalar_one_or_none()
+
+
+def closes_on(session: Session, symbols: list[str], day: date) -> dict[str, float]:
+    """Each symbol's close on *day*, read from the bars as they stand now (one fetch, so a split
+    or dividend adjustment applies to both ends of a return alike). Missing names are absent."""
+    if not symbols:
+        return {}
+    rows = session.execute(
+        select(DailyBarRow.symbol, DailyBarRow.close).where(
+            DailyBarRow.date == day, DailyBarRow.symbol.in_(symbols)
+        )
+    )
+    return {symbol: float(close) for symbol, close in rows if close is not None}
+
+
 def current_fingerprint_parts(session: Session, symbol: str) -> dict[str, Any]:
     """The cheap half of the ticker-file fingerprint (spec §6.9): the newest accession in
```

- [x] **Step 5: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_inputs.py tests/test_value_dry_run.py tests/test_value_fence.py`
  Expected: PASS (`test_value_inputs.py` 13). Then ruff check, ruff format --check and
  `.venv/bin/mypy src/common/value_inputs.py src/common/value_types.py` on the touched files — clean.

- [x] **Step 6: Commit**

  ```bash
  git add src/common/value_types.py src/common/value_inputs.py tests/test_value_inputs.py docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "feat(value): day bars and the read-only readers the shadow record needs"
  ```

---

### Task 3: The nightly sweep keeps every bar fresh, SPY's too

**Files:**
- Modify: `src/research/ingest/value_universe.py` (line 27; lines 37–41; line 55; lines 59–71)
- Modify: `tests/test_value_universe.py` (append after the scheduler test)

**Interfaces:**
- Produces: `BENCHMARKS = ("SPY",)`; `last_weekday_before(today: date) -> date`;
  `enqueue_value_universe(names=None, *, today=None, bars_only=None)` — the nightly call (no
  `names`) also queues `prices` for `BENCHMARKS`; bars are stale once older than
  `last_weekday_before(today)`.

- [x] **Step 1: Write the failing tests** — append to `tests/test_value_universe.py`:

  ```python


  def test_bars_are_stale_once_they_miss_the_last_weekday() -> None:
      from src.research.ingest.value_universe import last_weekday_before

      assert last_weekday_before(date(2026, 11, 2)) == date(2026, 10, 30)  # Monday -> Friday
      assert last_weekday_before(date(2026, 11, 4)) == date(2026, 11, 3)


  def test_the_nightly_sweep_refreshes_yesterdays_bars_and_spys(research_db, monkeypatch) -> None:
      from src.research.ingest import value_universe as sweep
      from src.research.store.models import DailyBarRow, IngestJobRow
      from src.research.store.session import research_session

      monday = date(2026, 11, 2)
      with research_session() as s:
          for symbol, last in (("FRESH", date(2026, 10, 30)), ("OLD", date(2026, 10, 29))):
              for i in range(260):
                  s.add(DailyBarRow(symbol=symbol, date=last - timedelta(days=i), close=1.0))
      monkeypatch.setattr(sweep, "value_names", lambda: ["FRESH", "OLD"])
      assert sweep.enqueue_value_universe(today=monday) == {
          "fundamentals": 0,
          "prices": 2,
          "no_cik": 2,
      }
      with research_session() as s:
          jobs = sorted((j.symbol, j.kind) for j in s.query(IngestJobRow))
      assert jobs == [("OLD", "prices"), ("SPY", "prices")]  # SPY's bars, never its filings
  ```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_universe.py`
  Expected: FAIL — `ImportError: cannot import name 'last_weekday_before'`.

- [x] **Step 3: The sweep** — apply to `src/research/ingest/value_universe.py` (the existing
  `test_the_sweep_queues_only_what_each_name_lacks` keeps passing: its "fresh" bars end the day
  before a Thursday):

```diff
diff --git a/src/research/ingest/value_universe.py b/src/research/ingest/value_universe.py
--- a/src/research/ingest/value_universe.py
+++ b/src/research/ingest/value_universe.py
@@ -25,5 +25,15 @@ log = logging.getLogger(__name__)
 MIN_BARS = 260
 FACTS_MAX_AGE = timedelta(days=1)
-BARS_MAX_AGE_DAYS = 4  # a long weekend is not stale
+# The value book's benchmark (spec §6.8): its bars are refreshed with the universe's, never its
+# filings (an ETF has none). SPY is the spreads book's underlying, so it is never in universe.yaml.
+BENCHMARKS = ("SPY",)
+
+
+def last_weekday_before(today: date) -> date:
+    """The newest weekday strictly before *today*: the session a nightly sweep must have."""
+    day = today - timedelta(days=1)
+    while day.weekday() >= 5:
+        day -= timedelta(days=1)
+    return day
 
 
@@ -36,9 +46,20 @@ def value_names() -> list[str]:
 
 def enqueue_value_universe(
-    names: list[str] | None = None, *, today: date | None = None
+    names: list[str] | None = None,
+    *,
+    today: date | None = None,
+    bars_only: tuple[str, ...] | None = None,
 ) -> dict[str, int]:
-    """Queue what each name lacks. Returns counts: fundamentals, prices, no_cik."""
-    names = names if names is not None else value_names()
+    """Queue what each name lacks. Returns counts: fundamentals, prices, no_cik.
+
+    Bars are stale once the newest is older than the last weekday before *today* (the value
+    book marks its shadow record every session). The nightly call (no *names*) also refreshes
+    the benchmark's bars (*bars_only*, default ``BENCHMARKS``)."""
+    if names is None:
+        names = value_names()
+        bars_only = BENCHMARKS if bars_only is None else bars_only
+    extra = [s for s in (bars_only or ()) if s not in names]
     today = today or datetime.now(UTC).date()
+    due = last_weekday_before(today)
     now = datetime.now(UTC).replace(tzinfo=None)
     counts = {"fundamentals": 0, "prices": 0, "no_cik": 0}
@@ -53,5 +74,5 @@ def enqueue_value_universe(
             for sym, n, last in s.execute(
                 select(DailyBarRow.symbol, func.count(), func.max(DailyBarRow.date))
-                .where(DailyBarRow.symbol.in_(names))
+                .where(DailyBarRow.symbol.in_([*names, *extra]))
                 .group_by(DailyBarRow.symbol)
             )
@@ -66,6 +87,7 @@ def enqueue_value_universe(
                 enqueue(symbol, "fundamentals")
                 counts["fundamentals"] += 1
+    for symbol in [*names, *extra]:
         n, last = bars.get(symbol, (0, None))
-        if n < MIN_BARS or last is None or (today - last).days > BARS_MAX_AGE_DAYS:
+        if n < MIN_BARS or last is None or last < due:
             enqueue(symbol, "prices")
             counts["prices"] += 1
```

- [x] **Step 4: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_universe.py tests/test_research_worker.py tests/test_research_materialize.py tests/test_value_dry_run.py`
  Expected: PASS (`test_value_universe.py` 12). Ruff check/format and
  `.venv/bin/mypy src/research/ingest/value_universe.py` clean.

- [x] **Step 5: Commit, then the section's Progress-log commit**

  ```bash
  git add src/research/ingest/value_universe.py tests/test_value_universe.py docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "feat(research): the value sweep wants yesterday's bar every night, and SPY's"
  ```

  Then run the full gate (Section exit), fill Task 3's row, and commit the plan alone, one command
  each:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "docs(plan): value book Part 2 Progress log - Section A"
  ```

---

## Section B — The exit engine and the shadow record (Tasks 4–6) · model: sonnet · effort: high

The exit engine as a pure state machine, the ranked record's arithmetic (and M5), then
`value.db`'s four shadow tables and `src/value/shadow.py`, which opens entries, fills them, steps
the legs, marks the horizons, closes what is finished and runs the ranked record. After this
section the record works on any `ValueScorecard` list; Section C feeds it every night.

**Spec to read:** §6.8 (all), §7 (all but §7.1), §12 (the "Therefore" bullets), §16 (the exit
engine and ranked-portfolio test bullets; revision 3's "Exits" bullet).

**Files the subagent reads:** this section; `src/common/value_types.py` (`DayBar`),
`src/common/value_inputs.py` (`build_day_bars`, `read_bars`, `closes_on`),
`src/common/config.py` (`ValueExitsCfg`), `src/value/schemas.py`, `src/value/rank.py`,
`src/value/store.py`, `src/value/ticker_file.py` (the persist pattern), `tests/test_value_rank.py`,
`tests/test_value_store.py` (the `value_db` fixture), `tests/value_fixtures.py` (signatures).

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **B1. Section A landed.** Tasks 1–3 ticked; record `git log --oneline main..HEAD | wc -l`
  (three task commits + one `docs(plan)` = 4 if nothing else was needed).
- [ ] **B2. Green, from the worktree root.** `.venv/bin/python -m pytest -q` = baseline + 8,
  `.venv/bin/ruff check .`, `.venv/bin/mypy src`; `FROZEN` holds v2:
  `.venv/bin/python -c "from src.value.ruleset import FROZEN; print(FROZEN)"` prints
  `{'v1': 'e1a1b3b096b1', 'v2': 'd07717fe5348'}`.
- [ ] **B3. The code Section B edits is where this plan says.** Each prints the line shown:

  ```bash
  grep -n 'higher there (spec §6.0: filed on the list where its rank score is higher)."""' src/value/rank.py   # 119:
  grep -n "^    for c in cards:$" src/value/rank.py                                      # 121:
  grep -n 'assert filed\["ETF"\] == "deep_value" and filed\["BAD"\] == "deep_value"' tests/test_value_rank.py   # 51:
  grep -n '^- ``value_runs`` - one row per scoring run (the dry run included).$' src/value/store.py   # 11:
  grep -n "^from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, create_engine, event$" src/value/store.py   # 21:
  grep -n "^_engine: Engine | None = None$" src/value/store.py                              # 93:
  ```

- [ ] **B4. The pieces Section B builds on exist.** Each prints at least one line:

  ```bash
  grep -n "^class DayBar" src/common/value_types.py
  grep -n "^def build_day_bars\|^def closes_on\|^def read_bars" src/common/value_inputs.py
  grep -n "^class ValueExitsCfg" src/common/config.py
  grep -n "^def rank_list\|^def percentiles" src/value/rank.py
  grep -n "^def value_session\|^def init_value_db" src/value/store.py
  ```

**Section exit:** three more task commits plus the section's `docs(plan)` commit; full gate green
with pytest = baseline + 47 (8 + 24 + 3 + 12); protected-file diff empty. Record the commit count.

---

### Task 4: The exit engine

**Files:** Create `src/value/exits.py`, `tests/test_value_exits.py`

**Interfaces:**
- Consumes: `ValueExitsCfg` (Task 1), `DayBar` (Task 2).
- Produces: `Policy = Literal["full", "value", "hold12"]`, `POLICIES`; `DayFacts(python_fair_value,
  effective_fair_value, latest_accn, piotroski, altman_z)`; `ExitEvent(day, kind, price, fraction,
  detail)` with `kind` in `arm, half, stop, trail, peak, thesis, remark, remark_below, catastrophe,
  time, proposal, fill`; `LegState` (pydantic, JSON-stored by Task 6) with `exit_return() -> float |
  None`; `open_leg(policy, *, entry_date, entry_price, atr14, fair_value, effective_fair_value,
  fv_accn, cfg) -> LegState`; `step(state, day: DayBar, facts: DayFacts | None, cfg) ->
  tuple[LegState, list[ExitEvent]]`; `benchmark_return(fills: list[tuple[date, float]],
  benchmark_open: dict[date, float], entry: float) -> float | None`.

The transitions `step` implements, in the order it applies them on each session (ruling 14):

| # | When | What happens | Policies |
|---|---|---|---|
| 1 | a sale is pending from the last close | it fills at this session's open (the close without an open); the leg closes when nothing remains | all |
| 2 | every close | sessions +1; highest close; position value and max drawdown | all |
| 3 | a new accession with a Python fair value | `remark`: fair value (and the effective one) re-marked, up or down | all |
| 4 | F-score ≤ 3, or Altman Z < 1.8, or (close < SMA50 and Python FV < 90% of the close) | `thesis`: sell everything at the next open; stop here | all |
| 4b | only the effective FV is < 90% of the close (under SMA50) | `proposal`: a tap, never a sale | all |
| 5 | close < stop | `stop` (not armed) or `trail` (armed): sell everything | full |
| 6 | not armed, FV > cost, close ≥ cost + 50% of (FV − cost) | `arm` | full |
| 7 | not yet half sold, close ≥ effective FV | `half`: sell 50% at the next open | full, value |
| 8 | armed | the stop rises to max(highest close − k × ATR, cost), never falls; k = 3, or 2 once half is sold | full |
| 9 | armed, and (a close ≥ FV seen and close < SMA20) or (RSI > 75 seen while armed and RSI < 70) | `peak`: sell the rest | full |
| 10 | close ≤ 70% of cost | `catastrophe`: sell everything | value, hold12 |
| 11 | re-marked this session and the new Python FV < close | `remark_below`: sell the rest | value |
| 11b | re-marked and only the effective FV < close | `proposal` | value |
| 12 | 252 sessions held | `time`: sell everything | hold12 |

- [x] **Step 1: Write the failing tests** — `tests/test_value_exits.py` (every number below was
  computed by hand and matched by the prototype):

```python
"""The exit engine as a state machine (value book spec §7, §16): stop, arm, half at fair value,
trail, peak, thesis, catastrophe, time; fair value re-marked only on a new filing; no automatic
exit reads the effective (Claude) fair value."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.config import ValueExitsCfg
from src.common.value_types import DayBar
from src.value.exits import (
    POLICIES,
    DayFacts,
    LegState,
    benchmark_return,
    open_leg,
    step,
)

CFG = ValueExitsCfg()
D0 = date(2026, 11, 2)
ACCN = "0000000001-26-000001"


def bar(i: int, close: float, **kw: float | None) -> DayBar:
    return DayBar(date=D0 + timedelta(days=i), close=close, **kw)


def leg(policy: str = "full", fv: float | None = 120.0, atr: float | None = 2.0, **kw) -> LegState:
    return open_leg(
        policy,  # type: ignore[arg-type]
        entry_date=D0,
        entry_price=100.0,
        atr14=atr,
        fair_value=fv,
        effective_fair_value=kw.get("effective", fv),
        fv_accn=ACCN,
        cfg=CFG,
    )


def run(state: LegState, bars: list[DayBar], facts: DayFacts | None = None):
    events = []
    for b in bars:
        state, ev = step(state, b, facts, CFG)
        events += ev
    return state, [(e.kind, round(e.fraction, 6)) for e in events]


def test_full_opens_with_the_initial_stop_never_wider_than_fifteen_percent() -> None:
    assert leg(atr=2.0).stop == pytest.approx(94.0)  # 100 - 3 x 2
    assert leg(atr=10.0).stop == pytest.approx(85.0)  # 3 x ATR would be 30% below: capped
    assert leg(atr=None).stop == pytest.approx(85.0)
    assert leg("value").stop is None and leg("hold12").stop is None


def test_a_close_below_the_stop_sells_everything_at_the_next_open() -> None:
    state, events = run(leg(), [bar(1, 93.0), bar(2, 91.0, open=92.0)])
    assert events == [("stop", 1.0), ("fill", 1.0)]
    assert state.closed and state.exit_date == D0 + timedelta(days=2)
    assert state.exit_return() == pytest.approx(-0.08)  # sold at the 92.00 open


def test_the_trail_arms_half_way_to_fair_value_and_is_never_lowered() -> None:
    state, events = run(leg(), [bar(1, 111.0, atr14=2.0)])
    assert events == [("arm", 0.0)] and state.armed
    assert state.stop == pytest.approx(105.0)  # highest close 111 - 3 x 2
    state, events = run(state, [bar(2, 109.0, atr14=4.0)])
    assert events == [] and state.stop == pytest.approx(105.0)  # 111 - 12 = 99 would lower it
    state, events = run(state, [bar(3, 104.0, atr14=4.0)])
    assert events == [("trail", 1.0)]


def test_half_sells_at_fair_value_then_the_trail_tightens_to_two_atr() -> None:
    state, events = run(leg(), [bar(1, 121.0, atr14=2.0)])
    assert events == [("arm", 0.0), ("half", 0.5)]
    assert state.stop == pytest.approx(117.0)  # 121 - 2 x 2 once half is sold
    state, events = run(state, [bar(2, 123.0, open=122.0, atr14=2.0, sma20=115.0)])
    assert events == [("fill", 0.5)] and state.remaining == pytest.approx(0.5)
    assert state.stop == pytest.approx(119.0)
    state, events = run(state, [bar(3, 118.0, atr14=2.0), bar(4, 116.0, open=117.0)])
    assert events == [("trail", 0.5), ("fill", 0.5)]
    assert state.exit_return() == pytest.approx(0.195)  # (0.5 x 122 + 0.5 x 117) / 100 - 1
    assert state.sells == 2


def test_the_peak_signal_below_the_twenty_day_average_after_fair_value() -> None:
    state, _ = run(leg(fv=110.0, atr=2.0), [bar(1, 111.0)])  # arm and half, no ATR: stop stays
    state, events = run(state, [bar(2, 108.0, open=111.0, sma20=109.0)])
    assert events == [("fill", 0.5), ("peak", 0.5)]


def test_the_peak_signal_when_rsi_falls_back_through_seventy() -> None:
    state, events = run(leg(fv=200.0), [bar(1, 160.0, rsi14=80.0)])
    assert events == [("arm", 0.0)] and state.rsi_hot
    state, events = run(state, [bar(2, 161.0, rsi14=68.0)])
    assert events == [("peak", 1.0)]


@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize(
    ("facts", "sma50", "detail"),
    [
        (DayFacts(piotroski=3.0), None, "F-score 3"),
        (DayFacts(altman_z=1.5), None, "Altman Z 1.50"),
        (DayFacts(), 120.0, "fair value"),
    ],
)
def test_thesis_exits_fire_under_every_policy(policy, facts, sma50, detail) -> None:
    fv = 90.0 if detail == "fair value" else 120.0  # 90 < 0.9 x 105 with the close under SMA50
    state, events = run(leg(policy, fv=fv), [bar(1, 105.0, sma50=sma50)], facts)
    assert events == [("thesis", 1.0)]
    assert state.pending_reason == "thesis"


def test_value_sells_half_at_fair_value_and_rides_the_rest_until_a_remark_below() -> None:
    state, events = run(leg("value"), [bar(1, 121.0), bar(2, 130.0, open=121.0), bar(3, 150.0)])
    assert events == [("half", 0.5), ("fill", 0.5)]  # above fair value, no new filing: hold
    newer = DayFacts(python_fair_value=140.0, latest_accn="0000000001-26-000002")
    state, events = run(state, [bar(4, 150.0)], newer)
    assert events == [("remark", 0.0), ("remark_below", 0.5)]
    state, events = run(state, [bar(5, 148.0, open=149.0)], newer)
    assert events == [("fill", 0.5)] and state.closed
    assert state.exit_return() == pytest.approx(0.35)  # (0.5 x 121 + 0.5 x 149) / 100 - 1


@pytest.mark.parametrize("policy", ["value", "hold12"])
def test_the_catastrophe_stop_is_thirty_percent_below_cost(policy) -> None:
    _, events = run(leg(policy), [bar(1, 70.5)])
    assert events == []
    _, events = run(leg(policy), [bar(1, 70.0)])
    assert events == [("catastrophe", 1.0)]


def test_hold12_sells_after_252_sessions() -> None:
    bars = [bar(i, 101.0) for i in range(1, 253)]
    state, events = run(leg("hold12"), bars)
    assert events == [("time", 1.0)] and state.sessions == 252
    state, events = run(state, [bar(253, 101.0, open=102.0)])
    assert events == [("fill", 1.0)] and state.exit_return() == pytest.approx(0.02)


def test_fair_value_moves_only_on_a_new_filing() -> None:
    same = DayFacts(python_fair_value=150.0, latest_accn=ACCN)
    state, events = run(leg("value"), [bar(1, 105.0)], same)
    assert events == [] and state.fair_value == 120.0  # price and news never move it
    newer = DayFacts(python_fair_value=150.0, latest_accn="0000000001-26-000002")
    state, events = run(state, [bar(2, 105.0)], newer)
    assert events == [("remark", 0.0)] and state.fair_value == 150.0


def test_no_automatic_exit_reads_the_effective_fair_value() -> None:
    """Revision 3: an exit only Claude's (effective) value would fire is a tap proposal. The
    half-sale target is the one place the effective value is read, by design."""
    newer = DayFacts(
        python_fair_value=125.0, effective_fair_value=100.0, latest_accn="0000000001-26-000002"
    )
    state, events = run(leg("value", effective=120.0), [bar(1, 110.0)], newer)
    assert ("remark_below", 0.5) not in events and ("remark_below", 1.0) not in events
    assert ("proposal", 0.0) in events
    assert events[-1] == ("half", 0.5)  # 110 >= the effective 100: the half-sale reads it
    state, events = run(
        leg("hold12", fv=120.0, effective=100.0), [bar(1, 115.0, sma50=120.0)], DayFacts()
    )
    assert events == [("proposal", 0.0)] and state.pending == 0.0


def test_a_closed_leg_does_not_move() -> None:
    state, _ = run(leg(), [bar(1, 93.0), bar(2, 91.0, open=92.0)])
    after, events = step(state, bar(3, 200.0), None, CFG)
    assert after is state and events == []


def test_max_drawdown_is_the_worst_fall_from_the_best_close() -> None:
    state, _ = run(leg("value", fv=200.0), [bar(1, 110.0), bar(2, 99.0)])
    assert state.max_drawdown == pytest.approx(0.99 / 1.10 - 1.0)


def test_the_benchmark_return_matches_the_fills() -> None:
    d1, d2 = D0 + timedelta(days=5), D0 + timedelta(days=9)
    opens = {d1: 520.0, d2: 500.0}
    assert benchmark_return([(d1, 0.5), (d2, 0.5)], opens, 500.0) == pytest.approx(0.02)
    assert benchmark_return([(d1, 0.5), (D0, 0.5)], opens, 500.0) is None
    assert benchmark_return([], opens, 500.0) is None
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_exits.py`
  Expected: collection error, `ModuleNotFoundError: No module named 'src.value.exits'`.

- [x] **Step 3: The engine** — `src/value/exits.py`:

```python
"""The exit engine (spec §7): a deterministic state machine, one leg per policy. Pure: no I/O.

Evaluated once a day on the close; a sale the close signals fills at the next session's open.
Three policies run side by side on every shadow entry (spec §7):

- ``full``: the initial stop, the half-way arm into a Chandelier trail, half sold at fair
  value with the trail tightened, the peak signals, the thesis exits;
- ``value`` (pre-registered as the live policy): half sold at fair value; the rest only on a
  thesis exit, a fair value re-marked below the price, or the catastrophe stop;
- ``hold12``: 252 sessions, earlier only on a thesis exit or the catastrophe stop.

Every exit that would send without a tap reads **Python's** fair value only (revision 3). The
half-sale target reads the effective fair value (Python's on the baseline track; Claude's
clamped value on Part 4's track). An exit only the effective value would fire is a ``proposal``
event: it waits for a tap and sells nothing. Fair value is re-marked only when a new filing lands
(a new accession). §7.1's shock stops and re-evaluations are Part 3.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Literal

from pydantic import BaseModel

from src.common.config import ValueExitsCfg
from src.common.value_types import DayBar

Policy = Literal["full", "value", "hold12"]
POLICIES: tuple[Policy, Policy, Policy] = ("full", "value", "hold12")
EventKind = Literal[
    "arm",
    "half",
    "stop",
    "trail",
    "peak",
    "thesis",
    "remark",
    "remark_below",
    "catastrophe",
    "time",
    "proposal",
    "fill",
]
_DONE = 1e-9

Sell = Callable[[float, "EventKind", str], None]
Note = Callable[["EventKind", str], None]


class DayFacts(BaseModel):
    """What the night's scorecard says about the name. ``effective_fair_value`` equals Python's
    on the baseline track; Part 4's Claude track sets its own."""

    python_fair_value: float | None = None
    effective_fair_value: float | None = None
    latest_accn: str | None = None
    piotroski: float | None = None
    altman_z: float | None = None


class ExitEvent(BaseModel):
    day: date
    kind: EventKind
    price: float | None = None
    fraction: float = 0.0  # of the original position
    detail: str = ""


class LegState(BaseModel):
    """One policy's simulated holding of one shadow entry. Fractions are of the original
    position; ``proceeds`` is the sum of fraction x fill price."""

    policy: Policy
    entry_date: date
    entry_price: float
    fair_value: float | None  # Python's, re-marked only on a new filing
    effective_fair_value: float | None
    fv_accn: str | None
    stop: float | None = None
    armed: bool = False
    half_sold: bool = False
    above_fv_seen: bool = False
    rsi_hot: bool = False
    highest_close: float
    sessions: int = 0
    remaining: float = 1.0
    proceeds: float = 0.0
    pending: float = 0.0  # the fraction to sell at the next session's open
    pending_reason: str = ""
    sells: int = 0
    closed: bool = False
    exit_date: date | None = None
    peak_value: float = 1.0  # position value / cost, at its best close
    max_drawdown: float = 0.0  # a fraction, <= 0

    def exit_return(self) -> float | None:
        """Return over cost once every share is sold; None while any is held."""
        return self.proceeds / self.entry_price - 1.0 if self.closed else None


def open_leg(
    policy: Policy,
    *,
    entry_date: date,
    entry_price: float,
    atr14: float | None,
    fair_value: float | None,
    effective_fair_value: float | None,
    fv_accn: str | None,
    cfg: ValueExitsCfg,
) -> LegState:
    """The plan written at entry (spec §7). ``full`` starts with the initial stop: cost - 3 x
    ATR(14), never more than 15% below cost (the 15% floor alone when ATR is unknown)."""
    stop: float | None = None
    if policy == "full":
        floor = entry_price * (1.0 - cfg.initial_stop_max_pct / 100.0)
        stop = floor if atr14 is None else max(entry_price - cfg.initial_stop_atr * atr14, floor)
    return LegState(
        policy=policy,
        entry_date=entry_date,
        entry_price=entry_price,
        fair_value=fair_value,
        effective_fair_value=effective_fair_value,
        fv_accn=fv_accn,
        stop=stop,
        highest_close=entry_price,
    )


def step(
    state: LegState, day: DayBar, facts: DayFacts | None, cfg: ValueExitsCfg
) -> tuple[LegState, list[ExitEvent]]:
    """Advance one leg by one session: fill yesterday's signal at today's open, then read
    today's close. Never mutates *state*."""
    if state.closed:
        return state, []
    s = state.model_copy()
    events: list[ExitEvent] = []

    if s.pending > _DONE:
        price = day.open if day.open is not None else day.close
        fraction = min(s.pending, s.remaining)
        s.proceeds += fraction * price
        s.remaining -= fraction
        s.sells += 1
        events.append(
            ExitEvent(
                day=day.date, kind="fill", price=price, fraction=fraction, detail=s.pending_reason
            )
        )
        s.pending, s.pending_reason = 0.0, ""
        if s.remaining <= _DONE:
            s.remaining, s.closed, s.exit_date = 0.0, True, day.date
            return s, events

    close = day.close
    s.sessions += 1
    s.highest_close = max(s.highest_close, close)
    value = (s.proceeds + s.remaining * close) / s.entry_price
    s.peak_value = max(s.peak_value, value)
    s.max_drawdown = min(s.max_drawdown, value / s.peak_value - 1.0)

    def sell(fraction: float, kind: EventKind, detail: str) -> None:
        s.pending = min(max(s.pending, fraction), s.remaining)
        s.pending_reason = kind
        events.append(
            ExitEvent(day=day.date, kind=kind, price=close, fraction=s.pending, detail=detail)
        )

    def note(kind: EventKind, detail: str) -> None:
        events.append(ExitEvent(day=day.date, kind=kind, price=close, detail=detail))

    # A new filing re-marks fair value, up or down (spec §7). Price and news never do.
    remarked = False
    if (
        facts is not None
        and facts.latest_accn is not None
        and facts.latest_accn != s.fv_accn
        and facts.python_fair_value is not None
    ):
        old = s.fair_value
        s.fair_value, s.fv_accn = facts.python_fair_value, facts.latest_accn
        s.effective_fair_value = (
            facts.effective_fair_value
            if facts.effective_fair_value is not None
            else facts.python_fair_value
        )
        remarked = True
        note("remark", f"fair value {old} -> {s.fair_value} ({facts.latest_accn})")

    # Thesis exits: every policy, Python's numbers only.
    if facts is not None:
        if facts.piotroski is not None and facts.piotroski <= cfg.thesis_piotroski_max:
            sell(s.remaining, "thesis", f"F-score {facts.piotroski:.0f}")
            return s, events
        if facts.altman_z is not None and facts.altman_z < cfg.thesis_altman_z_below:
            sell(s.remaining, "thesis", f"Altman Z {facts.altman_z:.2f}")
            return s, events
    bar = cfg.thesis_fv_below_price_pct / 100.0
    below_trend = day.sma50 is not None and close < day.sma50
    if below_trend and s.fair_value is not None and s.fair_value < close * bar:
        sell(s.remaining, "thesis", f"fair value {s.fair_value:.2f} below {bar:.0%} of the price")
        return s, events
    if below_trend and s.effective_fair_value is not None and s.effective_fair_value < close * bar:
        note("proposal", "the effective fair value alone is below 90% of the price: a tap")

    if s.policy == "full":
        _full(s, close, day, cfg, sell, note)
    elif s.policy == "value":
        floor = s.entry_price * (1.0 - cfg.catastrophe_stop_pct / 100.0)
        if close <= floor:
            sell(s.remaining, "catastrophe", f"close {close:.2f} <= {floor:.2f}")
        elif remarked and s.fair_value is not None and s.fair_value < close:
            sell(s.remaining, "remark_below", f"re-marked {s.fair_value:.2f} below the price")
        else:
            if remarked and s.effective_fair_value is not None and s.effective_fair_value < close:
                note("proposal", "the effective fair value alone was re-marked below the price")
            _half_at_fair_value(s, close, cfg, sell)
    else:
        floor = s.entry_price * (1.0 - cfg.catastrophe_stop_pct / 100.0)
        if close <= floor:
            sell(s.remaining, "catastrophe", f"close {close:.2f} <= {floor:.2f}")
        elif s.sessions >= cfg.hold12_sessions:
            sell(s.remaining, "time", f"{s.sessions} sessions")
    return s, events


def _half_at_fair_value(s: LegState, close: float, cfg: ValueExitsCfg, sell: Sell) -> None:
    target = s.effective_fair_value
    if not s.half_sold and target is not None and close >= target:
        s.half_sold = True
        sell(cfg.half_sell_pct / 100.0, "half", f"close {close:.2f} >= fair value {target:.2f}")


def _full(
    s: LegState, close: float, day: DayBar, cfg: ValueExitsCfg, sell: Sell, note: Note
) -> None:
    if s.stop is not None and close < s.stop:
        kind: EventKind = "trail" if s.armed else "stop"
        sell(s.remaining, kind, f"close {close:.2f} < stop {s.stop:.2f}")
        return
    fv = s.fair_value
    if (
        not s.armed
        and fv is not None
        and fv > s.entry_price
        and close >= s.entry_price + cfg.arm_at_pct / 100.0 * (fv - s.entry_price)
    ):
        s.armed = True
        note("arm", f"close {close:.2f} past the half-way mark to {fv:.2f}")
    _half_at_fair_value(s, close, cfg, sell)
    if s.effective_fair_value is not None and close >= s.effective_fair_value:
        s.above_fv_seen = True
    if not s.armed:
        return
    k = cfg.trail_atr_after_half if s.half_sold else cfg.trail_atr
    if day.atr14 is not None:
        chandelier = max(s.highest_close - k * day.atr14, s.entry_price)
        if s.stop is None or chandelier > s.stop:
            s.stop = chandelier  # a stop is never lowered
    if day.rsi14 is not None and day.rsi14 > cfg.peak_rsi_high:
        s.rsi_hot = True
    off_peak = s.above_fv_seen and day.sma20 is not None and close < day.sma20
    rsi_turn = s.rsi_hot and day.rsi14 is not None and day.rsi14 < cfg.peak_rsi_cross
    if off_peak:
        sell(s.remaining, "peak", "a close below the 20-day SMA after fair value")
    elif rsi_turn:
        sell(s.remaining, "peak", f"RSI(14) back through {cfg.peak_rsi_cross:.0f}")


def benchmark_return(
    fills: list[tuple[date, float]], benchmark_open: dict[date, float], entry: float
) -> float | None:
    """What the same fractions would have made in the benchmark, bought at the entry session's
    open and sold at each fill's open. None when any fill date has no benchmark bar."""
    if entry <= 0 or not fills:
        return None
    proceeds = 0.0
    for day, fraction in fills:
        px = benchmark_open.get(day)
        if px is None:
            return None
        proceeds += fraction * px
    return proceeds / entry - 1.0
```

- [x] **Step 4: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_exits.py`
  Expected: 24 passed. Ruff check/format and `.venv/bin/mypy src/value/exits.py` clean.

- [x] **Step 5: Commit**

  ```bash
  git add src/value/exits.py tests/test_value_exits.py docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "feat(value): the exit engine, a pure state machine with three policies"
  ```

---

### Task 5: The ranked arithmetic and the filed list (M5)

**Files:** Create `src/value/ranked.py`, `tests/test_value_ranked.py`; modify `src/value/rank.py`
(lines 119–121), `tests/test_value_rank.py` (line 51)

**Interfaces:**
- Produces: `Bucket`, `BUCKETS = ("top", "bottom", "all")`, `MIN_NAMES = 10`;
  `buckets(scores: dict[str, float | None]) -> dict[Bucket, list[str]] | None`;
  `equal_weight_return(members, start: dict[str, float], end: dict[str, float]) -> tuple[float |
  None, int]` (mean return, members dropped); `is_new_month(last_formed: date | None, as_of: date)
  -> bool`. `filed_lists` returns no entry for an unscored name.

- [x] **Step 1: Write the failing tests** — `tests/test_value_ranked.py`:

```python
"""The ranked monthly record's arithmetic (value book spec §6.8): tenths, ties, dropped members
and the monthly formation date."""

from __future__ import annotations

from datetime import date

import pytest

from src.value.ranked import buckets, equal_weight_return, is_new_month


def test_the_tenths_are_n_over_ten_names_ties_broken_by_symbol() -> None:
    scores: dict[str, float | None] = {f"N{i:02d}": float(i) for i in range(25)}
    scores["TIE"] = 24.0  # ties N24 at the top: the symbol orders them
    scores["NONE"] = None  # unscored: never in a portfolio
    picked = buckets(scores)
    assert picked is not None
    assert picked["top"] == ["N24", "TIE"]  # 26 scored names: 26 // 10 = 2
    assert picked["bottom"] == ["N01", "N00"]
    assert len(picked["all"]) == 26 and "NONE" not in picked["all"]
    assert buckets({f"N{i}": float(i) for i in range(9)}) is None  # under ten: no tenth


def test_equal_weight_drops_and_counts_members_without_a_close() -> None:
    ret, missing = equal_weight_return(
        ["A", "B", "C"], {"A": 10.0, "B": 20.0, "C": 5.0}, {"A": 11.0, "B": 19.0}
    )
    assert ret == pytest.approx((0.10 - 0.05) / 2)
    assert missing == 1
    assert equal_weight_return(["A"], {}, {}) == (None, 1)


def test_a_formation_on_the_first_run_of_each_month() -> None:
    assert is_new_month(None, date(2026, 11, 2))
    assert not is_new_month(date(2026, 11, 2), date(2026, 11, 30))
    assert is_new_month(date(2026, 11, 2), date(2026, 12, 1))
    assert is_new_month(date(2026, 12, 1), date(2027, 1, 4))
```

  …and apply to `tests/test_value_rank.py` (M5, ruling 3):

```diff
diff --git a/tests/test_value_rank.py b/tests/test_value_rank.py
--- a/tests/test_value_rank.py
+++ b/tests/test_value_rank.py
@@ -49,5 +49,5 @@ def test_a_name_on_both_lists_is_filed_where_it_ranks_higher() -> None:
     deep["MID"] = deep["MID"].model_copy(update={"score": 0.1})
     assert filed_lists(cards, deep, growth)["MID"] == "quality_growth"
-    assert filed["ETF"] == "deep_value" and filed["BAD"] == "deep_value"
+    assert "ETF" not in filed and "BAD" not in filed  # not scored: filed on neither list
 
 
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_ranked.py tests/test_value_rank.py`
  Expected: collection error (`No module named 'src.value.ranked'`) and, once that exists, the M5
  assertion fails (`assert "ETF" not in filed`).

- [x] **Step 3: The arithmetic** — `src/value/ranked.py`:

```python
"""The ranked monthly record's arithmetic (spec §6.8). Pure: no I/O.

Each month, per list, every scored name of the evidence universe is ordered by its rank score;
the top tenth, the bottom tenth and the whole scored universe become hypothetical equal-weight
portfolios held to the next formation, each measured against SPY (Gray & Carlisle's decile
test). The score orders names and never feeds a gate or a size.
"""

from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Literal

Bucket = Literal["top", "bottom", "all"]
BUCKETS: tuple[Bucket, Bucket, Bucket] = ("top", "bottom", "all")
MIN_NAMES = 10  # below this a tenth is empty and nothing is formed


def buckets(scores: dict[str, float | None]) -> dict[Bucket, list[str]] | None:
    """The three portfolios: names ordered by score (highest first, ties by symbol), the top
    and bottom ``n // 10`` and all of them. None when fewer than ten names have a score."""
    ordered = sorted(
        ((score, symbol) for symbol, score in scores.items() if score is not None),
        key=lambda pair: (-pair[0], pair[1]),
    )
    k = len(ordered) // 10
    if len(ordered) < MIN_NAMES or k == 0:
        return None
    names = [symbol for _, symbol in ordered]
    return {"top": names[:k], "bottom": names[-k:], "all": names}


def equal_weight_return(
    members: list[str], start: dict[str, float], end: dict[str, float]
) -> tuple[float | None, int]:
    """The mean of the members' close-to-close returns, and how many members were dropped for
    lacking a close at either end (a halted or delisted name: survivorship, printed)."""
    returns = [end[m] / start[m] - 1.0 for m in members if start.get(m, 0.0) > 0.0 and m in end]
    return (mean(returns) if returns else None), len(members) - len(returns)


def is_new_month(last_formed: date | None, as_of: date) -> bool:
    """A new formation on the first nightly run whose session falls in a later month."""
    return last_formed is None or (as_of.year, as_of.month) != (last_formed.year, last_formed.month)
```

- [x] **Step 4: M5** — apply to `src/value/rank.py`:

```diff
diff --git a/src/value/rank.py b/src/value/rank.py
--- a/src/value/rank.py
+++ b/src/value/rank.py
@@ -117,7 +117,10 @@ def filed_lists(
 ) -> dict[str, ListName]:
     """Deep value, unless the name passes health and the quality-growth entry rule and ranks
-    higher there (spec §6.0: filed on the list where its rank score is higher)."""
+    higher there (spec §6.0: filed on the list where its rank score is higher). A name that is
+    not scored (an ETF, a REIT, pre-profit, or data quality not passing) is filed on neither."""
     out: dict[str, ListName] = {}
     for c in cards:
+        if c.data_quality != "pass" or c.not_applicable_reason is not None:
+            continue
         ev = c.lists.get("quality_growth")
         qualifies = c.health == "pass" and ev is not None and ev.entry == "pass"
```

- [x] **Step 5: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_ranked.py tests/test_value_rank.py tests/test_value_dry_run.py`
  Expected: PASS (3 + 5 + 3). Ruff and `.venv/bin/mypy src/value/ranked.py src/value/rank.py` clean.

- [x] **Step 6: Commit**

  ```bash
  git add src/value/ranked.py src/value/rank.py tests/test_value_ranked.py tests/test_value_rank.py docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "feat(value): the ranked record's arithmetic; unscored names are filed on no list (M5)"
  ```

---

### Task 6: The shadow tables and the shadow record

**Files:** Modify `src/value/store.py` (lines 11–12, 21, insert before line 93); create
`src/value/shadow.py`, `src/value/report.py` (a two-line stub), `tests/test_value_shadow.py`

**Interfaces:**
- Consumes: Task 4's `POLICIES`, `DayFacts`, `LegState`, `open_leg`, `step`, `benchmark_return`;
  Task 5's `BUCKETS`, `buckets`, `equal_weight_return`, `is_new_month`; `rank.rank_list`; Task 2's
  `build_day_bars`, `read_bars`, `closes_on`. `HORIZONS` lives in the pure `src/value/report.py`
  (so the report and the record share one definition without the pure module importing I/O);
  this task creates that module as a stub, and Task 10 replaces it whole.
- Produces: tables `value_shadow` (`ValueShadowRow`), `value_shadow_legs` (`ValueShadowLegRow`),
  `value_shadow_events` (`ValueShadowEventRow`), `value_ranked` (`ValueRankedRow`); in
  `src.value.shadow`: `BENCHMARK = "SPY"`, `TRACK = "baseline"`, `HORIZONS` (re-exported),
  `ShadowSummary`, `day_facts(card, list_name) -> DayFacts | None`, `blocking_keys`,
  `open_signals(vs, cards, tags, atr, *, live_policy, now) -> dict[str, int]`,
  `load_bars(rs, symbols, as_of) -> dict[str, list[DayBar]]`, `fill_pending(vs, market, cfg) ->
  (filled, voided)`, `step_legs(vs, market, cards_by_symbol, cfg) -> (events, frozen)`,
  `mark_horizons(vs, market) -> (marked, frozen)`, `close_finished(vs, as_of) -> int`,
  `run_ranked(vs, rs, cards, evidence, *, as_of, version, digest) -> (formed, closed)`,
  `process(vs, rs, cards, *, tags, atr, evidence, as_of, cfg, version, digest, now) ->
  ShadowSummary`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_shadow.py`:

```python
"""The shadow record (value book spec §6.8, §7, §12): READY entries at the next open, control
groups, re-entry, the three policies' legs, fixed-horizon returns against SPY, the split guard
and the ranked monthly record."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import src.value.store as store
from src.common.config import get_config
from src.common.value_types import DayBar
from src.research.store.models import Base, DailyBarRow
from src.value import shadow
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueRankedRow,
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
    init_value_db,
    value_session,
)
from tests.value_fixtures import AS_OF, financials, inputs

CFG = get_config().value
NOW = datetime(2026, 4, 1, 10, 0)
SESSIONS = [d.date() for d in pd.bdate_range(start=AS_OF, periods=140)]  # SESSIONS[0] = AS_OF


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def bars(closes: list[float], *, opens: list[float] | None = None, start: int = 0, **kw):
    """DayBars on consecutive sessions from SESSIONS[start]."""
    return [
        DayBar(
            date=SESSIONS[start + i],
            close=c,
            open=(opens[i] if opens else c),
            **kw,
        )
        for i, c in enumerate(closes)
    ]


def ready(symbol: str = "STDY", close: float = 30.0):
    return build_scorecard(inputs(symbol=symbol, close=close), CFG)


def sick(symbol: str = "SICK", close: float = 25.0):
    fin = financials(net_income=[300, -266, -238, 212, 187])  # health fails, still cheap
    return build_scorecard(inputs(symbol=symbol, close=close, fin=fin), CFG)


def _open(cards, tags=None, atr=None):
    tags = tags or {c.symbol: "trading" for c in cards}
    with value_session() as s:
        return shadow.open_signals(s, cards, tags, atr or {}, live_policy="value", now=NOW)


def _rows():
    with value_session() as s:
        return [
            (r.kind, r.list_name, r.symbol, r.status)
            for r in s.scalars(select(ValueShadowRow).order_by(ValueShadowRow.id))
        ]


def test_a_ready_signal_waits_for_the_next_sessions_open(value_db) -> None:
    assert _open([ready()]) == {"ready": 2, "control_valuation": 0, "control_health": 0}
    market = {
        "STDY": bars([30.0, 31.5], opens=[29.0, 31.0]),
        "SPY": bars([500.0, 502.0], opens=[499.0, 501.0]),
    }
    with value_session() as s:
        assert shadow.fill_pending(s, market, CFG) == (2, 0)
    with value_session() as s:
        row = s.scalars(select(ValueShadowRow)).first()
        assert (row.status, row.entry_date, row.entry_price, row.spy_entry_price) == (
            "open",
            SESSIONS[1],
            31.0,
            501.0,
        )
        policies = sorted(leg.policy for leg in s.scalars(select(ValueShadowLegRow)))
        assert policies == ["full", "full", "hold12", "hold12", "value", "value"]


def test_control_groups_enter_only_on_a_night_with_a_new_ready_entry(value_db) -> None:
    cards = [ready(), ready("DEAR", 45.0), sick()]  # DEAR: deep WAIT, growth READY
    assert _open(cards) == {"ready": 3, "control_valuation": 1, "control_health": 2}
    assert ("control_valuation", "deep_value", "DEAR", "pending") in _rows()
    assert ("control_health", "quality_growth", "SICK", "pending") in _rows()
    # The next night: the same names, nothing new is READY, so no control enters either.
    assert _open(cards) == {"ready": 0, "control_valuation": 0, "control_health": 0}
    market = {s: bars([30.0, 31.0]) for s in ("STDY", "DEAR", "SICK", "SPY")}
    with value_session() as s:
        assert shadow.fill_pending(s, market, CFG) == (6, 0)
    with value_session() as s:
        assert len(s.scalars(select(ValueShadowLegRow)).all()) == 9  # READY entries only: 3 x 3


def test_a_looked_up_name_never_enters_the_shadow_record(value_db) -> None:
    assert _open([ready()], tags={"STDY": "lookup"})["ready"] == 0


def test_a_ready_key_reenters_only_once_its_live_policy_leg_has_exited(value_db) -> None:
    _open([ready()])
    market = {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0, 500.0])}
    with value_session() as s:
        shadow.fill_pending(s, market, CFG)
    assert _open([ready()])["ready"] == 0  # the value legs still hold
    with value_session() as s:
        for leg in s.scalars(select(ValueShadowLegRow).where(ValueShadowLegRow.policy == "value")):
            leg.closed = True
    assert _open([ready()])["ready"] == 2


def test_the_legs_run_each_policy_and_record_every_event(value_db) -> None:
    _open([ready()], atr={"STDY": 0.6})  # full's stop: max(31 - 1.8, 31 x 0.85) = 29.2
    closes = [30.0, 31.0, 29.0, 28.0]
    market = {
        "STDY": bars(closes, opens=[30.0, 31.0, 30.0, 28.5]),
        "SPY": bars([500.0] * 4, opens=[500.0, 500.0, 505.0, 510.0]),
    }
    with value_session() as s:
        shadow.fill_pending(s, market, CFG)
    cards = {"STDY": ready()}
    with value_session() as s:
        events, frozen = shadow.step_legs(s, market, cards, CFG)
        assert frozen == 0 and events == 4  # full stops on both lists: a stop and a fill each
    with value_session() as s:
        full = s.scalars(
            select(ValueShadowLegRow).where(ValueShadowLegRow.policy == "full")
        ).first()
        assert full.closed and full.exit_date == SESSIONS[3]
        assert full.ret_exit == pytest.approx(28.5 / 31.0 - 1.0)  # sold at the 28.50 open
        assert full.spy_ret_exit == pytest.approx(510.0 / 500.0 - 1.0)
        kinds = [e.kind for e in s.scalars(select(ValueShadowEventRow)) if e.policy == "full"]
        assert kinds == ["stop", "fill", "stop", "fill"]
        value = s.scalars(
            select(ValueShadowLegRow).where(ValueShadowLegRow.policy == "value")
        ).first()
        assert not value.closed and value.sessions == 3 and value.last_step == SESSIONS[3]


def test_horizons_mark_h_sessions_after_the_entry_session_against_spy(value_db) -> None:
    _open([ready()])
    closes = [30.0] + [31.0] * 21 + [33.0] + [32.0] * 30
    spy = [500.0] * 22 + [510.0] + [505.0] * 30
    market = {"STDY": bars(closes), "SPY": bars(spy)}
    with value_session() as s:
        shadow.fill_pending(s, market, CFG)  # entry: SESSIONS[1] at 31.00, SPY 500.00
    with value_session() as s:
        assert shadow.mark_horizons(s, market) == (2, 0)  # 21 for both lists; 63 not yet
    with value_session() as s:
        row = s.scalars(select(ValueShadowRow)).first()
        assert row.ret_21 == pytest.approx(33.0 / 31.0 - 1.0)  # SESSIONS[22]'s close
        assert row.spy_21 == pytest.approx(0.02)
        assert row.ret_63 is None


def test_a_horizon_waits_for_the_names_bar_then_settles_for_the_last_close(value_db) -> None:
    _open([ready()])
    stdy = bars([30.0] + [31.0] * 10 + [29.0])  # the name's bars stop at SESSIONS[11]
    with value_session() as s:
        shadow.fill_pending(s, {"STDY": stdy, "SPY": bars([500.0] * 2)}, CFG)
    with value_session() as s:  # h21 is SESSIONS[22]; only 2 SPY sessions after it so far
        assert shadow.mark_horizons(s, {"STDY": stdy, "SPY": bars([500.0] * 25)}) == (0, 0)
    with value_session() as s:  # 5 SPY sessions after it: settle for the last close
        assert shadow.mark_horizons(s, {"STDY": stdy, "SPY": bars([500.0] * 28)}) == (2, 0)
    with value_session() as s:
        row = s.scalars(select(ValueShadowRow)).first()
        assert row.ret_21 == pytest.approx(29.0 / 31.0 - 1.0)
        assert "h21: no bar since" in row.status_detail


def test_an_entry_closes_once_every_horizon_is_marked_and_every_leg_has_exited(value_db) -> None:
    _open([ready()])
    with value_session() as s:
        shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
    with value_session() as s:
        for row in s.scalars(select(ValueShadowRow)):
            for h in shadow.HORIZONS:
                setattr(row, f"ret_{h}", 0.0)
                setattr(row, f"spy_{h}", 0.0)
    with value_session() as s:
        assert shadow.close_finished(s, SESSIONS[130]) == 0  # the legs still hold
    with value_session() as s:
        for leg in s.scalars(select(ValueShadowLegRow)):
            leg.closed = True
    with value_session() as s:
        assert shadow.close_finished(s, SESSIONS[130]) == 2
    assert {r[3] for r in _rows()} == {"closed"}


def test_a_split_freezes_the_entry_instead_of_firing_its_stop(value_db) -> None:
    _open([ready()])
    with value_session() as s:
        shadow.fill_pending(s, {"STDY": bars([30.0, 31.0]), "SPY": bars([500.0] * 2)}, CFG)
    split = {"STDY": bars([15.0, 15.5, 15.4]), "SPY": bars([500.0] * 3)}  # 2-for-1 rewrite
    with value_session() as s:
        assert shadow.step_legs(s, split, {}, CFG) == (0, 2)
    assert {r[3] for r in _rows()} == {"rebase_needed"}
    with value_session() as s:
        assert s.scalars(select(ValueShadowEventRow)).first() is None


def test_a_signal_that_never_gets_a_bar_is_voided(value_db) -> None:
    _open([ready()])
    market = {"STDY": bars([30.0]), "SPY": bars([500.0] * 6)}
    with value_session() as s:
        assert shadow.fill_pending(s, market, CFG) == (0, 2)
    assert {r[3] for r in _rows()} == {"void"}


@pytest.fixture()
def research(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _bar(s: Session, symbol: str, day: date, close: float) -> None:
    s.add(DailyBarRow(symbol=symbol, date=day, open=close, high=close, low=close, close=close))


def test_the_ranked_record_forms_monthly_and_closes_at_the_next_formation(
    value_db, research
) -> None:
    names = [f"S{i}" for i in range(10)]
    cards = [ready(n, 20.0 + 2 * i) for i, n in enumerate(names)]  # S0 cheapest: ranks top
    april = date(2026, 4, 1)
    for i, n in enumerate(names):
        _bar(research, n, AS_OF, 20.0 + 2 * i)
        _bar(research, n, april, (20.0 + 2 * i) * (1.10 if i == 0 else 1.0))
    _bar(research, "SPY", AS_OF, 500.0)
    _bar(research, "SPY", april, 505.0)
    research.flush()
    with value_session() as s:
        assert shadow.run_ranked(
            s, research, cards, set(names), as_of=AS_OF, version="v2", digest="x"
        ) == (6, 0)  # three buckets per list
    with value_session() as s:
        top = s.scalars(
            select(ValueRankedRow).where(
                ValueRankedRow.list_name == "deep_value", ValueRankedRow.bucket == "top"
            )
        ).one()
        assert json.loads(top.members_json) == ["S0"] and top.n == 1
    with value_session() as s:  # the same month again: nothing
        assert shadow.run_ranked(
            s, research, cards, set(names), as_of=AS_OF, version="v2", digest="x"
        ) == (0, 0)
    with value_session() as s:
        assert shadow.run_ranked(
            s, research, cards, set(names), as_of=april, version="v2", digest="x"
        ) == (6, 6)
    with value_session() as s:
        closed = {
            (r.list_name, r.bucket): (r.ret, r.spy_ret, r.missing)
            for r in s.scalars(select(ValueRankedRow).where(ValueRankedRow.closed_on == april))
        }
    assert closed[("deep_value", "top")][0] == pytest.approx(0.10)
    assert closed[("deep_value", "bottom")][0] == pytest.approx(0.0)
    assert closed[("deep_value", "all")][0] == pytest.approx(0.01)  # 10% / 10 names
    assert closed[("deep_value", "top")][1] == pytest.approx(0.01)
    assert closed[("deep_value", "top")][2] == 0


def test_process_runs_a_night_in_order(value_db, research) -> None:
    for i, d in enumerate(SESSIONS[:3]):
        _bar(research, "STDY", d, 30.0 + i)
        _bar(research, "SPY", d, 500.0)
    research.flush()
    night = {"tags": {"STDY": "trading"}, "atr": {}, "evidence": set(), "cfg": CFG}
    with value_session() as s:
        out = shadow.process(
            s,
            research,
            [ready()],
            as_of=AS_OF,
            version="v2",
            digest="x",
            now=datetime.now(UTC).replace(tzinfo=None),
            **night,
        )
    assert out.opened["ready"] == 2 and out.filled == 0
    with value_session() as s:
        out = shadow.process(
            s,
            research,
            [ready()],
            as_of=SESSIONS[1],
            version="v2",
            digest="x",
            now=datetime.now(UTC).replace(tzinfo=None),
            **night,
        )
    assert (out.filled, out.opened["ready"]) == (2, 0)
    assert out.events == 0  # the entry session's close is read; nothing fires
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_shadow.py`
  Expected: collection error, `ImportError: cannot import name 'ValueRankedRow'`.

- [x] **Step 3: The tables** — apply to `src/value/store.py` (the existing three tables are
  untouched; `init_value_db` creates the new ones on the live `value.db` at the first start):

```diff
diff --git a/src/value/store.py b/src/value/store.py
--- a/src/value/store.py
+++ b/src/value/store.py
@@ -10,4 +10,13 @@ Part 1 tables:
   compact row once per session for names in the ranked universe;
 - ``value_runs`` - one row per scoring run (the dry run included).
+
+Part 2 tables (the shadow record, spec §6.8, §7, §12):
+- ``value_shadow`` - one hypothetical entry per READY signal or control-group name, with its
+  fixed-horizon returns against SPY;
+- ``value_shadow_legs`` - one row per entry and exit policy (READY entries only), holding the
+  exit engine's state;
+- ``value_shadow_events`` - every exit event and fill, append-only;
+- ``value_ranked`` - the ranked monthly record: top tenth, bottom tenth and the whole universe
+  per list, each held to the next formation.
 """
 
@@ -19,5 +28,16 @@ from datetime import date, datetime
 from pathlib import Path
 
-from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, create_engine, event
+from sqlalchemy import (
+    Boolean,
+    Date,
+    DateTime,
+    Float,
+    Index,
+    Integer,
+    String,
+    Text,
+    create_engine,
+    event,
+)
 from sqlalchemy.engine import Engine
 from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
@@ -91,4 +111,106 @@ class ValueRunRow(ValueBase):
 
 
+class ValueShadowRow(ValueBase):
+    """One hypothetical entry (spec §6.8). ``kind``: ``ready`` (a READY signal) or a control
+    group, ``control_valuation`` (healthy, too dear: WAIT) or ``control_health`` (cheap enough,
+    health failed). ``status``: pending (waiting for the next session's open), open, closed,
+    void (no bar ever came) or rebase_needed (the entry bar moved: a split, Part 3 rebases)."""
+
+    __tablename__ = "value_shadow"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    track: Mapped[str] = mapped_column(String(16))  # baseline (Claude's track is Part 4)
+    kind: Mapped[str] = mapped_column(String(24))
+    list_name: Mapped[str] = mapped_column(String(16))
+    symbol: Mapped[str] = mapped_column(String(16))
+    universe: Mapped[str] = mapped_column(String(16))  # trading | evidence
+    signal_date: Mapped[date] = mapped_column(Date)
+    status: Mapped[str] = mapped_column(String(16), default="pending")
+    status_detail: Mapped[str] = mapped_column(Text, default="")
+    verdict: Mapped[str] = mapped_column(String(16))  # Python's baseline verdict at the signal
+    signal_close: Mapped[float | None] = mapped_column(Float, nullable=True)
+    atr14: Mapped[float | None] = mapped_column(Float, nullable=True)
+    fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)
+    effective_fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)
+    margin_of_safety: Mapped[float | None] = mapped_column(Float, nullable=True)  # a fraction
+    required_mos_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
+    fv_accn: Mapped[str | None] = mapped_column(String(32), nullable=True)
+    fingerprint_key: Mapped[str] = mapped_column(String(16))
+    ruleset_version: Mapped[str] = mapped_column(String(32))
+    ruleset_hash: Mapped[str] = mapped_column(String(12))
+    scorecard_json: Mapped[str] = mapped_column(Text)
+    entry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
+    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
+    spy_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
+    ret_21: Mapped[float | None] = mapped_column(Float, nullable=True)
+    spy_21: Mapped[float | None] = mapped_column(Float, nullable=True)
+    ret_63: Mapped[float | None] = mapped_column(Float, nullable=True)
+    spy_63: Mapped[float | None] = mapped_column(Float, nullable=True)
+    ret_126: Mapped[float | None] = mapped_column(Float, nullable=True)
+    spy_126: Mapped[float | None] = mapped_column(Float, nullable=True)
+    created_at: Mapped[datetime] = mapped_column(DateTime)
+    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
+
+    __table_args__ = (
+        Index("ix_value_shadow_key", "track", "kind", "list_name", "symbol"),
+        Index("ix_value_shadow_status", "status"),
+    )
+
+
+class ValueShadowLegRow(ValueBase):
+    """One exit policy's simulated holding of one READY entry (spec §7)."""
+
+    __tablename__ = "value_shadow_legs"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    shadow_id: Mapped[int] = mapped_column(Integer, index=True)
+    policy: Mapped[str] = mapped_column(String(8))  # full | value | hold12
+    state_json: Mapped[str] = mapped_column(Text)  # src.value.exits.LegState
+    last_step: Mapped[date | None] = mapped_column(Date, nullable=True)
+    closed: Mapped[bool] = mapped_column(Boolean, default=False)
+    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
+    ret_exit: Mapped[float | None] = mapped_column(Float, nullable=True)
+    spy_ret_exit: Mapped[float | None] = mapped_column(Float, nullable=True)
+    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
+    sessions: Mapped[int] = mapped_column(Integer, default=0)
+    sells: Mapped[int] = mapped_column(Integer, default=0)
+
+
+class ValueShadowEventRow(ValueBase):
+    """Append-only: every exit event and fill of every leg."""
+
+    __tablename__ = "value_shadow_events"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    shadow_id: Mapped[int] = mapped_column(Integer, index=True)
+    policy: Mapped[str] = mapped_column(String(8))
+    day: Mapped[date] = mapped_column(Date)
+    kind: Mapped[str] = mapped_column(String(16))
+    price: Mapped[float | None] = mapped_column(Float, nullable=True)
+    fraction: Mapped[float] = mapped_column(Float, default=0.0)
+    detail: Mapped[str] = mapped_column(Text, default="")
+
+
+class ValueRankedRow(ValueBase):
+    """One hypothetical equal-weight portfolio of the ranked record (spec §6.8): a list's top
+    tenth, bottom tenth or whole scored universe, formed on the first session of a month and
+    held to the next formation."""
+
+    __tablename__ = "value_ranked"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    formed_on: Mapped[date] = mapped_column(Date, index=True)
+    list_name: Mapped[str] = mapped_column(String(16))
+    bucket: Mapped[str] = mapped_column(String(8))  # top | bottom | all
+    members_json: Mapped[str] = mapped_column(Text)  # JSON list of symbols
+    n: Mapped[int] = mapped_column(Integer)
+    ruleset_version: Mapped[str] = mapped_column(String(32))
+    ruleset_hash: Mapped[str] = mapped_column(String(12))
+    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
+    ret: Mapped[float | None] = mapped_column(Float, nullable=True)
+    spy_ret: Mapped[float | None] = mapped_column(Float, nullable=True)
+    missing: Mapped[int] = mapped_column(Integer, default=0)  # members without a bar at an end
+
+
 _engine: Engine | None = None
 _SessionLocal: sessionmaker[Session] | None = None
```

- [x] **Step 4: The `report.py` stub** so `HORIZONS` has one home — create `src/value/report.py`
  with exactly:

  ```python
  """The shadow record's report (spec §6.8, §7, §11, §12). Pure: no I/O."""

  HORIZONS = (21, 63, 126)  # sessions after the entry session (spec §6.8, §12)
  ```

- [x] **Step 5: The record** — `src/value/shadow.py`:

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
- a leg's absolute levels cannot survive a split: an entry whose entry bar moved by more than 25%
  is frozen as ``rebase_needed`` (Part 3 rebases).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg
from src.common.value_inputs import build_day_bars, closes_on, read_bars
from src.common.value_types import DayBar
from src.value.exits import POLICIES, DayFacts, LegState, benchmark_return, open_leg, step
from src.value.rank import rank_list
from src.value.ranked import BUCKETS, buckets, equal_weight_return, is_new_month
from src.value.report import HORIZONS
from src.value.schemas import LISTS, ValueScorecard
from src.value.store import (
    ValueRankedRow,
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
)

BENCHMARK = "SPY"
TRACK = "baseline"
SPLIT_GUARD = 0.25
GRACE_SESSIONS = 5
SHADOW_UNIVERSES = ("trading", "evidence")


@dataclass(slots=True)
class ShadowSummary:
    opened: dict[str, int] = field(default_factory=dict)
    filled: int = 0
    voided: int = 0
    events: int = 0
    marked: int = 0
    closed: int = 0
    rebase_needed: int = 0
    ranked_formed: int = 0
    ranked_closed: int = 0


def _actual(card: ValueScorecard, check_id: str) -> float | None:
    for c in card.health_checks:
        if c.id == check_id:
            return c.actual
    return None


def day_facts(card: ValueScorecard | None, list_name: str) -> DayFacts | None:
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
        altman_z=_actual(card, "health.altman_z"),
    )


def blocking_keys(vs: Session, live_policy: str) -> set[tuple[str, str, str]]:
    """(kind, list, symbol) keys that may not enter again tonight."""
    out: set[tuple[str, str, str]] = set()
    rows = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.track == TRACK,
            ValueShadowRow.status.in_(("pending", "open", "rebase_needed")),
        )
    )
    for row in rows:
        key = (row.kind, row.list_name, row.symbol)
        if row.kind != "ready" or row.status != "open":
            out.add(key)
            continue
        live = vs.scalar(
            select(ValueShadowLegRow.closed).where(
                ValueShadowLegRow.shadow_id == row.id, ValueShadowLegRow.policy == live_policy
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


def _split_moved(row: ValueShadowRow, bars: list[DayBar]) -> bool:
    if row.entry_date is None or not row.entry_price:
        return False
    bar = _bar_on(bars, row.entry_date)
    return bar is not None and abs(_price(bar) / row.entry_price - 1.0) > SPLIT_GUARD


def _freeze(row: ValueShadowRow) -> None:
    row.status = "rebase_needed"
    row.status_detail = (
        f"the {row.entry_date} bar no longer matches the entry price {row.entry_price:.2f} "
        "(a split?): frozen until Part 3's rebase"
    )


def step_legs(
    vs: Session,
    market: dict[str, list[DayBar]],
    cards: dict[str, ValueScorecard],
    cfg: ValueCfg,
) -> tuple[int, int]:
    """Run every open leg over the sessions it has not seen, with tonight's facts."""
    spy_open = {b.date: _price(b) for b in market.get(BENCHMARK, [])}
    n_events = frozen = 0
    rows = vs.scalars(
        select(ValueShadowRow).where(
            ValueShadowRow.status == "open", ValueShadowRow.kind == "ready"
        )
    ).all()
    for row in rows:
        bars = market.get(row.symbol, [])
        if _split_moved(row, bars):
            _freeze(row)
            frozen += 1
            continue
        assert row.entry_date is not None and row.spy_entry_price is not None
        facts = day_facts(cards.get(row.symbol), row.list_name)
        legs = vs.scalars(
            select(ValueShadowLegRow).where(
                ValueShadowLegRow.shadow_id == row.id, ValueShadowLegRow.closed.is_(False)
            )
        )
        for leg in legs:
            state = LegState.model_validate_json(leg.state_json)
            days = [
                b
                for b in bars
                if b.date >= row.entry_date and (leg.last_step is None or b.date > leg.last_step)
            ]
            for b in days:
                state, events = step(state, b, facts, cfg.rules.exits)
                for e in events:
                    vs.add(
                        ValueShadowEventRow(
                            shadow_id=row.id,
                            policy=leg.policy,
                            day=e.day,
                            kind=e.kind,
                            price=e.price,
                            fraction=e.fraction,
                            detail=e.detail,
                        )
                    )
                n_events += len(events)
            if days:
                leg.last_step = days[-1].date
            leg.state_json = state.model_dump_json()
            leg.sessions, leg.sells = state.sessions, state.sells
            leg.max_drawdown = state.max_drawdown
            if state.closed:
                vs.flush()
                fills = [
                    (d, f)
                    for d, f in vs.execute(
                        select(ValueShadowEventRow.day, ValueShadowEventRow.fraction).where(
                            ValueShadowEventRow.shadow_id == row.id,
                            ValueShadowEventRow.policy == leg.policy,
                            ValueShadowEventRow.kind == "fill",
                        )
                    )
                ]
                leg.closed, leg.exit_date = True, state.exit_date
                leg.ret_exit = state.exit_return()
                leg.spy_ret_exit = benchmark_return(fills, spy_open, row.spy_entry_price)
    vs.flush()
    return n_events, frozen


def _close_on_or_before(bars: list[DayBar], day: date) -> float | None:
    before = [b for b in bars if b.date <= day]
    return before[-1].close if before else None


def mark_horizons(vs: Session, market: dict[str, list[DayBar]]) -> tuple[int, int]:
    """Mark-to-market returns at 21/63/126 sessions (spec §12), against SPY, for every open
    entry: READY and control alike."""
    spy = market.get(BENCHMARK, [])
    marked = frozen = 0
    for row in vs.scalars(select(ValueShadowRow).where(ValueShadowRow.status == "open")).all():
        assert row.entry_date is not None and row.entry_price is not None
        bars = market.get(row.symbol, [])
        if _split_moved(row, bars):
            _freeze(row)
            frozen += 1
            continue
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
    return marked, frozen


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
) -> ShadowSummary:
    """One night of the shadow record, in order: fill yesterday's signals, run the legs, mark
    the horizons, close what is finished, open tonight's signals, then the ranked record."""
    out = ShadowSummary()
    by_symbol = {c.symbol: c for c in cards}
    live = cfg.rules.exits.live_policy
    held = set(
        vs.scalars(
            select(ValueShadowRow.symbol).where(ValueShadowRow.status.in_(("pending", "open")))
        )
    )
    market = load_bars(rs, held | {BENCHMARK}, as_of)
    out.filled, out.voided = fill_pending(vs, market, cfg)
    out.events, frozen_legs = step_legs(vs, market, by_symbol, cfg)
    out.marked, frozen_marks = mark_horizons(vs, market)
    out.rebase_needed = frozen_legs + frozen_marks
    vs.flush()
    out.closed = close_finished(vs, as_of)
    vs.flush()
    out.opened = open_signals(vs, cards, tags, atr, live_policy=live, now=now)
    out.ranked_formed, out.ranked_closed = run_ranked(
        vs, rs, cards, evidence, as_of=as_of, version=version, digest=digest
    )
    return out
```

- [x] **Step 6: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_shadow.py tests/test_value_store.py tests/test_value_fence.py`
  Expected: PASS (`test_value_shadow.py` 12). Ruff check/format and `.venv/bin/mypy src/value`
  clean.

- [x] **Step 7: Commit, then the section's Progress-log commit**

  ```bash
  git add src/value/store.py src/value/shadow.py src/value/report.py tests/test_value_shadow.py docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "feat(value): the shadow record - entries, controls, legs, horizons, the ranked record"
  ```

  Then the full gate (Section exit), Task 6's row, and one command each:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "docs(plan): value book Part 2 Progress log - Section B"
  ```

---

## Section C — The value process (Tasks 7–9) · model: sonnet · effort: high

`src/value/service.py` decides when a night is due and runs it in one transaction; the thin
entrypoint gathers the plain data `src/value/` may not fetch and is registered with the
supervisor; the fence learns about every new module and the process as a whole.

**Spec to read:** §6.6 (the earnings bullet), §6.9 ("What stays fresh without being opened", the
follow window), §9.7 (the process and config bullets), §16 (the first bullet: the fence and the
`sys.modules` check).

**Files the subagent reads:** this section; `src/value/shadow.py` (signatures of `process`,
`BENCHMARK`), `src/value/ticker_file.py` (`persist`), `src/value/store.py` (`record_run`,
`ValueTickerFileRow`, `ValueShadowRow`), `scripts/value_dry_run.py` (lines 85–160: the input
loading `service.load_inputs` mirrors), `src/common/value_inputs.py` (the readers),
`src/common/value_universe.py` (`ValueUniverse`, `build_value_universe`),
`scripts/run_research_worker.py` (the thread-and-signal entrypoint pattern),
`src/news/store/readonly.py` and `src/news/store/queries.py` (`earnings_between`),
`scripts/start.py` (lines 1–30, 60–100, 413–430), `ibkr`, `tests/test_start_launcher.py`,
`tests/test_value_fence.py`, `tests/test_spreads_fence.py` (lines 40–90 and 138–157: the parser and
the `sys.modules` probe), `tests/conftest.py` (the `news_db` fixture, lines 1000–1040).

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **C1. Section B landed.** Tasks 4–6 ticked; record `git log --oneline main..HEAD | wc -l`.
- [ ] **C2. Green, from the worktree root.** `.venv/bin/python -m pytest -q` = baseline + 47,
  `.venv/bin/ruff check .`, `.venv/bin/mypy src`.
- [ ] **C3. The code Section C edits is where this plan says.** Each prints the line shown:

  ```bash
  grep -n '^    python -m scripts.start --no-news      # skip the news service$' scripts/start.py   # 21:
  grep -n '^        "log": PROJECT_ROOT / "logs" / "news.log",$' scripts/start.py              # 94:
  grep -n '^    parser.add_argument("--no-news", action="store_true", help="Skip the news service")$' scripts/start.py   # 422:
  grep -c 'spreads|news|watchdog|supervisor' ibkr                                             # 2
  tail -n 1 tests/test_start_launcher.py      #     assert "news" not in active and "spreads" in active
  grep -n '^    "ruleset",$' tests/test_value_fence.py                                       # 31:
  grep -n '^    rows = ("ValueTickerFileRow(", "ValueTickerHistoryRow(", "ValueRunRow(")$' tests/test_value_fence.py   # 165:
  grep -n "import src.value.scorecard, src.value.store, src.value.ticker_file, src.value.funnel" tests/test_value_fence.py   # 178:
  ```

- [ ] **C4. The pieces Section C builds on exist.** Each prints at least one line:

  ```bash
  grep -n "^def process\|^def open_signals\|^BENCHMARK" src/value/shadow.py
  grep -n "^def persist\b\|^def persist(" src/value/ticker_file.py
  grep -n "^def newest_bar_before\|^def filings_coverage\|^def symbol_is_etf\|^def fetch_market_facts\|^def load_regime" src/common/value_inputs.py
  grep -n "^def earnings_between" src/news/store/queries.py
  grep -n "^def read_only_session" src/news/store/readonly.py
  grep -n "^def effective_universe" src/common/universe.py
  grep -n "^def news_db" tests/conftest.py
  ```

**Section exit:** three more task commits plus the section's `docs(plan)` commit; full gate green
with pytest = baseline + 62 (47 + 7 + 5 + 3); `.venv/bin/python -m py_compile scripts/run_value.py
scripts/value_feed.py` silent; `bash -n ibkr` silent; protected-file diff empty. Record the commit
count.

---

### Task 7: The nightly run

**Files:** Create `src/value/service.py`, `tests/test_value_service.py`

**Interfaces:**
- Consumes: `shadow.process`, `shadow.BENCHMARK`; `ticker_file.persist`; `store.record_run`;
  `rank.rank_list`, `rank.filed_lists`, `rank.rs_cutoff`; `scorecard.build_scorecard`;
  `ruleset.ruleset_id`; Task 2's readers; `value_universe.build_value_universe` (imported into the
  module's namespace, so tests patch `service.build_value_universe`).
- Produces: `RunPlan(as_of, tags, etfs, evidence, classification)` with `.names` and
  `.fetch_names`; `startup_check() -> str | None`; `is_due(now_et, as_of, last, run_hour) -> bool`;
  `last_nightly_as_of(vs)`; `followed_names(vs, now, follow_days) -> list[str]`;
  `shadow_names(vs) -> dict[str, str]`; `plan_run(now=None, universe=None) -> RunPlan | None`;
  `load_inputs(plan, rs, *, facts, earnings, regime) -> list[ValueInputs]`;
  `run_nightly(plan, *, facts: dict[str, MarketFacts], earnings: dict[str, date], now=None) ->
  dict[str, Any]` (the summary also written to `value_runs.summary_json`).

- [x] **Step 1: Write the failing tests** — `tests/test_value_service.py`:

```python
"""The value process's nightly run (value book spec §6.8, §6.9): when a run is due, what it
scores, the follow window, one transaction per night, and the idle-on-a-stale-ruleset check."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import src.common.value_inputs as vi
import src.value.store as store
from src.common.config import get_config
from src.common.value_types import MarketFacts
from src.common.value_universe import ValueUniverse
from src.research.store.models import Base, CompanyFactsRawRow, DailyBarRow, SymbolRow
from src.value import service
from src.value.store import (
    ValueRunRow,
    ValueShadowRow,
    ValueTickerFileRow,
    ValueTickerHistoryRow,
    init_value_db,
    record_run,
    value_session,
)
from tests.value_fixtures import AS_OF, companyfacts, price

# 07:00 ET on the session after AS_OF (2026-03-31): its bar may be forming, so AS_OF is scored.
NOW = datetime(2026, 4, 1, 11, 0)


def test_a_run_is_due_for_a_new_settled_session_after_the_hour() -> None:
    at = datetime(2026, 4, 1, 7, 0)
    assert service.is_due(at, AS_OF, None, 6)
    assert service.is_due(at, AS_OF, AS_OF - timedelta(days=1), 6)
    assert not service.is_due(at, AS_OF, AS_OF, 6)  # already scored
    assert not service.is_due(at, None, None, 6)  # no SPY bar at all
    assert not service.is_due(at.replace(hour=5), AS_OF, None, 6)  # the sweep may still run


@pytest.fixture()
def dbs(tmp_path, monkeypatch):
    research = tmp_path / "research.db"
    engine = create_engine(f"sqlite:///{research}")
    Base.metadata.create_all(engine)
    closes = price(30.0).closes
    days = pd.bdate_range(end=AS_OF, periods=len(closes)).date
    with Session(engine) as s:
        s.add(SymbolRow(symbol="STDY", cik="0000000001", name="Steady Co"))
        s.add(
            CompanyFactsRawRow(
                cik="0000000001",
                payload_json=json.dumps(companyfacts()),
                fetched_at=datetime(2026, 3, 30),
            )
        )
        for d, c in zip(days, closes, strict=True):
            s.add(DailyBarRow(symbol="STDY", date=d, open=c, high=c, low=c, close=c, volume=1e6))
            s.add(DailyBarRow(symbol="SPY", date=d, open=500, high=500, low=500, close=500.0))
        # A bar dated "today" (2026-04-01) that may still be forming: never scored.
        s.add(
            DailyBarRow(symbol="SPY", date=date(2026, 4, 1), open=501, high=501, low=501, close=501)
        )
        s.commit()
    monkeypatch.setattr(vi, "_resolve_path", lambda: str(research))
    vi.reset_engine()
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    monkeypatch.setattr(vi, "load_regime", lambda: "normal")
    monkeypatch.setattr(
        service,
        "build_value_universe",
        lambda cfg, universe: ValueUniverse(
            trading=["STDY"],
            evidence=["STDY"],
            classification={"STDY": ("Information Technology", "Application Software")},
        ),
    )
    yield
    vi.reset_engine()
    store.reset_engine()


def test_the_plan_scores_the_newest_settled_session_and_every_name(dbs) -> None:
    with value_session() as s:
        s.add(_file("LOOK", "lookup", viewed=NOW - timedelta(days=10)))
        s.add(_file("GONE", "lookup", viewed=NOW - timedelta(days=40)))
    plan = service.plan_run(NOW, universe={})
    assert plan is not None and plan.as_of == AS_OF  # not the forming 2026-04-01 bar
    assert plan.tags == {"STDY": "trading", "LOOK": "lookup"}  # GONE's window expired
    assert service.plan_run(NOW.replace(hour=9), universe={}) is None  # 05:00 ET: too early


def test_a_night_waits_until_the_research_sweep_has_filed_the_universe(dbs, monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "build_value_universe",
        lambda cfg, universe: ValueUniverse(trading=["STDY", "NEW"], evidence=["STDY", "NEW"]),
    )
    assert service.plan_run(NOW, universe={}) is None  # filings for 1 of 2 names: 50% < 90%
    monkeypatch.setattr(get_config().value.service, "min_filings_coverage_pct", 50.0)
    assert service.plan_run(NOW, universe={}) is not None


def test_a_session_already_scored_is_not_run_again(dbs) -> None:
    with value_session() as s:
        record_run(
            s,
            kind="nightly",
            started_at=NOW,
            finished_at=NOW,
            as_of=AS_OF,
            ruleset_version="v2",
            ruleset_hash="x",
            names=1,
            rs_cutoff_6m=None,
            summary_json="{}",
        )
    assert service.plan_run(NOW, universe={}) is None


def test_a_night_scores_persists_and_opens_the_shadow_record(dbs) -> None:
    plan = service.plan_run(NOW, universe={})
    assert plan is not None
    out = service.run_nightly(
        plan,
        facts={"STDY": MarketFacts(market_cap=3.0e9)},
        earnings={"STDY": AS_OF + timedelta(days=60)},
        now=NOW,
    )
    assert out["verdicts"]["deep_value"] == {"READY": 1}
    assert out["shadow"]["opened"] == {"ready": 2, "control_valuation": 0, "control_health": 0}
    assert out["shadow"]["ranked_formed"] == 0  # one name: no tenth to form
    with value_session() as s:
        row = s.get(ValueTickerFileRow, "STDY")
        assert (row.universe, row.verdict_deep, row.filed_list) == (
            "trading",
            "READY",
            "deep_value",
        )
        assert s.scalars(select(ValueTickerHistoryRow)).first() is not None
        run = s.scalars(select(ValueRunRow)).one()
        assert (run.kind, run.as_of, run.ruleset_version) == ("nightly", AS_OF, "v2")
        assert {r.status for r in s.scalars(select(ValueShadowRow))} == {"pending"}
    assert service.plan_run(NOW, universe={}) is None  # done for AS_OF


def test_a_failed_night_leaves_value_db_as_it_was(dbs, monkeypatch) -> None:
    plan = service.plan_run(NOW, universe={})
    assert plan is not None

    def boom(*_a, **_k):
        raise RuntimeError("shadow failed")

    monkeypatch.setattr(service.shadow, "process", boom)
    with pytest.raises(RuntimeError):
        service.run_nightly(plan, facts={}, earnings={}, now=NOW)
    with value_session() as s:
        assert s.get(ValueTickerFileRow, "STDY") is None
        assert s.scalars(select(ValueRunRow)).first() is None
    assert service.plan_run(NOW, universe={}) is not None  # the next poll retries


def test_an_old_private_config_idles_the_process_instead_of_crash_looping(monkeypatch) -> None:
    monkeypatch.setattr(get_config().value, "ruleset_version", "v1")  # v1's pin, v2's rules
    problem = service.startup_check()
    assert problem is not None and "frozen" in problem


def _file(symbol: str, universe: str, *, viewed: datetime | None) -> ValueTickerFileRow:
    return ValueTickerFileRow(
        symbol=symbol,
        computed_at=NOW,
        as_of=AS_OF,
        universe=universe,
        fingerprint_key="0" * 16,
        fingerprint_json="{}",
        ruleset_version="v2",
        ruleset_hash="x",
        company_class="operating",
        data_quality="pass",
        health="pass",
        verdict_deep="WAIT",
        verdict_growth="WAIT",
        summary_json="{}",
        scorecard_json="{}",
        last_viewed_at=viewed,
    )
```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_service.py`
  Expected: collection error, `ImportError: cannot import name 'service' from 'src.value'`.

- [x] **Step 3: The service** — `src/value/service.py` (rulings 5–9; persisting with
  `session_row=tag != "lookup"` gives every universe and shadow name its compact history row per
  session, spec §6.9):

```python
"""The value process's nightly run (spec §6.8, §6.9, §9.7): score both universes, the followed
names and every shadow name once a session has closed, write the ticker files, run the shadow
record and log the run. ``scripts/run_value.py`` is the thin entrypoint: it gathers the plain
data this module may not fetch itself (earnings dates from news.db, yfinance market facts) and
calls :func:`plan_run` and :func:`run_nightly`.

No IBKR connection and no clientId in Parts 1-4 (clientId 31 arrives with Stage 3). Reads
research.db read-only through ``src/common/value_inputs.py``; writes value.db only. One run is
one transaction: a run that fails leaves value.db as it was, and the next poll retries it.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common import value_inputs as vi
from src.common.config import get_config
from src.common.value_types import Classification, MarketFacts, ValueInputs
from src.common.value_universe import build_value_universe
from src.value import shadow
from src.value.rank import filed_lists, rank_list, rs_cutoff
from src.value.ruleset import ruleset_id
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueRunRow,
    ValueShadowRow,
    ValueTickerFileRow,
    init_value_db,
    record_run,
    value_session,
)
from src.value.ticker_file import persist

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RunPlan:
    """What tonight's run scores: the session it is for and every name with its universe tag."""

    as_of: date
    tags: dict[str, str]  # symbol -> trading | evidence | lookup
    etfs: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)
    classification: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return sorted(self.tags)

    @property
    def fetch_names(self) -> list[str]:
        """Names whose yfinance market facts the entrypoint fetches (not the ETFs)."""
        return [n for n in self.names if n not in self.etfs]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def startup_check() -> str | None:
    """Why the process must idle, or None. A frozen ruleset whose rules no longer match (a
    private config/value.yaml from an older version) idles the process instead of crash-looping
    under the supervisor."""
    try:
        ruleset_id(get_config().value)
    except ValueError as exc:
        return str(exc)
    init_value_db()
    return None


def is_due(now_et: datetime, as_of: date | None, last: date | None, run_hour: int) -> bool:
    """A settled session nobody has scored yet, and the hour has come."""
    return as_of is not None and (last is None or as_of > last) and now_et.hour >= run_hour


def last_nightly_as_of(vs: Session) -> date | None:
    return vs.scalar(select(func.max(ValueRunRow.as_of)).where(ValueRunRow.kind == "nightly"))


def followed_names(vs: Session, now: datetime, follow_days: int) -> list[str]:
    """Names looked up outside the universe and viewed within ``follow_days`` (spec §6.9).
    Part 6's surfaces set ``last_viewed_at``; after the window the file stays, unrefreshed."""
    cutoff = now - timedelta(days=follow_days)
    return list(
        vs.scalars(
            select(ValueTickerFileRow.symbol).where(
                ValueTickerFileRow.universe == "lookup",
                ValueTickerFileRow.last_viewed_at.is_not(None),
                ValueTickerFileRow.last_viewed_at >= cutoff,
            )
        )
    )


def shadow_names(vs: Session) -> dict[str, str]:
    """Every name with a pending or open shadow entry, and the universe it entered from: held
    and shadow names stay fresh even after they leave the universe (spec §6.9)."""
    rows = vs.execute(
        select(ValueShadowRow.symbol, ValueShadowRow.universe).where(
            ValueShadowRow.status.in_(("pending", "open"))
        )
    )
    return {symbol: universe for symbol, universe in rows}


def plan_run(now: datetime | None = None, universe: dict[str, Any] | None = None) -> RunPlan | None:
    """Tonight's plan, or None when no newly settled session is waiting. *as_of* is SPY's newest
    bar dated before today (ET): a bar dated today may still be forming."""
    cfg = get_config()
    vcfg = cfg.value
    now = now or _now()
    now_et = now.replace(tzinfo=UTC).astimezone(ZoneInfo(cfg.scheduler.timezone))
    with vi.research_read() as rs:
        if rs is None:
            log.warning("value: research.db not found; nothing to score")
            return None
        as_of = vi.newest_bar_before(rs, shadow.BENCHMARK, now_et.date())
    with value_session() as vs:
        last = last_nightly_as_of(vs)
        if not is_due(now_et, as_of, last, vcfg.service.run_hour_et):
            return None
        assert as_of is not None
        if universe is None:
            from src.common.universe import effective_universe

            universe = effective_universe()
        u = build_value_universe(vcfg, universe)
        tags = {s: u.tag(s) for s in u.all_names()}
        for symbol, entered_from in shadow_names(vs).items():
            tags.setdefault(symbol, entered_from)
        for symbol in followed_names(vs, now, vcfg.ticker_file.follow_days):
            tags.setdefault(symbol, "lookup")
    companies = [s for s in u.all_names() if s not in u.etfs]
    with vi.research_read() as rs:
        assert rs is not None
        have, want = vi.filings_coverage(rs, companies)
    if want and have * 100.0 < want * vcfg.service.min_filings_coverage_pct:
        log.warning(
            "value: waiting for the research sweep: filings for %d of %d names (need %.0f%%)",
            have,
            want,
            vcfg.service.min_filings_coverage_pct,
        )
        return None
    return RunPlan(
        as_of=as_of,
        tags=tags,
        etfs=set(u.etfs),
        evidence=set(u.evidence),
        classification=dict(u.classification),
    )


def load_inputs(
    plan: RunPlan,
    rs: Session,
    *,
    facts: dict[str, MarketFacts],
    earnings: dict[str, date],
    regime: str,
) -> list[ValueInputs]:
    """Every name's scorecard input as of the plan's session (filings filed by then, bars up to
    then). Earnings: news.db first, yfinance's calendar as the fallback (spec §6.6)."""
    spy = vi.read_bars(rs, shadow.BENCHMARK, plan.as_of)
    out: list[ValueInputs] = []
    stale = get_config().value.rules.data_quality.stale_item_days
    for symbol in plan.names:
        cik, payload = vi.read_payload(rs, symbol)
        mf = facts.get(symbol, MarketFacts())
        sector, industry = plan.classification.get(symbol, (None, None))
        out.append(
            ValueInputs(
                symbol=symbol,
                cik=cik,
                as_of=plan.as_of,
                financials=None
                if payload is None
                else vi.build_value_financials(payload, as_of=plan.as_of, stale_item_days=stale),
                price=vi.build_price_series(vi.read_bars(rs, symbol, plan.as_of), spy),
                classification=Classification(
                    sector=sector or mf.sector,
                    industry=industry or mf.industry,
                    source="snapshot" if industry else ("yfinance" if mf.industry else "none"),
                    is_etf=symbol in plan.etfs
                    or mf.quote_type == "ETF"
                    or vi.symbol_is_etf(rs, symbol),
                ),
                yf_market_cap=mf.market_cap,
                next_earnings=earnings.get(symbol, mf.next_earnings),
                regime=regime,
            )
        )
    return out


def run_nightly(
    plan: RunPlan,
    *,
    facts: dict[str, MarketFacts],
    earnings: dict[str, date],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Score, rank, persist the ticker files, run the shadow record and log the run, all in one
    value.db transaction. Returns the run's summary."""
    vcfg = get_config().value
    version, digest = ruleset_id(vcfg)
    started = now or _now()
    regime = vi.load_regime()
    with vi.research_read() as rs:
        if rs is None:
            raise RuntimeError("research.db not found")
        inputs = load_inputs(plan, rs, facts=facts, earnings=earnings, regime=regime)
        cutoff = rs_cutoff([i.price for i in inputs], vcfg.rules.timing.rs_bottom_pct)
        inputs = [i.model_copy(update={"rs_cutoff_6m": cutoff}) for i in inputs]
        cards = [build_scorecard(i, vcfg) for i in inputs]
        deep, growth = rank_list(cards, "deep_value"), rank_list(cards, "quality_growth")
        filed = filed_lists(cards, deep, growth)
        atr = {i.symbol: i.price.atr14 if i.price else None for i in inputs}
        with value_session() as vs:
            for card in cards:
                d, g = deep.get(card.symbol), growth.get(card.symbol)
                tag = plan.tags[card.symbol]
                persist(
                    vs,
                    card,
                    universe=tag,
                    ranks={
                        "deep_value": d.score if d else None,
                        "quality_growth": g.score if g else None,
                    },
                    filed=filed.get(card.symbol),
                    cfg=vcfg.ticker_file,
                    session_row=tag != "lookup",
                )
            vs.flush()
            record = shadow.process(
                vs,
                rs,
                cards,
                tags=plan.tags,
                atr=atr,
                evidence=plan.evidence,
                as_of=plan.as_of,
                cfg=vcfg,
                version=version,
                digest=digest,
                now=started,
            )
            verdicts = {
                name: dict(Counter(c.verdict_for(name) for c in cards))
                for name in ("deep_value", "quality_growth")
            }
            summary = {
                "regime": regime,
                "rs_cutoff_6m": cutoff,
                "verdicts": verdicts,
                "missing_market_cap": sum(
                    1 for i in inputs if not i.classification.is_etf and i.yf_market_cap is None
                ),
                "shadow": asdict(record),
            }
            record_run(
                vs,
                kind="nightly",
                started_at=started,
                finished_at=_now(),
                as_of=plan.as_of,
                ruleset_version=version,
                ruleset_hash=digest,
                names=len(cards),
                rs_cutoff_6m=cutoff,
                summary_json=json.dumps(summary, sort_keys=True),
            )
    log.info("value nightly %s: %d names; %s", plan.as_of, len(cards), json.dumps(summary))
    return summary
```

- [x] **Step 4: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_service.py tests/test_value_shadow.py tests/test_value_store.py`
  Expected: PASS (`test_value_service.py` 7). Ruff and `.venv/bin/mypy src/value` clean.

- [x] **Step 5: Commit**

  ```bash
  git add src/value/service.py tests/test_value_service.py docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "feat(value): the nightly run - plan, score, persist, shadow, one transaction"
  ```

---

### Task 8: The entrypoint, its feed and the supervisor

**Files:** Create `scripts/value_feed.py`, `scripts/run_value.py`, `tests/test_value_feed.py`;
modify `scripts/start.py` (after lines 21, 95 and 422), `ibkr` (lines 26 and 68),
`tests/test_start_launcher.py` (append)

**Interfaces:**
- Produces: `scripts.value_feed.earnings_dates(as_of: date) -> dict[str, date]` (news.db,
  read-only, the earliest report on or after `as_of` within 180 days; `{}` when news.db is
  unreadable); `scripts.value_feed.market_facts(names: list[str], workers: int) -> dict[str,
  MarketFacts]`; `scripts/run_value.py::main()`; `SERVICES["value"]` = `value_service`,
  `scripts.run_value`, `logs/value.log`; `--no-value`; `./ibkr logs value`.

- [x] **Step 1: Write the failing tests** — `tests/test_value_feed.py` (the entrypoint itself is
  only compiled, never imported):

```python
"""scripts/value_feed.py: the plain data the value process hands to src/value/ (value book spec
§6.6). ``scripts/run_value.py`` itself is never imported: it is compiled only."""

from __future__ import annotations

import py_compile
from datetime import date

import src.common.value_inputs as vi
from scripts import value_feed
from src.common.value_types import MarketFacts


def test_the_entrypoint_compiles() -> None:
    py_compile.compile("scripts/run_value.py", doraise=True)
    py_compile.compile("scripts/value_feed.py", doraise=True)


def test_earnings_come_from_news_db_earliest_first(news_db) -> None:
    from src.news.store.models import EarningsEventRow
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(EarningsEventRow(symbol="MU", report_date=date(2026, 12, 17)))
        s.add(EarningsEventRow(symbol="MU", report_date=date(2027, 3, 20)))
        s.add(EarningsEventRow(symbol="BAC", report_date=date(2026, 10, 14)))  # already past
        s.add(EarningsEventRow(symbol="FAR", report_date=date(2027, 8, 1)))  # beyond 180 days
    assert value_feed.earnings_dates(date(2026, 11, 2)) == {"MU": date(2026, 12, 17)}


def test_an_unreadable_news_db_means_no_dates_not_a_crash() -> None:
    assert value_feed.earnings_dates(date(2026, 11, 2)) == {}  # conftest points at no file


def test_market_facts_are_fetched_per_name(monkeypatch) -> None:
    monkeypatch.setattr(vi, "fetch_market_facts", lambda s: MarketFacts(market_cap=len(s) * 1e9))
    assert value_feed.market_facts(["MU", "GOOGL"], 2) == {
        "MU": MarketFacts(market_cap=2e9),
        "GOOGL": MarketFacts(market_cap=5e9),
    }
```

  …and append to `tests/test_start_launcher.py`:

  ```python


  def test_value_service_is_supervised_and_can_be_skipped():
      assert start.SERVICES["value"]["module"] == "scripts.run_value"
      assert start.SERVICES["value"]["log"].name == "value.log"
      args = start._build_parser().parse_args(["--no-value"])
      active = start._active_services(args)
      assert "value" not in active and "news" in active
  ```

- [x] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_feed.py tests/test_start_launcher.py`
  Expected: FAIL — `ImportError: cannot import name 'value_feed' from 'scripts'` and
  `KeyError: 'value'`.

- [x] **Step 3: The feed** — `scripts/value_feed.py`:

```python
"""The plain data the value process hands to ``src/value/`` (spec §6.6, §6.9): earnings dates
from news.db and yfinance market facts. ``src/value/`` may fetch neither itself: news.db is
enrichment's database and yfinance is a network provider, so ``scripts/run_value.py`` gathers
both here and passes them in as dicts.

Importable (no side effects at import), so it is tested and fenced; ``scripts/run_value.py`` is
not imported by anything.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from src.common.value_types import MarketFacts

log = logging.getLogger(__name__)

EARNINGS_HORIZON_DAYS = 180


def earnings_dates(as_of: date) -> dict[str, date]:
    """Each name's earliest earnings date on or after *as_of* from news.db's
    ``earnings_events`` (read-only). An unreadable news.db is an empty dict: the scorecard then
    falls back to yfinance's calendar, and a missing date is UNKNOWN timing, never a pass."""
    import src.news.store.queries as queries
    from src.news.store.readonly import read_only_session

    out: dict[str, date] = {}
    with read_only_session() as s:
        if s is None:
            log.warning("value feed: news.db unreadable; earnings fall back to yfinance")
            return out
        for e in queries.earnings_between(s, as_of, as_of + timedelta(days=EARNINGS_HORIZON_DAYS)):
            out.setdefault(e.symbol, e.report_date)
    return out


def market_facts(names: list[str], workers: int) -> dict[str, MarketFacts]:
    """yfinance market cap, sector, industry, quote type and next earnings for each name
    (``fetch_market_facts`` never raises: a failed read is an empty ``MarketFacts``)."""
    from src.common.value_inputs import fetch_market_facts

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(names, pool.map(fetch_market_facts, names), strict=True))
```

- [x] **Step 4: The entrypoint** — `scripts/run_value.py` (the `scripts/run_research_worker.py`
  pattern: a thread event, two signal handlers, no IBKR, no asyncio):

```python
"""Value book service entrypoint (docs/superpowers/specs/2026-10-28-value-swing-book-design.md).

Usage:
    python -m scripts.run_value

No IBKR connection, no clientId (Parts 1-4). Every ``value.service.poll_seconds`` it asks
``src.value.service.plan_run`` whether a settled session is waiting to be scored; when one is
(after ``value.service.run_hour_et``), it gathers the plain data ``src/value/`` may not fetch
itself (``scripts/value_feed.py``) and runs the night. Idles when the ruleset check fails.
Runs until SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.

The only module that will import ``src.value_ai`` (Part 4). Never import this file: check it
with ``python -m py_compile``.
"""

import logging
import signal
import threading

from scripts.value_feed import earnings_dates, market_facts
from src.common.config import get_config
from src.common.logging import setup_logging
from src.value.service import plan_run, run_nightly, startup_check

log = logging.getLogger("value")


def _tick() -> None:
    plan = plan_run()
    if plan is None:
        return
    workers = get_config().value.service.market_facts_workers
    log.info("value: scoring %d names for %s", len(plan.names), plan.as_of)
    facts = market_facts(plan.fetch_names, workers)
    run_nightly(plan, facts=facts, earnings=earnings_dates(plan.as_of))


def main() -> None:
    setup_logging()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    problem = startup_check()
    if problem is not None:
        log.critical("value: idle until the config is fixed and the process restarted: %s", problem)
        stop.wait()
        return
    poll = get_config().value.service.poll_seconds
    log.info("value: running; checking for a settled session every %ds", poll)
    while True:
        try:
            _tick()
        except Exception:  # noqa: BLE001 - a failed night is retried at the next poll
            log.exception("value: the nightly run failed; retrying at the next poll")
        if stop.wait(poll):
            break


if __name__ == "__main__":
    main()
```

  Check it without importing it: `.venv/bin/python -m py_compile scripts/run_value.py` prints
  nothing.

- [x] **Step 5: Register it** — apply to `scripts/start.py`:

```diff
diff --git a/scripts/start.py b/scripts/start.py
--- a/scripts/start.py
+++ b/scripts/start.py
@@ -20,4 +20,5 @@ Usage:
     python -m scripts.start --no-spreads   # skip the daily credit-spread service
     python -m scripts.start --no-news      # skip the news service
+    python -m scripts.start --no-value     # skip the value book's nightly service
     python -m scripts.start --no-eod       # skip the built-in EOD scheduler
 
@@ -94,4 +95,9 @@ SERVICES = {
         "log": PROJECT_ROOT / "logs" / "news.log",
     },
+    "value": {
+        "label": "value_service",
+        "module": "scripts.run_value",
+        "log": PROJECT_ROOT / "logs" / "value.log",
+    },
 }
 
@@ -421,4 +427,7 @@ def _build_parser() -> argparse.ArgumentParser:
     )
     parser.add_argument("--no-news", action="store_true", help="Skip the news service")
+    parser.add_argument(
+        "--no-value", action="store_true", help="Skip the value book's nightly service"
+    )
     parser.add_argument("--no-eod", action="store_true", help="Skip the built-in EOD scheduler")
     return parser
```

  …and to `ibkr` (both usage lines learn `value`):

```diff
diff --git a/ibkr b/ibkr
--- a/ibkr
+++ b/ibkr
@@ -24,5 +24,5 @@ Usage: ibkr <command> [args]
   restart                    stop, then start (the watchdog is never touched)
   status                     Agent state/pid plus the watchdog's own health checks
-  logs <name>                Tail a log: approval|monitor|api|research|eod|spreads|news|watchdog|supervisor
+  logs <name>                Tail a log: approval|monitor|api|research|eod|spreads|news|value|watchdog|supervisor
   watchdog                   Run one watchdog health check now (not through launchd)
   autonomy [level]           Show/set the autonomy rung (scripts/autonomy.py, Task 12)
@@ -66,5 +66,5 @@ case "${cmd}" in
     name="${1:-}"
     if [[ -z "${name}" ]]; then
-      echo "Usage: ibkr logs <approval|monitor|api|research|eod|spreads|news|watchdog|supervisor>" >&2
+      echo "Usage: ibkr logs <approval|monitor|api|research|eod|spreads|news|value|watchdog|supervisor>" >&2
       exit 1
     fi
```

  `bash -n ibkr` prints nothing.

- [x] **Step 6: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_feed.py tests/test_start_launcher.py tests/test_watchdog.py`
  Expected: PASS (4 + 8). Ruff check/format on the four Python files; `.venv/bin/mypy
  scripts/value_feed.py scripts/run_value.py` clean.

- [x] **Step 7: Commit**

  ```bash
  git add scripts/value_feed.py scripts/run_value.py scripts/start.py ibkr tests/test_value_feed.py tests/test_start_launcher.py docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "feat(value): scripts/run_value.py, its news/yfinance feed, supervised by ./ibkr"
  ```

---

### Task 9: The fences

**Files:** Modify `tests/test_value_fence.py` (lines 31, 165, 178; append three tests)

**Interfaces:**
- Consumes: every module above. Produces: `exits`, `ranked` and `report` join `PURE`; the four
  new row classes join the "only `src/value/` constructs `value.db` rows" scan; the scorecard probe
  imports the new modules; three new tests: only `scripts/run_value.py` may import `src.value_ai`;
  `scripts/run_value.py` imports only its feed, the service, the config and logging; the whole
  value process loads no wheel layer, no Claude, no `ib_async` and never `news.db`'s read-write
  engine.

- [x] **Step 1: Write the tests** — apply to `tests/test_value_fence.py`:

```diff
diff --git a/tests/test_value_fence.py b/tests/test_value_fence.py
--- a/tests/test_value_fence.py
+++ b/tests/test_value_fence.py
@@ -30,4 +30,7 @@ PURE = (
     "funnel",
     "ruleset",
+    "exits",
+    "ranked",
+    "report",
 )
 
@@ -163,5 +166,13 @@ def test_the_trading_path_never_imports_the_value_book() -> None:
 
 def test_only_src_value_constructs_value_rows() -> None:
-    rows = ("ValueTickerFileRow(", "ValueTickerHistoryRow(", "ValueRunRow(")
+    rows = (
+        "ValueTickerFileRow(",
+        "ValueTickerHistoryRow(",
+        "ValueRunRow(",
+        "ValueShadowRow(",
+        "ValueShadowLegRow(",
+        "ValueShadowEventRow(",
+        "ValueRankedRow(",
+    )
     offenders = []
     for p in [*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")]:
@@ -177,4 +188,5 @@ def test_the_value_scorecard_loads_no_wheel_layer_even_transitively() -> None:
         "import json, sys\n"
         "import src.value.scorecard, src.value.store, src.value.ticker_file, src.value.funnel\n"
+        "import src.value.exits, src.value.shadow, src.value.service, src.value.report\n"
         "import src.common.value_inputs, src.common.value_universe\n"
         "print(json.dumps(sorted(m for m in sys.modules if m.startswith('src.'))))\n"
@@ -196,2 +208,57 @@ def test_the_value_scorecard_loads_no_wheel_layer_even_transitively() -> None:
     ]
     assert bad == []
+
+
+def test_only_the_value_entrypoint_may_import_value_ai() -> None:
+    """Spec §5/§16: scripts/run_value.py is the only importer of src.value_ai (Part 4)."""
+    outside = [
+        p for p in (ROOT / "src").rglob("*.py") if (ROOT / "src" / "value_ai") not in p.parents
+    ]
+    scripts = [p for p in (ROOT / "scripts").glob("*.py") if p.stem != "run_value"]
+    offenders = [
+        str(p.relative_to(ROOT))
+        for p in [*outside, *scripts]
+        if _reaches(imported_modules(p), "src.value_ai")
+    ]
+    assert offenders == []
+
+
+def test_the_value_entrypoint_imports_only_its_feed_and_the_service() -> None:
+    """scripts/run_value.py is never imported (it starts a service), so its own imports are
+    checked by name; everything it reaches is in the sys.modules probe below."""
+    allowed = (
+        "logging",
+        "signal",
+        "threading",
+        "scripts.value_feed",
+        "src.common.config",
+        "src.common.logging",
+        "src.value.service",
+    )
+    mods = imported_modules(ROOT / "scripts" / "run_value.py")
+    extra = sorted(m for m in mods if not any(m == a or m.startswith(a + ".") for a in allowed))
+    assert extra == []
+
+
+def test_the_value_process_loads_no_wheel_layer_and_no_ibkr() -> None:
+    """Everything the value process imports, including the news.db readers its feed uses for
+    earnings dates: no wheel layer, no Claude, no IBKR client, and never news.db's read-write
+    engine."""
+    probe = (
+        "import importlib, json, pkgutil, sys\n"
+        "import src.value as v\n"
+        "for m in pkgutil.walk_packages(v.__path__, 'src.value.'):\n"
+        "    importlib.import_module(m.name)\n"
+        "import scripts.value_feed\n"
+        "import src.news.store.readonly, src.news.store.queries, src.data.factory\n"
+        "print(json.dumps(sorted(sys.modules)))\n"
+    )
+    env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
+    out = subprocess.run(
+        [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True
+    )
+    loaded = set(json.loads(out.stdout.strip().splitlines()[-1]))
+    forbidden = [f for f in FORBIDDEN_FOR_VALUE if f != "src.news"]
+    assert [m for m in forbidden if _reaches(loaded, m)] == []
+    assert not _reaches(loaded, "src.news.store.session")
+    assert not _reaches(loaded, "ib_async")
```

- [x] **Step 2: Run them.** They pass at once if Tasks 1–8 sit inside the fence — that is the
  point. To see the new tests bite, temporarily add `import src.engine.risk_engine` to
  `src/value/exits.py` (`test_value_imports_no_enrichment_and_no_other_system` and the process
  probe fail), then remove it; and temporarily add `import os` to `scripts/run_value.py` (the
  allowlist test fails), then remove it. Record both red runs in the Progress log.

  Run: `.venv/bin/python -m pytest -q tests/test_value_fence.py tests/test_spreads_fence.py tests/test_news_fence.py tests/test_regime_fence.py tests/test_web_fence.py tests/test_eval_skills.py`
  Expected: PASS (`test_value_fence.py` 13).

- [x] **Step 3: Commit, then the section's Progress-log commit**

  ```bash
  git add tests/test_value_fence.py docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "test(value): the fence covers the shadow record and the value process"
  ```

  Then the full gate (Section exit), Task 9's row, and one command each:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "docs(plan): value book Part 2 Progress log - Section C"
  ```

---

## Section D — The report, the postmortem and the docs (Tasks 10–11) · model: sonnet · effort: medium

The pure report with its pinned statistics, the read-only script that prints it, and the doc
sweep. After this section the code of Part 2 is complete.

**Spec to read:** §6.8 (the last paragraph of the shadow ledger: `value_report`), §7 (the
"`value_report` prints the three side by side" paragraph), §11 (the postmortem sentence), §12, §18.

**Files the subagent reads:** this section; `src/value/report.py` (the stub), `src/value/store.py`
(the four shadow tables), `src/value/schemas.py` (`Check`, `ValueScorecard`), `src/value/funnel.py`
(the rendering style), `scripts/value_dry_run.py` (the script style), and for Task 11 the doc anchors
D3 names.

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **D1. Section C landed.** Tasks 7–9 ticked; record `git log --oneline main..HEAD | wc -l`.
- [ ] **D2. Green, from the worktree root.** `.venv/bin/python -m pytest -q` = baseline + 62,
  `.venv/bin/ruff check .`, `.venv/bin/mypy src`, `.venv/bin/python -m py_compile
  scripts/run_value.py` silent.
- [ ] **D3. The doc anchors Task 11 edits are where this plan says.** Each prints the line(s)
  shown (`main` at `23b1ef3`):

  ```bash
  grep -n "^companies against what they are worth. \*\*Part 1 (2026-10-29) is the scorecard only: nothing in$" ARCHITECTURE.md   # 1220:
  grep -n '^| `store.py` | `value.db`: `value_ticker_files` (latest)' ARCHITECTURE.md      # 1235:
  grep -n '^| `ruleset.py` | The ruleset fingerprint' ARCHITECTURE.md                    # 1238:
  grep -n '^Inputs come from `src/common/value_inputs.py` (read-only) in the plain shapes of$' ARCHITECTURE.md   # 1240:
  grep -n '^| `value_universe_snapshot.py` |' ARCHITECTURE.md                              # 1584:
  grep -n '`--no-news` skips it. |$' ARCHITECTURE.md                                       # 1559:
  grep -n '^| `healthcheck` | Manual | 19 |' ARCHITECTURE.md                               # 1612:
  grep -n "Part 1 places no order. Enforced by$" ARCHITECTURE.md                           # 1742:
  grep -n '^| `value.yaml` | The value book' ARCHITECTURE.md                               # 587:
  grep -n '^| `value_types.py` |\|^| `value_inputs.py` |' ARCHITECTURE.md                 # 1036: and 1037:
  grep -n '^`logs/research.log`, `logs/spreads.log` and `logs/news.log`. Stop with Ctrl-C' SETUP.md   # 638:
  grep -n "^## 19. The value book, Part 1: the scorecard and the calibration dry run$" SETUP.md      # 2033:
  grep -n "^2. The research worker can refresh the value universes nightly" SETUP.md       # 2040:
  grep -n '^4. `ruleset_version` is frozen at `v1`' SETUP.md                               # 2047:
  grep -n '^| `python -m scripts.value_universe_snapshot` |' SETUP.md                      # 2056:
  grep -n '^| \*\*Value book Parts 2–6\*\*' STATUS.md                                       # 346:
  grep -n "^## Built (2026-10-29 — value book Part 1" STATUS.md                            # 350:
  grep -n "^- Part 1 places, sizes and gates nothing. The written exception for Claude's value verdict$" CLAUDE.md   # 393:
  ```

**Section exit:** two more task commits plus the section's `docs(plan)` commit; full gate green
with pytest = baseline + 69; `.venv/bin/python -m py_compile scripts/run_value.py
scripts/value_feed.py scripts/value_report.py scripts/value_dry_run.py` silent; protected-file
diff empty. Record the commit count.

---

### Task 10: The report and the postmortem

**Files:** Replace the stub `src/value/report.py`; create `scripts/value_report.py`,
`tests/test_value_report.py`

**Interfaces:**
- Consumes: the four shadow tables (Task 6); `ValueScorecard`, `Check`.
- Produces: in `src.value.report` — `HORIZONS` (unchanged), `SURVIVORSHIP`, `EntryView`,
  `LegView`, `EventView`, `RankedView`, `Stat` (`n`, `clusters`, `mean`, `se`, `.t`),
  `clustered_mean(points: list[tuple[date, float]]) -> Stat`, `horizon_section`,
  `go_live_line(entries, track) -> str`, `policy_section(entries, legs, live_policy)`,
  `ranked_section(rows)`, `closest_gate(card, list_name) -> Check | None`,
  `postmortem(entry, legs, events, fair_value_now) -> list[str]`, `render(...) -> str`;
  `scripts.value_report.main(argv) -> int`.

- [ ] **Step 1: Write the failing tests** — `tests/test_value_report.py` (the clustered standard
  error is pinned by hand: n 4, mean 0.045, residual sums 0.07 / −0.065 / −0.005,
  SE = √(3/2 × 0.00915 / 16) = 0.0292884; the closest gates are the fixture's 30.00 close against
  its 27.52 SMA200, 9.005% of room, just under ROIC's 16.36 vs 15, 9.04%):

```python
"""The shadow record's report (value book spec §6.8, §7, §11, §12): clustered errors, the go-live
line, the three policies side by side, the ranked record, postmortems, and the script."""

from __future__ import annotations

from datetime import date, datetime

import pytest

import src.value.store as store
from scripts import value_report
from src.common.config import get_config
from src.value.report import (
    SURVIVORSHIP,
    EntryView,
    EventView,
    LegView,
    RankedView,
    closest_gate,
    clustered_mean,
    go_live_line,
    postmortem,
    ranked_section,
    render,
)
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
    init_value_db,
    value_session,
)
from tests.value_fixtures import inputs

D1, D2, D3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)


def test_errors_are_clustered_by_entry_date() -> None:
    s = clustered_mean([(D1, 0.10), (D1, 0.06), (D2, -0.02), (D3, 0.04)])
    assert (s.n, s.clusters) == (4, 3)
    assert s.mean == pytest.approx(0.045)
    assert s.se == pytest.approx(0.029288436284649957)  # sqrt(3/2 x 0.00915 / 16)
    assert s.t == pytest.approx(1.5364425591947515)
    one_day = clustered_mean([(D1, 0.10), (D1, 0.06)])
    assert one_day.se is None and one_day.t is None  # one market day is one observation
    assert clustered_mean([]).mean is None


def _entry(i: int, day: date, ret63: float | None, **kw) -> EntryView:
    base = dict(
        id=i,
        track="baseline",
        kind="ready",
        list_name="deep_value",
        symbol=f"N{i}",
        universe="evidence",
        status="open",
        signal_date=day,
        entry_date=day,
        entry_price=100.0,
        fair_value=140.0,
        margin_of_safety=0.29,
        ruleset_version="v2",
        returns={21: 0.01, 63: ret63, 126: None},
        spy={21: 0.0, 63: 0.01 if ret63 is not None else None, 126: None},
    )
    base.update(kw)
    return EntryView(**base)


def test_the_go_live_line_counts_only_the_tracks_ready_entries() -> None:
    entries = [_entry(i, D1, 0.05) for i in range(3)] + [
        _entry(9, D2, 0.05, kind="control_valuation")
    ]
    line = go_live_line(entries, "baseline")
    assert "n 3 of 30 needed" in line and "+4.0%" in line and "not enough entries yet" in line
    many = [_entry(i, [D1, D2, D3][i % 3], -0.02) for i in range(30)]
    assert "at or below zero: do not go live" in go_live_line(many, "baseline")


def test_the_ranked_section_shows_each_bucket_and_the_spread() -> None:
    rows = [
        RankedView(
            formed_on=D1, list_name="deep_value", bucket=b, n=5, closed_on=D3, ret=r, spy_ret=0.01
        )
        for b, r in (("top", 0.03), ("bottom", -0.01), ("all", 0.01))
    ]
    text = "\n".join(ranked_section(rows))
    assert "top     months   1  mean +3.0%/month" in text
    assert "top - bottom: mean +4.0%/month over 1" in text
    assert "no month closed yet" in "\n".join(ranked_section([]))


def test_the_gate_closest_to_wrong_is_the_passing_check_with_least_room() -> None:
    card = build_scorecard(inputs(), get_config().value)
    deep = closest_gate(card, "deep_value")
    assert deep is not None and deep.id == "timing.trend"  # 30.00 vs the 27.52 SMA200: 9.0%
    growth = closest_gate(card, "quality_growth")
    assert growth is not None and growth.id == "timing.not_breaking_down"  # 9.005% < ROIC's 9.04%


def test_a_postmortem_tells_the_whole_story() -> None:
    card = build_scorecard(inputs(), get_config().value)
    e = _entry(1, D1, 0.05, status="closed", scorecard_json=card.model_dump_json())
    legs = [
        LegView(
            shadow_id=1,
            policy="value",
            closed=True,
            exit_date=D3,
            ret=0.2,
            spy_ret=0.05,
            max_drawdown=-0.04,
            sessions=40,
            sells=2,
        )
    ]
    events = [
        EventView(shadow_id=1, policy="value", day=D2, kind="half", price=140.0, fraction=0.5),
        EventView(shadow_id=1, policy="value", day=D3, kind="fill", price=141.0, fraction=0.5),
    ]
    text = "\n".join(postmortem(e, legs, events, 150.0))
    assert "fair value then 140.0 (margin of safety +29.0%), now 150.0" in text
    assert "value: exit 2026-01-07 return +20.0% (SPY +5.0%)" in text
    assert "2026-01-06 half; 2026-01-07 fill 50% @ 141.00" in text
    assert "closest to wrong: timing.trend 30.00 vs bar 27.52" in text


def test_render_leads_with_the_survivorship_caveat_and_marks_the_live_policy() -> None:
    entries = [_entry(1, D1, 0.05)]
    legs = [
        LegView(
            shadow_id=1,
            policy=p,
            closed=True,
            ret=0.1,
            spy_ret=0.02,
            max_drawdown=-0.05,
            sessions=30,
            sells=1,
        )
        for p in ("full", "value", "hold12")
    ]
    text = render(
        entries,
        legs,
        [],
        [],
        fair_values_now={},
        live_policy="value",
        track="baseline",
        postmortems=False,
    )
    assert text.splitlines()[1] == SURVIVORSHIP
    assert "value (live)" in text and "full (diagnostic)" in text and "hold12 (diagnostic)" in text
    assert "63 sessions" in text and "excess +4.0%" in text


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def test_the_script_reads_value_db_and_prints_the_record(value_db, capsys) -> None:
    card = build_scorecard(inputs(), get_config().value)
    with value_session() as s:
        row = ValueShadowRow(
            track="baseline",
            kind="ready",
            list_name="deep_value",
            symbol="STDY",
            universe="trading",
            signal_date=D1,
            status="closed",
            verdict="READY",
            fingerprint_key="0" * 16,
            ruleset_version="v2",
            ruleset_hash="x",
            scorecard_json=card.model_dump_json(),
            created_at=datetime(2026, 1, 5),
            entry_date=D2,
            entry_price=30.0,
            spy_entry_price=500.0,
            ret_21=0.02,
            spy_21=0.01,
            ret_63=0.05,
            spy_63=0.02,
            ret_126=0.08,
            spy_126=0.03,
        )
        s.add(row)
        s.flush()
        s.add(
            ValueShadowLegRow(
                shadow_id=row.id,
                policy="value",
                state_json="{}",
                closed=True,
                exit_date=D3,
                ret_exit=0.1,
                spy_ret_exit=0.01,
                sessions=3,
                sells=1,
                max_drawdown=-0.02,
            )
        )
        s.add(
            ValueShadowEventRow(
                shadow_id=row.id, policy="value", day=D3, kind="fill", price=33.0, fraction=1.0
            )
        )
    assert value_report.main(["--postmortems"]) == 0
    out = capsys.readouterr().out
    assert SURVIVORSHIP in out
    assert "[baseline · deep_value · ready] 1 entries" in out
    assert "## STDY deep_value #1" in out and "2026-01-07 fill 100% @ 33.00" in out
```

- [ ] **Step 2: Run them to see them fail**

  Run: `.venv/bin/python -m pytest -q tests/test_value_report.py`
  Expected: collection error, `ImportError: cannot import name 'SURVIVORSHIP' from
  'src.value.report'` (or `cannot import name 'value_report' from 'scripts'`).

- [ ] **Step 3: The report** — replace `src/value/report.py` with:

```python
"""The shadow record's report (spec §6.8, §7, §11, §12). Pure: no I/O.

``scripts/value_report.py`` reads value.db and hands plain views in. Returns are measured at
fixed horizons on every entry, marked to market, with standard errors clustered by entry date
(spec §12); the three exit policies side by side on the same READY entries (spec §7); the
ranked monthly record (spec §6.8); and a postmortem per closed position (spec §11). The report
proves nothing on its own: it is what a human reads before any go-live decision.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import mean

from pydantic import BaseModel, Field

from src.value.schemas import Check, ValueScorecard

HORIZONS = (21, 63, 126)  # sessions after the entry session (spec §6.8, §12)
SURVIVORSHIP = (
    "Prices carry yfinance's survivorship bias: delisted names are absent, so every return "
    "here flatters the rules (spec §6.2)."
)
GO_LIVE_ENTRIES = 30  # spec §12: the live track needs at least 30 entries
GO_LIVE_HORIZON = 63


class EntryView(BaseModel):
    id: int
    track: str
    kind: str
    list_name: str
    symbol: str
    universe: str
    status: str
    signal_date: date
    entry_date: date | None = None
    entry_price: float | None = None
    fair_value: float | None = None
    margin_of_safety: float | None = None
    ruleset_version: str
    returns: dict[int, float | None] = Field(default_factory=dict)
    spy: dict[int, float | None] = Field(default_factory=dict)
    scorecard_json: str = ""


class LegView(BaseModel):
    shadow_id: int
    policy: str
    closed: bool
    exit_date: date | None = None
    ret: float | None = None
    spy_ret: float | None = None
    max_drawdown: float | None = None
    sessions: int = 0
    sells: int = 0


class EventView(BaseModel):
    shadow_id: int
    policy: str
    day: date
    kind: str
    price: float | None = None
    fraction: float = 0.0
    detail: str = ""


class RankedView(BaseModel):
    formed_on: date
    list_name: str
    bucket: str
    n: int
    closed_on: date | None = None
    ret: float | None = None
    spy_ret: float | None = None
    missing: int = 0


@dataclass(frozen=True, slots=True)
class Stat:
    n: int
    clusters: int
    mean: float | None
    se: float | None  # clustered by entry date; None below two clusters

    @property
    def t(self) -> float | None:
        if self.mean is None or not self.se:
            return None
        return self.mean / self.se


def clustered_mean(points: list[tuple[date, float]]) -> Stat:
    """The mean of *points* and its standard error clustered by date: entries made on one day
    share that day's market, so they are not independent (spec §12). With G clusters,
    SE^2 = G / (G - 1) x sum over clusters of (sum of residuals)^2 / n^2."""
    n = len(points)
    if n == 0:
        return Stat(0, 0, None, None)
    m = sum(x for _, x in points) / n
    sums: dict[date, float] = defaultdict(float)
    for d, x in points:
        sums[d] += x - m
    g = len(sums)
    if g < 2:
        return Stat(n, g, m, None)
    var = g / (g - 1) * sum(s * s for s in sums.values()) / (n * n)
    return Stat(n, g, m, math.sqrt(var))


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:+.1f}%"


def _stat_line(label: str, rets: list[float], spys: list[float], s: Stat) -> str:
    t = "n/a" if s.t is None else f"{s.t:.2f}"
    se = "n/a" if s.se is None else f"{s.se * 100:.1f}%"
    return (
        f"  {label:<12} n {s.n:>4} ({s.clusters} dates)  return {_pct(mean(rets))}  "
        f"SPY {_pct(mean(spys))}  excess {_pct(s.mean)} ± {se}  t {t}"
    )


def horizon_section(entries: list[EntryView]) -> list[str]:
    """Every entry, READY and control alike, at 21/63/126 sessions against SPY."""
    lines = ["-- Fixed horizons (marked to market; errors clustered by entry date) --"]
    groups: dict[tuple[str, str, str], list[EntryView]] = defaultdict(list)
    for e in entries:
        groups[(e.track, e.list_name, e.kind)].append(e)
    if not groups:
        return [*lines, "  no entries yet"]
    for (track, list_name, kind), group in sorted(groups.items()):
        lines.append(f"[{track} · {list_name} · {kind}] {len(group)} entries")
        for h in HORIZONS:
            marked = [
                e
                for e in group
                if e.returns.get(h) is not None and e.spy.get(h) is not None and e.entry_date
            ]
            if not marked:
                lines.append(f"  {h:>3} sessions: none marked yet")
                continue
            rets = [e.returns[h] or 0.0 for e in marked]
            spys = [e.spy[h] or 0.0 for e in marked]
            excess = [
                (e.entry_date, (e.returns[h] or 0.0) - (e.spy[h] or 0.0))
                for e in marked
                if e.entry_date is not None
            ]
            lines.append(_stat_line(f"{h} sessions", rets, spys, clustered_mean(excess)))
    return lines


def go_live_line(entries: list[EntryView], track: str) -> str:
    """Spec §12's first go-live line for the track that would run live (the value policy reads
    the same entries; fixed horizons do not depend on the exit policy)."""
    marked: list[tuple[date, float]] = []
    for e in entries:
        ret, spy = e.returns.get(GO_LIVE_HORIZON), e.spy.get(GO_LIVE_HORIZON)
        if e.track == track and e.kind == "ready" and e.entry_date and ret is not None and spy:
            marked.append((e.entry_date, ret - spy))
    s = clustered_mean(marked)
    verdict = (
        "not enough entries yet"
        if s.n < GO_LIVE_ENTRIES
        else ("above zero" if (s.mean or 0.0) > 0 else "at or below zero: do not go live")
    )
    return (
        f"Go-live check ({track}, READY, {GO_LIVE_HORIZON}-session excess over SPY): "
        f"n {s.n} of {GO_LIVE_ENTRIES} needed, mean {_pct(s.mean)}: {verdict} (spec §12)"
    )


def policy_section(entries: list[EntryView], legs: list[LegView], live_policy: str) -> list[str]:
    """The three exit policies side by side on the same READY entries (spec §7)."""
    lines = ["-- Exit policies on the same READY entries (closed legs) --"]
    by_id = {e.id: e for e in entries if e.kind == "ready"}
    groups: dict[tuple[str, str], list[LegView]] = defaultdict(list)
    for leg in legs:
        e = by_id.get(leg.shadow_id)
        if e is not None:
            groups[(e.list_name, leg.policy)].append(leg)
    if not groups:
        return [*lines, "  no READY entries yet"]
    for (list_name, policy), group in sorted(groups.items()):
        done = [g for g in group if g.closed and g.ret is not None]
        tag = " (live)" if policy == live_policy else " (diagnostic)"
        if not done:
            lines.append(f"  {list_name:<15} {policy + tag:<20} {len(group)} held, none closed")
            continue
        vs = [g.ret - g.spy_ret for g in done if g.ret is not None and g.spy_ret is not None]
        dd = [g.max_drawdown for g in done if g.max_drawdown is not None]
        lines.append(
            f"  {list_name:<15} {policy + tag:<20} closed {len(done)}/{len(group)}  "
            f"return {_pct(mean(g.ret for g in done if g.ret is not None))}  "
            f"vs SPY {_pct(mean(vs) if vs else None)}  max DD {_pct(mean(dd) if dd else None)}  "
            f"held {mean(g.sessions for g in done):.0f} sessions  "
            f"sells/entry {mean(g.sells for g in done):.1f}"
        )
    return lines


def ranked_section(rows: list[RankedView]) -> list[str]:
    """Top tenth, bottom tenth and the whole scored universe per list, month by month (spec
    §6.8): the decile test of whether the method picks better companies."""
    lines = ["-- Ranked monthly record (equal weight, held to the next formation) --"]
    closed = [r for r in rows if r.closed_on is not None and r.ret is not None]
    if not closed:
        open_n = len({r.formed_on for r in rows})
        return [*lines, f"  no month closed yet ({open_n} formation(s) open)"]
    by: dict[tuple[str, str], list[RankedView]] = defaultdict(list)
    for r in closed:
        by[(r.list_name, r.bucket)].append(r)
    for list_name in sorted({k[0] for k in by}):
        for bucket in ("top", "bottom", "all"):
            group = by.get((list_name, bucket), [])
            if not group:
                continue
            rets = [r.ret for r in group if r.ret is not None]
            spys = [r.spy_ret for r in group if r.spy_ret is not None]
            missing = sum(r.missing for r in group)
            lines.append(
                f"  {list_name:<15} {bucket:<7} months {len(group):>3}  "
                f"mean {_pct(mean(rets))}/month  SPY {_pct(mean(spys) if spys else None)}/month"
                f"  members dropped {missing}"
            )
        tops = {r.formed_on: r.ret for r in by.get((list_name, "top"), [])}
        bottoms = {r.formed_on: r.ret for r in by.get((list_name, "bottom"), [])}
        spread = [
            (d, (tops[d] or 0.0) - (bottoms[d] or 0.0)) for d in sorted(set(tops) & set(bottoms))
        ]
        s = clustered_mean(spread)
        lines.append(f"  {list_name:<15} top - bottom: mean {_pct(s.mean)}/month over {s.n}")
    return lines


def closest_gate(card: ValueScorecard, list_name: str) -> Check | None:
    """The passing check with the least room to its bar at entry (spec §11: "which gate was
    closest to wrong"): relative distance |actual - bar| / |bar|, absolute when the bar is 0."""
    ev = card.lists.get(list_name)
    checks = [
        *card.health_checks,
        *(ev.entry_checks if ev else []),
        *(ev.timing_checks if ev else []),
    ]
    best: tuple[float, Check] | None = None
    for c in checks:
        if c.state != "pass" or c.actual is None or c.threshold is None:
            continue
        gap = abs(c.actual - c.threshold)
        room = gap / abs(c.threshold) if c.threshold else gap
        if best is None or room < best[0]:
            best = (room, c)
    return best[1] if best else None


def postmortem(
    entry: EntryView,
    legs: list[LegView],
    events: list[EventView],
    fair_value_now: float | None,
) -> list[str]:
    """One closed position, for a human (spec §11)."""
    lines = [
        f"## {entry.symbol} {entry.list_name} #{entry.id} ({entry.track}, {entry.universe}, "
        f"{entry.ruleset_version}) signal {entry.signal_date}, entered {entry.entry_date} at "
        f"{entry.entry_price}",
        f"   fair value then {entry.fair_value} (margin of safety {_pct(entry.margin_of_safety)}),"
        f" now {fair_value_now}",
    ]
    for leg in sorted(legs, key=lambda g: g.policy):
        mine = [e for e in events if e.policy == leg.policy]
        story = "; ".join(
            f"{e.day} {e.kind}"
            + (f" {e.fraction:.0%} @ {e.price:.2f}" if e.kind == "fill" and e.price else "")
            for e in mine
        )
        lines.append(
            f"   {leg.policy}: exit {leg.exit_date} return {_pct(leg.ret)} (SPY {_pct(leg.spy_ret)})"
            f", max DD {_pct(leg.max_drawdown)}: {story or 'no events'}"
        )
    marks = " · ".join(
        f"{h}: {_pct(entry.returns.get(h))} (SPY {_pct(entry.spy.get(h))})" for h in HORIZONS
    )
    lines.append(f"   horizons {marks}")
    if entry.scorecard_json:
        card = ValueScorecard.model_validate_json(entry.scorecard_json)
        c = closest_gate(card, entry.list_name)
        lines.append(
            "   closest to wrong: none measurable"
            if c is None
            else f"   closest to wrong: {c.id} {c.actual:.2f} vs bar {c.threshold:.2f}"
        )
    return lines


def render(
    entries: list[EntryView],
    legs: list[LegView],
    events: list[EventView],
    ranked: list[RankedView],
    *,
    fair_values_now: dict[tuple[str, str], float | None],
    live_policy: str,
    track: str,
    postmortems: bool,
) -> str:
    versions = sorted({e.ruleset_version for e in entries})
    lines = [
        f"== Value book shadow record: {len(entries)} entries, ruleset(s) {', '.join(versions) or 'n/a'} ==",
        SURVIVORSHIP,
        go_live_line(entries, track),
        "",
        *horizon_section(entries),
        "",
        *policy_section(entries, legs, live_policy),
        "",
        *ranked_section(ranked),
    ]
    if postmortems:
        lines += ["", "-- Postmortems (closed positions) --"]
        closed = [e for e in entries if e.kind == "ready" and e.status == "closed"]
        for e in closed:
            lines += postmortem(
                e,
                [g for g in legs if g.shadow_id == e.id],
                [v for v in events if v.shadow_id == e.id],
                fair_values_now.get((e.symbol, e.list_name)),
            )
        if not closed:
            lines.append("  none closed yet")
    return "\n".join(lines)
```

- [ ] **Step 4: The script** — `scripts/value_report.py`:

```python
"""The value book's shadow record, printed for a human (spec §6.8, §7, §11, §12).

    python -m scripts.value_report [--track baseline] [--universe all|trading|evidence]
        [--ruleset VERSION] [--postmortems]

Reads data/value.db (select only; on a new install it first creates the empty tables) and
prints: the survivorship caveat, the
go-live line of spec §12, fixed-horizon returns against SPY with errors clustered by entry date,
the three exit policies side by side, the ranked monthly record and, with ``--postmortems``, one
postmortem per closed position. No IBKR connection, no network.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from src.common.config import get_config
from src.value.report import HORIZONS, EntryView, EventView, LegView, RankedView, render
from src.value.store import (
    ValueRankedRow,
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
    ValueTickerFileRow,
    init_value_db,
    value_session,
)


def load(args: argparse.Namespace) -> str:
    vcfg = get_config().value
    init_value_db()
    with value_session() as s:
        q = select(ValueShadowRow).where(ValueShadowRow.track == args.track)
        if args.universe != "all":
            q = q.where(ValueShadowRow.universe == args.universe)
        if args.ruleset:
            q = q.where(ValueShadowRow.ruleset_version == args.ruleset)
        entries = [
            EntryView(
                id=r.id,
                track=r.track,
                kind=r.kind,
                list_name=r.list_name,
                symbol=r.symbol,
                universe=r.universe,
                status=r.status,
                signal_date=r.signal_date,
                entry_date=r.entry_date,
                entry_price=r.entry_price,
                fair_value=r.fair_value,
                margin_of_safety=r.margin_of_safety,
                ruleset_version=r.ruleset_version,
                returns={h: getattr(r, f"ret_{h}") for h in HORIZONS},
                spy={h: getattr(r, f"spy_{h}") for h in HORIZONS},
                scorecard_json=r.scorecard_json if r.kind == "ready" else "",
            )
            for r in s.scalars(q.order_by(ValueShadowRow.id))
        ]
        ids = {e.id for e in entries}
        legs = [
            LegView(
                shadow_id=g.shadow_id,
                policy=g.policy,
                closed=g.closed,
                exit_date=g.exit_date,
                ret=g.ret_exit,
                spy_ret=g.spy_ret_exit,
                max_drawdown=g.max_drawdown,
                sessions=g.sessions,
                sells=g.sells,
            )
            for g in s.scalars(select(ValueShadowLegRow))
            if g.shadow_id in ids
        ]
        events = [
            EventView(
                shadow_id=v.shadow_id,
                policy=v.policy,
                day=v.day,
                kind=v.kind,
                price=v.price,
                fraction=v.fraction,
                detail=v.detail,
            )
            for v in s.scalars(select(ValueShadowEventRow).order_by(ValueShadowEventRow.id))
            if args.postmortems and v.shadow_id in ids
        ]
        ranked = [
            RankedView(
                formed_on=r.formed_on,
                list_name=r.list_name,
                bucket=r.bucket,
                n=r.n,
                closed_on=r.closed_on,
                ret=r.ret,
                spy_ret=r.spy_ret,
                missing=r.missing,
            )
            for r in s.scalars(select(ValueRankedRow).order_by(ValueRankedRow.formed_on))
            if not args.ruleset or r.ruleset_version == args.ruleset
        ]
        now: dict[tuple[str, str], float | None] = {}
        for f in s.scalars(select(ValueTickerFileRow)):
            now[(f.symbol, "deep_value")] = f.fair_value_deep
            now[(f.symbol, "quality_growth")] = f.fair_value_growth
    return render(
        entries,
        legs,
        events,
        ranked,
        fair_values_now=now,
        live_policy=vcfg.rules.exits.live_policy,
        track=args.track,
        postmortems=args.postmortems,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The value book's shadow record (spec §6.8)")
    parser.add_argument("--track", default="baseline", choices=("baseline", "claude"))
    parser.add_argument("--universe", default="all", choices=("all", "trading", "evidence"))
    parser.add_argument("--ruleset", default=None, help="only this ruleset version")
    parser.add_argument("--postmortems", action="store_true")
    args = parser.parse_args(argv)
    print(load(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the tests**

  Run: `.venv/bin/python -m pytest -q tests/test_value_report.py tests/test_value_shadow.py tests/test_value_fence.py`
  Expected: PASS (`test_value_report.py` 7). Ruff check/format, `.venv/bin/mypy src/value/report.py
  scripts/value_report.py` clean; `.venv/bin/python -m py_compile scripts/value_report.py` silent.

- [ ] **Step 6: Commit**

  ```bash
  git add src/value/report.py scripts/value_report.py tests/test_value_report.py docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "feat(value): scripts/value_report.py - the shadow record and its postmortems"
  ```

---

### Task 11: Docs

**Files:** `ARCHITECTURE.md`, `SETUP.md`, `STATUS.md`, `CLAUDE.md` (the mandatory doc-update
table: new modules under `src/value/` → ARCHITECTURE folder guide and CLAUDE value fence; new
config keys → the committed example (Task 1), ARCHITECTURE `config/`, SETUP §19; new script
entrypoints → SETUP scripts table and ARCHITECTURE `scripts/`; a new process → ARCHITECTURE's
process table and SETUP's launcher paragraph; a feature built → STATUS). `README.md`,
`docs/web/commands.md`, `docs/web/api.md`, `How the scan works.md`, `UNIVERSE_RESEARCH.md` and the
`.opencode/` files are unchanged (no top-level directory, Telegram command, command kind, route,
scan-loop or universe change; no fence restated there) — record that as a ruling.

- [ ] **Step 1: ARCHITECTURE.md** — apply:

```diff
diff --git a/ARCHITECTURE.md b/ARCHITECTURE.md
--- a/ARCHITECTURE.md
+++ b/ARCHITECTURE.md
@@ -585,5 +585,5 @@ what ships) and given a code default. The table below names the files by their p
 | `news.yaml` (private) / `examples/news.yaml` (committed) | **The News thread** (docs/superpowers/specs/2026-10-09-news-thread-design.md, SETUP.md §17), typed as `NewsCfg` in `src/common/config.py`. `enabled` (ships `true`; the service idles when false), `db_url` (`data/news.db`), `charts_dir`, `retention_days` (30), per-category `lookback_hours`, `source_rank` (preferred outlets for a card's primary link), tape symbol lists; `sources` (RSS feed list with a category each, Google News macro queries, poll cadences, the Nasdaq date-key offsets `nasdaq_econ_date_offset_days` (1, re-derived by `scripts.news_probe`) / `nasdaq_earnings_date_offset_days`, `finnhub_per_minute`); `cluster` (Jaccard `similarity` 0.5 within `window_hours` 48, on title tokens minus template words); `tagging` (rumor / forward-looking term lists, topic keyword lists, manual ticker `aliases`, `noise_terms` — law-firm class-action solicitations kept out of ticker cards, writer headlines and digests); `alerts` (`macro_max_late_minutes` 180 — a print first seen later than that after release is not alerted, index levels, VIX jump/levels, held/universe σ thresholds, breaking-news `geo_min_sources`/`geo_reaction_pct`/`geo_reaction_window_min`/`geo_topics`, `max_per_hour` 6, `max_edits` 3); `reaction` (`window_min` 15, `max_wait_min` 35, RTH and extended-hours instrument maps); `quiet_hours` (Asia/Singapore 00:00–07:00, validated tz and HH:MM); `digests` (ET times, validated; `max_late_minutes` 120 — a digest missed by more than that while the service was down is skipped, not posted stale); `llm` (`backend` `cli`/`ollama`/`cli_then_ollama`, `model`, `ollama_model`, `timeout_seconds`, `max_calls_per_day` 44, `reserved_for_picture` 10 — see the market-picture keys below); `sentiment` (`model` `vader`/`finbert`, `lookback_hours`, `half_life_hours`); `grounding.rel_tol`; `flags` thresholds; `briefs` (`poll_seconds`, `dedupe_minutes`). **Market picture build (2026-10-22), keys with code defaults (a private `news.yaml` needs `llm.max_calls_per_day: 44` if it spells out its `llm:` line, since a file that says 40 keeps 40; the `dossier:`, `triage:` and `picture:` blocks have code defaults identical to the example, so copying them is for visibility and tuning):** `llm.reserved_for_picture` (10) keeps that many of the day's calls for triage and picture builds: general calls (card writer, digests, briefs) stop at `max_calls_per_day - reserved_for_picture - dossier.max_calls_per_day` (30 of 44 at the shipped values; never below one a day); `triage` (`enabled`, `batch_size` 40, `rth_batch_times` 10:30 / 12:30 / 14:30 ET, and the noise-check keys `promote_index_move_pct` 1.0, `promote_ticker_residual_pct` 3.0, `promote_window_min` 60, `max_promotions_per_hour` 2); `picture` (`enabled`, `max_rebuilds_per_day` 4, `max_stories` 5, `story_window_days` 7, `story_min_new_clusters` 2, `story_match_jaccard` 0.3, `staleness_hours` 26); `dossier` (`enabled`, `batch_size` 6 names per call, `max_calls_per_day` 4, `facts_refresh_min` 60, `prose_min_interval_hours` 6, `profile_days` 7, `story_window_days` 7, `max_event_days` 45, `staleness_hours` 26, `max_names_in_review` 8, `keep_days` 30, `health` with the debt-to-equity bands `de_strong` 100 and `de_weak` 200 in yfinance's percent unit). A disabled dossier hands its four calls back to the general budget. Nothing in it reaches the risk engine, scoring or sizing. **Research touches (2026-10-27):** `dossier.touch_enabled` (true), `dossier.researched_min_interval_min` (180), `dossier.touch_keep_days` (3) and `picture.touch_min_age_min` (90) — a /scan or a Claude review of a name makes its dossier due early (and the picture, once old enough), still under the daily caps. |
 | `news_playbook.yaml` (committed reference data) | The 📘 playbook: per US release (FOMC, CPI, core CPI, NFP, core PCE, PCE, unemployment, average hourly earnings, PPI, GDP, retail sales, ISM, claims, JOLTS, UoM) its title `aliases`, `tolerance` for in-line, `inverse` (a lower print is "hot"), and the textbook first-reaction direction of stocks/bonds/dollar/gold/oil/vol on a hot and on a cold print, with a one-line rationale each. Loaded by `src/news/playbook.py`; not operator tuning, so not private. |
-| `value.yaml` | The value book (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`). The `rules:` block (data quality, the classification lists, the health thresholds for operating companies, cyclicals, banks and insurers, valuation rates, the quality-growth entry rule, the margin of safety by regime, timing) is hashed into the ruleset fingerprint beside `ruleset_version`; changing a rule after the freeze is a version bump. Also the universe snapshots, the ticker-file history bands and `research_sweep.enabled` (the research worker's nightly value sweep, off until Part 2). Every model forbids unknown keys. |
+| `value.yaml` | The value book (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`). The `rules:` block (data quality, the classification lists, the health thresholds for operating companies, cyclicals, banks and insurers, valuation rates, the quality-growth entry rule, the margin of safety by regime, timing) is hashed into the ruleset fingerprint beside `ruleset_version`; changing a rule after the freeze is a version bump. Since v2 the `rules:` block also holds `exits` (the three exit policies' thresholds and the pre-registered `live_policy`). Also the universe snapshots, the ticker-file history bands, `research_sweep.enabled` (the research worker's nightly value sweep: filings, and every name's bars plus SPY's each session; on since Part 2) and `service` (the value process: run hour, poll interval, yfinance workers, the filings-coverage gate). Every model forbids unknown keys. |
 | `value_universe.csv` / `value_evidence_universe.csv` | Committed snapshots of the S&P 100 (the value book's trading universe, with `universe.yaml`'s `would_own` + `watchlist`) and the S&P 500 (its evidence universe): symbol, name, GICS sector and sub-industry, CIK, with the as-of date on line 1. Rebuilt by `python -m scripts.value_universe_snapshot`. |
 | `symbol_directory_overrides.yaml` | **2026-09-13.** A hand-maintained `overrides:` list of `{symbol, name, exchange, is_etf}` for tickers SEC EDGAR's directory omits entirely — verified directly against both `company_tickers.json` and `company_tickers_exchange.json`, neither lists `TQQQ`/`SOXL`/`UPRO` (share classes of a shared trust CIK, not individually-registered filers), which is why the web research console's `GET /research/search` couldn't find them despite all three being part of the live scan universe (`universe.yaml → leveraged_etfs`). No `cik` field — there isn't one to give them. Loaded by `src/research/ingest/symbols.py::refresh_symbol_directory`, which seeds a row only when the symbol has no directory row yet (never overwrites EDGAR-sourced data). Read directly with `yaml.safe_load`, not through `get_config()` — it's a data supplement, not a tunable. |
@@ -1034,6 +1034,6 @@ outstanding).
 | `schemas.py` (market picture build, 2026-10-22) | The schemas added by the market picture build: `MarketRegime` (normal / cautious / stressed / crisis: not the per-ticker `Regime`), `RegimeInputs`, `IndexRegime`, `RegimeChange` and `RegimeState` (the persisted regime); `ScaleInZone`, `SizingNote` (how the regime, the leveraged ceiling, the ladder and Claude's cut shaped one CSP: `pre_regime_contracts`, `regime`, `per_trade_cap`, `leverage_tier`, `ceiling_kind`, `floor_lot`, `scale_in`, `bottoming` (`market` or `name`), `vrp_waived`, `claude_suggested` / `claude_reason`) and `SizingContext` (everything the sizer and the gate read), with `TradeCandidate.sizing` and `TradeCandidate.cc_breakout` (`CcBreakout`); `ClaudeReview.max_contracts` / `size_reason` / `backend`; and the news-written `MarketPicture` family (`PictureFact`, `SeasonalityView`, `PictureStory`, `NoiseSummary`, `PictureRegime`) and `TickerDossier` (with `DossierFact`, `DossierEvent` and `DossierReported`). |
 | `config.py` (market picture build, 2026-10-22) | The config classes added by the market picture build: `RegimeCfg` (with `RegimeCspCfg`, `RegimeThresholdsCfg`, `RegimeIntradayCfg`, `RegimeLadderCfg` and `RegimeBottomingCfg`), `LeveragedSizingCfg`, `ClaudeCutCfg` and `CcTimingCfg` / `CcBreakoutCfg` (all `_KeyedCfg`: an unknown key raises) read through `get_regime_cfg()`, `get_leveraged_sizing_cfg()`, `get_claude_cut_cfg()` and `get_cc_timing_cfg()`; `NewsTriageCfg`, `NewsPictureCfg`, `NewsDossierCfg` (with `NewsDossierHealthCfg`) and `NewsLlmCfg.reserved_for_picture`, whose `max_calls_per_day` code default is now 44. |
-| `value_types.py` | The value book's plain input shapes (`ValueFinancials`, `PriceSeries`, `Classification`, `MarketFacts`, `ValueInputs`). Imports only pydantic, so the scorecard, the loader and (Part 6) the API share them. |
-| `value_inputs.py` | The value book's one read-only input loader: research.db opened `mode=ro` (the raw companyfacts payload through `select_periods(as_of=)` / `select_ttm`, daily bars), the regime through `load_regime_state`, fixed-window technicals through `src/analytics/technicals.py`, and `fetch_market_facts` (yfinance market cap, industry, next earnings, through `src/data`). Imports no enrichment and no `src.value`. |
+| `value_types.py` | The value book's plain input shapes (`ValueFinancials`, `PriceSeries`, `DayBar`, `Classification`, `MarketFacts`, `ValueInputs`). Imports only pydantic, so the scorecard, the loader and (Part 6) the API share them. |
+| `value_inputs.py` | The value book's one read-only input loader: research.db opened `mode=ro` (the raw companyfacts payload through `select_periods(as_of=)` / `select_ttm`, daily bars), the regime through `load_regime_state`, fixed-window technicals through `src/analytics/technicals.py`, and `fetch_market_facts` (yfinance market cap, industry, next earnings, through `src/data`). Part 2 adds `build_day_bars` (one session at a time with its technicals, for the exit engine), `newest_bar_before`, `closes_on`, `filings_coverage` and `symbol_is_etf`. Imports no enrichment and no `src.value`. |
 | `value_universe.py` | The value book's trading universe (`would_own` + `watchlist` + the S&P 100 snapshot) and evidence universe (the S&P 500 snapshot), share-class aliases mapped to one ticker. |
 
@@ -1218,6 +1218,6 @@ clientId.
 
 The value book (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`) scores healthy
-companies against what they are worth. **Part 1 (2026-10-29) is the scorecard only: nothing in
-it can place, size or gate an order.** `src/value/` is deterministic, imports no enrichment and
+companies against what they are worth. **Parts 1–2 (2026-10-29) are the scorecard and the
+shadow record: nothing in them can place, size or gate an order.** `src/value/` is deterministic, imports no enrichment and
 no other system, reads `src.research` only through `ingest/concepts.py` and `schemas.py`, and is
 the only writer of `data/value.db` (its own `ValueBase`). Enforced by `tests/test_value_fence.py`.
@@ -1233,8 +1233,18 @@ the only writer of `data/value.db` (its own `ValueBase`). Enforced by `tests/tes
 | `timing.py` | The earnings window, deep value's strict timing, quality growth's soft timing. |
 | `rank.py` | The cross-sectional rank score per list, the filed list, the run's relative-strength line. |
-| `store.py` | `value.db`: `value_ticker_files` (latest), `value_ticker_history` (append-only), `value_runs`; `record_run` is the one way the dry-run script logs a run. |
+| `store.py` | `value.db`: `value_ticker_files` (latest), `value_ticker_history` (append-only), `value_runs`; `record_run` is the one way a script logs a run. Part 2's shadow record: `value_shadow` (one hypothetical entry per READY signal or control-group name, with its 21/63/126-session returns against SPY), `value_shadow_legs` (one per entry and exit policy, the exit engine's state as JSON), `value_shadow_events` (every exit event and fill), `value_ranked` (the ranked monthly portfolios). |
 | `ticker_file.py` | Writes the latest row and history (a full row on any verdict, fair value, margin band or gate change; a compact row once a session); `is_fresh` compares fingerprints. |
 | `funnel.py` | The calibration dry run's pass funnel and per-name detail. |
-| `ruleset.py` | The ruleset fingerprint: `ruleset_version` + a hash of the `rules:` block; `FROZEN` pins a frozen version's hash. |
+| `ruleset.py` | The ruleset fingerprint: `ruleset_version` + a hash of the `rules:` block; `FROZEN` pins a frozen version's hash (v1: the entry rules; v2: v1 + `rules.exits`). |
+| `exits.py` | The exit engine (spec §7), pure: one `LegState` per policy (`full`, `value` — the pre-registered live policy — and `hold12`), stepped once a session on the close; a sale fills at the next open. Every exit that would send reads Python's fair value; the half-sale reads the effective one; an exit only the effective (Claude) value would fire is a `proposal`. Fair value is re-marked only on a new accession. |
+| `ranked.py` | The ranked monthly record's arithmetic, pure: the top and bottom tenth and the whole list, equal-weight returns with dropped members counted, the first-run-of-the-month formation. |
+| `shadow.py` | The shadow record (spec §6.8, §12): READY entries and control groups at the next session's open, the three legs, fixed-horizon returns against SPY from the bars as they stand, `rebase_needed` when a split moves the entry bar, the ranked record's formation and close. Writes `value.db`; reads `research.db` through `value_inputs`. Baseline track only until Part 4. |
+| `service.py` | The value process's nightly run: `plan_run` (a settled SPY session not yet scored, after `service.run_hour_et`, once the sweep has filings for `min_filings_coverage_pct` of the universe), `run_nightly` (score both universes, the followed names and every shadow name; persist the ticker files with a session history row; run the shadow record; log `value_runs`, all in one transaction), `startup_check`. |
+| `report.py` | The report, pure: fixed-horizon returns with errors clustered by entry date, the go-live line (spec §12), the three policies side by side, the ranked record, and a postmortem per closed position with the gate closest to wrong (spec §11). |
+
+**The value process** (`scripts/run_value.py`, Part 2) holds no IBKR connection and no clientId: it
+polls `service.plan_run`, gathers what `src/value/` may not fetch through `scripts/value_feed.py`
+(earnings dates from `news.db`, read-only; yfinance market facts) and calls `run_nightly`. It
+sends no message (Telegram is Part 6) and idles if the frozen ruleset no longer matches the config.
 
 Inputs come from `src/common/value_inputs.py` (read-only) in the plain shapes of
@@ -1557,5 +1567,5 @@ plus `logs`/`watchdog`/`autonomy`); see the `launchd.py` row below and `SETUP.md
 | `spreads_resolve.py` | `python -m scripts.spreads_resolve --spread-id ID --debit D [--contracts N] [--commission C]` | Settles an open or expiring spread by hand in `data/spreads.db` (`exit_reason = resolved_by_hand`) — for a spread the service can no longer close: it expired while still open, or the broker no longer holds it (a close that filled while the Gateway was down). Look the real price up in TWS or the trade ledger first. The one write the operator makes to the spreads DB |
 | `spreads_backtest.py` | `python -m scripts.spreads_backtest --start YYYY-MM-DD --end YYYY-MM-DD [--csv path] [--profit-take PCT] [--trigger move\|always] [--negative-gamma allow\|skip]` | Replays the spreads rules over ThetaData history (the Theta Terminal must be running; day files are cached in `data/spreads_bt/`) and prints the same report in SPY-equivalent dollars, plus the start-to-end capital. The flags override one setting per run so two runs compare |
-| `start.py` | `python -m scripts.start` | **Single-command launcher**: starts every always-on Python service — approval service, intraday monitor, web API, research worker, daily credit-spread service — as supervised subprocesses with auto-restart on crash, **and schedules the EOD report itself** — at `scheduler.eod_report` (default 16:15 ET) on NYSE trading days it spawns a one-shot `scripts.run_eod` subprocess (no cron job needed). The API and research worker hold no `ib_async` connection or clientId, so adding them to the same supervised pool doesn't touch the one-clientId-per-process invariant. The one thing it does not start is the Next.js frontend (`cd web && npm run dev`) — a Node process, not a Python script. The last-run date is persisted to `data/eod_scheduler_state.json` so a restart after the report has already run does not re-fire it; a start *after* the EOD time on a trading day that has not yet run fires immediately (catch-up). The launcher process holds **no** `ib_async` loop — the EOD job runs in its own subprocess with its own client ID, preserving the "no threaded scheduler inside an ib_async loop" invariant. **`_supervise_eod`/`_eod_tick` (Task 4b, 2026-09-29):** a running EOD is bounded by `scheduler.eod_timeout_minutes` (default 60) — a run still alive past that many minutes is SIGTERMed then SIGKILLed after `STOP_GRACE_SECONDS`, and an ERROR is logged (`"EOD exceeded %d min — killed"`). Before this fix the launcher only ever spawned a new EOD once `eod_proc.poll()` was not `None`, so one hung run (e.g. the account-summary fetch looping through an IBKR 1100/1102 connectivity flap — see the `eod_report.py` row above) blocked every later EOD forever (2026-09-29 evidence: a run was still alive >11h after it started). `_eod_tick` composes the supervision + kill decision with `_eod_should_fire` in one per-iteration step, so a kill frees the slot in the same tick a due run can fire in. Accepts `--no-monitor` / `--no-approval` / `--no-api` / `--no-research` / `--no-spreads` / `--no-eod` flags — the stale-process sweep below terminates any leftover instance of a skipped service too, so a service you started separately with `--no-x` will be killed on the next unqualified `scripts.start`. **The sweep never kills its own ancestors or any `caffeinate` process (C1, 2026-09-30):** `_find_stale_pids` reads `ps -eo pid,ppid,command`, walks the ancestry from `os.getppid()`, and skips any command line whose argv[0] basename is `caffeinate` — under launchd the job is `caffeinate -i -s <python> -m scripts.start`, whose own command line contains `scripts.start`, so before this fix every launchd start killed its own caffeinate wrapper and sleep prevention was silently off. On launch, when `claude.backend` uses Ollama, runs `probe_ollama()` and logs a loud WARNING if the local model is unreachable/unpulled — daemons still start (fail-soft: deterministic list, no LLM enrichment), so it never blocks startup. Before launching daemons it pauses `STARTUP_GRACE_SECONDS` (default 4s, `0` disables) so a fast restart gives IB Gateway time to release the prior session's client IDs (avoiding the `Error 326` collision; `connect_with_retry` is the backstop if it still races). **News thread:** also supervises `news_service` (`scripts.run_news`, log `logs/news.log`); `--no-news` skips it. |
+| `start.py` | `python -m scripts.start` | **Single-command launcher**: starts every always-on Python service — approval service, intraday monitor, web API, research worker, daily credit-spread service — as supervised subprocesses with auto-restart on crash, **and schedules the EOD report itself** — at `scheduler.eod_report` (default 16:15 ET) on NYSE trading days it spawns a one-shot `scripts.run_eod` subprocess (no cron job needed). The API and research worker hold no `ib_async` connection or clientId, so adding them to the same supervised pool doesn't touch the one-clientId-per-process invariant. The one thing it does not start is the Next.js frontend (`cd web && npm run dev`) — a Node process, not a Python script. The last-run date is persisted to `data/eod_scheduler_state.json` so a restart after the report has already run does not re-fire it; a start *after* the EOD time on a trading day that has not yet run fires immediately (catch-up). The launcher process holds **no** `ib_async` loop — the EOD job runs in its own subprocess with its own client ID, preserving the "no threaded scheduler inside an ib_async loop" invariant. **`_supervise_eod`/`_eod_tick` (Task 4b, 2026-09-29):** a running EOD is bounded by `scheduler.eod_timeout_minutes` (default 60) — a run still alive past that many minutes is SIGTERMed then SIGKILLed after `STOP_GRACE_SECONDS`, and an ERROR is logged (`"EOD exceeded %d min — killed"`). Before this fix the launcher only ever spawned a new EOD once `eod_proc.poll()` was not `None`, so one hung run (e.g. the account-summary fetch looping through an IBKR 1100/1102 connectivity flap — see the `eod_report.py` row above) blocked every later EOD forever (2026-09-29 evidence: a run was still alive >11h after it started). `_eod_tick` composes the supervision + kill decision with `_eod_should_fire` in one per-iteration step, so a kill frees the slot in the same tick a due run can fire in. Accepts `--no-monitor` / `--no-approval` / `--no-api` / `--no-research` / `--no-spreads` / `--no-eod` flags — the stale-process sweep below terminates any leftover instance of a skipped service too, so a service you started separately with `--no-x` will be killed on the next unqualified `scripts.start`. **The sweep never kills its own ancestors or any `caffeinate` process (C1, 2026-09-30):** `_find_stale_pids` reads `ps -eo pid,ppid,command`, walks the ancestry from `os.getppid()`, and skips any command line whose argv[0] basename is `caffeinate` — under launchd the job is `caffeinate -i -s <python> -m scripts.start`, whose own command line contains `scripts.start`, so before this fix every launchd start killed its own caffeinate wrapper and sleep prevention was silently off. On launch, when `claude.backend` uses Ollama, runs `probe_ollama()` and logs a loud WARNING if the local model is unreachable/unpulled — daemons still start (fail-soft: deterministic list, no LLM enrichment), so it never blocks startup. Before launching daemons it pauses `STARTUP_GRACE_SECONDS` (default 4s, `0` disables) so a fast restart gives IB Gateway time to release the prior session's client IDs (avoiding the `Error 326` collision; `connect_with_retry` is the backstop if it still races). **News thread:** also supervises `news_service` (`scripts.run_news`, log `logs/news.log`); `--no-news` skips it. **Value book:** also supervises `value_service` (`scripts.run_value`, log `logs/value.log`); `--no-value` skips it. |
 | `run_eod.py` | `python -m scripts.run_eod` | Runs the EOD report (normally spawned automatically by `scripts.start`'s scheduler; can also be run by hand) |
 | `run_approval_service.py` | `python -m scripts.run_approval_service` | Starts the long-running approval + execution daemon |
@@ -1583,4 +1593,7 @@ plus `logs`/`watchdog`/`autonomy`); see the `launchd.py` row below and `SETUP.md
 | `value_dry_run.py` | `python -m scripts.value_dry_run backfill\|run [...]` | The value book's calibration dry run (spec §17). `backfill` drains the research worker's own jobs for both universes in-process; `run` scores every name read-only, ranks both lists, writes the ticker files to `value.db` and prints the pass funnel, GOOGL/META/BAC/MU with every number, storage and run time. No IBKR, no Telegram. Run on database copies (`SETUP.md` §19). |
 | `value_universe_snapshot.py` | `python -m scripts.value_universe_snapshot` | Rebuilds `config/value_universe.csv` (S&P 100) and `config/value_evidence_universe.csv` (S&P 500) from Wikipedia's MediaWiki API. Review the diff before committing. |
+| `run_value.py` | `python -m scripts.run_value` | The value book's process (Part 2): no IBKR, no clientId, supervised by `scripts.start` (`value_service`, `logs/value.log`, `--no-value`). Each poll asks `src.value.service.plan_run` whether a settled session waits; runs the night with `scripts/value_feed.py`'s plain data. Never imported (it starts a service): checked with `py_compile`; the only future importer of `src.value_ai`. |
+| `value_feed.py` | (imported by `run_value.py`) | The plain data `src/value/` may not fetch: `earnings_dates` from `news.db` (read-only) and `market_facts` from yfinance. |
+| `value_report.py` | `python -m scripts.value_report [--track baseline] [--universe all\|trading\|evidence] [--ruleset V] [--postmortems]` | Prints the shadow record: the survivorship caveat, the go-live line, fixed-horizon returns with clustered errors, the three exit policies, the ranked record and per-position postmortems. Reads `value.db` only. |
 
 ---
@@ -1610,4 +1623,5 @@ processes that run at the same time.**
 | `spreads_service` | Always-on daemon (supervised by `scripts.start`; `--no-spreads` skips it) | 30 (`spreads`) | The daily credit-spread system (`scripts.run_spreads`). It shares the Gateway with the wheel daemons and holds at most 30 market-data lines. It places orders only in `mode: paper`. If the Gateway restarts (`src/ops/gateway_control.py`), it reconnects and re-reconciles before entering again |
 | `news_service` | Always-on daemon (supervised by `scripts.start`; `--no-news` skips it; idles unless `news.enabled`) | — (no IBKR) | The News thread (`scripts.run_news`): polls news/calendar sources into `data/news.db`, posts digests, alerts and briefs to `TELEGRAM_THREAD_NEWS`. Prices come from yfinance; positions from the newest `PortfolioSnapshotRow` Since 2026-10-22 it also keeps the market picture and a dossier per name in `data/news.db` (triage, picture, noise-check and dossier loops); it reads the trading process's regime record read-only and never writes it. |
+| `value_service` | Always-on daemon (supervised by `scripts.start`; `--no-value` skips it) | — (no IBKR until Stage 3's 31) | The value book (`scripts.run_value`): once a session has settled, scores both universes, writes the ticker files and runs the shadow record in `data/value.db`. Reads `research.db` and `news.db` read-only; sends nothing. |
 | `healthcheck` | Manual | 19 | Connection check / account print |
 | `trading_skills` MCP | Inside `claude -p` (opt-in) | 20 | Ad-hoc Claude lookups (see `STATUS.md`) |
@@ -1740,5 +1754,6 @@ Telegram renderer and the web page draw from.
 12. **The value fence.** `src/value/` is deterministic: it imports no enrichment, no other system
     and no trading-path module, nothing on the trading path imports it, and it is the only writer
-    of `data/value.db`. Its scorecard is a pure function. Part 1 places no order. Enforced by
+    of `data/value.db`. Its scorecard and exit engine are pure functions. Parts 1–2 place no
+    order and the value process holds no IBKR connection. Enforced by
     `tests/test_value_fence.py`.
 
```

- [ ] **Step 2: SETUP.md** — apply:

```diff
diff --git a/SETUP.md b/SETUP.md
--- a/SETUP.md
+++ b/SETUP.md
@@ -636,9 +636,10 @@ python -m scripts.start
 
 Logs are written to `logs/approval.log`, `logs/monitor.log`, `logs/api.log`,
-`logs/research.log`, `logs/spreads.log` and `logs/news.log`. Stop with Ctrl-C (only when run in a
+`logs/research.log`, `logs/spreads.log`, `logs/news.log` and `logs/value.log`. Stop with Ctrl-C (only when run in a
 terminal; under `./ibkr`, use `./ibkr stop`). Flags: `--no-monitor`, `--no-approval`, `--no-api`,
-`--no-research`, `--no-spreads`, `--no-news`, each skipping one service (`--no-eod` skips the
+`--no-research`, `--no-spreads`, `--no-news`, `--no-value`, each skipping one service (`--no-eod` skips the
 built-in EOD scheduler — see §7). The news service (§17) holds no IBKR connection and starts by
-default; set `enabled: false` in `config/news.yaml` (it then idles) or pass `--no-news`.
+default; set `enabled: false` in `config/news.yaml` (it then idles) or pass `--no-news`. The value
+service (§19) holds no IBKR connection either and scores once a night; `--no-value` skips it.
 
 > The web API and research worker need the `web` extra (`pip install -e ".[web,dev]"`, §6a)
@@ -2031,13 +2032,14 @@ that survived checking.
 ---
 
-## 19. The value book, Part 1: the scorecard and the calibration dry run
+## 19. The value book, Parts 1–2: the scorecard, the nightly process and the shadow record
 
 The value book scores healthy companies against what they are worth
 (`docs/superpowers/specs/2026-10-28-value-swing-book-design.md`). Part 1 is the scorecard and
-a one-off **calibration dry run**: it places no order, sends no message and runs no daemon.
+a one-off **calibration dry run**; Part 2 adds a nightly process and the **shadow record**. Neither
+places an order or sends a message.
 
 1. `cp config/examples/value.yaml config/value.yaml` (git-ignored; every key has a code default).
-2. The research worker can refresh the value universes nightly (`research_sweep.enabled`), but
-   Part 1 ships it **off**: the dry run backfills a database copy itself.
+2. The research worker refreshes the value universes nightly (`research_sweep.enabled`, on since
+   Part 2; Part 1 shipped it off and the dry run backfilled a database copy itself).
 3. The dry run (normally run for you by the plan's orchestrator, on copies, from the branch's
    worktree): `python -m scripts.value_dry_run backfill --env-file .env` then
@@ -2045,6 +2047,20 @@ a one-off **calibration dry run**: it places no order, sends no message and runs
    fall at each gate per list, GOOGL, META, BAC and MU with every number, the raw companyfacts
    storage and the run time.
-4. `ruleset_version` is frozen at `v1` (`src/value/ruleset.py::FROZEN`); a rule change is a
-   version bump with a written reason.
+4. `ruleset_version` is frozen at `v2` (`src/value/ruleset.py::FROZEN`: v1 = the entry rules the
+   operator froze after the dry run, v2 = v1 + `rules.exits`); a rule change is a version bump with
+   a written reason. **After pulling Part 2, refresh the private copy before restarting:**
+   `cp config/examples/value.yaml config/value.yaml` (a private file still saying v1 makes the
+   value process idle with a CRITICAL line in `logs/value.log`).
+5. **The nightly process (Part 2).** `scripts.start` / `./ibkr restart` runs `value_service`
+   (`python -m scripts.run_value`; `--no-value` skips it). With `research_sweep.enabled: true` the
+   research worker fetches every value name's filings and bars at 02:00 ET (the first sweep stores
+   ~2 GB of raw companyfacts in `data/research.db`). From `service.run_hour_et` (06:00 ET) the value
+   process scores the newest settled session once — no night until the sweep has filings for 90% of
+   the universe — writes the ticker files and runs the **shadow record**: Python's READY verdicts
+   enter at the next session's open with control groups beside them, each READY entry is carried
+   under the three exit policies (`value` is the live one; `full` and `hold12` are diagnostics), and
+   returns are marked at 21, 63 and 126 sessions against SPY. Nothing is ever ordered.
+6. **Read the record:** `python -m scripts.value_report` (add `--postmortems` for one postmortem per
+   closed position). It proves nothing for months; spec §12 says what it can and cannot show.
 
 ### Scripts
@@ -2055,4 +2071,6 @@ a one-off **calibration dry run**: it places no order, sends no message and runs
 | `python -m scripts.value_dry_run run [--as-of DATE] [--names A,B] [--limit N] [--no-persist] [--out cards.json] [--report report.txt]` | Scores every name, ranks both lists, writes `data/value.db`, prints the funnel. |
 | `python -m scripts.value_universe_snapshot` | Rebuilds the two committed universe CSVs from Wikipedia. |
+| `python -m scripts.run_value` | The value process. Normally started by `scripts.start` / `./ibkr restart`; `--no-value` skips it. Logs to `logs/value.log` (`./ibkr logs value`). |
+| `python -m scripts.value_report [--track baseline] [--universe all\|trading\|evidence] [--ruleset V] [--postmortems]` | Prints the shadow record from `data/value.db` (read only). |
 
 ## Troubleshooting
```

- [ ] **Step 3: STATUS.md** — apply:

```diff
diff --git a/STATUS.md b/STATUS.md
--- a/STATUS.md
+++ b/STATUS.md
@@ -344,8 +344,29 @@ MCP so the headless `claude -p` subprocess can do ad-hoc lookups (`ib_portfolio`
 | **Trade ledger web dashboard** (`/ledger`, `/ledger/trades`, `/ledger/ticker/[symbol]`, `/ledger/import`) | **Built (Tasks 13-16 of docs/superpowers/plans/2026-10-05-trade-ledger.md, on `feat/trade-ledger`).** Overview (tiles, cumulative-P&L curve, monthly bars, ticker table), the filterable trades table with CSV export and a trade panel that edits annotations (`ledger_annotate`), the per-ticker drill-down (wheel cost-basis walk, lots, dividends, every trade) and the import page (CSV upload via `ledger_import`, feed status, corporate actions with a mark-reviewed button, import history). All reads go through `GET /ledger/*`; all writes through the command queue. See `web/CLAUDE.md`/`ARCHITECTURE.md` `web/`. |
 | **Trade ledger fence test** (`tests/test_web_fence.py::test_the_trading_path_never_imports_the_ledger`, `::test_the_ledger_never_imports_the_enrichment_layer`, `::test_only_the_ledger_package_writes_the_ledger_tables`) | **Built (Task 17 Step 1).** Asserts `engine/`/`execution/`/`strategies/` never import `src.ledger` or `trade_ledger`, `src/ledger/` imports nothing from `src.claude`, and only `src/ledger/` (plus the ORM definitions in `models.py`) constructs the six ledger-table rows. `test_reporting_never_writes_anything` separately covers `trade_ledger.py`'s no-writes rule. |
-| **Value book Parts 2–6** | The value process and shadow record, re-evaluation and Stage 1b, Claude as the analyst, Stage 3 money (paper), web and Telegram — the roadmap in the Part 1 plan; each part is planned after the previous one merges. |
+| **Value book Parts 3–6** | Re-evaluation, shock stops, the corporate-action rebase and Stage 1b; Claude as the analyst (and the Claude track of the shadow record); Stage 3 money (paper); web and Telegram (with the follow window's `last_viewed_at`, digests, review cards and a watchdog check) — the roadmap in the Part 2 plan; each part is planned after the previous one merges. |
 
 ---
 
+## Built (2026-10-29 — value book Part 2: the value process and the shadow record)
+
+Plan: `docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md`. Deterministic only: no
+order, no Claude, no Telegram, no web, no IBKR connection.
+
+- `scripts/run_value.py` (`value_service`, supervised, `--no-value`), `scripts/value_feed.py`,
+  `src/value/service.py`: one transaction a night once a session has settled.
+- The shadow record (`src/value/shadow.py`, `exits.py`, `ranked.py`; four `value.db` tables):
+  baseline READY entries and control groups, the three exit policies, 21/63/126-session returns
+  against SPY, the ranked monthly record. `scripts/value_report.py` with postmortems.
+- `value_rules: v2` = v1's entry rules + `rules.exits`, frozen at `d07717fe5348`; `research_sweep`
+  on, now refreshing every name's bars and SPY's nightly. M5 fixed (unscored names are filed on no
+  list); M1–M4, M6–M8 still deferred (plan rulings 2 and 4).
+- Known limitations: the baseline track only (Claude's is Part 4); no shock stops, re-evaluations or
+  going-concern exit (Part 3); a split during a holding freezes the entry as `rebase_needed` until
+  Part 3's rebase; missed sessions are not back-filled (the next night scores the newest one; the
+  exit legs still step every bar); controls carry fixed-horizon returns only; the ranked record forms
+  on the first run of each month and its first period is partial; returns use yfinance bars with
+  their survivorship bias; nothing sets `last_viewed_at` until Part 6, so no name is followed yet;
+  the v1 fraction-valued keys stay fractions (M6).
+
 ## Built (2026-10-29 — value book Part 1: the scorecard and the calibration dry run)
 
```

- [ ] **Step 4: CLAUDE.md** — apply:

```diff
diff --git a/CLAUDE.md b/CLAUDE.md
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -391,6 +391,13 @@ the value book. It is **deterministic tier**:
 - Only `src/value/` constructs `data/value.db` rows (`ValueBase`); `scripts/` is scanned too, and the
   dry-run script logs its run through `src.value.store.record_run`.
-- Part 1 places, sizes and gates nothing. The written exception for Claude's value verdict
-  (spec §8.2, §18) is added with Part 4.
+- The value process (`scripts/run_value.py`, Part 2) holds no IBKR connection: it hands
+  `src/value/` earnings dates from `news.db` and yfinance market facts as plain data
+  (`scripts/value_feed.py`), so `src/value/` never imports `src.news` or `src.data`. It is the only
+  module that may import `src.value_ai` (Part 4), it is never imported itself, and its whole
+  process loads no wheel layer, no Claude and no `ib_async` (a `sys.modules` test).
+- The exit engine (`src/value/exits.py`) is pure; every exit that would send reads Python's fair
+  value, and an exit only Claude's value would fire is a tap proposal (spec §7, revision 3).
+- Parts 1–2 place, size and gate nothing: every shadow row is hypothetical. The written exception
+  for Claude's value verdict (spec §8.2, §18) is added with Part 4.
 
 Enforced by `tests/test_value_fence.py` — keep it green.
```

- [ ] **Step 5: The full gate** (Section exit) and a re-read of the trigger table in `CLAUDE.md`
  against `git diff --stat main...HEAD`: every row that matches has its doc edited.

- [ ] **Step 6: Commit, then the section's Progress-log commit**

  ```bash
  git add ARCHITECTURE.md SETUP.md STATUS.md CLAUDE.md docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "docs: value book Part 2 - the value process and the shadow record"
  ```

  Then Task 11's row, and one command each:

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-2-shadow-record.md
  git commit -m "docs(plan): value book Part 2 Progress log - Section D"
  ```

---

## Whole-branch review · model: opus · effort: high, then one sonnet fix pass · effort: high

- [ ] **R1.** Spawn one **opus** subagent with `effort: "high"`: "Review branch `feat/value-book-2`
  against `main` for correctness, using superpowers:requesting-code-review. Read the plan's
  Rulings, Global Constraints and Review Focus, the spec §§6.8, 6.9, 7, 11, 12, 16, and
  `git diff main...HEAD`. Check: the exit engine against §7 and rulings 13–16 transition by
  transition (the table in Task 4); that no automatic exit reads the effective fair value; the
  shadow record's entry, re-entry, control, horizon and close rules (rulings 10–13); the ranked
  record (ruling 17); that one night is one transaction and a failure leaves `value.db` unchanged;
  `plan_run`'s due logic (ruling 5) and the coverage gate (ruling 6); the fences (nothing on the
  trading path imports `src.value`; `src/value/` imports no enrichment; the process loads no wheel
  layer and no `ib_async`); unknown-never-zero; the v2 hash and that v2 changes no entry rule; the
  clustered standard error; the docs against the code. Report Critical / Important / Minor findings
  with file:line. Do not edit."
- [ ] **R2.** Record the findings in the Progress log. Spawn one **sonnet** subagent with
  `effort: "high"` to fix every Critical and Important finding in **one** commit
  (`fix(value): whole-branch review fixes`), TDD where a finding is a behaviour, with the full gate
  green. A fix that changes a key under `rules:` moves the v2 hash: it must re-run Task 1 Step 5,
  re-pin `FROZEN["v2"]` with the new value (v2 has produced no live row yet) and say so as a ruling.
  Minor findings are listed as deferred in the Progress log unless trivial.
- [ ] **R3.** Verify the fix commit yourself (log, status, full gate with pytest = baseline + 69 +
  the fix pass's new tests, protected diff, `py_compile` of the four scripts), then **ask the
  operator whether to merge `feat/value-book-2` into `main` and whether to push. Do neither without
  a yes.**

---

## Operator to-dos

**Before Part 2 starts (the orchestrator checks these at A0):**

0. Remove Part 1's worktree, which still holds ~2 GB of database copies (the 1.99 GB
   `research.db` among them): `git worktree remove --force .claude/worktrees/value-book-1` from the
   main checkout (and `git branch -d feat/value-book-1` once you no longer want the branch). Then
   `df -h .` should show at least 8 GiB free.

**After the merge, before the restart:**

1. Refresh the private config: `cp config/examples/value.yaml config/value.yaml`. A private file
   still saying `ruleset_version: v1` makes the value process idle with a CRITICAL line in
   `logs/value.log` (v1's pin no longer matches rules that include `exits`); one with
   `research_sweep.enabled: false` keeps the sweep off. If you had changed any key, re-apply it
   to the new copy (an entry-rule change is a new version: say so first).
2. Restart: `./ibkr restart` (daemons do not hot-reload). It starts `value_service` and restarts the
   research worker with the sweep on.

**The first nights:**

3. The 02:00 ET sweep queues ~1,000 jobs the first night (~2 GB of companyfacts into the live
   `data/research.db`; watch `df -h .`). Until it has filings for 90% of the universe,
   `./ibkr logs value` says "waiting for the research sweep"; then, from 06:00 ET, one line per
   night: `value nightly <session>: <N> names; {...}`.
4. Read the record when you like: `python -m scripts.value_report` (`--postmortems` once positions
   close). Expect "none marked yet" for a month: the first 21-session marks arrive about five weeks
   after the first READY entry, and the first ranked month closes at the start of next month.
5. Nothing sets `last_viewed_at` until Part 6, so no looked-up name is followed yet.

---

## Self-review (run by the plan's author, 2026-10-29)

- **Spec coverage (Part 2's scope).** §6.8 shadow ledger (READY entries at the next open, the
  baseline track, evidence-universe entries tagged, control groups, exit events, returns at
  21/63/126 and at exit against SPY, `value_report`) → Tasks 4, 6, 10; the ranked record → Tasks 5,
  6; the ruleset version → Task 1. §6.9 the follow window, session history rows, held and shadow
  names kept fresh → Task 7. §7 three policies, `value` pre-registered, `full`/`hold12` diagnostic,
  which fair value an exit reads, every `full` bullet but §7.1's → Task 4 (Claude's exit and review
  cards are Parts 4 and 6; ruling 19). §9.7 process bullets for Stages 1–2 → Tasks 7, 8. §11
  postmortem → Task 10. §12 fixed horizons, clustered errors, the go-live line → Tasks 6, 10 (Stage
  1b is Part 3). §16 fence, `sys.modules`, the exit state machine, the three policies on one entry,
  ranked portfolios (deciles, ties, excluded names), follow-window expiry, both shadow tracks (the
  baseline now; the Claude track's hook tested in Task 4) → Tasks 4–10. §18 docs → Task 11.
- **Placeholders.** None in Tasks 1–11: every module and test is given whole or as an exact diff and
  was run green — 5150 + 69 = 5219 passed and 1 skipped, `ruff check .` clean, `ruff format --check`
  clean on every touched file, `mypy src` clean (319 files) — on a code-only scratch copy of `main`
  at `23b1ef3` before this plan was written. The only value a run supplies is the commit count.
- **Type consistency.** `DayBar` (Task 2) is what `exits.step` (Task 4) and `shadow.load_bars`
  (Task 6) use; `LegState` is stored by Task 6 as JSON; `DayFacts` is built by `shadow.day_facts`;
  `HORIZONS` has one home (`report.py`, stubbed in Task 6, filled in Task 10); `RunPlan.tags` feeds
  `shadow.process(tags=…)` and `persist(universe=…)`; `filings_coverage` (Task 2) is what
  `plan_run` (Task 7) gates on; `ValueServiceCfg.min_filings_coverage_pct` is set in Task 1.
- **Review Focus.** Each of the five lines names the test that pins it, in the task that owns the
  code.
- **Proportion.** Complete code by the operator's brief (Sonnet executors with no room for doubt);
  the spec is cited, not restated. Modified files are given as exact diffs whose anchors the entry
  checks grep.
